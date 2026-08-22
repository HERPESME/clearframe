"""Refreshing mid-run must not lose your production.

Reported from the UI: "if I refresh the page before analysis ends that
analysis is entirely gone." It was never gone — the pipeline runs server-side
and every stage persists — but the client restored `list[0]`, and the list came
back in whatever order the store yielded, so "demo" won and the user's upload
vanished from view.

Newest first, and say whether it is still running.
"""

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(out_root=tmp_path)) as c:
        c.post("/api/productions/demo")
        yield c


def test_the_listing_carries_a_timestamp_and_a_running_flag(client):
    rows = client.get("/api/productions").json()
    assert rows
    row = rows[0]
    assert "updated_at" in row
    assert "running" in row


def test_a_finished_production_is_not_reported_as_running(client):
    row = next(r for r in client.get("/api/productions").json() if r["id"] == "demo")
    assert row["running"] is False


def test_the_newest_production_comes_first(client, tmp_path):
    """The actual bug: the client restores the first row, so the first row has
    to be the one the user was last looking at."""
    import json
    import time

    from clearframe.store import LocalJsonStore

    store = LocalJsonStore(tmp_path / "state")
    demo = store.load("demo")
    later = demo.model_copy(deep=True)
    later.production = later.production.model_copy(
        update={"id": "upload", "title": "My Clip"}
    )
    time.sleep(0.02)
    store.save(later)

    rows = client.get("/api/productions").json()
    assert rows[0]["id"] == "upload", [r["id"] for r in rows]


def test_a_partial_run_is_flagged_running(client, tmp_path):
    from clearframe.store import LocalJsonStore

    store = LocalJsonStore(tmp_path / "state")
    partial = store.load("demo").model_copy(deep=True)
    partial.production = partial.production.model_copy(update={"id": "midrun"})
    partial.stage_status = {"script": "complete", "scan": "running"}
    store.save(partial)

    row = next(r for r in client.get("/api/productions").json() if r["id"] == "midrun")
    assert row["running"] is True
