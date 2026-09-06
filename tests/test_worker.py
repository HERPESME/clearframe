"""The heavy container, and why a retry is safe.

Cloud Tasks delivers at least once. A live analysis is three Gemini video passes
over the footage plus Parallel research plus up to 150 grounding calls, so a
duplicate delivery that re-ran the pipeline would quietly pay for the whole
thing twice — and with `--concurrency=1` a redelivery lands on a *different
instance*, so no in-process guard can see it. The index is the only thing that
can, which is most of why it exists.

The other half is that a retry should be a *resume*. `Pipeline.run` already
skips stages marked complete and persists after each one, so a task that died
half-way — or hit the queue's thirty-minute dispatch deadline — continues from
where it stopped. That property was already in the pipeline; the worker just has
to not throw it away by rebuilding the state from scratch.
"""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.pipeline import ANALYSIS_STAGES
from clearframe.worker.app import create_worker_app


def _production(tmp_path, pid="p1", stages=None):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / f"{pid}.json").write_text(json.dumps({
        "production": {"id": pid, "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 10.0, "fps": 24.0},
        "elements": [],
        "stage_status": stages or {},
    }))


@pytest.fixture
def ran(monkeypatch):
    """Record pipeline runs instead of performing them."""
    calls = []

    class _FakePipeline:
        def __init__(self, stages):
            self._stages = stages

        async def run(self, ctx):
            calls.append(ctx.state.production.id)
            for stage in ANALYSIS_STAGES:
                ctx.state.stage_status[stage] = "complete"
            ctx.store.save(ctx.state)
            return ctx.state

    monkeypatch.setattr("clearframe.runner.Pipeline", _FakePipeline)
    monkeypatch.setattr(
        "clearframe.runner.build_context",
        lambda cfg, production, out_root: _ctx(production),
    )
    return calls


def _ctx(production):
    from clearframe.models import ProductionState
    from clearframe.pipeline import PipelineContext

    return PipelineContext(
        state=ProductionState(production=production),
        gemini=None, parallel=None, store=None,
    )


def test_the_worker_is_alive_before_anything_is_asked_of_it(tmp_path):
    client = TestClient(create_worker_app(out_root=tmp_path))

    assert client.get("/healthz").json()["status"] == "ok"


def test_a_job_runs_the_pipeline(tmp_path, ran):
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    resp = client.post("/internal/run", json={"production_id": "p1"})

    assert resp.json()["outcome"] == "ran"
    assert ran == ["p1"]


def test_a_duplicate_delivery_does_not_pay_twice(tmp_path, ran):
    """Cloud Tasks is at-least-once and a live run costs real money."""
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    client.post("/internal/run", json={"production_id": "p1"})
    second = client.post("/internal/run", json={"production_id": "p1"})

    assert second.json()["outcome"] == "already-complete"
    assert ran == ["p1"], "the pipeline ran twice for one production"


def test_a_duplicate_is_acked_not_retried(tmp_path, ran):
    """200, not 5xx. A redelivery that finds the work done must STOP; answering
    with an error brings it back for every remaining attempt."""
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))
    client.post("/internal/run", json={"production_id": "p1"})

    assert client.post("/internal/run", json={"production_id": "p1"}).status_code == 200


def test_a_retry_resumes_rather_than_restarting(tmp_path, monkeypatch):
    """The expensive half of the guarantee: stages already done are skipped."""
    _production(tmp_path, stages={"script": "complete", "scan": "complete"})
    started = []

    class _RecordingPipeline:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            for stage in ANALYSIS_STAGES:
                if ctx.state.stage_status.get(stage) == "complete":
                    continue
                started.append(stage)
                ctx.state.stage_status[stage] = "complete"
            ctx.store.save(ctx.state)
            return ctx.state

    monkeypatch.setattr("clearframe.runner.Pipeline", _RecordingPipeline)
    monkeypatch.setattr(
        "clearframe.runner.build_context",
        lambda cfg, production, out_root: _ctx(production),
    )
    client = TestClient(create_worker_app(out_root=tmp_path))

    client.post("/internal/run", json={"production_id": "p1"})

    assert "script" not in started and "scan" not in started
    assert "triage" in started


def test_an_unknown_production_is_acked_not_retried_for_ever(tmp_path, ran):
    """A task for a production that has been deleted must not come back."""
    client = TestClient(create_worker_app(out_root=tmp_path))

    resp = client.post("/internal/run", json={"production_id": "ghost"})

    assert resp.status_code == 200
    assert resp.json()["outcome"] == "unknown"


