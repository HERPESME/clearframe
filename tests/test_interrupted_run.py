"""A run whose process died is not a run that is still going.

`running` was `not all stages complete`, read from the persisted state alone.
So a pipeline interrupted by a restart — the process gone, no task, nothing in
flight — reported `running: true` for ever. The SPA restores the newest running
production on load, which meant the reviewer was returned to a dead analysis on
every page load and could not reach the upload form at all.

That is the shape of the refresh bug this endpoint was ordered to fix, one
level down: the client was handed the wrong row, and this time no row was
right.
"""

import json

from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


def _interrupted_state(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "upload.json").write_text(json.dumps({
        "production": {"id": "upload", "title": "Tattoo hangover",
                       "footage_uri": "c.mp4", "duration_s": 41.5, "fps": 24.0},
        "elements": [],
        # Twelve of thirteen: the process died before `court`.
        "stage_status": {s: "complete" for s in (
            "script", "scan", "triage", "corroborate", "drift", "preview",
            "research", "freshness", "risk", "territory", "coverage",
            "remediation")},
    }))


def test_an_interrupted_run_is_not_reported_as_running(tmp_path):
    _interrupted_state(tmp_path)
    with TestClient(create_app(out_root=tmp_path)) as client:
        row = next(r for r in client.get("/api/productions").json()
                   if r["id"] == "upload")
    assert row["running"] is False, "a dead run pins the SPA to a dead analysis"


def test_an_interrupted_run_says_it_was_interrupted(tmp_path):
    """Not complete either. Silence would read as a finished analysis."""
    _interrupted_state(tmp_path)
    with TestClient(create_app(out_root=tmp_path)) as client:
        row = next(r for r in client.get("/api/productions").json()
                   if r["id"] == "upload")
    assert row["interrupted"] is True


def test_a_finished_run_is_neither_running_nor_interrupted(tmp_path):
    from clearframe.pipeline import ANALYSIS_STAGES

    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "done.json").write_text(json.dumps({
        "production": {"id": "done", "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 1.0, "fps": 24.0},
        "elements": [],
        "stage_status": {s: "complete" for s in ANALYSIS_STAGES},
    }))
    with TestClient(create_app(out_root=tmp_path)) as client:
        row = client.get("/api/productions").json()[0]
    assert row["running"] is False
    assert row["interrupted"] is False
