"""Measured rectangles, where the other container can read them.

Pre-grounding works on a laptop and silently does not work in production, for
two independent reasons and with no error from either.

The trigger lives in `create_production`'s closure — `_listen` fires
`_start_preground` at `stage_complete`/`triage` — and that closure only ever runs
under `InProcessJobQueue`. In the deployed topology the pipeline runs in the
worker container through `runner.run_analysis`, whose listener has no such hook.

And even with the hook, `_ground_cache`, `_pregrounded` and `_preground_progress`
are in-memory dicts inside `create_app`. Nothing the worker measured could reach
the API that serves `/ground`, and with `--max-instances=2` two API instances
cannot see each other's work either — so the same frame is paid for twice.

Measured on the deployed site: `GET /ground` took **13.98s cold and 0.19s warm**,
and the bucket held only `events/`, `media/` and `state/`. Locally the same call
answers in 11-14ms because the run warmed it. A reviewer in production waits
fourteen seconds for the first box on every new moment.

The store here is modelled on `EventLog` — the existing precedent for "worker
writes, API reads" — with one difference stated in `grounding.py`: one blob per
second rather than one per production, because four measurements are in flight
at once and a read-modify-write against a single object loses answers.
"""

import pytest

from clearframe.models import (
    BBox,
    ClearanceCategory,
    ElementType,
    Production,
    ProductionState,
    Prominence,
    TimeRange,
    TriagedElement,
)
from clearframe.storage.blobs import LocalBlobStore


def _state(pid="p1"):
    return ProductionState(
        production=Production(
            id=pid, title="t", footage_uri="c.mp4", duration_s=20.0, fps=30.0
        ),
        elements=[
            TriagedElement(
                id="1",
                label="Calvin Klein",
                element_type=ElementType.LOGO,
                description="a logo",
                time_ranges=[TimeRange(start_s=4.0, end_s=8.0)],
                prominence=Prominence(screen_time_s=4.0, frame_coverage=0.01,
                                      centrality=0.5, plot_integral=False),
                category=ClearanceCategory.TRADEMARK,
            ),
            TriagedElement(
                id="2",
                label="Bad clock",
                element_type=ElementType.LOGO,
                description="timing disowned",
                time_ranges=[TimeRange(start_s=1.0, end_s=2.0)],
                prominence=Prominence(screen_time_s=1.0, frame_coverage=0.01,
                                      centrality=0.5, plot_integral=False),
                category=ClearanceCategory.TRADEMARK,
                timing_reliable=False,
            ),
        ],
    )


def _boxes():
    return {"1": [BBox(ymin=0.1, xmin=0.2, ymax=0.3, xmax=0.4).model_dump()]}


def test_a_measurement_written_by_one_container_is_read_by_another(tmp_path):
    """The whole feature. The worker measures, the API serves."""
    from clearframe.grounding import GroundStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    GroundStore(blobs, "p1", "v1").write(6, _boxes())

    assert GroundStore(blobs, "p1", "v1").read(6) == _boxes()


def test_a_second_that_was_never_measured_reads_as_absent(tmp_path):
    """Absent is NOT an answer.

    `grounded: true` with no boxes is a conclusion — nothing is here — and
    `grounded: false` is a gap. A blob that does not exist is neither: it means
    nobody has looked, so the caller must fall through to measuring. Returning
    an empty answer would suppress every box on that frame for ever.
    """
    from clearframe.grounding import GroundStore

    assert GroundStore(LocalBlobStore(tmp_path / "b"), "p1", "v1").read(6) is None


def test_a_new_upload_is_never_served_the_old_film_s_rectangles(tmp_path):
    """`media_version` is IN the key path, not merely in a value.

    This exact failure has been paid for twice already — the browser's video
    cache, then `_ground_cache` keyed `(pid, second)` handing film B the
    rectangles measured on film A and marking them `grounded: true`.
    """
    from clearframe.grounding import GroundStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    GroundStore(blobs, "p1", "v1").write(6, _boxes())

    assert GroundStore(blobs, "p1", "v2").read(6) is None


