"""Heuristics and complete analytics restricted to the uploaded publication dataset."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .analyzer import GitHubRateLimitError
from .batch import execute_repository_once
from .heuristics import RESEARCH_PROCESS_STEPS
from .storage import results_dir

DATASET_PATH = Path(__file__).with_name("datasets") / "software_with_publications_v2.json"
OUTPUT_DIR = Path("data/publication_collection_analysis")


def repository_identity(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"github.com", "www.github.com"} or len(parts) < 2:
        raise ValueError(f"Invalid GitHub repository URL: {url}")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}".lower()


def load_collection() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def collection_repositories() -> list[str]:
    return list(dict.fromkeys(repository_identity(record["github_url"])
                              for record in load_collection()["results"]))


def run_collection(
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    completed, errors = [], []
    repositories = collection_repositories()
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print(
            "Warning: GITHUB_TOKEN is not set. GitHub's unauthenticated API quota "
            "is small; the runner will pause and retry when rate-limited.",
            flush=True,
        )
    for index, url in enumerate(repositories, 1):
        while True:
            try:
                result, executed = execute_repository_once(
                    url,
                    token=token,
                    force=force,
                )
                repository = result.get("repository", {})
                summary = result.get("summary", {})
                files_per_step = summary.get("files_per_step", {})
                item = {
                    "repo_url": url,
                    "executed_now": executed,
                    "id": result.get("execution", {}).get("id"),
                    "file_count": repository.get("file_count", 0),
                    "files_per_step": {
                        step: int(files_per_step.get(step, 0))
                        for step in RESEARCH_PROCESS_STEPS
                    },
                    "unclassified_files": int(summary.get("unclassified_files", 0)),
                }
                completed.append(item)
                status = "refreshed" if force and executed else ("stored" if executed else "reused")
                break
            except GitHubRateLimitError as exc:
                wait_seconds = max(1, exc.wait_seconds)
                item = {
                    "repo_url": url,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                }
                progress = {
                    "index": index,
                    "total": len(repositories),
                    "status": "rate_limited",
                    **item,
                }
                if on_progress:
                    on_progress(progress)
                print(
                    f"[{index}/{len(repositories)}] rate_limited: {url} | "
                    f"waiting {wait_seconds}s, then retrying the same repository",
                    flush=True,
                )
                time.sleep(wait_seconds)
            except Exception as exc:
                item = {"repo_url": url, "error": str(exc)}
                errors.append(item)
                status = "error"
                break
        progress = {"index": index, "total": len(repositories), "status": status, **item}
        if on_progress:
            on_progress(progress)
        if status == "error":
            print(f"[{index}/{len(repositories)}] error: {url} | {item['error']}", flush=True)
        else:
            step_details = " | ".join(
                f"{step}={item['files_per_step'][step]}"
                for step in RESEARCH_PROCESS_STEPS
            )
            print(
                f"[{index}/{len(repositories)}] {status}: {url} | "
                f"files={item['file_count']} | {step_details} | "
                f"unclassified={item['unclassified_files']}",
                flush=True,
            )
    return {"completed": completed, "errors": errors, "total": len(repositories)}


def run_collection_analytics(output_dir: Path = OUTPUT_DIR, raw_cache_dir: Path = Path("data/github_cache")) -> dict[str, Any]:
    from .analyze_all import run_all_analyses

    allowed = set(collection_repositories())
    # A fresh snapshot prevents unrelated or stale results contaminating analytics.
    with tempfile.TemporaryDirectory(prefix="publication-results-") as directory:
        snapshot = Path(directory)
        found = set()
        for path in sorted(results_dir().glob("*.json")):
            if path.name.endswith(".meta.json"):
                continue
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                key = repository_identity(result["repository"]["url"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if key not in allowed or key in found:
                continue
            found.add(key)
            (snapshot / path.name).write_text(json.dumps(result), encoding="utf-8")
        if not found:
            raise ValueError("No stored results for this dataset. Run dataset heuristics first.")
        summary = run_all_analyses(snapshot, raw_cache_dir, output_dir, 500)
    summary["dataset_scope"] = {
        "repository_count": len(allowed), "completed_count": len(found),
        "missing_repositories": sorted(allowed - found),
        "complete": found == allowed,
    }
    (output_dir / "meeting_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List this dataset's repository URLs without running.")
    parser.add_argument("--analytics-only", action="store_true", help="Run all five analytics on stored dataset results.")
    parser.add_argument("--force", action="store_true", help="Rerun heuristics for every dataset repository and replace stored results.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--raw-cache-dir", type=Path, default=Path("data/github_cache"))
    args = parser.parse_args()
    if args.list:
        print("\n".join(collection_repositories()))
    elif args.analytics_only:
        summary = run_collection_analytics(args.output_dir, args.raw_cache_dir)
        print(json.dumps(summary["dataset_scope"], indent=2))
    else:
        result = run_collection(force=args.force)
        print(f"Finished: {len(result['completed'])} stored/reused, {len(result['errors'])} errors.")
        if result["errors"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
