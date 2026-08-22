# ClearFrame — Project Context

Autonomous rights-clearance department for film & TV. Google Cloud "Agentic Cinema" hackathon, **Parallel track**, deadline **Sep 10 2026, 2:30am IST**. Devpost judging: tech implementation, complete product (not PoC), credible impact, non-obvious idea.

## Architecture (read before editing)

Deterministic 12-stage pipeline: **script** (pre-scan) → **scan** (Gemini video, Vertex) → **triage** (rules+dedupe) → **corroborate** (independent logo catalogue confirms identity) → **drift** (script vs screen) → **research** (Parallel Task API fan-out, Basis citations = audit trail) → **freshness** (Parallel Search, live enforcement check) → **risk** (pure-code rubric in `scoring.py` — NEVER an LLM) → **territory** (per-jurisdiction bands) → **coverage** (rights ledger: are we already licensed?) → **remediation** (template drafts) → **court** → human review → **dossier** (E&O report + EDL/CSV markers + cue sheet). `ANALYSIS_STAGES` in `pipeline.py` is the source of truth — update it and the event-count test together.

- Core (`models.py`, `scoring.py`, `triage.py`, `pipeline.py`, `corroboration.py`, `territory.py`, `freshness.py`, `licensing.py`, `matching.py`, `exporters/`) must not import `google.*`.
- Identity verdicts, territory bands and coverage states are deterministic like risk scores — LLMs and detectors observe, pure code decides. A `CONFLICTED` identity blocks research; corroborator silence is `SINGLE_SOURCE`, never a conflict; coverage is `UNKNOWN` (not `NOT_COVERED`) whenever ownership or identity is unresolved.
- `<out>/state/` holds production JSON **and** `licences.json`. Never `glob("*.json")` it — use `LocalJsonStore.production_ids()`.
- Integration clients sit behind protocols with **fixture** and **live** implementations sharing one parser — demo mode (zero creds/network) exercises the identical code path. Fixtures: `src/clearframe/integrations/fixtures/`.
- ADK wrapper: `src/clearframe/adk/agents.py` (`SequentialAgent` of custom `StageAgent`s, google-adk 2.7).
- Review app: `src/clearframe/webapp/server.py` (FastAPI, server-side role gating, `asyncio.Lock` serializes all state saves) + `webapp/` React SPA (**prebuilt `webapp/dist` is committed** — rebuild with `npm run build` after any webapp/src change and commit dist).
- Spec: `docs/superpowers/specs/2026-08-15-clearframe-design.md`. Plans: `docs/superpowers/plans/`.

## Conventions

- TDD: failing test → implement → green → commit (one commit per task, `feat:`/`fix:`/`docs:`).
- Feature branches merged to `main` after the full suite passes twice (pre- and post-merge). `pytest` must stay green with dev-only install too (cloud-dependent tests use `pytest.importorskip`).
- Risk scores must stay reproducible from stored inputs. CSV text cells go through `exporters.safe_cell`.
- Timestamps come from callers/CLI, never inside builders (`as_of` is threaded into `licensing.assess`).
- Any change under `webapp/src/` needs `cd webapp && npm run build` and the `dist` diff committed.
- `scripts/smoke.sh` must stay green. Use its `has <needle> <curl args…>` helper for new checks — a bare `curl … | grep -q` races under `set -o pipefail` (grep exits first, curl dies of SIGPIPE 141).

## Status vs hackathon resources guide (updated 2026-08-22)

### Live-mode gotchas (hard-won — read before debugging live mode)

