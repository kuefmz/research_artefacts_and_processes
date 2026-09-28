"""GitHub repository analyzer using deterministic heuristics only."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .heuristics import (
    CONTENT_EXTENSIONS,
    EXCLUDED_PROCESS_STEP_EXTENSIONS,
    IMPLEMENTATION_COMPATIBLE_ARTIFACT_KINDS,
    IMPLEMENTATION_GENERIC_RULES,
    RESEARCH_PROCESS_STEPS,
    RULES,
    infer_artifact_kind,
)


DEFAULT_CONTENT_LIMIT = 250_000
DEFAULT_RAW_CACHE_DIR = Path("data/github_cache")
DETECTION_THRESHOLD = 2
USER_AGENT = "research-process-steps/0.1"
MAX_MATCHES_PER_RULE = 20
MAX_CONTENT_WORKERS = max(1, int(os.getenv("RPS_CONTENT_WORKERS", "1")))

class RepositoryTimeoutError(RuntimeError):
    """Raised when a repository exceeds its allowed processing time."""


class GitHubRateLimitError(RuntimeError):
    """Signal a GitHub primary/secondary rate limit to the batch coordinator."""

    def __init__(
        self,
        *,
        wait_seconds: int,
        status_code: int,
        url: str,
        remaining: str | None = None,
        reset: str | None = None,
        retry_after: str | None = None,
    ) -> None:
        self.wait_seconds = max(1, int(wait_seconds))
        self.status_code = status_code
        self.url = url
        self.remaining = remaining
        self.reset = reset
        self.retry_after = retry_after
        super().__init__(
            f"GitHub rate limit ({status_code}); wait {self.wait_seconds}s before retrying."
        )


def _check_deadline(deadline: float | None, repository_url: str = "") -> None:
    if deadline is not None and time.monotonic() >= deadline:
        suffix = f" for {repository_url}" if repository_url else ""
        raise RepositoryTimeoutError(f"Repository processing exceeded its time limit{suffix}.")


def _remaining_timeout(deadline: float | None, default: int = 30) -> float:
    if deadline is None:
        return float(default)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RepositoryTimeoutError("Repository processing exceeded its time limit.")
    return max(0.1, min(float(default), remaining))



def _parse_github_url(repository_url: str) -> tuple[str, str]:
    parsed = urlparse(repository_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Expected a github.com repository URL.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Expected a GitHub URL in the form https://github.com/OWNER/REPO.")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError("Could not determine repository owner and name.")
    return owner, repo


def _rate_limit_wait_seconds(
    exc: HTTPError,
    attempt: int,
    detail: str = "",
) -> int | None:
    """Return a retry delay only when a 403/429 is actually rate limiting."""
    if exc.code == 429:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(retry_after))
            except ValueError:
                pass
        return min(60 * (2 ** attempt), 15 * 60)

    if exc.code != 403:
        return None

    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1, int(retry_after))
        except ValueError:
            pass

    remaining = exc.headers.get("X-RateLimit-Remaining")
    reset = exc.headers.get("X-RateLimit-Reset")
    if remaining == "0":
        if reset:
            try:
                return max(1, int(reset) - int(time.time()) + 5)
            except ValueError:
                pass
        return min(60 * (2 ** attempt), 15 * 60)

    lowered = detail.lower()
    if "secondary rate limit" in lowered or "rate limit exceeded" in lowered:
        return min(60 * (2 ** attempt), 15 * 60)

    # A plain 403 can mean repository/access permissions. Do not globally pause.
    return None


def _request_json(url: str, token: str | None = None, *, deadline: float | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    for attempt in range(5):
        _check_deadline(deadline)
        try:
            with urlopen(request, timeout=_remaining_timeout(deadline, 30)) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            wait_seconds = _rate_limit_wait_seconds(exc, attempt, detail)
            if wait_seconds is not None:
                raise GitHubRateLimitError(
                    wait_seconds=wait_seconds,
                    status_code=exc.code,
                    url=url,
                    remaining=exc.headers.get("X-RateLimit-Remaining"),
                    reset=exc.headers.get("X-RateLimit-Reset"),
                    retry_after=exc.headers.get("Retry-After"),
                ) from exc
            raise RuntimeError(f"GitHub request failed ({exc.code}): {detail}") from exc
    raise RuntimeError("GitHub request failed after retries.")


def _request_bytes(
    url: str,
    token: str | None = None,
    *,
    deadline: float | None = None,
) -> bytes:
    """Fetch non-API bytes without consuming GitHub REST-core quota."""
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    _check_deadline(deadline)
    try:
        with urlopen(request, timeout=_remaining_timeout(deadline, 60)) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        wait_seconds = _rate_limit_wait_seconds(exc, 0, detail)
        if wait_seconds is not None:
            raise GitHubRateLimitError(
                wait_seconds=wait_seconds,
                status_code=exc.code,
                url=url,
                remaining=exc.headers.get("X-RateLimit-Remaining"),
                reset=exc.headers.get("X-RateLimit-Reset"),
                retry_after=exc.headers.get("Retry-After"),
            ) from exc
        raise RuntimeError(f"GitHub archive request failed ({exc.code}): {detail}") from exc


def _request_text(url: str, token: str | None = None, *, deadline: float | None = None) -> str:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    for attempt in range(5):
        _check_deadline(deadline)
        try:
            with urlopen(request, timeout=_remaining_timeout(deadline, 30)) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            wait_seconds = _rate_limit_wait_seconds(exc, attempt, detail)
            if wait_seconds is not None:
                raise GitHubRateLimitError(
                    wait_seconds=wait_seconds,
                    status_code=exc.code,
                    url=url,
                    remaining=exc.headers.get("X-RateLimit-Remaining"),
                    reset=exc.headers.get("X-RateLimit-Reset"),
                    retry_after=exc.headers.get("Retry-After"),
                ) from exc
            raise RuntimeError(f"GitHub content request failed ({exc.code}): {detail}") from exc
    raise RuntimeError("GitHub content request failed after retries.")



def _git_blob_sha(data: bytes) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _archive_tree_snapshot(
    *,
    owner: str,
    repo: str,
    ref: str,
    expected_root_tree_sha: str,
    snapshot_cache: Path,
    max_content_bytes: int,
    token: str | None,
    deadline: float | None,
) -> tuple[dict[str, Any], dict[str, tuple[str, bool]]]:
    """Reconstruct an exact Git tree from one codeload archive.

    The reconstructed root tree SHA must equal GitHub's already-returned root
    tree SHA. If it does not, the caller must fall back to the API tree walk.
    This makes the optimization result-preserving rather than approximate.
    """
    archive_url = (
        "https://codeload.github.com/"
        f"{quote(owner)}/{quote(repo)}/tar.gz/{quote(ref, safe='')}"
    )
    archive_bytes = _request_bytes(archive_url, token, deadline=deadline)

    blobs: dict[str, dict[str, Any]] = {}
    content_by_path: dict[str, tuple[str, bool]] = {}

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
            _check_deadline(deadline)
            if not member.name.startswith(root_prefix):
                continue
            path = member.name[len(root_prefix):].rstrip("/")
            if not path or member.isdir():
                continue
            if not (member.isfile() or member.issym() or member.islnk()):
                continue

            if member.issym():
                data = member.linkname.encode("utf-8")
                mode = "120000"
            else:
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"Could not read archive member: {path}")
                data = extracted.read()
                mode = "100755" if (member.mode & 0o111) else "100644"

            blob_sha = _git_blob_sha(data)
            blobs[path] = {
                "path": path,
                "mode": mode,
                "type": "blob",
                "sha": blob_sha,
                "size": len(data),
            }

            if _content_is_scannable(path) and len(data) <= max_content_bytes:
                decoded = data.decode("utf-8", errors="replace")
                content_by_path[path] = (decoded, True)
                cached_content_path = snapshot_cache / "content" / Path(path)
                cached_content_path.parent.mkdir(parents=True, exist_ok=True)
                cached_content_path.write_text(decoded, encoding="utf-8")

    # Build a nested directory structure and compute Git tree object SHAs
    # bottom-up. Matching the expected root SHA proves path/content/mode
    # equivalence with the Git tree returned by GitHub.
    root: dict[str, Any] = {"files": {}, "dirs": {}}
    for path, blob in blobs.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node["dirs"].setdefault(part, {"files": {}, "dirs": {}})
        node["files"][parts[-1]] = blob

    collected: list[dict[str, Any]] = []

    def build_tree(node: dict[str, Any], prefix: str = "") -> str:
        entries: list[tuple[bytes, str, str, str, int | None]] = []

        for name, child in node["dirs"].items():
            child_prefix = f"{prefix}/{name}" if prefix else name
            sha = build_tree(child, child_prefix)
            entries.append(
                ((name + "/").encode("utf-8"), name, "40000", sha, None)
            )

        for name, blob in node["files"].items():
            entries.append(
                (
                    name.encode("utf-8"),
                    name,
                    blob["mode"],
                    blob["sha"],
                    blob["size"],
                )
            )

        entries.sort(key=lambda item: item[0])
        body = bytearray()
        for _, name, mode, sha, _size in entries:
            body.extend(f"{mode} {name}\0".encode("utf-8"))
            body.extend(bytes.fromhex(sha))

        digest = hashlib.sha1()
        digest.update(f"tree {len(body)}\0".encode("ascii"))
        digest.update(body)
        tree_sha = digest.hexdigest()

        for _, name, mode, sha, size in entries:
            full_path = f"{prefix}/{name}" if prefix else name
            if mode == "40000":
                collected.append(
                    {
                        "path": full_path,
                        "mode": mode,
                        "type": "tree",
                        "sha": sha,
                    }
                )
            else:
                collected.append(
                    {
                        "path": full_path,
                        "mode": mode,
                        "type": "blob",
                        "sha": sha,
                        "size": size,
                    }
                )
        return tree_sha

    reconstructed_root_sha = build_tree(root)
    if reconstructed_root_sha != expected_root_tree_sha:
        raise RuntimeError(
            "Archive snapshot did not reconstruct the exact Git tree "
            f"(expected {expected_root_tree_sha}, got {reconstructed_root_sha})."
        )

    return (
        {
            "sha": reconstructed_root_sha,
            "tree": collected,
            "truncated": False,
            "archive_reconstructed": True,
        },
        content_by_path,
    )


def _walk_git_tree(
    api_base: str,
    root_tree_sha: str,
    token: str | None,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Fetch a complete Git tree without GitHub's recursive-tree truncation."""
    collected: list[dict[str, Any]] = []
    stack: list[tuple[str, str]] = [("", root_tree_sha)]

    while stack:
        _check_deadline(deadline)
        prefix, tree_sha = stack.pop()
        tree = _request_json(
            f"{api_base}/git/trees/{quote(tree_sha, safe='')}",
            token,
            deadline=deadline,
        )
        for item in tree.get("tree", []):
            name = item.get("path", "")
            full_path = f"{prefix}/{name}" if prefix else name
            normalized = dict(item)
            normalized["path"] = full_path
            collected.append(normalized)

            if item.get("type") == "tree" and item.get("sha"):
                stack.append((full_path, item["sha"]))

    return {
        "sha": root_tree_sha,
        "url": f"{api_base}/git/trees/{root_tree_sha}",
        "tree": collected,
        "truncated": False,
        "walked_non_recursive": True,
    }


