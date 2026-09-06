"""Progress that survives leaving the process that produced it."""

import json

import pytest

from clearframe.events import EventLog
from clearframe.storage.blobs import LocalBlobStore


@pytest.fixture
def blobs(tmp_path):
    return LocalBlobStore(tmp_path / "blobs")


def test_a_reader_in_another_process_sees_what_was_written(blobs):
    """The whole point: the API container reads what the worker wrote."""
    EventLog(blobs, "p1").append({"type": "stage_start", "stage": "scan"})

    assert EventLog.read(blobs, "p1") == [{"type": "stage_start", "stage": "scan"}]


def test_events_keep_their_order(blobs):
    log = EventLog(blobs, "p1")
    for stage in ("script", "scan", "triage"):
        log.append({"type": "stage_complete", "stage": stage})

    assert [e["stage"] for e in EventLog.read(blobs, "p1")] == ["script", "scan", "triage"]


def test_the_whole_payload_survives(blobs):
    """`preview_ready` carries the entire findings list — it is what unlocks
    "See findings now" — so this cannot be reduced to stage names."""
    payload = {
        "type": "preview_ready",
        "count": 2,
        "findings": [{"element_id": "e1", "label": "Nike", "band": "HIGH"}],
    }
    EventLog(blobs, "p1").append(payload)

    assert EventLog.read(blobs, "p1")[0]["findings"][0]["label"] == "Nike"


def test_reading_a_run_that_never_started_is_empty_not_an_error(blobs):
    assert EventLog.read(blobs, "nope") == []


def test_reading_is_repeatable_and_non_destructive(blobs):
    """The old queue was single-consumer: `get()` removed the item, so two tabs
    on one run split the events between them. Reading twice must give the same
    answer."""
    EventLog(blobs, "p1").append({"type": "stage_start", "stage": "scan"})

    assert EventLog.read(blobs, "p1") == EventLog.read(blobs, "p1")
    assert len(EventLog.read(blobs, "p1")) == 1


def test_the_log_outlives_the_run(blobs):
    """`event_queues.pop` deleted the queue on run_complete and the endpoint
    404s without it, so reconnecting a second late got nothing, for ever."""
    log = EventLog(blobs, "p1")
    log.append({"type": "stage_complete", "stage": "court"})
    log.append({"type": "run_complete"})

    assert len(EventLog.read(blobs, "p1")) == 2


def test_writes_are_coalesced_between_the_events_that_matter(blobs, monkeypatch):
    """`ctx.emit` is synchronous and there are forty emit sites, several inside
    the gather that runs three video scans at once. A blob write on every one
    would stall the work it is reporting on."""
    writes = []
    real_put = blobs.put
    monkeypatch.setattr(
        blobs, "put", lambda k, d: (writes.append(k), real_put(k, d))[1]
    )
    log = EventLog(blobs, "p1", flush_every_s=60.0)

    for i in range(10):
        log.append({"type": "scan_found", "n": i})

    assert len(writes) == 1, f"{len(writes)} blob writes for 10 chatty events"


def test_the_events_the_ui_waits_on_are_never_delayed(blobs, monkeypatch):
    """A coalesced `run_complete` would leave the reviewer looking at a spinner
    for up to the flush interval after the analysis had actually finished."""
    writes = []
    real_put = blobs.put
    monkeypatch.setattr(
        blobs, "put", lambda k, d: (writes.append(k), real_put(k, d))[1]
    )
    log = EventLog(blobs, "p1", flush_every_s=60.0)

    log.append({"type": "scan_found", "n": 1})
    before = len(writes)
    log.append({"type": "run_complete"})

    assert len(writes) == before + 1
    assert EventLog.read(blobs, "p1")[-1]["type"] == "run_complete"


def test_coalesced_events_are_not_lost(blobs):
    """Buffered is not dropped — the flush must carry everything since the last
    one, not just the event that triggered it."""
    log = EventLog(blobs, "p1", flush_every_s=60.0)

    for i in range(5):
        log.append({"type": "scan_found", "n": i})
    log.append({"type": "run_complete"})

    assert len(EventLog.read(blobs, "p1")) == 6


def test_a_failed_write_does_not_kill_the_run(blobs, monkeypatch):
    """Progress reporting is cosmetic; the analysis is not. An event log that
    raises would take down a run that was otherwise fine."""
    def boom(key, data):
        raise OSError("disk full")

    monkeypatch.setattr(blobs, "put", boom)

    EventLog(blobs, "p1").append({"type": "stage_start", "stage": "scan"})


def test_a_corrupt_log_reads_as_empty_rather_than_raising(blobs):
    blobs.put("events/p1.json", b"{not json")

    assert EventLog.read(blobs, "p1") == []


def test_existence_distinguishes_no_run_from_an_empty_one(blobs):
    """The SSE endpoint 404s for a production with no run, which is what
    `test_events_without_run_404` asserts today."""
    assert not EventLog.exists(blobs, "p1")

    EventLog(blobs, "p1").append({"type": "stage_start", "stage": "script"})

    assert EventLog.exists(blobs, "p1")


def test_a_rerun_can_clear_the_previous_log(blobs):
    """Re-running the demo replays it from scratch; the old events must not be
    prepended to the new run."""
    EventLog(blobs, "demo").append({"type": "run_complete"})

    EventLog.clear(blobs, "demo")

    assert EventLog.read(blobs, "demo") == []


def test_the_log_is_plain_json_anyone_can_read(blobs):
    """Deliberately not pickled or framed: a human debugging a stuck run should
    be able to cat the file."""
    EventLog(blobs, "p1").append({"type": "stage_start", "stage": "scan"})

    assert json.loads(blobs.get("events/p1.json"))[0]["stage"] == "scan"
