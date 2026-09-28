"""Analyze files that remain unclassified by the heuristics."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .heuristics import EXCLUDED_PROCESS_STEP_EXTENSIONS
from .storage import DEFAULT_RESULTS_DIR

DEFAULT_OUTPUT_DIR = Path("data/analysis_unclassified")

SOURCE_LIKE_EXTENSIONS = {
    ".py", ".r", ".m", ".java", ".js", ".ts", ".tsx", ".jsx", ".c", ".cc",
    ".cpp", ".cxx", ".h", ".hpp", ".cs", ".go", ".rs", ".jl", ".scala",
    ".sh", ".bash", ".zsh", ".rb", ".php", ".swift", ".kt", ".kts", ".lua",
    ".pl", ".pm", ".f", ".f90", ".f95", ".for", ".sql", ".ipynb",
}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_unclassified(results_dir: Path, output_dir: Path) -> dict[str, Any]:
    extensions: Counter[str] = Counter()
    artifacts: Counter[str] = Counter()
    source_extensions: Counter[str] = Counter()
    eligible_extensions: Counter[str] = Counter()
    excluded_extensions: Counter[str] = Counter()
    total = 0

    for path in sorted(results_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        for record in result.get("files", []):
            if not isinstance(record, dict):
                continue
            steps = record.get("steps") or []
            if not record.get("unclassified", not steps):
                continue

            total += 1
            ext = record.get("extension") or "(none)"
            artifact = record.get("artifact_kind") or "(unknown)"
            extensions[ext] += 1
            artifacts[artifact] += 1
            if ext in SOURCE_LIKE_EXTENSIONS:
                source_extensions[ext] += 1
            if ext in EXCLUDED_PROCESS_STEP_EXTENSIONS:
                excluded_extensions[ext] += 1
            else:
                eligible_extensions[ext] += 1

    def rows(counter: Counter[str], count_key: str) -> list[dict[str, Any]]:
        denom = sum(counter.values())
        return [
            {
                "name": name,
                count_key: count,
                "pct": round(count / denom * 100, 4) if denom else 0.0,
            }
            for name, count in counter.most_common()
        ]

    ext_rows = rows(extensions, "unclassified_files")
    artifact_rows = rows(artifacts, "unclassified_files")
    source_rows = rows(source_extensions, "unclassified_source_files")
    eligible_rows = rows(eligible_extensions, "eligible_unclassified_files")
    excluded_rows = rows(excluded_extensions, "excluded_unclassified_files")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "unclassified_extensions.csv", ext_rows,
               ["name", "unclassified_files", "pct"])
    _write_csv(output_dir / "unclassified_artifact_kinds.csv", artifact_rows,
               ["name", "unclassified_files", "pct"])
    _write_csv(output_dir / "unclassified_source_extensions.csv", source_rows,
               ["name", "unclassified_source_files", "pct"])
    _write_csv(output_dir / "eligible_unclassified_extensions.csv", eligible_rows,
               ["name", "eligible_unclassified_files", "pct"])
    _write_csv(output_dir / "excluded_unclassified_extensions.csv", excluded_rows,
               ["name", "excluded_unclassified_files", "pct"])

    summary = {
        "unclassified_files": total,
        "excluded_by_design_unclassified_files": sum(excluded_extensions.values()),
        "eligible_unclassified_files": sum(eligible_extensions.values()),
        "source_like_unclassified_files": sum(source_extensions.values()),
        "top_extensions": ext_rows[:50],
        "top_artifact_kinds": artifact_rows[:50],
        "top_source_extensions": source_rows[:50],
        "top_eligible_extensions": eligible_rows[:50],
        "top_excluded_extensions": excluded_rows[:50],
    }
    (output_dir / "unclassified_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze unclassified files only.")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    summary = analyze_unclassified(args.results_dir, args.output_dir)

    print(f"Unclassified files: {summary['unclassified_files']:,}")
    print(f"Excluded by design: {summary['excluded_by_design_unclassified_files']:,}")
    print(f"Still eligible:      {summary['eligible_unclassified_files']:,}")
    print(f"Source-like:         {summary['source_like_unclassified_files']:,}")
    print()
    print("Top unclassified extensions:")
    for row in summary["top_extensions"][:20]:
        print(f"  {row['name']:12} {row['unclassified_files']:>10,} ({row['pct']:.2f}%)")
    print()
    print("Top unclassified source extensions:")
    for row in summary["top_source_extensions"][:20]:
        print(f"  {row['name']:12} {row['unclassified_source_files']:>10,} ({row['pct']:.2f}%)")
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
