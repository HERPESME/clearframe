---
name: run-clearframe
description: Run, serve, test, or rebuild ClearFrame — demo pipeline CLI, review web app, frontend rebuild, screenshot verification. Use whenever asked to run/launch/demo the app or verify a change works.
---

# Running ClearFrame

All commands from the repo root. The venv lives at `.venv/` (create with
`python3 -m venv .venv && .venv/bin/pip install -e ".[dev,cloud]"` if missing;
Python 3.14 resolves the cloud extra fine). Frontend deps: `cd webapp && npm ci`.

## Demo pipeline (no credentials)

```bash
.venv/bin/python -m clearframe run --demo --out out --auto-approve
open out/dossier.html   # E&O report; also markers.edl/csv, cue_sheet.csv, dossier.json
```

Demo scene is **8 elements**. Expect 1 CRITICAL, 1 identity `CONFLICTED` (the
Adidas duffel the logo catalogue reads as Kappa — research is blocked for it),
and coverage spanning COVERED / PARTIAL / NOT_COVERED / UNKNOWN.

Two behaviours worth watching in the output because they are the product:

- **e1 promotes.** The scan only ever sees "Upbeat electronic music"; acoustic
  fingerprinting turns it into "Blinding Lights — The Weeknd" with verdict
  `FINGERPRINTED`, and that is what lands in `cue_sheet.csv` — a legal filing
  to a PRO.
- **The ladder routes.** `state/demo.json` → `routes` shows `SEARCH` for
  Coca-Cola (owner known locally, posture live), `STATUTE` for the background
  face (a release form, not research), `BLOCKED` for the disputed Adidas
  identity, `DEEP` for the unknown-artist mural. The dossier prints
  "Resolved without rights research (N of M)" with the authority for each.

## Live run on your own footage

```bash
./scripts/fetch_test_clips.sh                 # 6 public-domain spots + ground truth
set -a && source .env && set +a               # nothing auto-loads .env
.venv/bin/python -m clearframe run --live \
  --footage testdata/clips/ctvc_TEXACO_512kb.mp4 \
  --title "Texaco spot" --duration-s 60 --territories US,DE,FR \
  --out out-live --auto-approve
```

`--territories` (or `CLEARFRAME_TERRITORIES`) drives per-jurisdiction banding;
without it live runs are US-only.

`--use-context ADVERTISING` (or SPONSORED / NEWS / EDUCATIONAL) tells the risk
engine this is commercial speech, which carries no expressive-work shield:
scores rise and posture checks escalate to full rights research, because the
open question becomes permission rather than posture. Default EXPRESSIVE is the
calibration baseline, so omitting it reproduces the old numbers exactly.

`--sponsors "Coca-Cola,Nike"` flags competitor marks in shot. Not an
infringement — a contract exposure, since category exclusivity is standard in
brand deals.

`--platform youtube` (or tiktok / instagram / twitch / none) projects what the
PLATFORM will do, which is not what a court would do. Automated matching does
not evaluate fair use, so a finding with a strong legal defence can still be
claimed on upload. Default `none` means theatrical/festival/broadcast delivery:
no automated enforcement, which makes clearance more important rather than
less — there is no takedown to react to, only a distributor rejecting delivery.

`--territories` now spans 12 jurisdictions. The dossier prints, per finding,
which defences that jurisdiction does and does NOT offer — parody is statutory
in GB/DE/FR/ES and simply absent in India, Japan and Italy.

Without `--auto-approve` the pipeline pauses at review (exercise the web app instead). A rerun with the same `--out` resumes persisted state — pass a fresh dir to start over.

## Review web app

```bash
.venv/bin/python -m clearframe serve --out out --port 8000
# http://127.0.0.1:8000 → "Load demo production" → review cards → Generate clearance dossier
```

Upload footage from the hero screen ("Upload my own footage") — **live mode only**;
demo mode returns a 409 rather than replaying fixtures as your results. Upload a
rights ledger (CSV/JSON, `docs/sample-rights-ledger.csv` is a working sample) as
legal/producer to get COVERED / gap states. "Check live signals" re-runs the
Parallel Search pass on demand.

The SPA is served from committed `webapp/dist`. After ANY change under `webapp/src/`:

```bash
cd webapp && npm run build && cd ..   # then commit the dist changes too
```

## Verifying visually

`scripts/smoke.sh` runs its own server on port 8399 and kills only what holds
that port. It used to `pkill -f "clearframe serve"`, which killed any dev
server you had running on another port — twice per invocation, because the
EXIT trap fires too. Do not widen that pkill again.

To exercise every UI surface without credentials, load the demo as an advert:

```bash
curl -X POST localhost:8000/api/productions/demo -H 'Content-Type: application/json' \
  -d '{"use_context":"ADVERTISING","sponsors":["Pepsi"],"platform":"youtube"}'
```

Left unset, the sponsor and platform panels stay empty — correctly, since the
demo declares no sponsor and publishes nowhere.

**Debugging bounding boxes**: never reason about them, draw them. Extract the
frame at the element's `at_s` and render the stored rectangle onto it:

```bash
FF=$(.venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
"$FF" -ss <at_s> -i clip.mp4 -frames:v 1 \
  -vf "drawbox=x=iw*<xmin>:y=ih*<ymin>:w=iw*<w>:h=ih*<h>:color=lime:t=5" -y /tmp/box.png
```

That is how the axis transposition was found — the assumed reading floated in
empty wall while the transposed one landed on the object.

Headless Chrome works on this machine:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --window-size=1400,1200 --screenshot=/tmp/ui.png http://127.0.0.1:8000/
```

Read the PNG to check the design (dark screening-room theme, risk-colored timeline lanes).

## MCP server

```bash
.venv/bin/python -m clearframe.mcp --out out                          # stdio (local clients)
.venv/bin/python -m clearframe.mcp --transport http --port 8080 --out out  # streamable HTTP at /mcp
```

11 tools: `run_clearance · get_status · list_findings · get_finding ·
record_decision · verify_identities · territory_report · check_freshness ·
list_licences · check_coverage · generate_dossier`. Keep
`tests/test_mcp_server.py::test_tools_are_registered` in step when adding one.

## Tests + smoke

```bash
.venv/bin/pytest -q     # 406 tests; must be green before any commit
bash scripts/smoke.sh   # 7 sections: CLI, web, SSE, webhook, verification, ledger, MCP
```

When adding a smoke check, use its `has <needle> <curl args…>` helper. A bare
`curl … | grep -q` races under `set -o pipefail`: grep exits on first match, curl
dies of SIGPIPE (141), and the pipeline reports failure though the needle matched.
The helper buffers the body and matches with a **here-string**, not a pipe —
buffering alone is not enough, because `grep -q` still stops reading early and
kills any writer whose output exceeds the 64KB pipe buffer. The dossier crossed
that threshold and a correct check reported failure.

Cloud-dependent tests auto-skip without the `cloud` extra. Live mode needs env vars — see the live-validate skill. Deployment — see the deploy-cloud skill.