- **`gcloud auth login` ≠ `gcloud auth application-default login`.** The Python SDK uses ADC only. On 2026-08-22 ADC was authenticated as a *different Google account* (`sumitgeorgian3986@`) with zero IAM on the project, while `gcloud config` showed the owner — every Vertex call 403'd with "Permission 'aiplatform.locations.list' denied". Check identity with `curl "https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=$(gcloud auth application-default print-access-token)"`. Also set `gcloud auth application-default set-quota-project <PROJECT>`.
- **zsh eats `$VAR:` as a history modifier.** `"$M:generateContent"` expands to garbage (`5-pronerateContent`) and Google returns an **HTML 404 page** that reads exactly like "model not available". Always brace: `"${M}:generateContent"`.
- **Vertex REST is `v1beta1`**, not `v1` — the google-genai SDK targets v1beta1. A `v1` URL gives the same misleading HTML 404.
- **`gemini-3-pro-preview` genuinely 404s in this project** (clean JSON `NOT_FOUND` under correct auth, re-confirmed 2026-08-22). The coded fallback to `gemini-2.5-pro` is load-bearing: live runs are actually served by 2.5-pro.
- **Gemini video is the CHEAP option**: 258 tokens/second @ $1.25/M ≈ **$0.019/min**. A 90-min feature is ~$1.74/pass; Cloud Video Intelligence `LOGO_RECOGNITION` is $0.15/min (**7.8× more**). Never "optimise" the scan away from Gemini on cost grounds.
- **Parallel list prices** (docs.parallel.ai/getting-started/pricing, checked 2026-08-22): Search **$0.005/req**; Task per run lite $0.005 / base $0.010 / pro $0.100 / ultra $0.300. `planner.EST_COST` must track these — it was 10× high and Mission Control announced "$4.70" for a ~$0.40 run.
- **`.env` needs the dot.** A file named `env` is not gitignored; it showed as untracked with the live Parallel key in it. Verify with `git check-ignore -q .env`.

