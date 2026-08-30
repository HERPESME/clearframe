---
name: live-validate
description: Validate ClearFrame live mode against real Vertex Gemini and Parallel (Task, FindAll, Search) APIs — auth troubleshooting, first scan, detection tuning, corroboration/freshness/territory/coverage checks, fixture refresh. Credentials already exist; read the status block for the traps that have already cost hours (ADC identity, zsh $VAR:, v1beta1). Use whenever live mode misbehaves or needs re-verifying.
---

# Live-mode validation runbook

> **Status 2026-08-22 — second live validation DONE (Phase 7/8).** Read this block first; it is where the expensive hours went.
>
> **Auth: the trap that cost the most time.** `gcloud auth login` and
> `gcloud auth application-default login` are *separate credential stores*, and
> the Python SDK uses ADC only. ADC was authenticated as a different Google
> account with no IAM binding on the project while `gcloud config` showed the
> owner — every Vertex call returned `403 Permission 'aiplatform.locations.list'
> denied`. Always check WHO ADC is before debugging anything else:
> ```bash
> curl -s "https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=$(gcloud auth application-default print-access-token)" | python3 -c "import json,sys;print(json.load(sys.stdin)['email'])"
> gcloud config get-value account     # may be a DIFFERENT identity
> ```
> Fix: re-run `gcloud auth application-default login` as the project owner, then
> `gcloud auth application-default set-quota-project <PROJECT>`.
>
> **Two false 404s that look like "model unavailable" but are not:**
> 1. **zsh modifier**: `"$M:generateContent"` expands to garbage (`5-pronerateContent`).
>    Always brace — `"${M}:generateContent"`. Symptom: Google's *HTML* 404 page.
> 2. **Wrong API version**: Vertex REST is **`v1beta1`**, not `v1`. Same HTML 404.
>
> A real model 404 returns **JSON** with `NOT_FOUND`. Working probe:
> ```bash
> TOKEN=$(gcloud auth application-default print-access-token); PROJ=<project>; LOC=us-central1; M=gemini-2.5-pro
> curl -X POST "https://${LOC}-aiplatform.googleapis.com/v1beta1/projects/${PROJ}/locations/${LOC}/publishers/google/models/${M}:generateContent" \
>   -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
>   -d '{"contents":[{"role":"user","parts":[{"text":"Reply with exactly: VERTEX OK"}]}]}'
> ```
>
> **Confirmed 2026-08-22**: `gemini-3-pro-preview` still 404s (clean JSON) in this
> project; `gemini-2.5-pro` and `gemini-2.5-flash` return 200. Live runs are
> actually served by the FALLBACK model — say so honestly in the video.
>
> **Parallel Search API live-verified**: `POST https://api.parallel.ai/v1beta/search`,
> headers `x-api-key` + `parallel-beta: search-extract-2025-10-10`, body
> `{objective, search_queries[], max_results, max_chars_per_result}` → `{search_id,
> results[{url,title,excerpts[]}], usage}`. **$0.005/request** — cheap enough to run
> on demand from the review screen, unlike a Task run. Same key as the Task API.
>
> **Cost reality (do not "optimise" the wrong way)**: Gemini video is 258 tokens/sec
> @ $1.25/M ≈ **$0.019/min** — a 90-min feature is ~$1.74/pass. Cloud Video
> Intelligence `LOGO_RECOGNITION` is $0.15/min, i.e. **7.8× more expensive**. It
> earns its cost as an *independent second opinion on identity*, never as a
> cheaper scanner.
>
> **`videointelligence.googleapis.com` was enabled 2026-08-22.** With it off, the
> corroborator logs `SERVICE_DISABLED` and every identity degrades to
> `SINGLE_SOURCE` — the pipeline still runs, which is correct, but the headline
> feature is silently inert. Verify enabled before claiming corroboration works live.
>
> **Bug found and fixed while validating**: `scan_script` routed through
> `_generate()`, which pinned `SCAN_RESPONSE_SCHEMA` — Gemini was forced to answer
> in the *video* shape while `parse_script_payload` looked for `mentions`, so live
> script pre-scan silently returned 0 and drift no-opped. Demo mode masked it
> (fixture client reads the JSON directly). Live-verified 0 → 4 mentions after fix.
> **Lesson: any live-only code path with a fixture twin needs a test asserting the
> live client's REQUEST, not just its response parsing.**

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

## Step 5b — validate the ladder and fingerprinting (Phase 9)

- **Fingerprinting**: needs `AUDD_API_TOKEN` (or the legacy `AUDIO_API_KEY`) and
  an *activated* AudD trial — a well-formed token on an inactive account returns
  error 900. Run any clip with music and check `state/*.json` → `audio_matches`
  and `corroboration.<music id>.verdict` = `FINGERPRINTED`. If the video model
  gave only a description, the element label should have been REWRITTEN to the
  fingerprinted title; that rewrite is what reaches the cue sheet.
- **Ladder**: check `routes` in the state. On real creator footage most findings
  should land on `STATUTE` (faces, own captions) and only one or two on `DEEP`.
  If everything is `DEEP`, the knowledge base is not loading — check
  `data/rights/` shipped with the install.
- **Cost**: `research_planned` now emits `deep_runs` and `routes`. Deep runs are
  the only line item that costs real money; SEARCH is $0.005 each.
- **ffmpeg**: comes from `imageio-ffmpeg` inside the venv. Confirm with
  `python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`.
  A bare `ffmpeg` on PATH is NOT what the code uses.

## Step 5 — validate the newer surfaces

- **Corroboration**: needs `videointelligence.googleapis.com`. Run any clip live and
  check `state/*.json` → `corroboration`. Expect `CORROBORATED` on catalogued marks,
  `SINGLE_SOURCE` on murals/tattoos/music (correct — not a failure), `CONFLICTED`
  only on genuine disagreement. A `CONFLICTED` finding must NOT appear in `research`.
- **Freshness**: `POST /api/productions/{pid}/freshness` or MCP `check_freshness`.
  Verify real URLs come back and that `material` separates enforcement news from
  brand marketing (`freshness.py::_MATERIAL_TERMS`).
- **Territory**: `--territories US,DE,FR`. The mural should band MEDIUM/LOW/HIGH.
- **Coverage**: upload `docs/sample-rights-ledger.csv`, then confirm COVERED /
  PARTIAL(gap named) / NOT_COVERED / UNKNOWN all appear.
- **Test corpus**: `./scripts/fetch_test_clips.sh` — six ~2MB public-domain
  commercials (Bayer, Jell-O, Lipton, Texaco, Playtex, Volkswagen) with
  `ground_truth.json`. Small enough for inline upload; the films are PD but the
  marks are still live, which is the product's whole thesis.

## Step 6 — record the evidence

Note model id, working prompt version, and any API-shape fixes in CLAUDE.md status section. These feed the demo video and Devpost "how we built it".
