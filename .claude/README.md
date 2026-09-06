# .claude — project automation for ClearFrame

Context for any Claude Code session working in this repo. Root `CLAUDE.md` holds
project context, conventions, the status tracker vs the hackathon resources guide,
and the agreed roadmap. Read it first — especially "Live-mode gotchas" and
"Environment facts", which record what already went wrong so it doesn't twice.

Current shape: a deterministic **13-stage** pipeline, **674 tests**, a 7-section
smoke script, three transports (CLI / web / MCP with 11 tools), and two Cloud Run
services. Live validation, MCP, webapp expansion, audio fingerprinting, two-phase
reporting and the escalation ladder are DONE. Open fronts: **recall** (~60% per
pass, and it is the product's central claim — three passes and detector
promotion now ship, but neither has been measured live), scene chunking for
feature-length footage, and cloud wiring (Firestore/Pub-Sub/IAP).

**Before claiming a UI change works, open the app.** A whole class of defects
this project has shipped — transposed bounding boxes, an upload endpoint that
500'd on a NameError, a page refresh that appeared to delete the analysis, a
smoke script that killed the user's dev server — passed a green suite and were
found by a human clicking. `CLAUDE.md` → "UI-mode gotchas" lists them.

Where to pick up (as of Sep 6): the backend and the built SPA are in sync and
everything is committed. Phase 13 closed the box path — the merge was destroying
per-shot rectangles, the ground cache was serving the previous film's boxes, and
one finding can now draw several. The open thread is **recall measured on live
footage**: three passes and Video Intelligence promotion ship untested against
real film, and the 60% figure predates both. See `CLAUDE.md` -> NOT DONE.

**Box accuracy is solved; box DELIVERY was the problem.** Grounding a still is
accurate (verified by drawing rectangles onto real frames on three separate
clips). What broke was that the call blocked the event loop, started too late,
and was drawn over by the scan's union box in the meantime. All three fixed —
if boxes misbehave again, check `measuring boxes N/M` in the player status line
and which bundle the access log shows being fetched, before suspecting geometry.

One module takes findings away rather than adding them: `cast.py` holds that a
face attributed to a named performer is not a third-party finding, because the
production engaged them. The boundary is asymmetric on purpose — an unnamed
person stays a finding, since that release is real work.

Three modules answer questions the clearance pipeline does not: `platform.py`
(what the platform does — detectability, which inverts legal merit),
`exposure.py` (things on screen nobody owns — addresses, documents, minors),
and `conflicts.py` (sponsor category exclusivity). `territory.py` now answers
"which law governs this finding here" across 12 jurisdictions × 8 dimensions.

Two variables decide trademark risk, and both default to the old behaviour:
`Production.use_context` (advertising carries no Rogers shield) and
`DetectedElement.depiction` (holders object to portrayal, not presence). Music
is exempt from both. `conflicts.py` is the only check here that is not about
infringement at all — sponsor category exclusivity.

The two modules to read first when touching cost or latency are `routing.py`
(the escalation ladder — which rung answers each finding) and `knowledge.py`
(the local rights table). The governing rule is that a rung must be able to
answer the question its category poses; the honesty rule is that a finding
resolved for free is a documented position, never a silent skip.

## Skills (`.claude/skills/`)

- **run-clearframe** — run/serve/test/rebuild anything in the repo (demo CLI, live
  runs on your own footage, review app, MCP, frontend rebuild, headless-Chrome
  screenshot verification).
- **live-validate** — the runbook for first contact with real Vertex Gemini and
  Parallel APIs once credentials exist, including the detection-tuning loop.
- **submission-preflight** — Devpost readiness audit (fresh clone, license
  visibility, rules compliance, link checks).
- **deploy-cloud** — Cloud Run deploy runbook (webapp + MCP, scale-to-zero),
  Cloud Build CI/CD, live-mode secret wiring, rollback and cost notes.

## Agents (`.claude/agents/`)

- **detection-tuner** — iterates the Gemini scan prompt against real footage and
  reports detection quality (needs live creds).
- **submission-auditor** — read-only judge-mode audit against the rules and the four
  judging criteria.

## Where the hard-won facts live

- **Live-mode traps** (ADC being a different account than `gcloud config`, zsh
  eating `$VAR:`, Vertex being `v1beta1`, which Gemini model actually serves) —
  `CLAUDE.md` → "Live-mode gotchas", expanded in the **live-validate** skill.
- **Real API prices** (Gemini video is the cheap option; Parallel list prices) —
  `CLAUDE.md` → "Live-mode gotchas" and the **deploy-cloud** skill's cost model.
- **What this machine has configured** (project, enabled APIs, `.env` contents,
  Python version, missing ffmpeg) — `CLAUDE.md` → "Environment facts".
- **Competitive positioning** and the one-line pitch — `CLAUDE.md`.
- **Why each finding was routed the way it was** — `routing.py`'s module
  docstring carries the litigation reasoning; `data/rights/litigation.json`
  carries the cases themselves.
- **Per-phase design rationale** — `docs/superpowers/plans/`. Phases 7 and 8 share
  `2026-08-22-clearframe-phase7-verified-clearance.md`; Phase 9 (the latency
  phase) is `2026-08-22-clearframe-phase9-triage-ladder.md`, whose "What changed
  during implementation" section records three places the plan was wrong.

## Plugins

Claude Code plugins are installed at the user level (marketplace), not per-repo —
this project intentionally has none. Project automation lives in the skills/agents
above; harness settings (if ever needed) go in `.claude/settings.json`.
