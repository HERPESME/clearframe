# ClearFrame Phase 3 Implementation Plan — MCP Server + Guardrails

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `clearframe-mcp` — an MCP server exposing the clearance pipeline as tools for any MCP client — and harden the pipeline with production guardrails (Gemini safety settings, research spend cap, Parallel retry, append-only audit trail), plus a shared review service so webapp/MCP/CLI stop duplicating decision logic.

**Architecture:** A new `review.py` service module owns decision recording + dossier generation (role checks, review reopening, audit appends); the FastAPI app and the MCP server both call it. The MCP server (`mcp` SDK v2, `MCPServer` + `@tool()`) wraps the same stores/pipeline as everything else; stdio transport via `python -m clearframe.mcp`. Guardrails slot into existing seams: safety settings in `LiveGeminiClient`'s config, the research cap in `ResearchStage`, retries in `LiveParallelClient`.

**Tech Stack:** `mcp>=2.0` (added to main deps), existing stack otherwise.

**Spec:** roadmap §2 of `CLAUDE.md` + `docs/superpowers/specs/2026-08-15-clearframe-design.md` §6 (error policy), §4 (append-only decisions).

## Global Constraints

- All Phase-1/2 constraints hold. Audit events are append-only; timestamps come from the transport layer (webapp/MCP/CLI), never from builders.
- MCP tool results are plain JSON-able dicts; errors raise `ValueError` with actionable messages (SDK surfaces them as `is_error`).
- Role gating identical across webapp and MCP: only `legal`/`producer` record decisions.

### Task 1: Gemini safety settings (guide Phase 5)

**Files:** Modify `src/clearframe/integrations/gemini_live.py`; Test `tests/test_gemini_live.py`

- `_scan_config()` helper returns `GenerateContentConfig(response_mime_type, response_schema, safety_settings=[...])` — `BLOCK_ONLY_HIGH` for the four harm categories (footage analysis must not refuse on mild content but blocks extremes). Fake-client test asserts the captured config carries 4 safety settings.

### Task 2: Research cap + Parallel retry

**Files:** Modify `src/clearframe/stages/research.py`, `src/clearframe/integrations/parallel_client.py`, `src/clearframe/pipeline.py`; Tests `tests/test_pipeline.py`, `tests/test_parallel_client.py`

- `ResearchStage(max_research: int = 25)`: elements sorted by `prominence.screen_time_s` desc; beyond the cap get incomplete results (owner None) so they surface honestly in review. `build_demo_pipeline(max_research=...)` plumbs it; default read from `CLEARFRAME_MAX_RESEARCH` env in `build_context`/CLI. Test: cap=2 on demo → exactly 2 complete-capable, 4 incomplete.
- `LiveParallelClient(attempts: int = 2)`: extract `_research_once`; retry loop catches `httpx.HTTPError` with 2s backoff between attempts. Test: stub instance whose `_research_once` raises once then succeeds → result returned, 2 calls.

### Task 3: Audit trail + shared review service

**Files:** Modify `src/clearframe/models.py` (`AuditEvent`, `ProductionState.audit_log`), `src/clearframe/exporters/dossier_html.py` (audit section); Create `src/clearframe/review.py`; Modify `src/clearframe/webapp/server.py` (delegate to service); Tests `tests/test_review.py`, extend `tests/test_webapp.py`, `tests/test_dossier.py`

- `review.record_decision(store, pid, element_id, action, note, role, reviewer, at) -> ProductionState`: raises `RoleNotPermittedError` / `UnknownElementError` (new exceptions in `review.py`); writes Decision, reopens review if complete, appends `AuditEvent(at, actor=reviewer, role, event="decision", detail=f"{element_id}:{action}")`, saves.
- `review.generate_dossier_for(store, out_root, pid, at) -> list[str]`: runs DossierStage (propagates `ReviewPendingError`), appends `AuditEvent(event="dossier_generated")`, saves, returns artifacts.
- Webapp endpoints shrink to HTTP translation of service calls. Dossier HTML gains an "Audit trail" section listing events.

### Task 4: MCP server

**Files:** Create `src/clearframe/mcp/__init__.py`, `src/clearframe/mcp/server.py`, `src/clearframe/mcp/__main__.py`; Modify `pyproject.toml` (add `mcp>=2.0`); Test `tests/test_mcp_server.py`

- `build_server(out_root: Path) -> MCPServer` registering six tools (all docstringed — docstrings are the client-visible descriptions):
  - `run_clearance(footage_uri, title, production_id, duration_s, fps)` — `demo://` → fixtures; else live config from env (missing vars → ValueError naming them). Runs analysis stages; returns findings summary (counts per band, pending ids).
  - `get_status(production_id)`, `list_findings(production_id)`, `get_finding(production_id, element_id)` (full evidence incl. basis citations + remediation), `record_decision(production_id, element_id, action, note, role)` (via review service; reviewer="mcp"), `generate_dossier(production_id)` (pending → ValueError listing ids).
- `python -m clearframe.mcp --out out` → `run_stdio_async`.
- Tests exercise tools in-process via `server.call_tool(...)`: full demo flow (run → list → decide ×6 → dossier → artifacts on disk), editor role → `is_error`, unknown production → `is_error`.

### Task 5: Deploy extra + docs

**Files:** Modify `pyproject.toml` (`deploy` extra: `google-cloud-aiplatform[agent_engines,adk]>=1.101.0` — verify it co-installs with google-adk 2.7; if it conflicts, document in deploy.md instead), `docs/deploy.md` (MCP registration section — Gemini Enterprise / Claude Code client config), `README.md` (MCP quickstart + guardrails), `CLAUDE.md` (status tracker).

## Self-Review

Covers roadmap MCP prong B fully; prong A (consuming Parallel's managed MCP server as transport) intentionally deferred until live keys exist — it replaces REST inside `parallel_client` and needs real auth to verify. Guardrails cover guide Phase 5 items achievable without credentials. No placeholders; MCP SDK API verified in-process before planning.
