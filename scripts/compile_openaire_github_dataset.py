"""Compile the local OpenAIRE software.tar into reusable GitHub CSV datasets.

Source archive:
https://zenodo.org/records/12819872/files/software.tar?download=1

The compiler uses the OpenAIRE software field codeRepositoryUrl and keeps only
records whose source-code repository can be normalized to a GitHub repository.

Outputs are DATA ONLY. Manual annotations and validation samples must be created
separately so the same compiled dataset can be shared with other experiments.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

DEFAULT_SOURCE_TAR = Path("data/raw/software.tar")
DEFAULT_OUTPUT_DIR = Path("data/openaire_zenodo_12819872")
COMPILER_VERSION = "1.1.0"

GITHUB_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
GITHUB_RESERVED_ROOTS = {
    "about", "apps", "collections", "contact", "customer-stories", "enterprise",
    "events", "explore", "features", "issues", "join", "login", "marketplace",
    "new", "notifications", "orgs", "organizations", "pricing", "pulls",
    "search", "security", "settings", "site", "sponsors", "topics", "trending",
    "users",
}

RECORD_FIELDS = [
    "openaire_id",
    "type",
    "main_title",
    "sub_title",
    "publication_date",
    "publisher",
    "version",
    "programming_language",
    "authors",
    "pids",
    "code_repository_url_original",
    "github_repository_url",
]

REPOSITORY_FIELDS = [
    "github_repository_url",
    "record_count",
    "representative_title",
    "openaire_ids",
    "programming_languages",
    "publication_dates",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item


def normalize_github_repo_url(value: str) -> str | None:
    """Normalize a GitHub reference to https://github.com/OWNER/REPO."""
    if not value:
        return None

    raw = value.strip().strip("<>[](){}.,;")
    if not raw:
        return None

    if raw.lower().startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
        parts = [part for part in path.split("/") if part]
    else:
        if raw.lower().startswith("git+"):
            raw = raw[4:]
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in {"github.com", "www.github.com"}:
            return None
        parts = [part for part in parsed.path.split("/") if part]

    if len(parts) < 2:
        return None

    owner = parts[0]
    repository = parts[1]
    if repository.lower().endswith(".git"):
        repository = repository[:-4]

    if (
        not owner
        or not repository
        or owner.lower() in GITHUB_RESERVED_ROOTS
        or not GITHUB_COMPONENT_RE.fullmatch(owner)
        or not GITHUB_COMPONENT_RE.fullmatch(repository)
    ):
        return None

    return f"https://github.com/{owner}/{repository}"


def _authors(record: dict[str, Any]) -> str:
    values = record.get("authors")
    if values is None:
        values = record.get("author")

    names: list[str] = []
    if isinstance(values, list):
        for author in values:
            if not isinstance(author, dict):
                continue
            name = (
                author.get("fullName")
                or author.get("fullname")
                or " ".join(
                    part
                    for part in [author.get("name"), author.get("surname")]
                    if part
                )
            )
            if name:
                names.append(str(name).strip())
    return " | ".join(names)


def _pids(record: dict[str, Any]) -> str:
    values = record.get("pids")
    if values is None:
        values = record.get("pid")

    result: list[str] = []
    if isinstance(values, list):
        for pid in values:
            if not isinstance(pid, dict):
                continue
            scheme = pid.get("scheme")
            value = pid.get("value")
            if value:
                result.append(f"{scheme}:{value}" if scheme else str(value))
    return " | ".join(result)


def compact_record(
    record: dict[str, Any],
    original_repo_url: str,
    github_repo_url: str,
) -> dict[str, str]:
    return {
        "openaire_id": str(record.get("id") or ""),
        "type": str(record.get("type") or ""),
        "main_title": str(record.get("mainTitle") or record.get("maintitle") or ""),
        "sub_title": str(record.get("subTitle") or record.get("subtitle") or ""),
        "publication_date": str(
            record.get("publicationDate") or record.get("publicationdate") or ""
        ),
        "publisher": str(record.get("publisher") or ""),
        "version": str(record.get("version") or ""),
        "programming_language": str(
            record.get("programmingLanguage")
            or record.get("programminglanguage")
            or ""
        ),
        "authors": _authors(record),
        "pids": _pids(record),
        "code_repository_url_original": original_repo_url,
        "github_repository_url": github_repo_url,
    }


