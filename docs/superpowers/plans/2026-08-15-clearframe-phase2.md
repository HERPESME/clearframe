# ClearFrame Phase 2 Implementation Plan — Live Integrations + Review UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClearFrame live-capable (Vertex Gemini video scan, env-driven mode selection) and give it its complete product face: the clearance review web app (FastAPI + Vite/React/Tailwind), cue sheet export, and deployment collateral.

**Architecture:** Live clients slot behind the existing `GeminiClient`/`ParallelClient` protocols — no core changes. A `config.py` module owns env-driven mode selection. The web app is an API-first FastAPI backend over `LocalJsonStore` state with server-side role enforcement, plus a prebuilt React SPA committed to `webapp/dist` so judges need only Python to run it.

**Tech Stack:** google-genai (Vertex), FastAPI + uvicorn, Vite + React + Tailwind (build-time only), pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-clearframe-design.md` (§3.2, §3.4, §5)

## Global Constraints

- All Phase-1 constraints hold (src layout, Pydantic v2, deterministic scoring, demo mode = zero network/credentials).
- Live-mode code paths must degrade with actionable error messages listing exactly which env vars are missing.
- The web backend enforces roles server-side (`X-ClearFrame-Role`); UI role switcher is a convenience, not the control.
- `webapp/dist` is committed so the UI runs without node.
- Env vars: `CLEARFRAME_MODE` (demo|live), `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (default `us-central1`), `PARALLEL_API_KEY`, `CLEARFRAME_GEMINI_MODEL` (default `gemini-3-pro-preview`, runtime fallback `gemini-2.5-pro`).

---

### Task 1: LiveGeminiClient (Vertex video scan)

**Files:** Create `src/clearframe/integrations/gemini_live.py`; Test `tests/test_gemini_live.py`

**Interfaces:**
- `LiveGeminiClient(project: str, location: str, model: str = "gemini-3-pro-preview", fallback_model: str = "gemini-2.5-pro", client_factory=None)` implementing `GeminiClient.scan(footage_uri, duration_s) -> ScanResult`.
- `footage_uri` handling: `gs://` → `types.Part.from_uri(file_uri=..., mime_type="video/mp4")`; local path → `types.Part.from_bytes(data=..., mime_type="video/mp4")`; else `ValueError`.
- Calls `client.models.generate_content(model=..., contents=[video_part, SCAN_PROMPT], config=GenerateContentConfig(response_mime_type="application/json", response_schema=SCAN_RESPONSE_SCHEMA))`, parses `resp.text` as JSON → `parse_scan_payload`.
- Error policy (spec §6): on JSON decode / empty-elements-with-nonempty-video validation error → one re-prompt appending the parse error text; second failure raises `ScanFailedError`. On model-not-found for primary model → retry once with `fallback_model`.
- `client_factory` (returns a genai Client) exists so tests inject a fake; default builds `genai.Client(vertexai=True, project=..., location=...)`.

- [ ] **Step 1: failing tests** — fake client object with programmable `.models.generate_content` returning stub responses (`SimpleNamespace(text=...)`): (a) happy path parses two elements; (b) first response invalid JSON, second valid → succeeds and the retry prompt contains the error; (c) both invalid → `ScanFailedError`; (d) local path missing file → `FileNotFoundError`.
- [ ] **Step 2: run → FAIL.** **Step 3: implement.** **Step 4: run → PASS.** **Step 5: commit** `feat: live Vertex Gemini scan client`.

### Task 2: Config + mode wiring + live CLI

**Files:** Create `src/clearframe/config.py`; Modify `src/clearframe/cli.py`, `src/clearframe/pipeline.py` (add `build_context(cfg, production, out_root)`); Test `tests/test_config.py`

**Interfaces:**
- `ClearFrameConfig` (pydantic): `mode: Literal["demo","live"]`, `project: str|None`, `location: str`, `parallel_api_key: str|None`, `gemini_model: str`; classmethod `from_env(env: Mapping[str,str]) -> ClearFrameConfig`.
- `validate_live(cfg)` → list of missing var names; `build_context(cfg, production, out_root)` returns PipelineContext with fixture clients (demo) or `LiveGeminiClient` + `LiveParallelClient` (live).
- CLI: `run --live --footage <path|gs://uri> [--title T] [--duration-s N]` (footage required in live mode; duration default 0 lets Gemini infer). Missing env → exit 2 with the missing-vars message. `--demo` unchanged.

- [ ] **Step 1: failing tests** — `from_env` defaults; live context wires Live clients (monkeypatched constructors); `validate_live` lists `GOOGLE_CLOUD_PROJECT`/`PARALLEL_API_KEY` when absent; CLI live without env exits 2 mentioning both vars.
- [ ] **Steps 2–5:** red → implement → green → commit `feat: env config and live mode wiring`.

### Task 3: Cue sheet exporter

**Files:** Create `src/clearframe/exporters/cue_sheet.py`; Modify `src/clearframe/stages/dossier.py` (write `cue_sheet.csv` when MUSIC_SYNC elements exist); Test `tests/test_cue_sheet.py`

