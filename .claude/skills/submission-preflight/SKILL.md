---
name: submission-preflight
description: Pre-submission audit for the Devpost deadline (Sep 10 2026) — fresh-clone test, license visibility, rules-compliance checks, link verification. Use in the final days before submitting or when asked "are we ready to submit".
---

# Submission preflight

Run every check; report pass/fail with evidence. Rules source: hackathon brief + `docs/submission/checklist.md`.

## Automated checks

1. **Fresh clone**: clone the GitHub repo (not the local dir) into a temp dir; `pip install -e ".[dev]"`; `pytest` (expect green with 2 module skips without the cloud extra); `python -m clearframe run --demo --out out --auto-approve`; verify all 5 artifacts exist.
2. **Serve check**: `python -m clearframe serve` from the fresh clone; confirm the SPA loads (committed dist present) and `POST /api/productions/demo` returns **8** elements.
2b. **Full smoke**: `bash scripts/smoke.sh` — 7 sections must all pass. This is the single highest-signal check; run it before anything else.
2c. **No secrets staged**: `git status --porcelain` clean, and `git check-ignore -q .env` succeeds. A file named `env` (no dot) is NOT ignored — that near-miss already happened once with a live Parallel key in it. Also `git log --all -- .env env` must be empty.
3. **License visibility**: `gh api repos/<owner>/<repo> --jq .license.spdx_id` must return `MIT` (this is what populates the About sidebar — a rules requirement).
4. **Partner runtime use**: confirm `LiveParallelClient` is reachable from the default pipeline path (grep `build_context` wiring) — the rules require the partner service *called in code*, not just named. Parallel is now used at **three** runtime points: Task API (`research`), FindAll (`find_all`), Search API (`search`, the freshness pass). Note honestly that the deployed public URL runs in demo mode with no key bound, so it makes no Parallel calls; live usage is local or behind a supervised flip.
4b. **Claims that must survive a 60-second check** (each has been true as of 2026-08-22 — re-verify, don't assume):
   - "8 findings, 1 identity disputed, research blocked for it" → `curl … /api/productions/demo | jq '.corroboration.e8.verdict'` = `CONFLICTED`, and `.research.e8.status` = `incomplete`.
   - "mural bands differently per territory" → `.territory_risk.e5` = US MEDIUM / DE LOW / FR HIGH with cited statutes.
   - "we check rights you already hold" → `.coverage` spans COVERED / PARTIAL / NOT_COVERED / UNKNOWN.
   - "Parallel Search runs in real time" → `POST /api/productions/demo/freshness` returns `material_signals`.
   - Budget figures in Mission Control must match `docs.parallel.ai` list prices (they were 10× high once).
   - The demo video says live mode is served by `gemini-2.5-pro` (the fallback), because `gemini-3-pro-preview` 404s in this project. Do not claim otherwise.
5. **Docker**: `docker build .` succeeds (daemon must be running).

## Manual checks (walk the user through)

- Devpost form: Parallel track selected; hosted URL (Cloud Run) live and loads for a logged-out browser; repo public.
- Video: ≤3 minutes, shows the agent functioning as built, English (or subtitled), YouTube/Vimeo link public/unlisted-with-link, plays in incognito.
- README contains: run instructions (demo + live), architecture, hosted URL, video URL.
- Submit with ≥48h buffer before Sep 10 2:30am IST.

Anything failing: fix first, re-run the full preflight, only then tell the user it's ready.
