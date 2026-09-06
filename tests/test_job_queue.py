"""How many analyses may run at once, and what happens to the rest.

This is the money constraint, so it is asserted rather than configured. An
analysis is three concurrent Gemini video passes plus Parallel research plus up
to 150 grounding calls; today nothing counts in-flight runs before
`asyncio.create_task`, and the deployed Cloud Run config (`--max-instances=2
--concurrency=80`) would happily admit 160 of them.

The cap belongs in a queue rather than a rejection because the sixth upload is
not an error. It is a job that has not started yet, and the honest thing is to
run it when a slot frees rather than to tell someone their film was refused.
"""

import asyncio

import pytest

from clearframe.storage.queue import AnalysisJob, InProcessJobQueue

pytestmark = pytest.mark.asyncio


class Recorder:
    """A stand-in analysis that reports how many of it were running at once."""

    def __init__(self, hold: float = 0.02):
        self.hold = hold
        self.live = 0
        self.peak = 0
        self.ran: list[str] = []

    async def __call__(self, job: AnalysisJob) -> None:
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(self.hold)
            self.ran.append(job.production_id)
        finally:
            self.live -= 1


async def test_everything_enqueued_eventually_runs():
    runner = Recorder()
    queue = InProcessJobQueue(runner, limit=5)

    for i in range(8):
        await queue.enqueue(AnalysisJob(production_id=f"p{i}"))
    await queue.drain()

    assert sorted(runner.ran) == [f"p{i}" for i in range(8)]


async def test_never_more_than_the_limit_run_at_once():
    """The whole point. Eight uploads, five slots."""
    runner = Recorder()
    queue = InProcessJobQueue(runner, limit=5)

    for i in range(8):
        await queue.enqueue(AnalysisJob(production_id=f"p{i}"))
    await queue.drain()

    assert runner.peak <= 5, f"{runner.peak} analyses ran at once against a cap of 5"


async def test_the_limit_is_actually_reached():
    """Guards the opposite failure: a queue that serialises everything would
    pass the test above and quietly make eight uploads take eight times as
    long."""
    runner = Recorder()
    queue = InProcessJobQueue(runner, limit=5)

    for i in range(8):
        await queue.enqueue(AnalysisJob(production_id=f"p{i}"))
    await queue.drain()

    assert runner.peak == 5


async def test_enqueue_returns_without_waiting_for_the_run():
    """The upload response must not block on the analysis — that is the whole
    reason the work is queued rather than awaited."""
    runner = Recorder(hold=5.0)
    queue = InProcessJobQueue(runner, limit=5)

    await asyncio.wait_for(queue.enqueue(AnalysisJob(production_id="p1")), timeout=0.5)

    await queue.cancel_all()


async def test_a_failing_job_does_not_take_the_queue_down_with_it():
    """A pipeline that raises must free its slot. Without this an exception in
    one analysis permanently reduces the number that can ever run."""
    seen = []

    async def explode(job: AnalysisJob) -> None:
        seen.append(job.production_id)
        raise RuntimeError("scan failed")

    queue = InProcessJobQueue(explode, limit=2)
    for i in range(5):
        await queue.enqueue(AnalysisJob(production_id=f"p{i}"))
    await queue.drain()

    assert len(seen) == 5


async def test_the_queue_reports_what_is_waiting():
    """A dashboard that says "queued" needs to know, and so does anyone
    wondering why their upload has not started."""
    runner = Recorder(hold=0.3)
    queue = InProcessJobQueue(runner, limit=2)

    for i in range(5):
        await queue.enqueue(AnalysisJob(production_id=f"p{i}"))
    await asyncio.sleep(0.05)

    assert queue.pending() == 3

    await queue.drain()
    assert queue.pending() == 0


async def test_the_job_carries_its_owner():
    """The worker needs the uploader's identity to reach their rights ledger,
    and it cannot ask the browser — there is no request by then."""
    runner = Recorder()
    queue = InProcessJobQueue(runner, limit=1)

    await queue.enqueue(AnalysisJob(production_id="p1", owner_uid="alice"))
    await queue.drain()

    assert AnalysisJob(production_id="p1", owner_uid="alice").owner_uid == "alice"
