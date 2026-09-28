"""Analyze heuristic coverage, drivers, and unclassified files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .heuristics import EXCLUDED_PROCESS_STEP_EXTENSIONS
from .storage import DEFAULT_RESULTS_DIR


DEFAULT_OUTPUT_DIR = Path("data/analysis_coverage")

SOURCE_LIKE_EXTENSIONS = {
    ".py", ".r", ".m", ".java", ".js", ".ts", ".tsx", ".jsx",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs", ".go",
    ".rs", ".jl", ".scala", ".sh", ".bash", ".zsh", ".rb", ".php",
    ".swift", ".kt", ".kts", ".lua", ".pl", ".pm", ".f", ".f90",
    ".f95", ".for", ".sql", ".ipynb",
}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_coverage(results_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    ext_total: Counter[str] = Counter()
    ext_classified: Counter[str] = Counter()
    ext_unclassified: Counter[str] = Counter()

    unclassified_artifact_counts: Counter[str] = Counter()
    unclassified_source_ext_counts: Counter[str] = Counter()
    unclassified_eligible_ext_counts: Counter[str] = Counter()
    unclassified_excluded_ext_counts: Counter[str] = Counter()

    rule_by_step: dict[str, Counter[str]] = defaultdict(Counter)

    total_files = 0
    classified_files = 0
    unclassified_files = 0

    eligible_files = 0
    eligible_classified = 0
    eligible_unclassified = 0

    excluded_files = 0
    excluded_unclassified = 0

    source_total = 0
    source_classified = 0
    source_unclassified = 0

    completed_repositories = 0

    for path in sorted(results_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue

        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        files = result.get("files", [])
        if not isinstance(files, list):
            continue

        completed_repositories += 1

        for record in files:
            if not isinstance(record, dict):
                continue

            total_files += 1

            extension = record.get("extension") or "(none)"
            artifact_kind = record.get("artifact_kind") or "(unknown)"
            steps = record.get("steps") or []
            if not isinstance(steps, list):
                steps = []

            is_unclassified = bool(record.get("unclassified", not steps))
            is_classified = not is_unclassified
            is_excluded = extension in EXCLUDED_PROCESS_STEP_EXTENSIONS
            is_source_like = extension in SOURCE_LIKE_EXTENSIONS

            ext_total[extension] += 1

            if is_classified:
                classified_files += 1
                ext_classified[extension] += 1
            else:
                unclassified_files += 1
                ext_unclassified[extension] += 1
                unclassified_artifact_counts[artifact_kind] += 1
                if is_source_like:
                    unclassified_source_ext_counts[extension] += 1
                if is_excluded:
                    unclassified_excluded_ext_counts[extension] += 1
                else:
                    unclassified_eligible_ext_counts[extension] += 1

            if is_excluded:
                excluded_files += 1
                if is_unclassified:
                    excluded_unclassified += 1
            else:
                eligible_files += 1
                if is_classified:
                    eligible_classified += 1
                else:
                    eligible_unclassified += 1

            if is_source_like:
                source_total += 1
                if is_classified:
                    source_classified += 1
                else:
                    source_unclassified += 1

            for evidence in record.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                rule_id = evidence.get("rule_id")
                step = evidence.get("step")
                if rule_id and step:
                    rule_by_step[str(step)][str(rule_id)] += 1

    extension_rows: list[dict[str, Any]] = []
    for extension, total in ext_total.most_common():
        classified = ext_classified.get(extension, 0)
        unclassified = ext_unclassified.get(extension, 0)
        extension_rows.append(
            {
                "extension": extension,
                "total_files": total,
                "classified_files": classified,
                "unclassified_files": unclassified,
                "classification_rate_pct": round(
                    classified / total * 100, 4
                ) if total else 0.0,
                "unclassified_rate_pct": round(
                    unclassified / total * 100, 4
                ) if total else 0.0,
            }
        )

    unclassified_extension_rows = [
        {
            "extension": extension,
            "unclassified_files": count,
            "pct_of_unclassified_files": round(
                count / unclassified_files * 100, 4
            ) if unclassified_files else 0.0,
            "excluded_by_design": extension in EXCLUDED_PROCESS_STEP_EXTENSIONS,
            "source_like": extension in SOURCE_LIKE_EXTENSIONS,
        }
        for extension, count in ext_unclassified.most_common()
    ]

    unclassified_artifact_rows = [
        {
            "artifact_kind": artifact_kind,
            "unclassified_files": count,
            "pct_of_unclassified_files": round(
                count / unclassified_files * 100, 4
            ) if unclassified_files else 0.0,
        }
        for artifact_kind, count in unclassified_artifact_counts.most_common()
    ]

    unclassified_source_rows = [
        {
            "extension": extension,
            "unclassified_source_files": count,
            "pct_of_unclassified_source_files": round(
                count / source_unclassified * 100, 4
            ) if source_unclassified else 0.0,
        }
        for extension, count in unclassified_source_ext_counts.most_common()
    ]

    eligible_unclassified_rows = [
        {
            "extension": extension,
            "eligible_unclassified_files": count,
            "pct_of_eligible_unclassified_files": round(
                count / eligible_unclassified * 100, 4
            ) if eligible_unclassified else 0.0,
        }
        for extension, count in unclassified_eligible_ext_counts.most_common()
    ]

    excluded_unclassified_rows = [
        {
            "extension": extension,
            "excluded_unclassified_files": count,
            "pct_of_excluded_unclassified_files": round(
                count / excluded_unclassified * 100, 4
            ) if excluded_unclassified else 0.0,
        }
        for extension, count in unclassified_excluded_ext_counts.most_common()
    ]

    driver_rows: list[dict[str, Any]] = []
    for step, counter in sorted(rule_by_step.items()):
        for rule_id, count in counter.most_common():
            driver_rows.append(
                {
                    "step": step,
                    "rule_id": rule_id,
                    "files_with_rule_evidence": count,
                }
            )

    summary = {
        "completed_repositories": completed_repositories,
        "total_files": total_files,
        "classified_files": classified_files,
        "unclassified_files": unclassified_files,
        "overall_classification_rate_pct": round(
            classified_files / total_files * 100, 4
        ) if total_files else 0.0,
        "eligible_files": eligible_files,
        "eligible_classified_files": eligible_classified,
        "eligible_unclassified_files": eligible_unclassified,
        "eligible_classification_rate_pct": round(
            eligible_classified / eligible_files * 100, 4
        ) if eligible_files else 0.0,
        "excluded_files": excluded_files,
        "excluded_unclassified_files": excluded_unclassified,
        "source_like_files": source_total,
        "source_like_classified_files": source_classified,
        "source_like_unclassified_files": source_unclassified,
        "source_like_classification_rate_pct": round(
            source_classified / source_total * 100, 4
        ) if source_total else 0.0,
        "top_unclassified_extensions": unclassified_extension_rows[:50],
        "top_unclassified_artifact_kinds": unclassified_artifact_rows[:50],
        "top_unclassified_source_extensions": unclassified_source_rows[:50],
        "top_eligible_unclassified_extensions": eligible_unclassified_rows[:50],
        "top_excluded_unclassified_extensions": excluded_unclassified_rows[:50],
    }

    _write_csv(
        output_dir / "extension_classification_rates.csv",
        extension_rows,
        [
            "extension",
            "total_files",
            "classified_files",
            "unclassified_files",
            "classification_rate_pct",
            "unclassified_rate_pct",
        ],
    )
    _write_csv(
        output_dir / "unclassified_extensions.csv",
        unclassified_extension_rows,
        [
            "extension",
            "unclassified_files",
            "pct_of_unclassified_files",
            "excluded_by_design",
            "source_like",
        ],
    )
    _write_csv(
        output_dir / "unclassified_artifact_kinds.csv",
        unclassified_artifact_rows,
        [
            "artifact_kind",
            "unclassified_files",
            "pct_of_unclassified_files",
        ],
    )
    _write_csv(
        output_dir / "unclassified_source_extensions.csv",
        unclassified_source_rows,
        [
            "extension",
            "unclassified_source_files",
            "pct_of_unclassified_source_files",
        ],
    )
    _write_csv(
        output_dir / "eligible_unclassified_extensions.csv",
        eligible_unclassified_rows,
        [
            "extension",
            "eligible_unclassified_files",
            "pct_of_eligible_unclassified_files",
        ],
    )
    _write_csv(
        output_dir / "excluded_unclassified_extensions.csv",
        excluded_unclassified_rows,
        [
            "extension",
            "excluded_unclassified_files",
            "pct_of_excluded_unclassified_files",
        ],
    )
    _write_csv(
        output_dir / "heuristic_rule_drivers.csv",
        driver_rows,
        ["step", "rule_id", "files_with_rule_evidence"],
    )

    (output_dir / "coverage_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return summary


def _print_summary(summary: dict[str, Any], output_dir: Path) -> None:
    print(f"Completed repositories:        {summary['completed_repositories']:,}")
    print(f"Total files:                   {summary['total_files']:,}")
    print(
        f"Overall classification rate:   "
        f"{summary['overall_classification_rate_pct']:.2f}%"
    )
    print()
    print(f"Eligible files:                {summary['eligible_files']:,}")
    print(f"Eligible classified files:     {summary['eligible_classified_files']:,}")
    print(
        f"Eligible classification rate:  "
        f"{summary['eligible_classification_rate_pct']:.2f}%"
    )
    print()
    print(f"Excluded-by-design files:      {summary['excluded_files']:,}")
    print(f"Source-like files:             {summary['source_like_files']:,}")
    print(
        f"Source-like classification:    "
        f"{summary['source_like_classification_rate_pct']:.2f}%"
    )
    print()
    print("Top unclassified source extensions")
    for row in summary["top_unclassified_source_extensions"][:20]:
        print(
            f"  {row['extension']:12} "
            f"{row['unclassified_source_files']:>10,} "
            f"({row['pct_of_unclassified_source_files']:.2f}%)"
        )
    print()
    print("Top eligible unclassified extensions")
    for row in summary["top_eligible_unclassified_extensions"][:20]:
        print(
            f"  {row['extension']:12} "
            f"{row['eligible_unclassified_files']:>10,} "
            f"({row['pct_of_eligible_unclassified_files']:.2f}%)"
        )
    print()
    print(f"Analysis written to: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze classification coverage, unclassified files, and heuristic drivers."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing completed repository result JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for coverage/unclassified analysis outputs.",
    )
    args = parser.parse_args()

    summary = analyze_coverage(args.results_dir, args.output_dir)
    _print_summary(summary, args.output_dir)


if __name__ == "__main__":
    main()
