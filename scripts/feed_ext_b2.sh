#!/bin/bash
# Feed the second event block (2000-3999) of the extended design points.
#
# The extension (design_2001-2360) was simulated with one 2000-event block; the
# emulator study found more events per point buy 2-3% while more points buy 20-30%,
# so one block was the right call then.  Observables with larger statistical
# demands (higher flow harmonics, cumulants, event-shape selections) need the
# second block, and it is the same dictionary with a different event offset: no
# parameter changes, so events are common with the rest of the campaign.
#
# Staging already exists on the AP (scripts/stage_campaign.py --dps 2001-2360
# --offsets 2000 --jobid-template 'zr96c2_x_b2_dp{dp}', shipped to
# <aphome>/{dicts,run,submit}).  This script decides which points still need it
# and submits a tranche.
#
# Selection rules, each learned from a failure:
#   * "delivered" is >= COMPLETE tagged archives (90) -- a 100-job block yields
#     90-99, and a higher threshold resubmits a point whose block legitimately
#     ended short, on every pass;
#   * a point whose block is already queued is skipped, so the same 20 events are
#     never submitted twice;
#   * the submit file's initialdir is deleted once a point is drained, so it is
#     recreated before each submit or condor_submit fails with "No such
#     directory";
#   * the tranche stops below MAX_QUEUED, because the schedd defers submissions
#     silently at MAX_JOBS_PER_OWNER (50,000).
#
# Usage:
#   feed_ext_b2.sh                          # dry run
#   feed_ext_b2.sh --apply --tranche 120
#   feed_ext_b2.sh --apply --tranche 120 --dps 2001      # single-point canary
set -u
APPLY=0
TRANCH=120
MAXQ=40000
ONLY=""
COMPLETE=${COMPLETE:-90}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --tranche) TRANCH=$2; shift 2 ;;
    --max-queued) MAXQ=$2; shift 2 ;;
    --dps) ONLY=$2; shift 2 ;;
    *) shift ;;
  esac
done

CM=${IBEM_CM:-/tmp/opencode/cm_osg}
PROD=${IBEM_PROD:-/data/mluzum/zr96c2_results/prod}
APROOT=${IBEM_APROOT:-/home/matthew.luzum/zr96c2_prod}
STAGE=${IBEM_STAGE:-/home/matthew.luzum/zr96c2_x_b2}
LOG=/tmp/opencode/feed_ext_b2.log
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=25 osg"
mkdir -p /tmp/opencode

echo "[$(date +%H:%M)] planning (complete>=$COMPLETE, tranche=$TRANCH, maxq=$MAXQ${ONLY:+, only $ONLY})" | tee -a $LOG

if [ -n "$ONLY" ]; then
  printf "%s\n" $ONLY > /tmp/opencode/ext_b2_all.txt
else
  seq 2001 2360 > /tmp/opencode/ext_b2_all.txt
fi

# drop points whose second block is already delivered
: > /tmp/opencode/ext_b2_need.txt
while read -r dp; do
  n=$(ls "$PROD/dp$dp/tarballs"/spvn_results_e2000_*.tar.gz 2>/dev/null | wc -l)
  [ "$n" -lt "$COMPLETE" ] && echo "$dp" >> /tmp/opencode/ext_b2_need.txt
done < /tmp/opencode/ext_b2_all.txt
echo "  points still needing block 2: $(wc -l < /tmp/opencode/ext_b2_need.txt)" | tee -a $LOG

# drop points that already have this block in the queue
$SSH 'condor_q -af JobBatchName 2>/dev/null' </dev/null 2>/dev/null |
  grep -oE 'x_b2_dp[0-9]{4}' | sed 's/^x_b2_dp//' | sort -u > /tmp/opencode/ext_b2_queued.txt
comm -23 <(sort /tmp/opencode/ext_b2_need.txt) /tmp/opencode/ext_b2_queued.txt > /tmp/opencode/ext_b2_todo.txt
echo "  already queued: $(wc -l < /tmp/opencode/ext_b2_queued.txt), to submit: $(wc -l < /tmp/opencode/ext_b2_todo.txt)" | tee -a $LOG

if [ "$APPLY" = 0 ]; then
  echo "  (dry run) first 10: $(head -10 /tmp/opencode/ext_b2_todo.txt | tr '\n' ' ')" | tee -a $LOG
  exit 0
fi

cat > /tmp/opencode/ext_b2_remote.sh <<'REMOTE'
set -u
tranch=$1; maxq=$2; aproot=$3; stage=$4; list=$5
n=0; ok=0; fail=0
q=$(condor_q -af ClusterId 2>/dev/null | wc -l)
echo "  queue at start: $q (ceiling $maxq)"
while read -r dp; do
  [ -z "$dp" ] && continue
  [ "$n" -ge "$tranch" ] && { echo "  tranche reached ($n)"; break; }
  [ "$q" -ge "$maxq" ] && { echo "  queue ceiling reached ($q)"; break; }
  mkdir -p "$aproot/dp$dp" 2>/dev/null || { echo "  dp$dp MKDIR_FAIL"; fail=$((fail+1)); continue; }
  out=$(cd "$stage/submit/b1/dp$dp" && condor_submit singularity.submit 2>&1)
  if echo "$out" | grep -q "submitted to cluster"; then
    ok=$((ok+1)); n=$((n+1)); q=$((q+100))
    echo "  dp$dp $(echo "$out" | grep -o 'cluster [0-9]*')"
  else
    fail=$((fail+1)); echo "  dp$dp SUBMIT_FAIL $(echo "$out" | tail -1)"
  fi
done < "$list"
echo "  submitted=$ok failed=$fail queue_estimate=$q"
REMOTE
tar czf /tmp/opencode/ext_b2_payload.tgz -C /tmp/opencode ext_b2_remote.sh ext_b2_todo.txt 2>/dev/null
for attempt in 1 2 3; do
  $SSH "tar xzf - -C /tmp/opencode && bash /tmp/opencode/ext_b2_remote.sh $TRANCH $MAXQ $APROOT $STAGE /tmp/opencode/ext_b2_todo.txt" \
    < /tmp/opencode/ext_b2_payload.tgz >> $LOG 2>&1
  rc=$?
  tail -3 $LOG | sed 's/^/  /'
  if tail -5 $LOG | grep -q "submitted="; then break; fi
  echo "  attempt $attempt did not complete (rc=$rc); retrying in 20 s" | tee -a $LOG
  sleep 20
done
echo "[$(date +%H:%M)] tranche done" | tee -a $LOG
