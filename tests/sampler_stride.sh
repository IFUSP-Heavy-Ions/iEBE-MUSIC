#!/bin/bash
# Nucleus sampler: a batch with configuration_stride must equal separate calls.
#
# Companion of trento_event_id_mode.sh.  Event g uses pool addresses (2g)K and
# (2g+1)K mod 2^32; one call with stride 2K has to give, bit for bit, the
# nuclei that one call per event gives -- and the modified sampler must still
# give what the previous one gave.
#
#   docker run --rm -e NEVENTS=40 \
#     -v <Isobar-Sampler source>:/sampler:ro -v <dir with a parameter dictionary>:/par:ro \
#     -v $PWD/tests:/t:ro --entrypoint bash <image> /t/sampler_stride.sh
set -e
PARAM=${PARAM:-parameter_dictionary_design_point_583.py}
export PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=1 HOME=/tmp/w XDG_DATA_HOME=/tmp/w/.local/share XDG_CACHE_HOME=/tmp/w/.cache TRENTO_CACHE=/tmp/w/.trento
export PATH="${PATH}:/usr/lib64/openmpi/bin"
mkdir -p /tmp/w $XDG_DATA_HOME/trento $XDG_CACHE_HOME $TRENTO_CACHE; cd /tmp/w && cp /par/${PARAM} .
/opt/iEBE-MUSIC/generate_jobs.py -w playground -c OSG -par ${PARAM} -id 0 -n_th 1 -n_urqmd 1 -n_hydro 20 -seed 0 --event_start_id 0 --event_end_id 0 --nocopy --continueFlag > generate.log 2>&1
cd playground/event_0 && bash ./run_trento.sh 100 > /dev/null 2>&1; cd TRENTo
N=${NEVENTS:-40}; FIRST=${FIRST:-123456}; NEWPY=/sampler/exec/build_isobars.py
python3 - "$N" "$FIRST" "$NEWPY" <<'PY'
import sys, subprocess, shutil, os, yaml, h5py, numpy as np
N, FIRST, NEWPY = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
K, M = 2654435761, 1 << 32
def run(side, script, start, n, stride=None, out="out"):
    d = "Isobar-Sampler_%s" % side; f = "%s/isobars-conf_%s.yaml" % (d, side)
    c = yaml.safe_load(open(f))
    c["isobar_samples"]["number_configs"]["value"] = n
    c["isobar_samples"]["start_configuration"] = {"description": "", "value": int(start)}
    c["isobar_samples"].pop("configuration_stride", None)
    if stride is not None:
        c["isobar_samples"]["configuration_stride"] = {"description": "", "value": int(stride)}
    yaml.safe_dump(c, open(f, "w"), sort_keys=False)
    shutil.rmtree("%s/nuclei_%s" % (d, side), ignore_errors=True)
    subprocess.run([script, os.path.basename(f)], cwd=d, check=True, stdout=subprocess.DEVNULL)
    with h5py.File("%s/nuclei_%s/%s.hdf" % (d, side, side), "r") as h:
        return h[side][()], dict(h.attrs)
ok = True
for side, off in (("target", 0), ("projectile", 1)):
    addr = [((2 * g + off) * K) % M for g in range(FIRST, FIRST + N)]
    batch, attrs = run(side, NEWPY, addr[0], N, stride=(2 * K) % M)
    assert batch.shape[0] == N, batch.shape
    same_new = same_old = True
    for i in (list(range(N)) if N <= 60 else list(range(0, N, max(1, N // 60)))):
        one_new, _ = run(side, NEWPY, addr[i], 1)
        same_new &= np.array_equal(batch[i:i+1], one_new)
        if i < 5:
            one_old, _ = run(side, "./build_isobars.py", addr[i], 1)
            same_old &= np.array_equal(one_new, one_old)
    print("%-10s batch of %d (stride %d) == separate calls: %s | new == campaign sampler (5 checked): %s | dtype %s"
          % (side, N, (2 * K) % M, same_new, same_old, batch.dtype))
    ok &= same_new and same_old
import time
t = time.time(); run("target", NEWPY, 0, 1000, stride=(2 * K) % M); print("1000 configurations with stride: %.1f s" % (time.time() - t))
print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
PY
