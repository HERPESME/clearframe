# .claude — project automation for ClearFrame

Context for any Claude Code session working in this repo. Root `CLAUDE.md` holds
project context, conventions, the status tracker vs the hackathon resources guide,
and the agreed roadmap. Read it first — especially "Live-mode gotchas" and
"Environment facts", which record what already went wrong so it doesn't twice.

Current shape: a deterministic **12-stage** pipeline, **161 tests**, a 7-section
smoke script, three transports (CLI / web / MCP with 11 tools), and two Cloud Run
services. Live validation, MCP, and webapp expansion are DONE; audio verification
and cloud wiring (Firestore/Pub-Sub/IAP) are the open fronts.

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
- **Per-phase design rationale** — `docs/superpowers/plans/`. Phases 7 and 8 share
  `2026-08-22-clearframe-phase7-verified-clearance.md`.

## Plugins

Claude Code plugins are installed at the user level (marketplace), not per-repo —
this project intentionally has none. Project automation lives in the skills/agents
above; harness settings (if ever needed) go in `.claude/settings.json`.
