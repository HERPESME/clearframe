"""What the API does while it is waiting on the network.

The interface service is deployed `--cpu=1 --concurrency=80` under a bare
`uvicorn.run` — one process, one event loop, no workers. So every synchronous
network call made from a coroutine stops the whole service for its duration, and
the service in question is the one drawing the review screen.

`CLAUDE.md` already records this exact failure for `ground_frame`: "Grounding
froze the whole server for the length of every call ... That was most of 'I pause
and no box ever appears': the request was made and the server was blocked on the
one before." It came back in three new places once the storage moved into a
bucket, because a blob read *looks* like a file read and is a round trip.

The measurement rule from that episode holds here and is the point of these
tests: **count ticks DURING the call**. Waiting for the ticker to finish passes
against the blocking implementation, which is how the first version of that test
passed against the bug it was written for.
"""

import asyncio
import time

import pytest

from clearframe.config import ClearFrameConfig
from clearframe.storage import build_backends

pytestmark = pytest.mark.asyncio


class _SlowBlobs:
    """A blob store with a round trip in it, like the real one."""

    def __init__(self, inner, delay: float = 0.15):
        self._inner = inner
        self._delay = delay
        self.reads = 0

    def get(self, key: str) -> bytes:
        self.reads += 1
        time.sleep(self._delay)
        return self._inner.get(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _ticks_during(coro, settle: float = 0.02) -> tuple[int, object]:
    """How many times the loop got a turn while `coro` was awaited."""
    ticks = 0
    stop = False

    async def ticker():
        nonlocal ticks
        while not stop:
            await asyncio.sleep(0.005)
            ticks += 1

    counting = asyncio.create_task(ticker())
    await asyncio.sleep(settle)
    before = ticks
    result = await coro
    during = ticks - before
    stop = True
    await counting
    return during, result


async def test_reading_the_event_log_does_not_freeze_the_api(tmp_path):
    """The stream polls this four times a second for the length of a run.

    `EventLog.read` is `blobs.get` — `download_as_bytes()` against GCS in the
    cloud profile, fully synchronous. Called from inside the SSE generator's
    loop at `SSE_POLL_S = 0.25`, a ten-minute run makes ~2,400 of them, and each
    one holds the only event loop the API has. Nothing else the service does —
    listing productions, serving media, answering a grounding request — gets a
    turn in between.
    """
    from clearframe.events import EventLog

    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)
    log = EventLog(backends.blobs, "p1")
    log.append({"type": "stage_complete", "stage": "scan"})
    log.flush()

    slow = _SlowBlobs(backends.blobs, delay=0.15)
    during, events = await _ticks_during(EventLog.read_async(slow, "p1"))

    assert events and events[0]["stage"] == "scan"
    assert during >= 5, (
        f"the loop got {during} turns during a 150ms read; the API answers "
        "nothing at all while the event stream is talking to the bucket"
    )


async def test_verifying_a_token_does_not_freeze_the_api(monkeypatch):
    """Every authenticated request pays this, and it is network plus RSA.

    `firebase_admin.auth.verify_id_token` fetches Google's signing certificates
    when its cache is cold and verifies a signature. It ran synchronously inside
    an `async def` middleware, on every single request — so the gate that was
    added to protect the expensive endpoints became a serialiser in front of all
    of them.
    """
    from clearframe.webapp import auth

    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")

    def blocking_verify(token: str):
        time.sleep(0.15)
        return {"uid": "u1", "email": "a@b.c", "email_verified": True}

    monkeypatch.setattr(auth, "verify_token", blocking_verify)

    during, user = await _ticks_during(auth.user_from_token_async("a-token"))

    assert user is not None and user.uid == "u1"
    assert during >= 5, (
        f"the loop got {during} turns during a 150ms verification; one slow "
        "certificate fetch stalls every other request in flight"
    )


async def test_the_stream_checks_the_index_off_the_loop(tmp_path):
    """The keepalive path asks the index whether the run is still going.

    Once every fifteen seconds, per open stream, and in the cloud that is a
    Firestore round trip. Small on its own; it is on the same loop as everything
    else, and it is inside the branch that runs when a stage has gone quiet —
    which is exactly when the reviewer is most likely to be clicking around.
    """
    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)

    class _SlowIndex:
        def __init__(self, inner):
            self._inner = inner

        def get(self, pid):
            time.sleep(0.15)
            return self._inner.get(pid)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    from clearframe.webapp.server import index_get_async

    during, _ = await _ticks_during(
        index_get_async(_SlowIndex(backends.index), "p1")
    )

    assert during >= 5, (
        f"the loop got {during} turns during a 150ms index read"
    )
