"""Run heuristics over every unique GitHub repository in a CSV, safely and resumably."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .analyzer import (
    DEFAULT_CONTENT_LIMIT,
    DEFAULT_RAW_CACHE_DIR,
    GitHubRateLimitError,
    RepositoryTimeoutError,
    analyze_github_repository,
)
from .storage import load_result, normalize_repo_url, save_result


DEFAULT_DATASET = Path("data/openaire_zenodo_12819872/github_repositories.csv")
DEFAULT_LOG_DIR = Path("data/batch_runs")
RATE_LIMIT_URL = "https://api.github.com/rate_limit"
API_REQUESTS_PER_UNCACHED_REPOSITORY = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_repositories(dataset_path: Path) -> list[str]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Repository CSV not found: {dataset_path}")

    repositories: list[str] = []
    seen: set[str] = set()
    with dataset_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if "github_repository_url" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain a github_repository_url column.")

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


def get_rate_limit(token: str) -> dict[str, int]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "research-process-steps/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = Request(RATE_LIMIT_URL, headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Could not verify GitHub authentication/rate limit ({exc.code}): {detail}"
        ) from exc

    core = payload.get("resources", {}).get("core", {})
    return {
        "limit": int(core.get("limit", 0)),
        "remaining": int(core.get("remaining", 0)),
        "used": int(core.get("used", 0)),
        "reset": int(core.get("reset", 0)),
    }


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_failed_repositories(error_path: Path) -> set[str]:
    """Return normalized repository URLs that previously ended in repository_error."""
    failed: set[str] = set()
    if not error_path.exists():
        return failed

    for line in error_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "repository_error":
            continue
        repo_url = (event.get("repo_url") or "").strip()
        if repo_url:
            failed.add(normalize_repo_url(repo_url))
    return failed


def write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def wait_for_safe_quota(
    token: str,
    *,
    reserve: int,
    log_path: Path,
) -> dict[str, int]:
    while True:
        status = get_rate_limit(token)
        required = reserve + API_REQUESTS_PER_UNCACHED_REPOSITORY
        if status["remaining"] > required:
            return status

        wait_seconds = max(1, status["reset"] - int(time.time()) + 10)
        event = {
            "timestamp": utc_now(),
            "event": "rate_limit_wait",
            "remaining": status["remaining"],
            "limit": status["limit"],
            "reset": status["reset"],
            "sleep_seconds": wait_seconds,
        }
        append_jsonl(log_path, event)
        print(
            f"GitHub core quota is low ({status['remaining']}/{status['limit']}). "
            f"Sleeping until the rate-limit window resets.",
            flush=True,
        )
        time.sleep(wait_seconds)


def run_all(
    *,
    dataset_path: Path,
    token: str,
    log_dir: Path,
    raw_cache_dir: Path,
    rate_limit_reserve: int,
    max_content_bytes: int,
    max_retries: int,
    workers: int,
    repo_timeout_seconds: float,
    retry_failed: bool,
    limit: int | None = None,
) -> dict[str, Any]:
    repositories = load_repositories(dataset_path)
    if limit is not None:
        repositories = repositories[:limit]

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run_all.jsonl"
    error_path = log_dir / "errors.jsonl"
    progress_path = log_dir / "progress.json"

    auth_status = get_rate_limit(token)
    if auth_status["limit"] < 5000:
        raise RuntimeError(
            "GitHub authentication does not appear active: expected an authenticated "
            f"core limit of at least 5000/hour, got {auth_status['limit']}. "
            "Check GITHUB_TOKEN and rerun."
        )

    stats: dict[str, Any] = {
        "started_at": utc_now(),
        "updated_at": utc_now(),
        "dataset": str(dataset_path),
        "total_unique_repositories": len(repositories),
        "completed_now": 0,
        "already_completed": 0,
        "errors": 0,
        "previously_failed_skipped": 0,
        "processed": 0,
        "last_repository": None,
        "results_dir": os.getenv("RPS_RESULTS_DIR", "data/heuristic_results"),
        "raw_cache_dir": str(raw_cache_dir),
        "log_file": str(log_path),
        "error_file": str(error_path),
        "authenticated_rate_limit": auth_status,
        "workers": workers,
        "repo_timeout_seconds": repo_timeout_seconds,
    }
    write_progress(progress_path, stats)

    append_jsonl(
        log_path,
        {
            "timestamp": utc_now(),
            "event": "batch_start",
            "dataset": str(dataset_path),
            "repositories": len(repositories),
            "rate_limit": auth_status,
            "raw_cache_dir": str(raw_cache_dir),
        },
    )

    previously_failed = set() if retry_failed else load_failed_repositories(error_path)

    pending: list[tuple[int, str]] = []
    for index, repo_url in enumerate(repositories, start=1):
        stats["last_repository"] = repo_url
        existing = load_result(repo_url)
        if existing is not None:
            stats["already_completed"] += 1
            stats["processed"] += 1
            stats["updated_at"] = utc_now()
            append_jsonl(
                log_path,
                {
                    "timestamp": utc_now(),
                    "event": "skip_existing",
                    "index": index,
                    "total": len(repositories),
                    "repo_url": repo_url,
                    "execution_id": existing.get("execution", {}).get("id"),
                },
            )
            print(f"[{index}/{len(repositories)}] already stored: {repo_url}", flush=True)
        elif normalize_repo_url(repo_url) in previously_failed:
            stats["previously_failed_skipped"] += 1
            stats["processed"] += 1
            stats["updated_at"] = utc_now()
            append_jsonl(
                log_path,
                {
                    "timestamp": utc_now(),
                    "event": "skip_previous_failure",
                    "index": index,
                    "total": len(repositories),
                    "repo_url": repo_url,
                },
            )
            print(
                f"[{index}/{len(repositories)}] previously failed; skipping: {repo_url}",
                flush=True,
            )
        else:
            pending.append((index, repo_url))

    write_progress(progress_path, stats)

    rate_limit_lock = threading.Lock()
    rate_limit_pause_until = 0.0

    def wait_for_global_rate_limit() -> None:
        while True:
            with rate_limit_lock:
                pause_until = rate_limit_pause_until
            remaining = pause_until - time.time()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 5.0))

    def register_global_rate_limit(exc: GitHubRateLimitError, repo_url: str) -> None:
        nonlocal rate_limit_pause_until
        now = time.time()
        requested_until = now + exc.wait_seconds
        should_log = False
        with rate_limit_lock:
            if requested_until > rate_limit_pause_until:
                rate_limit_pause_until = requested_until
                should_log = True
            effective_until = rate_limit_pause_until

        if should_log:
            append_jsonl(
                log_path,
                {
                    "timestamp": utc_now(),
                    "event": "rate_limit_pause",
                    "repo_url": repo_url,
                    "status_code": exc.status_code,
                    "wait_seconds": int(max(1, effective_until - now)),
                    "resume_after_epoch": int(effective_until),
                    "remaining_header": exc.remaining,
                    "reset_header": exc.reset,
                    "retry_after_header": exc.retry_after,
                    "url": exc.url,
                },
            )
            print(
                f"GitHub rate limit hit ({exc.status_code}). "
                f"Pausing all workers for ~{int(max(1, effective_until - now))}s, then resuming.",
                flush=True,
            )

    def execute_one(index: int, repo_url: str) -> tuple[int, str, dict[str, Any] | None, str | None]:
        last_error = ""
        for attempt in range(1, max_retries + 1):
            while True:
                try:
                    wait_for_global_rate_limit()
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "repository_start",
                            "index": index,
                            "total": len(repositories),
                            "repo_url": repo_url,
                            "attempt": attempt,
                            "rate_limit_before": "managed_from_response_headers",
                        },
                    )
                    result = analyze_github_repository(
                        repo_url,
                        token=token,
                        max_content_bytes=max_content_bytes,
                        raw_cache_dir=raw_cache_dir,
                        timeout_seconds=repo_timeout_seconds,
                    )
                    stored = save_result(repo_url, result)
                    return index, repo_url, stored, None
                except GitHubRateLimitError as exc:
                    register_global_rate_limit(exc, repo_url)
                    wait_for_global_rate_limit()
                    continue
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    timed_out = isinstance(exc, RepositoryTimeoutError)
                    forbidden = (
                        "GitHub request failed (403)" in last_error
                        or "GitHub content request failed (403)" in last_error
                    )
                    permanent = (
                        "GitHub request failed (404)" in last_error
                        or "GitHub content request failed (404)" in last_error
                        or forbidden
                        or timed_out
                    )
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "repository_timeout" if timed_out else "repository_retry",
                            "index": index,
                            "total": len(repositories),
                            "repo_url": repo_url,
                            "attempt": attempt,
                            "error": last_error,
                        },
                    )
                    if permanent:
                        break
                    if attempt < max_retries:
                        time.sleep(min(30 * (2 ** (attempt - 1)), 5 * 60))
        return index, repo_url, None, last_error

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(execute_one, index, repo_url): (index, repo_url)
            for index, repo_url in pending
        }
        pending_futures = set(futures)
        while pending_futures:
            done, pending_futures = wait(
                pending_futures,
                timeout=120,
                return_when=FIRST_COMPLETED,
            )

            if not done:
                with rate_limit_lock:
                    pause_until = rate_limit_pause_until
                if pause_until > time.time():
                    remaining = int(max(1, pause_until - time.time()))
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "rate_limit_waiting",
                            "pending_workers": len(pending_futures),
                            "remaining_wait_seconds": remaining,
                            "resume_after_epoch": int(pause_until),
                        },
                    )
                    stats["updated_at"] = utc_now()
                    write_progress(progress_path, stats)
                    print(
                        f"GitHub rate-limit pause active; ~{remaining}s remaining. "
                        f"{len(pending_futures)} workers will resume automatically.",
                        flush=True,
                    )
                    continue

                stuck = [
                    {
                        "index": futures[future][0],
                        "repo_url": futures[future][1],
                    }
                    for future in list(pending_futures)[:20]
                ]
                append_jsonl(
                    log_path,
                    {
                        "timestamp": utc_now(),
                        "event": "batch_stall_warning",
                        "pending_workers": len(pending_futures),
                        "sample_pending": stuck,
                    },
                )
                stats["updated_at"] = utc_now()
                write_progress(progress_path, stats)
                print(
                    f"WARNING: no repository completed for 120s; "
                    f"{len(pending_futures)} futures still pending.",
                    flush=True,
                )
                continue

            for future in done:
                index, repo_url = futures[future]
                stats["last_repository"] = repo_url
                try:
                    _, _, stored, error = future.result()
                except KeyboardInterrupt:
                    stats["updated_at"] = utc_now()
                    write_progress(progress_path, stats)
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "batch_interrupted",
                            "index": index,
                            "repo_url": repo_url,
                        },
                    )
                    raise

                if stored is not None:
                    stats["completed_now"] += 1
                    stats["processed"] += 1
                    stats["updated_at"] = utc_now()
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "repository_complete",
                            "index": index,
                            "total": len(repositories),
                            "repo_url": repo_url,
                            "execution_id": stored.get("execution", {}).get("id"),
                            "full_name": stored.get("repository", {}).get("full_name"),
                            "file_count": stored.get("repository", {}).get("file_count", 0),
                            "raw_cache_path": stored.get("repository", {}).get("raw_cache_path"),
                        },
                    )
                    print(
                        f"[{index}/{len(repositories)}] stored "
                        f"{stored.get('repository', {}).get('full_name', repo_url)} "
                        f"({stored.get('repository', {}).get('file_count', 0)} files)",
                        flush=True,
                    )
                else:
                    stats["errors"] += 1
                    stats["processed"] += 1
                    stats["updated_at"] = utc_now()
                    error_event = {
                        "timestamp": utc_now(),
                        "event": "repository_error",
                        "index": index,
                        "total": len(repositories),
                        "repo_url": repo_url,
                        "attempts": max_retries,
                        "error": error,
                    }
                    append_jsonl(log_path, error_event)
                    append_jsonl(error_path, error_event)
                    print(f"[{index}/{len(repositories)}] ERROR {repo_url}: {error}", flush=True)

                write_progress(progress_path, stats)

    stats["finished_at"] = utc_now()
    stats["updated_at"] = stats["finished_at"]
    write_progress(progress_path, stats)
    append_jsonl(
        log_path,
        {
            "timestamp": utc_now(),
            "event": "batch_complete",
            "completed_now": stats["completed_now"],
            "already_completed": stats["already_completed"],
            "errors": stats["errors"],
            "previously_failed_skipped": stats["previously_failed_skipped"],
            "processed": stats["processed"],
        },
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic heuristics over every unique repository in the CSV. "
            "The command is resumable, caches raw GitHub inputs, stores every successful "
            "result immediately, logs failures, and waits before exhausting the API quota."
        )
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="Persistent batch progress/error log directory.",
    )
    parser.add_argument(
        "--raw-cache-dir",
        type=Path,
        default=Path(os.getenv("RPS_RAW_CACHE_DIR", str(DEFAULT_RAW_CACHE_DIR))),
        help="Directory for reusable GitHub metadata/tree/source caches.",
    )
    parser.add_argument(
        "--rate-limit-reserve",
        type=int,
        default=100,
        help="Never intentionally consume the final N core API requests (default: 100).",
    )
    parser.add_argument(
        "--max-content-bytes",
        type=int,
        default=DEFAULT_CONTENT_LIMIT,
        help="Maximum size of text/source files fetched for content heuristics.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help=(
            "Repository-level attempts for transient failures (default: 1). "
            "Increase only when you explicitly want same-run retries."
        ),
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help=(
            "Explicitly retry repositories already recorded in errors.jsonl. "
            "By default previous failures are skipped on every restart."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent repository workers (default: 4). Use 2-6 conservatively.",
    )
    parser.add_argument(
        "--repo-timeout-seconds",
        type=float,
        default=60.0,
        help=(
            "Skip a repository if processing exceeds this many seconds "
            "(default: 60). Use 0 to disable the timeout."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional first-N repository limit for a small test run.",
    )
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN is not set. Create a GitHub personal access token and export "
            "it before running this command."
        )

    result = run_all(
        dataset_path=args.dataset,
        token=token,
        log_dir=args.log_dir,
        raw_cache_dir=args.raw_cache_dir,
        rate_limit_reserve=args.rate_limit_reserve,
        max_content_bytes=args.max_content_bytes,
        max_retries=args.max_retries,
        workers=max(1, args.workers),
        repo_timeout_seconds=max(0.0, args.repo_timeout_seconds),
        retry_failed=args.retry_failed,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
