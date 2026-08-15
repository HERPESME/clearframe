---
name: run-clearframe
description: Run, serve, test, or rebuild ClearFrame — demo pipeline CLI, review web app, frontend rebuild, screenshot verification. Use whenever asked to run/launch/demo the app or verify a change works.
---

# Running ClearFrame

All commands from the repo root. The venv lives at `.venv/` (create with `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,cloud]"` if missing).

## Demo pipeline (no credentials)

```bash
.venv/bin/python -m clearframe run --demo --out out --auto-approve
open out/dossier.html   # E&O report; also markers.edl/csv, cue_sheet.csv, dossier.json
```

Without `--auto-approve` the pipeline pauses at review (exercise the web app instead). A rerun with the same `--out` resumes persisted state — pass a fresh dir to start over.

## Review web app

```bash
.venv/bin/python -m clearframe serve --out out --port 8000
# http://127.0.0.1:8000 → "Load demo production" → review cards → Generate clearance dossier
```

The SPA is served from committed `webapp/dist`. After ANY change under `webapp/src/`:

```bash
cd webapp && npm run build && cd ..   # then commit the dist changes too
```

## Verifying visually

Headless Chrome works on this machine:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --window-size=1400,1200 --screenshot=/tmp/ui.png http://127.0.0.1:8000/
```

Read the PNG to check the design (dark screening-room theme, risk-colored timeline lanes).

## Tests

```bash
.venv/bin/pytest -q          # full suite; must be green before any commit
```

Cloud-dependent tests auto-skip without the `cloud` extra. Live mode needs env vars — see the live-validate skill.
