from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.review import generate_dossier_async, record_decision

AT = "2026-08-15T12:00:00Z"


async def _reviewed_store(tmp_path):
    ctx = demo_context(tmp_path)
    await Pipeline(build_demo_pipeline()).run(ctx)
    store = ctx.store
    state = store.load("demo")
    for el in state.elements:
        record_decision(store, "demo", el.id, "license", "", role="legal", reviewer="x", at=AT)
    return store


async def test_dossier_creates_standing_watches(tmp_path):
    store = await _reviewed_store(tmp_path)
    await generate_dossier_async(store, tmp_path, "demo", at=AT)
    state = store.load("demo")
    # clear_required (e1, e4), escalate (e3, e5), incomplete (e5, e6-non-IP has no
    # holding but is incomplete), litigious owners — expect watches on e1, e3, e4, e5
    assert {"e1", "e3", "e4", "e5"}.issubset(set(state.watches.keys()))
    assert state.watches["e3"].monitor_id == "mon-e3"
    watch_events = [a for a in state.audit_log if a.event == "watch_created"]
    assert len(watch_events) == len(state.watches)


async def test_watch_webhook_reopens_review(tmp_path):
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    app = create_app(out_root=tmp_path)
    with TestClient(app) as client:
        client.post("/api/productions/demo")
        state = client.get("/api/productions/demo").json()
        for el in state["elements"]:
            client.post(
                "/api/productions/demo/decisions",
                json={"element_id": el["id"], "action": "license", "note": ""},
                headers={"X-ClearFrame-Role": "legal"},
            )
        assert client.post("/api/productions/demo/dossier").status_code == 200

        resp = client.post(
            "/api/webhooks/parallel-monitor",
            json={
                "monitor_id": "mon-e3",
                "summary": "Nike files new suit over unauthorized depiction",
                "source_url": "https://news.example/nike-suit",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["reopened_element"] == "e3"

        refreshed = client.get("/api/productions/demo").json()
        assert refreshed["stage_status"]["review"] == "awaiting"
        assert refreshed["alerts"][0]["summary"].startswith("Nike")
        assert any(a["event"] == "watch_alert" for a in refreshed["audit_log"])


async def test_unknown_monitor_404(tmp_path):
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    app = create_app(out_root=tmp_path)
    with TestClient(app) as client:
        client.post("/api/productions/demo")
        resp = client.post(
            "/api/webhooks/parallel-monitor",
            json={"monitor_id": "mon-nope", "summary": "x", "source_url": ""},
        )
        assert resp.status_code == 404
