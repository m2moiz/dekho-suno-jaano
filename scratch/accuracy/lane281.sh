#!/bin/bash
# #281 lane: every candidate to completion, one cell at a time, each logged.
#   scratch/accuracy/lane281.sh            # from the bench-281 worktree
# Order: the whisper cells run.py --plan 281 holds (Apex in both modes on urdu
# and earnings, large_v3_ur once scratch/models/dl/mlx-community--whisper-large-v3-mlx
# exists), then the three sherpa-onnx CTC models from other_models.py on every
# set they can read, then the scorer's table. The only cap is the owner's
# ruling of 9 Oct 2026: a run is stopped past 2.5x the recording's length.
# Awaaz and Qwen3 are not in this lane: convert_finetunes.py has no awaaz
# target and other_models.py has no qwen3 decoder (noted on #281).
# Everything a run writes is already ignored (runs/, logs281/, models/).
set -u
cd "$(dirname "$0")/../.." || exit 1
LOG=scratch/accuracy/logs281
PY=.venv/bin/python
mkdir -p "$LOG"

log() { echo "$(date +%F' '%T) | $*" | tee -a "$LOG/lane.log"; }

log "lane start | load $(sysctl -n vm.loadavg) | free $(df -h /System/Volumes/Data | awk 'NR==2{print $4}')"

log "run.py --plan 281 start"
$PY scratch/accuracy/run.py --plan 281 --max-wall-x 2.5 2>&1 | grep -vi warning >> "$LOG/run_plan281.log"
log "run.py --plan 281 exit ${PIPESTATUS[0]}"

for m in dolphin omni1b; do
  for s in podcast urdu earnings; do
    log "$m/$s start | load $(sysctl -n vm.loadavg)"
    $PY -I scratch/accuracy/other_models.py "$m" --set "$s" --max-wall-x 2.5 > "$LOG/${m}_${s}.log" 2>&1
    log "$m/$s exit $? | $(grep -iE 'realtime|wall|too_slow' "$LOG/${m}_${s}.log" | tail -1)"
  done
done
for m in indicconformer_ctc indicconformer_rnnt; do
  for s in podcast urdu; do
    log "$m/$s start | load $(sysctl -n vm.loadavg)"
    $PY -I scratch/accuracy/other_models.py "$m" --set "$s" --max-wall-x 2.5 > "$LOG/${m}_${s}.log" 2>&1
    log "$m/$s exit $? | $(grep -iE 'realtime|wall|too_slow' "$LOG/${m}_${s}.log" | tail -1)"
  done
done

log "score table start"
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py table > "$LOG/table.txt" 2>&1
log "score table exit $?"
uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py wall > "$LOG/wall.txt" 2>&1
log "score wall exit $?"
log "lane done"
