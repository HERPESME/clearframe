"""Who owns a production, and whether anyone is still working on it.

Two facts in `GET /api/productions` could only ever be answered by the one
process that happened to be running the analysis:

  - `updated_at` was the state file's mtime, read straight off the filesystem
    (`store.root / f"{pid}.json"`).stat().st_mtime.
  - `running` was `pid in _live_runs`, a `set` in the app's closure whose own
    docstring says "in this process. A restart empties it, which is the point."

Both are fine while there is exactly one process. The moment the analysis runs
in a *worker container*, `_live_runs` on the API container is empty, so every
live job reports itself `interrupted` to the dashboard — and the client acts on
that, refusing to poll and showing a "this run died" banner over a run that is
proceeding normally.

The replacement is a heartbeat. The worker says "still here" every few seconds
while it works; a row whose heartbeat has gone stale is genuinely abandoned,
whatever machine it was on. That preserves the honest three-way distinction the
current code makes — complete, running, interrupted — without requiring the
answer to come from the process that owns the run.
"""

import json
import time

import pytest

from clearframe.storage.index import (
    HEARTBEAT_STALE_S,
    IndexRow,
    LocalProductionIndex,
)


@pytest.fixture
def index(tmp_path):
    return LocalProductionIndex(tmp_path / "index")


def row(pid="p1", uid="alice", **kw):
    return IndexRow(id=pid, owner_uid=uid, title=kw.pop("title", "A Film"), **kw)


def test_a_row_survives_the_round_trip(index):
    index.put(row(title="Golden Hour"))

    got = index.get("p1")

    assert got is not None
    assert got.title == "Golden Hour"
    assert got.owner_uid == "alice"


def test_an_unknown_production_is_none_not_an_error(index):
    assert index.get("nope") is None


def test_listing_is_scoped_to_the_owner(index):
    """The defect this exists to fix: every signed-in user saw everyone's work."""
    index.put(row("p1", "alice"))
    index.put(row("p2", "bob"))

    assert [r.id for r in index.list_for("alice")] == ["p1"]
    assert [r.id for r in index.list_for("bob")] == ["p2"]


def test_listing_with_no_owner_returns_everything(index):
    """Authentication is opt-in. With it off there is no user to scope to, and
    the app must behave exactly as it did before ownership existed — which is
    what keeps demo mode and the credential-free smoke script green."""
    index.put(row("p1", "alice"))
    index.put(row("p2", "bob"))

    assert {r.id for r in index.list_for(None)} == {"p1", "p2"}


def test_listing_is_newest_first(index):
    """The client restores the first row; store order once sorted `demo` ahead
    of a user's own upload and it looked like the analysis had been lost."""
    index.put(row("old", updated_at=100.0))
    index.put(row("new", updated_at=200.0))
    index.put(row("mid", updated_at=150.0))

    assert [r.id for r in index.list_for("alice")] == ["new", "mid", "old"]


def test_a_fresh_heartbeat_means_running(index):
    index.put(row(stage_status={"script": "complete"}))

    index.heartbeat("p1")

    assert index.get("p1").is_running()


def test_a_stale_heartbeat_means_interrupted_not_running(index):
    """The run died with its machine. Saying 'running' would leave the client
    polling for ever; saying 'complete' would hide the missing stages."""
    index.put(row(stage_status={"script": "complete"},
                  heartbeat_at=time.time() - HEARTBEAT_STALE_S - 1))

    got = index.get("p1")

    assert not got.is_running()
    assert got.is_interrupted()


def test_a_production_that_never_started_is_not_interrupted(index):
    """No heartbeat ever recorded and no stages done is a fresh row, not a
    corpse. Only something that got part-way and stopped is interrupted."""
    got = index.put(row(stage_status={})) or index.get("p1")

    assert not got.is_interrupted()


def test_a_finished_production_is_neither_running_nor_interrupted(index, monkeypatch):
    from clearframe.pipeline import ANALYSIS_STAGES

    index.put(row(stage_status={s: "complete" for s in ANALYSIS_STAGES}))
    index.heartbeat("p1")

    got = index.get("p1")
    assert not got.is_running()
    assert not got.is_interrupted()


