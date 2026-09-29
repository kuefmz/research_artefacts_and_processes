"""Git-based repository acquisition that avoids GitHub REST API quota.

This module preserves the existing deterministic heuristic layer. Repository
state is acquired with Git's smart HTTP protocol, then file-tree metadata and
blob contents are read from the exact checked-out commit locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .analyzer import (
    DEFAULT_CONTENT_LIMIT,
    DEFAULT_RAW_CACHE_DIR,
    DETECTION_THRESHOLD,
    RepositoryTimeoutError,
    _content_is_scannable,
    analyze_file,
)
from .heuristics import RESEARCH_PROCESS_STEPS


def _check_deadline(deadline: float | None, repository_url: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RepositoryTimeoutError(
            f"Repository processing exceeded its time limit for {repository_url}."
        )


def _remaining(deadline: float | None, default: float = 60.0) -> float:
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RepositoryTimeoutError("Repository processing exceeded its time limit.")
    return max(1.0, remaining)


def _parse(repository_url: str) -> tuple[str, str]:
    parsed = urlparse(repository_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Expected a github.com repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Expected https://github.com/OWNER/REPO.")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 60.0,
    text: bool = True,
    input_data: bytes | str | None = None,
) -> subprocess.CompletedProcess:
    """Run Git with both process and low-speed network timeouts."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"

    # Prevent git-remote-https from occupying a worker indefinitely when a
    # transfer stops making meaningful progress.
    env["GIT_CONFIG_COUNT"] = "2"
    env["GIT_CONFIG_KEY_0"] = "http.lowSpeedLimit"
    env["GIT_CONFIG_VALUE_0"] = "1024"
    env["GIT_CONFIG_KEY_1"] = "http.lowSpeedTime"
    env["GIT_CONFIG_VALUE_1"] = "20"

    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=text,
            timeout=timeout,
            input=input_data,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepositoryTimeoutError(
            f"Git command exceeded its {timeout:.1f}s timeout."
        ) from exc


def _read_blobs_batch(
    repo_dir: Path,
    items: list[dict[str, Any]],
    deadline: float | None,
) -> dict[str, bytes]:
    """Read Git blobs in bounded batches while preserving exact blob bytes."""
    if not items:
        return {}

    max_batch_files = 256
    max_batch_bytes = 32 * 1024 * 1024
    blobs: dict[str, bytes] = {}

    batch: list[dict[str, Any]] = []
    batch_bytes = 0

    def flush(current: list[dict[str, Any]]) -> None:
        if not current:
            return
        payload = "".join(f"{item['sha']}\n" for item in current)
        result = _run_git(
            ["cat-file", "--batch"],
            cwd=repo_dir,
            timeout=_remaining(deadline, 60),
            text=False,
            input_data=payload.encode("ascii"),
        )

        offset = 0
        output = result.stdout
        for item in current:
            newline = output.find(b"\n", offset)
            if newline < 0:
                raise RuntimeError("Malformed git cat-file --batch output.")
            header = output[offset:newline].decode("ascii", errors="replace")
            offset = newline + 1
            parts = header.split()
            if len(parts) != 3 or parts[1] != "blob":
                raise RuntimeError(f"Unexpected git cat-file header: {header}")
            size = int(parts[2])
            data = output[offset:offset + size]
            offset += size
            if offset >= len(output) or output[offset:offset + 1] != b"\n":
                raise RuntimeError("Malformed git cat-file blob delimiter.")
            offset += 1
            blobs[item["sha"]] = data

    for item in items:
        size = int(item.get("size") or 0)
        if batch and (
            len(batch) >= max_batch_files
            or batch_bytes + size > max_batch_bytes
        ):
            flush(batch)
            batch = []
            batch_bytes = 0
            _check_deadline(deadline, str(repo_dir))

        batch.append(item)
        batch_bytes += size

    flush(batch)
    return blobs

def _snapshot_dir(cache_root: Path, owner: str, repo: str, ref: str) -> Path:
    repo_dir = cache_root / f"{owner.replace('/', '_')}__{repo.replace('/', '_')}"
    key = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:12]
    return repo_dir / key


def _parse_ls_tree(data: bytes) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_record in data.split(b"\0"):
        if not raw_record:
            continue
        meta, raw_path = raw_record.split(b"\t", 1)
        parts = meta.decode("ascii").split()
        mode, object_type, sha = parts[:3]
        size_text = parts[3] if len(parts) >= 4 else "-"
        item: dict[str, Any] = {
            "path": raw_path.decode("utf-8", errors="surrogateescape"),
            "mode": mode,
            "type": object_type,
            "sha": sha,
        }
        if size_text.isdigit():
            item["size"] = int(size_text)
        items.append(item)
    return items


def _read_blob(repo_dir: Path, sha: str, deadline: float | None) -> bytes:
    """Compatibility helper used by tests and small callers."""
    return _read_blobs_batch(repo_dir, [{"sha": sha}], deadline)[sha]

