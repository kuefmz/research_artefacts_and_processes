import csv
import random

from research_process_steps import batch, storage


def _write_dataset(path, urls):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["github_repository_url"])
        writer.writeheader()
        for url in urls:
            writer.writerow({"github_repository_url": url})


def test_execute_repository_once_never_reruns(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_RESULTS_DIR", str(tmp_path / "results"))
    calls = {"count": 0}

    def fake_analyze(repo_url, *, token=None, max_content_bytes=None):
        calls["count"] += 1
        return {
            "repository": {
                "url": repo_url,
                "full_name": "example/repo",
                "ref": "main",
                "file_count": 0,
            },
            "summary": {"files_per_step": {}, "unclassified_files": 0},
            "files": [],
        }

    monkeypatch.setattr(batch, "analyze_github_repository", fake_analyze)

    repo = "https://github.com/example/repo"
    first, first_executed = batch.execute_repository_once(repo)
    second, second_executed = batch.execute_repository_once(repo)

    assert calls["count"] == 1
    assert first_executed is True
    assert second_executed is False
    assert first["execution"]["id"] == second["execution"]["id"]
    assert second["cache"]["hit"] is True


def test_random_selection_excludes_stored_repositories(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_RESULTS_DIR", str(tmp_path / "results"))
    dataset = tmp_path / "repos.csv"
    urls = [f"https://github.com/example/repo{i}" for i in range(12)]
    _write_dataset(dataset, urls)

    storage.save_result(
        urls[0],
        {
            "repository": {
                "url": urls[0],
                "full_name": "example/repo0",
                "ref": "main",
                "file_count": 0,
            },
            "summary": {"files_per_step": {}, "unclassified_files": 0},
            "files": [],
        },
    )

    selected = batch.select_unexecuted_random(
        10,
        dataset_path=dataset,
        rng=random.Random(42),
    )

    assert len(selected) == 10
    assert urls[0] not in selected
    assert len(set(selected)) == 10