**Interfaces:**
- `render_cue_sheet(production: Production, elements, research, ) -> str` — CSV, header `cue_number,title,rights_owner,usage,timecode_in,timecode_out,duration_s`; one row per TimeRange of each MUSIC_SYNC element; usage = `"Feature"` if `plot_integral` else `"Background"`; owner falls back `"UNKNOWN"`.
- Golden test: demo state produces one row for the Weeknd cue, usage Feature, duration 12.0.

- [ ] **Steps 1–5:** red → implement → green (extend `test_cli.py` assertion for `cue_sheet.csv` existence) → commit `feat: ASCAP/BMI cue sheet export`.

### Task 4: Review API backend (FastAPI)

**Files:** Create `src/clearframe/webapp/__init__.py`, `src/clearframe/webapp/server.py`; Modify `pyproject.toml` (add `fastapi>=0.110`, `uvicorn>=0.29` to dependencies), `src/clearframe/cli.py` (add `serve` subcommand); Test `tests/test_webapp.py`

**Interfaces:**
- `create_app(out_root: Path) -> FastAPI` over `LocalJsonStore(out_root/"state")`; artifacts in `out_root`.
- Endpoints:
  - `GET /api/productions` → `[{id,title,stage_status}]`
  - `POST /api/productions/demo` → run demo pipeline if absent (idempotent), return full state
  - `GET /api/productions/{pid}` → full `ProductionState` JSON (404 unknown)
  - `POST /api/productions/{pid}/decisions` body `{element_id, action, note}` + header `X-ClearFrame-Role` — role must be `legal` or `producer` else 403; unknown element 404; saves `Decision(reviewer=role-header value, role=header)`
  - `POST /api/productions/{pid}/dossier` → DossierStage; 409 + missing ids if pending decisions; returns `{artifacts:[...]}`
  - `GET /api/productions/{pid}/artifacts/{name}` → FileResponse, name whitelisted to the five artifact files
  - `/` serves `webapp/dist/index.html` + assets when the dist directory exists (SPA fallback), else a JSON pointer to the API.
- `serve` CLI: `python -m clearframe serve --out out --port 8000` (uvicorn).

- [ ] **Step 1: failing tests** (fastapi TestClient): demo create → 6 elements; editor decision → 403; legal decisions for all → dossier 200 and artifacts listed; dossier before decisions → 409 listing pending ids; artifact fetch 200; traversal name → 404.
- [ ] **Steps 2–5:** red → implement → green → commit `feat: clearance review API with role enforcement`.

### Task 5: Review UI (Vite + React + Tailwind SPA)

**Files:** Create `webapp/` (package.json, vite.config.ts, tailwind, `src/…` components), commit built `webapp/dist`; Modify `.gitignore` (ignore `webapp/node_modules`, NOT dist)

**Required screens (spec §5):** production dashboard w/ stage progress; timeline view (SVG timecode ruler 0→duration with risk-colored marker blocks per element range, click → scroll to card); element review cards (label, category + band chips, score factor breakdown, research summary, basis citations as links w/ excerpt + confidence, remediation options w/ collapsible license email, decision buttons Approve risk / License / Blur / Reshoot / Escalate + note field); role switcher (producer/legal/editor → sets `X-ClearFrame-Role`; editor sees buttons disabled); dossier bar (generate → links to artifacts incl. dossier.html, markers.edl/csv, cue_sheet.csv, dossier.json).

**Design:** invoke `frontend-design:frontend-design` skill before building; dark "screening room" aesthetic; risk colors match dossier (`#c0392b`/`#e67e22`/`#2980b9`/`#27ae60`).

- [ ] **Step 1:** scaffold Vite React TS + Tailwind; proxy `/api` → `:8000` for dev.
- [ ] **Step 2:** implement screens against the Task-4 API (fetch wrapper adds role header from a React context).
- [ ] **Step 3:** `npm run build` → dist; run `serve`, exercise the full flow manually (create demo → review all 6 → generate dossier → open artifacts) and screenshot.
- [ ] **Step 4:** commit `feat: clearance review web UI`.

### Task 6: Deployment collateral + README

**Files:** Create `Dockerfile`, `.dockerignore`, `docs/deploy.md`; Modify `README.md`

- Dockerfile: `python:3.12-slim`, copy src + webapp/dist, `pip install .`, `CMD ["python","-m","clearframe","serve","--out","/data/out","--port","8080"]`.
- `docs/deploy.md`: exact `gcloud run deploy` commands, required env vars, Agent Engine deployment notes for `build_clearframe_agent`, Firestore/Pub/Sub wiring plan (Phase 3).
- README: full architecture section, live-mode quickstart, submission checklist mapping, screenshot.

- [ ] **Steps 1–3:** write files → `docker build` if docker available else note → commit `docs: deployment collateral and full README`.

## Self-Review

- Spec coverage: §3.2 live Gemini (T1), §3.4 modes (T2), stretch cue sheet (T3), §5 web app (T4–T5), §3.2 Cloud Run (T6). Firestore/Pub/Sub/Agent Engine deploy and IAP mapping remain Phase 3 (needs credentials) — documented in deploy.md.
- No placeholders: interfaces and test behaviors are pinned; UI visual detail is delegated to the frontend-design skill pass by design.
- Type consistency: clients implement Phase-1 protocols; `build_context` returns Phase-1 `PipelineContext`; artifact names match DossierStage outputs (+ cue_sheet.csv added in T3 and whitelisted in T4).
