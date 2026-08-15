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
- ADK native multi-agent pipeline (guide Phase 4) — built and tested.
- Gemini multimodal video analysis with timestamps (Phase 2) — coded; live quality NOT yet validated.
- Partner integration via Parallel Task API REST (Phase 3) — fixture-proven; live NOT yet called.
- Cloud Run collateral: Dockerfile + docs/deploy.md incl. Secret Manager commands (Phase 5) — written, not deployed; Docker build unverified.

NOT DONE (blocked on credentials/user):
- GCP project + $100 credit form + Parallel API key (Phase 1/3 forms).
- First live Gemini scan + prompt tuning; first live Parallel research run.
- Agent Engine deployment (guide recommends `pip install "google-cloud-aiplatform[agent_engines,adk]>=1.101.0"` — add to `cloud` extra when deploying).
- Cloud Run deploy + Secret Manager provisioning.
- Gemini safety settings on the live client (small code task — add `safety_settings` to `GenerateContentConfig` in `gemini_live.py` when touching it).

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
