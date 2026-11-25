#!/bin/bash
# HTCondor job (local pool): draw one block of event ids with
# scripts/draw_events.py inside the image, phase 1 of an importance-sampled
# campaign (docs/importance_sampling.md).
#
#   condor_draws.sh FIRST_ID N PARAM OUT_DIR IMAGE [EXTRA_FILE ...]
#
# PARAM is the parameter dictionary (TRENTo must be the campaign's); EXTRA_FILE
# are files it refers to by relative path (e.g. an EoS table), copied next to
# it. The scratch is the node's job directory; the table goes to
# OUT_DIR/draws_<FIRST_ID>.npz over NFS, renamed into place only when complete,
# so a block either exists whole or not at all.
set -euo pipefail
first=$1; n=$2; param=$3; out=$4; image=$5
shift 5
scratch=${_CONDOR_SCRATCH_DIR:-$PWD}/draws_$first
mkdir -p "$scratch/w" "$scratch/.local/share"   # TRENTo caches under $HOME/.local/share
cp "$param" "$scratch/"
for f in "$@"; do cp "$f" "$scratch/w/"; done
final="$out/draws_$first.npz"
[[ -e "$final" ]] && { echo "$final exists; nothing to do"; exit 0; }
singularity exec --contain -B /data/mluzum -B "$scratch" --env HOME="$scratch" "$image" \
  python3 /opt/iEBE-MUSIC/scripts/draw_events.py --param "$scratch/$(basename "$param")" \
  --first-id "$first" --n "$n" --out "$scratch/draws_$first.npz" --processes 1 \
  --workdir "$scratch/w"
cp "$scratch/draws_$first.npz" "$out/.draws_$first.npz.part"
mv "$out/.draws_$first.npz.part" "$final"
echo "wrote $final"
