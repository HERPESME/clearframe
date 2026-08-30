---
name: deploy-cloud
description: Deploy ClearFrame to Google Cloud Run (webapp + MCP, scale-to-zero, demo or live mode) and manage the Cloud Build CI/CD pipeline. Use for deploys, rollbacks, cost checks, enabling live mode with secrets, or CI/CD troubleshooting.
---

# Cloud deployment runbook

Architecture: **one image, two Cloud Run services**, both `min-instances=0` (cost ≈ $0 when idle; requests bill per-100ms). Region `us-central1`. Demo mode needs no secrets; state lives in `/tmp/out` (ephemeral — resets on scale-to-zero, which is fine for demo).

| Service | Command | Purpose |
| --- | --- | --- |
| `clearframe` | `python -m clearframe serve --host 0.0.0.0 --port 8080 --out /tmp/out` | review webapp + API |
| `clearframe-mcp` | `python -m clearframe.mcp --transport http --port 8080 --out /tmp/out` | MCP streamable-HTTP at `/mcp` |

## Prerequisites (once per project)

```bash
gcloud auth login && gcloud config set project <PROJECT_ID> && gcloud config set run/region us-central1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com secretmanager.googleapis.com videointelligence.googleapis.com
gcloud artifacts repositories create clearframe --repository-format=docker --location=us-central1
```

## Deploy (manual)

```bash
gcloud builds submit --config cloudbuild.yaml .
```

`cloudbuild.yaml` builds the image, pushes to Artifact Registry, and deploys both services. Verify:

```bash
gcloud run services list --format='value(SERVICE,URL)'
curl -sf <webapp-url>/api/productions   # -> []
curl -s -X POST <mcp-url>/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
```

## CI/CD (push-to-deploy)

A Cloud Build trigger on `main` runs the same `cloudbuild.yaml`. If the trigger doesn't exist, connecting GitHub needs one console step (Cloud Build → Triggers → Connect repository → GitHub App), then:

```bash
gcloud builds triggers create github --name=clearframe-main \
  --repo-owner=<GH_OWNER> --repo-name=clearframe \
  --branch-pattern='^main$' --build-config=cloudbuild.yaml --region=us-central1
```

The Cloud Build service account needs `roles/run.admin` + `roles/iam.serviceAccountUser` (grant shown in Phase-6 history; `gcloud projects add-iam-policy-binding`).

## Flipping to live mode (when API keys exist)

> **Done on 2026-08-19**: secret `parallel-api-key` exists in Secret Manager and the
> Cloud Run default SA (220710110855-compute@) already has `secretAccessor`. The
> public services deliberately REMAIN in demo mode — an unauthenticated URL with
> live keys is open spend for anyone who finds it. Flip only behind auth (IAP) or
> for a supervised demo window, using the command below; flip back afterwards with
> `--set-env-vars CLEARFRAME_MODE=demo --clear-secrets`.

```bash
gcloud run services update clearframe --region us-central1 \
  --set-env-vars CLEARFRAME_MODE=live,GOOGLE_CLOUD_PROJECT=<PROJECT_ID>,GOOGLE_CLOUD_LOCATION=us-central1 \
  --set-secrets PARALLEL_API_KEY=parallel-api-key:latest
```

## Live-mode cost model (verified 2026-08-22)

The original "unauthenticated URL + live keys = open spend" fear was reasoned
from `planner.EST_COST`, which was **~10× Parallel's list price**. Real numbers:

| Item | Price | Full 8-finding demo run |
| --- | --- | --- |
| Gemini video scan | $0.019/min (258 tok/s @ $1.25/M) | ~$0.04 (62s, two passes) |
| Parallel Task | lite $0.005 / base $0.010 / pro $0.100 / ultra $0.300 per run | ~$0.30 |
| Parallel Search (freshness) | $0.005/request | ~$0.03 |
| Video Intelligence (corroboration) | $0.15/min — first 1,000 min free | ~$0.15 |

So a public live run is **well under $1**, not $5+. Live mode behind a rate limit
plus `CLEARFRAME_MAX_RESEARCH` is defensible for a judged demo window. Video
Intelligence is the priciest per minute — it earns it as an independent identity
check, never as a cheaper scanner.

## Costs / rollback

- Idle cost: $0 compute (scale-to-zero); pennies for Artifact Registry storage + build minutes.
- Rollback: `gcloud run services update-traffic clearframe --to-revisions <REVISION>=100`.
- Watch spend: `gcloud billing accounts list` / console budgets — set a budget alert early.
