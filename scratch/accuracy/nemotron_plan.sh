#!/bin/bash
# #240 Nemotron plan, one run at a time.
cd /Users/moiz/Documents/code/jaano
M='mlx-audio @ git+https://github.com/Blaizzy/mlx-audio@70f4add32911bab6f869b824864ad9f1e24dcb97'
for job in "hi-IN urdu" "hi-IN podcast" "hi-IN earnings" "auto urdu" "auto podcast" "auto earnings" "en-US earnings"; do
  set -- $job
  echo "== $1 $2 $(date +%T) load $(sysctl -n vm.loadavg)"
  uv run --with "$M" python scratch/accuracy/nemotron_run.py --language $1 --set $2 2>&1 | grep -v -i warning | tail -3
done
echo "== done $(date +%T)"
