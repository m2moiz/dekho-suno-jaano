#!/bin/bash
# #281 redo: rerun every other_models.py cell whose log ends in a traceback.
#   scratch/accuracy/lane281_redo.sh [WAIT_PID]
# The 6 Nov lane lost Dolphin on all three sets (and whatever started before
# ff639dc landed) to the from_tokens crash. A cell is redone when its log holds
# "Traceback"; its old log is kept beside the new one as <cell>.crashed.log.
# Waits on WAIT_PID first (the ground-truth lane), so no two models run at once.
set -u
cd "$(dirname "$0")/../.." || exit 1
LOG=scratch/accuracy/logs281
PY=.venv/bin/python
log() { echo "$(date +%F' '%T) | $*" | tee -a "$LOG/lane.log"; }

if [ "${1:-}" ]; then
  while kill -0 "$1" 2>/dev/null; do sleep 60; done
fi
log "redo start | load $(sysctl -n vm.loadavg)"
for f in "$LOG"/*_*.log; do
  cell=$(basename "$f" .log)
  case "$cell" in fetch_*|run_*|lane*) continue;; esac
  grep -q 'Traceback' "$f" || continue
  m=${cell%_*}; s=${cell##*_}
  mv "$f" "$LOG/$cell.crashed.log"
  log "$m/$s redo start | load $(sysctl -n vm.loadavg)"
  $PY -I scratch/accuracy/other_models.py "$m" --set "$s" --max-wall-x 2.5 > "$LOG/$cell.log" 2>&1
  log "$m/$s redo exit $? | $(grep -iE 'realtime|wall|too_slow' "$LOG/$cell.log" | tail -1)"
done
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py table > "$LOG/table.txt" 2>&1
log "score table exit $?"
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py wall > "$LOG/wall.txt" 2>&1
log "score wall exit $?"
log "redo done"
