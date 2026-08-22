"""Clearance review web app: API over production state with server-side role gating."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearframe.dossier import pending_ids
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.review import (
    RoleNotPermittedError,
    UnknownElementError,
    generate_dossier_async,
    record_decision,
    record_watch_alert,
    refresh_freshness,
)
from clearframe.stages.dossier import ReviewPendingError
from clearframe.store import LocalJsonStore

ARTIFACT_WHITELIST = (
    "dossier.html",
    "dossier.json",
    "markers.edl",
    "markers.csv",
    "cue_sheet.csv",
)

def _find_dist_dir() -> Path | None:
    """Locate the built SPA: env override, container/cwd layout, or repo layout."""
    import os

    candidates = []
    if os.environ.get("CLEARFRAME_DIST_DIR"):
        candidates.append(Path(os.environ["CLEARFRAME_DIST_DIR"]))
    candidates.append(Path.cwd() / "webapp" / "dist")
    candidates.append(Path(__file__).resolve().parents[3] / "webapp" / "dist")
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


DIST_DIR = _find_dist_dir()


class DecisionRequest(BaseModel):
    element_id: str
    action: Literal["approve_risk", "license", "blur", "reshoot", "escalate"]
    note: str = ""


class DemoRunRequest(BaseModel):
    pace_s: float = 0.0


class MonitorAlertRequest(BaseModel):
    monitor_id: str
    summary: str
    source_url: str = ""


class _PacedStage:
    """Wraps a stage with presentation pacing so fixture-speed demo runs are
    watchable in Mission Control. Pacing only — the work is the real pipeline."""

    def __init__(self, stage, pace_s: float):
        self._stage = stage
        self.name = stage.name
        self._pace_s = pace_s

    async def run(self, ctx) -> None:
        await asyncio.sleep(self._pace_s)
        await self._stage.run(ctx)
        await asyncio.sleep(self._pace_s)


def create_app(out_root: Path) -> FastAPI:
    out_root = Path(out_root)
    store = LocalJsonStore(out_root / "state")
    app = FastAPI(title="ClearFrame Review")
    # Serializes every load-modify-save of production state; without it,
    # concurrent decision posts (threadpool) and dossier generation could
    # silently clobber each other's saves.
    state_lock = asyncio.Lock()
    event_queues: dict[str, asyncio.Queue] = {}

    def _load(pid: str):
        try:
            return store.load(pid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")

    @app.get("/api/meta")
    def meta():
        import os

        import clearframe

        return {
            "mode": "live" if os.environ.get("CLEARFRAME_MODE") == "live" else "demo",
            "version": clearframe.__version__,
        }

    @app.get("/api/productions")
    def list_productions():
        out = []
        for path in sorted(store.root.glob("*.json")):
            state = store.load(path.stem)
            out.append(
                {
                    "id": state.production.id,
                    "title": state.production.title,
                    "stage_status": state.stage_status,
                }
            )
        return out

    async def _run_paced_demo(pace_s: float) -> None:
        queue = event_queues["demo"]
        ctx = demo_context(out_root)
        ctx.store = store
        ctx.listener = queue.put_nowait
        stages = [_PacedStage(s, pace_s) for s in build_demo_pipeline()]
        try:
            await Pipeline(stages).run(ctx)
        finally:
            queue.put_nowait({"type": "run_complete"})

    @app.post("/api/productions/demo")
    async def create_demo(body: DemoRunRequest | None = None):
        pace_s = body.pace_s if body else 0.0
        if pace_s > 0:
            # Mission Control mode: fresh paced run in the background, events
            # streamed over /events. Restarts the demo production from scratch.
            state_path = store.root / "demo.json"
            if state_path.exists():
                state_path.unlink()
            event_queues["demo"] = asyncio.Queue()
            asyncio.create_task(_run_paced_demo(pace_s))
            return {"status": "running"}
        try:
            state = store.load("demo")
        except FileNotFoundError:
            ctx = demo_context(out_root)
            ctx.store = store
            state = await Pipeline(build_demo_pipeline()).run(ctx)
        return JSONResponse(state.model_dump(mode="json"))

    @app.get("/api/productions/{pid}/events")
    async def stream_events(pid: str):
        queue = event_queues.get(pid)
        if queue is None:
            raise HTTPException(status_code=404, detail="No active run for this production")

        async def gen():
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "run_complete":
                    event_queues.pop(pid, None)
                    break

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/productions/{pid}")
    def get_production(pid: str):
        return JSONResponse(_load(pid).model_dump(mode="json"))

    @app.post("/api/productions/{pid}/decisions")
    async def post_decision(
        pid: str,
        body: DecisionRequest,
        x_clearframe_role: str = Header(default="editor"),
    ):
        async with state_lock:
            try:
                state = record_decision(
                    store,
                    pid,
                    body.element_id,
                    body.action,
                    body.note,
                    role=x_clearframe_role,
                    reviewer=x_clearframe_role.lower(),
                    at=datetime.now(timezone.utc).isoformat(),
                )
            except RoleNotPermittedError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except UnknownElementError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")
            return {"ok": True, "pending": pending_ids(state)}

    @app.post("/api/productions/{pid}/freshness")
    async def check_freshness(pid: str):
        """Live Parallel Search pass over every identified rights holder.

        Deep research is a snapshot from pipeline time; this is the real-time
        check a reviewer runs before signing off. Priced per request, so it is
        affordable to call on demand from the review screen.
        """
        async with state_lock:
            try:
                state, checked = await refresh_freshness(
                    store, out_root, pid, at=datetime.now(timezone.utc).isoformat()
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")
        material = sum(
            1 for sigs in state.freshness.values() for s in sigs if s.material
        )
        return {
            "checked": checked,
            "holders": len(state.freshness),
            "material_signals": material,
        }

    @app.post("/api/productions/{pid}/dossier")
    async def generate_dossier(pid: str):
        async with state_lock:
            try:
                await generate_dossier_async(
                    store, out_root, pid, at=datetime.now(timezone.utc).isoformat()
                )
            except ReviewPendingError:
                raise HTTPException(
                    status_code=409, detail={"pending": pending_ids(_load(pid))}
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")
        artifacts = [n for n in ARTIFACT_WHITELIST if (out_root / n).exists()]
        return {"artifacts": artifacts}

    @app.post("/api/webhooks/parallel-monitor")
    async def monitor_webhook(body: MonitorAlertRequest):
        # Parallel Monitor webhook: an outside-world change on a watched finding
        # reopens review so the dossier can't go silently stale.
        async with state_lock:
            for path in sorted(store.root.glob("*.json")):
                reopened = record_watch_alert(
                    store,
                    path.stem,
                    body.monitor_id,
                    body.summary,
                    body.source_url,
                    at=datetime.now(timezone.utc).isoformat(),
                )
                if reopened is not None:
                    return {"reopened_element": reopened, "production_id": path.stem}
        raise HTTPException(status_code=404, detail=f"No watch for monitor {body.monitor_id}")

    @app.get("/api/productions/{pid}/artifacts/{name}")
    def get_artifact(pid: str, name: str):
        _load(pid)
        if name not in ARTIFACT_WHITELIST or not (out_root / name).exists():
            raise HTTPException(status_code=404, detail="Unknown artifact")
        media = "text/html" if name.endswith(".html") else "text/plain"
        return FileResponse(out_root / name, media_type=media)

    if DIST_DIR is not None:
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")
    else:

        @app.get("/")
        def index():
            return {
                "app": "ClearFrame Review API",
                "ui": "webapp/dist not built — run `npm run build` in webapp/",
                "api": "/docs",
            }

    return app
