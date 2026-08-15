"""Clearance review web app: API over production state with server-side role gating."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearframe.dossier import pending_ids
from clearframe.models import Decision
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.stages.dossier import DossierStage, ReviewPendingError
from clearframe.store import LocalJsonStore

ARTIFACT_WHITELIST = (
    "dossier.html",
    "dossier.json",
    "markers.edl",
    "markers.csv",
    "cue_sheet.csv",
)

DECIDER_ROLES = {"legal", "producer"}

DIST_DIR = Path(__file__).resolve().parents[3] / "webapp" / "dist"


class DecisionRequest(BaseModel):
    element_id: str
    action: Literal["approve_risk", "license", "blur", "reshoot", "escalate"]
    note: str = ""


def create_app(out_root: Path) -> FastAPI:
    out_root = Path(out_root)
    store = LocalJsonStore(out_root / "state")
    app = FastAPI(title="ClearFrame Review")
    # Serializes every load-modify-save of production state; without it,
    # concurrent decision posts (threadpool) and dossier generation could
    # silently clobber each other's saves.
    state_lock = asyncio.Lock()

    def _load(pid: str):
        try:
            return store.load(pid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")

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

    @app.post("/api/productions/demo")
    async def create_demo():
        try:
            state = store.load("demo")
        except FileNotFoundError:
            ctx = demo_context(out_root)
            ctx.store = store
            state = await Pipeline(build_demo_pipeline()).run(ctx)
        return JSONResponse(state.model_dump(mode="json"))

    @app.get("/api/productions/{pid}")
    def get_production(pid: str):
        return JSONResponse(_load(pid).model_dump(mode="json"))

    @app.post("/api/productions/{pid}/decisions")
    async def post_decision(
        pid: str,
        body: DecisionRequest,
        x_clearframe_role: str = Header(default="editor"),
    ):
        role = x_clearframe_role.lower()
        if role not in DECIDER_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' cannot record decisions (requires legal or producer).",
            )
        async with state_lock:
            state = _load(pid)
            if not any(el.id == body.element_id for el in state.elements):
                raise HTTPException(
                    status_code=404, detail=f"Unknown element: {body.element_id}"
                )
            state.decisions[body.element_id] = Decision(
                element_id=body.element_id,
                action=body.action,
                reviewer=role,
                role=role,
                note=body.note,
            )
            store.save(state)
            return {"ok": True, "pending": pending_ids(state)}

    @app.post("/api/productions/{pid}/dossier")
    async def generate_dossier(pid: str):
        async with state_lock:
            state = _load(pid)
            ctx = demo_context(out_root)
            ctx.store = store
            ctx.state = state
            stage = DossierStage(
                out_dir=out_root, generated_at=datetime.now(timezone.utc).isoformat()
            )
            try:
                await stage.run(ctx)
            except ReviewPendingError:
                raise HTTPException(status_code=409, detail={"pending": pending_ids(state)})
            store.save(state)
        artifacts = [n for n in ARTIFACT_WHITELIST if (out_root / n).exists()]
        return {"artifacts": artifacts}

    @app.get("/api/productions/{pid}/artifacts/{name}")
    def get_artifact(pid: str, name: str):
        _load(pid)
        if name not in ARTIFACT_WHITELIST or not (out_root / name).exists():
            raise HTTPException(status_code=404, detail="Unknown artifact")
        media = "text/html" if name.endswith(".html") else "text/plain"
        return FileResponse(out_root / name, media_type=media)

    if DIST_DIR.exists():
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