def iter_software_records(tar_path: Path) -> Iterable[dict[str, Any]]:
    """Stream records from JSON-lines members of the OpenAIRE tar archive."""
    with tarfile.open(tar_path, mode="r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue

            extracted = archive.extractfile(member)
            if extracted is None:
                continue

            print(f"Reading {member.name}", flush=True)
            stream = (
                gzip.GzipFile(fileobj=extracted)
                if member.name.lower().endswith(".gz")
                else extracted
            )

            with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:
                for line_number, line in enumerate(text, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Invalid JSON in {member.name}:{line_number}: {exc}"
                        ) from exc
                    if isinstance(record, dict):
                        yield record


def github_urls_from_record(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Return unique (original URL, normalized GitHub URL) pairs."""
    value = record.get("codeRepositoryUrl")
    if value is None:
        value = record.get("coderepositoryurl")

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for original in _iter_values(value):
        normalized = normalize_github_repo_url(original)
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append((original, normalized))
    return result


def compile_dataset(source_tar: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    records_path = output_dir / "github_software_records.csv"
    repositories_path = output_dir / "github_repositories.csv"
    summary_path = output_dir / "summary.json"
    data_flow_path = output_dir / "data_flow.json"

    total_records = 0
    records_with_code_repo = 0
    github_record_links = 0
    non_github_or_invalid = 0
    repository_records: dict[str, list[dict[str, str]]] = defaultdict(list)

    with records_path.open("w", encoding="utf-8", newline="") as output:
        record_writer = csv.DictWriter(output, fieldnames=RECORD_FIELDS)
        record_writer.writeheader()

        for record in iter_software_records(source_tar):
            total_records += 1

            raw_code_repo = (
                record.get("codeRepositoryUrl")
                if "codeRepositoryUrl" in record
                else record.get("coderepositoryurl")
            )
            raw_values = list(_iter_values(raw_code_repo))
            if raw_values:
                records_with_code_repo += 1

            github_pairs = github_urls_from_record(record)
            if raw_values and not github_pairs:
                non_github_or_invalid += 1

            for original_url, github_url in github_pairs:
                row = compact_record(record, original_url, github_url)
                record_writer.writerow(row)
                repository_records[github_url.lower()].append(row)
                github_record_links += 1

            if total_records % 100_000 == 0:
                print(
                    f"Processed {total_records:,} software records; "
                    f"{github_record_links:,} GitHub links",
                    flush=True,
                )

    repository_rows: list[dict[str, str | int]] = []
    for key in sorted(repository_records):
        grouped = repository_records[key]
        representative = grouped[0]
        repository_rows.append(
            {
                "github_repository_url": representative["github_repository_url"],
                "record_count": len(grouped),
                "representative_title": representative["main_title"],
                "openaire_ids": " | ".join(
                    sorted({row["openaire_id"] for row in grouped if row["openaire_id"]})
                ),
                "programming_languages": " | ".join(
                    sorted(
                        {
                            row["programming_language"]
                            for row in grouped
                            if row["programming_language"]
                        }
                    )
                ),
                "publication_dates": " | ".join(
                    sorted(
                        {
                            row["publication_date"]
                            for row in grouped
                            if row["publication_date"]
                        }
                    )
                ),
            }
        )

    with repositories_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=REPOSITORY_FIELDS)
        writer.writeheader()
        writer.writerows(repository_rows)

    input_sha256 = sha256_file(source_tar)
    records_sha256 = sha256_file(records_path)
    repositories_sha256 = sha256_file(repositories_path)
    generated_at = datetime.now(timezone.utc).isoformat()

    summary = {
        "source": {
            "zenodo_record": "https://zenodo.org/records/12819872",
            "software_tar_filename": source_tar.name,
            "source_tar_size_bytes": source_tar.stat().st_size,
            "sha256": input_sha256,
        },
        "filter": {
            "field": "codeRepositoryUrl",
            "host": "github.com",
            "normalization": "https://github.com/OWNER/REPO",
        },
        "counts": {
            "software_records_total": total_records,
            "records_with_code_repository_url": records_with_code_repo,
            "github_record_links": github_record_links,
            "unique_github_repositories": len(repository_rows),
            "non_github_or_invalid_code_repository_urls": non_github_or_invalid,
        },
        "outputs": {
            "record_level_csv": {
                "path": str(records_path),
                "sha256": records_sha256,
            },
            "repository_level_csv": {
                "path": str(repositories_path),
                "sha256": repositories_sha256,
            },
        },
        "compiler": {
            "script": "scripts/compile_openaire_github_dataset.py",
            "version": COMPILER_VERSION,
            "generated_at_utc": generated_at,
        },
        "annotations": "Not included. Annotation data must be stored separately.",
    }

    data_flow = {
        "pipeline_name": "OpenAIRE software to GitHub repository dataset",
        "pipeline_version": COMPILER_VERSION,
        "generated_at_utc": generated_at,
        "source": {
            "zenodo_record": "https://zenodo.org/records/12819872",
            "archive_filename": source_tar.name,
            "archive_size_bytes": source_tar.stat().st_size,
            "archive_sha256": input_sha256,
        },
        "stages": [
            {
                "stage": 1,
                "name": "read_openaire_software_records",
                "input": "software.tar",
                "operation": (
                    "Stream JSON-lines software records from members of the "
                    "OpenAIRE software archive."
                ),
                "output_count": total_records,
            },
            {
                "stage": 2,
                "name": "select_records_with_code_repository_url",
                "input_count": total_records,
                "operation": (
                    "Keep track of records where the OpenAIRE codeRepositoryUrl "
                    "field is present."
                ),
                "output_count": records_with_code_repo,
            },
            {
                "stage": 3,
                "name": "filter_github_repositories",
                "input_count": records_with_code_repo,
                "operation": (
                    "Accept only codeRepositoryUrl values whose host is github.com "
                    "and which can be parsed as OWNER/REPO."
                ),
                "output_count": github_record_links,
                "rejected_count": non_github_or_invalid,
            },
            {
                "stage": 4,
                "name": "normalize_github_repository_urls",
                "operation": (
                    "Normalize GitHub references to https://github.com/OWNER/REPO; "
                    "remove .git and deep-link path components."
                ),
                "record_level_output": str(records_path),
                "record_level_sha256": records_sha256,
                "output_count": github_record_links,
            },
            {
                "stage": 5,
                "name": "deduplicate_by_normalized_repository_url",
                "input_count": github_record_links,
                "operation": (
                    "Case-insensitive deduplication by normalized GitHub repository "
                    "URL while preserving the OpenAIRE IDs associated with each repo."
                ),
                "repository_level_output": str(repositories_path),
                "repository_level_sha256": repositories_sha256,
                "output_count": len(repository_rows),
            },
        ],
        "separation_of_concerns": {
            "shared_data": "data/openaire_zenodo_12819872/",
            "annotations": "annotations/",
            "rule": (
                "Shared CSV files contain no manual labels. Validation samples and "
                "manual annotations must be derived separately from github_repositories.csv."
            ),
        },
        "reproduce": {
            "command": "python scripts/compile_openaire_github_dataset.py",
            "default_input": str(DEFAULT_SOURCE_TAR),
            "script": "scripts/compile_openaire_github_dataset.py",
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    data_flow_path.write_text(
        json.dumps(data_flow, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary["counts"], indent=2), flush=True)
    print(f"Wrote {records_path}", flush=True)
    print(f"Wrote {repositories_path}", flush=True)
    print(f"Wrote {summary_path}", flush=True)
    print(f"Wrote {data_flow_path}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a local OpenAIRE software.tar into GitHub-linked CSV datasets."
        )
    )
    parser.add_argument(
        "--software-tar",
        type=Path,
        default=DEFAULT_SOURCE_TAR,
        help=f"Input archive (default: {DEFAULT_SOURCE_TAR}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    args = parser.parse_args()

    if not args.software_tar.is_file():
        raise SystemExit(
            f"software.tar not found: {args.software_tar}\n"
            f"Place the downloaded archive at {DEFAULT_SOURCE_TAR} "
            "or override it with --software-tar."
        )

    compile_dataset(args.software_tar, args.output_dir)


if __name__ == "__main__":
    main()
