# ClearFrame Phase 4 Implementation Plan — Clearance Court, Self-Audit, Mission Control, Budget Planner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClearFrame read as a genuine multi-agent system: an adversarial Clearance Court (Studio Counsel vs Fair Use Advocate vs Judge, arguing real case law per contested finding), a second scan agent auditing the first for misses, a research Budget Planner allocating Parallel processor tiers with rationale, and a live Mission Control view streaming agent activity to the webapp.

**Architecture:** New `CourtStage` after remediation (contested = MEDIUM+ band) behind a `CourtClient` protocol (fixture: authored case files with real precedent; live: Gemini persona calls). `ScanStage` gains an audit pass via `GeminiClient.audit_scan`. `ResearchStage` gains a deterministic planner assigning Parallel processor tiers (live-mode Gemini planner is keys-day). Pipeline stages emit events through a `PipelineContext.emit` hook; the webapp exposes them as SSE and renders the Mission Control roster; demo runs accept a pacing parameter so fixture-speed runs remain watchable (presentation pacing, documented, not fake work).

**Tech Stack:** existing stack; SSE via Starlette `StreamingResponse`.

**Spec:** brainstorm decisions in conversation 2026-08-15 + CLAUDE.md roadmap. Demo scene grows to **7 elements** (audit finds e7 "News broadcast on background TV").

## Global Constraints

- All prior constraints hold. Court opinions NEVER alter the deterministic risk score — they attach reasoning; the human still decides.
- Demo fixtures must cite **real case law accurately** (Ringgold v. BET, Sandoval v. New Line Cinema, Rogers v. Grimaldi, Caterpillar v. Walt Disney, 17 U.S.C. §504(c) statutory damages, VARA) — legal literacy is a judging asset; sloppy citations are a liability.
- Tests asserting 6 demo elements update to 7 deliberately (pipeline, webapp, MCP, CLI).

### Task 1: Models for court + planner

`models.py` additions: `Precedent(case_name, citation, holding, relevance)`, `BriefSide = Literal["counsel","advocate"]`, `Brief(side, argument: str, precedents: list[Precedent])`, `CourtHolding = Literal["clear_required","defensible","escalate"]`, `CourtOpinion(element_id, holding, confidence: Literal["low","medium","high"], reasoning, briefs: list[Brief])`, `ResearchPlan(element_id, processor: Literal["lite","base","pro","ultra"], rationale, est_cost_usd: float)`. `ProductionState` gains `court: dict[str, CourtOpinion]` and `research_plan: dict[str, ResearchPlan]` (default empty). Tests: round-trip serialization.

### Task 2: Scan self-audit (demo scene → 7 elements)

- `GeminiClient` protocol gains `audit_scan(footage_uri, duration_s, found_labels: list[str]) -> ScanResult`. `AUDIT_PROMPT` in `gemini_client.py`: "you are the studio's E&O auditor; the first coordinator found these elements: …; report ONLY elements they missed."
- Fixture `demo_scene_audit.json`: one element `e7` "News broadcast on background TV" (ARTWORK, 50–53s, st 3.0, cov 0.06, cen 0.3, plot false → LOW ~12) + research fixture `news-broadcast-on-background-tv.json` (owner "KTLA-style local station affiliate" → generic "Local broadcast affiliate (KXBC-7)", standard posture, complete).
- `ScanStage`: primary scan → audit_scan with found labels → merge detections + unscanned ranges. `LiveGeminiClient.audit_scan` mirrors `scan` with AUDIT_PROMPT.
- Update count assertions 6→7 across tests; dossier `incomplete_research` stays 2; CRITICAL stays 1.

### Task 3: Budget planner in ResearchStage

- `planner.py`: `plan_research(elements) -> dict[str, ResearchPlan]` — deterministic policy with recorded rationale: MUSIC_SYNC → `pro` ("ownership chains split composition/master"); ARTWORK with unknown-ish label (contains "unknown"/no proper noun) → `ultra`; well-known LOGO → `lite` ("famous mark, ownership trivial"); default → `base`. `EST_COST = {"lite":0.05,"base":0.20,"pro":1.00,"ultra":3.00}` (indicative, constant-documented).
- `ResearchStage` stores plan in state, passes `processor` to `ParallelClient.research(el, title, processor=...)` (fixture ignores; `LiveParallelClient` uses per-call, overriding constructor default). Cap unchanged. Tests: plan tiers for demo scene (e1→pro, e5→ultra, e2/e3→lite, e4/e7→base, e6→base), total est cost computed.