def test_progress_crosses_the_container_boundary_too(tmp_path):
    """"measuring boxes N/M" has to report the WORKER's progress.

    The client polls the API, and in the deployed topology the API is not the
    thing doing the measuring.
    """
    from clearframe.grounding import GroundStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    GroundStore(blobs, "p1", "v1").write_progress(
        {"total": 40, "done": 12, "running": True, "skipped": 0}
    )

    assert GroundStore(blobs, "p1", "v1").read_progress()["done"] == 12


def test_no_progress_yet_is_distinguishable_from_finished(tmp_path):
    """`total: 0` means nobody has started; `running: false` with a total means
    it is done. The client latches its poll off on the second, so conflating
    them is what made "measuring boxes N/M" never appear on the restore path."""
    from clearframe.grounding import GroundStore

    assert GroundStore(LocalBlobStore(tmp_path / "b"), "p1", "v1").read_progress() is None


def test_only_seconds_with_a_reliable_appearance_are_planned():
    """A finding whose timecodes were disowned has no moment to measure."""
    from clearframe.grounding import plan_seconds

    planned = plan_seconds(_state())

    assert 6 in planned, "the midpoint of the good appearance"
    assert 1 not in planned and 2 not in planned, "the disowned one was measured"


def test_midpoints_are_planned_before_the_filler():
    """A clip long enough to hit the cap must still get its midpoints."""
    from clearframe.grounding import plan_seconds

    planned = plan_seconds(_state())

    assert planned[0] == 6, f"midpoint first, got {planned}"
    assert set(planned) == {4, 5, 6, 7, 8}


def test_elements_on_screen_excludes_the_disowned_ones():
    """Asking a model to place something that is not there invites it to
    oblige, and asking costs a call."""
    from clearframe.grounding import elements_at

    assert [el.id for el in elements_at(_state(), 6.0)] == ["1"]
    assert elements_at(_state(), 1.5) == []


@pytest.mark.asyncio
async def test_warming_measures_every_second_and_persists_each_one(tmp_path):
    """The driver, end to end, with the model stubbed."""
    from clearframe.grounding import GroundStore, warm

    blobs = LocalBlobStore(tmp_path / "bucket")
    store = GroundStore(blobs, "p1", "v1")
    asked: list[float] = []

    async def measure(at_s, here):
        asked.append(at_s)
        return _boxes()

    progress = await warm(store, _state(), measure, cap=150)

    assert sorted(asked) == [4.0, 5.0, 6.0, 7.0, 8.0]
    assert progress["done"] == 5 and progress["running"] is False
    assert store.read(6) == _boxes()
    assert store.read_progress()["done"] == 5


@pytest.mark.asyncio
async def test_warming_stops_at_the_cap_and_says_so(tmp_path):
    """A capped warm-up is never silent: an unwarmed second still works, it is
    just slow, and the reviewer should not have to guess which."""
    from clearframe.grounding import GroundStore, warm

    store = GroundStore(LocalBlobStore(tmp_path / "b"), "p1", "v1")

    async def measure(at_s, here):
        return _boxes()

    progress = await warm(store, _state(), measure, cap=2)

    assert progress["total"] == 2
    assert progress["skipped"] == 3


@pytest.mark.asyncio
async def test_one_failed_frame_does_not_stop_the_warm_up(tmp_path):
    """A warm cache is a nicety, never a failure. It runs inside the analysis
    request on the worker, so an exception here would fail the whole run."""
    from clearframe.grounding import GroundStore, warm

    store = GroundStore(LocalBlobStore(tmp_path / "b"), "p1", "v1")

    async def measure(at_s, here):
        if at_s == 6.0:
            raise RuntimeError("the model said no")
        return _boxes()

    progress = await warm(store, _state(), measure, cap=150)

    assert progress["done"] == 5, "a failed frame must still count as attempted"
    assert store.read(4) == _boxes()
    assert store.read(6) is None, "a failure must not be cached as an answer"


@pytest.mark.asyncio
async def test_an_already_measured_second_is_not_paid_for_again(tmp_path):
    """Two API instances, or a re-run, must not re-buy what the bucket has."""
    from clearframe.grounding import GroundStore, warm

    store = GroundStore(LocalBlobStore(tmp_path / "b"), "p1", "v1")
    store.write(6, _boxes())
    asked = []

    async def measure(at_s, here):
        asked.append(at_s)
        return _boxes()

    await warm(store, _state(), measure, cap=150)

    assert 6.0 not in asked, "a second already in the bucket was measured again"


