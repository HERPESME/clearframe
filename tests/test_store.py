from clearframe.models import Production, ProductionState
from clearframe.store import LocalJsonStore


def test_save_load_roundtrip(tmp_path):
    store = LocalJsonStore(tmp_path)
    s = ProductionState(
        production=Production(id="p1", title="T", footage_uri="u", duration_s=1)
    )
    store.save(s)
    assert store.load("p1").production.title == "T"