### Task 4: Clearance Court

- `CourtCase` dataclass (element, research, risk, production). `CourtClient` protocol: `async def try_case(case) -> CourtOpinion | None` (None = no case file → skip, court is best-effort).
- `FixtureCourtClient(fixtures_dir)`: loads `court/{slug(label)}.json` = `{"briefs":[{side,argument,precedents:[…]},…], "opinion":{holding,confidence,reasoning}}`.
- Five authored case files (real precedent): e1 song → counsel cites §504(c) willful statutory damages + no de-minimis for plot-integral sync; advocate weak diegetic argument; **clear_required/high**. e3 swoosh → advocate cites Rogers v. Grimaldi expressive-work defense; counsel cites Nike v. MSCHF enforcement; **escalate/medium** ("defensible under Rogers; blur cheaper than a fight with Nike"). e2 can → advocate cites Caterpillar v. Walt Disney (court refused to enjoin product depiction) + incidental prop; **defensible/medium**. e4 poster → counsel cites Ringgold v. BET (26.75s poster = infringement); advocate cites Sandoval v. New Line (fleeting/out-of-focus de minimis); 5s clear view sits between → **clear_required/medium**. e5 mural → counsel: mural copyright + VARA + untraceable owner is uninsurable; **escalate/high**.
- `CourtStage` (name "court", appended to ANALYSIS_STAGES after remediation): gathers cases for MEDIUM+ bands, `asyncio.gather` try_case, stores non-None in `state.court`.
- `LiveCourtClient(project, location, model)`: three Gemini calls per case (counsel persona, advocate persona, judge with both briefs), JSON structured output matching the fixture shape; tested with fake client factory (happy path only); Parallel-powered precedent enrichment marked keys-day TODO in docstring.
- Dossier HTML: court section per entry (both briefs with precedent lists, ruling banner colored by holding). Webapp/MCP: court opinion included in element card / `get_finding`.
- Tests: fixture client parses e1 file; CourtStage produces 5 opinions on demo scene, none for e6/e7; dossier HTML contains "Ringgold"; MCP get_finding exposes opinion.

### Task 5: Event stream + SSE

- `PipelineContext` gains `listener: Callable[[dict],None]|None`; `emit(event: dict)` no-ops without listener. `Pipeline.run` emits `stage_start`/`stage_complete` (+`skipped`). `ResearchStage` emits `research_start/research_done` per element (label, processor); `CourtStage` emits `case_opened/case_ruled` (label, holding); `ScanStage` emits `scan_found` counts + `audit_found`.
- Webapp: `POST /api/productions/demo` accepts optional JSON body `{"pace_s": float}` (default 0 → current synchronous behavior, existing tests untouched). With `pace_s>0`: starts a background task that runs the pipeline with `asyncio.sleep(pace_s)` between events, returns `{"status":"running"}` immediately. `GET /api/productions/demo/events` → SSE (`text/event-stream`) draining a per-run `asyncio.Queue`, ending with `run_complete`. Tests: pace 0 sync unchanged; SSE endpoint with pace 0.01 yields stage_start events and terminates with run_complete.

### Task 6: Frontend — Mission Control + court UI

Invoke `frontend-design:frontend-design` before building. Mission Control: pre-review screen shown while a paced demo run streams — agent roster (Scene Scanner, E&O Auditor, Budget Planner, Rights Researchers ×N, Risk Engine, Remediation Drafter, Studio Counsel, Fair Use Advocate, The Judge) as cards lighting active/done with live status lines from SSE, then handoff into the review screen. Element cards gain: planner chip (tier + rationale tooltip), Court section (ruling banner + collapsible briefs with precedents). Rebuild dist, headless-Chrome screenshot both screens, commit.

### Task 7: Surfaces + docs + merge

MCP `get_finding`/`list_findings` include holding; README (Court + Mission Control sections, agent roster diagram), CLAUDE.md status, video-script beats updated (court scene becomes the 1:00–1:45 centerpiece), submission draft "what it does" updated. Full suite, merge to main.

## Self-Review

Court never changes scores (constraint held in CourtStage — writes only `state.court`). Demo count change is deliberate and confined to Task 2. SSE keeps sync default so no existing test churn in Task 5. Live-court and live-planner are coded but marked unvalidated until keys (consistent with project honesty policy).
