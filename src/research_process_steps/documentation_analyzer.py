"""Documentation-only repository review and copyable batch score tables."""

from __future__ import annotations
import argparse
import base64
import csv
import io
import json
import os
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from .analyzer import (
    _parse_github_url,
    _request_json,
    DEFAULT_CONTENT_LIMIT,
)
from .documentation import CRITERIA, VERSION, analyze_document, is_documentation


def analyze_documentation_repository(
    repository_url, *, token=None, ref=None, max_content_bytes=DEFAULT_CONTENT_LIMIT
):
    if max_content_bytes < 0:
        raise ValueError("max_content_bytes must be non-negative")
    owner, repo = _parse_github_url(repository_url)
    url = f"https://github.com/{owner}/{repo}"
    api = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    metadata = _request_json(api, token)
    requested = ref or metadata["default_branch"]
    commit = _request_json(f"{api}/commits/{quote(requested, safe='')}", token)["sha"]
    tree = _request_json(f"{api}/git/trees/{commit}?recursive=1", token)
    if tree.get("truncated"):
        raise RuntimeError(
            "Truncated repository tree: documentation coverage is incomplete"
        )
    candidates = [
        x
        for x in tree.get("tree", [])
        if x.get("type") == "blob" and is_documentation(x["path"])
    ]

    def review(item):
        path = item["path"]
        encoded = quote(path, safe="/")
        file_url = f"{url}/blob/{commit}/{encoded}?plain=1"
        record = {"path": path, "file_url": file_url}
        if item.get("size", 0) > max_content_bytes:
            return {**record, "status": "skipped_size_limit", "evidence": []}
        try:
            payload = _request_json(f"{api}/contents/{encoded}?ref={commit}", token)
            if payload.get("encoding") != "base64":
                raise ValueError("GitHub API did not return base64 file content")
            text = base64.b64decode(payload["content"]).decode("utf-8")
            result = analyze_document(path, text)
            for e in result["evidence"]:
                e["url"] = f"{file_url}#L{e['line']}"
                if e["line_end"] != e["line"]:
                    e["url"] += f"-L{e['line_end']}"
            return {**record, **result, "status": "reviewed"}
        except Exception as exc:
            return {**record, "status": "unreadable", "error": str(exc), "evidence": []}

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(review, sorted(candidates, key=lambda x: x["path"])))
    evidence = [e for d in records for e in d["evidence"]]
    incomplete = any(d["status"] != "reviewed" for d in records)
    scores = {
        c: 1
        if any(e["criterion"] == c for e in evidence)
        else "Unverified"
        if incomplete
        else 0
        for c in CRITERIA
    }
    return {
        "repository": {"url": url, "commit": commit, "ref": requested},
        "method": {
            "name": "documentation_only_heuristics",
            "version": VERSION,
            "uses_ai": False,
        },
        "scores": scores,
        "coverage": "partial" if incomplete else "complete",
        "documents": records,
    }


def markdown_table(results):
    rows = [
        "| GitHub URL | Collection | Processing | Method | Experimentation | Evaluation | Dissemination |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        url = result["repository"]["url"]
        rows.append(
            f"| [{url}]({url}) | "
            + " | ".join(str(result["scores"][c]) for c in CRITERIA)
            + " |"
        )
    return "\n".join(rows)


def csv_table(results):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Repository", *(c.title() for c in CRITERIA)])
    for result in results:
        writer.writerow(
            [result["repository"]["url"], *(result["scores"][c] for c in CRITERIA)]
        )
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(
        description="Score research lifecycle documentation only; never fetch implementation files."
    )
    parser.add_argument("repositories", nargs="*")
    parser.add_argument(
        "--repos-file", type=Path, help="UTF-8 file with one repository URL per line"
    )
    parser.add_argument(
        "--format", choices=["markdown", "csv", "json"], default="markdown"
    )
    parser.add_argument("--ref")
    parser.add_argument("--max-content-bytes", type=int, default=DEFAULT_CONTENT_LIMIT)
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    urls = list(args.repositories)
    if args.repos_file:
        urls += [
            s.strip()
            for s in args.repos_file.read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.lstrip().startswith("#")
        ]
    if not urls:
        parser.error("Supply repository URLs or --repos-file")
    if args.max_content_bytes < 0:
        parser.error("--max-content-bytes must be non-negative")
    results = []
    for url in dict.fromkeys(urls):
        try:
            results.append(
                analyze_documentation_repository(
                    url,
                    token=args.token,
                    ref=args.ref,
                    max_content_bytes=args.max_content_bytes,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "repository": {"url": url},
                    "scores": dict.fromkeys(CRITERIA, "Unverified"),
                    "coverage": "unverified",
                    "error": str(exc),
                }
            )
    rendered = (
        markdown_table(results)
        if args.format == "markdown"
        else csv_table(results)
        if args.format == "csv"
        else json.dumps(results, indent=2, ensure_ascii=False)
    )
    if args.output:
        args.output.write_text(rendered.rstrip("\r\n") + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
