"""How a production disappears from a dashboard while its state sits in a bucket.

A deployed upload answered `200 queued`, was polled twice with its stages
advancing, and then was absent from `/api/productions` for the rest of the run —
`GET /api/productions/{pid}` returning 404. Something was advancing its stages,
so the row existed and the worker was running it.

Three mechanisms in the Firestore twin can each produce that, and none of them
exists in the local twin, which is the only one the suite exercised:

  - `record_stage`, `heartbeat` and `clear_heartbeat` write with `merge=True`,
    which **creates the document if it is absent** — carrying only those fields
    and no `id`. `id` is required on `IndexRow`, so such a document fails
    validation for ever: invisible to every listing, and `None` from `get()`.
  - `list_for` dropped an unparseable row with a bare `except: continue` and no
    log line, so that invisibility left no trace anywhere.
  - the listing filter is `owner_uid in [uid, None, ""]`, and Firestore's `IN`
    is a disjunction of field equalities that cannot express IS_NULL. A row
    whose `owner_uid` is null is not returned by it.

And `BlobStateStore.save` fed all three: `self._index.get(pid) or IndexRow(id=pid)`
followed by a full `.set()` rebuilt the row from defaults on any read miss,
dropping `owner_uid` — the field the listing filters on.

The fake below models Firestore's actual semantics, in particular that `IN`
does not match a null field. A fake that matched it would prove the opposite of
what is true in production.
"""

import pytest

from clearframe.storage.index import IndexRow


class _Snap:
    def __init__(self, data, key=""):
        self._data = data
        self.id = key
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Doc:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        return _Snap(self._store.get(self._key), self._key)

    def set(self, data, merge=False):
        if merge:
            current = dict(self._store.get(self._key) or {})
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(current.get(k), dict):
                    current[k] = {**current[k], **v}
                else:
                    current[k] = v
            self._store[self._key] = current
        else:
            self._store[self._key] = dict(data)

    def delete(self):
        self._store.pop(self._key, None)


class _Query:
    def __init__(self, store, predicate=None):
        self._store = store
        self._predicate = predicate

    def where(self, filter=None):  # noqa: A002 - matches the SDK's keyword
        return _Query(self._store, filter)

    def stream(self):
        for key, data in list(self._store.items()):
            if self._predicate is None or self._predicate(data):
                yield _Snap(data, key)

    def document(self, key):
        return _Doc(self._store, key)


class _FieldFilter:
    """Firestore comparison semantics, including the one that bites.

    `IN` is a disjunction of equality comparisons on a field. A null-valued
    field is not equal to anything in the array, so a `None` element neither
    matches nulls nor acts as a wildcard — it is dead weight at best, and
    Firestore documents null as unsupported in `in`/`not-in`.
    """

    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value

    def __call__(self, data):
        have = data.get(self.field)
        if self.op == "in":
            if have is None:
                return False
            return have in [v for v in self.value if v is not None]
        if self.op == "==":
            return have == self.value
        raise AssertionError(f"unmodelled operator {self.op}")


@pytest.fixture
def firestore(monkeypatch):
    """A `FirestoreProductionIndex` over an in-memory collection."""
    import sys
    import types

    from clearframe.storage.cloud import FirestoreProductionIndex

    store: dict = {}

    base_query = types.ModuleType("google.cloud.firestore_v1.base_query")
    base_query.FieldFilter = _FieldFilter
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1.base_query", base_query)

    index = FirestoreProductionIndex("a-project")
    monkeypatch.setattr(index, "_c", lambda: _Query(store))
    index._raw = store
    return index


def test_a_heartbeat_on_an_absent_row_leaves_a_readable_one(firestore):
    """`merge=True` creates the document. It must create a valid one.

    A row without `id` fails `IndexRow` validation, so it is dropped from every
    listing and returns `None` from `get()` for ever — which then makes
    `BlobStateStore.save` rebuild it from defaults and lose the owner too.
    """
    firestore.heartbeat("p1")

    assert firestore.get("p1") is not None, "the row it just wrote is unreadable"
    assert firestore._raw["p1"].get("id") == "p1"


