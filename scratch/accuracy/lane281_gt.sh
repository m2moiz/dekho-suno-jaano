#!/bin/bash
# #281 ground-truth lane: full large-v3, `ur` decode, no speed floor.
#   scratch/accuracy/lane281_gt.sh [LANE_PID]
# PLAN_281 in run.py holds only the Apex cells, so large_v3_ur is asked for
# with --also. Waits for lane281.sh (by pid) to finish first, so the two never
# run a whisper at once. No --max-wall-x: the owner's ruling of 9 Oct 2026 puts
# the ground-truth lane under no floor, and large-v3 measured 0.50x realtime.
set -u
cd "$(dirname "$0")/../.." || exit 1
LOG=scratch/accuracy/logs281
PY=.venv/bin/python
log() { echo "$(date +%F' '%T) | $*" | tee -a "$LOG/lane.log"; }

if [ "${1:-}" ]; then
  while kill -0 "$1" 2>/dev/null; do sleep 60; done
fi
log "gt lane start | load $(sysctl -n vm.loadavg)"
$PY scratch/accuracy/run.py --plan 281 --also urdu/large_v3_ur/1 podcast/large_v3_ur/1 earnings/large_v3_ur/1 2>&1 \
  | grep -vi warning >> "$LOG/run_gt.log"
log "gt run.py exit ${PIPESTATUS[0]}"
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py table > "$LOG/table.txt" 2>&1
log "score table exit $?"
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py wall > "$LOG/wall.txt" 2>&1
log "score wall exit $?"
log "gt lane done"
