"""The cloud twins must not cost the local build anything.

Two properties, both easy to break by moving one import to the top of a file,
and both load-bearing:

  The deployed demo image installs base dependencies only and contains no
  Google packages at all. `pip install .` has to keep working, and this module
  has to keep importing under it.

  The 815 tests run with no credentials and no network. A module-level
  `from google.cloud import storage` would fail collection outright on a
  dev-only install.

The third check is the one that catches a real class of bug rather than a
packaging slip: the cloud implementations must satisfy the same protocols as the
local ones. Python will happily let a method be renamed on one side only, and
the failure would surface in production as an AttributeError on a code path that
no local test can reach.
"""

import pytest

from clearframe.config import ClearFrameConfig
from clearframe.storage import build_backends, build_queue
from clearframe.storage.blobs import BlobStore, LocalBlobStore
from clearframe.storage.index import LocalProductionIndex, ProductionIndex
from clearframe.storage.queue import CloudTasksJobQueue, HttpJobQueue, JobQueue


def test_the_cloud_module_imports_without_any_google_package():
    import clearframe.storage.cloud as cloud

    assert cloud.GcsBlobStore and cloud.FirestoreProductionIndex


def test_the_gcs_store_satisfies_the_same_protocol_as_the_local_one():
    from clearframe.storage.cloud import GcsBlobStore

    assert isinstance(GcsBlobStore("a-bucket"), BlobStore)


def test_the_firestore_index_satisfies_the_same_protocol_as_the_local_one():
    from clearframe.storage.cloud import FirestoreProductionIndex

    assert isinstance(FirestoreProductionIndex("a-project"), ProductionIndex)


def test_constructing_a_cloud_backend_makes_no_network_call():
    """Clients are built lazily, so importing and wiring cost nothing. Without
    this the API container would resolve credentials at startup and fail to
    boot anywhere they are absent."""
    from clearframe.storage.cloud import FirestoreProductionIndex, GcsBlobStore

    GcsBlobStore("a-bucket")
    FirestoreProductionIndex("a-project")


@pytest.mark.parametrize("cls", [HttpJobQueue, CloudTasksJobQueue])
def test_every_queue_satisfies_the_queue_protocol(cls):
    made = (
        cls("http://worker") if cls is HttpJobQueue
        else cls("projects/p/locations/l/queues/q", "http://worker", "sa@p.iam")
    )
    assert isinstance(made, JobQueue)


# --- the default has to stay local --------------------------------------------


def test_an_empty_environment_selects_the_local_backends(tmp_path):
    """`CLEARFRAME_PROFILE` unset means local, which is what keeps every
    existing command, the suite and the smoke script behaving as before."""
    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)

    assert isinstance(backends.blobs, LocalBlobStore)
    assert isinstance(backends.index, LocalProductionIndex)


def test_the_cloud_profile_refuses_to_start_without_a_bucket(tmp_path):
    """Failing at startup beats writing a run's state into a directory that
    disappears with the instance."""
    cfg = ClearFrameConfig.from_env({"CLEARFRAME_PROFILE": "cloud"})

    with pytest.raises(ValueError, match="CLEARFRAME_BUCKET"):
        build_backends(cfg, tmp_path)


def test_a_worker_url_alone_gives_the_two_container_topology(tmp_path):
    """No queue needed to run both containers on a laptop — the arrangement
    that makes the cross-process machinery debuggable without GCP."""
    cfg = ClearFrameConfig.from_env({"CLEARFRAME_WORKER_URL": "http://127.0.0.1:8001"})

    assert isinstance(build_queue(cfg, lambda job: None), HttpJobQueue)


def test_a_queue_and_a_worker_url_together_give_cloud_tasks(tmp_path):
    cfg = ClearFrameConfig.from_env({
        "CLEARFRAME_WORKER_URL": "http://worker",
        "CLEARFRAME_TASKS_QUEUE": "projects/p/locations/l/queues/q",
    })

    assert isinstance(build_queue(cfg, lambda job: None), CloudTasksJobQueue)
