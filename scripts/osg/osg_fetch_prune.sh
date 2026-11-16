#!/bin/bash
# Fetch what is missing for a design point and delete the AP copies in the same
# pass.
#
# No file is opened twice and nothing is decompressed to prove it arrived:
#
#   * one remote `ls` gives the names (metadata only, no reads);
#   * the names already present locally need no transfer at all;
#   * the rest go over in a single tar stream, and the stream's own exit status
#     is the integrity check -- a truncated or failed read makes tar fail, which
#     is why the delete is conditional on it;
#   * every remote name is then removed with one `rm`, using explicit names, so
#     no second listing is needed.
#
# This replaces the separate pull-then-prune pair, whose cost was dominated by
# `tar tzf` on every local archive (~40 s per design point of decompression) plus
# a second metadata sweep.
#
# Usage: IBEM_BASE=... IBEM_LOCAL=... osg_fetch_prune.sh START END [WORKERS]
set -u
BASE=${IBEM_BASE:?IBEM_BASE required}
LOCAL=${IBEM_LOCAL:?IBEM_LOCAL required}
S=${1:-1}; E=${2:-$S}; PAR=${3:-2}
CM=${IBEM_CM:-/tmp/opencode/cm_osg}
SSH="ssh -o ControlMaster=auto -o ControlPath=$CM -o ConnectTimeout=20 osg"

one() {
  i=$1
  dp=$(printf 'dp%04d' "$i")
  dest=$LOCAL/$dp/tarballs
  mkdir -p "$dest" || { echo "$dp MKDIR_FAIL"; return; }

  rlist=$($SSH "find $BASE/$dp -maxdepth 1 -name '*.tar.gz' -printf '%s %p\n' 2>/dev/null || true" </dev/null 2>/dev/null)
  [ -z "$rlist" ] && { echo "$dp no_remote"; return; }

  # A job whose packing step died leaves a 0-byte archive behind.  It carries no
  # data, it can never pass the non-empty check below, and keeping it means the
  # point is never pruned (the delete happens after the check) and never merged
  # (the merge aborts on the bad tar, so the whole design point is lost).  Drop it
  # on both sides and say so, so the job can be re-run deliberately.
  missing=""; names=""; n_miss=0; n_have=0; empty=""; n_empty=0
  while read -r sz f; do
    [ -z "$f" ] && continue
    b=${f##*/}
    if [ "$sz" -eq 0 ]; then empty="$empty $b"; n_empty=$((n_empty+1)); continue; fi
    names="$names $b"
    if [ -s "$dest/$b" ]; then n_have=$((n_have+1)); else missing="$missing $b"; n_miss=$((n_miss+1)); fi
  done <<< "$rlist"

  if [ "$n_empty" -gt 0 ]; then
    $SSH "cd $BASE/$dp && rm -f $empty" </dev/null 2>/dev/null
    for b in $empty; do rm -f "$dest/$b"; done
    echo "$dp REMOTE_EMPTY n=$n_empty$empty"
  fi
  [ -z "$names" ] && return

  if [ "$n_miss" -gt 0 ]; then
    if ! $SSH "cd $BASE/$dp && tar cf - $missing" </dev/null > "$dest/.incoming.tar" 2>/dev/null; then
      echo "$dp STREAM_FAIL n=$n_miss"; rm -f "$dest/.incoming.tar"; return
    fi
    if ! tar xf "$dest/.incoming.tar" -C "$dest" 2>/dev/null; then
      echo "$dp EXTRACT_FAIL n=$n_miss"; rm -f "$dest/.incoming.tar"; return
    fi
    rm -f "$dest/.incoming.tar"
    # every arrived file must be non-empty before anything is deleted remotely
    for b in $missing; do
      [ -s "$dest/$b" ] || { echo "$dp ARRIVAL_FAIL $b"; return; }
    done
  fi

  # all remote names are now present locally: delete them by name, one call
  if $SSH "cd $BASE/$dp && rm -f $names" </dev/null 2>/dev/null; then
    echo "$dp ok fetched=$n_miss already=$n_have removed=$((n_miss+n_have))"
  else
    echo "$dp RM_FAIL fetched=$n_miss"
  fi
}
export -f one
export BASE LOCAL SSH
seq "$S" "$E" | xargs -P "$PAR" -I{} bash -c 'one {}'
echo FETCH_PRUNE_DONE
