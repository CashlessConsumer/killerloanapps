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
LOCK="data/.refresh.lock"
mkdir -p data

# issue #3: single writer + fail-loud. A 2026-09-28 run died at the availability
# recheck leaving a dirty tree and a truncated log with no failure marker.
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  echo "refresh already running (pid $(cat "$LOCK")); refusing to race" && exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "=== FAILED: dirty working tree (commit or clean before refreshing) ===" | tee -a "$LOG"
  exit 1
fi

step() { # step <name> <cmd...> — runs, and on failure writes an explicit marker then aborts
  local name="$1"; shift
  echo "--- $name ---"
  if ! "$@"; then
    echo "=== FAILED at step: $name ===" | tee -a "$LOG"
    exit 1
  fi
}

{
  echo "=== killerloanapps refresh $LABEL · $(date -u +%FT%TZ) ==="
  if [ "$SKIP_HARVEST" = "1" ]; then
    echo "--- harvest skipped (SKIP_HARVEST=1) ---"
  else
    for cc in $LIVE_CC; do
      # seeded harvest + staging host: corpus verification needs ~2 req/app, past prod limits
      step "harvest $cc" env GPLAY_BASE="${GPLAY_BASE:-https://gplayapidev.fly.dev}" \
        python3 scripts/harvest.py --country "$cc" --label "$LABEL" --seed
    done
  fi
  step "warehouse" python3 scripts/build_warehouse.py
  step "availability recheck" python3 scripts/check_deletions.py
  step "score" python3 scripts/score.py
  step "site" python3 scripts/build_site.py
  echo "--- publish ---"
  git add -A
  if git diff --cached --quiet; then
    echo "no changes to publish"
  else
    VERDICTS="$(duckdb data/killerloanapps.duckdb -noheader -list -c "SELECT jurisdiction || ':' || status || '=' || COUNT(*) FROM availability GROUP BY 1,2 ORDER BY 1,2" | paste -sd' ' -)"
    git -c user.name="CashlessConsumer" -c user.email="cashlessconsumerin@gmail.com" \
      commit -q -m "refresh $LABEL: harvest live corpora + availability + scores" \
      -m "availability: $VERDICTS"
    git push -q origin main
    echo "pushed $(git rev-parse --short HEAD)"
  fi
  echo "=== done ==="
} 2>&1 | tee -a "$LOG"
