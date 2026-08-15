---
name: submission-preflight
description: Pre-submission audit for the Devpost deadline (Sep 10 2026) — fresh-clone test, license visibility, rules-compliance checks, link verification. Use in the final days before submitting or when asked "are we ready to submit".
---

# Submission preflight

Run every check; report pass/fail with evidence. Rules source: hackathon brief + `docs/submission/checklist.md`.

## Automated checks

1. **Fresh clone**: clone the GitHub repo (not the local dir) into a temp dir; `pip install -e ".[dev]"`; `pytest` (expect green with skips); `python -m clearframe run --demo --out out --auto-approve`; verify all 5 artifacts exist.
2. **Serve check**: `python -m clearframe serve` from the fresh clone; confirm the SPA loads (committed dist present) and `POST /api/productions/demo` returns 6 elements.
3. **License visibility**: `gh api repos/<owner>/<repo> --jq .license.spdx_id` must return `MIT` (this is what populates the About sidebar — a rules requirement).
4. **Partner runtime use**: confirm `LiveParallelClient` is reachable from the default pipeline path (grep `build_context` wiring) — the rules require the partner service *called in code*, not just named.
5. **Docker**: `docker build .` succeeds (daemon must be running).

## Manual checks (walk the user through)

- Devpost form: Parallel track selected; hosted URL (Cloud Run) live and loads for a logged-out browser; repo public.
- Video: ≤3 minutes, shows the agent functioning as built, English (or subtitled), YouTube/Vimeo link public/unlisted-with-link, plays in incognito.
- README contains: run instructions (demo + live), architecture, hosted URL, video URL.
- Submit with ≥48h buffer before Sep 10 2:30am IST.

Anything failing: fix first, re-run the full preflight, only then tell the user it's ready.
