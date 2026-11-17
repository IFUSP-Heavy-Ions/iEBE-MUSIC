#!/usr/bin/env python3
"""Phase 1 of an importance-sampled campaign: draw initial conditions in bulk.

For a block of global event ids this generates the nuclei and runs TRENTo --
nothing else -- and records, per event, the impact parameter and the total
initial multiplicity that the event selection is based on.  It does so in
batches (one sampler call and one TRENTo call per thousand events), which
costs about 0.2 CPU-seconds per event for A = 96 -- nearly all of it the
nucleus sampler, at 0.1 s per nucleus -- against 1.4 s when each event starts
its own processes.

The events are *the same events* the full chain later regenerates one at a
time from their ids: the sampler's `configuration_stride` and TRENTo's
`--first-event-id` exist for that, and tests/sampler_stride.sh and
tests/trento_event_id_mode.sh check it digit for digit.

Run inside the image (it needs generate_jobs.py, the sampler and TRENTo):

    python3 scripts/draw_events.py --param <parameter dictionary> \\
        --first-id 0 --n 1000000 --out draws_dp0001_0.npz

Output (npz), one row per drawn id, including the ones that never collide:
    event_id, b (nan if no collision), npart, mult, entropy
and scalars: b_max, master_seed, first_id, n.  `mult` is the quantity
events_drawn.csv calls `mult`.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Event g uses nucleus pool addresses (2g)K and (2g+1)K mod 2**32
# (generate_jobs.py, run_trento.sh): an arithmetic progression of stride 2K.
WEYL = 2654435761
MODULUS = 1 << 32


def make_job_folder(param, workdir, framework):
    """Let generate_jobs.py lay out one event folder; return its TRENTo dir."""
    shutil.copy(param, workdir)
    subprocess.run([
        sys.executable,
        os.path.join(framework, "generate_jobs.py"), "-w", "playground", "-c",
        "OSG", "-par",
        os.path.basename(param), "-id", "0", "-n_th", "1", "-n_urqmd", "1",
        "-n_hydro", "1", "-seed", "0", "--event_start_id", "0",
        "--event_end_id", "0", "--nocopy", "--continueFlag"
    ],
                   cwd=workdir,
                   check=True,
                   stdout=subprocess.DEVNULL)
    return os.path.join(workdir, "playground", "event_0", "TRENTo")


def sample_nuclei(trento_dir, side, first_id, n, sampler, processes=1):
    """One sampler call for the nuclei of events first_id .. first_id+n-1."""
    folder = os.path.join(trento_dir, "Isobar-Sampler_" + side)
    conf_file = "isobars-conf_{}.yaml".format(side)
    path = os.path.join(folder, conf_file)
    with open(path) as fh:
        conf = yaml.safe_load(fh)
    offset = 0 if side == "target" else 1
    samples = conf["isobar_samples"]
    samples["number_configs"]["value"] = int(n)
    # The job templates ask the sampler for every core it can see (-1).  A
    # drawer is one of many on a node, or a one-core grid job: be explicit.
    samples["number_of_parallel_processes"] = {
        "description": "Number of processes to compute in parallel.",
        "value": int(processes),
    }
    samples["start_configuration"] = {
        "description": "Pool address of the first configuration",
        "value": int(((2 * first_id + offset) * WEYL) % MODULUS),
    }
    samples["configuration_stride"] = {
        "description": "Address step between configurations (2K mod 2**32)",
        "value": int((2 * WEYL) % MODULUS),
    }
    with open(path, "w") as fh:
        yaml.safe_dump(conf, fh, sort_keys=False)
    out = os.path.join(trento_dir, "nuclei_" + side)
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(os.path.join(folder, "nuclei_" + side), ignore_errors=True)
    proc = subprocess.Popen([sampler or "./build_isobars.py", conf_file],
                            cwd=folder,
                            stdout=subprocess.DEVNULL)
    return proc, os.path.join(folder, "nuclei_" + side), out, int(
        samples["master_seed"]["value"])


def run_batch(trento_dir, first_id, n, trento, sampler, processes=1):
    jobs = []
    for side in ("target", "projectile"):
        jobs.append(
            sample_nuclei(trento_dir, side, first_id, n, sampler, processes))
        if processes == 1:
            # one core: one nucleus at a time
            jobs[-1][0].wait()
    for proc, produced, wanted, _ in jobs:
        if proc.wait() != 0:
            raise RuntimeError("nucleus sampler failed")
        shutil.move(produced, wanted)
    master_seed = jobs[0][3]

    b_max = None
    with open(os.path.join(trento_dir, "input")) as fh, open(
            os.path.join(trento_dir, "batch.conf"), "w") as out:
        for line in fh:
            key = line.split("=")[0].strip()
            if key in ("number-events", "output"):
                continue
            if key == "b-max":
                b_max = float(line.split("=")[1])
            out.write(line)
    res = subprocess.run([
        trento or "./trento", "-c", "batch.conf", "--number-events",
        str(n), "--first-event-id",
        str(first_id)
    ],
                         cwd=trento_dir,
                         check=True,
                         capture_output=True,
                         text=True)
    b = np.full(n, np.nan)
    npart = np.zeros(n, dtype=np.int32)
    mult = np.zeros(n)
    entropy = np.zeros(n)
    for line in res.stdout.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        col = line.split()
        i = int(col[0]) - first_id
        b[i], npart[i] = float(col[1]), int(col[2])
        mult[i], entropy[i] = float(col[3]), float(col[4])
    return b, npart, mult, entropy, b_max, master_seed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--param", required=True, help="parameter dictionary")
    ap.add_argument("--first-id", type=int, required=True)
    ap.add_argument("--n", type=int, required=True, help="number of event ids")
    ap.add_argument(
        "--chunk",
        type=int,
        default=1000,
        help="events per sampler/TRENTo call.  At most 2000: the sampler "
        "records each configuration's deformation in HDF5 attributes, which "
        "hold 64 kB")
    ap.add_argument("--out", required=True, help="output .npz")
    ap.add_argument("--trento", help="TRENTo binary (default: the image's)")
    ap.add_argument("--sampler",
                    help="build_isobars.py (default: the image's)")
    ap.add_argument("--workdir", help="scratch directory (default: a temp dir)")
    ap.add_argument("--processes",
                    type=int,
                    default=1,
                    help="cores the nucleus sampler may use (default 1)")
    ap.add_argument("--framework",
                    default=REPO,
                    help="framework root holding generate_jobs.py and the "
                    "compiled codes (default: where this script lives)")
    args = ap.parse_args()

    if not 1 <= args.chunk <= 2000:
        ap.error("--chunk must be between 1 and 2000")
    t0 = time.time()
    workdir = args.workdir or tempfile.mkdtemp(prefix="draw_events_")
    os.makedirs(workdir, exist_ok=True)
    trento_dir = make_job_folder(os.path.abspath(args.param), workdir,
                                 args.framework)
    parts = []
    b_max = master_seed = None
    for start in range(args.first_id, args.first_id + args.n, args.chunk):
        n = min(args.chunk, args.first_id + args.n - start)
        *arrays, b_max, master_seed = run_batch(trento_dir, start, n,
                                                args.trento, args.sampler,
                                                args.processes)
        parts.append(arrays)
    b, npart, mult, entropy = (np.concatenate(x) for x in zip(*parts))
    np.savez_compressed(args.out,
                        event_id=np.arange(args.first_id,
                                           args.first_id + args.n,
                                           dtype=np.int64),
                        b=b,
                        npart=npart,
                        mult=mult,
                        entropy=entropy,
                        b_max=b_max,
                        master_seed=master_seed,
                        first_id=args.first_id,
                        n=args.n)
    if not args.workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    dt = time.time() - t0
    print("drew {} events ({} collided) in {:.0f} s = {:.1f} ms/event -> {}".
          format(args.n, int(np.sum(mult > 0)), dt, 1e3 * dt / args.n,
                 args.out))


if __name__ == "__main__":
    main()
