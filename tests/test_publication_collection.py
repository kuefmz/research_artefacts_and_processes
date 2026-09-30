import json

import pytest
from fastapi.testclient import TestClient

from research_process_steps import api, publication_collection as collection


def test_full_collection_and_nested_urls():
    records = collection.load_collection()["results"]
    assert len(records) == 386
    assert sum(len(record["related_to"]) for record in records) == 1732
    assert len(collection.collection_repositories()) == 386
    assert collection.repository_identity("https://github.com/Owner/Repo/blob/main/x.py") == "https://github.com/owner/repo"
    assert collection.repository_identity("https://github.com/Owner/Repo.git") == "https://github.com/owner/repo"
    with pytest.raises(ValueError):
        collection.repository_identity("https://example.com/owner/repo")


def test_runner_is_dataset_only_and_continues(monkeypatch):
    urls = ["https://github.com/a/one", "https://github.com/b/two"]
    monkeypatch.setattr(collection, "collection_repositories", lambda: urls)
    calls, progress = [], []

    def execute(url, **kwargs):
        calls.append(url)
        if url == urls[0]:
            raise RuntimeError("unavailable")
        return {"execution": {"id": "saved"}}, False

    monkeypatch.setattr(collection, "execute_repository_once", execute)
    result = collection.run_collection(progress.append)
    assert calls == urls
    assert len(result["errors"]) == 1
    assert result["completed"][0]["executed_now"] is False
    assert progress[-1]["index"] == 2


def test_all_five_analytics_exclude_unrelated_and_duplicate_results(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setenv("RPS_RESULTS_DIR", str(results))
    allowed = ["https://github.com/a/one", "https://github.com/b/two"]
    monkeypatch.setattr(collection, "collection_repositories", lambda: allowed)
    def write(name, url):
        (results / name).write_text(json.dumps({
            "repository": {"url": url, "full_name": "a/one", "ref": "main"},
            "files": [], "summary": {}, "execution": {},
        }))
    write("one.json", allowed[0])
    write("duplicate.json", allowed[0] + "/tree/main")
    write("unrelated.json", "https://github.com/outside/repo")
    output = tmp_path / "analytics"
    summary = collection.run_collection_analytics(output, tmp_path / "cache")
    assert summary["completed_repositories"] == 1
    assert summary["dataset_scope"]["completed_count"] == 1
    assert summary["dataset_scope"]["missing_repositories"] == [allowed[1]]
    assert not summary["dataset_scope"]["complete"]
    assert len(summary["output_directories"]) == 5
    assert all((output / key).is_dir() for key in summary["output_directories"])
    assert (output / "meeting_summary.json").exists()


def test_collection_api_empty_pdf_slots_and_job_is_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_PAPERS_DIR", str(tmp_path / "papers"))
    monkeypatch.setenv("RPS_RESULTS_DIR", str(tmp_path / "results"))
    client = TestClient(api.app)
    payload = client.get("/api/publication-collection").json()
    assert len(payload["repositories"]) == 386
    assert len(payload["papers"]) == 1732
    assert all(p["pdf_url"] is None for p in payload["papers"])
    assert client.put("/api/selection/papers/C1732", content=b"%PDF-1.4").status_code == 200
    assert client.put("/api/selection/papers/C1733", content=b"%PDF-1.4").status_code == 404
    class Worker:
        def submit(self, function, *args):
            function(*args)
    monkeypatch.setattr(api, "COLLECTION_WORKER", Worker())
    monkeypatch.setattr(api, "COLLECTION_JOBS", {})
    monkeypatch.setattr(api, "run_collection", lambda progress: {"completed": [], "errors": []})
    job = client.post("/api/publication-collection/jobs", json={"action": "heuristics"}).json()
    state = client.get(f"/api/publication-collection/jobs/{job['id']}").json()
    assert state["status"] == "completed"
    assert client.post("/api/publication-collection/jobs", json={"action":"other"}).status_code == 422


def test_job_rejects_concurrent_run(monkeypatch):
    monkeypatch.setattr(api, "COLLECTION_JOBS", {"existing": {"status": "running"}})
    client = TestClient(api.app)
    response = client.post("/api/publication-collection/jobs", json={"action": "analytics"})
    assert response.status_code == 409
