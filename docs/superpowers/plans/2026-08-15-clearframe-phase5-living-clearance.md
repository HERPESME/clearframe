# ClearFrame Phase 5 Implementation Plan — Living Clearance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen Parallel API usage from Task-only to the full surface (FindAll, Monitor, Search/Extract) and extend ClearFrame across the production lifecycle: script pre-scan → footage scan → script-vs-screen drift → research with candidate enumeration → dossier → **standing clearance watch** that reopens review when the outside world changes. Ship a one-command smoke test (`scripts/smoke.sh`).

**Architecture:** All features slot behind existing protocols with fixture/live pairs. `ParallelClient` gains `find_all` (candidate rights-holder enumeration for incomplete research) and `create_monitor` (standing watch, created post-dossier); the webapp gains a Parallel-monitor webhook that reopens review (reusing the stale-dossier machinery + audit trail). `GeminiClient` gains `scan_script`; two new pipeline stages (`script`, `drift`) bracket the existing scan/triage. Court precedents gain Extract-style quotes (`quote`, `source_url`); the live court documents the Search→Extract precedent path for keys-day.

**Spec:** competitive analysis conversation 2026-08-15 (absorb ClearVault's Monitor/FindAll USPs; full-lifecycle differentiation).

## Global Constraints

- All prior constraints hold. Demo scene stays 7 elements. Deterministic scores untouched by any new feature.
- New live-API endpoints are best-effort with `TODO(keys-day)` verification notes; fixtures carry the demo and tests.
- Watch alerts must flow through the existing reopen+audit machinery, never a parallel path.

### Task 1: Models

`Production.script_uri: str|None = None`. `Precedent` += `quote: str = ""`, `source_url: str = ""`. New: `ScriptMention(label, element_type, scene)`, `ScriptDrift(unscripted_element_ids: list[str], scripted_not_seen: list[str])`, `CandidateEntity(name, kind, url, note)`, `ClearanceWatch(element_id, monitor_id, query, frequency)`, `WatchAlert(element_id, monitor_id, at, summary, source_url)`. `ProductionState` += `script_mentions: list[ScriptMention]`, `drift: ScriptDrift|None`, `candidates: dict[str, list[CandidateEntity]]`, `watches: dict[str, ClearanceWatch]`, `alerts: list[WatchAlert]` (all defaulted). Round-trip test.

### Task 2: Script pre-scan + drift stages

- Fixtures: `fixtures/script/golden-hour.txt` (scene pages mentioning the Coke can, the song cue, the poster — NOT the hoodie/mural/TV) + `fixtures/script_scan.json` (mentions: Coca-Cola can/LOGO, Blinding Lights/MUSIC, tour poster/ARTWORK).
- `GeminiClient.scan_script(text) -> list[ScriptMention]`; fixture loads JSON; live = text-only Gemini call with `SCRIPT_PROMPT` + schema.
- `ScriptStage` ("script", first): resolves `script_uri` (`demo://` → bundled fixture; local path → read), stores mentions, emits `script_mentions`.
- `drift.py::compute_drift(mentions, elements)` — casefolded token overlap match; FACE excluded (people aren't props). Demo expectation: unscripted = {e3 hoodie, e5 mural, e7 TV}; scripted_not_seen = [].
- `DriftStage` ("drift", after triage) stores drift, emits `drift_computed`.
- `ANALYSIS_STAGES = ("script","scan","triage","drift","research","risk","remediation","court")`; demo production gets `script_uri="demo://golden-hour-script"`. Update event-count test (8 stages).

### Task 3: FindAll candidate enumeration

- `ParallelClient.find_all(element, production_title) -> list[CandidateEntity]`; fixture loads `fixtures/findall/{slug}.json` (missing → []); live posts to the FindAll beta endpoint (`TODO(keys-day)`).
- Fixture for the mural: 3 candidates (mural-registry org, building owner via assessor records, local artist collective) with kind/url/note.
- `ResearchStage`: after gather, for elements with incomplete research AND category in {COPYRIGHT_ART, TRADEMARK, MUSIC_SYNC} → `find_all` → `state.candidates[el.id]`, emit `candidates_found`. Tests: mural gets 3 candidates; face gets none.

### Task 4: Standing clearance watch + webhook reopen

- `ParallelClient.create_monitor(element_id, query, frequency, webhook_url) -> ClearanceWatch|None`; fixture returns deterministic `mon-{element_id}`; live `TODO(keys-day)`.
- `review.generate_dossier_async`: after dossier, create watches for elements whose court holding is `clear_required`/`escalate`, whose research is incomplete, or whose owner posture is litigious — query text describes what to watch (new litigation/filings by owner; artist identification for unknowns). Store in `state.watches`, audit event `watch_created` per watch.
- Webapp `POST /api/webhooks/parallel-monitor` body `{monitor_id, summary, source_url}`: locate watch → append `WatchAlert`, reopen review (`stage_status["review"]="awaiting"`), audit `watch_alert`, save; 404 unknown monitor. Tests: dossier creates ≥3 watches; webhook reopens review + appends alert; unknown monitor 404.
- MCP `get_status` includes `watches` count + `alerts`.

### Task 5: Court quotes (Extract shape)

Update the five court fixtures: key precedents gain `quote` (short verbatim-style passage) + `source_url` (case-law reference URL). Dossier HTML + review UI render the quote as a pull-quote with link. `LiveCourtClient` docstring documents the keys-day Search→Extract enrichment path. Test: dossier HTML contains a Ringgold quote text.

### Task 6: UI — lifecycle surfaces

Mission Control: add "Script Reader" agent card (script stage events) and drift line on Triage card; candidates rows on the researcher card. Review screen: `NOT IN SCRIPT` badge on unscripted elements + drift summary chip; candidates list under incomplete research ("Possible rights holders — FindAll"); watch banner section after dossier generation ("Standing watch active on N findings"); alert banner when `alerts` non-empty ("⚠ watch alert — review reopened"). Court briefs show precedent quotes. Rebuild dist, screenshot.

### Task 7: Smoke test + docs + merge

- `scripts/smoke.sh` (bash, set -euo pipefail, PASS/FAIL lines): pytest; CLI demo run → artifact + content greps (Court, Audit trail, cue sheet); serve on :8399 → paced run → SSE stream check → role-gated decision flow via curl (editor 403, legal 200 ×7) → dossier 200 → artifacts fetch → **webhook alert → verify review reopened** → MCP stdio initialize handshake; cleanup; summary.
- README (Living Clearance section, lifecycle diagram), CLAUDE.md status, devpost/video-script beats (watch-alert demo beat), memory. Full suite, merge to main, push.

## Self-Review

Monitor/FindAll/script features all reuse existing seams (protocols, reopen machinery, audit log, emit). Stage count changes are confined to Task 2's test updates. Live endpoints are explicitly TODO-flagged, consistent with project honesty policy. The smoke script exercises every transport (CLI, HTTP, SSE, webhook, MCP stdio) — the "check what you built" deliverable.
