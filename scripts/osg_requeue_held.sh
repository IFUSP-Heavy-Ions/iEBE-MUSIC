#!/bin/bash
# Requeue held jobs by resetting their hold counter, at the end of a batch.
#
# The sweep stops retrying a job after MAX_HOLDS (3) failures, because some sites
# kill every job they are given for "memory usage exceeded" while the job reports
# its usage in KB against a MB request.  Retrying those in place is what produced
# 38 holds on single jobs, so they are left held instead -- and then recovered
# once, in bulk, when the batch is finished.
#
# Resetting NumHolds is enough: the job keeps its (design point, job index), so a
# re-run writes the same archive and the merger dedupes by event id.  That is far
# cheaper than resubmitting a whole 100-job point to recover a handful of jobs.
#
# Usage:
#   osg_requeue_held.sh                    # dry run, campaign-2 extension
#   osg_requeue_held.sh --apply
#   PATTERN='zr96c2_b1' osg_requeue_held.sh --apply
set -u
PATTERN=${PATTERN:-zr96c2_x_dp}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
CM=${IBEM_CM:-/tmp/opencode/cm_osg}
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=25"
CONSTRAINT="JobStatus == 5 && regexp(\"$PATTERN\", JobBatchName)"

held=$($SSH osg "condor_q -constraint '$CONSTRAINT' -af ClusterId ProcId 2>/dev/null" </dev/null 2>/dev/null | wc -l)
echo "held jobs matching $PATTERN: $held"
if [ "$held" -eq 0 ]; then exit 0; fi

if [ "$APPLY" = 0 ]; then
  $SSH osg "condor_q -constraint '$CONSTRAINT' -af JobBatchName NumHolds HoldReason 2>/dev/null | head -5" </dev/null 2>/dev/null
  echo "(dry run; re-run with --apply)"
  exit 0
fi

$SSH osg "condor_qedit -constraint '$CONSTRAINT' NumHolds 0 2>&1 | tail -1" </dev/null 2>/dev/null
$SSH osg "condor_release -constraint '$CONSTRAINT' 2>&1 | tail -1" </dev/null 2>/dev/null
sleep 5
left=$($SSH osg "condor_q -constraint '$CONSTRAINT' -af ClusterId 2>/dev/null | wc -l" </dev/null 2>/dev/null)
echo "requeued $((held - left)); still held: $left"
