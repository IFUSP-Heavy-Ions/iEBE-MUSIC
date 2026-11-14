#!/bin/bash
# Recover held jobs: exclude the sites that killed them, clear the hold, release.
#
# Three classes dominate the queue:
#   code 21  memory usage exceeded -- a site bug that compares MemoryUsage in KB
#            against RequestMemory in MB.  The job is fine everywhere else, which
#            is why the sweep retries it (MAX_HOLDS) and then leaves it alone:
#            releasing in place without excluding the site just holds again.
#   code  3  OnExitHold with ExitCode 85 -- the driver's 12-hour self-checkpoint
#            (checkPoint() tars the results and exits).  The submit files no
#            longer carry checkpoint_exit_code (it broke slot matching), so the
#            job is held instead of restarted; releasing runs it again.
#   code 47  exceeded the 20 h walltime.
#
# The exclusion is derived from the held jobs themselves: a host with at least
# MIN_HOLDS holds and no job of ours currently running is blacklisted (a host
# running our work right now is evidently fine, whatever it did once).
#
# The Requirements are applied in ONE transaction.  Two earlier approaches are
# deliberately not used: a per-job loop over `condor_q -af ClusterId ProcId`
# iterates over individual ids (that output is one line per job, space-separated,
# so half the values are proc numbers and 'condor_q 67' means nothing), and a
# constraint referencing Requirements (`!regexp("TARGET.Machine", Requirements)`)
# is rejected outright.  All our submit files carry the same base expression, so
# one qedit with a JobStatus constraint is both correct and immediate.
#
# Usage:
#   osg_recover_held.sh                        # dry run: what, from where
#   osg_recover_held.sh --apply
#   osg_recover_held.sh --apply --min-holds 3
#   osg_recover_held.sh --apply --extra-hosts 'warlock21\.beocat\.ksu\.edu'
set -u
APPLY=0
MIN_HOLDS=${MIN_HOLDS:-2}
EXTRA=${EXTRA:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --min-holds) MIN_HOLDS=$2; shift 2 ;;
    --extra-hosts) EXTRA=$2; shift 2 ;;
    *) shift ;;
  esac
done
CM=${IBEM_CM:-/tmp/opencode/cm_osg}
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=25 osg"
LOG=/tmp/opencode/recover.log
mkdir -p /tmp/opencode

echo "[$(date +%H:%M)] held-job recovery (min_holds=$MIN_HOLDS, apply=$APPLY)" | tee -a $LOG

# 1. derive the exclusion on the AP, keep the result locally
$SSH "python3 - $MIN_HOLDS" > /tmp/opencode/recover_excl.txt 2>/dev/null <<'PY'
import subprocess, re, collections, sys
min_holds = int(sys.argv[1])
def q(args):
    return subprocess.run(["condor_q"] + args, capture_output=True, text=True).stdout
bad = collections.Counter()
for m in re.finditer(r'^HoldReason = "(.*)"$', q(["-long", "-constraint", "JobStatus == 5"]), re.M):
    h = re.search(r'@([A-Za-z0-9._-]+):', m.group(1))
    if h:
        bad[h.group(1)] += 1
good = set()
for line in q(["-af", "JobStatus", "RemoteHost"]).splitlines():
    p = line.split()
    if len(p) == 2 and p[0] == "2" and "@" in p[1]:
        good.add(p[1].split("@")[-1])
print("")
print("|".join(sorted(h for h, c in bad.items() if c >= min_holds and h not in good)))
PY
EXCL=$(sed -n '2p' /tmp/opencode/recover_excl.txt)
[ -n "$EXTRA" ] && EXCL="${EXCL:+$EXCL|}$EXTRA"
echo "  excluded hosts: $(echo "$EXCL" | tr '|' '\n' | grep -c .)" | tee -a $LOG
$SSH 'condor_q -af JobStatus HoldReasonCode 2>/dev/null' </dev/null 2>/dev/null |
  awk '$1==5{c[$2]++} END{for(k in c) printf "%s:%d ", k, c[k]}' |
  sed 's/^/  held by code: /' | tee -a $LOG

if [ "$APPLY" = 0 ]; then
  echo "  would exclude: $(echo "$EXCL" | cut -c1-150)..." | tee -a $LOG
  $SSH "condor_q -constraint 'JobStatus == 5' -af JobBatchName ProcId HoldReason 2>/dev/null | head -5" \
    </dev/null 2>/dev/null | cut -c1-120 | sed 's/^/   /' | tee -a $LOG
  echo "  (dry run; re-run with --apply)" | tee -a $LOG
  exit 0
fi

# 2. ship the list and apply it, then release, in one AP session
tar czf - -C /tmp/opencode recover_excl.txt 2>/dev/null |
  $SSH "tar xzf - -C /tmp/opencode" </dev/null 2>/dev/null
$SSH 'bash -s' <<'REMOTE' 2>&1 | tee -a $LOG
set -u
EXCL=$(sed -n '2p' /tmp/opencode/recover_excl.txt)
BASE='((TARGET.HasSingularity && StringListIMember("stash",HasFileTransferPluginMethods)) && (TARGET.Arch == "X86_64") && TARGET.HasContainer && TARGET.HasSIF && (TARGET.Memory >= RequestMemory) && (TARGET.HasFileTransfer) && TARGET.HasSingularity && TARGET.SINGULARITY_CAN_USE_SIF)'
# An empty pattern matches every host, so !regexp("") would reject the whole
# pool.  With nothing to exclude, leave Requirements alone and just release.
if [ -n "$EXCL" ]; then
  echo "  applying the exclusion to idle and held jobs"
  condor_qedit -constraint 'JobStatus == 1 || JobStatus == 5' Requirements "$BASE && !regexp(\"$EXCL\", TARGET.Machine)" 2>&1 | tail -1
else
  echo "  no host qualifies for exclusion; leaving Requirements untouched"
fi
condor_qedit -constraint 'JobStatus == 5' NumHolds 0 2>&1 | tail -1
condor_release -constraint 'JobStatus == 5' 2>&1 | tail -1
sleep 5
echo "  still held: $(condor_q -constraint 'JobStatus == 5' -af ProcId 2>/dev/null | wc -l)"
echo "  now idle:   $(condor_q -constraint 'JobStatus == 1' -af ProcId 2>/dev/null | wc -l)"
REMOTE
echo "[$(date +%H:%M)] done" | tee -a $LOG
