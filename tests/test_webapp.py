import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(out_root=tmp_path)
    with TestClient(app) as c:
        yield c


def _create_demo(client) -> dict:
    resp = client.post("/api/productions/demo")
    assert resp.status_code == 200
    return resp.json()


def test_demo_creation_is_idempotent(client):
    state = _create_demo(client)
    assert len(state["elements"]) == 8
    again = _create_demo(client)
    assert again["production"]["id"] == state["production"]["id"]
    listing = client.get("/api/productions").json()
    assert len(listing) == 1


def test_editor_cannot_decide(client):
    _create_demo(client)
    resp = client.post(
        "/api/productions/demo/decisions",
        json={"element_id": "e1", "action": "license", "note": "x"},
        headers={"X-ClearFrame-Role": "editor"},
    )
    assert resp.status_code == 403


def test_dossier_before_decisions_409_lists_pending(client):
    _create_demo(client)
    resp = client.post("/api/productions/demo/dossier")
    assert resp.status_code == 409
    assert "e1" in resp.json()["detail"]["pending"]


def test_full_review_flow_generates_artifacts(client):
    state = _create_demo(client)
    for el in state["elements"]:
        resp = client.post(
            "/api/productions/demo/decisions",
            json={"element_id": el["id"], "action": "license", "note": "ok"},
            headers={"X-ClearFrame-Role": "legal"},
        )
        assert resp.status_code == 200
    resp = client.post("/api/productions/demo/dossier")
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert "dossier.html" in artifacts and "cue_sheet.csv" in artifacts

    html = client.get("/api/productions/demo/artifacts/dossier.html")
    assert html.status_code == 200 and "Clearance Report" in html.text


def test_artifact_name_whitelist(client):
    _create_demo(client)
    resp = client.get("/api/productions/demo/artifacts/..%2Fpyproject.toml")
    assert resp.status_code == 404


def test_unknown_production_404(client):
    assert client.get("/api/productions/nope").status_code == 404


def test_decision_after_dossier_reopens_review(client):
    state = _create_demo(client)
    for el in state["elements"]:
        client.post(
            "/api/productions/demo/decisions",
            json={"element_id": el["id"], "action": "license", "note": ""},
            headers={"X-ClearFrame-Role": "legal"},
        )
    assert client.post("/api/productions/demo/dossier").status_code == 200
    client.post(
        "/api/productions/demo/decisions",
        json={"element_id": "e1", "action": "escalate", "note": "second thoughts"},
        headers={"X-ClearFrame-Role": "legal"},
    )
    refreshed = client.get("/api/productions/demo").json()
    assert refreshed["stage_status"]["review"] == "awaiting"
