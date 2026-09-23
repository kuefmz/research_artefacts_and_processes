"""Minimal FastAPI interface for deterministic repository experiments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/KnowledgeCaptureAndDiscovery/somef"])
    ref: str | None = None
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
    return {"count": len(executions), "repositories": executions}


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
    """Analyze once; all later requests for the same repository reuse storage."""
    try:
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
                    "Custom refs are disabled to guarantee that a repository is never "
                    "executed twice."
                ),
            )

        result, _ = execute_repository_once(
            request.repo_url,
            token=os.getenv("GITHUB_TOKEN"),
            max_content_bytes=request.max_content_bytes,
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
