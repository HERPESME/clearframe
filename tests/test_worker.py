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
        lambda cfg, production, out_root, **kw: _ctx(production),
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
        lambda cfg, production, out_root, **kw: _ctx(production),
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


def test_footage_reaches_the_blob_store_not_just_the_container_disk(tmp_path, monkeypatch):
    """The other half of the handover, and the one that breaks Cloud Run.

    The API and the worker are separate services, both started with
    `--out /tmp/out` — a per-instance tmpfs. Footage written straight to that
    directory is invisible to the worker, so every live upload would reach the
    scan with no file to scan. `put_file`/`open_local` were defined for exactly
    this and had zero callers.

    Asserted through the store rather than the filesystem, because locally the
    two are the same path and only the store's answer is true in both profiles.
    """
    from fastapi.testclient import TestClient as _TestClient

    from clearframe.config import ClearFrameConfig
    from clearframe.storage import build_backends
    from clearframe.webapp.server import create_app

    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-project")
    monkeypatch.setenv("PARALLEL_API_KEY", "a-key")

    class _Recording:
        async def enqueue(self, job):
            return job.production_id

    monkeypatch.setattr(
        "clearframe.webapp.server.build_queue", lambda cfg, runner: _Recording()
    )
    monkeypatch.setattr(
        "clearframe.webapp.server.probe_media", lambda path: (10.0, 24.0)
    )
    client = _TestClient(create_app(out_root=tmp_path))

    client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 4096, "video/mp4")},
        data={"title": "Handover", "production_id": "handover"},
    )

    blobs = build_backends(ClearFrameConfig.from_env({}), tmp_path).blobs
    assert blobs.exists("media/handover/footage.mp4"), (
        "the worker would find no footage to scan"
    )
    assert len(blobs.get("media/handover/footage.mp4")) == 4096
    assert blobs.version("media/handover/footage.mp4")


def test_the_worker_opens_footage_the_other_container_uploaded(tmp_path, monkeypatch):
    """The bug a real cloud run found, and no local run could.

    `footage_uri` is an absolute path written by whichever container took the
    upload. In the cloud profile that is the API's own download cache —
    `/tmp/clearframe-cache/<hash>.mp4` — on a filesystem the worker has never
    seen. The bytes were in the bucket the whole time; what did not travel was
    the path. Every live upload failed the scan with FileNotFoundError, and
    Cloud Tasks retried it three times before giving up.

    Locally the two paths coincide, which is exactly why this needed a
    deployment to surface and needs a stored uri that is deliberately WRONG to
    reproduce.
    """
    from clearframe.config import ClearFrameConfig
    from clearframe.runner import _with_local_footage
    from clearframe.storage import build_backends

    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)
    backends.blobs.put("media/p1/footage.mp4", b"\x00" * 32)

    _production(tmp_path, pid="p1")
    state = backends.store.load("p1")
    state.production = state.production.model_copy(
        update={"footage_uri": "/tmp/clearframe-cache/deadbeef.mp4"}
    )

    fixed = _with_local_footage(state, "p1", backends)

    assert fixed.production.footage_uri != "/tmp/clearframe-cache/deadbeef.mp4"
    from pathlib import Path as _P
    assert _P(fixed.production.footage_uri).exists(), "the scan would find nothing"


def test_a_production_with_no_stored_footage_is_left_alone(tmp_path):
    """A demo production, or one the CLI made against a path that really is
    local. Rewriting those would break the case that already worked."""
    from clearframe.config import ClearFrameConfig
    from clearframe.runner import _with_local_footage
    from clearframe.storage import build_backends

    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)
    _production(tmp_path, pid="p1")
    state = backends.store.load("p1")

    assert _with_local_footage(state, "p1", backends).production.footage_uri == "c.mp4"


