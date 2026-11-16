#!/bin/bash
# Refill the queue with batch-2 jobs for the A=96 campaign.
#
# Batch 2 (event ids 2000-3999) is one 100-job block per design point, staged on
# the AP as submit/b2/dp<NNNN>/singularity.submit.  Only ~177 of 1,000 points have
# their block delivered, so this walks the rest in tranches.
#
# Three details learned the hard way:
#   * the submit file's initialdir (<aproot>/dp<NNNN>) is deleted once a point has
#     been drained, so condor_submit fails with "No such directory" until the
#     directory is recreated -- hence the mkdir before each submit;
#   * a point whose block is already queued must be skipped, or the same 20 events
#     are computed twice (harmless to the merge, which keys groups by event id,
#     but it burns the pool);
#   * the schedd defers submissions silently once the owner is at
#     MAX_JOBS_PER_OWNER (50,000), so queue depth is checked before each point and
#     the tranche stops well below the cap.
#
# Usage:
#   feed_batch2.sh                                  # dry run
#   feed_batch2.sh --apply --tranche 150
#   feed_batch2.sh --apply --tranche 400 --max-queued 45000
set -u
APPLY=0
TRANCH=150
MAXQ=40000
# A 100-job block yields 90-99 archives (a job whose events all skip the
# freeze-out surface produces none), so "delivered" is the same 90 the merger
# uses.  A higher threshold resubmits a point whose block legitimately ended at
# 90-95, and does it again on every pass.
COMPLETE=${COMPLETE:-90}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --tranche) TRANCH=$2; shift 2 ;;
    --max-queued) MAXQ=$2; shift 2 ;;
    *) shift ;;
  esac
done

CM=${IBEM_CM:-/tmp/opencode/cm_osg}
PROD=${IBEM_PROD:-/data/mluzum/zr96c2_results/prod}
APROOT=${IBEM_APROOT:-/home/matthew.luzum/zr96c2_prod}
STAGE=${IBEM_STAGE:-/home/matthew.luzum/zr96c2_stage}
LOG=/tmp/opencode/feed2.log
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=25 osg"
mkdir -p /tmp/opencode

echo "[$(date +%H:%M)] planning (complete>=$COMPLETE, tranche=$TRANCH, maxq=$MAXQ)" | tee -a $LOG

# 1. points whose b2 block is not delivered yet, from the local archives
nice -n 19 python3 - "$PROD" "$COMPLETE" > /tmp/opencode/feed2_all.txt <<'PY'
import glob, os, sys
prod, complete = sys.argv[1], int(sys.argv[2])
for d in sorted(glob.glob(os.path.join(prod, 'dp*'))):   # dp1000 does not match dp0*
    dp = os.path.basename(d)
    try:
        n = int(dp[2:])
    except ValueError:
        continue
    if n > 1000:
        continue
    tag = len(glob.glob(os.path.join(d, 'tarballs', 'spvn_results_e2000_*.tar.gz')))
    if tag < complete:
        print("%04d" % n)
PY
echo "  points still needing batch 2: $(wc -l < /tmp/opencode/feed2_all.txt)" | tee -a $LOG

# 2. drop the ones already queued.  Held jobs do NOT count: a point whose only
#    survivors are held is otherwise 'queued' forever and never resubmitted
#    (39 of them were left with one held job and 89 removed by a condor_rm). (this is what prevents double submission)
$SSH 'condor_q -af JobBatchName JobStatus 2>/dev/null' </dev/null 2>/dev/null |
  awk '$2 != 5' | grep -oE 'b2_dp[0-9]{4}' | sed 's/^b2_dp//' | sort -u > /tmp/opencode/feed2_queued.txt
sort /tmp/opencode/feed2_all.txt | comm -23 - /tmp/opencode/feed2_queued.txt > /tmp/opencode/feed2_todo.txt
echo "  already queued: $(wc -l < /tmp/opencode/feed2_queued.txt), to submit: $(wc -l < /tmp/opencode/feed2_todo.txt)" | tee -a $LOG

if [ "$APPLY" = 0 ]; then
  echo "  (dry run) first 10: $(head -10 /tmp/opencode/feed2_todo.txt | tr '\n' ' ')" | tee -a $LOG
  exit 0
fi

# 3. submit on the AP.  The list and the loop are shipped to the AP's local /tmp
#    (a CephFS mkdir there has cost minutes under metadata pressure; /tmp does not).
cat > /tmp/opencode/feed2_remote.sh <<'REMOTE'
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
  out=$(cd "$stage/submit/b2/dp$dp" && condor_submit singularity.submit 2>&1)
  if echo "$out" | grep -q "submitted to cluster"; then
    ok=$((ok+1)); n=$((n+1)); q=$((q+100))
    echo "  dp$dp $(echo "$out" | grep -o 'cluster [0-9]*')"
  else
    fail=$((fail+1)); echo "  dp$dp SUBMIT_FAIL $(echo "$out" | tail -1)"
  fi
done < "$list"
echo "  submitted=$ok failed=$fail queue_estimate=$q"
REMOTE
tar czf - -C /tmp/opencode feed2_remote.sh feed2_todo.txt 2>/dev/null > /tmp/opencode/feed2_payload.tgz
for attempt in 1 2 3; do
  $SSH "tar xzf - -C /tmp/opencode && bash /tmp/opencode/feed2_remote.sh $TRANCH $MAXQ $APROOT $STAGE /tmp/opencode/feed2_todo.txt" \
    < /tmp/opencode/feed2_payload.tgz >> $LOG 2>&1
  rc=$?
  tail -3 $LOG | sed 's/^/  /'
  # A dropped connection truncates the stream and the remote tar never runs, so
  # "submitted=" is the only proof the tranche actually executed.
  if tail -5 $LOG | grep -q "submitted="; then break; fi
  echo "  attempt $attempt did not complete (rc=$rc); retrying in 20 s" | tee -a $LOG
  sleep 20
done
echo "[$(date +%H:%M)] tranche done" | tee -a $LOG
