"""Persist timestamped C0/C1 reproducibility conversation links per paper."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

PaperConversationVariant = Literal["c0", "c1"]
VARIANTS: tuple[PaperConversationVariant, ...] = ("c0", "c1")
_PAPER_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def conversation_directory() -> Path:
    return Path(
        os.getenv(
            "RPS_REPRO_CONVERSATIONS_DIR",
            "data/reproducibility_conversations",
        )
    )


def _path(paper_id: str) -> Path:
    if not _PAPER_ID.fullmatch(paper_id):
        raise ValueError("Invalid paper id.")
    return conversation_directory() / f"{paper_id}.json"


def _empty(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "records": {variant: [] for variant in VARIANTS},
    }


def load_paper_conversations(paper_id: str) -> dict[str, list[dict[str, str]]]:
    path = _path(paper_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = _empty(paper_id)

    records = payload.get("records", {})
    normalized: dict[str, list[dict[str, str]]] = {}
    for variant in VARIANTS:
        values = records.get(variant, [])
        normalized[variant] = [
            {
                "id": str(item.get("id", "")),
                "url": str(item.get("url", "")),
                "created_at": str(item.get("created_at", "")),
                "updated_at": str(item.get("updated_at", "")),
            }
            for item in values
            if isinstance(item, dict) and item.get("id") and item.get("url")
        ]
    return normalized


def _write(paper_id: str, records: dict[str, list[dict[str, str]]]) -> None:
    path = _path(paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"paper_id": paper_id, "records": records}
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def add_paper_conversation(
    paper_id: str,
    variant: PaperConversationVariant,
    url: str,
) -> dict[str, str]:
    if variant not in VARIANTS:
        raise ValueError("Unknown conversation variant.")
    records = load_paper_conversations(paper_id)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": uuid4().hex,
        "url": url,
        "created_at": now,
        "updated_at": now,
    }
    records[variant].append(record)
    _write(paper_id, records)
    return record


def update_paper_conversation(
    paper_id: str,
    variant: PaperConversationVariant,
    record_id: str,
    url: str,
) -> dict[str, str]:
    if variant not in VARIANTS:
        raise ValueError("Unknown conversation variant.")
    records = load_paper_conversations(paper_id)
    for record in records[variant]:
        if record["id"] == record_id:
            record["url"] = url
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write(paper_id, records)
            return record
    raise KeyError(record_id)