def test_clearing_the_heartbeat_ends_the_run(index):
    """A worker that finishes cleanly stops beating on purpose, so the row
    settles immediately rather than after the staleness window."""
    from clearframe.pipeline import ANALYSIS_STAGES

    index.put(row(stage_status={s: "complete" for s in ANALYSIS_STAGES}))
    index.heartbeat("p1")

    index.clear_heartbeat("p1")

    assert index.get("p1").heartbeat_at is None


def test_heartbeating_an_unknown_production_is_not_an_error(index):
    """A retried task for a deleted production must not 500 the worker."""
    index.heartbeat("ghost")


def test_stage_status_updates_without_rewriting_the_whole_row(index):
    index.put(row(title="Keep Me"))

    index.record_stage("p1", "scan", "complete")

    got = index.get("p1")
    assert got.stage_status["scan"] == "complete"
    assert got.title == "Keep Me"


def test_recording_a_stage_advances_updated_at(index):
    index.put(row(updated_at=1.0))

    index.record_stage("p1", "scan", "complete")

    assert index.get("p1").updated_at > 1.0


# --- the backfill: productions that predate this module ------------------------
#
# The CLI, the MCP server and forty-odd tests write `<out>/state/{pid}.json`
# directly and know nothing about an index. Without a fallback every one of
# those productions would simply disappear from the dashboard.


def _state_file(tmp_path, pid="old", title="Before The Index", stages=None):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{pid}.json").write_text(
        json.dumps(
            {
                "production": {"id": pid, "title": title, "footage_uri": "c.mp4"},
                "elements": [],
                "stage_status": stages or {},
            }
        )
    )
    return state_dir


def test_a_production_with_no_index_row_is_read_from_its_state(tmp_path):
    state_dir = _state_file(tmp_path)
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)

    got = index.get("old")

    assert got is not None
    assert got.title == "Before The Index"


def test_a_backfilled_row_keeps_its_stage_progress(tmp_path):
    state_dir = _state_file(tmp_path, stages={"script": "complete", "scan": "complete"})
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)

    assert index.get("old").stage_status["scan"] == "complete"


def test_a_backfilled_row_is_never_running(tmp_path):
    """Nothing is claiming it, so an unfinished one is interrupted — which is
    exactly what a run that died with its process is."""
    state_dir = _state_file(tmp_path, stages={"script": "complete"})
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)

    got = index.get("old")
    assert not got.is_running()
    assert got.is_interrupted()


def test_backfilled_rows_appear_in_the_listing(tmp_path):
    state_dir = _state_file(tmp_path)
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)

    assert [r.id for r in index.list_for(None)] == ["old"]


def test_the_licence_ledger_is_not_a_production(tmp_path):
    """`state/` also holds the rights ledger; globbing it blindly is the bug
    `RESERVED_STATE_FILES` exists to prevent, and per-user ledgers add a
    `licences-{uid}` shape that the same rule has to cover."""
    state_dir = _state_file(tmp_path)
    (state_dir / "licences.json").write_text("[]")
    (state_dir / "licences-abc123.json").write_text("[]")
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)

    assert [r.id for r in index.list_for(None)] == ["old"]


def test_an_owned_row_wins_over_the_backfill(tmp_path):
    """Once a production has a real row, the state file stops being the source
    of truth for who owns it."""
    state_dir = _state_file(tmp_path, pid="p1", title="Stale Title")
    index = LocalProductionIndex(tmp_path / "index", state_dir=state_dir)
    index.put(row("p1", "alice", title="Real Title"))

    assert index.get("p1").title == "Real Title"
    assert index.get("p1").owner_uid == "alice"


def test_an_unowned_production_stays_visible_to_everyone(index):
    """Ownership is opt-in exactly as authentication is. A production written
    with auth off, or by the CLI, or the shared demo, belongs to nobody — and
    hiding it from everybody would make demo mode look broken."""
    index.put(IndexRow(id="shared", owner_uid=None, title="Golden Hour"))
    index.put(row("mine", "alice"))

    assert {r.id for r in index.list_for("alice")} == {"shared", "mine"}
    assert {r.id for r in index.list_for("bob")} == {"shared"}