def test_the_upload_persists_the_production_before_handing_it_over(tmp_path, monkeypatch):
    """The bug that only a real two-process run could show.

    In one process the upload never needed to save: the run held the state in
    memory and the first stage wrote it. A worker in another container is handed
    an id and loads what is on disk, so without a save it answers "no such
    production" and acks a job that never runs — silently, with the upload
    reporting success and the dashboard showing a production that never starts.

    Every other test here writes the state file itself, which is exactly why
    none of them could see it.
    """
    import json as _json

    from fastapi.testclient import TestClient as _TestClient

    from clearframe.webapp.server import create_app

    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-project")
    monkeypatch.setenv("PARALLEL_API_KEY", "a-key")

    enqueued = []

    class _Recording:
        async def enqueue(self, job):
            enqueued.append(job.production_id)
            return job.production_id

    monkeypatch.setattr(
        "clearframe.webapp.server.build_queue", lambda cfg, runner: _Recording()
    )
    monkeypatch.setattr(
        "clearframe.webapp.server.probe_media", lambda path: (10.0, 24.0)
    )
    client = _TestClient(create_app(out_root=tmp_path))

    resp = client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 2048, "video/mp4")},
        data={"title": "Handover", "production_id": "handover"},
    )

    assert resp.status_code == 200
    assert enqueued == ["handover"]
    written = tmp_path / "state" / "handover.json"
    assert written.exists(), "the worker would be handed an id with nothing behind it"
    assert _json.loads(written.read_text())["production"]["title"] == "Handover"


def test_progress_is_written_where_another_container_can_read_it(tmp_path, ran):
    """The API serves the event stream and does not share memory with this."""
    from clearframe.events import EventLog
    from clearframe.storage import build_backends
    from clearframe.config import ClearFrameConfig

    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))
    client.post("/internal/run", json={"production_id": "p1"})

    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)
    events = EventLog.read(backends.blobs, "p1")

    assert events and events[-1]["type"] == "run_complete"


def test_the_run_stops_claiming_to_be_running_when_it_ends(tmp_path, ran):
    from clearframe.config import ClearFrameConfig
    from clearframe.storage import build_backends

    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))
    client.post("/internal/run", json={"production_id": "p1"})

    row = build_backends(ClearFrameConfig.from_env({}), tmp_path).index.get("p1")

    assert row is None or not row.is_running()


# --- the gate ------------------------------------------------------------------


def test_with_no_audience_configured_the_worker_is_open(tmp_path, ran):
    """Opt-in, exactly like the auth gate. This is what lets the two-container
    topology run on a laptop and under a test client with no credentials."""
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    assert client.post("/internal/run", json={"production_id": "p1"}).status_code == 200


def test_an_unsigned_call_is_refused_when_an_audience_is_set(tmp_path, ran, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_WORKER_AUDIENCE", "https://worker.example")
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    resp = client.post("/internal/run", json={"production_id": "p1"})

    assert resp.status_code == 401
    assert ran == []


def test_a_verified_call_is_allowed(tmp_path, ran, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_WORKER_AUDIENCE", "https://worker.example")
    monkeypatch.setattr(
        "clearframe.worker.oidc.verify_token",
        lambda raw, audience: {"email": "tasks@project.iam.gserviceaccount.com"},
    )
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    resp = client.post(
        "/internal/run",
        json={"production_id": "p1"},
        headers={"Authorization": "Bearer a-token"},
    )

    assert resp.status_code == 200
    assert ran == ["p1"]


def test_a_token_from_the_wrong_account_is_refused(tmp_path, ran, monkeypatch):
    """Without this, any Google-issued token for the audience would do — a much
    larger set of callers than the one queue this worker serves."""
    monkeypatch.setenv("CLEARFRAME_WORKER_AUDIENCE", "https://worker.example")
    monkeypatch.setenv("CLEARFRAME_TASKS_SA", "tasks@project.iam.gserviceaccount.com")
    monkeypatch.setattr(
        "clearframe.worker.oidc.verify_token",
        lambda raw, audience: {"email": "someone-else@example.com"},
    )
    _production(tmp_path)
    client = TestClient(create_worker_app(out_root=tmp_path))

    resp = client.post(
        "/internal/run",
        json={"production_id": "p1"},
        headers={"Authorization": "Bearer a-token"},
    )

    assert resp.status_code == 401
    assert ran == []
