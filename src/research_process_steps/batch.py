"""Run deterministic heuristics over random, never-before-executed repositories."""

from __future__ import annotations

import argparse
import csv
import os
import random
from pathlib import Path
from typing import Any, Callable

from .analyzer import DEFAULT_CONTENT_LIMIT, analyze_github_repository
from .storage import (
    acquire_execution,
    load_result,
    normalize_repo_url,
    release_execution,
    save_result,
)

DEFAULT_DATASET = Path("data/openaire_zenodo_12819872/github_repositories.csv")
ALLOWED_BATCH_SIZES = {10, 20, 25, 50, 100}


def load_repository_population(dataset_path: Path = DEFAULT_DATASET) -> list[str]:
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Repository dataset not found: {dataset_path}. "
            "Run scripts/compile_openaire_github_dataset.py first."
        )

    repositories: list[str] = []
    seen: set[str] = set()
    with dataset_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if "github_repository_url" not in (reader.fieldnames or []):
            raise ValueError("Dataset must contain a github_repository_url column.")
        for row in reader:
            repo_url = (row.get("github_repository_url") or "").strip()
            if not repo_url:
                continue
            key = normalize_repo_url(repo_url)
            if key in seen:
                continue
            seen.add(key)
            repositories.append(repo_url)
    return repositories


def select_unexecuted_random(
    count: int,
    *,
    dataset_path: Path = DEFAULT_DATASET,
    rng: random.Random | random.SystemRandom | None = None,
) -> list[str]:
    population = load_repository_population(dataset_path)
    available = [repo for repo in population if load_result(repo) is None]
    if len(available) < count:
        raise ValueError(
            f"Requested {count} repositories but only {len(available)} "
            "never-executed repositories remain."
        )
    chooser = rng or random.SystemRandom()
    return chooser.sample(available, count)


def execute_repository_once(
    repo_url: str,
    *,
    token: str | None = None,
    max_content_bytes: int = DEFAULT_CONTENT_LIMIT,
) -> tuple[dict[str, Any], bool]:
    """Return (result, executed_now). A stored repository is never rerun."""
    existing = load_result(repo_url)
    if existing is not None:
        return existing, False

    if not acquire_execution(repo_url):
        # Another process/server request owns this repository. Do not execute it.
        existing = load_result(repo_url)
        if existing is not None:
            return existing, False
        raise RuntimeError(f"Repository is already being executed: {repo_url}")

    try:
        # Check again after obtaining the lock in case another process completed it.
        existing = load_result(repo_url)
        if existing is not None:
            return existing, False

        result = analyze_github_repository(
            repo_url,
            token=token,
            max_content_bytes=max_content_bytes,
        )
        return save_result(repo_url, result), True
    finally:
        release_execution(repo_url)


def run_random_batch(
    count: int,
    *,
    dataset_path: Path = DEFAULT_DATASET,
    token: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if count not in ALLOWED_BATCH_SIZES:
        raise ValueError(f"count must be one of {sorted(ALLOWED_BATCH_SIZES)}")

    selected = select_unexecuted_random(count, dataset_path=dataset_path)
    completed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for index, repo_url in enumerate(selected, start=1):
        try:
            result, executed_now = execute_repository_once(repo_url, token=token)
            item = {
                "repo_url": repo_url,
                "id": result.get("execution", {}).get("id"),
                "full_name": result.get("repository", {}).get("full_name"),
                "file_count": result.get("repository", {}).get("file_count", 0),
                "executed_now": executed_now,
            }
            completed.append(item)
            if on_progress:
                on_progress({"index": index, "count": count, "status": "completed", **item})
        except Exception as exc:
            error = {"repo_url": repo_url, "error": str(exc)}
            errors.append(error)
            if on_progress:
                on_progress({"index": index, "count": count, "status": "error", **error})

    return {
        "requested": count,
        "selected": len(selected),
        "completed": completed,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute heuristics on random repositories that have never been run before."
    )
    parser.add_argument(
        "count",
        nargs="?",
        type=int,
        default=100,
        choices=sorted(ALLOWED_BATCH_SIZES),
        help="Number of random never-before-executed repositories (default: 100).",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Repository-level CSV produced by the OpenAIRE dataset compiler.",
    )
    args = parser.parse_args()

    def report(item: dict[str, Any]) -> None:
        prefix = f"[{item['index']}/{item['count']}]"
        if item["status"] == "completed":
            print(f"{prefix} stored {item['full_name']} ({item['file_count']} files)", flush=True)
        else:
            print(f"{prefix} ERROR {item['repo_url']}: {item['error']}", flush=True)

    result = run_random_batch(
        args.count,
        dataset_path=args.dataset,
        token=os.getenv("GITHUB_TOKEN"),
        on_progress=report,
    )
    print(
        f"Finished: {len(result['completed'])} stored, {len(result['errors'])} errors.",
        flush=True,
    )


if __name__ == "__main__":
    main()