def analyze_github_repository_git(
    repository_url: str,
    *,
    max_content_bytes: int = DEFAULT_CONTENT_LIMIT,
    raw_cache_dir: Path | str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Analyze an exact GitHub HEAD snapshot without REST API requests."""

    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else None
    )
    owner, repo = _parse(repository_url)
    cache_root = Path(raw_cache_dir or DEFAULT_RAW_CACHE_DIR)

    _check_deadline(deadline, repository_url)

    with tempfile.TemporaryDirectory(prefix="rps-git-") as temp:
        checkout = Path(temp) / "repo"
        _run_git(
            [
                "clone",
                "--depth", "1",
                "--no-tags",
                "--single-branch",
                repository_url,
                str(checkout),
            ],
            timeout=_remaining(deadline, 60),
        )

        branch = _run_git(
            ["symbolic-ref", "--short", "HEAD"],
            cwd=checkout,
            timeout=_remaining(deadline, 5),
        ).stdout.strip()
        commit_sha = _run_git(
            ["rev-parse", "HEAD"], cwd=checkout, timeout=_remaining(deadline, 5)
        ).stdout.strip()

        snapshot_cache = _snapshot_dir(cache_root, owner, repo, branch)
        snapshot_cache.mkdir(parents=True, exist_ok=True)

        tree_sha = _run_git(
            ["rev-parse", "HEAD^{tree}"], cwd=checkout, timeout=_remaining(deadline, 10)
        ).stdout.strip()

        tree_raw = _run_git(
            ["ls-tree", "-r", "-t", "-l", "-z", "HEAD"],
            cwd=checkout,
            timeout=_remaining(deadline, 30),
            text=False,
        ).stdout
        tree_items = _parse_ls_tree(tree_raw)
        blobs = [item for item in tree_items if item.get("type") == "blob"]
        blobs.sort(key=lambda item: item["path"].lower())

        tree_payload = {
            "sha": tree_sha,
            "tree": tree_items,
            "truncated": False,
            "git_acquisition": True,
            "resolved_commit_sha": commit_sha,
        }
        (snapshot_cache / "tree.json").write_text(
            json.dumps(tree_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (snapshot_cache / "manifest.json").write_text(
            json.dumps(
                {
                    "repository_url": repository_url,
                    "full_name": f"{owner}/{repo}",
                    "ref": branch,
                    "resolved_commit_sha": commit_sha,
                    "tree_sha": tree_sha,
                    "acquisition": "git_shallow_clone",
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

        scannable_items = [
            item
            for item in blobs
            if _content_is_scannable(item["path"])
            and int(item.get("size") or 0) <= max_content_bytes
        ]
        raw_content_by_sha = _read_blobs_batch(checkout, scannable_items, deadline)

        output_files: list[dict[str, Any]] = []
        for item in blobs:
            _check_deadline(deadline, repository_url)
            path = item["path"]
            size = int(item.get("size") or 0)
            content = ""
            content_scanned = False

            if _content_is_scannable(path) and size <= max_content_bytes:
                raw = raw_content_by_sha[item["sha"]]
                content = raw.decode("utf-8", errors="replace")
                content_scanned = True
                cached = snapshot_cache / "content" / Path(path)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(content, encoding="utf-8")

            result = analyze_file(path, content)
            encoded_path = quote(path, safe="/")
            file_url = (
                f"https://github.com/{quote(owner)}/{quote(repo)}/blob/"
                f"{quote(branch, safe='')}/{encoded_path}"
            )
            for evidence in result["evidence"]:
                for match in evidence.get("matches", []):
                    line = match.get("line")
                    match["url"] = f"{file_url}#L{line}" if line else file_url

            file_path = Path(path)
            result.update(
                {
                    "file_name": file_path.name,
                    "directory": "" if str(file_path.parent) == "." else str(file_path.parent),
                    "extension": file_path.suffix.lower(),
                    "size_bytes": size,
                    "content_scanned": content_scanned,
                    "blob_sha": item.get("sha"),
                    "file_url": file_url,
                    "ref": branch,
                }
            )
            output_files.append(result)

    step_counts = {
        step: sum(step in record["steps"] for record in output_files)
        for step in RESEARCH_PROCESS_STEPS
    }

    return {
        "repository": {
            "url": repository_url,
            "full_name": f"{owner}/{repo}",
            "ref": branch,
            "resolved_commit_sha": commit_sha,
            "commit_tree_sha": tree_sha,
            "file_count": len(output_files),
            "raw_cache_path": str(snapshot_cache),
            "acquisition": "git_shallow_clone",
        },
        "method": {
            "name": "deterministic_research_process_step_heuristics",
            "version": "0.1.0",
            "uses_ai": False,
            "multi_label": True,
            "detection_threshold": DETECTION_THRESHOLD,
            "max_content_bytes": max_content_bytes,
        },
        "summary": {
            "files_per_step": step_counts,
            "unclassified_files": sum(record["unclassified"] for record in output_files),
        },
        "files": output_files,
    }
