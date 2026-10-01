from fastapi.testclient import TestClient

from research_process_steps import api
from research_process_steps.paper_conversations import load_paper_conversations


def test_paper_conversations_append_and_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("RPS_REPRO_CONVERSATIONS_DIR", str(tmp_path / "repro"))
    client = TestClient(api.app)
    paper_id = api.collection_papers()[0]["paper_id"]

    first = client.post(
        f"/api/publication-collection/papers/{paper_id}/conversations",
        json={"variant": "c0", "url": "https://chatgpt.com/share/first"},
    )
    assert first.status_code == 200
    first_record = first.json()["record"]
    assert first_record["created_at"]
    assert first_record["updated_at"]

    second = client.post(
        f"/api/publication-collection/papers/{paper_id}/conversations",
        json={"variant": "c0", "url": "https://chatgpt.com/share/second"},
    )
    assert second.status_code == 200
    assert len(second.json()["conversations"]["c0"]) == 2

    changed = client.put(
        f"/api/publication-collection/papers/{paper_id}/conversations/{first_record['id']}",
        json={"variant": "c0", "url": "https://chatgpt.com/share/first-edited"},
    )
    assert changed.status_code == 200
    changed_record = changed.json()["record"]
    assert changed_record["created_at"] == first_record["created_at"]
    assert changed_record["url"].endswith("first-edited")

    stored = load_paper_conversations(paper_id)
    assert len(stored["c0"]) == 2
    assert stored["c1"] == []


def test_reproducibility_prompts_expose_control_and_metadata_condition():
    client = TestClient(api.app)
    response = client.get("/api/reproducibility/prompts")
    assert response.status_code == 200
    prompts = response.json()["prompts"]
    assert "ADDITIONAL METADATA: none" in prompts["c0"]["prompt"]
    assert "supplied file-level research-process-step metadata" in prompts["c1"]["prompt"]
    assert "static assessment" in prompts["c0"]["prompt"]
    assert "static assessment" in prompts["c1"]["prompt"]
