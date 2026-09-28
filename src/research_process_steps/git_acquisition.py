"""Git-based repository acquisition that avoids GitHub REST API quota.

This module preserves the existing deterministic heuristic layer. Repository
state is acquired with Git's smart HTTP protocol, then file-tree metadata and
blob contents are read from the exact checked-out commit locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=text,
        timeout=timeout,
    )


def _resolve_head(repository_url: str, deadline: float | None) -> tuple[str, str]:
    result = _run_git(
        ["ls-remote", "--symref", repository_url, "HEAD"],
        timeout=_remaining(deadline, 30),
    )
    branch = ""
    commit = ""
    for line in result.stdout.splitlines():
        if line.startswith("ref: ") and line.endswith("\tHEAD"):
            ref = line.split("\t", 1)[0][5:]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                branch = ref[len(prefix):]
        elif line.endswith("\tHEAD"):
            commit = line.split("\t", 1)[0].strip()
    if not branch or not commit:
        raise RuntimeError("Could not resolve repository default branch/HEAD with git.")
    return branch, commit


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
    result = _run_git(
        ["cat-file", "blob", sha],
        cwd=repo_dir,
        timeout=_remaining(deadline, 30),
        text=False,
    )
    return result.stdout


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
    branch, resolved_head = _resolve_head(repository_url, deadline)
    snapshot_cache = _snapshot_dir(cache_root, owner, repo, branch)
    snapshot_cache.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="rps-git-") as temp:
        checkout = Path(temp) / "repo"
        _run_git(
            [
                "clone",
                "--depth", "1",
                "--no-tags",
                "--single-branch",
                "--branch", branch,
                repository_url,
                str(checkout),
            ],
            timeout=_remaining(deadline, 120),
        )

        commit_sha = _run_git(
            ["rev-parse", "HEAD"], cwd=checkout, timeout=_remaining(deadline, 10)
        ).stdout.strip()
        if commit_sha != resolved_head:
            raise RuntimeError(
                "Repository HEAD changed between resolution and clone; "
                "discarding snapshot to avoid inconsistent results."
            )

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

        output_files: list[dict[str, Any]] = []
        for item in blobs:
            _check_deadline(deadline, repository_url)
            path = item["path"]
            size = int(item.get("size") or 0)
            content = ""
            content_scanned = False

            if _content_is_scannable(path) and size <= max_content_bytes:
                raw = _read_blob(checkout, item["sha"], deadline)
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
