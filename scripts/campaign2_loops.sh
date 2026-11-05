#!/bin/bash
# Start, stop, or report every campaign-2 background loop.
#
# Everything runs under setsid so a tmux/panel/session crash cannot take it down,
# and the scripts themselves live in the repo (not /tmp), so a reboot cannot lose
# them either -- that happened once and cost the whole toolset.
#
# The loops:
#   collect     collect + prune the AP staging area, by name   (fetch_prune)
#   merge-main  re-merge every point whose source count changed
#   merge-ext   the same, scoped to dp2001-2360 so extension results appear fast
#   sweep       release memory/disk/exit holds, capped at 3 retries per job
#   guard       hold production if /home passes 120 GB
#
# Usage: campaign2_loops.sh [start|stop|status]   (default: start)
set -u
CM=${IBEM_CM:-/tmp/opencode/cm_osg}
PROD=/data/mluzum/zr96c2_results/prod
MERGED=/data/mluzum/zr96c2_results/merged
APROOT=/home/matthew.luzum/zr96c2_prod
LOGD=/tmp/opencode
mkdir -p "$LOGD"
# Bracketed so the patterns cannot match this script's own command line.
PATS=('campaign2_loop[s]' 'osg_fetch_prun[e]\.sh' 'consolidate_dp[s]\.sh'
      'osg_memory_swee[p]' 'osg_home_guar[d]')

count() { local n=0; for p in "${PATS[@]}"; do n=$((n + $(pgrep -cf "$p"))); done; echo "$n"; }

status() {
  for p in "${PATS[@]}"; do printf "  %-26s %s\n" "$p" "$(pgrep -cf "$p")"; done
  echo "  --- logs ---"
  for f in collect.log merge-main.log merge-ext.log sweeps.log home_guard.log; do
    printf "  %-16s %s | %s\n" "$f" \
      "$(ls -l --time-style=+%H:%M $LOGD/$f 2>/dev/null | awk '{print $6}')" \
      "$(tail -1 $LOGD/$f 2>/dev/null | cut -c1-58)"
  done
  echo "  --- AP ---"
  ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=20 osg \
    'echo "  home=$(quota -s 2>/dev/null | awk "\$1==\"/dev/md9\"{print \$2}")  idle=$(condor_q -af JobStatus 2>/dev/null | grep -c "^1$")  running=$(condor_q -af JobStatus 2>/dev/null | grep -c "^2$")  held=$(condor_q -af JobStatus 2>/dev/null | grep -c "^5$")"' \
    </dev/null 2>/dev/null
  echo "  --- local ---"
  echo "  merged=$(ls $MERGED 2>/dev/null | grep -c '^dp')  raw=$(ls $PROD 2>/dev/null | wc -l)"
  return 0
}

stop() {
  pkill -f 'campaign2_loop[s]' 2>/dev/null
  pkill -f 'osg_fetch_prun[e]\.sh' 2>/dev/null
  pkill -f 'consolidate_dp[s]\.sh' 2>/dev/null
  pkill -f 'osg_memory_swee[p]' 2>/dev/null
  pkill -f 'osg_home_guar[d]' 2>/dev/null
  sleep 3
  echo "stopped; remaining: $(count)"
}

case "${1:-start}" in
  status) status; exit 0 ;;
  stop) stop; exit 0 ;;
esac

stop
cd /data/mluzum/GeSe || exit 1

# 1. collect + prune the AP staging area
setsid nohup bash -c 'while true; do
    IBEM_BASE='"$APROOT"' IBEM_LOCAL='"$PROD"' IBEM_CM='"$CM"' \
      timeout 5400 bash /data/mluzum/GeSe/scripts/osg_fetch_prune.sh 1 2360 4 \
      >> '"$LOGD"'/collect.log 2>&1
    echo "[$(date +%H:%M)] sweep done; merged=$(ls '"$MERGED"' | grep -c "^dp")" >> '"$LOGD"'/collect.log
    sleep 600
  done' > /dev/null 2>&1 < /dev/null &
echo "  started collect"

# 2. main merge loop (all points)
setsid nohup bash -c 'while true; do
    nice -n 19 ionice -c3 env IBEM_PROD='"$PROD"' IBEM_OUT='"$MERGED"' \
      timeout 21600 bash /data/mluzum/GeSe/scripts/consolidate_dps.sh \
      >> '"$LOGD"'/merge-main.log 2>&1
    echo "[$(date +%H:%M)] pass done merged=$(ls '"$MERGED"' | grep -c "^dp")" >> '"$LOGD"'/merge-main.log
    sleep 900
  done' > /dev/null 2>&1 < /dev/null &
echo "  started merge-main"

# 3. extension-scoped merge (so dp2001+ does not wait behind 1,000 points)
setsid nohup bash -c 'while true; do
    nice -n 19 ionice -c3 env IBEM_PROD='"$PROD"' IBEM_OUT='"$MERGED"' IBEM_ONLY="dp2*" \
      timeout 7200 bash /data/mluzum/GeSe/scripts/consolidate_dps.sh \
      >> '"$LOGD"'/merge-ext.log 2>&1
    echo "[$(date +%H:%M)] ext pass done ext=$(ls '"$MERGED"' | grep -c "^dp2")" >> '"$LOGD"'/merge-ext.log
    sleep 600
  done' > /dev/null 2>&1 < /dev/null &
echo "  started merge-ext"

# 4. hold sweep
setsid nohup bash -c 'while true; do sleep 1800
    echo "--- sweep $(date +%H:%M) ---"
    timeout 300 ssh -o ControlMaster=auto -o ControlPath='"$CM"' -o ConnectTimeout=20 osg \
      python3 - < /data/mluzum/GeSe/scripts/osg_memory_sweep.py 2>&1 | tail -3
  done' > "$LOGD/sweeps.log" 2>&1 < /dev/null &
echo "  started sweep"

# 5. /home quota guard
setsid nohup bash /data/mluzum/GeSe/scripts/osg_home_guard.sh \
  > "$LOGD/home_guard.log" 2>&1 < /dev/null &
echo "  started guard"

sleep 20
echo "running loop processes: $(count)"
