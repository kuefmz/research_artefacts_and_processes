import importlib

import pytest
from fastapi.testclient import TestClient

from research_process_steps import api, batch, conversations, storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_CONVERSATIONS_DIR", str(tmp_path / "links"))
    monkeypatch.setenv("RPS_RESULTS_DIR", str(tmp_path / "results"))
    return TestClient(api.app)


def attach(client, repo, variant="no_metadata", url="https://chatgpt.com/share/example"):
    return client.put("/api/conversations", json={"repo_url": repo, "variant": variant, "url": url})


def test_links_persist_edit_remove_and_normalize_repository_identity(client):
    repo = "https://github.com/Example/Repo.git"
    assert attach(client, repo).status_code == 200
    assert attach(client, repo, "research_process_step_metadata", "https://chatgpt.com/share/steps").status_code == 200
    importlib.reload(conversations)
    links = conversations.load_conversations("https://github.com/example/repo/tree/main")
    assert links == {
        "no_metadata": "https://chatgpt.com/share/example",
        "research_process_step_metadata": "https://chatgpt.com/share/steps",
    }
    assert attach(client, repo, url="https://chatgpt.com/share/edited").json()["conversations"]["no_metadata"].endswith("/edited")
    links = attach(client, repo, url=None).json()["conversations"]
    assert links["no_metadata"] is None
    assert links["research_process_step_metadata"].endswith("/steps")
    assert attach(client, repo, url=None).status_code == 200


@pytest.mark.parametrize("changes", [
    {"url": "javascript:alert(1)"}, {"url": "file:///etc/passwd"},
    {"url": "not a URL"}, {"variant": "unknown"},
    {"repo_url": "https://example.com/owner/repo"},
])
def test_invalid_links_and_variants_rejected(client, changes):
    payload = {"repo_url": "https://github.com/example/repo", "variant": "no_metadata", "url": "https://chatgpt.com/share/example"}
    payload.update(changes)
    assert client.put("/api/conversations", json=payload).status_code == 422


def test_links_appear_in_every_repository_view(client, monkeypatch):
    repo = api.selected_repositories()[0]
    monkeypatch.setattr(api, "collection_repositories", lambda: [repo])
    assert attach(client, repo).status_code == 200
    storage.save_result(repo, {"repository": {"url": repo}, "files": []})
    for endpoint in ["/api/selection", "/api/publication-collection", "/api/executed"]:
        payload = client.get(endpoint).json()
        record = next(item for item in payload["repositories"] if item["repo_url"] == repo)
        assert record["conversations"]["no_metadata"] == "https://chatgpt.com/share/example"
        assert record["conversations"]["research_process_step_metadata"] is None


def test_links_survive_single_and_all_heuristic_reruns(client, monkeypatch):
    repo = "https://github.com/example/repo"
    attach(client, repo)
    storage.save_result(repo, {"files": []})
    monkeypatch.setattr(batch, "analyze_github_repository", lambda *args, **kwargs: {"files": [{"path": "code.R"}]})
    assert client.post("/api/analyze", json={"repo_url": repo, "force": True}).status_code == 200

    class Worker:
        def submit(self, function, *args):
            function(*args)

    monkeypatch.setattr(api, "COLLECTION_JOBS", {})
    monkeypatch.setattr(api, "COLLECTION_WORKER", Worker())
    job = client.post("/api/publication-collection/jobs", json={"action": "rerun_all"}).json()
    state = client.get(f"/api/publication-collection/jobs/{job['id']}").json()
    assert len(state["result"]["completed"]) == 1
    assert conversations.load_conversations(repo)["no_metadata"] == "https://chatgpt.com/share/example"
    assert storage.load_result(repo)["files"] == [{"path": "code.R"}]
