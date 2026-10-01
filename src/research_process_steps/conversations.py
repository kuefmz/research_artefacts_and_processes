"""Persist manually attached conversation URLs independently of heuristic results."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from .publication_collection import repository_identity
from .storage import result_id

ConversationVariant = Literal["no_metadata", "research_process_step_metadata"]
VARIANTS = ("no_metadata", "research_process_step_metadata")


def conversation_directory() -> Path:
    return Path(os.getenv("RPS_CONVERSATIONS_DIR", "data/conversation_links"))


def _path(repo_url: str, variant: ConversationVariant) -> Path:
    if variant not in VARIANTS:
        raise ValueError("Unknown conversation variant.")
    return conversation_directory() / f"{result_id(repository_identity(repo_url))}.{variant}.json"


def load_conversations(repo_url: str) -> dict[str, str | None]:
    links = {}
    for variant in VARIANTS:
        try:
            links[variant] = json.loads(_path(repo_url, variant).read_text())["url"]
        except (OSError, ValueError, KeyError):
            links[variant] = None
    return links


def save_conversation(repo_url: str, variant: ConversationVariant, url: str | None) -> None:
    path = _path(repo_url, variant)
    if url is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Separate variant files and unique temporary paths avoid lost updates
    # when two variants are saved concurrently.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump({"url": url}, stream)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