@pytest.mark.asyncio
async def test_the_worker_warms_the_boxes_during_the_run(tmp_path, monkeypatch):
    """The half that was missing in production.

    `create_production`'s listener fires `_start_preground` at triage, and that
    closure only ever runs under `InProcessJobQueue`. The deployed topology runs
    the pipeline in the worker through `runner.run_analysis`, whose listener had
    no such hook — so on the deployed site nothing was ever warmed and every
    pause paid 14 seconds.
    """
    import json

    from clearframe import runner as runner_mod
    from clearframe.config import ClearFrameConfig
    from clearframe.grounding import GroundStore
    from clearframe.storage import AnalysisJob, build_backends

    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "p1.json").write_text(_state().model_dump_json())
    media = tmp_path / "media" / "p1"
    media.mkdir(parents=True)
    (media / "footage.mp4").write_bytes(b"\x00" * 2048)

    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"})
    backends = build_backends(cfg, tmp_path)

    monkeypatch.setattr(
        "clearframe.grounding.extract_frame", lambda path, at_s, **kw: b"\xff\xd8f"
    )

    class _Grounder:
        async def ground_frame(self, image, labels):
            return {labels[0]: [BBox(ymin=0.1, xmin=0.2, ymax=0.3, xmax=0.4)]}

    monkeypatch.setattr("clearframe.grounding.build_client", lambda cfg: _Grounder())

    class _TriagePipeline:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            ctx.state.stage_status["triage"] = "complete"
            ctx.listener({"type": "stage_complete", "stage": "triage"})
            ctx.store.save(ctx.state)
            return ctx.state

    monkeypatch.setattr(runner_mod, "Pipeline", _TriagePipeline)

    await runner_mod.run_analysis(
        AnalysisJob(production_id="p1"), cfg, tmp_path, backends, backends.store
    )

    version = backends.blobs.version("media/p1/footage.mp4") or ""
    store = GroundStore(backends.blobs, "p1", version)
    assert store.read(6) is not None, "the worker finished a run without warming"
    assert store.read_progress()["running"] is False


@pytest.mark.asyncio
async def test_the_warm_up_finishes_before_the_request_does(tmp_path, monkeypatch):
    """Cloud Run throttles CPU to near-zero once a response is sent.

    That is the entire reason the worker container exists. A `create_task` left
    running past the end of `run_analysis` would be frozen mid-warm — the
    original background-task bug, re-introduced one layer down.
    """
    from clearframe import runner as runner_mod
    from clearframe.config import ClearFrameConfig
    from clearframe.storage import AnalysisJob, build_backends

    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "p1.json").write_text(_state().model_dump_json())
    media = tmp_path / "media" / "p1"
    media.mkdir(parents=True)
    (media / "footage.mp4").write_bytes(b"\x00" * 2048)

    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"})
    backends = build_backends(cfg, tmp_path)
    finished: list[str] = []

    monkeypatch.setattr(
        "clearframe.grounding.extract_frame", lambda path, at_s, **kw: b"\xff\xd8f"
    )

    class _SlowGrounder:
        async def ground_frame(self, image, labels):
            import asyncio

            await asyncio.sleep(0.05)
            finished.append("frame")
            return {labels[0]: [BBox(ymin=0.1, xmin=0.2, ymax=0.3, xmax=0.4)]}

    monkeypatch.setattr("clearframe.grounding.build_client", lambda cfg: _SlowGrounder())

    class _TriagePipeline:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            ctx.state.stage_status["triage"] = "complete"
            ctx.listener({"type": "stage_complete", "stage": "triage"})
            ctx.store.save(ctx.state)
            return ctx.state

    monkeypatch.setattr(runner_mod, "Pipeline", _TriagePipeline)

    await runner_mod.run_analysis(
        AnalysisJob(production_id="p1"), cfg, tmp_path, backends, backends.store
    )

    assert len(finished) == 5, (
        f"the run returned with {len(finished)}/5 frames measured; the rest "
        "would be frozen by the CPU throttle"
    )
