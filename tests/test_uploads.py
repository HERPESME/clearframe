"""Footage and rights-ledger upload surfaces."""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app

LEGAL = {"X-ClearFrame-Role": "legal"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(out_root=tmp_path)) as c:
        c.post("/api/productions/demo")
        yield c


# --------------------------------------------------------------- footage
def test_demo_mode_refuses_footage_upload_honestly(client):
    resp = client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 32, "video/mp4")},
        data={"title": "My Clip"},
    )
    # Demo mode replays fixtures, so analysing an upload would return Golden
    # Hour's findings as if they were the user's. Refusing is the honest path.
    assert resp.status_code == 409
    assert "demo mode" in resp.json()["detail"].lower()


def test_media_endpoint_404s_when_no_footage_stored(client):
    assert client.get("/api/productions/demo/media").status_code == 404


def test_media_endpoint_404s_for_unknown_production(client):
    assert client.get("/api/productions/nope/media").status_code == 404


def test_live_mode_rejects_unsupported_footage_type(client, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")
    resp = client.post(
        "/api/productions",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"title": "X"},
    )
    assert resp.status_code == 415
    assert ".mp4" in resp.json()["detail"]


def test_live_mode_without_credentials_is_actionable(client, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    resp = client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 16, "video/mp4")},
        data={"title": "X"},
    )
    assert resp.status_code == 503
    assert "GOOGLE_CLOUD_PROJECT" in resp.json()["detail"]


def test_a_live_upload_actually_builds_a_production(client, monkeypatch):
    """The success path. Every other footage test bails out BEFORE the
    Production is constructed — wrong mode, wrong file type, missing
    credentials — so the construction itself was never executed by the suite.

    A `NameError` on that line therefore survived 392 green tests and only
    surfaced when a human clicked upload. This test executes the line.
    """
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")

    started: dict = {}

    def _capture(cfg, production, out_root, **kw):
        # build_context is synchronous. Capture the production, then hand back
        # a fixture-backed context so the request completes without touching a
        # real API — the point is to execute the construction, not the pipeline.
        started["production"] = production
        from clearframe.pipeline import demo_context

        ctx = demo_context(out_root)
        ctx.state.production = production
        return ctx

    monkeypatch.setattr("clearframe.webapp.server.build_context", _capture)

    resp = client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 4096, "video/mp4")},
        data={
            "title": "Live Clip",
            "territories": "US,DE",
            "distribution": "STREAMING",
            "use_context": "ADVERTISING",
            "sponsors": "Bayer",
            "platform": "youtube",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["production_id"] == "upload"

    p = started["production"]
    assert p.title == "Live Clip"
    assert p.release_territories == ["US", "DE"]
    assert p.use_context.value == "ADVERTISING"
    assert p.sponsors == ["Bayer"]
    assert p.platform == "youtube"
    assert p.has_media is True
    # Not a real video, so the probe cannot read a duration — it must degrade
    # to 0.0 rather than raising, which is the whole point of that contract.
    assert p.duration_s == 0.0


def test_a_supplied_duration_is_trusted_over_the_probe(client, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")
    started: dict = {}

    def _capture(cfg, production, out_root, **kw):
        started["production"] = production
        from clearframe.pipeline import demo_context

        ctx = demo_context(out_root)
        ctx.state.production = production
        return ctx

    monkeypatch.setattr("clearframe.webapp.server.build_context", _capture)
    client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 4096, "video/mp4")},
        data={"title": "X", "duration_s": "42.5"},
    )
    assert started["production"].duration_s == 42.5


# --------------------------------------------------------------- ledger
def test_demo_ledger_is_seeded(client):
    body = client.get("/api/licences").json()
    assert body["licences"] and len(body["licences"]) >= 10
    holders = {lic["rights_holder"] for lic in body["licences"]}
    assert "The Coca-Cola Company" in holders


def test_csv_ledger_upload_merges_without_clobbering(client):
    before = {lic["id"]: lic["rights_holder"] for lic in client.get("/api/licences").json()["licences"]}
    csv = "rights_holder,territories,media\nA24 Films,WORLDWIDE,ALL\n"
    resp = client.post(
        "/api/licences",
        files={"file": ("ledger.csv", csv, "text/csv")},
        data={"replace": "false"},
        headers=LEGAL,
    )
    assert resp.status_code == 200 and resp.json()["added"] == 1
    after = {lic["id"]: lic["rights_holder"] for lic in client.get("/api/licences").json()["licences"]}
    assert after["LIC-001"] == before["LIC-001"]  # seeded rows survive
    assert "A24 Films" in after.values()


def test_replace_swaps_the_whole_ledger(client):
    csv = "rights_holder,territories,media\nOnly Studio,US,ALL\n"
    client.post(
        "/api/licences",
        files={"file": ("l.csv", csv, "text/csv")},
        data={"replace": "true"},
        headers=LEGAL,
    )
    licences = client.get("/api/licences").json()["licences"]
    assert len(licences) == 1 and licences[0]["rights_holder"] == "Only Studio"


def test_json_ledger_upload(client):
    body = json.dumps({"licences": [{"id": "X-1", "rights_holder": "Mubi Ltd"}]})
    resp = client.post(
        "/api/licences",
        files={"file": ("ledger.json", body, "application/json")},
        data={"replace": "true"},
        headers=LEGAL,
    )
    assert resp.status_code == 200
    assert client.get("/api/licences").json()["licences"][0]["id"] == "X-1"


def test_editor_cannot_change_the_ledger(client):
    resp = client.post(
        "/api/licences",
        files={"file": ("l.csv", "rights_holder\nX\n", "text/csv")},
        headers={"X-ClearFrame-Role": "editor"},
    )
    assert resp.status_code == 403


def test_malformed_ledger_is_rejected_with_guidance(client):
    resp = client.post(
        "/api/licences",
        files={"file": ("l.csv", "name,scope\nfoo,bar\n", "text/csv")},
        headers=LEGAL,
    )
    assert resp.status_code == 400
    assert "rights_holder" in resp.json()["detail"]
