#!/bin/bash
# OSG job: draw one block of event ids with scripts/draw_events.py, phase 1 of
# an importance-sampled campaign (docs/importance_sampling.md). The job runs
# inside the campaign image (container_image in the submit file); every input
# is transferred into the job directory.
#
#   osg_draws.sh FIRST_ID N PARAM [EXTRA_FILE ...]
#
# PARAM is the parameter dictionary (TRENTo must be the campaign's); EXTRA_FILE
# are files it refers to by relative path (e.g. an EoS table). Output:
# draws_<FIRST_ID>.npz in the job directory, for transfer_output_files.
# scripts/condor_draws.sh is the same job for the local pool.
set -euo pipefail
first=$1; n=$2; param=$3
shift 3
export HOME="$PWD"
mkdir -p "$HOME/.local/share" w   # TRENTo caches under $HOME/.local/share
for f in "$@"; do cp "$f" w/; done
python3 /opt/iEBE-MUSIC/scripts/draw_events.py --param "$PWD/$param" \
  --first-id "$first" --n "$n" --out "draws_$first.npz" --processes 1 \
  --workdir "$PWD/w"
