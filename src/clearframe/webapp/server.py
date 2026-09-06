"""Clearance review web app: API over production state with server-side role gating."""

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
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
from clearframe.events import EventLog
from clearframe.grounding import (
    GroundStore,
    build_client as grounding_build_client,
    measure_frame,
    plan_seconds,
    warm,
)
from clearframe.runner import HEARTBEAT_EVERY_S, beat
from clearframe.stages.dossier import ReviewPendingError
from clearframe.storage import (
    AnalysisJob,
    Backends,
    IndexRow,
    build_backends,
    build_queue,
)
from clearframe.store import LocalJsonStore
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

# How often the event stream looks for new progress, and how long it will stay
# silent before sending a comment frame. The poll exists because the producer
# may be another container; the keepalive because Cloud Run and intermediate
# proxies close a stream that says nothing, and some stages are quiet for
# minutes.
SSE_POLL_S = 0.25
SSE_KEEPALIVE_S = 15.0


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


def _purge_stale_posters(blobs, pid: str) -> None:
    """Drop the previous cut's poster frames. One list plus N deletes.

    Kept as a plain function so the whole sweep goes to a single thread rather
    than the caller awaiting each delete — and so it cannot be accidentally
    called from a coroutine without one.
    """
    for stale in blobs.list(f"media/{pid}/thumb-"):
        blobs.delete(stale)


