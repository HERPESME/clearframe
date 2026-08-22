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

# curl | grep races under pipefail (grep exits early -> curl gets SIGPIPE
# -> 141 propagates). Buffer the body, then match WITHOUT a pipe: `grep -q`
# stops reading at the first match, so even `printf "$body" | grep -q` takes
# SIGPIPE once the body exceeds the 64KB pipe buffer. The dossier HTML crossed
# that line and this check failed while matching perfectly. A here-string is
# backed by a temp file, so there is no pipe and no race at any size.
has() {  # has <needle> <curl args...>
  local needle="$1"; shift
  local body
  body=$(curl -s "$@") || return 1
  grep -q -- "$needle" <<<"$body"
}

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
has "ClearFrame" "$BASE/"; check $? "SPA served at /"
has running -X POST "$BASE/api/productions/demo" -H 'Content-Type: application/json' -d '{"pace_s": 0.05}'
check $? "paced Mission Control run started"
has "run_complete" -N --max-time 30 "$BASE/api/productions/demo/events"
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

has "cue_sheet.csv" -X POST "$BASE/api/productions/demo/dossier"
check $? "dossier generated with all artifacts"
has "Clearance Report" "$BASE/api/productions/demo/artifacts/dossier.html"
check $? "artifact served over HTTP"

echo "━━ 4. Living clearance (standing watch)"
WATCHES=$(curl -sf "$BASE/api/productions/demo" | $PY -c "import json,sys; print(len(json.load(sys.stdin)['watches']))")
[ "$WATCHES" -ge 3 ]; check $? "standing watches created post-dossier ($WATCHES)"
has '"reopened_element":"e3"' -X POST "$BASE/api/webhooks/parallel-monitor" \
  -H 'Content-Type: application/json' \
  -d '{"monitor_id":"mon-e3","summary":"smoke: rights holder posture changed","source_url":""}'
check $? "monitor webhook reopened the watched finding"
curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
assert s['stage_status']['review'] == 'awaiting', 'review not reopened'
assert any(a['event'] == 'watch_alert' for a in s['audit_log']), 'no audit event'
"
check $? "review reopened + audit trail updated"

