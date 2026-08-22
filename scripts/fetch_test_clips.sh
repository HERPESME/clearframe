#!/usr/bin/env bash
# Fetch a small corpus of rights-clean test footage that is dense with brands.
#
# Source: archive.org/details/ctvc — "Classic Television Commercials", released
# under Creative Commons public domain. Each spot is ~2MB, comfortably under
# Gemini's 20MB inline limit, so `--live --footage clip.mp4` works without GCS.
#
# The point worth noticing: the FILM is public domain, but the TRADEMARKS in it
# (Bayer, Jell-O, Lipton, Texaco, Playtex, Volkswagen, Zenith) are still live and
# still owned. That gap between "the footage is free" and "the marks in it are
# not" is exactly what ClearFrame exists to flag.
#
# Usage: ./scripts/fetch_test_clips.sh [dest_dir]     (default: testdata/clips)
set -euo pipefail

DEST="${1:-testdata/clips}"
BASE="https://archive.org/download/ctvc"
mkdir -p "$DEST"

# spot id -> the mark a coordinator should expect to see
CLIPS=(
  "BAYER:Bayer aspirin"
  "JELLO:Jell-O"
  "LIPTON:Lipton tea"
  "TEXACO:Texaco"
  "PLAYTEX:Playtex"
  "VWBUG:Volkswagen Beetle"
)

echo "Fetching ${#CLIPS[@]} public-domain spots into $DEST/"
for entry in "${CLIPS[@]}"; do
  id="${entry%%:*}"
  file="ctvc_${id}_512kb.mp4"
  if [ -f "$DEST/$file" ]; then
    echo "  · $file (already present)"
    continue
  fi
  if curl -sfL --max-time 180 -o "$DEST/$file" "$BASE/$file"; then
    printf '  ✓ %-28s %s\n' "$file" "$(du -h "$DEST/$file" | cut -f1)"
  else
    echo "  ✗ $file — download failed, skipping"
    rm -f "$DEST/$file"
  fi
done

# Ground truth: what a coordinator would actually flag in each spot. Used to
# score detection recall rather than eyeballing it.
cat > "$DEST/ground_truth.json" <<'JSON'
{
  "_comment": "Hand-labelled expectations for the fetched spots. 'must_find' marks are the ones a miss should count against; everything else is a bonus. Timecodes are approximate — match on label, not exact seconds.",
  "source": "https://archive.org/details/ctvc (Creative Commons public domain)",
  "clips": [
    {"file": "ctvc_BAYER_512kb.mp4",   "truth": [{"label": "Bayer", "type": "LOGO", "must_find": true}]},
    {"file": "ctvc_JELLO_512kb.mp4",   "truth": [{"label": "Jell-O", "type": "LOGO", "must_find": true}]},
    {"file": "ctvc_LIPTON_512kb.mp4",  "truth": [{"label": "Lipton", "type": "LOGO", "must_find": true}]},
    {"file": "ctvc_TEXACO_512kb.mp4",  "truth": [{"label": "Texaco", "type": "LOGO", "must_find": true}]},
    {"file": "ctvc_PLAYTEX_512kb.mp4", "truth": [{"label": "Playtex", "type": "LOGO", "must_find": true}]},
    {"file": "ctvc_VWBUG_512kb.mp4",   "truth": [{"label": "Volkswagen", "type": "LOGO", "must_find": true}]}
  ]
}
JSON

cat <<EOF

Done. $DEST now holds the clips plus ground_truth.json.

Run one live (needs CLEARFRAME_MODE=live + credentials):
  set -a && source .env && set +a
  .venv/bin/python -m clearframe run --live \\
    --footage $DEST/ctvc_TEXACO_512kb.mp4 \\
    --title "Texaco spot" --duration-s 60 --territories US,DE,FR \\
    --out out-live --auto-approve

Or upload it in the review UI once the server is running in live mode.
Load docs/sample-rights-ledger.csv first to see COVERED / gap states.
EOF
