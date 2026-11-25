#!/bin/bash
# OSG job: one scripts/draw_events.py call, phase 1 of an importance-sampled
# campaign (docs/importance_sampling.md). The job runs inside the campaign
# image (container_image in the submit file); every input is transferred into
# the job directory.
#
#   osg_draws.sh TAG PARAM [EXTRA_FILE ...] -- DRAW_EVENTS_ARGS ...
#   e.g. osg_draws.sh s0 template.py eos.dat -- --pool-slots 0 2048 --pool-q 58
#        osg_draws.sh 0 template.py eos.dat -- --first-id 0 --n 10000
#
# PARAM is the parameter dictionary (TRENTo must be the campaign's); EXTRA_FILE
# are files it refers to by relative path (e.g. an EoS table). Output:
# draws_<TAG>.npz in the job directory, for transfer_output_files.
# scripts/condor_draws.sh is the id-block job for the local pool.
set -euo pipefail
tag=$1; param=$2
shift 2
export HOME="$PWD"
mkdir -p "$HOME/.local/share" w   # TRENTo caches under $HOME/.local/share
while [[ $# -gt 0 && "$1" != "--" ]]; do cp "$1" w/; shift; done
[[ "${1:-}" == "--" ]] || { echo "usage: $0 TAG PARAM [FILE ...] -- ARGS" >&2; exit 2; }
shift
python3 /opt/iEBE-MUSIC/scripts/draw_events.py --param "$PWD/$param" \
  --out "draws_$tag.npz" --processes 1 --workdir "$PWD/w" "$@"
