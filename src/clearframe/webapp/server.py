"""Clearance review web app: API over production state with server-side role gating."""

import asyncio
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearframe.config import ClearFrameConfig, validate_live
from clearframe.dossier import pending_ids
from clearframe.licensing import assign_ids, parse_licence_csv, parse_licence_json
from clearframe.media import extract_frame, probe_media

log = logging.getLogger("clearframe.webapp")
from clearframe.models import Production
from clearframe.overlay import bind_ground_boxes
from clearframe.webapp import auth
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
from clearframe.timeline import timing_is_reliable

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

# How many frames a single production may warm in the background. Each one is
# a model round trip on a still — about eight seconds, a fraction of a cent —
# so a feature-length upload must not try to measure every second of itself.
# Overridable because the right number depends on how long the footage is and
# how much the operator wants to spend before anyone clicks.
PREGROUND_MAX_FRAMES = int(os.environ.get("CLEARFRAME_PREGROUND_MAX", "150"))


class _ShellFiles(StaticFiles):
    """The shell revalidates; the hashed assets it points at never need to.

    Mounted as plain `StaticFiles`, index.html carried no cache policy, so
    browsers served it from their heuristic cache — still pointing at a bundle
    filename from two commits earlier. Two fixes were made, rebuilt, committed
    and verified, and none of them reached the screen; the next three
    diagnoses were of code that was no longer running.

    Exactly the `media_version` failure in a different costume: a URL whose
    bytes changed underneath a browser that had been given no reason to ask
    again. The asset filenames are content-hashed by Vite, so caching THEM
    forever is free and correct — it is only the document that names them
    which must be checked every time.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


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



def build_grounding_client(cfg):
    """The client that locates known labels on a still frame.

    Separate from `build_context` because grounding is not a pipeline stage —
    it answers an interactive question about one moment, long after the run
    finished. Demo mode gets the fixture twin, so the identical parser and the
    identical drawing code run with no credentials and no network.
    """
    if cfg.mode == "live":
        from clearframe.integrations.gemini_live import LiveGeminiClient

        # The configured model, like every other caller (see pipeline.py). This
        # used to fall through to the hard-coded default, so grounding ignored
        # CLEARFRAME_GEMINI_MODEL and paid the 404-then-fallback round trip on
        # a model the rest of the run had already given up on.
        return LiveGeminiClient(cfg.project, cfg.location, model=cfg.gemini_model)

    from pathlib import Path as _Path

    from clearframe.integrations.gemini_client import FixtureGeminiClient

    return FixtureGeminiClient(
        _Path(__file__).resolve().parents[1] / "integrations" / "fixtures"
    )


def create_app(out_root: Path) -> FastAPI:
    out_root = Path(out_root)
    store = LocalJsonStore(out_root / "state")
    app = FastAPI(title="ClearFrame Review")
    # Serializes every load-modify-save of production state; without it,
    # concurrent decision posts (threadpool) and dossier generation could
    # silently clobber each other's saves.
    state_lock = asyncio.Lock()
    event_queues: dict[str, asyncio.Queue] = {}
    # Productions with a pipeline task actually in flight in this process. A
    # restart empties it, which is the point: nothing here survives the process
    # that was doing the work, so neither should the claim that work is
    # happening.
    _live_runs: set[str] = set()

    def _load(pid: str):
        try:
            return store.load(pid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")

    # ---------------------------------------------------------------- auth --
    #
    # One middleware rather than a dependency on seventeen routes, because the
    # routes that most needed guarding were the ones nobody had remembered to
    # decorate: the upload that runs the whole live pipeline, the grounding
    # calls, the freshness search. A default-closed gate cannot be forgotten.

    @app.middleware("http")
    async def _require_session(request, call_next):
        if not auth.auth_enabled() or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if auth.is_open(request.url.path):
            return await call_next(request)
        if auth.user_from_request(request) is None:
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        return await call_next(request)

    def _current_user(request):
        return auth.user_from_request(request) if auth.auth_enabled() else None

    def _role_for(request, header_role: str) -> str:
        """The role this request may act with.

        With auth on it comes from the verified user and the header stops being
        evidence — that header was the entire bypass. With auth off it is the
        header, unchanged, because demo mode has nobody to ask.

        Open-roles mode is the third case: signed in, but free to choose. It
        exists so a visitor to the deployed demo can exercise the controls
        without waiting to be granted anything. The header is honoured there
        BECAUSE the whole point is self-selection — there is nothing to bypass.
        """
        user = _current_user(request)
        if user is None:
            return header_role
        return header_role if auth.open_roles() else user.role

    def _actor_for(request, header_role: str) -> str:
        """What the audit trail records: a person if we know one."""
        user = _current_user(request)
        return user.actor if user else header_role.lower()

    @app.get("/api/auth/config")
    def auth_config():
        """What the browser needs to start a sign-in, and whether to bother."""
        return {
            "enabled": auth.auth_enabled(),
            "open_roles": auth.open_roles(),
            "firebase": auth.firebase_web_config(),
        }

    @app.get("/api/auth/me")
    def auth_me(request: Request):
        user = _current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in.")
        return user.model_dump()

    @app.post("/api/auth/session")
    def auth_session(request: Request, body: dict):
        """Exchange a verified Firebase ID token for a cookie session."""
        if not auth.auth_enabled():
            raise HTTPException(status_code=400, detail="Authentication is not enabled.")
        raw = (body or {}).get("idToken") or ""
        try:
            user = auth.user_from_token(raw)
        except Exception:
            raise HTTPException(status_code=401, detail="Could not verify that sign-in.")
        response = JSONResponse(user.model_dump())
        response.set_cookie(
            auth.SESSION_COOKIE,
            raw,
            httponly=True,
            samesite="lax",
            # Not Secure on plain HTTP, or local development cannot sign in at
            # all; Cloud Run terminates TLS, so this is set there.
            secure=request.url.scheme == "https",
            max_age=60 * 60,  # an ID token's own lifetime; the client refreshes
            path="/",
        )
        return response

    @app.post("/api/auth/signout")
    def auth_signout():
        response = JSONResponse({"status": "signed-out"})
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.get("/api/meta")
    def meta(request: Request):
        import os

        import clearframe

        user = _current_user(request)
        return {
            "mode": "live" if os.environ.get("CLEARFRAME_MODE") == "live" else "demo",
            "version": clearframe.__version__,
            "auth": auth.auth_enabled(),
            # The client must know, because a role the visitor picked has to
            # be labelled as such rather than shown as an assignment.
            "open_roles": auth.open_roles(),
            "user": user.model_dump() if user else None,
        }

    def _stored_media(pid: str):
        """The footage file for this production, if one is on disk."""
        media_dir = out_root / "media" / pid
        for suffix, media_type in MEDIA_TYPES.items():
            candidate = media_dir / f"footage{suffix}"
            if candidate.exists():
                return candidate, media_type
        return None

    def _media_version(pid: str) -> str:
        """Which FOOTAGE this production currently holds.

        Size and write time together: whole seconds collide when two uploads
        land in the same second, which a test does routinely and an impatient
        user manages too. Every upload from the UI lands at the same production
        id, so this string is the only thing that distinguishes one film from
        the next — which is why the box cache is keyed by it and not just by
        the id.
        """
        found = _stored_media(pid)
        if not found:
            return ""
        st = found[0].stat()
        return f"{st.st_size}-{st.st_mtime_ns}"

    def _with_media_flag(state):
        """Answer `has_media` by looking for the file, not by trusting a flag.

        The review app renders its video player on this. It used to be set only
        by the upload endpoint, so a production re-scanned from the CLI came
        back False while the media endpoint served the very same bytes with a
        200 — no player, and no way for a user to work out why.
        """
        actual = _stored_media(state.production.id) is not None
        version = _media_version(state.production.id)
        if (
            state.production.has_media == actual
            and state.production.media_version == version
        ):
            return state
        return state.model_copy(
            update={
                "production": state.production.model_copy(
                    update={"has_media": actual, "media_version": version}
                )
            }
        )

    def _with_timing_verdicts(state):
        """Disown timecodes the scan cannot have measured, on read.

        `scan` marks these when it runs, but every analysis completed before
        `timeline.py` existed carries the default of "believable" — including,
        on the clip that found this, a tattoo whose six appearances totalled
        0.15 seconds. Deriving on read rather than migrating on disk means an
        old state gets the correct answer without being rewritten, and there is
        one rule in one place.
        """
        prod = state.production
        checked = []
        changed = False
        for el in state.elements:
            ok, reason = timing_is_reliable(el, prod.duration_s, prod.fps)
            if ok == el.timing_reliable and (ok or reason == el.timing_note):
                checked.append(el)
                continue
            changed = True
            checked.append(
                el.model_copy(
                    update={"timing_reliable": ok, "timing_note": "" if ok else reason}
                )
            )
        return state.model_copy(update={"elements": checked}) if changed else state

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
                    # Actually in flight IN THIS PROCESS, not merely unfinished.
                    # This was `not done`, read from the persisted state alone,
                    # so a run interrupted by a restart reported itself running
                    # for ever — and the client, which restores the newest
                    # running production on load, returned the reviewer to a
                    # dead analysis every time and never showed them the upload
                    # form. Exactly the refresh bug this endpoint was ordered to
                    # fix, one level down: last time the client was handed the
                    # wrong row, this time no row was right.
                    "running": not done and pid in _live_runs,
                    # Unfinished and nobody is working on it. Distinct from
                    # complete, because silence here would read as a finished
                    # analysis and the missing stages would never be noticed.
                    "interrupted": not done and pid not in _live_runs,
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
        _live_runs.add("demo")
        try:
            await Pipeline(stages).run(ctx)
        finally:
            _live_runs.discard("demo")
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

        # One ffmpeg call for both numbers, in a thread. It was two spawns
        # parsing the same banner, run synchronously inside an async handler —
        # so every upload stalled the whole server for the length of them.
        probed_duration, probed_fps = await asyncio.to_thread(probe_media, target)

        production = Production(
            id=pid,
            title=title,
            footage_uri=str(target),
            # Measured, for the same reason duration is. The form default of
            # 24.0 fed `timeline`'s one-frame test, so a 30fps clip was judged
            # against a 42ms frame instead of a 33ms one — a physical test
            # running on a guessed constant. A caller who supplies a rate other
            # than the default is trusted; otherwise ffmpeg decides.
            fps=(fps if fps != 24.0 else (probed_fps or 24.0)),
            # Measure it. The form defaults to 0.0 and nothing used to correct
            # that, so a 49-second clip declared itself zero seconds long and
            # got a single audio fingerprint sample at the head. A caller who
            # supplies a duration is trusted; otherwise ffmpeg decides.
            duration_s=duration_s or probed_duration,
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
        # New footage at this id. The version in each key already keeps the old
        # film's answers from being served for the new one; this drops them so
        # they do not accumulate for the life of the process, and resets the
        # progress the player is about to poll.
        for key in [k for k in _ground_cache if k[0] == pid]:
            del _ground_cache[key]
        for warmed in [k for k in _pregrounded if k[0] == pid]:
            _pregrounded.discard(warmed)
        _preground_progress.pop(pid, None)
        # The poster is keyed by media version so a stale one is never SERVED,
        # but it would sit on disk for the life of the deployment otherwise.
        for stale in target.parent.glob("thumb-*.jpg"):
            stale.unlink(missing_ok=True)

        ctx = build_context(cfg.model_copy(update={"mode": "live"}), production, out_root)
        ctx.store = store
        event_queues[pid] = asyncio.Queue()

        def _listen(event: dict) -> None:
            event_queues[pid].put_nowait(event)
            # Warm the boxes at the EARLIEST moment they are final, which is
            # triage — not when the run ends, and not when preview does.
            #
            # Triage fixes the element ids, labels, appearances and rectangles.
            # Everything after it changes what is KNOWN about a finding, never
            # where or when it is on screen. The one exception is `corroborate`
            # rewriting a label, and it does that only for MUSIC, which has no
            # rectangle and is never grounded.
            #
            # The measured shape of a run: scan ends at ~102s, preview at
            # ~167s, the whole run at ~502s, and warming a 50s clip takes
            # ~100s. Hooking preview already hid the warm-up inside research;
            # hooking triage buys another ~65s, which is what decides it on
            # longer footage, where warming can outlast the stages it is
            # hiding behind.
            if event.get("type") == "stage_complete" and event.get("stage") == "triage":
                if (pid, _media_version(pid)) not in _pregrounded:
                    try:
                        _start_preground(pid, store.load(pid))
                    except FileNotFoundError:
                        pass

        ctx.listener = _listen

        async def _run() -> None:
            try:
                await Pipeline(build_demo_pipeline()).run(ctx)
            finally:
                _live_runs.discard(pid)
                event_queues[pid].put_nowait({"type": "run_complete"})

        _live_runs.add(pid)
        asyncio.create_task(_run())
        return {"production_id": pid, "status": "running", "media": name}

    @app.get("/api/productions/{pid}/media")
    def get_media(pid: str):
        """Serve the uploaded footage so the review UI can play it."""
        _load(pid)
        found = _stored_media(pid)
        if found is None:
            raise HTTPException(
                status_code=404, detail="No footage stored for this production"
            )
        path, media_type = found
        # The URL is the same for every upload to this production, so a player
        # holding it will replay the previous clip unless told to check. The
        # ETag makes that check cheap; `media_version` on the production keeps
        # a fresh page from asking at all.
        return FileResponse(
            path, media_type=media_type, headers={"Cache-Control": "no-cache"}
        )

    def _poster_moment(state) -> float:
        """Which second of this footage represents it.

        The middle of the first finding's first appearance, because that is
        what the analysis says the footage is ABOUT — a card showing the frame
        where the trademark actually appears says more than second one, which
        on most clips is a fade from black.
        """
        for el in state.elements:
            if not getattr(el, "timing_reliable", True):
                continue
            for r in el.time_ranges:
                return round((r.start_s + r.end_s) / 2, 2)
        duration = state.production.duration_s or 0.0
        # Far enough in to be past a title card, short of the credits.
        return round(duration * 0.4, 2) if duration else 1.0

    @app.get("/api/productions/{pid}/thumbnail")
    async def get_thumbnail(pid: str):
        """A poster for this production, taken from its own footage.

        The dashboard needs a picture per production and the only honest one is
        a frame the production already contains — this is a rights-clearance
        tool, so shipping somebody else's marketing art as decoration would be
        a poor joke at its own expense.

        404 rather than a placeholder when there is nothing to extract: the
        fallback art belongs to the client, which draws it.
        """
        state = await asyncio.to_thread(_load, pid)
        found = _stored_media(pid)
        if found is None:
            raise HTTPException(status_code=404, detail="No footage stored")

        # Cached on disk under the media version, so a re-upload at the same
        # production id gets a new picture — the rule the video URL and the box
        # cache already follow, for the same reason.
        cached = found[0].parent / f"thumb-{_media_version(pid)}.jpg"
        if not cached.exists():
            frame = await asyncio.to_thread(
                extract_frame, found[0], _poster_moment(state)
            )
            if not frame:
                raise HTTPException(status_code=404, detail="No frame available")
            await asyncio.to_thread(cached.write_bytes, frame)

        return FileResponse(
            cached,
            media_type="image/jpeg",
            # The filename carries the version, so this URL's bytes never
            # change and the client busts it with ?v= exactly like the video.
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    # Boxes measured on the paused frame, cached per whole second.
    #
    # The scan's boxes come from the video pass, where Gemini samples at about
    # 1fps and returns ONE rectangle per time range — a union of where the
    # subject travelled rather than where it is in any frame. Three separate
    # box defects traced back to that. Grounding a still sidesteps the video
    # timeline entirely: full resolution, one frame, labels already known.
    # Keyed by (production, FOOTAGE, second). The version is load-bearing: every
    # upload from the UI lands at the same production id, so a key of
    # (pid, second) survived a change of film. `media_version` already busts the
    # browser's video cache and the client's own box map — and then the very
    # next /ground handed back the previous film's rectangles marked
    # `grounded: true`, i.e. presented as measured on this frame. Putting the
    # thing that invalidates the answer INTO the key also makes a late
    # measurement from the old film land harmlessly under the old key rather
    # than poisoning the new one.
    _ground_cache: dict[tuple[str, str, int], dict] = {}
    # Seconds being measured right now, so the same frame is never paid for
    # twice. Pre-grounding schedules every second up front — all of them check
    # the cache before more than a handful have finished — and a reviewer
    # pausing races them.
    _ground_inflight: dict[tuple[str, str, int], asyncio.Future] = {}
    # One gate for the whole process, not one per warm-up. It also bounds the
    # on-demand path, which had no limit at all: a reviewer dragging the
    # scrubber could queue dozens of model calls.
    _ground_gate = asyncio.Semaphore(4)
    # One client per configuration, not one per frame. Building it re-resolves
    # ADC and opens a fresh connection pool, and the instance is where the
    # model-fallback answer is remembered — so a 150-frame warm-up was paying
    # both costs 150 times. Keyed by the config that shapes it, because config
    # is read from the environment per request and a flip should take effect.
    _grounding_clients: dict[tuple, object] = {}

    def _grounding_client(cfg):
        key = (cfg.mode, cfg.project, cfg.location, cfg.gemini_model)
        if key not in _grounding_clients:
            _grounding_clients[key] = build_grounding_client(cfg)
        return _grounding_clients[key]

    async def _ground_second(pid: str, at_s: float, here: list) -> dict:
        """One measurement per second per film, however many ask for it."""
        key = (pid, _media_version(pid), int(at_s))
        if key in _ground_cache:
            return {
                "at_s": at_s,
                "boxes": _ground_cache[key],
                "grounded": True,
                "cached": True,
            }
        waiting = _ground_inflight.get(key)
        if waiting is not None:
            # Someone is already measuring this exact frame. Their answer is
            # ours; asking again would buy the same rectangles twice.
            return {**(await asyncio.shield(waiting)), "at_s": at_s}

        loop = asyncio.get_running_loop()
        mine: asyncio.Future = loop.create_future()
        _ground_inflight[key] = mine
        body = {"at_s": at_s, "boxes": {}, "grounded": False}
        try:
            async with _ground_gate:
                # Re-checked inside the gate: while this call queued, the
                # answer may have arrived from a warm-up that got there first.
                if key in _ground_cache:
                    body = {
                        "at_s": at_s,
                        "boxes": _ground_cache[key],
                        "grounded": True,
                        "cached": True,
                    }
                else:
                    body = await _measure_frame(pid, at_s, here, key)
        finally:
            _ground_inflight.pop(key, None)
            if not mine.done():
                mine.set_result(body)
        return body

    @app.get("/api/productions/{pid}/ground")
    async def ground_frame_at(pid: str, at_s: float = 0.0):
        # In a thread: reading and validating a state file is not free, and a
        # sync handler would land in the threadpool anyway. Doing it inline in
        # an `async def` stalled every other request for the length of it —
        # the same mistake the ffmpeg and Gemini calls below already avoid.
        state = await asyncio.to_thread(_load, pid)

        # Only ask about elements the analysis says are on screen here. A model
        # asked to place something that is not in the frame will sometimes
        # oblige, and asking costs a call.
        here = [
            el for el in state.elements
            if el.timing_reliable
            and any(r.start_s <= at_s <= r.end_s for r in el.time_ranges)
        ]
        # Nothing here is a conclusion, not a gap: the analysis says no
        # element appears at this moment, so there is nothing to place.
        if not here:
            return {"at_s": at_s, "boxes": {}, "grounded": True}
        return await _ground_second(pid, at_s, here)

    async def _measure_frame(pid: str, at_s: float, here: list, key) -> dict:
        found = _stored_media(pid)
        if found is None:
            return {"at_s": at_s, "boxes": {}, "grounded": False}

        # ffmpeg is a subprocess, and a subprocess call in an async handler
        # blocks the event loop exactly as a synchronous SDK call does.
        frame = await asyncio.to_thread(extract_frame, found[0], at_s)
        if frame is None:
            # Nobody looked at this frame. Saying "grounded" would tell the
            # player to suppress every box on it.
            return {"at_s": at_s, "boxes": {}, "grounded": False}

        cfg = ClearFrameConfig.from_env(os.environ)
        try:
            located = await _grounding_client(cfg).ground_frame(
                # One entry per distinct label: asking twice about the same
                # words invites the model to answer twice for one object.
                frame, list(dict.fromkeys(el.label for el in here))
            )
        except Exception as exc:  # a refined box is a nicety, never a failure
            log.warning("grounding failed for %s at %.2fs: %s", pid, at_s, exc)
            return {"at_s": at_s, "boxes": {}, "grounded": False}

        # Keyed by element id, and a LIST: the client draws against its own
        # state, a label is not a stable identifier, and one finding can be in
        # two places in the same frame.
        boxes = {
            eid: [b.model_dump() for b in found]
            for eid, found in bind_ground_boxes(here, located, at_s).items()
        }
        _ground_cache[key] = boxes
        return {"at_s": at_s, "boxes": boxes, "grounded": True}

    # Productions whose boxes have already been warmed in this process, and
    # how far along each one is. Without the second, a reviewer pausing during
    # the warm-up cannot tell a frame that is still being measured from a
    # player that has stopped working — which is exactly how this landed the
    # first time.
    # Keyed by (production, FOOTAGE) for the same reason the box cache is: a
    # re-upload at the same id must be warmed again, and this used to be a bare
    # set of ids, so the second film was never warmed at all.
    _pregrounded: set[tuple[str, str]] = set()
    _preground_progress: dict[str, dict] = {}

    def _plan_seconds(state) -> list[int]:
        """Which whole seconds to measure, most useful first.

        Every whole second something is on screen, because a reviewer pauses
        where they pause — not on the midpoint of an appearance. Midpoints
        first so the moments most likely to be jumped to are warm earliest; a
        clip long enough to exceed the cap gets its midpoints regardless.
        """
        midpoints, filler = set(), set()
        for el in state.elements:
            if not el.timing_reliable:
                continue
            for r in el.time_ranges:
                midpoints.add(int((r.start_s + r.end_s) / 2))
                filler.update(range(int(r.start_s), int(r.end_s) + 1))
        return sorted(midpoints) + sorted(filler - midpoints)

    def _start_preground(pid: str, state) -> dict | None:
        """Seed the progress SYNCHRONOUSLY, then measure in the background.

        The seeding is not tidiness. The player polls this endpoint from a
        child effect, and React runs child effects before its parent's — so
        the first GET goes out before the POST that starts the warm-up exists.
        If progress only appeared once the task got a turn, that poll saw
        "not running", latched off, and the reviewer watched an eight-second
        model call with nothing on screen saying it was happening.
        """
        ordered = _plan_seconds(state)
        if not ordered:
            return None
        seconds = ordered[:PREGROUND_MAX_FRAMES]
        progress = {
            "total": len(seconds),
            "done": 0,
            "running": True,
            "skipped": max(0, len(ordered) - len(seconds)),
        }
        _preground_progress[pid] = progress
        _pregrounded.add((pid, _media_version(pid)))
        if len(ordered) > len(seconds):
            # Never a silent cap: a second that was not warmed still works, it
            # is just slow, and the reviewer should not have to guess which.
            log.info(
                "pre-grounding %d of %d frame(s) for %s (capped at %d; the rest "
                "are measured on demand)",
                len(seconds), len(ordered), pid, PREGROUND_MAX_FRAMES,
            )
        else:
            log.info("pre-grounding %d frame(s) for %s", len(seconds), pid)
        asyncio.create_task(_preground(pid, state, seconds, progress))
        return progress

    async def _preground(pid: str, state, seconds: list[int], progress: dict) -> None:
        """Measure the moments that matter before anyone pauses on them.

        Grounding a cold frame is a Gemini call on a still and takes about
        eight seconds. On demand that is the whole interaction: pause, wait,
        and meanwhile the only honest thing to draw is nothing, because the
        scan's rectangle is a union across the whole appearance and is wrong
        at any given instant.

        The appearance timecodes are already known, so the wait is avoidable.
        Every second something is on screen, measured in the background once
        triage has fixed the boxes, makes the moments a reviewer actually
        lands on warm before they get there. Failures are swallowed: a cold
        second still works the old way, just slowly.

        Concurrency, de-duplication and caching all belong to `_ground_second`
        now. This used to hold its own semaphore, so two warm-ups running at
        once ran at twice the intended rate, and it checked the cache outside
        that gate, so a second could be measured twice.
        """
        # Which film this warm-up is for. If the footage changes underneath it,
        # every remaining second belongs to a film nobody is looking at any
        # more — and its answers would be cached against the new one's id.
        version = _media_version(pid)

        async def one(second: int) -> None:
            if _media_version(pid) != version:
                return
            at_s = float(second)
            here = [
                el for el in state.elements
                if el.timing_reliable
                and any(r.start_s <= at_s <= r.end_s for r in el.time_ranges)
            ]
            try:
                if here:
                    await _ground_second(pid, at_s, here)
            except Exception as exc:  # a warm cache is a nicety, never a failure
                log.warning("pre-grounding %s at %ss failed: %s", pid, second, exc)
            finally:
                progress["done"] += 1

        try:
            await asyncio.gather(*(one(s) for s in seconds), return_exceptions=True)
        finally:
            progress["running"] = False
        log.info("pre-grounding complete for %s (%d cached)", pid, len(_ground_cache))

    @app.get("/api/productions/{pid}/preground")
    def preground_progress(pid: str):
        """How much of this production has had its boxes measured."""
        return _preground_progress.get(
            pid, {"total": 0, "done": 0, "running": False, "skipped": 0}
        )

    @app.post("/api/productions/{pid}/preground")
    async def preground(pid: str):
        """Warm the boxes on demand — used by the UI once a run finishes.

        Refuses to stack. Triage starts one, the SPA starts one when the
        player mounts, and a reload starts another; each used to get its own
        semaphore and all of them wrote to one progress dict, so `done` could
        exceed `total` and whichever finished first reported the whole warm-up
        complete while measurement was still in flight.
        """
        state = await asyncio.to_thread(_load, pid)
        running = _preground_progress.get(pid)
        if running and running.get("running"):
            return {"status": "already-warming", **running}
        if (pid, _media_version(pid)) in _pregrounded:
            return {"status": "warm", **(running or {})}
        _start_preground(pid, state)
        return {
            "status": "warming",
            "appearances": sum(len(el.time_ranges) for el in state.elements),
        }

    @app.get("/api/licences")
    def list_licences():
        """The rights ledger: clearances this deployment already holds."""
        ledger = LicenceStore(out_root / "state")
        return {"licences": [lic.model_dump(mode="json") for lic in ledger.load()]}

    @app.post("/api/licences")
    async def upload_licences(
        request: Request,
        file: UploadFile = File(...),
        replace: bool = Form(True),
        x_clearframe_role: str = Header(default="editor"),
    ):
        """Upload your own rights ledger as JSON or CSV.

        CSV columns: id, rights_holder, work, scope, territories, media,
        starts, expires, reference, notes. Territories and media are
        pipe- or semicolon-separated (e.g. "US|DE|FR").
        """
        if _role_for(request, x_clearframe_role).lower() not in {"legal", "producer"}:
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
        return JSONResponse(
            _with_timing_verdicts(_with_media_flag(_load(pid))).model_dump(mode="json")
        )

    @app.post("/api/productions/{pid}/decisions")
    async def post_decision(
        request: Request,
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
                    role=_role_for(request, x_clearframe_role),
                    # A person, once we know one. This was the role WORD, so an
                    # E&O audit trail recorded that "legal" signed off — and a
                    # job title cannot sign anything.
                    reviewer=_actor_for(request, x_clearframe_role),
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
    async def monitor_webhook(
        body: MonitorAlertRequest,
        x_clearframe_signature: str = Header(default=""),
    ):
        # Parallel Monitor webhook: an outside-world change on a watched finding
        # reopens review so the dossier can't go silently stale.
        #
        # A shared secret rather than a user session, because the caller is
        # Parallel and not a browser. Unset leaves the endpoint open, which is
        # the existing behaviour and what keeps the smoke script running — but
        # this writes to the audit trail and can reopen a signed-off dossier,
        # and monitor ids are readable from an endpoint anyone can reach.
        secret = auth.webhook_secret()
        if secret and not hmac.compare_digest(secret, x_clearframe_signature or ""):
            raise HTTPException(status_code=401, detail="Bad webhook signature.")
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
        app.mount("/", _ShellFiles(directory=DIST_DIR, html=True), name="ui")
    else:

        @app.get("/")
        def index():
            return {
                "app": "ClearFrame Review API",
                "ui": "webapp/dist not built — run `npm run build` in webapp/",
                "api": "/docs",
            }

    return app
