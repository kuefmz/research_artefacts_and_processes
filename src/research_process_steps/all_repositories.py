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
from .storage import normalize_repo_url, result_id, result_path, save_result
from .git_acquisition import analyze_github_repository_git


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


def api_quota_available(status: dict[str, int], reserve: int) -> bool:
    return status["remaining"] > reserve + API_REQUESTS_PER_UNCACHED_REPOSITORY


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
    acquisition_mode: str,
    limit: int | None = None,
    max_new: int | None = None,
) -> dict[str, Any]:
    repositories = load_repositories(dataset_path)
    if limit is not None:
        repositories = repositories[:limit]

    requested_workers = max(1, workers)
    effective_workers = (
        min(requested_workers, 16)
        if acquisition_mode in {"git", "hybrid"}
        else requested_workers
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = log_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "events.jsonl"
    error_path = log_dir / "errors.jsonl"
    progress_path = run_dir / "progress.json"
    latest_progress_path = log_dir / "progress.json"

    if acquisition_mode in {"api", "hybrid"}:
        auth_status = get_rate_limit(token)
        if auth_status["limit"] < 5000:
            raise RuntimeError(
                "GitHub authentication does not appear active: expected an authenticated "
                f"core limit of at least 5000/hour, got {auth_status['limit']}. "
                "Check GITHUB_TOKEN and rerun."
            )
    else:
        auth_status = {
            "limit": 0,
            "remaining": 0,
            "used": 0,
            "reset": 0,
            "mode": "git_no_rest_quota",
        }

    stats: dict[str, Any] = {
        "run_id": run_id,
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
        "requested_workers": requested_workers,
        "workers": effective_workers,
        "repo_timeout_seconds": repo_timeout_seconds,
        "acquisition_mode": acquisition_mode,
        "api_completed": 0,
        "fallback_completed": 0,
        "api_checks": 0,
    }
    write_progress(progress_path, stats)
    write_progress(latest_progress_path, stats)

    append_jsonl(
        log_path,
        {
            "timestamp": utc_now(),
            "event": "batch_start",
            "dataset": str(dataset_path),
            "repositories": len(repositories),
            "rate_limit": auth_status,
            "raw_cache_dir": str(raw_cache_dir),
            "requested_workers": requested_workers,
            "workers": effective_workers,
            "acquisition_mode": acquisition_mode,
            "run_id": run_id,
            "run_dir": str(run_dir),
        },
    )

    previously_failed = set() if retry_failed else load_failed_repositories(error_path)

    pending: list[tuple[int, str]] = []
    for index, repo_url in enumerate(repositories, start=1):
        stats["last_repository"] = repo_url
        existing_path = result_path(repo_url)
        if existing_path.exists():
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
                    "execution_id": result_id(repo_url),
                },
            )
            if stats["already_completed"] % 1000 == 0:
                print(
                    f"Resume scan: {stats['already_completed']:,} successful "
                    f"repositories already stored.",
                    flush=True,
                )
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

    if max_new is not None:
        pending = pending[:max(0, max_new)]
        stats["max_new"] = max_new
        stats["new_repositories_scheduled"] = len(pending)

    write_progress(progress_path, stats)
    write_progress(latest_progress_path, stats)

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
            started = time.monotonic()
            selected_mode = acquisition_mode

            def log_stage(stage: str) -> None:
                append_jsonl(
                    log_path,
                    {
                        "timestamp": utc_now(),
                        "event": "repository_stage",
                        "index": index,
                        "repo_url": repo_url,
                        "mode": selected_mode,
                        "stage": stage,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    },
                )

            try:
                rate_status = None
                if acquisition_mode == "hybrid":
                    # GitHub documents GET /rate_limit as not consuming the primary
                    # REST quota. Check it for every repository dispatch so API use
                    # resumes automatically as soon as quota is available again.
                    try:
                        rate_status = get_rate_limit(token)
                        with rate_limit_lock:
                            stats["api_checks"] += 1
                        selected_mode = (
                            "api"
                            if api_quota_available(rate_status, rate_limit_reserve)
                            else "fallback"
                        )
                    except Exception as exc:
                        selected_mode = "fallback"
                        rate_status = {"check_error": f"{type(exc).__name__}: {exc}"}

                append_jsonl(
                    log_path,
                    {
                        "timestamp": utc_now(),
                        "event": "repository_start",
                        "index": index,
                        "total": len(repositories),
                        "repo_url": repo_url,
                        "attempt": attempt,
                        "selected_mode": selected_mode,
                        "rate_limit_before": rate_status,
                    },
                )

                if selected_mode == "api":
                    try:
                        result = analyze_github_repository(
                            repo_url,
                            token=token,
                            max_content_bytes=max_content_bytes,
                            raw_cache_dir=raw_cache_dir,
                            timeout_seconds=repo_timeout_seconds,
                        )
                        result.setdefault("repository", {})["acquisition"] = "github_rest_api"
                    except GitHubRateLimitError as exc:
                        # Never wait out the REST window in hybrid mode. Fall back
                        # immediately, then the next worker checks API health again.
                        if acquisition_mode != "hybrid":
                            raise
                        append_jsonl(
                            log_path,
                            {
                                "timestamp": utc_now(),
                                "event": "api_rate_limit_fallback",
                                "index": index,
                                "repo_url": repo_url,
                                "status_code": exc.status_code,
                                "wait_seconds": exc.wait_seconds,
                                "remaining_header": exc.remaining,
                                "reset_header": exc.reset,
                            },
                        )
                        selected_mode = "fallback"
                        result = analyze_github_repository_git(
                            repo_url,
                            max_content_bytes=max_content_bytes,
                            raw_cache_dir=raw_cache_dir,
                            timeout_seconds=repo_timeout_seconds,
                            stage_callback=log_stage,
                        )
                    except Exception as exc:
                        detail = f"{type(exc).__name__}: {exc}"
                        is_not_found = (
                            "GitHub request failed (404)" in detail
                            or "GitHub content request failed (404)" in detail
                        )
                        if acquisition_mode != "hybrid" or is_not_found:
                            raise
                        append_jsonl(
                            log_path,
                            {
                                "timestamp": utc_now(),
                                "event": "api_error_fallback",
                                "index": index,
                                "repo_url": repo_url,
                                "api_error": detail,
                            },
                        )
                        selected_mode = "fallback"
                        result = analyze_github_repository_git(
                            repo_url,
                            max_content_bytes=max_content_bytes,
                            raw_cache_dir=raw_cache_dir,
                            timeout_seconds=repo_timeout_seconds,
                            stage_callback=log_stage,
                        )
                elif selected_mode in {"git", "fallback"}:
                    result = analyze_github_repository_git(
                        repo_url,
                        max_content_bytes=max_content_bytes,
                        raw_cache_dir=raw_cache_dir,
                        timeout_seconds=repo_timeout_seconds,
                        stage_callback=log_stage,
                    )
                else:
                    result = analyze_github_repository(
                        repo_url,
                        token=token,
                        max_content_bytes=max_content_bytes,
                        raw_cache_dir=raw_cache_dir,
                        timeout_seconds=repo_timeout_seconds,
                    )
                    result.setdefault("repository", {})["acquisition"] = "github_rest_api"

                result.setdefault("repository", {})["batch_selected_mode"] = selected_mode
                stored = save_result(repo_url, result)
                append_jsonl(
                    log_path,
                    {
                        "timestamp": utc_now(),
                        "event": "repository_finish",
                        "index": index,
                        "repo_url": repo_url,
                        "selected_mode": selected_mode,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": "success",
                    },
                )
                return index, repo_url, stored, selected_mode
            except GitHubRateLimitError as exc:
                # API-only mode keeps historical pause behavior.
                register_global_rate_limit(exc, repo_url)
                wait_for_global_rate_limit()
                last_error = f"{type(exc).__name__}: {exc}"
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
                        "selected_mode": selected_mode,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "error": last_error,
                    },
                )
                if permanent:
                    break
                if attempt < max_retries:
                    time.sleep(min(30 * (2 ** (attempt - 1)), 5 * 60))
        return index, repo_url, None, last_error

    if requested_workers != effective_workers:
        print(
            f"Git acquisition safety cap: requested {requested_workers} workers; "
            f"using {effective_workers}.",
            flush=True,
        )

    def record_finished_future(future, future_info: dict[Any, tuple[int, str]]) -> None:
        index, repo_url = future_info[future]
        stats["last_repository"] = repo_url
        try:
            _, _, stored, outcome = future.result()
        except KeyboardInterrupt:
            stats["updated_at"] = utc_now()
            write_progress(progress_path, stats)
            write_progress(latest_progress_path, stats)
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
            if outcome == "api":
                stats["api_completed"] += 1
            else:
                stats["fallback_completed"] += 1
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
                    "selected_mode": outcome,
                },
            )
            print(
                f"[{index}/{len(repositories)}] stored "
                f"{stored.get('repository', {}).get('full_name', repo_url)} "
                f"({stored.get('repository', {}).get('file_count', 0)} files) "
                f"[{outcome}]",
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
                "error": outcome,
            }
            append_jsonl(log_path, error_event)
            append_jsonl(error_path, error_event)
            print(f"[{index}/{len(repositories)}] ERROR {repo_url}: {outcome}", flush=True)

        write_progress(progress_path, stats)
        write_progress(latest_progress_path, stats)

    # Keep only a small bounded set of futures in memory. Previously every
    # remaining repository (~100k) was submitted at once, making stall
    # reporting misleading and wasting substantial memory.
    max_inflight = max(effective_workers, effective_workers * 2)
    next_pending = 0
    future_info: dict[Any, tuple[int, str]] = {}

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        def fill_inflight() -> None:
            nonlocal next_pending
            while len(future_info) < max_inflight and next_pending < len(pending):
                index, repo_url = pending[next_pending]
                next_pending += 1
                future = executor.submit(execute_one, index, repo_url)
                future_info[future] = (index, repo_url)

        fill_inflight()

        while future_info:
            done, _ = wait(
                set(future_info),
                timeout=120,
                return_when=FIRST_COMPLETED,
            )

            if not done:
                with rate_limit_lock:
                    pause_until = rate_limit_pause_until

                queued_remaining = len(pending) - next_pending
                if pause_until > time.time():
                    remaining = int(max(1, pause_until - time.time()))
                    append_jsonl(
                        log_path,
                        {
                            "timestamp": utc_now(),
                            "event": "rate_limit_waiting",
                            "inflight_tasks": len(future_info),
                            "queued_remaining": queued_remaining,
                            "configured_workers": effective_workers,
                            "remaining_wait_seconds": remaining,
                            "resume_after_epoch": int(pause_until),
                        },
                    )
                    stats["updated_at"] = utc_now()
                    write_progress(progress_path, stats)
                    write_progress(latest_progress_path, stats)
                    print(
                        f"GitHub rate-limit pause active; ~{remaining}s remaining. "
                        f"{len(future_info)} tasks in flight, "
                        f"{queued_remaining} not yet submitted.",
                        flush=True,
                    )
                    continue

                active_sample = [
                    {
                        "index": future_info[future][0],
                        "repo_url": future_info[future][1],
                    }
                    for future in list(future_info)[:min(20, len(future_info))]
                ]
                append_jsonl(
                    log_path,
                    {
                        "timestamp": utc_now(),
                        "event": "batch_stall_warning",
                        "inflight_tasks": len(future_info),
                        "queued_remaining": queued_remaining,
                        "configured_workers": effective_workers,
                        "sample_inflight": active_sample,
                    },
                )
                stats["updated_at"] = utc_now()
                write_progress(progress_path, stats)
                write_progress(latest_progress_path, stats)
                print(
                    f"WARNING: no repository completed for 120s; "
                    f"{len(future_info)} tasks are in flight "
                    f"(max {effective_workers} running), "
                    f"{queued_remaining} remain unsubmitted.",
                    flush=True,
                )
                continue

            for future in done:
                record_finished_future(future, future_info)
                del future_info[future]

            fill_inflight()

    stats["finished_at"] = utc_now()
    stats["updated_at"] = stats["finished_at"]
    write_progress(progress_path, stats)
    write_progress(latest_progress_path, stats)
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
        "--acquisition-mode",
        choices=["hybrid", "api", "git"],
        default="hybrid",
        help=(
            "Repository acquisition method. 'hybrid' (default) checks GitHub API "
            "quota before every repository, uses REST while healthy, and immediately "
            "falls back to an exact non-REST snapshot when REST is unavailable. "
            "'api' forces REST and 'git' forces the fallback path."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help=(
            "Concurrent repository workers (default: 4). Git mode is safety-capped "
            "at 16 even if a higher value is requested."
        ),
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
        help="Optional first-N repository limit before resume filtering.",
    )
    parser.add_argument(
        "--max-new",
        type=int,
        help=(
            "After skipping successful/previously failed repositories, process at "
            "most this many unseen repositories. Useful for a production smoke test."
        ),
    )
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "")
    if args.acquisition_mode in {"api", "hybrid"} and not token:
        raise SystemExit(
            "GITHUB_TOKEN is required for API or hybrid acquisition mode."
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
        acquisition_mode=args.acquisition_mode,
        limit=args.limit,
        max_new=args.max_new,
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
