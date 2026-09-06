"""The heavy container: one analysis per request, and nothing else.

Separate from the API service for two reasons, one of them a correctness bug
rather than a matter of taste.

**Cloud Run throttles CPU to near-zero once a response is sent.** The API used
to accept an upload, call `asyncio.create_task`, and return — which works
perfectly on a laptop and freezes mid-pipeline on Cloud Run. It has never been
seen to fail in production only because the deployed service runs in demo mode
and refuses uploads outright. Doing the work *inside* a request is the only
shape where Cloud Run guarantees CPU for its whole duration without paying for
always-on instances.

**And an analysis should not compete with the interface.** Three concurrent
Gemini video passes, Parallel research, up to 150 grounding calls: on one
service that traffic shares an event loop and a memory limit with the requests
that draw the review screen.

So: `--concurrency=1 --max-instances=5` on this service, `max_concurrent_dispatches=5`
on the queue in front of it, and the number of analyses that can run at once is
exactly five, because "in flight" is literally "an open HTTP request".
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from clearframe.config import ClearFrameConfig
from clearframe.runner import run_analysis
from clearframe.storage import AnalysisJob, build_backends
from clearframe.store import LocalJsonStore
from clearframe.worker import oidc

log = logging.getLogger("clearframe.worker")

# A local guard, not the real cap. In Cloud Run each instance takes one request
# and the queue holds the rest, so this never binds there. It binds when the
# whole topology is running on a laptop against a single worker process, which
# is the arrangement most likely to be pointed at real API keys by accident.
DEFAULT_MAX_CONCURRENT = 5


def create_worker_app(out_root: Path, max_concurrent: int = DEFAULT_MAX_CONCURRENT):
    out_root = Path(out_root)
    app = FastAPI(title="ClearFrame Worker")
    store = LocalJsonStore(out_root / "state")
    cfg = ClearFrameConfig.from_env(os.environ)
    backends = build_backends(cfg, out_root)
    gate = asyncio.Semaphore(max_concurrent)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "profile": cfg.profile, "mode": cfg.mode}

    @app.post("/internal/run")
    async def run(job: AnalysisJob, request: Request):
        """Run one analysis to completion, then answer.

        The response is the ack. Cloud Tasks holds the connection for up to its
        dispatch deadline and retries on a 5xx, so what this returns decides
        whether the job comes back.
        """
        audience = os.environ.get("CLEARFRAME_WORKER_AUDIENCE", "").strip()
        if audience:
            token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
            if not oidc.verify(token, audience, os.environ.get("CLEARFRAME_TASKS_SA")):
                raise HTTPException(status_code=401, detail="Unverified caller.")

        async with gate:
            outcome = await run_analysis(job, cfg, out_root, backends, store)

        # 200 for every one of these, including the no-ops. A retried task that
        # finds the work already done must STOP, not come back three more times
        # — the whole point of acking a duplicate is that a live run costs real
        # money and Cloud Tasks delivers at least once.
        return JSONResponse({"production_id": job.production_id, "outcome": outcome})

    return app
