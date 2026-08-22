# ClearFrame — Project Context

Autonomous rights-clearance department for film & TV. Google Cloud "Agentic Cinema" hackathon, **Parallel track**, deadline **Sep 10 2026, 2:30am IST**. Devpost judging: tech implementation, complete product (not PoC), credible impact, non-obvious idea.

## Architecture (read before editing)

Deterministic 11-stage pipeline: **script** (pre-scan) → **scan** (Gemini video, Vertex) → **triage** (rules+dedupe) → **corroborate** (independent logo catalogue confirms identity) → **drift** (script vs screen) → **research** (Parallel Task API fan-out, Basis citations = audit trail) → **freshness** (Parallel Search, live enforcement check) → **risk** (pure-code rubric in `scoring.py` — NEVER an LLM) → **territory** (per-jurisdiction bands) → **remediation** (template drafts) → **court** → human review → **dossier** (E&O report + EDL/CSV markers + cue sheet). `ANALYSIS_STAGES` in `pipeline.py` is the source of truth.

- Core (`models.py`, `scoring.py`, `triage.py`, `pipeline.py`, `corroboration.py`, `territory.py`, `freshness.py`, `matching.py`, `exporters/`) must not import `google.*`.
- Identity verdicts and territory bands are deterministic like risk scores — LLMs and detectors observe, pure code decides. A `CONFLICTED` identity blocks research; corroborator silence is `SINGLE_SOURCE`, never a conflict.
- Integration clients sit behind protocols with **fixture** and **live** implementations sharing one parser — demo mode (zero creds/network) exercises the identical code path. Fixtures: `src/clearframe/integrations/fixtures/`.
- ADK wrapper: `src/clearframe/adk/agents.py` (`SequentialAgent` of custom `StageAgent`s, google-adk 2.7).
- Review app: `src/clearframe/webapp/server.py` (FastAPI, server-side role gating, `asyncio.Lock` serializes all state saves) + `webapp/` React SPA (**prebuilt `webapp/dist` is committed** — rebuild with `npm run build` after any webapp/src change and commit dist).
- Spec: `docs/superpowers/specs/2026-08-15-clearframe-design.md`. Plans: `docs/superpowers/plans/`.

## Conventions

- TDD: failing test → implement → green → commit (one commit per task, `feat:`/`fix:`/`docs:`).
- Feature branches merged to `main` after the full suite passes twice (pre- and post-merge). `pytest` must stay green with dev-only install too (cloud-dependent tests use `pytest.importorskip`).
- Risk scores must stay reproducible from stored inputs. CSV text cells go through `exporters.safe_cell`.
- Timestamps come from callers/CLI, never inside builders.

## Status vs hackathon resources guide (updated 2026-08-19)

DONE:
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
- Parallel **managed MCP server** as research transport (roadmap prong A). Verified reachable Aug 19: `https://task-mcp.parallel.ai/mcp` authenticates with our key (`x-api-key` header) and handshakes (tools `createDeepResearch`, `createTaskGroup`). Deliberately NOT adopted as the research transport: our direct Task API integration is live-proven and strictly richer (custom output schemas, processor tiers, FindAll) — the MCP tools expose only generic research. Decision stands unless judges weight managed adapters heavily.
- Parallel Monitors live (beta gated for this key — 401 product-unavailable; local stand-in fallback shipped instead).
- Agent Engine deployment (Cloud Run is the live surface; Agent Engine optional stretch).
- User-side: salted demo scene shoot, 3-min video, deadline verification on Devpost (Sep 7 vs Sep 10 conflict), repo flip to public, Devpost form.

NOT USED (deliberate — out of scope for clearance): Imagen, Lyria, TTS, Live API streaming, BigQuery RAG, MCP Database Toolbox. Possible stretch if time allows: script-clearance pre-scan (parse screenplay PDF for flaggable items before the shoot — real industry workflow, uses guide's document processing).

## Roadmap (agreed direction)

1. **Live validation** (first, once keys exist): `/live-validate` skill.
2. **MCP** (two prongs, both planned):
   - Integrate **Parallel's official Task MCP server** as the research transport (brief rewards "managed protocol adapters"; Parallel's judges built it).
   - Ship **`clearframe-mcp`**: an MCP server exposing `scan_footage`, `research_rights`, `list_findings`, `record_decision`, `get_dossier` so any MCP client (Gemini Enterprise, Claude) can drive clearance. New plan doc before building.
3. **Webapp expansion**: footage upload + `<video>` player synced to the clearance timeline, multi-production dashboard, IAP-backed roles on Cloud Run.
4. Cloud wiring: Firestore store (same repository interface as `LocalJsonStore`), Pub/Sub for Parallel webhooks, Agent Engine deploy.
5. Submission: `/submission-preflight` skill before Devpost.

## Commands

- Demo pipeline: `python -m clearframe run --demo --out out --auto-approve`
- Review app: `python -m clearframe serve --out out --port 8000`
- Tests: `.venv/bin/pytest -q` · Frontend rebuild: `cd webapp && npm run build`
