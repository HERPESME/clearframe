"""The rights ledger has to reach the container doing the analysis.

`build_context` read the ledger off the local filesystem —
`LicenceStore(out_root / "state", owner_uid=...)` — while the API writes an
uploaded ledger to *its* filesystem. Both Cloud Run services run `--out /tmp/out`
on separate instances, so in the cloud profile the worker's coverage stage always
opened an empty ledger no matter what the user had uploaded.

That is the one direction this feature must never be wrong in. The ledger exists
to answer "are we already licensed for this?", and an empty ledger answers
NOT_COVERED / UNKNOWN for everything — so the failure is quiet and reads as a
working product with pessimistic findings, rather than as a broken one.

Media, state and events all crossed to the blob store when the topology split.
The ledger was left behind, and nothing noticed because the local profile — the
only one the suite exercised — has one filesystem.
"""

import pytest

from clearframe.config import ClearFrameConfig
from clearframe.models import LicenceGrant
from clearframe.storage import build_backends
from clearframe.storage.blobs import LocalBlobStore


def _grant(work="Nike swoosh", holder="Nike, Inc.") -> LicenceGrant:
    return LicenceGrant(
        id="LIC-001",
        rights_holder=holder,
        work=work,
        territories=["US"],
        media=["theatrical"],
        starts="2020-01-01",
        expires="2030-01-01",
    )


def test_a_ledger_written_by_one_container_is_read_by_another(tmp_path):
    """The whole defect, in the shape the deployment actually has.

    Two `Backends` over one bucket and two different working directories: the
    API's `/tmp/out` and the worker's. Nothing about the ledger may depend on
    those two directories being the same filesystem, because they never are.
    """
    blobs = LocalBlobStore(tmp_path / "bucket")

    api = build_backends(
        ClearFrameConfig.from_env({}), tmp_path / "api-tmp"
    )._replace(blobs=blobs)
    worker = build_backends(
        ClearFrameConfig.from_env({}), tmp_path / "worker-tmp"
    )._replace(blobs=blobs)

    from clearframe.storage.licences import BlobLicenceStore

    BlobLicenceStore(api.blobs, "alice").save([_grant()])
    reached = BlobLicenceStore(worker.blobs, "alice").load()

    assert [g.work for g in reached] == ["Nike swoosh"], (
        "the worker cannot see the ledger the API was given"
    )


def test_one_account_s_ledger_is_not_another_s(tmp_path):
    """Isolation survives the move to the bucket.

    Being wrong in the COVERED direction is the single failure the ledger must
    not have: Alice's Nike grant marking Bob's Nike finding cleared, in Bob's
    E&O dossier.
    """
    from clearframe.storage.licences import BlobLicenceStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    BlobLicenceStore(blobs, "alice").save([_grant()])

    assert BlobLicenceStore(blobs, "bob").load() == []


def test_the_unowned_ledger_is_its_own_shelf(tmp_path):
    """The CLI, the MCP server and the demo seed have no signed-in user.

    They share one ledger deliberately, and it must not collide with a real
    account's — nor be reachable by naming an empty uid.
    """
    from clearframe.storage.licences import BlobLicenceStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    BlobLicenceStore(blobs, "").save([_grant(work="Shared")])
    BlobLicenceStore(blobs, "alice").save([_grant(work="Alice only")])

    assert [g.work for g in BlobLicenceStore(blobs, "").load()] == ["Shared"]
    assert [g.work for g in BlobLicenceStore(blobs, "alice").load()] == [
        "Alice only"
    ]


def test_a_uid_cannot_escape_its_own_key(tmp_path):
    """A uid arrives from a verified token, but the key is still built from it."""
    from clearframe.storage.licences import BlobLicenceStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    hostile = BlobLicenceStore(blobs, "../../etc/passwd")

    hostile.save([_grant()])

    assert ".." not in hostile.key
    assert "/" not in hostile.key.removeprefix("licences/")


def test_a_malformed_row_does_not_sink_the_ledger(tmp_path):
    """Same tolerance the local store has: one bad grant is not a lost ledger."""
    import json

    from clearframe.storage.licences import BlobLicenceStore

    blobs = LocalBlobStore(tmp_path / "bucket")
    store = BlobLicenceStore(blobs, "alice")
    blobs.put(
        store.key,
        json.dumps(
            {"licences": [{"nonsense": True}, _grant().model_dump(mode="json")]}
        ).encode(),
    )

    assert [g.work for g in store.load()] == ["Nike swoosh"]


def test_an_absent_ledger_is_empty_not_an_error(tmp_path):
    """A production with no ledger is a valid state — every finding reads
    UNKNOWN or NOT_COVERED, which is the honest answer."""
    from clearframe.storage.licences import BlobLicenceStore

    assert BlobLicenceStore(LocalBlobStore(tmp_path / "b"), "nobody").load() == []


def test_the_worker_runs_with_the_uploader_s_ledger(tmp_path, monkeypatch):
    """End to end: the uid on the job selects the ledger the analysis reads.

    `owner_uid` has been on the wire since the queue was written. It reached
    `build_context`, which then ignored it in favour of a local file that does
    not exist on this container.
    """
    import json

    from clearframe import runner as runner_mod
    from clearframe.storage import AnalysisJob

    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "p1.json").write_text(json.dumps({
        "production": {"id": "p1", "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 10.0, "fps": 24.0},
        "elements": [],
        "stage_status": {},
    }))

    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"})
    backends = build_backends(cfg, tmp_path)
    # Through the backends' own factory, which is what the API upload uses. The
    # point is that whatever shelf this profile hands out is the shelf the run
    # reads — not that it happens to be a bucket.
    backends.ledger("alice").save([_grant()])

    seen: list = []

    class _Peek:
        def __init__(self, stages):
            pass

        async def run(self, ctx):
            seen.append(list(ctx.licences))
            return ctx.state

    monkeypatch.setattr(runner_mod, "Pipeline", _Peek)

    import asyncio

    asyncio.run(runner_mod.run_analysis(
        AnalysisJob(production_id="p1", owner_uid="alice"),
        cfg, tmp_path, backends, backends.store,
    ))

    assert seen and [g.work for g in seen[0]] == ["Nike swoosh"], (
        "the coverage stage would report every finding uncovered"
    )


def test_the_cli_ledger_path_is_untouched(tmp_path):
    """`pip install .` with no bucket still reads `<out>/state/licences.json`.

    The CLI, the MCP server and the demo seed all depend on that exact path, and
    a working directory written before any of this must keep working.
    """
    from clearframe.pipeline import build_context
    from clearframe.store import LicenceStore

    LicenceStore(tmp_path / "state").save([_grant(work="From the CLI")])

    from clearframe.models import Production

    ctx = build_context(
        ClearFrameConfig.from_env({"CLEARFRAME_MODE": "demo"}),
        Production(id="p1", title="t", footage_uri="c.mp4", duration_s=1.0, fps=24.0),
        tmp_path,
    )

    assert [g.work for g in ctx.licences] == ["From the CLI"]


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