def test_a_stage_record_on_an_absent_row_leaves_a_readable_one(firestore):
    firestore.record_stage("p1", "scan", "running")

    row = firestore.get("p1")
    assert row is not None and row.stage_status["scan"] == "running"


def test_an_unowned_row_is_still_listed(firestore):
    """The demo production carries no owner, and everyone may see it.

    `in [uid, None, ""]` cannot match a null field — the null element is not a
    wildcard. This is the filter as deployed, and it hid every row whose owner
    had been lost.
    """
    firestore.put(IndexRow(id="demo", owner_uid=None, title="Golden Hour"))
    firestore.put(IndexRow(id="p1", owner_uid="alice", title="Alice's film"))

    ids = [r.id for r in firestore.list_for("alice")]

    assert "demo" in ids, "an unowned production is invisible to a signed-in user"
    assert "p1" in ids


def test_another_account_s_production_is_still_not_listed(firestore):
    """The fix must not widen the filter into a leak."""
    firestore.put(IndexRow(id="p1", owner_uid="alice"))
    firestore.put(IndexRow(id="p2", owner_uid="bob"))

    assert [r.id for r in firestore.list_for("alice")] == ["p1"]


def test_a_dropped_row_says_so(firestore, caplog):
    """Silence is what made this untraceable.

    `except Exception: continue` with no log meant a production vanished from
    the dashboard leaving no evidence anywhere — not in the logs, not in the
    metrics, and the state blob still sitting in the bucket looking healthy.
    """
    firestore.put(IndexRow(id="p1", owner_uid="alice"))
    firestore._raw["broken"] = {"owner_uid": "alice", "title": "no id here"}

    with caplog.at_level("WARNING"):
        rows = firestore.list_for("alice")

    assert [r.id for r in rows] == ["p1"]
    assert any("broken" in r.getMessage() for r in caplog.records), (
        "a row was dropped from the listing without a word about it"
    )


def _state_store(firestore):
    import tempfile
    from pathlib import Path

    from clearframe.storage.blobs import LocalBlobStore
    from clearframe.storage.state import BlobStateStore

    return BlobStateStore(LocalBlobStore(Path(tempfile.mkdtemp())), firestore)


def _save(store, pid="p1", title="t"):
    from clearframe.models import Production, ProductionState

    store.save(ProductionState(production=Production(
        id=pid, title=title, footage_uri="c.mp4", duration_s=1.0, fps=24.0)))


def test_saving_state_does_not_orphan_a_row_it_could_not_read(firestore):
    """The read-modify-write that fed every mechanism above.

    `self._index.get(pid) or IndexRow(id=pid)` followed by a full `.set()`
    rebuilds the row from defaults whenever the read misses — and the read
    misses on any row that fails validation, which is exactly the state an
    `id`-less merge write leaves behind. `owner_uid` is what the listing filters
    on, so one unreadable row became a permanently invisible production.

    Writing only the fields this caller owns fixes both halves: the stored owner
    survives a read it could not parse, and the row becomes valid again.
    """
    firestore._raw["p1"] = {"owner_uid": "alice", "title": "was here"}
    assert firestore.get("p1") is None, "precondition: the row does not validate"

    _save(_state_store(firestore), title="Renamed")

    row = firestore.get("p1")
    assert row is not None, "the row is still unreadable after a save"
    assert row.owner_uid == "alice", "the save orphaned the production"
    assert row.title == "Renamed"


def test_saving_state_does_not_touch_the_lease(firestore):
    """A full `.set()` reverted anything written since the read.

    `Pipeline.run` saves after every stage while the beat timer writes every
    thirty seconds, so the two collide by design rather than by accident. The
    save has no business writing the lease at all — and now does not, which is
    why there is no window left to race in.
    """
    firestore.put(IndexRow(id="p1", owner_uid="alice"))
    store = _state_store(firestore)
    firestore.heartbeat("p1")
    beating = firestore.get("p1").heartbeat_at

    _save(store)

    assert firestore.get("p1").heartbeat_at == beating, (
        "the save reverted the lease, so a redelivery may start a second paid run"
    )