echo "━━ 5. Verified identity, live signals, territory"
IDS=$(curl -sf "$BASE/api/productions/demo" | $PY -c "
import json,sys
s=json.load(sys.stdin)
v=[c['verdict'] for c in s['corroboration'].values()]
print(v.count('CORROBORATED'), v.count('CONFLICTED'))
")
[ "$IDS" = "2 1" ]; check $? "identity corroboration: 2 confirmed, 1 disputed ($IDS)"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
assert s['research']['e8']['status'] == 'incomplete', 'disputed identity was researched anyway'
assert 'e8' not in s['candidates'], 'disputed identity was enumerated anyway'
"
check $? "disputed identity is blocked from rights research"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
bands = {t['territory']: t['band'] for t in s['territory_risk']['e5']}
assert bands == {'US': 'MEDIUM', 'DE': 'LOW', 'FR': 'HIGH'}, bands
assert 'UrhG' in [t['authority'] for t in s['territory_risk']['e5']][1]
"
check $? "mural bands per territory US/DE/FR with cited authority"

$PY - <<'PHASE_C'
import asyncio, tempfile
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.territory import TERRITORY_RULES


async def main():
    assert len(TERRITORY_RULES) >= 12, len(TERRITORY_RULES)

    with tempfile.TemporaryDirectory() as tmp:
        ctx = demo_context(tmp)
        ctx.state.production = ctx.state.production.model_copy(
            update={"release_territories": ["IN", "GB", "IT"]}
        )
        st = await Pipeline(build_demo_pipeline()).run(ctx)

    rows = st.defences["e5"]  # the unknown-artist mural
    by = {(r["territory"], r["name"]): r for r in rows}

    # Parody: statutory in the UK, absent in India and Italy. One global answer
    # could not have told a skit maker any of this.
    assert by[("GB", "Parody / caricature")]["available"] is True
    assert by[("IN", "Parody / caricature")]["available"] is False
    assert by[("IT", "Parody / caricature")]["available"] is False

    # India is unusually generous about background artwork in a film.
    incidental_in = by[("IN", "Incidental inclusion")]
    assert incidental_in["available"] is True
    assert "52(1)(u)" in incidental_in["authority"]

    # Italy is the most restrictive: no panorama exception at all.
    assert by[("IT", "Freedom of panorama")]["available"] is False

    # Only the US has an open-ended exceptions regime.
    assert by[("GB", "Fair use (open-ended)")]["available"] is False

    # Every row carries its authority — an uncited legal claim is worse than none.
    assert all(r["authority"] for r in rows)


asyncio.run(main())
PHASE_C
check $? "jurisdiction defences differ per territory, each with its authority"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
x = s['assessed_exposures']
assert len(x) == 1, x
one = x[0]
# Not a clearance item — nobody owns a delivery label with an address on it.
assert one['kind'] == 'PERSONAL_DATA', one['kind']
# The strictest release territory governs: a publication cannot be un-made in
# one country and left standing in another.
assert one['territory'] == 'DE', one['territory']
assert 'GDPR' in one['regime'], one['regime']
assert one['band'] == 'CRITICAL', one['band']
# The fix has to be something an editor can do.
assert '00:18' in one['remedy'] and '00:21' in one['remedy'], one['remedy']
# And it stays out of the clearance element list.
assert all(e['id'] != one['id'] for e in s['elements'])
"
check $? "on-screen exposure found, banded by strictest territory, fix timecoded"

grep -q "On-screen exposure" "$OUT/dossier.html"
check $? "dossier reports on-screen exposure as its own class"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
el = {e['id']: e for e in s['elements']}['e1']
c = s['corroboration']['e1']
assert c['verdict'] == 'FINGERPRINTED', c['verdict']
assert el['label'] == 'Blinding Lights — The Weeknd', el['label']
assert s['audio_matches'][0]['provenance'] == 'VERIFIED', s['audio_matches']
"
check $? "music identity promoted by fingerprint (description -> named work)"

CUE=$(grep -c 'Blinding Lights — The Weeknd' "$OUT/cue_sheet.csv")
[ "$CUE" = "1" ]; check $? "PRO cue sheet carries the fingerprinted title, not the description"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
p = s['preview']
assert len(p) == len(s['elements']), 'every finding must be in the preliminary report'
assert all(f['time_ranges'] and f['provisional_band'] for f in p), p[:1]
assert [f['provisional_score'] for f in p] == sorted(
    [f['provisional_score'] for f in p], reverse=True), 'preview must rank by exposure'
# provisional risk is an upper bound: it can only fall once research lands
assert all(f['provisional_score'] >= s['risk'][f['element_id']]['score'] for f in p)
assert any(not f['awaiting_research'] and f['disposition'] for f in p)
"
check $? "preliminary report is complete and banded before research runs"

$PY - <<'PHASE_A'
import asyncio, tempfile
from clearframe.models import UseContext
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        expressive = await Pipeline(build_demo_pipeline()).run(demo_context(tmp))

    with tempfile.TemporaryDirectory() as tmp:
        ctx = demo_context(tmp)
        ctx.state.production = ctx.state.production.model_copy(
            update={"use_context": UseContext.ADVERTISING, "sponsors": ["Pepsi"]}
        )
        ad = await Pipeline(build_demo_pipeline()).run(ctx)

    # Commercial speech carries no expressive-work shield, so the same finding
    # scores harder. Rogers v. Grimaldi protects films, not advertisements.
    assert ad.risk["e3"].score > expressive.risk["e3"].score
    assert ad.risk["e3"].factors["use_context_factor"] == 1.4

    # Music is exempt: sync + master are required whichever medium this is.
    assert ad.risk["e1"].score == expressive.risk["e1"].score

    # A rival mark while a sponsor pays is a CONTRACT exposure, not infringement.
    assert [c.conflicts_with for c in ad.sponsor_conflicts] == ["Pepsi"]
    assert ad.sponsor_conflicts[0].label == "Coca-Cola can"

    # In an advert the open question is permission, not posture.
    assert ad.routes["e2"].tier.value == "DEEP", ad.routes["e2"].tier


asyncio.run(main())
PHASE_A
check $? "advertising context scores harder, music exempt, sponsor conflict flagged"

$PY - <<'PHASE_B'
import asyncio, tempfile
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.platform import detectability


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        ctx = demo_context(tmp)
        ctx.state.production = ctx.state.production.model_copy(
            update={"platform": "youtube"}
        )
        st = await Pipeline(build_demo_pipeline()).run(ctx)

    outcomes = st.platform_outcomes
    assert len(outcomes) == len(st.elements)

    # Ranked by how likely the PLATFORM is to act, not by legal merit.
    scores = [detectability(o) for o in outcomes]
    assert scores == sorted(scores, reverse=True), scores

    # Detectability inverts legal merit: a fingerprinted track is caught
    # essentially always; a mural with real legal weight almost never is.
    top = outcomes[0]
    assert top.action.value == "CLAIM_LIKELY", top.action
    assert top.confidence == "near-certain"
    assert "00:12" in top.remedy, top.remedy          # actionable timecode
    assert "Republic Records" in top.revenue_impact   # who gets the money
    assert "fair use" in top.consequence.lower()      # and that it is no defence

    visual = [o for o in outcomes if o.action.value == "MANUAL_COMPLAINT"]
    assert visual and detectability(visual[0]) < detectability(top)


asyncio.run(main())
PHASE_B
check $? "platform outcomes rank by detectability, not legal merit"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
# Default platform is 'none' — theatrical/festival delivery, no automated
# enforcement — so nothing is reported as an automated claim.
assert s['production']['platform'] == 'none', s['production']['platform']
assert all(o['action'] != 'CLAIM_LIKELY' for o in s['platform_outcomes'])
"
check $? "default platform is none — no automated enforcement claimed"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
assert s['production']['use_context'] == 'EXPRESSIVE', s['production']['use_context']
assert s['sponsor_conflicts'] == []
assert all(f['depiction'] in (None, 'NEUTRAL') for f in s['preview'])
assert all(r['factors']['use_context_factor'] == 1.0 for r in s['risk'].values())
"
check $? "default context is EXPRESSIVE — existing runs score exactly as before"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
tiers = {k: v['tier'] for k, v in s['routes'].items()}
assert tiers['e2'] == 'SEARCH', tiers['e2']    # Coca-Cola: owner local, posture live
assert tiers['e6'] == 'STATUTE', tiers['e6']   # background face: release form
assert tiers['e8'] == 'BLOCKED', tiers['e8']   # disputed identity
assert tiers['e5'] == 'DEEP', tiers['e5']      # unknown-artist mural
assert s['routes']['e5']['enumerate_candidates'] is True
# every route must carry a reason; a cheap route is a documented position
assert all(r['rationale'] for r in s['routes'].values())
"
check $? "escalation ladder routes every finding with a recorded reason"

grep -q "Resolved without rights research" "$OUT/dossier.html"
check $? "dossier declares what was resolved without research (honesty guardrail)"

has '"material_signals"' -X POST "$BASE/api/productions/demo/freshness"
check $? "live Parallel Search freshness pass ran on demand"

grep -q "Territory exposure" "$OUT/dossier.html"; check $? "dossier reports territory exposure"
grep -q "Identity verification" "$OUT/dossier.html"; check $? "dossier reports identity verification"
grep -q "CONFLICTED" "$OUT/markers.csv"; check $? "NLE markers carry the identity verdict"

echo "━━ 6. Rights ledger + upload surfaces"
LEDGER=$(curl -sf "$BASE/api/licences" | $PY -c "import json,sys; print(len(json.load(sys.stdin)['licences']))")
[ "$LEDGER" -ge 10 ]; check $? "demo rights ledger seeded ($LEDGER licences)"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
c = {k: v['status'] for k, v in s['coverage'].items()}
assert c['e2'] == 'COVERED', c['e2']
assert c['e1'] == 'PARTIAL', c['e1']
assert c['e3'] == 'NOT_COVERED', c['e3']
assert c['e8'] == 'UNKNOWN', c['e8']
gaps = s['coverage']['e1']['gaps']
assert any('territory' in g for g in gaps) and any('media' in g for g in gaps), gaps
"
check $? "coverage: covered / gap / unlicensed / unknown all reachable"

curl -sf "$BASE/api/productions/demo" | $PY -c "
import json, sys
s = json.load(sys.stdin)
gaps = s['coverage']['e1']['gaps']
# A song needs BOTH halves. The demo holds the composition licence only.
assert any('master' in g.lower() and 'missing' in g.lower() for g in gaps), gaps
assert any('territory' in g for g in gaps) and any('media' in g for g in gaps), gaps
"
check $? "music coverage requires both composition and master licences"

CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/licences" \
  -H 'X-ClearFrame-Role: editor' -F 'file=@docs/sample-rights-ledger.csv')
[ "$CODE" = "403" ]; check $? "ledger upload role-gated (editor 403)"

has '"stored"' -X POST "$BASE/api/licences" -H 'X-ClearFrame-Role: legal' \
  -F 'file=@docs/sample-rights-ledger.csv' -F 'replace=false'
check $? "CSV rights ledger uploads and merges"

CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/productions" \
  -F 'file=@docs/sample-rights-ledger.csv' -F 'title=X')
[ "$CODE" = "409" ]; check $? "demo mode refuses footage upload honestly (409)"

[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/productions/demo/media")" = "404" ]
check $? "media endpoint 404s when no footage stored"

grep -q "Rights already held" "$OUT/dossier.html"; check $? "dossier reports rights already held"

echo "━━ 7. MCP server (stdio)"
MCP_OUT=$(printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}\n' \
  | $PY -m clearframe.mcp --out "$OUT" 2>/dev/null)
printf '%s' "$MCP_OUT" | grep -q '"clearframe"'
check $? "MCP stdio server answers initialize handshake"

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32m━━ SMOKE TEST PASSED — every transport verified ━━\033[0m\n'
else
  printf '\033[31m━━ SMOKE TEST: %d FAILURE(S) ━━\033[0m\n' "$FAILURES"
  exit 1
fi
