"""Analyze all currently completed heuristic result files.

This module intentionally works on a partial corpus: rerun it at any point while
the crawler is still running and it will summarize every successfully stored
repository available at that moment.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .heuristics import RESEARCH_PROCESS_STEPS
from .storage import DEFAULT_RESULTS_DIR


DEFAULT_ANALYSIS_DIR = Path("data/analysis")


def _percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _iter_results(results_dir: Path):
    for path in sorted(results_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            yield path, None
            continue
        if isinstance(payload, dict):
            yield path, payload
        else:
            yield path, None


def analyze_results(
    results_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    repository_rows: list[dict[str, Any]] = []
    invalid_result_files: list[str] = []

    step_file_counts: Counter[str] = Counter()
    step_repo_counts: Counter[str] = Counter()
    artifact_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    evidence_rule_counts: Counter[str] = Counter()

    total_files = 0
    total_unclassified = 0
    total_multilabel_files = 0
    total_content_scanned = 0
    repository_file_counts: list[int] = []

    for path, result in _iter_results(results_dir):
        if result is None:
            invalid_result_files.append(str(path))
            continue

        repository = result.get("repository", {})
        files = result.get("files", [])
        if not isinstance(files, list):
            invalid_result_files.append(str(path))
            continue

        full_name = repository.get("full_name") or ""
        repo_url = repository.get("url") or ""
        execution = result.get("execution", {})
        summary = result.get("summary", {})

        repo_step_counts: Counter[str] = Counter()
        repo_unclassified = 0
        repo_multilabel = 0
        repo_content_scanned = 0

        for record in files:
            if not isinstance(record, dict):
                continue

            total_files += 1
            steps = record.get("steps") or []
            if not isinstance(steps, list):
                steps = []

            if record.get("unclassified", not steps):
                total_unclassified += 1
                repo_unclassified += 1

            if len(steps) > 1:
                total_multilabel_files += 1
                repo_multilabel += 1

            if record.get("content_scanned"):
                total_content_scanned += 1
                repo_content_scanned += 1

            artifact = record.get("artifact_kind") or "(unknown)"
            extension = record.get("extension") or "(none)"
            artifact_counts[artifact] += 1
            extension_counts[extension] += 1

            for step in steps:
                step_file_counts[step] += 1
                repo_step_counts[step] += 1

            for evidence in record.get("evidence") or []:
                if isinstance(evidence, dict):
                    rule_id = evidence.get("rule_id")
                    if rule_id:
                        evidence_rule_counts[str(rule_id)] += 1

        for step in repo_step_counts:
            step_repo_counts[step] += 1

        file_count = len(files)
        repository_file_counts.append(file_count)
        repository_rows.append(
            {
                "full_name": full_name,
                "repo_url": repo_url,
                "executed_at": execution.get("executed_at", ""),
                "ref": repository.get("ref", ""),
                "file_count": file_count,
                "unclassified_files": repo_unclassified,
                "unclassified_pct": round((repo_unclassified / file_count * 100), 4)
                if file_count
                else 0.0,
                "content_scanned_files": repo_content_scanned,
                "multi_label_files": repo_multilabel,
                **{
                    f"{step}_files": repo_step_counts.get(step, 0)
                    for step in RESEARCH_PROCESS_STEPS
                },
            }
        )

    repository_count = len(repository_rows)

    all_steps = list(RESEARCH_PROCESS_STEPS)
    for step in sorted(step_file_counts):
        if step not in all_steps:
            all_steps.append(step)

    step_rows = []
    for step in all_steps:
        files_count = step_file_counts.get(step, 0)
        repos_count = step_repo_counts.get(step, 0)
        step_rows.append(
            {
                "step": step,
                "classified_files": files_count,
                "pct_of_all_files": round(files_count / total_files * 100, 4)
                if total_files
                else 0.0,
                "repositories_with_step": repos_count,
                "pct_of_repositories": round(repos_count / repository_count * 100, 4)
                if repository_count
                else 0.0,
            }
        )

    artifact_rows = [
        {
            "artifact_kind": name,
            "file_count": count,
            "pct_of_all_files": round(count / total_files * 100, 4)
            if total_files
            else 0.0,
        }
        for name, count in artifact_counts.most_common()
    ]

    extension_rows = [
        {
            "extension": name,
            "file_count": count,
            "pct_of_all_files": round(count / total_files * 100, 4)
            if total_files
            else 0.0,
        }
        for name, count in extension_counts.most_common()
    ]

    rule_rows = [
        {"rule_id": rule_id, "files_with_rule_evidence": count}
        for rule_id, count in evidence_rule_counts.most_common()
    ]

    summary = {
        "results_dir": str(results_dir),
        "completed_repositories": repository_count,
        "invalid_result_files": len(invalid_result_files),
        "total_files": total_files,
        "classified_files": total_files - total_unclassified,
        "unclassified_files": total_unclassified,
        "unclassified_pct": round(total_unclassified / total_files * 100, 4)
        if total_files
        else 0.0,
        "content_scanned_files": total_content_scanned,
        "content_scanned_pct": round(total_content_scanned / total_files * 100, 4)
        if total_files
        else 0.0,
        "multi_label_files": total_multilabel_files,
        "multi_label_pct": round(total_multilabel_files / total_files * 100, 4)
        if total_files
        else 0.0,
        "repository_file_count": {
            "mean": round(statistics.mean(repository_file_counts), 3)
            if repository_file_counts
            else 0.0,
            "median": round(statistics.median(repository_file_counts), 3)
            if repository_file_counts
            else 0.0,
            "p90": round(_percentile(repository_file_counts, 0.90), 3),
            "p95": round(_percentile(repository_file_counts, 0.95), 3),
            "max": max(repository_file_counts) if repository_file_counts else 0,
        },
        "files_per_step": dict(step_file_counts),
        "repositories_per_step": dict(step_repo_counts),
        "invalid_paths": invalid_result_files,
    }

    repo_fields = [
        "full_name",
        "repo_url",
        "executed_at",
        "ref",
        "file_count",
        "unclassified_files",
        "unclassified_pct",
        "content_scanned_files",
        "multi_label_files",
        *[f"{step}_files" for step in RESEARCH_PROCESS_STEPS],
    ]
    _write_csv(output_dir / "repository_summary.csv", repository_rows, repo_fields)
    _write_csv(
        output_dir / "step_summary.csv",
        step_rows,
        [
            "step",
            "classified_files",
            "pct_of_all_files",
            "repositories_with_step",
            "pct_of_repositories",
        ],
    )
    _write_csv(
        output_dir / "artifact_kind_summary.csv",
        artifact_rows,
        ["artifact_kind", "file_count", "pct_of_all_files"],
    )
    _write_csv(
        output_dir / "extension_summary.csv",
        extension_rows,
        ["extension", "file_count", "pct_of_all_files"],
    )
    _write_csv(
        output_dir / "evidence_rule_summary.csv",
        rule_rows,
        ["rule_id", "files_with_rule_evidence"],
    )
    (output_dir / "overall_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return summary


def _print_summary(summary: dict[str, Any], output_dir: Path) -> None:
    print(f"Completed repositories: {summary['completed_repositories']:,}")
    print(f"Total files:            {summary['total_files']:,}")
    print(
        f"Classified files:       {summary['classified_files']:,} "
        f"({100 - summary['unclassified_pct']:.2f}%)"
    )
    print(
        f"Unclassified files:     {summary['unclassified_files']:,} "
        f"({summary['unclassified_pct']:.2f}%)"
    )
    print(
        f"Content scanned:        {summary['content_scanned_files']:,} "
        f"({summary['content_scanned_pct']:.2f}%)"
    )
    print(f"Multi-label files:      {summary['multi_label_files']:,}")
    print()
    print("Repository size (files)")
    sizes = summary["repository_file_count"]
    print(f"  mean:   {sizes['mean']}")
    print(f"  median: {sizes['median']}")
    print(f"  p90:    {sizes['p90']}")
    print(f"  p95:    {sizes['p95']}")
    print(f"  max:    {sizes['max']}")
    print()
    print("Files per research-process step")
    for step in RESEARCH_PROCESS_STEPS:
        print(f"  {step:16} {summary['files_per_step'].get(step, 0):,}")
    print()
    print(f"Analysis written to: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze all successfully completed repository heuristic results."
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing stored per-repository result JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ANALYSIS_DIR,
        help="Directory for aggregate CSV/JSON analysis outputs.",
    )
    args = parser.parse_args()

    summary = analyze_results(args.results_dir, args.output_dir)
    _print_summary(summary, args.output_dir)


if __name__ == "__main__":
    main()
