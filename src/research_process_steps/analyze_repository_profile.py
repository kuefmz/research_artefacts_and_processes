"""Analyze what a typical completed repository looks like."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .heuristics import RESEARCH_PROCESS_STEPS
from .storage import DEFAULT_RESULTS_DIR

DEFAULT_OUTPUT_DIR = Path("data/analysis_repository_profile")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_repository_profile(results_dir: Path, output_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

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

        step_counts = {step: 0 for step in RESEARCH_PROCESS_STEPS}
        unclassified = 0
        content_scanned = 0

        for record in files:
            if not isinstance(record, dict):
                continue
            steps = record.get("steps") or []
            if record.get("unclassified", not steps):
                unclassified += 1
            if record.get("content_scanned"):
                content_scanned += 1
            for step in steps:
                if step in step_counts:
                    step_counts[step] += 1

        n = len(files)
        repository = result.get("repository", {})
        row: dict[str, Any] = {
            "full_name": repository.get("full_name", ""),
            "file_count": n,
            "unclassified_files": unclassified,
            "unclassified_pct": (unclassified / n * 100) if n else 0.0,
            "content_scanned_files": content_scanned,
        }
        for step in RESEARCH_PROCESS_STEPS:
            row[f"{step}_files"] = step_counts[step]
            row[f"{step}_pct"] = (step_counts[step] / n * 100) if n else 0.0
        rows.append(row)

    def stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"mean": 0.0, "median": 0.0}
        return {
            "mean": round(statistics.mean(values), 3),
            "median": round(statistics.median(values), 3),
        }

    summary: dict[str, Any] = {
        "completed_repositories": len(rows),
        "file_count": stats([float(r["file_count"]) for r in rows]),
        "unclassified_files": stats([float(r["unclassified_files"]) for r in rows]),
        "unclassified_pct": stats([float(r["unclassified_pct"]) for r in rows]),
        "content_scanned_files": stats([float(r["content_scanned_files"]) for r in rows]),
        "steps": {},
    }

    for step in RESEARCH_PROCESS_STEPS:
        file_values = [float(r[f"{step}_files"]) for r in rows]
        pct_values = [float(r[f"{step}_pct"]) for r in rows]
        present = sum(v > 0 for v in file_values)
        summary["steps"][step] = {
            "mean_files_per_repo": stats(file_values)["mean"],
            "median_files_per_repo": stats(file_values)["median"],
            "mean_pct_of_repo_files": stats(pct_values)["mean"],
            "median_pct_of_repo_files": stats(pct_values)["median"],
            "repositories_with_step": present,
            "pct_of_repositories_with_step": round(present / len(rows) * 100, 4)
            if rows else 0.0,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "repository_profile.csv",
        rows,
        [
            "full_name", "file_count", "unclassified_files", "unclassified_pct",
            "content_scanned_files",
            *[f"{s}_files" for s in RESEARCH_PROCESS_STEPS],
            *[f"{s}_pct" for s in RESEARCH_PROCESS_STEPS],
        ],
    )
    (output_dir / "repository_profile_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the typical completed repository.")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    summary = analyze_repository_profile(args.results_dir, args.output_dir)

    print(f"Completed repositories: {summary['completed_repositories']:,}")
    print(
        f"Files/repo: mean={summary['file_count']['mean']}, "
        f"median={summary['file_count']['median']}"
    )
    print(
        f"Unclassified %/repo: mean={summary['unclassified_pct']['mean']:.2f}%, "
        f"median={summary['unclassified_pct']['median']:.2f}%"
    )
    print(
        f"Content-scanned files/repo: mean={summary['content_scanned_files']['mean']}, "
        f"median={summary['content_scanned_files']['median']}"
    )
    print("Process-step presence:")
    for step in RESEARCH_PROCESS_STEPS:
        s = summary["steps"][step]
        print(
            f"  {step:16} {s['repositories_with_step']:,} repos "
            f"({s['pct_of_repositories_with_step']:.2f}%), "
            f"median files={s['median_files_per_repo']}, "
            f"median share={s['median_pct_of_repo_files']:.2f}%"
        )
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
