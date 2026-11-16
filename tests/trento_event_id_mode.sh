#!/bin/bash
# TRENTo event-id mode: a batch must reproduce single-event runs exactly.
#
# Phase 1 of an importance-sampled campaign draws a million TRENTo events per
# design point in batches; phase 2 regenerates the selected ones one at a
# time from their event id.  The two must be the same events.  This test
# builds a TRENTo source tree, runs N events as one batch
# (--first-event-id) and as N separate runs (--random-seed=id+1, one
# configuration per file), with the new binary and with the one in the image,
# and compares every digit of the output and the entropy grids.
#
# Run inside the image, with the TRENTo source, a parameter dictionary and
# this directory mounted:
#
#   docker run --rm -e NEVENTS=300 \
#     -v <trento source>:/src:ro -v <dir with a parameter dictionary>:/par:ro \
#     -v $PWD/tests:/t:ro --entrypoint bash <image> /t/trento_event_id_mode.sh
#
# PARAM names the dictionary inside /par (default: the zr96-c2 reference point).
set -e
PARAM=${PARAM:-parameter_dictionary_design_point_583.py}
export PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=1 HOME=/tmp/w XDG_DATA_HOME=/tmp/w/.local/share XDG_CACHE_HOME=/tmp/w/.cache TRENTO_CACHE=/tmp/w/.trento
export PATH="${PATH}:/usr/lib64/openmpi/bin"
mkdir -p /tmp/w $XDG_DATA_HOME/trento $XDG_CACHE_HOME $TRENTO_CACHE /tmp/build
cp -r /src /tmp/trento_src && cd /tmp/build
cmake /tmp/trento_src -DNATIVE=OFF -DCMAKE_INSTALL_PREFIX=/tmp/inst > cmake.log 2>&1 && make -j8 > make.log 2>&1 || { tail -30 make.log; exit 1; }
NEW=/tmp/build/src/trento; OLD=/opt/iEBE-MUSIC/codes/trento_code/build/src/trento
echo "built: $(ls -la $NEW | awk '{print $5}') bytes"
cd /tmp/w && cp /par/${PARAM} .
/opt/iEBE-MUSIC/generate_jobs.py -w playground -c OSG -par ${PARAM} -id 0 -n_th 1 -n_urqmd 1 -n_hydro 20 -seed 0 --event_start_id 0 --event_end_id 0 --nocopy --continueFlag > generate.log 2>&1
cd playground/event_0 && bash ./run_trento.sh 100 > /dev/null 2>&1; cd TRENTo
N=${NEVENTS:-300}; FIRST=5000
for side in target projectile; do python3 - <<PY
import yaml
f="Isobar-Sampler_${side}/isobars-conf_${side}.yaml"
c=yaml.safe_load(open(f)); c["isobar_samples"]["number_configs"]["value"]=$N
yaml.safe_dump(c,open(f,"w"),sort_keys=False)
PY
(cd Isobar-Sampler_$side && ./build_isobars.py isobars-conf_$side.yaml > run.log 2>&1 && rm -rf ../nuclei_$side && mv nuclei_$side ..); done
python3 - <<PY
import h5py, os
for side in ("target","projectile"):
    src=h5py.File("nuclei_%s/%s.hdf"%(side,side),"r")
    os.makedirs("single_%s"%side, exist_ok=True)
    for i in range($N):
        with h5py.File("single_%s/%d.hdf"%(side,i),"w") as dst:
            for name,d in src.items():
                dst.create_dataset(name, data=d[i:i+1])
    print(side, {k:v.shape for k,v in src.items()})
PY
grep -vE "^(number-events|output|projectile)" input > base.conf
# batch, event-id mode
{ echo "projectile = nuclei_target/target.hdf"; echo "projectile = nuclei_projectile/projectile.hdf"; cat base.conf; echo "number-events = $N"; } > batch.conf
s=$(date +%s%N); $NEW -c batch.conf --first-event-id $FIRST > batch.out; e=$(date +%s%N)
echo "batch of $N in event-id mode: $(( (e - s)/1000000 )) ms, $(grep -vc '^#' batch.out) collided"
# singles, new binary and the campaign binary
: > single_new.out; : > single_old.out
for i in $(seq 0 $((N-1))); do
  { echo "projectile = single_target/$i.hdf"; echo "projectile = single_projectile/$i.hdf"; cat base.conf; echo "number-events = 1"; } > one.conf
  $NEW -c one.conf --random-seed=$((FIRST + i + 1)) | grep -v '^#' | sed -E "s/^ *0 /ID$((FIRST+i)) /" >> single_new.out || true
  $OLD -c one.conf --random-seed=$((FIRST + i + 1)) | grep -v '^#' | sed -E "s/^ *0 /ID$((FIRST+i)) /" >> single_old.out || true
done
grep -v '^#' batch.out | sed -E 's/^ *([0-9]+) /ID\1 /' > batch_norm.out
echo "lines: batch $(wc -l < batch_norm.out), single(new) $(wc -l < single_new.out), single(campaign binary) $(wc -l < single_old.out)"
cmp single_new.out single_old.out && echo "PASS  single-event mode unchanged: new binary == campaign binary"
cmp batch_norm.out single_new.out && echo "PASS  event-id batch == single-event runs, every digit"
paste -d"\n" <(head -2 batch_norm.out | cut -c1-100) <(head -2 single_new.out | cut -c1-100)
# full grids too, for a few events
mkdir -p gb gs; { cat batch.conf; echo "output = gb"; } > batchg.conf; sed -i 's/number-events = .*/number-events = 5/' batchg.conf
$NEW -c batchg.conf --first-event-id $FIRST > /dev/null
for i in 0 1 2 3 4; do { echo "projectile = single_target/$i.hdf"; echo "projectile = single_projectile/$i.hdf"; cat base.conf; echo "number-events = 1"; echo "output = gs/$i"; } > one.conf; $OLD -c one.conf --random-seed=$((FIRST + i + 1)) > /dev/null; done
n_ok=0; n_cmp=0; for i in 0 1 2 3 4; do id=$((FIRST+i)); [ -f gb/$id.dat ] && [ -f gs/$i/0.dat ] || continue; n_cmp=$((n_cmp+1)); if cmp -s <(grep -v "^#" gb/$id.dat) <(grep -v "^#" gs/$i/0.dat); then n_ok=$((n_ok+1)); else diff <(head -12 gb/$id.dat) <(head -12 gs/$i/0.dat) | head -6; fi; done; echo "entropy grids (data lines) identical: $n_ok of $n_cmp compared"; diff <(grep "^#" gb/$FIRST.dat) <(grep "^#" gs/0/0.dat) | head -4
