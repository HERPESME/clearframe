"""The clearance record in a bucket, with the dashboard row kept in step.

`ProductionState` is 227KB for a 42-second clip and grows with the footage, so
it cannot be a Firestore document — the limit is 1 MiB and a feature would blow
straight through it. It is a blob. What the dashboard lists is a few hundred
bytes that wants ordering and an owner filter, and that is a different storage
problem.

The pairing is the risk. Two stores can disagree, and the symptom would be a
production that exists but is not listed, or a row whose progress bar stopped
moving while the analysis carried on. `Pipeline.run` saves after every stage, so
that save is the one place where both can be updated together.
"""

import pytest

from clearframe.models import Production, ProductionState
from clearframe.storage.blobs import LocalBlobStore
from clearframe.storage.index import IndexRow, LocalProductionIndex
from clearframe.storage.state import BlobStateStore


@pytest.fixture
def parts(tmp_path):
    blobs = LocalBlobStore(tmp_path / "blobs")
    index = LocalProductionIndex(tmp_path / "index")
    return blobs, index, BlobStateStore(blobs, index)


def _state(pid="p1", title="A Film", stages=None):
    return ProductionState(
        production=Production(id=pid, title=title, footage_uri="c.mp4", duration_s=10.0),
        stage_status=stages or {},
    )


def test_a_state_survives_the_round_trip(parts):
    _, _, store = parts
    store.save(_state(title="Golden Hour"))

    assert store.load("p1").production.title == "Golden Hour"


def test_a_missing_production_raises_the_error_callers_already_catch(parts):
    """FileNotFoundError, not KeyError: `cli._try_resume` and the MCP server
    both catch it to mean "nothing persisted yet"."""
    _, _, store = parts

    with pytest.raises(FileNotFoundError):
        store.load("never-was")


def test_saving_the_state_updates_the_dashboard_row(parts):
    """The whole reason the two are wired together here rather than at every
    call site that saves."""
    _, index, store = parts

    store.save(_state(title="Golden Hour", stages={"script": "complete"}))

    row = index.get("p1")
    assert row.title == "Golden Hour"
    assert row.stage_status["script"] == "complete"


def test_progress_reaches_the_row_on_every_save(parts):
    """`Pipeline.run` saves after each stage, so this is how a dashboard in one
    container follows a run in another."""
    _, index, store = parts
    store.save(_state(stages={"script": "complete"}))

    store.save(_state(stages={"script": "complete", "scan": "complete"}))

    assert len(index.get("p1").stage_status) == 2


def test_saving_does_not_clobber_who_owns_it(parts):
    """The owner is set once, at upload, and the state knows nothing about it —
    ownership is a deployment fact, not part of the clearance record. A save
    that reset it would hand every production back to everybody."""
    _, index, store = parts
    index.put(IndexRow(id="p1", owner_uid="alice", title="placeholder"))

    store.save(_state(title="Renamed"))

    row = index.get("p1")
    assert row.owner_uid == "alice"
    assert row.title == "Renamed"


def test_listing_ids_skips_the_rights_ledger(parts):
    """`state/` also holds `licences.json`, and per-user ledgers add a
    `licences-{uid}` shape. Returning either as a production id is exactly the
    bug the reserved-name rule exists to prevent."""
    blobs, _, store = parts
    store.save(_state("p1"))
    store.save(_state("p2"))
    blobs.put("state/licences.json", b"[]")
    blobs.put("state/licences-abc123.json", b"[]")

    assert store.production_ids() == ["p1", "p2"]


def test_the_state_store_works_without_an_index(parts, tmp_path):
    """The CLI and the MCP server have no dashboard to keep in step."""
    blobs = LocalBlobStore(tmp_path / "solo")
    store = BlobStateStore(blobs)

    store.save(_state())

    assert store.load("p1").production.id == "p1"


def test_it_satisfies_the_interface_the_pipeline_already_speaks(parts):
    """Same three methods as `LocalJsonStore`. A wider interface would mean
    changing the pipeline, review, the CLI and MCP to gain nothing."""
    _, _, store = parts

    for name in ("save", "load", "production_ids"):
        assert callable(getattr(store, name))