DONE:
- **Phase 8 (Aug 22, "Bring your own footage + rights ledger")**: footage upload (`POST /api/productions`, multipart, 512MB cap, extension whitelist; demo mode refuses with 409 rather than replaying fixtures as the user's results), `GET /api/productions/{pid}/media`, `<video>` player with per-frame bbox overlay + click-to-scrub, **rights ledger** (`licensing.py`, `LicenceStore`; COVERED/PARTIAL/NOT_COVERED/UNKNOWN with territory/term/media gap analysis — the WKRP problem), CSV+JSON ledger upload (`POST /api/licences`, role-gated), MCP `list_licences`/`check_coverage`, `scripts/fetch_test_clips.sh` (6 public-domain spots from archive.org/details/ctvc + ground truth), `docs/sample-rights-ledger.csv`. Demo ledger seeds 12 licences; the Adidas duffel has a matching grant (LIC-005) but disputed identity so it reads UNKNOWN. **Fixed**: uploaded ledgers without an id column were numbered by row position and silently overwrote seeded entries (`assign_ids`); state-dir globs picked up `licences.json` (`LocalJsonStore.production_ids()`). 161 tests, smoke green.
- **Phase 7 (Aug 22, "Verified Clearance")**: identity corroboration via Cloud Video Intelligence `LOGO_RECOGNITION` (`CORROBORATED`/`SINGLE_SOURCE`/`CONFLICTED`; conflicts block research), **Parallel Search API** live freshness pass (`POST /v1beta/search`, beta header `search-extract-2025-10-10`, ~$0.005/req — live-verified Aug 22) exposed as an on-demand button + `POST /api/productions/{pid}/freshness` + MCP `check_freshness`, territory-aware risk (freedom-of-panorama table, US/GB/DE/FR/JP/IN, cited statutes), bounding boxes on detections + `FramePosition` UI, `markers.csv` identity column, MCP tools `verify_identities`/`territory_report`/`check_freshness`. Demo scene 7 → 8 elements (Adidas duffel that the logo catalogue reads as Kappa). **Fixed**: `scan_script` pinned the video schema so live script pre-scan always returned 0 mentions and drift no-opped (live-verified 0 → 4); planner `EST_COST` was ~10x Parallel list price; `curl | grep` pipefail race in `smoke.sh`. 135 tests, smoke green.
- **Live validation (Aug 19)**: Google credits + Parallel API key arrived. Key lives in local `.env` (gitignored; load with `set -a && source .env && set +a`) and Secret Manager `parallel-api-key` (Cloud Run SA has accessor). **Live-proven**: Parallel Task API research (parser unchanged, real Basis citations), live Gemini video scan on Vertex (9 detections on Sintel trailer incl. 1s tattoo; `gemini-3-pro-preview` 404s here → coded fallback to `gemini-2.5-pro` works), E&O auditor second pass catches extra elements on real footage. **Fixed on keys-day**: FindAll rewritten to real run-based API (`POST /v1beta/findall/runs` → poll → `/result`, shared `parse_findall_result`, fixture in genuine API shape); Monitors beta is 401-gated for this key → live falls back to local stand-in watches (`local-{el}`), webhook flow identical. Public Cloud Run stays demo mode deliberately (unauth URL + live keys = open spend). 95 tests.
- **Phase 6 (Aug 15, cloud)**: deployed to **Cloud Run** (project configured via `gcloud config`, region us-central1, demo mode, `min-instances=0` scale-to-zero, `/tmp/out` ephemeral state): services `clearframe` (webapp) + `clearframe-mcp` (streamable HTTP at `/mcp`, stateless). One image in Artifact Registry repo `clearframe`; `cloudbuild.yaml` builds+deploys both. See `.claude/skills/deploy-cloud`. Live-mode flip = env vars + Secret Manager (keys pending). No credentials/personal data are committed — project id lives only in local gcloud config.
- **Phase 5 (Aug 15, "Living Clearance")**: script pre-scan + script-vs-screen drift (stages `script`/`drift`, 8 stages total), FindAll candidate enumeration for incomplete IP research, **standing clearance watch** (Parallel Monitors created post-dossier; webhook `/api/webhooks/parallel-monitor` reopens review + audit), court precedent quotes w/ source links, `scripts/smoke.sh` (full-transport smoke test — keep it green). Parallel surface now: Task+processors, FindAll, Monitor (+Search/Extract documented for live court, keys-day).
- **Phase 4 (Aug 15)**: Clearance Court (adversarial counsel/advocate/judge agents with real case-law fixtures — Ringgold, Sandoval, Rogers, Caterpillar, Falkner, VARA, §504(c); live = 3 Gemini persona calls, keys-day validation), E&O Auditor second scan pass (demo scene now **7 elements**), Budget Planner (Parallel processor tiers + rationale + est cost), Mission Control (SSE event stream + live agent roster UI; `?autorun` URL flag for demo recordings; paced demo runs via `POST /api/productions/demo {"pace_s": …}`).
- ADK native multi-agent pipeline (guide Phase 4) — built and tested; user-reachable via `--adk`.
- Gemini multimodal video analysis with timestamps (Phase 2) — **live-validated Aug 19** (real detections, sane prominence, fallback model chain proven).
- Partner integration via Parallel Task API REST (Phase 3) — **live-called Aug 19**, parser unchanged, real Basis citations.
- **clearframe-mcp server** (roadmap prong B): pipeline as 6 MCP tools, `python -m clearframe.mcp`, mcp SDK v2, fully tested in-process.
- **Guardrails**: Gemini safety settings (BLOCK_ONLY_HIGH ×4), research spend cap (`CLEARFRAME_MAX_RESEARCH`), Parallel retry+backoff, append-only audit trail (in dossier too), shared `review.py` service (webapp+MCP use identical rules).
- Cloud Run collateral: Dockerfile + docs/deploy.md incl. Secret Manager + MCP registration (Phase 5) — written, not deployed; Docker build unverified.
- `deploy` extra: `google-cloud-aiplatform[agent_engines,adk]>=1.101.0` (dry-run resolved clean against google-adk 2.7).

NOT DONE:
- **Audio verification (highest-value remaining gap).** Music IS handled — `MUSIC_SYNC`, highest category weight (1.0), `pro` research tier, ASCAP/BMI cue sheet — but identification is Gemini listening and naming a track, and `corroboration.CORROBORATABLE` excludes `MUSIC_SYNC`, so every song is permanently `SINGLE_SOURCE`. That title flows into a cue sheet, which is a **legal filing to a PRO**. Fix = audio fingerprinting (ACRCloud / AudD / AcoustID) behind a new client protocol with a fixture twin, then add `MUSIC_SYNC` to `CORROBORATABLE`. Needs a third-party API key — the only feature so far that does.
- Parallel **managed MCP server** as research transport (roadmap prong A). Re-verified live 2026-08-22: `https://task-mcp.parallel.ai/mcp` → `Parallel Task MCP 1.0.5`, tools `createDeepResearch · createTaskGroup · getStatus · getResultMarkdown`. Their docs confirm **markdown-only output, no custom output schemas, no processor tiers, no FindAll**. Deliberately NOT adopted: it would delete `parse_task_output`, make the Budget Planner meaningless, and kill the FindAll mural lead. If judges weight managed adapters, add it as a THIRD `ParallelClient` implementation behind `CLEARFRAME_RESEARCH_TRANSPORT=direct|mcp` — never as the default.
- Parallel Monitors live (beta gated for this key — 401 product-unavailable; local stand-in fallback shipped instead).
- Agent Engine deployment (Cloud Run is the live surface; Agent Engine optional stretch).
- Real frame stills in the dossier (ffmpeg not installed locally; `FramePosition` renders box geometry without footage as the stand-in).
- Video player never exercised against real footage — component typechecks/builds and is wired, but no clip has been uploaded through it. Run `./scripts/fetch_test_clips.sh` then upload in live mode.
- Firestore / Pub/Sub / IAP; multi-production dossier paths still collide (artifacts write flat to `out_root`).
- User-side: salted demo scene shoot, 3-min video, deadline verification on Devpost (Sep 7 vs Sep 10 conflict), repo flip to public, Devpost form.

NOT USED (deliberate — out of scope for clearance): Imagen, Lyria, TTS, Live API streaming, BigQuery RAG, MCP Database Toolbox. Possible stretch if time allows: script-clearance pre-scan (parse screenplay PDF for flaggable items before the shoot — real industry workflow, uses guide's document processing).

## Roadmap (agreed direction)

1. **Live validation** (first, once keys exist): `/live-validate` skill.
2. **MCP** (two prongs, both planned):
   - Integrate **Parallel's official Task MCP server** as the research transport (brief rewards "managed protocol adapters"; Parallel's judges built it).
   - Ship **`clearframe-mcp`**: an MCP server exposing `scan_footage`, `research_rights`, `list_findings`, `record_decision`, `get_dossier` so any MCP client (Gemini Enterprise, Claude) can drive clearance. New plan doc before building.
3. ~~**Webapp expansion**: footage upload + `<video>` player~~ — DONE Phase 8 (upload, media serving, player with bbox overlay). Still open: multi-production dashboard, IAP-backed roles.
4. **Audio fingerprinting** — the remaining correctness gap (see NOT DONE). Needs a user-supplied key.
5. Cloud wiring: Firestore store (same repository interface as `LocalJsonStore`), Pub/Sub for Parallel webhooks, Agent Engine deploy.
6. Submission: `/submission-preflight` skill before Devpost.

## Competitive positioning (market research 2026-08-22)

The one-line pitch: **Content ID finds *your* IP in *other people's* video; ClearFrame finds *other people's* IP in *your* video — before you ship.** The incumbents solve the inverse problem and none serve production-side visual clearance:

| Segment | Players | Gap |
| --- | --- | --- |
| Content ID / ACR | Vobile, Pex (acquired Apr 2025), Audible Magic | enforcement-side, for platforms |
| Cue-sheet automation | Soundmouse / Orfium (claims 83% admin cut) | music only |
| Rights & contract mgmt | Rightsline, FilmTrack, FADEL | manages licences you already hold; cannot discover what you need |
| Human clearance | The Clearance Lab, Media Research & Clearances Inc | people, hourly |

Our differentiators, in order of defensibility: corroborated identity (nobody markets "we don't guess at brands"), the rights ledger closing detection↔licences-held, territory-aware banding, live enforcement signals.

## Commands

- Demo pipeline: `python -m clearframe run --demo --out out --auto-approve`
- Live run: `set -a && source .env && set +a` then `python -m clearframe run --live --footage clip.mp4 --duration-s 60 --territories US,DE,FR --out out-live`
- Review app: `python -m clearframe serve --out out --port 8000`
- MCP: `python -m clearframe.mcp --out out` (stdio) · `--transport http --port 8080`
- Tests: `.venv/bin/pytest -q` (161) · Smoke: `bash scripts/smoke.sh` · Frontend: `cd webapp && npm run build`
- Test footage: `./scripts/fetch_test_clips.sh` (6 public-domain spots + ground truth)
- Sample ledger to upload: `docs/sample-rights-ledger.csv`

## Environment facts (this machine, 2026-08-22)

- GCP project `original-future-505614-p7` (number 220710110855 — matches the Cloud Run URLs). Enabled: aiplatform, run, secretmanager, cloudbuild, artifactregistry, **videointelligence** (enabled 2026-08-22 for corroboration).
- `.env` (gitignored) holds `CLEARFRAME_MODE=live`, project, location, `PARALLEL_API_KEY`. **Not** set: `CLEARFRAME_TERRITORIES` — live runs default to US-only unless added.
- Parallel key also lives in Secret Manager as `parallel-api-key`; the same key authenticates the Search API.
- `.venv` is Python 3.14; `[dev,cloud]` installs clean (google-genai 2.19, google-adk 2.7.1, google-cloud-videointelligence).
- Deployed Cloud Run services are **demo mode** and have no `PARALLEL_API_KEY` bound — the public URL makes no Parallel calls. Flipping live = the `deploy-cloud` skill's update command.
- ffmpeg is NOT installed (blocks real frame stills).
