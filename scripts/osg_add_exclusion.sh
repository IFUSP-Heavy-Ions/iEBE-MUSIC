#!/bin/bash
# Append a host exclusion to the Requirements of matching jobs.  Runs entirely on
# the access point: doing this through nested ssh/xargs quoting silently produced
# "applied to N jobs" while changing nothing.
#
# Usage: add_exclusion.sh '<regex>' "<condor constraint>" [--dry-run]
set -u
EXCL=${1:?exclusion regex required}
CONSTRAINT=${2:?condor constraint required}
DRY=0
[ "${3:-}" = "--dry-run" ] && DRY=1

n_ok=0; n_fail=0; n_skip=0
condor_q -constraint "$CONSTRAINT" -af ClusterId ProcId 2>/dev/null | while read -r c p; do
  [ -z "${c:-}" ] && continue
  j="$c.$p"
  R=$(condor_q "$j" -long 2>/dev/null | sed -n 's/^Requirements = //p')
  if [ -z "$R" ]; then echo "  $j SKIP (no Requirements)"; continue; fi
  case "$R" in
    *"TARGET.Machine"*) continue ;;   # already excluded
  esac
  NEW="($R) && !regexp(\"$EXCL\", TARGET.Machine)"
  if [ "$DRY" = 1 ]; then
    echo "  $j would set: ...&& !regexp(<$EXCL>)"
  else
    condor_qedit "$j" Requirements "$NEW" >/dev/null 2>&1 && echo "  $j ok" || echo "  $j FAILED"
  fi
done | tail -5
echo "done (dry=$DRY)"
