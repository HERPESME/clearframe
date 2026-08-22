# .claude — project automation for ClearFrame

Context for any Claude Code session working in this repo. Root `CLAUDE.md` holds
project context, conventions, the status tracker vs the hackathon resources guide,
and the agreed roadmap. Read it first — especially "Live-mode gotchas" and
"Environment facts", which record what already went wrong so it doesn't twice.

Current shape: a deterministic **13-stage** pipeline, **346 tests**, a 7-section
smoke script, three transports (CLI / web / MCP with 11 tools), and two Cloud Run
services. Live validation, MCP, webapp expansion and audio fingerprinting are
DONE. Open fronts: two-phase reporting, scene chunking for feature-length
footage, and cloud wiring (Firestore/Pub-Sub/IAP).

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
