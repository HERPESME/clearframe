# .claude — project automation for ClearFrame

Context for any Claude Code session working in this repo. Root `CLAUDE.md` holds
project context, conventions, the status tracker vs the hackathon resources guide,
and the agreed roadmap (live validation → MCP → webapp expansion → cloud wiring →
submission). Read it first.

## Skills (`.claude/skills/`)

- **run-clearframe** — run/serve/test/rebuild anything in the repo (demo CLI, review
  app, frontend rebuild, headless-Chrome screenshot verification).
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

## Plugins

Claude Code plugins are installed at the user level (marketplace), not per-repo —
this project intentionally has none. Project automation lives in the skills/agents
above; harness settings (if ever needed) go in `.claude/settings.json`.
