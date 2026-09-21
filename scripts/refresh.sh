#!/usr/bin/env bash
# killerloanapps refresh — the whole cycle in one command.
#
#   scripts/refresh.sh [LABEL]        # LABEL defaults to today (YYYY-MM-DD)
#
# Steps: harvest live jurisdictions -> rebuild warehouse -> availability recheck ->
# rescore -> rebuild site -> commit + push (GH Pages workflow deploys).
# Historical corpora are frozen; they are never re-harvested, only re-linked.
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL="${1:-$(date +%F)}"
LIVE_CC="${LIVE_CC-in lk}"
SKIP_HARVEST="${SKIP_HARVEST:-0}"
LOG="data/refresh-${LABEL}.log"
mkdir -p data

{
  echo "=== killerloanapps refresh $LABEL · $(date -u +%FT%TZ) ==="
  if [ "$SKIP_HARVEST" = "1" ]; then
    echo "--- harvest skipped (SKIP_HARVEST=1) ---"
  else
    for cc in $LIVE_CC; do
      echo "--- harvest $cc ---"
      python3 scripts/harvest.py --country "$cc" --label "$LABEL"
    done
  fi
  echo "--- warehouse ---"
  python3 scripts/build_warehouse.py
  echo "--- availability recheck (live corpora) ---"
  python3 scripts/check_deletions.py
  echo "--- score ---"
  python3 scripts/score.py
  echo "--- site ---"
  python3 scripts/build_site.py
  echo "--- publish ---"
  git add -A
  if git diff --cached --quiet; then
    echo "no changes to publish"
  else
    git -c user.name="CashlessConsumer" -c user.email="cashlessconsumerin@gmail.com" \
      commit -q -m "refresh $LABEL: harvest live corpora + availability + scores"
    git push -q origin main
    echo "pushed $(git rev-parse --short HEAD)"
  fi
  echo "=== done ==="
} 2>&1 | tee -a "$LOG"
