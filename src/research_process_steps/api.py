"""Minimal FastAPI interface for deterministic repository experiments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from .conversations import ConversationVariant, load_conversations, save_conversation
from .paper_conversations import (
    PaperConversationVariant,
    add_paper_conversation,
    load_paper_conversations,
    update_paper_conversation,
)
from .reproducibility_prompts import reproducibility_prompts
from .analyzer import DEFAULT_CONTENT_LIMIT
from .batch import (
    ALLOWED_BATCH_SIZES,
    DEFAULT_DATASET,
    execute_repository_once,
    run_random_batch,
)
from .storage import (
    list_executions,
    load_result,
    load_result_by_id,
    save_result,
)
from .selected_repositories import load_selection, selected_repositories
from .publication_collection import (
    load_collection, collection_repositories, repository_identity,
    run_collection, run_collection_analytics,
)
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

COLLECTION_WORKER = ThreadPoolExecutor(max_workers=1)
COLLECTION_JOB_LOCK = Lock()
COLLECTION_JOBS: dict[str, dict[str, Any]] = {}


def collection_papers() -> list[dict[str, Any]]:
    papers = []
    for record in load_collection()["results"]:
        for source in record.get("related_to", []):
            papers.append({
                "paper_id": f"C{len(papers) + 1:04d}",
                "github_url": repository_identity(record["github_url"]),
                "title": source.get("title", ""),
                "doi": source.get("doi"), "paper_url": source.get("url", ""),
            })
    return papers


def paper_directory() -> Path:
    return Path(os.getenv("RPS_PAPERS_DIR", "data/selected_papers"))


def paper_path(paper_id: str) -> Path:
    allowed = {paper["paper_id"] for paper in load_selection()["papers"]}
    allowed.update(paper["paper_id"] for paper in collection_papers())
    if paper_id not in allowed:
        raise HTTPException(status_code=404, detail="Unknown selected paper.")
    return paper_directory() / f"{paper_id}.pdf"


def publication_paper(paper_id: str) -> dict[str, Any]:
    paper = next((item for item in collection_papers() if item["paper_id"] == paper_id), None)
    if paper is None:
        raise HTTPException(status_code=404, detail="Unknown publication-collection paper.")
    return paper


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/KnowledgeCaptureAndDiscovery/somef"])
    ref: str | None = None
    force: bool = Field(default=False, description="Rerun heuristics and replace the stored result.")
    max_content_bytes: int = Field(
        default=DEFAULT_CONTENT_LIMIT,
        ge=0,
        le=2_000_000,
        description="Maximum size of a file whose textual contents are inspected.",
    )


class RandomBatchRequest(BaseModel):
    count: int = Field(..., examples=[100])


app = FastAPI(
    title="Research Process Steps Heuristic API",
    description=(
        "Deterministic, no-AI API that maps files in a GitHub repository to "
        "research process steps and persistently stores every repository result."
    ),
    version="0.2.0",
)

WEB_DIR = Path(__file__).with_name("web")
BUNDLED_CACHE_DIR = Path(__file__).with_name("demo_cache")
CACHE_VERSION = "v2"
CACHE_DIR = Path(
    os.getenv(
        "RPS_CACHE_DIR",
        str(Path.home() / ".cache" / "research_process_steps"),
    )
)
DEMO_REPOSITORIES = {
    "somef": "https://github.com/KnowledgeCaptureAndDiscovery/somef",
    "widoco": "https://github.com/dgarijo/Widoco",
}
DEMO_REPOSITORY_URLS = {
    _url.rstrip("/").removesuffix(".git").lower()
    for _url in DEMO_REPOSITORIES.values()
}
BUNDLED_DEMO_FILES = {
    "https://github.com/knowledgecaptureanddiscovery/somef": "somef.json",
    "https://github.com/dgarijo/widoco": "widoco.json",
}


def _normalize_repo_url(repo_url: str) -> str:
    return repo_url.rstrip("/").removesuffix(".git").lower()


def _bundled_demo_path(request: AnalyzeRequest) -> Path | None:
    normalized = _normalize_repo_url(request.repo_url)
    filename = BUNDLED_DEMO_FILES.get(normalized)
    if (
        filename is None
        or request.ref is not None
        or request.max_content_bytes != DEFAULT_CONTENT_LIMIT
    ):
        return None
    return BUNDLED_CACHE_DIR / filename


def _demo_cache_path(request: AnalyzeRequest) -> Path | None:
    normalized = _normalize_repo_url(request.repo_url)
    if (
        normalized not in DEMO_REPOSITORY_URLS
        or request.ref is not None
        or request.max_content_bytes != DEFAULT_CONTENT_LIMIT
    ):
        return None

    key = hashlib.sha256(
        f"{CACHE_VERSION}|{normalized}".encode("utf-8")
    ).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def _load_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    payload["cache"] = {
        "hit": True,
        "persistent": True,
        "path": str(path),
    }
    return payload


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = dict(payload)
    cached["cache"] = {
        "hit": False,
        "persistent": True,
        "path": str(path),
    }
    path.write_text(
        json.dumps(cached, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "method": "deterministic_heuristics",
        "uses_ai": False,
        "dataset": str(DEFAULT_DATASET),
        "allowed_batch_sizes": sorted(ALLOWED_BATCH_SIZES),
    }


@app.get("/api/executed")
def executed_repositories() -> dict[str, Any]:
    executions = list_executions()
    for item in executions:
        item["conversations"] = load_conversations(item["repo_url"])
    return {"count": len(executions), "repositories": executions}


class ConversationLinkRequest(BaseModel):
    repo_url: str
    variant: ConversationVariant
    url: HttpUrl | None = None


@app.put("/api/conversations")
def update_conversation(request: ConversationLinkRequest) -> dict[str, Any]:
    try:
        repo_url = repository_identity(request.repo_url)
        save_conversation(repo_url, request.variant, str(request.url) if request.url else None)
        return {"repo_url": repo_url, "conversations": load_conversations(repo_url)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/selection")
def selection() -> dict[str, Any]:
    payload = load_selection()
    executions = {
        _normalize_repo_url(item["repo_url"]): item for item in list_executions()
    }
    payload["repositories"] = [
        {"repo_url": url, "execution": executions.get(_normalize_repo_url(url)), "conversations": load_conversations(url)}
        for url in selected_repositories()
    ]
    for paper in payload["papers"]:
        paper["pdf_url"] = (
            f"/api/selection/papers/{paper['paper_id']}"
            if paper_path(paper["paper_id"]).is_file() else None
        )
    return payload


@app.get("/api/publication-collection")
def publication_collection() -> dict[str, Any]:
    executions = {}
    for item in list_executions():
        try:
            executions[repository_identity(item["repo_url"])] = item
        except (ValueError, KeyError):
            continue
    papers = collection_papers()
    for paper in papers:
        paper["pdf_url"] = (
            f"/api/selection/papers/{paper['paper_id']}"
            if (paper_directory() / f"{paper['paper_id']}.pdf").is_file() else None
        )
        paper["reproducibility_conversations"] = load_paper_conversations(paper["paper_id"])
        paper["research_step_metadata_url"] = (
            f"/api/publication-collection/papers/{paper['paper_id']}/research-step-metadata"
            if load_result(paper["github_url"]) is not None else None
        )
    return {
        "papers": papers,
        "repositories": [
            {"repo_url": url, "execution": executions.get(url), "conversations": load_conversations(url)}
            for url in collection_repositories()
        ],
    }


class PaperConversationRequest(BaseModel):
    variant: PaperConversationVariant
    url: HttpUrl


@app.get("/api/reproducibility/prompts")
def get_reproducibility_prompts() -> dict[str, Any]:
    return {"prompts": reproducibility_prompts()}


@app.post("/api/publication-collection/papers/{paper_id}/conversations")
def add_reproducibility_conversation(
    paper_id: str,
    request: PaperConversationRequest,
) -> dict[str, Any]:
    publication_paper(paper_id)
    record = add_paper_conversation(paper_id, request.variant, str(request.url))
    return {
        "paper_id": paper_id,
        "variant": request.variant,
        "record": record,
        "conversations": load_paper_conversations(paper_id),
    }


@app.put("/api/publication-collection/papers/{paper_id}/conversations/{record_id}")
def overwrite_reproducibility_conversation(
    paper_id: str,
    record_id: str,
    request: PaperConversationRequest,
) -> dict[str, Any]:
    publication_paper(paper_id)
    try:
        record = update_paper_conversation(
            paper_id,
            request.variant,
            record_id,
            str(request.url),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation record not found.") from exc
    return {
        "paper_id": paper_id,
        "variant": request.variant,
        "record": record,
        "conversations": load_paper_conversations(paper_id),
    }


@app.get("/api/publication-collection/papers/{paper_id}/research-step-metadata")
def paper_research_step_metadata(paper_id: str) -> dict[str, Any]:
    paper = publication_paper(paper_id)
    result = load_result(paper["github_url"])
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No stored heuristic result exists for this repository.",
        )
    repository = result.get("repository", {})
    return {
        "schema_version": "1",
        "paper_id": paper_id,
        "repository": {
            "url": paper["github_url"],
            "ref": repository.get("ref"),
            "tree_sha": repository.get("commit_tree_sha"),
        },
        "files": [
            {
                "path": item.get("path"),
                "blob_sha": item.get("blob_sha"),
                "artifact_kind": item.get("artifact_kind"),
                "research_process_steps": item.get("steps", []),
                "evidence": item.get("evidence", []),
            }
            for item in result.get("files", [])
        ],
    }


class CollectionJobRequest(BaseModel):
    action: str = Field(pattern="^(heuristics|analytics|rerun_all)$")


def _execute_collection_job(job_id: str, action: str) -> None:
    def progress(item: dict[str, Any]) -> None:
        with COLLECTION_JOB_LOCK:
            COLLECTION_JOBS[job_id]["progress"] = item
    try:
        if action == "rerun_all":
            repositories = COLLECTION_JOBS[job_id]["repositories"]
            result = {"completed": [], "errors": []}
            for index, repo_url in enumerate(repositories, 1):
                progress({"index": index, "total": len(repositories), "repo_url": repo_url, "status": "rerunning"})
                try:
                    refreshed, _ = execute_repository_once(
                        repo_url, token=os.getenv("GITHUB_TOKEN"), force=True,
                    )
                    result["completed"].append({"repo_url": repo_url, "execution": refreshed.get("execution")})
                except Exception as exc:
                    result["errors"].append({"repo_url": repo_url, "error": str(exc)})
        else:
            result = run_collection(progress) if action == "heuristics" else run_collection_analytics()
        with COLLECTION_JOB_LOCK:
            COLLECTION_JOBS[job_id].update(status="completed", result=result)
    except Exception as exc:
        with COLLECTION_JOB_LOCK:
            COLLECTION_JOBS[job_id].update(status="failed", error=str(exc))


@app.post("/api/publication-collection/jobs")
def start_collection_job(request: CollectionJobRequest) -> dict[str, str]:
    with COLLECTION_JOB_LOCK:
        if any(job["status"] == "running" for job in COLLECTION_JOBS.values()):
            raise HTTPException(status_code=409, detail="A dataset job is already running.")
        # Keep bounded history in this local server process.
        if len(COLLECTION_JOBS) >= 20:
            COLLECTION_JOBS.pop(next(iter(COLLECTION_JOBS)))
        job_id = uuid4().hex
        COLLECTION_JOBS[job_id] = {"id": job_id, "action": request.action, "status": "running"}
        if request.action == "rerun_all":
            COLLECTION_JOBS[job_id]["repositories"] = list(dict.fromkeys(
                item["repo_url"] for item in list_executions()
            ))
    COLLECTION_WORKER.submit(_execute_collection_job, job_id, request.action)
    return {"id": job_id, "status": "running"}


@app.get("/api/publication-collection/jobs/{job_id}")
def collection_job(job_id: str) -> dict[str, Any]:
    with COLLECTION_JOB_LOCK:
        if job_id not in COLLECTION_JOBS:
            raise HTTPException(status_code=404, detail="Dataset job not found.")
        return dict(COLLECTION_JOBS[job_id])


@app.get("/api/selection/papers/{paper_id}")
def selected_paper(paper_id: str) -> FileResponse:
    path = paper_path(paper_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No PDF uploaded yet.")
    return FileResponse(
        path, media_type="application/pdf", filename=f"{paper_id}.pdf",
        content_disposition_type="inline",
    )


@app.put("/api/selection/papers/{paper_id}")
async def upload_selected_paper(paper_id: str, request: Request) -> dict[str, str]:
    path = paper_path(paper_id)
    contents = bytearray()
    async for chunk in request.stream():
        contents.extend(chunk)
        if len(contents) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="PDF must be at most 25 MB.")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Please upload a PDF file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary files avoid collisions between simultaneous uploads.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(contents)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"paper_id": paper_id, "pdf_url": f"/api/selection/papers/{paper_id}"}


@app.get("/api/executed/{execution_id}")
def executed_repository(execution_id: str) -> dict[str, Any]:
    result = load_result_by_id(execution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Stored repository result not found.")
    return result


@app.post("/api/random")
def random_batch(request: RandomBatchRequest) -> dict[str, Any]:
    if request.count not in ALLOWED_BATCH_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"count must be one of {sorted(ALLOWED_BATCH_SIZES)}",
        )
    try:
        return run_random_batch(
            request.count,
            dataset_path=DEFAULT_DATASET,
            token=os.getenv("GITHUB_TOKEN"),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Random batch failed: {exc}") from exc


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    """Reuse stored results unless an explicit rerun is requested."""
    try:
        if not request.force:
            existing = load_result(request.repo_url)
            if existing is not None:
                return existing

            # Preserve the precomputed demos, but promote them into the general
            # repository store so they participate in history and no-repeat logic.
            bundled_path = _bundled_demo_path(request)
            if bundled_path is not None:
                bundled = _load_cache(bundled_path)
                if bundled is not None:
                    return save_result(request.repo_url, bundled)

            cache_path = _demo_cache_path(request)
            if cache_path is not None:
                cached = _load_cache(cache_path)
                if cached is not None:
                    return save_result(request.repo_url, cached)

        if request.ref is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Persistent repository executions are keyed by repository URL. "
                    "Custom refs are disabled; executions use the default branch."
                ),
            )

        result, _ = execute_repository_once(
            request.repo_url,
            token=os.getenv("GITHUB_TOKEN"),
            max_content_bytes=request.max_content_bytes,
            **({"force": True} if request.force else {}),
        )
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Repository analysis failed: {exc}",
        ) from exc


@app.get("/", include_in_schema=False)
def interface() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    """Run the local experimentation web interface."""
    import uvicorn

    uvicorn.run(
        "research_process_steps.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


def precache_demo() -> None:
    """Populate persistent caches for the repositories used in demonstrations."""
    for name, repo_url in DEMO_REPOSITORIES.items():
        existing = load_result(repo_url)
        if existing is not None:
            print(f"{name}: already stored")
            continue
        request = AnalyzeRequest(repo_url=repo_url)
        print(f"{name}: loading precomputed result for {repo_url} ...")
        result = analyze(request)
        print(f"{name}: stored as {result.get('execution', {}).get('id')}")