@pytest.mark.asyncio
async def test_a_long_stage_keeps_beating_while_it_works(tmp_path, monkeypatch):
    """A beat at stage boundaries is not a heartbeat, it is a stage counter.

    `runner.listen` recorded a beat only on `stage_start`/`stage_complete`.
    `scan` emits `scan_found`, `audit_found`, `fingerprint_*` and
    `corroborator_hits`, none of which qualify — so a three-pass scan on real
    footage produced exactly ONE beat and then silence for the whole stage. A
    deployed run spent ~1270s in scan against a 900s staleness window, so
    `is_running()` went false on a healthy run: the dashboard said not running,
    the Mission Control stream cut itself off (`server.py`), and a Cloud Tasks
    redelivery was free to start a second concurrent PAID analysis.

    The fix is a beat on a timer, which is what `test_production_index`'s own
    docstring has claimed all along — "the worker says 'still here' every few
    seconds while it works". It never did.
    """
    import asyncio
    import time

    from clearframe import runner as runner_mod
    from clearframe.storage import AnalysisJob, build_backends
    from clearframe.config import ClearFrameConfig

    monkeypatch.setattr(runner_mod, "HEARTBEAT_EVERY_S", 0.05)

    beats: list[float] = []

    class _SlowPipeline:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            # One stage, far longer than the beat interval and emitting no
            # stage events at all — exactly the shape of `scan`.
            await asyncio.sleep(0.4)
            return ctx.state

    monkeypatch.setattr(runner_mod, "Pipeline", _SlowPipeline)
    monkeypatch.setattr(
        runner_mod, "build_context",
        lambda cfg, production, out_root, **kw: _ctx(production),
    )

    _production(tmp_path, pid="p1")
    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"})
    backends = build_backends(cfg, tmp_path)

    real_heartbeat = backends.index.heartbeat

    def _counting(pid: str) -> None:
        # `time.monotonic`, not the loop clock: the beat is deliberately made
        # from a thread so it cannot block the pipeline it is reporting on.
        beats.append(time.monotonic())
        real_heartbeat(pid)

    monkeypatch.setattr(backends.index, "heartbeat", _counting)

    await runner_mod.run_analysis(
        AnalysisJob(production_id="p1"), cfg, tmp_path, backends, backends.store
    )

    assert len(beats) >= 4, (
        f"a 0.4s stage at a 0.05s beat interval produced {len(beats)} beats; "
        "a run is only 'running' for as long as it keeps saying so"
    )


@pytest.mark.asyncio
async def test_the_beat_stops_when_the_run_does(tmp_path, monkeypatch):
    """The timer must not outlive the analysis.

    A beat left running would report a finished — or crashed — run as live
    forever, which is worse than the bug it replaces: `is_running()` is what
    stops a redelivery from paying twice.
    """
    import asyncio

    from clearframe import runner as runner_mod
    from clearframe.storage import AnalysisJob, build_backends
    from clearframe.config import ClearFrameConfig

    monkeypatch.setattr(runner_mod, "HEARTBEAT_EVERY_S", 0.02)

    class _Boom:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            raise RuntimeError("the scan died")

    monkeypatch.setattr(runner_mod, "Pipeline", _Boom)
    monkeypatch.setattr(
        runner_mod, "build_context",
        lambda cfg, production, out_root, **kw: _ctx(production),
    )

    _production(tmp_path, pid="p1")
    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"})
    backends = build_backends(cfg, tmp_path)

    with pytest.raises(RuntimeError):
        await runner_mod.run_analysis(
            AnalysisJob(production_id="p1"), cfg, tmp_path, backends, backends.store
        )

    before = backends.index.get("p1")
    await asyncio.sleep(0.1)
    after = backends.index.get("p1")

    assert before.heartbeat_at is None, "a failed run must not still hold the lease"
    assert after.heartbeat_at is None, "the timer outlived the run it was beating for"


@pytest.mark.asyncio
async def test_the_staleness_window_is_a_multiple_of_the_beat():
    """Two constants in two modules that have to stay in proportion.

    `HEARTBEAT_STALE_S` used to be a guess about how long a STAGE might take,
    because that is what the beat rode on. Now it beats on a timer, so the only
    honest basis for the window is how many beats may be missed. Four: enough to
    ride out a transient index failure, short enough to spot an abandoned run in
    minutes rather than a quarter of an hour.
    """
    from clearframe.runner import HEARTBEAT_EVERY_S
    from clearframe.storage.index import HEARTBEAT_STALE_S

    missed = HEARTBEAT_STALE_S / HEARTBEAT_EVERY_S
    assert 3 <= missed <= 6, (
        f"the window tolerates {missed:g} missed beats; under three is jumpy, "
        "over six and an abandoned run holds its lease for no good reason"
    )
