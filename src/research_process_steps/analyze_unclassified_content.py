"""Inspect cached contents of unclassified source files without GitHub requests.

The command joins completed heuristic results with the local GitHub raw-content
cache. It reports what unclassified source files appear to contain, which weak
heuristic signals they already have, and which recurring filenames/imports/
symbols/keywords may deserve manual review or new deterministic rules.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .heuristics import RESEARCH_PROCESS_STEPS, SOURCE_CODE_EXTENSIONS
from .storage import DEFAULT_RESULTS_DIR

DEFAULT_RAW_CACHE_DIR = Path("data/github_cache")
DEFAULT_OUTPUT_DIR = Path("data/analysis_unclassified_content")
MAX_SAMPLE_FILES = 500

COMMON_KEYWORDS = (
    "load", "read", "download", "fetch", "scrape", "crawl", "collect",
    "clean", "preprocess", "process", "transform", "normalize", "parse",
    "extract", "train", "fit", "predict", "model", "experiment", "trial",
    "sweep", "evaluate", "evaluation", "benchmark", "metric", "accuracy",
    "precision", "recall", "f1", "plot", "visualize", "report", "export",
    "save", "write", "simulate", "simulation", "optimize", "analysis",
)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _repo_cache_dir(raw_cache_dir: Path, full_name: str) -> Path:
    owner, repo = (full_name.split("/", 1) + [""])[:2]
    return raw_cache_dir / f"{owner.replace('/', '_')}__{repo.replace('/', '_')}"


def _snapshot_dir(repo_cache_dir: Path, ref: str) -> Path:
    ref_key = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:12]
    return repo_cache_dir / ref_key


def _cached_content_path(
    raw_cache_dir: Path,
    full_name: str,
    ref: str,
    file_path: str,
) -> Path:
    return _snapshot_dir(_repo_cache_dir(raw_cache_dir, full_name), ref) / "content" / Path(file_path)


def _python_symbols_and_imports(text: str) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    symbols: list[str] = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return imports, symbols

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    return imports, symbols


def _generic_imports(text: str, extension: str) -> list[str]:
    patterns: list[str] = []
    if extension in {".js", ".ts", ".tsx", ".jsx"}:
        patterns = [
            r"\bfrom\s+['\"]([^'\"]+)['\"]",
            r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"\bimport\s+['\"]([^'\"]+)['\"]",
        ]
    elif extension in {".r"}:
        patterns = [r"\b(?:library|require)\s*\(\s*['\"]?([A-Za-z0-9_.]+)"]
    elif extension in {".java", ".kt", ".kts"}:
        patterns = [r"^\s*import\s+([A-Za-z0-9_.]+)"]
    elif extension in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
        patterns = [r"^\s*#\s*include\s*[<\"]([^>\"]+)"]
    elif extension == ".go":
        patterns = [r"^\s*import\s+['\"]([^'\"]+)['\"]"]
    elif extension in {".php"}:
        patterns = [r"\b(?:require|require_once|include|include_once)\s*\(?\s*['\"]([^'\"]+)"]
    elif extension in {".sh", ".bash"}:
        patterns = [r"^\s*(?:source|\.)\s+([^\s#]+)"]

    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            values.append(match.group(1).split("/")[0])
    return values


def _generic_symbols(text: str, extension: str) -> list[str]:
    patterns = [
        r"\b(?:def|function|func|subroutine)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    if extension in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs", ".java"}:
        patterns.append(
            r"^[A-Za-z_][A-Za-z0-9_:<>\[\]\s*&]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
        )
    values: list[str] = []
    for pattern in patterns:
        values.extend(
            m.group(1)
            for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
        )
    return values


def _first_meaningful_lines(text: str, limit: int = 5) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lines.append(stripped[:220])
        if len(lines) >= limit:
            break
    return " | ".join(lines)


def analyze_unclassified_content(
    results_dir: Path,
    raw_cache_dir: Path,
    output_dir: Path,
    sample_limit: int = MAX_SAMPLE_FILES,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    filenames: Counter[str] = Counter()
    directories: Counter[str] = Counter()
    imports: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    near_miss_steps: Counter[str] = Counter()
    near_miss_rules: Counter[str] = Counter()

    total_unclassified_source = 0
    cached_content_files = 0
    uncached_content_files = 0
    total_loc = 0
    samples: list[dict[str, Any]] = []

    for result_path in sorted(results_dir.glob("*.json")):
        if result_path.name.endswith(".meta.json"):
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        repository = result.get("repository", {})
        full_name = str(repository.get("full_name") or "")
        ref = str(repository.get("ref") or "")
        if not full_name or not ref:
            continue

        for record in result.get("files", []):
            if not isinstance(record, dict):
                continue
            path = str(record.get("path") or "")
            extension = Path(path).suffix.lower()
            steps = record.get("steps") or []
            if extension not in SOURCE_CODE_EXTENSIONS:
                continue
            if not record.get("unclassified", not steps):
                continue

            total_unclassified_source += 1
            extensions[extension] += 1
            filenames[Path(path).name.lower()] += 1
            parent = str(Path(path).parent)
            directories[parent if parent != "." else "(root)"] += 1

            scores = record.get("scores") or {}
            if isinstance(scores, dict):
                for step, score in scores.items():
                    try:
                        numeric_score = float(score)
                    except (TypeError, ValueError):
                        continue
                    if 0 < numeric_score < 2:
                        near_miss_steps[str(step)] += 1

            for evidence in record.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                try:
                    weight = float(evidence.get("weight", 0))
                except (TypeError, ValueError):
                    weight = 0
                if 0 < weight < 2 and evidence.get("rule_id"):
                    near_miss_rules[str(evidence["rule_id"])] += 1

            cache_path = _cached_content_path(raw_cache_dir, full_name, ref, path)
            if not cache_path.exists():
                uncached_content_files += 1
                continue

            try:
                text = cache_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                uncached_content_files += 1
                continue

            cached_content_files += 1
            loc = len(text.splitlines())
            total_loc += loc

            if extension == ".py":
                file_imports, file_symbols = _python_symbols_and_imports(text)
            else:
                file_imports = _generic_imports(text, extension)
                file_symbols = _generic_symbols(text, extension)

            imports.update(value.lower() for value in file_imports if value)
            symbols.update(value.lower() for value in file_symbols if value)

            lower_text = text.lower()
            present_keywords = [
                keyword for keyword in COMMON_KEYWORDS
                if re.search(rf"\b{re.escape(keyword)}\b", lower_text)
            ]
            keywords.update(present_keywords)

            if len(samples) < sample_limit:
                samples.append(
                    {
                        "repository": full_name,
                        "ref": ref,
                        "path": path,
                        "extension": extension,
                        "loc": loc,
                        "scores": json.dumps(scores, sort_keys=True),
                        "imports": ";".join(sorted(set(file_imports))[:25]),
                        "symbols": ";".join(sorted(set(file_symbols))[:25]),
                        "keywords": ";".join(present_keywords),
                        "preview": _first_meaningful_lines(text),
                        "cache_path": str(cache_path),
                    }
                )

    def counter_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: name, "count": count} for name, count in counter.most_common()]

    _write_csv(output_dir / "filename_patterns.csv", counter_rows(filenames, "filename"),
               ["filename", "count"])
    _write_csv(output_dir / "directory_patterns.csv", counter_rows(directories, "directory"),
               ["directory", "count"])
    _write_csv(output_dir / "imports.csv", counter_rows(imports, "import"), ["import", "count"])
    _write_csv(output_dir / "symbols.csv", counter_rows(symbols, "symbol"), ["symbol", "count"])
    _write_csv(output_dir / "keyword_counts.csv", counter_rows(keywords, "keyword"),
               ["keyword", "count"])
    _write_csv(output_dir / "extension_counts.csv", counter_rows(extensions, "extension"),
               ["extension", "count"])
    _write_csv(output_dir / "near_miss_steps.csv", counter_rows(near_miss_steps, "step"),
               ["step", "count"])
    _write_csv(output_dir / "near_miss_rules.csv", counter_rows(near_miss_rules, "rule_id"),
               ["rule_id", "count"])
    _write_csv(
        output_dir / "sample_files.csv",
        samples,
        [
            "repository", "ref", "path", "extension", "loc", "scores",
            "imports", "symbols", "keywords", "preview", "cache_path",
        ],
    )

    summary = {
        "unclassified_source_files": total_unclassified_source,
        "cached_content_files_analyzed": cached_content_files,
        "uncached_content_files": uncached_content_files,
        "cached_content_coverage_pct": round(
            cached_content_files / total_unclassified_source * 100, 4
        ) if total_unclassified_source else 0.0,
        "mean_loc_for_cached_files": round(
            total_loc / cached_content_files, 3
        ) if cached_content_files else 0.0,
        "top_extensions": counter_rows(extensions, "extension")[:50],
        "top_filenames": counter_rows(filenames, "filename")[:50],
        "top_directories": counter_rows(directories, "directory")[:50],
        "top_imports": counter_rows(imports, "import")[:100],
        "top_symbols": counter_rows(symbols, "symbol")[:100],
        "top_keywords": counter_rows(keywords, "keyword")[:100],
        "near_miss_steps": counter_rows(near_miss_steps, "step"),
        "near_miss_rules": counter_rows(near_miss_rules, "rule_id"),
        "sample_file_count": len(samples),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze cached contents of unclassified source files."
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--raw-cache-dir", type=Path, default=DEFAULT_RAW_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=MAX_SAMPLE_FILES,
        help="Maximum number of detailed representative file rows to write.",
    )
    args = parser.parse_args()

    summary = analyze_unclassified_content(
        args.results_dir,
        args.raw_cache_dir,
        args.output_dir,
        max(0, args.sample_limit),
    )

    print(f"Unclassified source files:      {summary['unclassified_source_files']:,}")
    print(f"Cached contents analyzed:       {summary['cached_content_files_analyzed']:,}")
    print(f"Cached content coverage:        {summary['cached_content_coverage_pct']:.2f}%")
    print(f"Content not cached:             {summary['uncached_content_files']:,}")
    print(f"Mean LOC (cached files):        {summary['mean_loc_for_cached_files']:.1f}")
    print()
    print("Top filenames")
    for row in summary["top_filenames"][:20]:
        print(f"  {row['filename'][:35]:35} {row['count']:>8,}")
    print()
    print("Top imports/dependencies")
    for row in summary["top_imports"][:20]:
        print(f"  {row['import'][:35]:35} {row['count']:>8,}")
    print()
    print("Top content keywords")
    for row in summary["top_keywords"][:20]:
        print(f"  {row['keyword'][:35]:35} {row['count']:>8,}")
    print()
    print("Near-miss process steps (score below threshold)")
    for row in summary["near_miss_steps"]:
        print(f"  {row['step']:16} {row['count']:>8,}")
    print()
    print(f"Detailed outputs: {args.output_dir}")


if __name__ == "__main__":
    main()
