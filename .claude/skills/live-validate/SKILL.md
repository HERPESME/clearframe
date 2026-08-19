---
name: live-validate
description: Validate ClearFrame live mode against real Vertex Gemini and Parallel Task APIs once credentials exist — first scan, detection-quality tuning loop, first research run, fixture refresh. Use when the user provides GCP/Parallel credentials or asks to test live mode.
---

# Live-mode validation runbook

> **Status 2026-08-19 — first live validation DONE.** Facts a future session needs:
> - Credentials: local `.env` (gitignored) has the real values; Secret Manager holds `parallel-api-key` (Cloud Run default SA has accessor). Load env with `set -a && source .env && set +a` — nothing auto-loads `.env`.
> - **Gemini**: `gemini-3-pro-preview` returns 404 in this project/region — the coded fallback to `gemini-2.5-pro` fires and works. First live scan (Sintel trailer, 52s, inline bytes) returned 9 high-quality detections incl. a 1s tattoo; parser unchanged.
> - **Parallel Task API**: live-verified exactly as coded (`POST /v1/tasks/runs`, poll, `/result`, `x-api-key`). `parse_task_output` needed zero changes; real Basis citations returned.
> - **FindAll**: original guess was wrong (404). Real flow: `POST /v1beta/findall/runs` (objective, entity_type, match_conditions incl. our `kind` condition, generator, match_limit) → poll `status.status` → `GET .../result` → `candidates[]`. Shared parser `parse_findall_result`; fixture uses the genuine result shape.
> - **Monitors**: gated beta — this key gets 401 `Product(s) unavailable to provided credential`. Live client falls back to local stand-in watches (`local-{el}`); webhook/reopen flow identical.
> - Public Cloud Run stays **demo mode** deliberately (unauthenticated URL + live keys = open spend). Live runs happen locally or behind auth.

Prereqs from the user: GCP project ID (Vertex AI API enabled, billing on) and a Parallel API key. Never commit keys; use env vars or `.env` (gitignored).

```bash
export CLEARFRAME_MODE=live GOOGLE_CLOUD_PROJECT=<project> PARALLEL_API_KEY=<key>
# optional: GOOGLE_CLOUD_LOCATION (default us-central1), CLEARFRAME_GEMINI_MODEL (default gemini-3-pro-preview, falls back to gemini-2.5-pro)
gcloud auth application-default login   # user runs this themselves (suggest `! gcloud auth application-default login`)
```

## Step 1 — first live scan (the project's top risk)

Use any short local mp4 (<20MB inline; larger → upload to GCS and pass `gs://…`):

```bash
.venv/bin/python -m clearframe run --live --footage clip.mp4 --title "Live Test" --duration-s 30 --fps 24 --out out-live
```

Failure modes: auth → ADC not set; 404 model → check `CLEARFRAME_GEMINI_MODEL` against current Vertex model ids; `ScanFailedError` → inspect the raw response by adding a temporary print in `gemini_live.py`.

## Step 2 — detection-quality tuning loop

Judge the scan against what's actually in the clip. Iterate `SCAN_PROMPT` in `src/clearframe/integrations/gemini_client.py` (it is shared by live + future fixture regeneration). Watch for: missed audio/music, missed background artwork, prominence numbers that don't match reality (screen_time_s vs actual). Tune, rerun, compare. Consider the detection-tuner agent for systematic passes.

## Step 3 — first live Parallel research

The same `--live` run exercises research automatically. Verify: Basis citations present, postures sane, incomplete-handling honest. If the API shape differs from `parse_task_output`'s expectations (endpoints/fields per docs.parallel.ai), fix the parser — fixtures already validate the expected shape, so update BOTH parser and fixtures together, keeping tests green.

## Step 4 — refresh fixtures from reality (optional but ideal)

Capture real responses from the salted demo scene and replace the hand-written fixtures in `src/clearframe/integrations/fixtures/` so demo mode replays genuine API output. Keep element ids/labels aligned with `demo_scene.json` expectations in tests, or update tests deliberately.

## Step 5 — record the evidence

Note model id, working prompt version, and any API-shape fixes in CLAUDE.md status section. These feed the demo video and Devpost "how we built it".
