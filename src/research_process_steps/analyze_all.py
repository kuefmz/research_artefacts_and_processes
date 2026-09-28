"""Run every available analysis over the completed result subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analyze_results import analyze_results
from .analyze_repository_profile import analyze_repository_profile
from .analyze_unclassified import analyze_unclassified
from .analyze_coverage import analyze_coverage
from .analyze_unclassified_content import analyze_unclassified_content
from .storage import DEFAULT_RESULTS_DIR

DEFAULT_RAW_CACHE_DIR = Path("data/github_cache")
DEFAULT_OUTPUT_DIR = Path("data/analysis_meeting")


def run_all_analyses(
    results_dir: Path,
    raw_cache_dir: Path,
    output_dir: Path,
    sample_limit: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    dirs = {
        "overall": output_dir / "overall",
        "repository_profile": output_dir / "repository_profile",
        "unclassified": output_dir / "unclassified",
        "coverage": output_dir / "coverage",
        "unclassified_content": output_dir / "unclassified_content",
    }

    print("[1/5] Overall corpus analysis...", flush=True)
    overall = analyze_results(results_dir, dirs["overall"])

    print("[2/5] Repository profile analysis...", flush=True)
    profile = analyze_repository_profile(results_dir, dirs["repository_profile"])

    print("[3/5] Unclassified-file analysis...", flush=True)
    unclassified = analyze_unclassified(results_dir, dirs["unclassified"])

    print("[4/5] Coverage and heuristic-driver analysis...", flush=True)
    coverage = analyze_coverage(results_dir, dirs["coverage"])

    print("[5/5] Unclassified source-content analysis...", flush=True)
    unclassified_content = analyze_unclassified_content(
        results_dir,
        raw_cache_dir,
        dirs["unclassified_content"],
        sample_limit,
    )

    summary = {
        "completed_repositories": overall.get("completed_repositories", 0),
        "total_files": overall.get("total_files", 0),
        "classified_files": overall.get("classified_files", 0),
        "unclassified_files": overall.get("unclassified_files", 0),
        "unclassified_pct": overall.get("unclassified_pct", 0.0),
        "repository_file_count": overall.get("repository_file_count", {}),
        "files_per_step": overall.get("files_per_step", {}),
        "repository_profile": profile,
        "coverage": {
            "overall_classification_rate_pct": coverage.get("overall_classification_rate_pct", 0.0),
            "eligible_files": coverage.get("eligible_files", 0),
            "eligible_classified_files": coverage.get("eligible_classified_files", 0),
            "eligible_classification_rate_pct": coverage.get("eligible_classification_rate_pct", 0.0),
            "source_like_files": coverage.get("source_like_files", 0),
            "source_like_classified_files": coverage.get("source_like_classified_files", 0),
            "source_like_classification_rate_pct": coverage.get("source_like_classification_rate_pct", 0.0),
        },
        "unclassified": {
            "excluded_by_design_unclassified_files": unclassified.get("excluded_by_design_unclassified_files", 0),
            "eligible_unclassified_files": unclassified.get("eligible_unclassified_files", 0),
            "source_like_unclassified_files": unclassified.get("source_like_unclassified_files", 0),
            "top_extensions": unclassified.get("top_extensions", [])[:20],
            "top_source_extensions": unclassified.get("top_source_extensions", [])[:20],
        },
        "unclassified_content": {
            "cached_content_files_analyzed": unclassified_content.get("cached_content_files_analyzed", 0),
            "cached_content_coverage_pct": unclassified_content.get("cached_content_coverage_pct", 0.0),
            "mean_loc_for_cached_files": unclassified_content.get("mean_loc_for_cached_files", 0.0),
            "top_filenames": unclassified_content.get("top_filenames", [])[:20],
            "top_imports": unclassified_content.get("top_imports", [])[:20],
            "top_keywords": unclassified_content.get("top_keywords", [])[:20],
            "near_miss_steps": unclassified_content.get("near_miss_steps", []),
        },
        "output_directories": {name: str(path) for name, path in dirs.items()},
    }

    (output_dir / "meeting_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    repo_size = summary["repository_file_count"]
    lines = [
        "# Research Process Steps - Interim Meeting Analysis",
        "",
        "## Snapshot",
        f"- Completed repositories: {summary['completed_repositories']:,}",
        f"- Total files: {summary['total_files']:,}",
        f"- Classified files: {summary['classified_files']:,}",
        f"- Unclassified files: {summary['unclassified_files']:,} ({summary['unclassified_pct']:.2f}%)",
        "",
        "## Repository size",
        f"- Mean files/repo: {repo_size.get('mean', 0)}",
        f"- Median files/repo: {repo_size.get('median', 0)}",
        f"- P90: {repo_size.get('p90', 0)}",
        f"- P95: {repo_size.get('p95', 0)}",
        f"- Max: {repo_size.get('max', 0)}",
        "",
        "## Files per research-process step",
    ]
    for step, count in summary["files_per_step"].items():
        lines.append(f"- {step}: {count:,}")

    lines += [
        "",
        "## Coverage",
        f"- Overall classification rate: {summary['coverage']['overall_classification_rate_pct']:.2f}%",
        f"- Eligible classification rate: {summary['coverage']['eligible_classification_rate_pct']:.2f}%",
        f"- Source-like classification rate: {summary['coverage']['source_like_classification_rate_pct']:.2f}%",
        "",
        "## Unclassified",
        f"- Excluded by design: {summary['unclassified']['excluded_by_design_unclassified_files']:,}",
        f"- Still eligible: {summary['unclassified']['eligible_unclassified_files']:,}",
        f"- Source-like: {summary['unclassified']['source_like_unclassified_files']:,}",
        "",
        "## Unclassified source-content inspection",
        f"- Cached source files analyzed: {summary['unclassified_content']['cached_content_files_analyzed']:,}",
        f"- Cached content coverage: {summary['unclassified_content']['cached_content_coverage_pct']:.2f}%",
        f"- Mean LOC of cached files: {summary['unclassified_content']['mean_loc_for_cached_files']:.1f}",
        "",
        "## Output directories",
    ]
    for name, path in summary["output_directories"].items():
        lines.append(f"- {name}: {path}")

    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all result analyses and prepare a meeting-ready aggregate folder."
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--raw-cache-dir", type=Path, default=DEFAULT_RAW_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-limit", type=int, default=500)
    args = parser.parse_args()

    summary = run_all_analyses(
        args.results_dir,
        args.raw_cache_dir,
        args.output_dir,
        max(0, args.sample_limit),
    )

    print()
    print("All analyses complete.")
    print(f"Meeting summary: {args.output_dir / 'README.md'}")
    print(f"Machine-readable summary: {args.output_dir / 'meeting_summary.json'}")
    print(
        f"Snapshot: {summary['completed_repositories']:,} repositories, "
        f"{summary['total_files']:,} files, "
        f"{summary['classified_files']:,} classified."
    )


if __name__ == "__main__":
    main()