async def index_get_async(index, pid: str):
    """`index.get`, off the event loop.

    Firestore in the cloud profile, so a round trip. It is read from the event
    stream's keepalive branch — once every fifteen seconds per open stream, and
    precisely when a stage has gone quiet, which is when the reviewer is most
    likely to be clicking on something else.
    """
    return await asyncio.to_thread(index.get, pid)


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

    Kept as a name here because it is the seam the endpoint tests patch, but the
    implementation lives in `grounding` — the worker builds one too, and two
    copies of "which model, and does demo mode get the fixture twin" is exactly
    the kind of duplication that drifts.
    """
    return grounding_build_client(cfg)


def create_app(out_root: Path, backends: Backends | None = None) -> FastAPI:
    out_root = Path(out_root)
    app = FastAPI(title="ClearFrame Review")
    # Blobs, the production index and the state store. Local by default, so an
    # existing working directory keeps working and the credential-free suite is
    # unaffected; `backends` is the injection point for tests.
    backends = backends or build_backends(
        ClearFrameConfig.from_env(os.environ), out_root
    )
    index = backends.index
    store = backends.store
    # Serializes every load-modify-save of production state; without it,
    # concurrent decision posts (threadpool) and dossier generation could
    # silently clobber each other's saves.
    state_lock = asyncio.Lock()

    # ONE queue for the whole app — the cap is a property of the deployment, not
    # of a request. Building one per upload would give every upload its own
    # semaphore, which is the same as having no cap at all.
    #
    # The runner looks the work up rather than carrying it, because a job has to
    # be describable to a worker in another container and a closure is not.
    _pending_runs: dict[str, object] = {}

    async def _dispatch(job: AnalysisJob) -> None:
        run = _pending_runs.pop(job.production_id, None)
        if run is None:
            log.warning("no pending run for %s", job.production_id)
            return
        await run(job)

    _queue = build_queue(ClearFrameConfig.from_env(os.environ), _dispatch)

    def _owner_of(pid: str) -> str | None:
        row = index.get(pid)
        return row.owner_uid if row else None

    def _require_owner(request, pid: str) -> None:
        """404 for somebody else's production — never 403.

        403 would confirm the id exists, which turns a guessable id into an
        existence oracle. It is also the lower-churn answer: an unknown
        production is already a 404 everywhere in this file.

        Three things deliberately do not scope. With authentication off there is
        no user to scope to and the app must behave exactly as it did before
        ownership existed — that property is what keeps demo mode and the
        credential-free smoke script green. A production with no owner (the
        demo, anything the CLI or MCP wrote) belongs to everybody. And a
        production nobody has claimed cannot be stolen by checking it.
        """
        if not auth.auth_enabled():
            return
        owner = _owner_of(pid)
        if not owner:
            return
        user = _current_user(request)
        if user is None or user.uid != owner:
            raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")

    def _load(pid: str, request=None):
        if request is not None:
            _require_owner(request, pid)
        try:
            return store.load(pid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Unknown production: {pid}")

    def _listener_for(pid: str, log_: EventLog):
        """The `ctx.listener`: publish progress, and say we are still alive.

        Two jobs in one callback because they have the same trigger. The event
        log is what Mission Control reads; the index is what the dashboard
        reads, and its heartbeat is the only thing that can distinguish a run in
        progress from one whose process died — a distinction that used to come
        from a set in this process and therefore could not survive the work
        moving to a worker container.

        The heartbeat rides on stage boundaries rather than a timer because
        `Pipeline.run` already persists after each stage, so it costs nothing
        and there is no extra task to supervise.
        """

        def listen(event: dict) -> None:
            log_.append(event)
            kind = event.get("type")
            stage = event.get("stage")
            if stage and kind in ("stage_start", "stage_complete"):
                index.record_stage(
                    pid, stage, "complete" if kind == "stage_complete" else "running"
                )
                index.heartbeat(pid)

        return listen

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
        user = await auth.user_from_request_async(request)
        if user is None:
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        # Verified once, then carried. Handlers used to call `_current_user`
        # and re-verify the same cookie a second time — network plus RSA,
        # twice, for every authenticated request.
        request.state.clearframe_user = user
        return await call_next(request)

    def _current_user(request):
        """Who is making this request.

        Prefers what the middleware already verified. The fallback is for the
        open paths — `/api/auth/session` and friends — which never reach the
        branch above and so have nothing stashed; those verify once here rather
        than twice.
        """
        if not auth.auth_enabled():
            return None
        stashed = getattr(request.state, "clearframe_user", None)
        if stashed is not None:
            return stashed
        return auth.user_from_request(request)

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
        # Record the person, not their credentials — Firebase owns those and a
        # second copy of a password hash is the one thing nobody should keep.
        # This is what the deployment itself knows: what they call themselves,
        # what role they have been working as, when they first appeared.
        # Firebase can say an account exists and nothing about what it did here.
        try:
            backends.users.seen(
                user.uid,
                email=user.email,
                name=user.name,
                email_verified=user.email_verified,
                role=user.role,
            )
        except Exception:
            # A directory write must never cost somebody their sign-in.
            log.exception("could not record the sign-in for %s", user.uid)
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

    def _media_key(pid: str) -> str | None:
        """The blob key of this production's footage, if it has any."""
        for suffix in MEDIA_TYPES:
            key = f"media/{pid}/footage{suffix}"
            if backends.blobs.exists(key):
                return key
        return None

    def _stored_media(pid: str):
        """The footage for this production as a real path, if it has any.

        Through the blob store now, not a directory. Both containers run
        `--out /tmp/out`, a per-instance tmpfs, so while footage was written
        straight to disk the WORKER could not see what the API had just
        received — every live upload on Cloud Run would have failed at the scan.

        Still a path rather than bytes because the three consumers are ffmpeg
        (an argv), `FileResponse` (streams after the handler returns) and audio
        fingerprinting (which refuses a `gs://` URI outright). Locally that is
        the real file at no cost; in the cloud it is a version-keyed download
        cached per container.
        """
        key = _media_key(pid)
        if key is None:
            return None
        path = backends.blobs.local_path(key)
        if path is None:
            return None
        return path, MEDIA_TYPES[Path(key).suffix]

    def _media_version(pid: str) -> str:
        """Which FOOTAGE this production currently holds.

        The store's own answer: a GCS generation, or size and nanosecond write
        time locally. Whole seconds collide when two uploads land in the same
        one, which a test does routinely and an impatient user manages too.

        This string is what distinguishes one film from the next at a stable
        production id, which is why the box cache, the thumbnail filename, the
        pre-ground set and the video URL are all keyed by it rather than by the
        id alone.
        """
        key = _media_key(pid)
        return (backends.blobs.version(key) or "") if key else ""

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
    def list_productions(request: Request):
        """Your productions, newest first, each flagged with its run state.

        The client restores the first row on load. When this returned store
        order, "demo" sorted ahead of a user's upload — so refreshing the page
        mid-analysis appeared to lose the production entirely. It was never
        lost: the pipeline runs server-side and every stage persists. The
        client was simply handed the wrong one.

        Two of the three facts here used to be answerable only by the process
        running the analysis. `updated_at` was the state file's mtime, and
        `running` was membership of an in-process set — correct for "is THIS
        process running it", wrong for "is anyone running it", and those stop
        being the same question the moment the pipeline moves to a worker
        container. Both now come from the index, which any container can read.
        """
        user = _current_user(request)
        rows = index.list_for(user.uid if user else None)
        return [
            {
                "id": row.id,
                "title": row.title,
                "stage_status": row.stage_status,
                "updated_at": row.updated_at,
                # Something is holding the lease. Survives a restart of *this*
                # process and, unlike the set it replaces, is true across the
                # container boundary.
                "running": row.is_running(),
                # Part-way through and nothing is working on it. Distinct from
                # complete, because silence would read as a finished analysis
                # and the missing stages would never be noticed.
                "interrupted": row.is_interrupted(),
            }
            for row in rows
        ]

    async def _run_paced_demo(pace_s: float, declared: dict | None = None) -> None:
        log_ = EventLog(backends.blobs, "demo")
        ctx = demo_context(out_root)
        if declared:
            ctx.state.production = ctx.state.production.model_copy(update=declared)
        ctx.store = store
        ctx.listener = _listener_for("demo", log_)
        stages = [_PacedStage(s, pace_s) for s in build_demo_pipeline()]
        index.heartbeat("demo")
        try:
            await Pipeline(stages).run(ctx)
        finally:
            index.clear_heartbeat("demo")
            log_.append({"type": "run_complete"})

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
            # Reaching through the store to a filesystem path is what a
            # bucket cannot answer; deleting the blob is the same intent stated
            # in terms the interface actually has.
            backends.blobs.delete("state/demo.json")
            # A replay starts from nothing: the previous run's events must not
            # be prepended to this one, and the row has to exist before the
            # first heartbeat or there is nothing to beat against.
            EventLog.clear(backends.blobs, "demo")
            index.put(IndexRow(id="demo", owner_uid=None, title="Golden Hour"))
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
            backends.blobs.delete("state/demo.json")

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
        request: Request,
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

        user = _current_user(request)
        pid = "".join(c for c in production_id if c.isalnum() or c in "-_") or "upload"
        # A signed-in upload gets an id of its own. `"upload"` was the default
        # AND the only value the client ever sent, so every user's footage
        # landed in one slot — the same state file, the same media directory,
        # and an upload actively deleted the previous occupant's caches and
        # thumbnails. Two people using this at once overwrote each other.
        #
        # Unsigned uploads keep the old id: the CLI, the MCP server and the
        # smoke script all address `upload` by name, and demo mode has no user
        # to attribute one to.
        if user is not None and production_id == "upload":
            pid = f"p-{secrets.token_hex(4)}"
        # An id you were given back is yours to re-upload to; an id belonging to
        # somebody else is not. Without this, naming another user's production
        # overwrote their footage and state, wiped their event log, thumbnails
        # and measured boxes, and reassigned `owner_uid` to the caller — because
        # the index row is replaced wholesale below. 404 rather than 403, like
        # every other ownership refusal here: a 403 would confirm the id exists.
        _require_owner(request, pid)
        name = _safe_media_name(file.filename or "")
        media_key = f"media/{pid}/{name}"

        # Stream to a temporary file first, then hand the finished file to the
        # store. Streaming lets the size cap stop a hostile upload part-way
        # instead of after 512MB has been accepted, and a completed file is what
        # `put_file` wants — the cloud store uploads it without ever holding the
        # whole clip in a container sized for an API.
        import tempfile as _tempfile

        fd, staged_name = _tempfile.mkstemp(suffix=Path(name).suffix)
        staged = Path(staged_name)
        written = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Footage exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
                        )
                    out.write(chunk)
            await asyncio.to_thread(backends.blobs.put_file, media_key, staged)
        finally:
            staged.unlink(missing_ok=True)

        # In a thread: in the cloud profile this DOWNLOADS the clip back out
        # of the bucket into the container's cache, which for a 512MB upload
        # is not a file open, it is a transfer.
        target = await asyncio.to_thread(backends.blobs.local_path, media_key)
        if target is None:  # pragma: no cover - the store just wrote it
            raise HTTPException(status_code=500, detail="Footage could not be stored.")

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
        # but it would sit in the bucket for the life of the deployment
        # otherwise — and there it costs money rather than a few inodes.
        await asyncio.to_thread(_purge_stale_posters, backends.blobs, pid)

        ctx = build_context(
            cfg.model_copy(update={"mode": "live"}),
            production,
            out_root,
            # Their licences decide their coverage, and nobody else's.
            owner_uid=user.uid if user else "",
            licences=backends.ledger(user.uid if user else "").load(),
        )
        ctx.store = store
        # Persist the production BEFORE handing the job over.
        #
        # In-process this was unnecessary: the run held the state in memory and
        # the first stage wrote it. A worker in another container has no memory
        # to share — it is given a production id and loads what is on disk — so
        # without this it answers "no such production" and acks a job that never
        # runs. Found by actually running the split topology; no unit test could
        # see it, because they all write the state file themselves.
        await asyncio.to_thread(store.save, ctx.state)
        await asyncio.to_thread(EventLog.clear, backends.blobs, pid)
        run_log = EventLog(backends.blobs, pid)
        publish = _listener_for(pid, run_log)
        # Open the log BEFORE responding, so the stream exists the moment the
        # client asks for it.
        #
        # In one process this was free: the event queue was created here,
        # synchronously, and the endpoint could never 404 for a run that had
        # just started. With the work queued to another container the first real
        # event is several seconds away — dispatch plus a 4Gi cold start — and
        # the client opens its EventSource the instant this response lands. It
        # got a 404, and `MissionControl` closes on error and never retries, so
        # the analysis ran to completion behind a screen that said "Standing
        # by". Seen on the deployed site: one 404, no second attempt.
        await asyncio.to_thread(run_log.append, {"type": "queued", "production_id": pid})
        # The row has to exist before the run starts: it is what the dashboard
        # lists, what carries the owner, and what the heartbeat beats against.
        await asyncio.to_thread(
            index.put,
            IndexRow(
                id=pid,
                owner_uid=(user.uid if user else None),
                title=production.title,
                has_media=True,
                media_version=await asyncio.to_thread(_media_version, pid),
            ),
        )

        def _listen(event: dict) -> None:
            publish(event)
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

        async def _run(job) -> None:
            # The same beat the worker uses, for the same reason. This path had
            # it worse: one heartbeat at the start and nothing again until the
            # run ended, so a local analysis longer than the staleness window
            # reported itself dead while it was still working.
            index.heartbeat(job.production_id)
            heart = asyncio.create_task(
                beat(index, job.production_id, HEARTBEAT_EVERY_S)
            )
            try:
                await Pipeline(build_demo_pipeline()).run(ctx)
            finally:
                heart.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heart
                index.clear_heartbeat(job.production_id)
                run_log.append({"type": "run_complete"})

        # Queued, not launched. Nothing counted in-flight analyses before this,
        # and each one is three Gemini video passes plus research plus up to 150
        # grounding calls — the deployed `--max-instances=2 --concurrency=80`
        # would have admitted a hundred and sixty of them.
        #
        # The run goes into a registry rather than into the job, because the
        # queue is one object for the whole app and a job has to survive being
        # handed to a worker in another container, where a closure cannot go.
        _pending_runs[pid] = _run
        await _queue.enqueue(
            AnalysisJob(production_id=pid, owner_uid=user.uid if user else None)
        )
        return {"production_id": pid, "status": "queued", "media": name}

    @app.get("/api/productions/{pid}/media")
    def get_media(pid: str, request: Request):
        """Serve the uploaded footage so the review UI can play it."""
        _load(pid, request)
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
    async def get_thumbnail(pid: str, request: Request):
        """A poster for this production, taken from its own footage.

        The dashboard needs a picture per production and the only honest one is
        a frame the production already contains — this is a rights-clearance
        tool, so shipping somebody else's marketing art as decoration would be
        a poor joke at its own expense.

        404 rather than a placeholder when there is nothing to extract: the
        fallback art belongs to the client, which draws it.
        """
        state = await asyncio.to_thread(_load, pid, request)
        found = _stored_media(pid)
        if found is None:
            raise HTTPException(status_code=404, detail="No footage stored")

        # Cached on disk under the media version, so a re-upload at the same
        # production id gets a new picture — the rule the video URL and the box
        # cache already follow, for the same reason.
        thumb_key = f"media/{pid}/thumb-{_media_version(pid)}.jpg"
        if not backends.blobs.exists(thumb_key):
            frame = await asyncio.to_thread(
                extract_frame, found[0], _poster_moment(state)
            )
            if not frame:
                raise HTTPException(status_code=404, detail="No frame available")
            await asyncio.to_thread(backends.blobs.put, thumb_key, frame)
        cached = backends.blobs.local_path(thumb_key)
        if cached is None:  # pragma: no cover - just written
            raise HTTPException(status_code=404, detail="No frame available")

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

    def _ground_store(pid: str) -> GroundStore:
        return GroundStore(backends.blobs, pid, _media_version(pid))

    def _hit(at_s: float, boxes: dict) -> dict:
        return {"at_s": at_s, "boxes": boxes, "grounded": True, "cached": True}

    async def _ground_second(pid: str, at_s: float, here: list) -> dict:
        """One measurement per second per film, however many ask for it.

        Three tiers, and the middle one is what makes the feature work in the
        deployed topology at all: **memory (11-14ms) -> the blob store (~30-50ms)
        -> Gemini (8-14s)**. The worker measures during the run and writes to the
        bucket; this is where the API reads that back. Without it the analysis
        container's work was invisible to the one serving `/ground`, and with
        `--max-instances=2` two API instances paid Gemini separately for the
        same frame.

        A blob MISS is not an answer. It falls through to measuring, never to
        `grounded: false` — that distinction is the whole contract the player's
        four-answer logic rests on.
        """
        key = (pid, _media_version(pid), int(at_s))
        if key in _ground_cache:
            return _hit(at_s, _ground_cache[key])
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
            stored = await asyncio.to_thread(_ground_store(pid).read, int(at_s))
            if stored is not None:
                _ground_cache[key] = stored
                body = _hit(at_s, stored)
            else:
                async with _ground_gate:
                    # Re-checked inside the gate: while this call queued, the
                    # answer may have arrived from a warm-up that got there
                    # first.
                    if key in _ground_cache:
                        body = _hit(at_s, _ground_cache[key])
                    else:
                        body = await _measure_frame(pid, at_s, here, key)
        finally:
            _ground_inflight.pop(key, None)
            if not mine.done():
                mine.set_result(body)
        return body

    @app.get("/api/productions/{pid}/ground")
    async def ground_frame_at(pid: str, request: Request, at_s: float = 0.0):
        # In a thread: reading and validating a state file is not free, and a
        # sync handler would land in the threadpool anyway. Doing it inline in
        # an `async def` stalled every other request for the length of it —
        # the same mistake the ffmpeg and Gemini calls below already avoid.
        state = await asyncio.to_thread(_load, pid, request)

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

        cfg = ClearFrameConfig.from_env(os.environ)
        boxes = await measure_frame(found[0], at_s, here, _grounding_client(cfg))
        if boxes is None:
            # Nobody looked at this frame, or the model refused. Saying
            # "grounded" would tell the player to suppress every box on it.
            return {"at_s": at_s, "boxes": {}, "grounded": False}

        _ground_cache[key] = boxes
        # And where the other container can read it. A frame a reviewer paused
        # on is measured exactly once for the whole deployment, not once per
        # instance.
        await asyncio.to_thread(_ground_store(pid).write, int(at_s), boxes)
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

    def _start_preground(pid: str, state) -> dict | None:
        """Seed the progress SYNCHRONOUSLY, then measure in the background.

        The seeding is not tidiness. The player polls this endpoint from a child
        effect, and React runs child effects before its parent's — so the first
        GET goes out before the POST that starts the warm-up exists. If progress
        only appeared once the task got a turn, that poll saw "not running",
        latched off, and the reviewer watched an eight-second model call with
        nothing on screen saying it was happening.

        The measuring itself is `grounding.warm`, shared with the worker, so the
        two transports cannot drift on which seconds get measured or what the
        cap means. What is NOT shared is the measurer: this one goes through
        `_ground_second`, which owns the in-memory tier and the in-flight map, so
        a reviewer pausing during the warm-up joins the call already in progress
        instead of buying the same rectangles twice.
        """
        if not plan_seconds(state):
            return None
        progress: dict = {"total": 0, "done": 0, "running": True, "skipped": 0}
        _preground_progress[pid] = progress
        _pregrounded.add((pid, _media_version(pid)))
        asyncio.create_task(_preground(pid, state, progress))
        return progress

    async def _preground(pid: str, state, progress: dict) -> None:
        """Measure the moments that matter before anyone pauses on them."""
        # Which film this warm-up is for. If the footage changes underneath it,
        # every remaining second belongs to a film nobody is looking at any
        # more — and its answers would be filed against the new one.
        version = _media_version(pid)

        async def measure(at_s: float, here: list):
            if _media_version(pid) != version:
                return None
            await _ground_second(pid, at_s, here)
            # Already stored: `_ground_second` has to write the blob anyway,
            # because a reviewer pausing on a cold frame must leave a
            # measurement behind for everyone else.
            return None

        await warm(
            GroundStore(backends.blobs, pid, version),
            state,
            measure,
            cap=PREGROUND_MAX_FRAMES,
            progress=progress,
        )

    @app.get("/api/productions/{pid}/preground")
    async def preground_progress(pid: str, request: Request):
        """How much of this production has had its boxes measured.

        This instance's own warm-up first, then whatever the WORKER published.
        In the deployed topology the container measuring the boxes is not the
        one being polled, so without the second lookup the client's
        "measuring boxes N/M" reported nothing while the work was happening in
        another container.
        """
        _require_owner(request, pid)
        mine = _preground_progress.get(pid)
        if mine is not None:
            return mine
        theirs = await asyncio.to_thread(_ground_store(pid).read_progress)
        # `total: 0` means nobody has started. The client distinguishes that
        # from finished (a total, not running) and latches its poll off only on
        # the second, so the zero must not be mistaken for a completed run.
        return theirs or {"total": 0, "done": 0, "running": False, "skipped": 0}

    @app.post("/api/productions/{pid}/preground")
    async def preground(pid: str, request: Request):
        """Warm the boxes on demand — used by the UI once a run finishes.

        Refuses to stack. Triage starts one, the SPA starts one when the
        player mounts, and a reload starts another; each used to get its own
        semaphore and all of them wrote to one progress dict, so `done` could
        exceed `total` and whichever finished first reported the whole warm-up
        complete while measurement was still in flight.
        """
        state = await asyncio.to_thread(_load, pid, request)
        running = _preground_progress.get(pid)
        if running and running.get("running"):
            return {"status": "already-warming", **running}
        if (pid, _media_version(pid)) in _pregrounded:
            return {"status": "warm", **(running or {})}
        # The worker warms during the run, so by the time the client opens the
        # production the work is usually already done. Re-running it here would
        # buy 150 frames a second time for rectangles the bucket already holds.
        theirs = await asyncio.to_thread(_ground_store(pid).read_progress)
        if theirs and not theirs.get("running") and theirs.get("total"):
            return {"status": "warm", **theirs}
        if theirs and theirs.get("running"):
            return {"status": "already-warming", **theirs}
        _start_preground(pid, state)
        return {
            "status": "warming",
            "appearances": sum(len(el.time_ranges) for el in state.elements),
        }

    def _ledger_for(request):
        """This caller's rights ledger.

        One global file meant one account's licences decided another account's
        coverage — upload a grant for Nike and every other user's Nike finding
        read COVERED, with that conclusion written into their E&O dossier. With
        auth off there is no caller to scope to and the global ledger is exactly
        right, which is what the demo, the CLI and the smoke script use.
        """
        user = _current_user(request)
        # Through the backends, not straight to disk. In the cloud profile the
        # ledger lives in the bucket, because `out_root` here is the API
        # container's own tmpfs and the worker that reads the ledger during
        # `coverage` has never seen it.
        return backends.ledger(user.uid if user else "")

    @app.get("/api/licences")
    def list_licences(request: Request):
        """The rights ledger: clearances YOU already hold."""
        ledger = _ledger_for(request)
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

        ledger = _ledger_for(request)
        existing = [] if replace else ledger.load()
        by_id = {lic.id: lic for lic in existing}
        for lic in assign_ids(parsed, set(by_id)):
            by_id[lic.id] = lic
        merged = list(by_id.values())
        ledger.save(merged)
        return {"stored": len(merged), "added": len(parsed), "replaced": replace}

    @app.get("/api/productions/{pid}/events")
    async def stream_events(pid: str, request: Request):
        """Mission Control's stream, tailed from the log rather than a queue.

        The producer may be a different container, so this cannot await an
        in-process `asyncio.Queue` — it reads the log the run appends to and
        keeps its own cursor.

        Two behaviours change for the better as a side effect. Every reader gets
        every event, where `queue.get()` used to consume it so two tabs on one
        run split the stream between them. And the log is not deleted at
        `run_complete`, so a reader who arrives late replays from the top
        instead of getting a 404 — Mission Control's handlers are all setters,
        so a replay converges on the same screen.
        """
        _require_owner(request, pid)
        if not await EventLog.exists_async(backends.blobs, pid):
            raise HTTPException(status_code=404, detail="No active run for this production")

        async def gen():
            cursor = 0
            idle = 0.0
            while True:
                # Off the loop. This is a bucket round trip four times a
                # second for the length of a run; inline it stopped the
                # API's single event loop on every poll.
                events = await EventLog.read_async(backends.blobs, pid)
                if len(events) > cursor:
                    idle = 0.0
                    for event in events[cursor:]:
                        yield f"data: {json.dumps(event)}\n\n"
                    cursor = len(events)
                    if events[-1].get("type") == "run_complete":
                        break
                else:
                    await asyncio.sleep(SSE_POLL_S)
                    idle += SSE_POLL_S
                    # A comment frame keeps proxies and Cloud Run from closing
                    # an idle stream during a long silent stage.
                    if idle >= SSE_KEEPALIVE_S:
                        idle = 0.0
                        yield ": keepalive\n\n"
                        # Nothing is holding the lease and nothing has arrived:
                        # the run died with its container. Ending the stream is
                        # honest; hanging on it for ever is what the old
                        # in-process set was invented to avoid.
                        row = await index_get_async(index, pid)
                        if row is not None and not row.is_running():
                            break
                if await request.is_disconnected():
                    break

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/productions/{pid}")
    def get_production(pid: str, request: Request):
        return JSONResponse(
            _with_timing_verdicts(_with_media_flag(_load(pid, request))).model_dump(
                mode="json"
            )
        )

    @app.post("/api/productions/{pid}/decisions")
    async def post_decision(
        request: Request,
        pid: str,
        body: DecisionRequest,
        x_clearframe_role: str = Header(default="editor"),
    ):
        # The one pid-route that never checked, and the one where it matters
        # most: this writes a signature into somebody's E&O audit trail. It was
        # missing from the parametrized ownership test too, which is exactly why
        # nothing caught it.
        _require_owner(request, pid)
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
    async def check_freshness(pid: str, request: Request):
        """Live Parallel Search pass over every identified rights holder.

        Deep research is a snapshot from pipeline time; this is the real-time
        check a reviewer runs before signing off. Priced per request, so it is
        affordable to call on demand from the review screen.
        """
        _require_owner(request, pid)
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
    async def generate_dossier(pid: str, request: Request):
        _require_owner(request, pid)
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
        artifacts = [
            n for n in ARTIFACT_WHITELIST
            if (out_root / "artifacts" / pid / n).exists()
        ]
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
    def get_artifact(pid: str, name: str, request: Request):
        _load(pid, request)
        # The whitelist is checked BEFORE a path is built, which is what makes
        # `..%2Fpyproject.toml` a 404 rather than a traversal — it must stay a
        # membership test, never a normalisation.
        if name not in ARTIFACT_WHITELIST:
            raise HTTPException(status_code=404, detail="Unknown artifact")
        path = out_root / "artifacts" / pid / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Unknown artifact")
        media = "text/html" if name.endswith(".html") else "text/plain"
        return FileResponse(path, media_type=media)

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
