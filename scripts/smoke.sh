#!/usr/bin/env bash
# ClearFrame smoke test — exercises every transport end to end in demo mode.
# Usage: ./scripts/smoke.sh   (from the repo root; needs .venv with dev deps)
set -uo pipefail

PY=".venv/bin/python"
PORT=8399
BASE="http://127.0.0.1:$PORT"
OUT="$(mktemp -d)/smoke-out"
FAILURES=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
check() { if [ "$1" -eq 0 ]; then pass "$2"; else fail "$2"; fi }

cleanup() { pkill -f "clearframe serve" 2>/dev/null || true; }
trap cleanup EXIT
# ensure no stale server from a previous run holds the port
pkill -f "clearframe serve" 2>/dev/null || true
sleep 1

echo "━━ 1. Test suite"
$PY -m pytest -q > /tmp/clearframe-smoke-pytest.log 2>&1
check $? "pytest suite green (log: /tmp/clearframe-smoke-pytest.log)"

echo "━━ 2. CLI demo pipeline"
$PY -m clearframe run --demo --out "$OUT" --auto-approve > /tmp/clearframe-smoke-cli.log 2>&1
check $? "CLI demo run exits 0"
for f in dossier.html dossier.json markers.edl markers.csv cue_sheet.csv; do
  [ -f "$OUT/$f" ]; check $? "artifact $f exists"
done
grep -q "Clearance Court" "$OUT/dossier.html"; check $? "dossier contains Clearance Court opinions"
grep -q "Audit trail" "$OUT/dossier.html"; check $? "dossier contains audit trail"
grep -q "Ringgold" "$OUT/dossier.html"; check $? "dossier cites real precedent"

echo "━━ 3. Review web app"
SERVE_OUT="$(mktemp -d)/web-out"
$PY -m clearframe serve --out "$SERVE_OUT" --port $PORT > /tmp/clearframe-smoke-serve.log 2>&1 &
sleep 2
curl -sf "$BASE/" | grep -q "ClearFrame"; check $? "SPA served at /"
curl -sf -X POST "$BASE/api/productions/demo" -H 'Content-Type: application/json' -d '{"pace_s": 0.05}' | grep -q running
check $? "paced Mission Control run started"
curl -sfN --max-time 30 "$BASE/api/productions/demo/events" | grep -q "run_complete"
check $? "SSE stream delivered run_complete"
COUNT=$(curl -sf "$BASE/api/productions/demo" | $PY -c "import json,sys; print(len(json.load(sys.stdin)['elements']))")
[ "$COUNT" = "8" ]; check $? "pipeline found 8 elements (incl. auditor catch)"

CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/productions/demo/decisions" \
  -H 'Content-Type: application/json' -H 'X-ClearFrame-Role: editor' \
  -d '{"element_id":"e1","action":"license","note":""}')
[ "$CODE" = "403" ]; check $? "editor role rejected (403) — server-side gating"

for el in e1 e2 e3 e4 e5 e6 e7 e8; do
  curl -sf -X POST "$BASE/api/productions/demo/decisions" \
    -H 'Content-Type: application/json' -H 'X-ClearFrame-Role: legal' \
    -d "{\"element_id\":\"$el\",\"action\":\"license\",\"note\":\"smoke\"}" > /dev/null || FAILURES=$((FAILURES+1))
done
pass "8 legal decisions recorded"

curl -sf -X POST "$BASE/api/productions/demo/dossier" | grep -q "cue_sheet.csv"
check $? "dossier generated with all artifacts"
curl -sf "$BASE/api/productions/demo/artifacts/dossier.html" | grep -q "Clearance Report"
check $? "artifact served over HTTP"

echo "━━ 4. Living clearance (standing watch)"
WATCHES=$(curl -sf "$BASE/api/productions/demo" | $PY -c "import json,sys; print(len(json.load(sys.stdin)['watches']))")
[ "$WATCHES" -ge 3 ]; check $? "standing watches created post-dossier ($WATCHES)"
curl -sf -X POST "$BASE/api/webhooks/parallel-monitor" -H 'Content-Type: application/json' \
  -d '{"monitor_id":"mon-e3","summary":"smoke: rights holder posture changed","source_url":""}' \
  | grep -q '"reopened_element":"e3"'
check $? "monitor webhook reopened the watched finding"
curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
assert s['stage_status']['review'] == 'awaiting', 'review not reopened'
assert any(a['event'] == 'watch_alert' for a in s['audit_log']), 'no audit event'
"
check $? "review reopened + audit trail updated"

echo "━━ 5. MCP server (stdio)"
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}\n' \
  | $PY -m clearframe.mcp --out "$OUT" 2>/dev/null | grep -q '"clearframe"'
check $? "MCP stdio server answers initialize handshake"

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32m━━ SMOKE TEST PASSED — every transport verified ━━\033[0m\n'
else
  printf '\033[31m━━ SMOKE TEST: %d FAILURE(S) ━━\033[0m\n' "$FAILURES"
  exit 1
fi
