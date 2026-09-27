import csv
from pathlib import Path

from research_process_steps import all_repositories


def test_load_repositories_deduplicates_normalized_urls(tmp_path: Path):
    dataset = tmp_path / "repos.csv"
    with dataset.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["github_repository_url", "other"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "github_repository_url": "https://github.com/example/repo",
                "other": "a",
            }
        )
        writer.writerow(
            {
                "github_repository_url": "https://github.com/example/repo.git",
                "other": "b",
            }
        )
        writer.writerow(
            {
                "github_repository_url": "https://github.com/example/other",
                "other": "c",
            }
        )

    repositories = all_repositories.load_repositories(dataset)

    assert repositories == [
        "https://github.com/example/repo",
        "https://github.com/example/other",
    ]


def test_wait_for_safe_quota_returns_without_sleep(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        all_repositories,
        "get_rate_limit",
        lambda token: {
            "limit": 5000,
            "remaining": 4500,
            "used": 500,
            "reset": 0,
        },
    )

    def fail_sleep(seconds):
        raise AssertionError(f"sleep should not be called: {seconds}")

    monkeypatch.setattr(all_repositories.time, "sleep", fail_sleep)

    status = all_repositories.wait_for_safe_quota(
        "token",
        reserve=100,
        log_path=tmp_path / "run.jsonl",
    )

    assert status["remaining"] == 4500
