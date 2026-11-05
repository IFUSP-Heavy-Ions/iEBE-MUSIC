#!/bin/bash
# Hold production if the AP /home staging area approaches its quota.
#
# /home has a 150 GB quota (160 GB hard).  When it fills, output transfers fail
# and jobs go on hold for the wrong reason, so the throttle is placed on
# production rather than on the transfer: holding idle jobs stops new work from
# starting within seconds, while the jobs already running finish and drain.
#
# Only jobs this script held are released again (hold reason code 1), so memory
# and disk holds managed by the sweep are never touched.
#
#   HOLD_AT  GB used on /home that stops new jobs   (default 120)
#   FREE_AT  GB used on /home that resumes them     (default 105)
set -u
HOLD_AT=${HOLD_AT:-120}
FREE_AT=${FREE_AT:-105}
PATTERN=${PATTERN:-iEBEMUSIC_zr96c2_}
CM=${IBEM_CM:-/tmp/opencode/cm_osg}
LOG=${LOG:-/tmp/opencode/home_guard.log}
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=20 osg"

throttled=0
while true; do
  raw=$($SSH 'quota -s 2>/dev/null | awk "\$1==\"/dev/md9\"{print \$2}"' </dev/null 2>/dev/null | tr -d '\r')
  case "$raw" in
    *G) used=$(echo "${raw%G}" | cut -d. -f1) ;;
    *M) used=$(( $(echo "${raw%M}" | cut -d. -f1) / 1024 )) ;;
    *)  echo "[$(date +%H:%M)] query failed ('$raw')" >> $LOG; sleep 300; continue ;;
  esac

  if [ "$throttled" = 0 ] && [ "$used" -ge "$HOLD_AT" ]; then
    n=$($SSH "condor_hold -constraint 'JobStatus == 1 && regexp(\"$PATTERN\", JobBatchName)' 2>&1 | tail -1" </dev/null 2>/dev/null)
    echo "[$(date +%H:%M)] home=${used}G >= ${HOLD_AT}G -> THROTTLE ON: $n" >> $LOG
    throttled=1
  elif [ "$throttled" = 1 ] && [ "$used" -le "$FREE_AT" ]; then
    n=$($SSH "condor_release -constraint 'JobStatus == 5 && HoldReasonCode == 1 && regexp(\"$PATTERN\", JobBatchName)' 2>&1 | tail -1" </dev/null 2>/dev/null)
    echo "[$(date +%H:%M)] home=${used}G <= ${FREE_AT}G -> THROTTLE OFF: $n" >> $LOG
    throttled=0
  else
    echo "[$(date +%H:%M)] home=${used}G state=$([ $throttled = 1 ] && echo throttled || echo running)" >> $LOG
  fi
  sleep 600
done
