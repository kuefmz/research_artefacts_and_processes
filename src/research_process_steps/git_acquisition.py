"""Exact repository acquisition without GitHub REST-core quota.

The default path resolves the repository HEAD with a lightweight git ls-remote,
downloads that exact commit as one GitHub codeload archive, and feeds the same
deterministic heuristic layer the exact file bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

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

def _resolve_head(repository_url: str, deadline: float | None) -> tuple[str, str]:
    """Resolve default branch and exact HEAD commit with a tiny Git transfer."""
    result = _run_git(
        ["ls-remote", "--symref", repository_url, "HEAD"],
        timeout=min(_remaining(deadline, 15), 15),
    )
    branch = ""
    commit = ""
    for line in result.stdout.splitlines():
        if line.startswith("ref: ") and line.endswith("\tHEAD"):
            ref = line.split("\t", 1)[0][5:]
            prefix = "refs/heads/"
            branch = ref[len(prefix):] if ref.startswith(prefix) else ref
        elif line.endswith("\tHEAD"):
            commit = line.split("\t", 1)[0].strip()
    if not branch or not commit:
        raise RuntimeError("Could not resolve repository default branch/HEAD.")
    return branch, commit


def _download_archive(
    owner: str,
    repo: str,
    commit_sha: str,
    deadline: float | None,
) -> bytes:
    """Download one immutable GitHub archive for the resolved commit."""
    url = (
        "https://codeload.github.com/"
        f"{quote(owner)}/{quote(repo)}/tar.gz/{quote(commit_sha, safe='')}"
    )
    request = Request(url, headers={"User-Agent": "research-process-steps/0.1"})
    timeout = min(_remaining(deadline, 45), 45)
    with urlopen(request, timeout=timeout) as response:
        chunks: list[bytes] = []
        while True:
            _check_deadline(deadline, f"https://github.com/{owner}/{repo}")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


def _git_blob_sha(data: bytes) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _archive_files(archive_bytes: bytes) -> list[dict[str, Any]]:
    """Return exact blob-like file records from a GitHub tar archive."""
    records: list[dict[str, Any]] = []
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        members = tar.getmembers()
        roots = {
            member.name.split("/", 1)[0]
            for member in members
            if member.name and "/" in member.name
        }
        if len(roots) != 1:
            raise RuntimeError("Could not identify a unique GitHub archive root.")
        root_prefix = next(iter(roots)) + "/"

        for member in members:
            if not member.name.startswith(root_prefix):
                continue
            path = member.name[len(root_prefix):].rstrip("/")
            if not path or member.isdir():
                continue
            if member.issym():
                data = member.linkname.encode("utf-8")
                mode = "120000"
            elif member.isfile() or member.islnk():
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                data = extracted.read()
                mode = "100755" if (member.mode & 0o111) else "100644"
            else:
                # Gitlinks/submodules are not blobs and were never classified
                # by the historical analyzer either.
                continue

            records.append(
                {
                    "path": path,
                    "mode": mode,
                    "type": "blob",
                    "sha": _git_blob_sha(data),
                    "size": len(data),
                    "_raw": data,
                }
            )
    records.sort(key=lambda item: item["path"].lower())
    return records


def analyze_github_repository_git(
    repository_url: str,
    *,
    max_content_bytes: int = DEFAULT_CONTENT_LIMIT,
    raw_cache_dir: Path | str | None = None,
    timeout_seconds: float | None = None,
    stage_callback=None,
) -> dict[str, Any]:
    """Analyze an exact GitHub HEAD snapshot without REST API requests."""

    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else None
    )
    owner, repo = _parse(repository_url)
    cache_root = Path(raw_cache_dir or DEFAULT_RAW_CACHE_DIR)

    def stage(name: str) -> None:
        if stage_callback is not None:
            stage_callback(name)

    _check_deadline(deadline, repository_url)
    stage("resolve_head")
    branch, commit_sha = _resolve_head(repository_url, deadline)

    snapshot_cache = _snapshot_dir(cache_root, owner, repo, branch)
    snapshot_cache.mkdir(parents=True, exist_ok=True)

    stage("download_archive")
    archive_bytes = _download_archive(owner, repo, commit_sha, deadline)

    stage("parse_archive")
    blobs = _archive_files(archive_bytes)
    _check_deadline(deadline, repository_url)

    # Tree SHA here is the exact immutable commit identifier plus per-blob SHAs.
    # The commit SHA is the authoritative repository snapshot identifier.
    tree_fingerprint = hashlib.sha256()
    for item in blobs:
        tree_fingerprint.update(item["mode"].encode("ascii"))
        tree_fingerprint.update(b"\0")
        tree_fingerprint.update(item["path"].encode("utf-8", errors="surrogateescape"))
        tree_fingerprint.update(b"\0")
        tree_fingerprint.update(item["sha"].encode("ascii"))
        tree_fingerprint.update(b"\n")
    snapshot_fingerprint = tree_fingerprint.hexdigest()

    tree_payload = {
        "resolved_commit_sha": commit_sha,
        "snapshot_fingerprint_sha256": snapshot_fingerprint,
        "tree": [
            {key: value for key, value in item.items() if key != "_raw"}
            for item in blobs
        ],
        "truncated": False,
        "archive_acquisition": True,
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
                "snapshot_fingerprint_sha256": snapshot_fingerprint,
                "acquisition": "exact_commit_codeload_archive",
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    stage("analyze_files")
    output_files: list[dict[str, Any]] = []
    for item in blobs:
        _check_deadline(deadline, repository_url)
        path = item["path"]
        size = int(item.get("size") or 0)
        content = ""
        content_scanned = False

        if _content_is_scannable(path) and size <= max_content_bytes:
            content = item["_raw"].decode("utf-8", errors="replace")
            content_scanned = True
            cached = snapshot_cache / "content" / Path(path)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(content, encoding="utf-8")

        result = analyze_file(path, content)
        encoded_path = quote(path, safe="/")
        file_url = (
            f"https://github.com/{quote(owner)}/{quote(repo)}/blob/"
            f"{quote(commit_sha, safe='')}/{encoded_path}"
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

    stage("complete")
    return {
        "repository": {
            "url": repository_url,
            "full_name": f"{owner}/{repo}",
            "ref": branch,
            "resolved_commit_sha": commit_sha,
            "commit_tree_sha": None,
            "snapshot_fingerprint_sha256": snapshot_fingerprint,
            "file_count": len(output_files),
            "raw_cache_path": str(snapshot_cache),
            "acquisition": "exact_commit_codeload_archive",
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
