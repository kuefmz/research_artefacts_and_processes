"""Persistent result store for repository-level heuristic executions.

A normalized GitHub repository URL is the identity key. Once a result exists for
that repository, callers must reuse it rather than execute the repository again.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RESULTS_DIR = Path("data/heuristic_results")


def normalize_repo_url(repo_url: str) -> str:
    """Return the stable repository identity used by the result store."""
    value = repo_url.strip().rstrip("/")
    if value.lower().endswith(".git"):
        value = value[:-4]
    return value.lower()


def results_dir() -> Path:
    return Path(os.getenv("RPS_RESULTS_DIR", str(DEFAULT_RESULTS_DIR)))


def result_id(repo_url: str) -> str:
    return hashlib.sha256(normalize_repo_url(repo_url).encode("utf-8")).hexdigest()[:20]


def result_path(repo_url: str) -> Path:
    return results_dir() / f"{result_id(repo_url)}.json"


def metadata_path(repo_url: str) -> Path:
    return results_dir() / f"{result_id(repo_url)}.meta.json"


def lock_path(repo_url: str) -> Path:
    return results_dir() / f"{result_id(repo_url)}.lock"


def load_result(repo_url: str) -> dict[str, Any] | None:
    path = result_path(repo_url)
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
        "scope": "repository",
    }
    return payload


def load_result_by_id(execution_id: str) -> dict[str, Any] | None:
    if not execution_id or any(ch not in "0123456789abcdef" for ch in execution_id.lower()):
        return None
    path = results_dir() / f"{execution_id}.json"
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
        "scope": "repository",
    }
    return payload


def acquire_execution(repo_url: str) -> bool:
    """Acquire an exclusive cross-process lock for one repository."""
    directory = results_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = lock_path(repo_url)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def release_execution(repo_url: str) -> None:
    try:
        lock_path(repo_url).unlink()
    except FileNotFoundError:
        pass


def save_result(repo_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a completed execution and its lightweight history metadata."""
    directory = results_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = result_path(repo_url)
    execution_id = result_id(repo_url)
    now = datetime.now(timezone.utc).isoformat()

    stored = dict(payload)
    stored["execution"] = {
        "id": execution_id,
        "repo_key": normalize_repo_url(repo_url),
        "executed_at": now,
    }
    stored["cache"] = {
        "hit": False,
        "persistent": True,
        "path": str(path),
        "scope": "repository",
    }

    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(stored, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)

    repository = stored.get("repository", {})
    summary = stored.get("summary", {})
    meta = {
        "id": execution_id,
        "repo_url": repository.get("url") or repo_url,
        "full_name": repository.get("full_name") or normalize_repo_url(repo_url),
        "ref": repository.get("ref"),
        "file_count": repository.get("file_count", 0),
        "files_per_step": summary.get("files_per_step", {}),
        "unclassified_files": summary.get("unclassified_files", 0),
        "executed_at": now,
    }
    metadata_path(repo_url).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return stored


def list_executions() -> list[dict[str, Any]]:
    directory = results_dir()
    if not directory.exists():
        return []

    items: list[dict[str, Any]] = []
    for path in directory.glob("*.meta.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(item)

    items.sort(key=lambda item: item.get("executed_at", ""), reverse=True)
    return items
