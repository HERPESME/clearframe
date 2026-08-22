"""Clearance review web app: API over production state with server-side role gating."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearframe.config import ClearFrameConfig, validate_live
from clearframe.dossier import pending_ids
from clearframe.licensing import assign_ids, parse_licence_csv, parse_licence_json
from clearframe.media import probe_duration_s
from clearframe.models import Production
from clearframe.pipeline import (
    ANALYSIS_STAGES,
    Pipeline,
    build_context,
    build_demo_pipeline,
    demo_context,
)
from clearframe.review import (
    RoleNotPermittedError,
    UnknownElementError,
    generate_dossier_async,
    record_decision,
    record_watch_alert,
    refresh_freshness,
)
from clearframe.stages.dossier import ReviewPendingError
from clearframe.store import LicenceStore, LocalJsonStore

# Browsers must be able to <video> it; keep the accepted set narrow.
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
MAX_UPLOAD_BYTES = 512 * 1024 * 1024

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
    """Demo run options.

    The three declarations exist so a UI tester can reach every surface without
    credentials. Left unset the demo behaves exactly as it always has — an
    expressive work, no sponsors, no publishing platform — which is also the
    combination that leaves the sponsor and platform panels empty.
    """

    pace_s: float = 0.0
    use_context: str | None = None
    sponsors: list[str] | None = None
    platform: str | None = None

    @property
    def declares_anything(self) -> bool:
        return any(
            v is not None for v in (self.use_context, self.sponsors, self.platform)
        )


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


def _use_context(raw: str):
    """Parse a declared use context, defaulting to the calibration baseline.

    EXPRESSIVE is what every score was calibrated against, so an unrecognised
    or missing value must land there — never on a harsher band the uploader
    did not ask for.
    """
    from clearframe.models import UseContext

    try:
        return UseContext((raw or "").strip().upper())
    except ValueError:
        return UseContext.EXPRESSIVE


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
        """Newest first, each flagged with whether its run is still going.

        The client restores the first row on load. When this returned store
        order, "demo" sorted ahead of a user's upload — so refreshing the page
        mid-analysis appeared to lose the production entirely. It was never
        lost: the pipeline runs server-side and every stage persists. The
        client was simply handed the wrong one.
        """
        out = []
        for pid in store.production_ids():
            state = store.load(pid)
            path = store.root / f"{pid}.json"
            done = all(
                state.stage_status.get(stage) == "complete"
                for stage in ANALYSIS_STAGES
            )
            out.append(
                {
                    "id": state.production.id,
                    "title": state.production.title,
                    "stage_status": state.stage_status,
                    "updated_at": path.stat().st_mtime if path.exists() else 0.0,
                    "running": not done,
                }
            )
        return sorted(out, key=lambda r: r["updated_at"], reverse=True)

    async def _run_paced_demo(pace_s: float, declared: dict | None = None) -> None:
        queue = event_queues["demo"]
        ctx = demo_context(out_root)
        if declared:
            ctx.state.production = ctx.state.production.model_copy(update=declared)
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

        def _apply(ctx):
            if body is None:
                return ctx
            update = {}
            if body.use_context is not None:
                update["use_context"] = _use_context(body.use_context)
            if body.sponsors is not None:
                update["sponsors"] = body.sponsors
            if body.platform is not None:
                update["platform"] = body.platform.strip().lower()
            if update:
                ctx.state.production = ctx.state.production.model_copy(update=update)
            return ctx
        if pace_s > 0:
            # Mission Control mode: fresh paced run in the background, events
            # streamed over /events. Restarts the demo production from scratch.
            state_path = store.root / "demo.json"
            if state_path.exists():
                state_path.unlink()
            event_queues["demo"] = asyncio.Queue()
            declared: dict = {}
            if body is not None:
                if body.use_context is not None:
                    declared["use_context"] = _use_context(body.use_context)
                if body.sponsors is not None:
                    declared["sponsors"] = body.sponsors
                if body.platform is not None:
                    declared["platform"] = body.platform.strip().lower()
            asyncio.create_task(_run_paced_demo(pace_s, declared))
            return {"status": "running"}
        # A cached run cannot answer a different question, so declaring
        # anything forces a fresh one rather than silently returning the
        # previous configuration's numbers.
        if body is not None and body.declares_anything:
            state_path = store.root / "demo.json"
            if state_path.exists():
                state_path.unlink()

        try:
            state = store.load("demo")
        except FileNotFoundError:
            ctx = _apply(demo_context(out_root))
            ctx.store = store
            state = await Pipeline(build_demo_pipeline()).run(ctx)
        return JSONResponse(state.model_dump(mode="json"))

    def _safe_media_name(filename: str) -> str:
        """Never trust an upload's filename: keep the extension, drop the path."""
        suffix = Path(filename or "").suffix.lower()
        if suffix not in MEDIA_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported footage type '{suffix}'. Use one of: "
                + ", ".join(sorted(MEDIA_TYPES)),
            )
        return f"footage{suffix}"

    @app.post("/api/productions")
    async def create_production(
        file: UploadFile = File(...),
        title: str = Form("Untitled Production"),
        production_id: str = Form("upload"),
        duration_s: float = Form(0.0),
        fps: float = Form(24.0),
        territories: str = Form("US"),
        distribution: str = Form("THEATRICAL,STREAMING"),
        use_context: str = Form("EXPRESSIVE"),
        sponsors: str = Form(""),
        platform: str = Form("none"),
    ):
        """Upload footage and run the clearance pipeline over it.

        Demo mode deliberately refuses: it replays recorded fixtures, so it
        would return Golden Hour's findings for your clip. Saying so is better
        than quietly showing someone else's results as their own.
        """
        cfg = ClearFrameConfig.from_env(os.environ)
        if cfg.mode != "live":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This deployment is in demo mode, which replays recorded fixtures "
                    "and cannot analyse new footage. Set CLEARFRAME_MODE=live with "
                    "GOOGLE_CLOUD_PROJECT and PARALLEL_API_KEY to scan your own clip."
                ),
            )
        missing = validate_live(cfg.model_copy(update={"mode": "live"}))
        if missing:
            raise HTTPException(
                status_code=503,
                detail="Live mode is not configured. Missing: " + ", ".join(missing),
            )

        pid = "".join(c for c in production_id if c.isalnum() or c in "-_") or "upload"
        name = _safe_media_name(file.filename or "")
        media_dir = out_root / "media" / pid
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / name

        written = 0
        with open(target, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Footage exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
                    )
                out.write(chunk)

        production = Production(
            id=pid,
            title=title,
            footage_uri=str(target),
            fps=fps,
            # Measure it. The form defaults to 0.0 and nothing used to correct
            # that, so a 49-second clip declared itself zero seconds long and
            # got a single audio fingerprint sample at the head. A caller who
            # supplies a duration is trusted; otherwise ffmpeg decides.
            duration_s=duration_s or probe_duration_s(target),
            release_territories=[t.strip().upper() for t in territories.split(",") if t.strip()]
            or ["US"],
            distribution=[d.strip().upper() for d in distribution.split(",") if d.strip()],
            # An unrecognised value falls back to the calibration baseline rather
            # than 400-ing an upload that is otherwise fine.
            use_context=_use_context(use_context),
            sponsors=[b.strip() for b in sponsors.split(",") if b.strip()],
            platform=(platform or "none").strip().lower(),
            has_media=True,
        )
        ctx = build_context(cfg.model_copy(update={"mode": "live"}), production, out_root)
        ctx.store = store
        event_queues[pid] = asyncio.Queue()
        ctx.listener = event_queues[pid].put_nowait

        async def _run() -> None:
            try:
                await Pipeline(build_demo_pipeline()).run(ctx)
            finally:
                event_queues[pid].put_nowait({"type": "run_complete"})

        asyncio.create_task(_run())
        return {"production_id": pid, "status": "running", "media": name}

    @app.get("/api/productions/{pid}/media")
    def get_media(pid: str):
        """Serve the uploaded footage so the review UI can play it."""
        _load(pid)
        media_dir = out_root / "media" / pid
        for suffix, media_type in MEDIA_TYPES.items():
            candidate = media_dir / f"footage{suffix}"
            if candidate.exists():
                return FileResponse(candidate, media_type=media_type)
        raise HTTPException(status_code=404, detail="No footage stored for this production")

    @app.get("/api/licences")
    def list_licences():
        """The rights ledger: clearances this deployment already holds."""
        ledger = LicenceStore(out_root / "state")
        return {"licences": [lic.model_dump(mode="json") for lic in ledger.load()]}

    @app.post("/api/licences")
    async def upload_licences(
        file: UploadFile = File(...),
        replace: bool = Form(True),
        x_clearframe_role: str = Header(default="editor"),
    ):
        """Upload your own rights ledger as JSON or CSV.

        CSV columns: id, rights_holder, work, scope, territories, media,
        starts, expires, reference, notes. Territories and media are
        pipe- or semicolon-separated (e.g. "US|DE|FR").
        """
        if x_clearframe_role.lower() not in {"legal", "producer"}:
            raise HTTPException(
                status_code=403,
                detail="Only legal or producer may change the rights ledger.",
            )
        raw = (await file.read(MAX_UPLOAD_BYTES)).decode("utf-8", errors="replace")
        name = (file.filename or "").lower()
        try:
            parsed = (
                parse_licence_csv(raw) if name.endswith(".csv") else parse_licence_json(raw)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not parsed:
            raise HTTPException(status_code=400, detail="No usable licence rows found.")

        ledger = LicenceStore(out_root / "state")
        existing = [] if replace else ledger.load()
        by_id = {lic.id: lic for lic in existing}
        for lic in assign_ids(parsed, set(by_id)):
            by_id[lic.id] = lic
        merged = list(by_id.values())
        ledger.save(merged)
        return {"stored": len(merged), "added": len(parsed), "replaced": replace}

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
            for pid in store.production_ids():
                reopened = record_watch_alert(
                    store,
                    pid,
                    body.monitor_id,
                    body.summary,
                    body.source_url,
                    at=datetime.now(timezone.utc).isoformat(),
                )
                if reopened is not None:
                    return {"reopened_element": reopened, "production_id": pid}
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
