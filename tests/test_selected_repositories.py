from fastapi.testclient import TestClient

from research_process_steps import api, selected_repositories as selected


def test_selection_preserves_ten_papers_and_eight_repositories():
    papers = selected.load_selection()["papers"]
    repositories = selected.selected_repositories()
    assert len(papers) == 10
    assert len(repositories) == 8
    assert papers[2]["github_url"] == papers[3]["github_url"]
    assert papers[6]["github_url"] == papers[7]["github_url"]
    assert repositories[0] == "https://github.com/DanSBS/NGSPower"
    assert all(paper["pdf_path"] is None for paper in papers)


def test_runner_only_visits_selected_repos_and_continues_after_error(monkeypatch):
    calls = []

    def execute(url, **kwargs):
        calls.append(url)
        if len(calls) == 2:
            raise RuntimeError("unavailable")
        return {"execution": {"id": str(len(calls))}}, False

    monkeypatch.setattr(selected, "execute_repository_once", execute)
    result = selected.run_selection()
    assert calls == selected.selected_repositories()
    assert len(result["completed"]) == 7
    assert len(result["errors"]) == 1
    assert all(not item["executed_now"] for item in result["completed"])


def test_papers_start_empty_and_uploads_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_PAPERS_DIR", str(tmp_path / "papers"))
    monkeypatch.setenv("RPS_RESULTS_DIR", str(tmp_path / "results"))
    client = TestClient(api.app)
    assert all(p["pdf_url"] is None for p in client.get("/api/selection").json()["papers"])
    assert client.get("/api/selection/papers/D01").status_code == 404
    assert client.put("/api/selection/papers/D99", content=b"%PDF-1.4").status_code == 404
    assert client.put("/api/selection/papers/D01", content=b"not a PDF").status_code == 422
    pdf = b"%PDF-1.4\nmanual upload"
    assert client.put("/api/selection/papers/D01", content=pdf).status_code == 200
    assert client.get("/api/selection/papers/D01").content == pdf
    papers = client.get("/api/selection").json()["papers"]
    assert papers[0]["pdf_url"] == "/api/selection/papers/D01"
    assert all(p["pdf_url"] is None for p in papers[1:])
    # A manually copied file is also immediately available.
    (tmp_path / "papers" / "D02.pdf").write_bytes(pdf)
    assert client.get("/api/selection/papers/D02").status_code == 200


def test_selection_includes_only_matching_execution_metadata(monkeypatch):
    monkeypatch.setattr(api, "list_executions", lambda: [
        {"repo_url": "https://github.com/DanSBS/NGSPower", "id": "selected"},
        {"repo_url": "https://github.com/example/other", "id": "other"},
    ])
    repositories = api.selection()["repositories"]
    assert len(repositories) == 8
    assert repositories[0]["execution"]["id"] == "selected"
    assert all(item["execution"] is None for item in repositories[1:])
