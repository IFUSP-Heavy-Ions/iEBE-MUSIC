#!/bin/bash
# Event-list mode: an event run from a list must equal the same event run alone.
#
# Runs positions POS..POS+NEV-1 of an event list (scripts/select_events.py)
# through the full chain with IEBE_EVENT_LIST set.  Compare the resulting
# spvn_results_<id>.h5 with single-event jobs of the same ids, e.g.
#
#   python3 scripts/rerun_events_local.py --param <dictionary> --events <ids> \
#       --per-job 1 --out <dir> --variant alone --image <image>
#
# All datasets must be bit-identical, and events_drawn.csv must carry the
# weight with selection_check = match.
#
#   docker run --rm --user $(id -u):$(id -g) -e POS=0 -e NEV=2 -e LIST=<list.csv> \
#     -v $PWD:/fw:ro -v <dir with the dictionary>:/par:ro -v <dir with the list>:/list:ro \
#     -v $PWD/tests:/t:ro -v <output dir>:/out --entrypoint bash <image> /t/event_list_mode.sh
#
# PARAM names the dictionary inside /par (default: the zr96-c2 reference point).
set -e
PARAM=${PARAM:-parameter_dictionary_design_point_583.py}
export PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 HOME=/out/home XDG_DATA_HOME=/out/home/.local/share XDG_CACHE_HOME=/out/home/.cache TRENTO_CACHE=/out/home/.trento
export PATH="${PATH}:/usr/lib64/openmpi/bin:/usr/local/gsl/2.5/x86_64/bin"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/lib:/usr/local/gsl/2.5/x86_64/lib64"
mkdir -p $XDG_DATA_HOME/trento $XDG_CACHE_HOME $TRENTO_CACHE /out/job && cd /out/job
cp /par/${PARAM} .
POS=${POS:-0}; NEV=${NEV:-2}
/opt/iEBE-MUSIC/generate_jobs.py -w playground -c OSG -par ${PARAM} -id 0 -n_th 1 -n_urqmd 1 -n_hydro ${NEV} -seed 0 --event_start_id ${POS} --event_end_id ${POS} --nocopy --continueFlag > generate.log 2>&1
cd playground/event_${POS}
cp /fw/codes/hydro_plus_UrQMD_driver.py hydro_plus_UrQMD_driver.py
[ -n "${LIST}" ] && export IEBE_EVENT_LIST=/list/${LIST}
bash submit_job.script > /out/job/run.log 2>&1 || echo "driver exit $?"
grep -E "event list|differs from|MISMATCH" /out/job/run.log | head -5
mkdir -p /out/results && find . -name 'spvn_results_*.h5' -exec cp {} /out/results/ \; ; for f in $(find . -name events_drawn.csv); do cat $f; done; ls /out/results
