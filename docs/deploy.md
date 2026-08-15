# Deploying ClearFrame to Google Cloud

## Prerequisites

- A GCP project with billing enabled and these APIs turned on:
  `aiplatform.googleapis.com`, `run.googleapis.com`, `artifactregistry.googleapis.com`
- A Parallel API key from https://platform.parallel.ai
- `gcloud` CLI authenticated (`gcloud auth login && gcloud config set project <PROJECT>`)

## Environment variables

| Variable | Purpose | Example |
| --- | --- | --- |
| `CLEARFRAME_MODE` | `demo` (fixtures) or `live` | `live` |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Vertex AI | `my-project` |
| `GOOGLE_CLOUD_LOCATION` | Vertex region | `us-central1` |
| `PARALLEL_API_KEY` | Parallel Task API key | `pk_…` |
| `CLEARFRAME_GEMINI_MODEL` | Override scan model | `gemini-3-pro-preview` |

## Cloud Run (review app)

```bash
gcloud run deploy clearframe \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars CLEARFRAME_MODE=live,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=us-central1 \
  --set-secrets PARALLEL_API_KEY=parallel-api-key:latest
```

Store the Parallel key in Secret Manager first:

```bash
printf '%s' "$PARALLEL_API_KEY" | gcloud secrets create parallel-api-key --data-file=-
```

For a judged demo, `--allow-unauthenticated` keeps the URL public; for real
production put the service behind Identity-Aware Proxy and map IAP identities
to ClearFrame roles (legal / producer / editor) instead of the demo role
switcher header.

## Live pipeline run (CLI)

Upload footage to GCS and run:

```bash
gsutil cp scene.mp4 gs://$BUCKET/scene.mp4
CLEARFRAME_MODE=live GOOGLE_CLOUD_PROJECT=$PROJECT PARALLEL_API_KEY=$KEY \
  python -m clearframe run --live --footage gs://$BUCKET/scene.mp4 \
  --title "Golden Hour" --duration-s 62 --out out
```

## Agent Engine (managed agent runtime)

The pipeline is exposed as an ADK `SequentialAgent` via
`clearframe.adk.agents.build_clearframe_agent`. To deploy on Vertex AI Agent
Engine:

```python
from vertexai import agent_engines
from clearframe.adk.agents import build_clearframe_agent
from clearframe.pipeline import build_context
# build ctx from ClearFrameConfig.from_env(...), then:
app = agent_engines.create(
    agent_engine=build_clearframe_agent(ctx, out_dir=Path("/tmp/out"), auto_approve=False),
    requirements=["clearframe @ git+https://github.com/<you>/clearframe"],
)
```

Verify the current `agent_engines` API against the Gemini Enterprise Agent
Platform docs at deploy time.

## Phase 3 wiring (planned)

- **Firestore** replaces `LocalJsonStore` (same repository interface).
- **Pub/Sub** receives Parallel task webhooks so research resumes
  event-driven instead of polling.
- **Cloud IAM/IAP** replaces the demo role header.
