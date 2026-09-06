"""How an analysis gets scheduled, and how many may run at once.

An analysis is the expensive thing this product does: three concurrent Gemini
video passes, Parallel research across every finding that needs it, and up to
150 grounding calls. Until now nothing counted them. `create_production` called
`asyncio.create_task` and returned, so the number of simultaneous analyses was
however many people happened to upload — and the deployed Cloud Run settings
(`--max-instances=2 --concurrency=80`) would have admitted 160.

So the cap is a queue rather than a rejection. The sixth upload is not an error;
it is a job that has not started yet.

Three implementations, one protocol, in the shape the integration clients
already use:

  - `InProcessJobQueue` — a semaphore and a backlog. What a laptop and the test
    suite run, and therefore what the 5-at-a-time behaviour is actually tested
    against.
  - `HttpJobQueue` — posts to a worker over plain HTTP. This is the one that
    makes the whole two-container topology runnable on a laptop with no GCP
    account at all, which is the difference between debugging the design and
    debugging a deployment.
  - `CloudTasksJobQueue` — hands the job to Cloud Tasks, whose
    `max_concurrent_dispatches` is the real cap in production.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

log = logging.getLogger("clearframe.queue")

# Five concurrent analyses. Chosen as a spend ceiling rather than a throughput
# target, and it is the number Cloud Tasks is configured with too, so the local
# and deployed behaviour agree.
DEFAULT_LIMIT = 5

# How long Cloud Tasks will hold the ack connection open for one analysis.
#
# This has to be SET. Left unset, an HTTP task gets Cloud Tasks' default of
# **600 seconds** — while the worker is deployed `--timeout=1800` on the belief
# that a task is held for thirty minutes. 1800s is the maximum a deadline may be
# raised to, not what you get for free, and the two numbers were never made to
# agree.
#
# The failure is expensive rather than loud: at 600s the connection is severed,
# Cloud Tasks calls the attempt failed and redelivers, and Cloud Run does not
# cancel the handler that is already running. So the first attempt keeps burning
# Gemini and Parallel calls while a second one starts on another instance. A
# measured deployed run was 538s — under the real limit by about a minute, which
# is why this has never been seen and would have shown up on the next longer
# clip.
#
# 1800s is both the queue's maximum and the worker's request timeout, so the
# task can never outlive the service it is waiting for.
DISPATCH_DEADLINE_S = 1800


class AnalysisJob(BaseModel):
    """Everything a worker needs to run one analysis.

    Deliberately just identifiers. The worker loads the production from the
    store rather than being handed it, so a retried task picks up whatever
    progress the previous attempt persisted instead of restarting from a
    snapshot taken when the job was created.
    """

    production_id: str
    # The uploader. Carried because the worker needs their rights ledger and
    # cannot ask the browser — by then there is no request to ask.
    owner_uid: str | None = None


Runner = Callable[[AnalysisJob], Awaitable[None]]


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, job: AnalysisJob) -> str:
        """Accept a job for execution. Must return without running it."""


class InProcessJobQueue:
    """A semaphore and a backlog, on this process's event loop.

    Not a stub. This is what runs on a laptop and in the tests, so the cap that
    ships is the cap that was measured.
    """

    def __init__(self, runner: Runner, limit: int = DEFAULT_LIMIT):
        self._runner = runner
        self._limit = limit
        self._gate = asyncio.Semaphore(limit)
        self._tasks: set[asyncio.Task] = set()
        self._waiting = 0

    async def enqueue(self, job: AnalysisJob) -> str:
        task = asyncio.create_task(self._run(job))
        # Hold a reference: a bare create_task is only kept alive by the loop,
        # and the garbage collector is entitled to take a task nobody holds.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._waiting += 1
        return job.production_id

    async def _run(self, job: AnalysisJob) -> None:
        async with self._gate:
            self._waiting -= 1
            try:
                await self._runner(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed analysis must free its slot. Without this, one
                # exception permanently reduces how many can ever run again.
                log.exception("analysis failed for %s", job.production_id)

    def pending(self) -> int:
        """Jobs accepted but not yet started."""
        return max(0, self._waiting)

    def running(self) -> int:
        return self._limit - self._gate._value  # noqa: SLF001 - no public accessor

    async def drain(self) -> None:
        """Wait for everything currently queued. Tests and shutdown only."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)


class HttpJobQueue:
    """Post the job straight at a worker over plain HTTP.

    The fixture twin of `CloudTasksJobQueue`, and the reason the whole
    two-container design is debuggable without a GCP account: point
    `CLEARFRAME_WORKER_URL` at a worker on another port and the API enqueues,
    the worker runs, the event log crosses between them and the lease decides
    what "running" means — all the machinery that is hard to get right, none of
    the infrastructure that is slow to provision.

    The request is deliberately **not awaited**. The worker runs the pipeline
    inside the request and takes minutes; in production Cloud Tasks is the one
    holding that connection open, and here nobody is. Fire it and let it run.
    """

    def __init__(self, worker_url: str, timeout_s: float = 1800.0):
        self._url = worker_url.rstrip("/") + "/internal/run"
        self._timeout_s = timeout_s
        self._tasks: set[asyncio.Task] = set()

    async def enqueue(self, job: AnalysisJob) -> str:
        task = asyncio.create_task(self._post(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.production_id

    async def _post(self, job: AnalysisJob) -> None:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(self._url, json=job.model_dump())
                if resp.status_code >= 400:
                    log.error(
                        "worker refused %s: %s %s",
                        job.production_id, resp.status_code, resp.text[:200],
                    )
        except Exception:
            log.exception("could not reach the worker for %s", job.production_id)


class CloudTasksJobQueue:
    """Hand the job to Cloud Tasks, which is where the real cap lives.

    `max_concurrent_dispatches` on the queue is what actually holds job six back
    while five run — not this class, which only creates the task and returns.
    The worker is deployed `--no-allow-unauthenticated`, so the task carries an
    OIDC token minted for a service account holding `run.invoker` on it.

    The SDK import is inside the method for the same reason every other Google
    import in this repo is: the base image installs no Google packages, and the
    credential-free test suite must be able to import this module.
    """

    def __init__(self, queue_path: str, worker_url: str, service_account: str | None):
        self._queue = queue_path
        self._url = worker_url.rstrip("/") + "/internal/run"
        self._sa = service_account

    async def enqueue(self, job: AnalysisJob) -> str:
        return await asyncio.to_thread(self._create, job)

    def _create(self, job: AnalysisJob) -> str:
        import json
        from datetime import timedelta

        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        request: dict = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": self._url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(job.model_dump()).encode(),
            },
            # The task's own name makes the enqueue idempotent: a double-submit
            # of the same production collides rather than paying twice.
            "name": f"{self._queue}/tasks/{job.production_id}",
            # A `timedelta` rather than a `duration_pb2.Duration`: proto-plus
            # marshals it, and this way nothing here needs `google.protobuf`,
            # which the credential-free base install does not have.
            "dispatch_deadline": timedelta(seconds=DISPATCH_DEADLINE_S),
        }
        if self._sa:
            request["http_request"]["oidc_token"] = {
                "service_account_email": self._sa,
                "audience": self._url.rsplit("/internal/run", 1)[0],
            }
        created = client.create_task(parent=self._queue, task=request)
        return created.name
