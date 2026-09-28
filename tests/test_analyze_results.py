import json
from pathlib import Path

from research_process_steps.analyze_results import analyze_results


def test_analyze_partial_results(tmp_path: Path):
    results = tmp_path / "results"
    output = tmp_path / "analysis"
    results.mkdir()

    payload = {
        "repository": {
            "url": "https://github.com/example/repo",
            "full_name": "example/repo",
            "ref": "main",
        },
        "execution": {"executed_at": "2026-09-28T00:00:00+00:00"},
        "files": [
            {
                "path": "src/train.py",
                "artifact_kind": "source_code",
                "extension": ".py",
                "content_scanned": True,
                "steps": ["implementation", "experimentation"],
                "unclassified": False,
                "evidence": [{"rule_id": "TEST_RULE"}],
            },
            {
                "path": "data/results.json",
                "artifact_kind": "data",
                "extension": ".json",
                "content_scanned": False,
                "steps": [],
                "unclassified": True,
                "evidence": [],
            },
        ],
    }
    (results / "abc.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = analyze_results(results, output)

    assert summary["completed_repositories"] == 1
    assert summary["total_files"] == 2
    assert summary["unclassified_files"] == 1
    assert summary["multi_label_files"] == 1
    assert summary["files_per_step"]["implementation"] == 1
    assert (output / "overall_summary.json").exists()
    assert (output / "repository_summary.csv").exists()
    assert (output / "step_summary.csv").exists()
    assert (output / "artifact_kind_summary.csv").exists()
    assert (output / "extension_summary.csv").exists()
    assert (output / "unclassified_extension_summary.csv").exists()
    assert (output / "evidence_rule_summary.csv").exists()
    assert summary["top_unclassified_extensions"][0]["extension"] == ".json"
    assert "typical_repository" in summary
    assert summary["typical_repository"]["file_count"]["median"] == 2
    assert (
        summary["typical_repository"]["steps"]["implementation"][
            "pct_of_repositories_with_step"
        ]
        == 100.0
    )
