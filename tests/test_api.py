import json

from research_process_steps import api


def test_health_reports_no_ai():
    result = api.health()
    assert result["status"] == "ok"
    assert result["uses_ai"] is False
    assert 100 in result["allowed_batch_sizes"]


def test_analyze_uses_execute_once(monkeypatch):
    captured = {}

    monkeypatch.setattr(api, "load_result", lambda repo_url: None)
    monkeypatch.setattr(api, "_bundled_demo_path", lambda request: None)
    monkeypatch.setattr(api, "_demo_cache_path", lambda request: None)

    def fake_execute(repo_url, *, token=None, max_content_bytes=None):
        captured.update(
            repo_url=repo_url,
            token=token,
            max_content_bytes=max_content_bytes,
        )
        return (
            {
                "repository": {
                    "url": repo_url,
                    "full_name": "example/repo",
                    "ref": "main",
                    "file_count": 0,
                },
                "summary": {"files_per_step": {}, "unclassified_files": 0},
                "files": [],
                "cache": {"hit": False, "persistent": True},
            },
            True,
        )

    monkeypatch.setattr(api, "execute_repository_once", fake_execute)
    request = api.AnalyzeRequest(
        repo_url="https://github.com/example/repo",
        max_content_bytes=1234,
    )

    result = api.analyze(request)

    assert result["files"] == []
    assert result["cache"]["persistent"] is True
    assert captured["repo_url"] == "https://github.com/example/repo"
    assert captured["max_content_bytes"] == 1234


def test_analyze_returns_existing_without_execution(monkeypatch):
    stored = {
        "repository": {
            "url": "https://github.com/example/repo",
            "full_name": "example/repo",
            "ref": "main",
            "file_count": 1,
        },
        "summary": {"files_per_step": {}, "unclassified_files": 1},
        "files": [{"path": "README.md"}],
        "cache": {"hit": True, "persistent": True},
    }
    monkeypatch.setattr(api, "load_result", lambda repo_url: stored)

    def fail_execute(*args, **kwargs):
        raise AssertionError("already stored repository must never execute again")

    monkeypatch.setattr(api, "execute_repository_once", fail_execute)

    result = api.analyze(api.AnalyzeRequest(repo_url="https://github.com/example/repo"))
    assert result is stored
    assert result["cache"]["hit"] is True


def test_bundled_demo_is_promoted_to_general_store(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    monkeypatch.setenv("RPS_RESULTS_DIR", str(results_dir))
    monkeypatch.setattr(api, "BUNDLED_CACHE_DIR", bundled_dir)

    payload = {
        "repository": {
            "url": "https://github.com/dgarijo/Widoco",
            "full_name": "dgarijo/Widoco",
            "ref": "master",
            "file_count": 0,
        },
        "summary": {"files_per_step": {}, "unclassified_files": 0},
        "files": [],
    }
    (bundled_dir / "widoco.json").write_text(json.dumps(payload), encoding="utf-8")

    request = api.AnalyzeRequest(repo_url="https://github.com/dgarijo/Widoco")
    first = api.analyze(request)
    second = api.analyze(request)

    assert first["cache"]["persistent"] is True
    assert second["cache"]["hit"] is True
    assert first["execution"]["id"] == second["execution"]["id"]
