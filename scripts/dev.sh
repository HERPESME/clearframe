#!/usr/bin/env bash
# Run ClearFrame locally. One command per role, so nobody has to remember which
# environment variables make which topology.
#
#   ./scripts/dev.sh                 the app, everything in one process
#   ./scripts/dev.sh --worker        the heavy container, on its own port
#   ./scripts/dev.sh --split         the app, expecting a worker on :8001
#   ./scripts/dev.sh --demo          fixtures only, no credentials, no spend
#
# `--split` is the one worth knowing about: it runs the exact two-container
# arrangement that ships, on a laptop, with no queue and no GCP account. The
# parts that are hard to get right — progress crossing a process boundary, a
# lease deciding what "running" means, a retry resuming instead of restarting —
# are all exercised, and none of the infrastructure has to exist yet.
set -euo pipefail

cd "$(dirname "$0")/.."

MODE="app"
DEMO=0
PORT=""
OUT="${CLEARFRAME_OUT:-out-live-ui}"

while [ $# -gt 0 ]; do
  case "$1" in
    --worker) MODE="worker" ;;
    --split)  MODE="split" ;;
    --demo)   DEMO=1 ;;
    --port)   PORT="$2"; shift ;;
    --out)    OUT="$2"; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Credentials, if there are any. `.env` is gitignored and holds live keys; a
# missing one is not an error, it just means demo mode.
if [ -f .env ] && [ "$DEMO" -eq 0 ]; then
  set -a && . ./.env && set +a
fi
if [ "$DEMO" -eq 1 ]; then
  export CLEARFRAME_MODE=demo
  unset PARALLEL_API_KEY || true
fi

# Local storage profile. Stated rather than assumed, because the whole point of
# these scripts is that you can read off which world you are in.
export CLEARFRAME_PROFILE=local

case "$MODE" in
  worker)
    PORT="${PORT:-8001}"
    echo "▸ worker · profile=local · mode=${CLEARFRAME_MODE:-demo} · out=$OUT · :$PORT"
    exec "$PY" -m clearframe worker --out "$OUT" --port "$PORT"
    ;;
  split)
    PORT="${PORT:-8000}"
    export CLEARFRAME_WORKER_URL="${CLEARFRAME_WORKER_URL:-http://127.0.0.1:8001}"
    echo "▸ app (split) · worker=$CLEARFRAME_WORKER_URL · out=$OUT · :$PORT"
    echo "  start the worker in another terminal: ./scripts/dev.sh --worker"
    exec "$PY" -m clearframe serve --out "$OUT" --port "$PORT"
    ;;
  *)
    PORT="${PORT:-8000}"
    echo "▸ app · profile=local · mode=${CLEARFRAME_MODE:-demo} · out=$OUT · :$PORT"
    exec "$PY" -m clearframe serve --out "$OUT" --port "$PORT"
    ;;
esac
