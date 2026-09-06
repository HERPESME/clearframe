#!/usr/bin/env bash
# Deploy ClearFrame to Cloud Run.
#
#   ./scripts/deploy.sh staging     cloud storage, DEMO detectors — no spend
#   ./scripts/deploy.sh prod        cloud storage, LIVE detectors — asks first
#
# The two differ in exactly one thing: whether the detectors are real. Both use
# the cloud storage profile, so `staging` exercises the entire deployed topology
# — buckets, Firestore, the queue, the worker, ownership — with recorded
# fixtures behind it and nothing billable. That combination is the one to deploy
# first, and the one to leave running.
#
# `prod` asks for confirmation because an unauthenticated URL with live keys
# behind it is open spend, and this project has a standing decision that the
# public demo stays in demo mode.
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${1:-}"
case "$TARGET" in
  staging) MODE="demo" ;;
  prod)    MODE="live" ;;
  *) echo "usage: $0 <staging|prod>" >&2; exit 2 ;;
esac

REGION="${CLEARFRAME_REGION:-us-central1}"
PROJECT="$(gcloud config get-value project 2>/dev/null)"
BUCKET="${CLEARFRAME_BUCKET:-clearframe-${PROJECT}-media}"
QUEUE="${CLEARFRAME_TASKS_QUEUE:-projects/${PROJECT}/locations/${REGION}/queues/clearframe-analysis}"

if [ -z "$PROJECT" ]; then
  echo "no gcloud project configured — run: gcloud config set project <id>" >&2
  exit 2
fi

echo "project : $PROJECT"
echo "region  : $REGION"
echo "bucket  : $BUCKET"
echo "queue   : $QUEUE"
echo "mode    : $MODE"

# Fail early rather than half-way through a deploy. Each of these is created
# once by hand; the README section in docs/deploy.md has the commands.
missing=0
gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 || {
  echo "  ✗ bucket gs://${BUCKET} does not exist"; missing=1; }
gcloud tasks queues describe "${QUEUE##*/}" --location="$REGION" >/dev/null 2>&1 || {
  echo "  ✗ queue ${QUEUE##*/} does not exist in $REGION"; missing=1; }
gcloud firestore databases describe --database='(default)' >/dev/null 2>&1 || {
  echo "  ✗ no Firestore database (create it in NATIVE mode — the choice is permanent)"; missing=1; }
[ "$missing" -eq 0 ] || { echo "provision the above first: see docs/deploy.md" >&2; exit 1; }

if [ "$MODE" = "live" ]; then
  echo
  echo "This puts LIVE detectors behind the deployed URL."
  echo "Each analysis runs three Gemini video passes and real Parallel research."
  printf "Type the word live to continue: "
  read -r confirm
  [ "$confirm" = "live" ] || { echo "aborted."; exit 1; }
fi

gcloud builds submit --config cloudbuild.yaml . \
  --substitutions="_REGION=${REGION}"

WORKER_URL="$(gcloud run services describe clearframe-worker \
  --region="$REGION" --format='value(status.url)')"

# Applied after the build so both services agree on the same worker URL, which
# is not knowable until the worker exists. `--update-env-vars`, never `--set-`:
# the latter replaces the whole block and would silently drop the secrets.
gcloud run services update clearframe --region="$REGION" \
  --update-env-vars="CLEARFRAME_MODE=${MODE},CLEARFRAME_PROFILE=cloud,CLEARFRAME_BUCKET=${BUCKET},CLEARFRAME_TASKS_QUEUE=${QUEUE},CLEARFRAME_WORKER_URL=${WORKER_URL},GOOGLE_CLOUD_PROJECT=${PROJECT}"

gcloud run services update clearframe-worker --region="$REGION" \
  --update-env-vars="CLEARFRAME_MODE=${MODE},CLEARFRAME_PROFILE=cloud,CLEARFRAME_BUCKET=${BUCKET},CLEARFRAME_WORKER_AUDIENCE=${WORKER_URL},GOOGLE_CLOUD_PROJECT=${PROJECT}"

echo
echo "app    : $(gcloud run services describe clearframe --region="$REGION" --format='value(status.url)')"
echo "worker : $WORKER_URL  (not public — the queue's service account only)"
