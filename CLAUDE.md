# ClearFrame — Project Context

Autonomous rights-clearance department for film & TV. Google Cloud "Agentic Cinema" hackathon, **Parallel track**, deadline **Sep 10 2026, 2:30am IST**. Devpost judging: tech implementation, complete product (not PoC), credible impact, non-obvious idea.

## Architecture (read before editing)

Deterministic 6-stage pipeline: **scan** (Gemini video, Vertex) → **triage** (rules+dedupe) → **research** (Parallel Task API fan-out, Basis citations = audit trail) → **risk** (pure-code rubric in `scoring.py` — NEVER an LLM) → **remediation** (template drafts) → human review → **dossier** (E&O report + EDL/CSV markers + cue sheet).

- Core (`models.py`, `scoring.py`, `triage.py`, `pipeline.py`, `exporters/`) must not import `google.*`.
- Integration clients sit behind protocols with **fixture** and **live** implementations sharing one parser — demo mode (zero creds/network) exercises the identical code path. Fixtures: `src/clearframe/integrations/fixtures/`.
- ADK wrapper: `src/clearframe/adk/agents.py` (`SequentialAgent` of custom `StageAgent`s, google-adk 2.7).
- Review app: `src/clearframe/webapp/server.py` (FastAPI, server-side role gating, `asyncio.Lock` serializes all state saves) + `webapp/` React SPA (**prebuilt `webapp/dist` is committed** — rebuild with `npm run build` after any webapp/src change and commit dist).
- Spec: `docs/superpowers/specs/2026-08-15-clearframe-design.md`. Plans: `docs/superpowers/plans/`.

## Conventions

- TDD: failing test → implement → green → commit (one commit per task, `feat:`/`fix:`/`docs:`).
- Feature branches merged to `main` after the full suite passes twice (pre- and post-merge). `pytest` must stay green with dev-only install too (cloud-dependent tests use `pytest.importorskip`).
- Risk scores must stay reproducible from stored inputs. CSV text cells go through `exporters.safe_cell`.
- Timestamps come from callers/CLI, never inside builders.

## Status vs hackathon resources guide (updated 2026-08-15)

DONE:
- **Phase 6 (Aug 15, cloud)**: deployed to **Cloud Run** (project configured via `gcloud config`, region us-central1, demo mode, `min-instances=0` scale-to-zero, `/tmp/out` ephemeral state): services `clearframe` (webapp) + `clearframe-mcp` (streamable HTTP at `/mcp`, stateless). One image in Artifact Registry repo `clearframe`; `cloudbuild.yaml` builds+deploys both. See `.claude/skills/deploy-cloud`. Live-mode flip = env vars + Secret Manager (keys pending). No credentials/personal data are committed — project id lives only in local gcloud config.
- **Phase 5 (Aug 15, "Living Clearance")**: script pre-scan + script-vs-screen drift (stages `script`/`drift`, 8 stages total), FindAll candidate enumeration for incomplete IP research, **standing clearance watch** (Parallel Monitors created post-dossier; webhook `/api/webhooks/parallel-monitor` reopens review + audit), court precedent quotes w/ source links, `scripts/smoke.sh` (full-transport smoke test — keep it green). Parallel surface now: Task+processors, FindAll, Monitor (+Search/Extract documented for live court, keys-day).
- **Phase 4 (Aug 15)**: Clearance Court (adversarial counsel/advocate/judge agents with real case-law fixtures — Ringgold, Sandoval, Rogers, Caterpillar, Falkner, VARA, §504(c); live = 3 Gemini persona calls, keys-day validation), E&O Auditor second scan pass (demo scene now **7 elements**), Budget Planner (Parallel processor tiers + rationale + est cost), Mission Control (SSE event stream + live agent roster UI; `?autorun` URL flag for demo recordings; paced demo runs via `POST /api/productions/demo {"pace_s": …}`).
- ADK native multi-agent pipeline (guide Phase 4) — built and tested.
- Gemini multimodal video analysis with timestamps (Phase 2) — coded; live quality NOT yet validated.
- Partner integration via Parallel Task API REST (Phase 3) — fixture-proven; live NOT yet called.
- **clearframe-mcp server** (roadmap prong B): pipeline as 6 MCP tools, `python -m clearframe.mcp`, mcp SDK v2, fully tested in-process.
- **Guardrails**: Gemini safety settings (BLOCK_ONLY_HIGH ×4), research spend cap (`CLEARFRAME_MAX_RESEARCH`), Parallel retry+backoff, append-only audit trail (in dossier too), shared `review.py` service (webapp+MCP use identical rules).
- Cloud Run collateral: Dockerfile + docs/deploy.md incl. Secret Manager + MCP registration (Phase 5) — written, not deployed; Docker build unverified.
- `deploy` extra: `google-cloud-aiplatform[agent_engines,adk]>=1.101.0` (dry-run resolved clean against google-adk 2.7).

NOT DONE (blocked on credentials/user):
- GCP project + $100 credit form + Parallel API key (Phase 1/3 forms).
- First live Gemini scan + prompt tuning; first live Parallel research run.
- Parallel **managed MCP server** as research transport (roadmap prong A — needs real auth to verify).
- Agent Engine deployment, Cloud Run deploy, Secret Manager provisioning.

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
