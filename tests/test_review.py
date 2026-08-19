import pytest

from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.review import (
    RoleNotPermittedError,
    UnknownElementError,
    generate_dossier_async,
    record_decision,
)
from clearframe.stages.dossier import ReviewPendingError

AT = "2026-08-15T12:00:00Z"


async def _ran(tmp_path):
    ctx = demo_context(tmp_path)
    await Pipeline(build_demo_pipeline()).run(ctx)
    return ctx.store


async def test_record_decision_appends_audit(tmp_path):
    store = await _ran(tmp_path)
    state = record_decision(
        store, "demo", "e1", "license", "ok", role="legal", reviewer="ada", at=AT
    )
    assert state.decisions["e1"].action == "license"
    assert state.audit_log[-1].event == "decision"
    assert state.audit_log[-1].actor == "ada"
    assert "e1:license" in state.audit_log[-1].detail
    # revision appends a second event, never rewrites
    state = record_decision(
        store, "demo", "e1", "escalate", "no", role="legal", reviewer="ada", at=AT
    )
    assert len([e for e in state.audit_log if e.event == "decision"]) == 2


async def test_editor_role_rejected(tmp_path):
    store = await _ran(tmp_path)
    with pytest.raises(RoleNotPermittedError):
        record_decision(store, "demo", "e1", "license", "", role="editor", reviewer="x", at=AT)


async def test_unknown_element_rejected(tmp_path):
    store = await _ran(tmp_path)
    with pytest.raises(UnknownElementError):
        record_decision(store, "demo", "nope", "license", "", role="legal", reviewer="x", at=AT)


async def test_generate_dossier_service(tmp_path):
    store = await _ran(tmp_path)
    with pytest.raises(ReviewPendingError):
        await generate_dossier_async(store, tmp_path, "demo", at=AT)
    state = store.load("demo")
    for el in state.elements:
        record_decision(store, "demo", el.id, "license", "", role="legal", reviewer="x", at=AT)
    artifacts = await generate_dossier_async(store, tmp_path, "demo", at=AT)
    assert "dossier.html" in artifacts
    events = [a.event for a in store.load("demo").audit_log]
    assert "dossier_generated" in events
    assert "watch_created" in events  # standing watches follow the dossier


async def test_dossier_html_includes_audit_trail(tmp_path):
    store = await _ran(tmp_path)
    state = store.load("demo")
    for el in state.elements:
        record_decision(store, "demo", el.id, "license", "", role="legal", reviewer="x", at=AT)
    await generate_dossier_async(store, tmp_path, "demo", at=AT)
    html = (tmp_path / "dossier.html").read_text()
    assert "Audit trail" in html


def test_dossier_ctx_uses_live_parallel_client_in_live_env(tmp_path, monkeypatch):
    # A live deployment must create watches through the live Parallel client,
    # not silently through fixtures (live-observed gap, 2026-08-19).
    from clearframe.integrations.parallel_client import (
        FixtureParallelClient,
        LiveParallelClient,
    )
    from clearframe.models import Production, ProductionState
    from clearframe.review import _dossier_ctx

    state = ProductionState(
        production=Production(
            id="p1", title="T", footage_uri="f.mp4", duration_s=10.0
        )
    )
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "k")
    ctx = _dossier_ctx(tmp_path, state)
    assert isinstance(ctx.parallel, LiveParallelClient)

    monkeypatch.setenv("CLEARFRAME_MODE", "demo")
    ctx = _dossier_ctx(tmp_path, state)
    assert isinstance(ctx.parallel, FixtureParallelClient)
