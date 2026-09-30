"""Fixed first-ten-paper selection and heuristic-only runner."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .batch import execute_repository_once
from .storage import normalize_repo_url

DATASET_PATH = Path(__file__).with_name("datasets") / "first_10_papers.json"


def load_selection() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def selected_repositories() -> list[str]:
    """Deduplicate repositories while preserving paper order."""
    repositories: dict[str, str] = {}
    for paper in load_selection()["papers"]:
        url = paper["github_url"]
        repositories.setdefault(normalize_repo_url(url), url)
    return list(repositories.values())


def run_selection() -> dict[str, Any]:
    completed, errors = [], []
    repositories = selected_repositories()
    for index, url in enumerate(repositories, 1):
        try:
            result, executed_now = execute_repository_once(
                url, token=os.getenv("GITHUB_TOKEN")
            )
            completed.append({
                "repo_url": url,
                "id": result.get("execution", {}).get("id"),
                "executed_now": executed_now,
            })
            print(f"[{index}/{len(repositories)}] {'stored' if executed_now else 'reused'} {url}", flush=True)
        except Exception as exc:
            errors.append({"repo_url": url, "error": str(exc)})
            print(f"[{index}/{len(repositories)}] ERROR {url}: {exc}", flush=True)
    return {"completed": completed, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic heuristics only for the eight repositories linked to the first ten papers. No repository code or paper download is executed."
    )
    parser.add_argument("--list", action="store_true", help="List selected URLs without executing heuristics.")
    args = parser.parse_args()
    if args.list:
        print("\n".join(selected_repositories()))
        return
    result = run_selection()
    print(f"Finished: {len(result['completed'])} stored/reused, {len(result['errors'])} errors.")
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