def _cache_repo_dir(owner: str, repo: str, cache_root: Path) -> Path:
    safe_owner = owner.replace("/", "_")
    safe_repo = repo.replace("/", "_")
    return cache_root / f"{safe_owner}__{safe_repo}"


def _cache_snapshot_dir(repo_dir: Path, ref: str) -> Path:
    ref_key = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:12]
    return repo_dir / ref_key


def _read_json_cache(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _content_is_scannable(path: str) -> bool:
    name = Path(path).name.lower()
    suffix = Path(name).suffix.lower()
    if suffix in EXCLUDED_PROCESS_STEP_EXTENSIONS:
        return False
    if name in {"dockerfile", "makefile"}:
        return True
    return suffix in CONTENT_EXTENSIONS


def _unique_matches(rule, haystack: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in rule.pattern.finditer(haystack):
        value = match.group(0)[:160]
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        line = None
        if rule.source == "content":
            line = haystack.count("\n", 0, match.start()) + 1
        values.append({"text": value, "line": line})
        if len(values) >= MAX_MATCHES_PER_RULE:
            break
    return values


def analyze_file(path: str, content: str = "") -> dict[str, Any]:
    """Classify one repository file using explicit deterministic rules.

    A process step is emitted when its accumulated evidence score reaches the
    detection threshold. Content-only indicators are intentionally weak; this
    prevents a single incidental word from assigning a research step.
    """

    artifact_kind = infer_artifact_kind(path)
    suffix = Path(path).suffix.lower()

    if suffix in EXCLUDED_PROCESS_STEP_EXTENSIONS:
        return {
            "path": path,
            "artifact_kind": artifact_kind,
            "steps": [],
            "unclassified": True,
            "scores": {},
            "evidence": [],
            "suppressed_evidence": [
                {
                    "rule_id": "GLOBAL_STRUCTURED_DATA_EXCLUSION",
                    "step": None,
                    "source": "file_type",
                    "artifact_kind": artifact_kind,
                    "reason": (
                        f"Excluded {suffix!r} file from all research-process-step "
                        "classification because it is structured data, metadata, "
                        "or configuration."
                    ),
                }
            ],
        }

    scores = {step: 0 for step in RESEARCH_PROCESS_STEPS}
    evidence: list[dict[str, Any]] = []
    suppressed_evidence: list[dict[str, Any]] = []

    for rule in RULES:
        haystack = path if rule.source == "path" else content
        if not haystack:
            continue

        matches = _unique_matches(rule, haystack)
        if not matches:
            continue

        if (
            rule.id in IMPLEMENTATION_GENERIC_RULES
            and artifact_kind not in IMPLEMENTATION_COMPATIBLE_ARTIFACT_KINDS
        ):
            suppressed_evidence.append(
                {
                    "rule_id": rule.id,
                    "step": rule.step,
                    "source": rule.source,
                    "artifact_kind": artifact_kind,
                    "reason": (
                        f"Suppressed because {artifact_kind!r} files are not "
                        "compatible with this generic implementation rule."
                    ),
                }
            )
            continue

        matched_texts = [match["text"] for match in matches]
        scores[rule.step] += rule.weight
        evidence.append(
            {
                "rule_id": rule.id,
                "step": rule.step,
                "source": rule.source,
                "weight": rule.weight,
                "matched_text": matched_texts[0],
                "matched_texts": matched_texts,
                "matches": matches,
                "description": rule.description,
            }
        )

    detected = [
        step for step in RESEARCH_PROCESS_STEPS if scores[step] >= DETECTION_THRESHOLD
    ]
    return {
        "path": path,
        "artifact_kind": artifact_kind,
        "steps": detected,
        "unclassified": not detected,
        "scores": {step: score for step, score in scores.items() if score},
        "evidence": evidence,
        "suppressed_evidence": suppressed_evidence,
    }


def analyze_github_repository(
    repository_url: str,
    *,
    token: str | None = None,
    ref: str | None = None,
    max_content_bytes: int = DEFAULT_CONTENT_LIMIT,
    raw_cache_dir: Path | str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Analyze a GitHub repository and persist reusable raw inputs locally."""

    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else None
    )
    _check_deadline(deadline, repository_url)
    owner, repo = _parse_github_url(repository_url)
    api_base = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    cache_root = Path(
        raw_cache_dir
        or os.getenv("RPS_RAW_CACHE_DIR", str(DEFAULT_RAW_CACHE_DIR))
    )
    repo_cache = _cache_repo_dir(owner, repo, cache_root)

    metadata_path = repo_cache / "metadata.json"
    metadata = _read_json_cache(metadata_path)
    if metadata is None:
        metadata = _request_json(api_base, token, deadline=deadline)
        _write_json_cache(metadata_path, metadata)

    chosen_ref = ref or metadata["default_branch"]
    snapshot_cache = _cache_snapshot_dir(repo_cache, chosen_ref)
    manifest_path = snapshot_cache / "manifest.json"
    tree_path = snapshot_cache / "tree.json"

    archive_content_by_path: dict[str, tuple[str, bool]] = {}

    tree = _read_json_cache(tree_path)
    if tree is None:
        tree_url = f"{api_base}/git/trees/{quote(chosen_ref, safe='')}?recursive=1"
        tree = _request_json(tree_url, token, deadline=deadline)
        _write_json_cache(tree_path, tree)
        _write_json_cache(
            manifest_path,
            {
                "repository_url": repository_url,
                "full_name": f"{owner}/{repo}",
                "ref": chosen_ref,
                "tree_sha": tree.get("sha"),
            },
        )
    if tree.get("truncated"):
        # A recursive GitHub tree can truncate for large repositories. First try
        # one codeload archive (non-REST) and reconstruct the exact Git tree
        # locally. We only accept it if the reconstructed root SHA is identical
        # to GitHub's root tree SHA. Otherwise we retain the original API walk.
        expected_tree_sha = tree.get("sha")
        try:
            if not expected_tree_sha:
                raise RuntimeError("Truncated tree did not include a root SHA.")
            tree, archive_content_by_path = _archive_tree_snapshot(
                owner=owner,
                repo=repo,
                ref=chosen_ref,
                expected_root_tree_sha=expected_tree_sha,
                snapshot_cache=snapshot_cache,
                max_content_bytes=max_content_bytes,
                token=token,
                deadline=deadline,
            )
            tree_traversal = "verified_archive_fallback"
        except (RepositoryTimeoutError, GitHubRateLimitError):
            raise
        except Exception:
            tree = _walk_git_tree(
                api_base,
                expected_tree_sha or chosen_ref,
                token,
                deadline=deadline,
            )
            archive_content_by_path = {}
            tree_traversal = "non_recursive_api_fallback"

        _write_json_cache(tree_path, tree)
        _write_json_cache(
            manifest_path,
            {
                "repository_url": repository_url,
                "full_name": f"{owner}/{repo}",
                "ref": chosen_ref,
                "tree_sha": tree.get("sha"),
                "tree_traversal": tree_traversal,
            },
        )

    files = [item for item in tree.get("tree", []) if item.get("type") == "blob"]
    sorted_files = sorted(files, key=lambda value: value["path"].lower())

    def fetch_content(item: dict[str, Any]) -> tuple[str, str, bool]:
        _check_deadline(deadline, repository_url)
        path = item["path"]
        size = int(item.get("size") or 0)
        if not (_content_is_scannable(path) and size <= max_content_bytes):
            return path, "", False

        cached_content_path = snapshot_cache / "content" / Path(path)
        if cached_content_path.exists():
            try:
                return path, cached_content_path.read_text(encoding="utf-8"), True
            except OSError:
                pass

        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        raw_url = (
            "https://raw.githubusercontent.com/"
            f"{quote(owner)}/{quote(repo)}/{quote(chosen_ref, safe='')}/{encoded_path}"
        )
        try:
            file_content = _request_text(raw_url, token, deadline=deadline)
            cached_content_path.parent.mkdir(parents=True, exist_ok=True)
            cached_content_path.write_text(file_content, encoding="utf-8")
            return path, file_content, True
        except RepositoryTimeoutError:
            raise
        except Exception:
            return path, "", False

    content_by_path: dict[str, tuple[str, bool]] = {
        item["path"]: archive_content_by_path.get(item["path"], ("", False))
        for item in sorted_files
    }
    scannable = [
        item
        for item in sorted_files
        if _content_is_scannable(item["path"])
        and int(item.get("size") or 0) <= max_content_bytes
    ]

    scannable_to_fetch = [
        item
        for item in scannable
        if not content_by_path.get(item["path"], ("", False))[1]
    ]

    if MAX_CONTENT_WORKERS == 1:
        for item in scannable_to_fetch:
            _check_deadline(deadline, repository_url)
            path, file_content, content_scanned = fetch_content(item)
            content_by_path[path] = (file_content, content_scanned)
    else:
        with ThreadPoolExecutor(max_workers=MAX_CONTENT_WORKERS) as executor:
            futures = [executor.submit(fetch_content, item) for item in scannable_to_fetch]
            for future in as_completed(futures):
                _check_deadline(deadline, repository_url)
                path, file_content, content_scanned = future.result()
                content_by_path[path] = (file_content, content_scanned)

    output_files: list[dict[str, Any]] = []
    for item in sorted_files:
        _check_deadline(deadline, repository_url)
        path = item["path"]
        size = int(item.get("size") or 0)
        file_content, content_scanned = content_by_path[path]

        result = analyze_file(path, file_content)
        encoded_web_path = quote(path, safe="/")
        file_url = (
            f"https://github.com/{quote(owner)}/{quote(repo)}/blob/"
            f"{quote(chosen_ref, safe='')}/{encoded_web_path}"
        )
        for evidence_item in result["evidence"]:
            for match in evidence_item.get("matches", []):
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
                "ref": chosen_ref,
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
            "ref": chosen_ref,
            "commit_tree_sha": tree.get("sha"),
            "file_count": len(output_files),
            "raw_cache_path": str(snapshot_cache),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Identify research process steps for every file in a GitHub repository "
            "using deterministic heuristics only."
        )
    )
    parser.add_argument("repository_url", help="GitHub repository URL")
    parser.add_argument("--ref", help="Branch, tag, or commit; defaults to default branch")
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub token; defaults to GITHUB_TOKEN",
    )
    parser.add_argument(
        "--max-content-bytes",
        type=int,
        default=DEFAULT_CONTENT_LIMIT,
        help="Maximum file size for optional content-rule scanning",
    )
    parser.add_argument("-o", "--output", help="Write JSON output to this path")
    args = parser.parse_args()

    result = analyze_github_repository(
        args.repository_url,
        token=args.token,
        ref=args.ref,
        max_content_bytes=args.max_content_bytes,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
