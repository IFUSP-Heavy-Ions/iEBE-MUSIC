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

With control_dict['nucleus_pool_size'] = M the chain reuses nuclei: event
g = q*M + r takes target slot r and projectile slot (r + q) mod M of a pool of
M configurations per side, each use rotated at random by TRENTo (seeded by the
event id).  Fresh nuclei cost about 0.2-0.5 s each against 6 ms for a TRENTo
event, so draw such a campaign by slots, not by id blocks:

    python3 scripts/draw_events.py --param <dictionary> \\
        --pool-slots 0 2048 --pool-q 58 --out draws_pool_0.npz

samples target slots [0, 2048) and projectile slots [0, 2048 + 57) once and
runs events q*M + r for every q < 58 and r in [0, 2048): 2 nuclei per 58
events instead of 2 per event.  Jobs with disjoint slot ranges draw disjoint
events; together, ranges covering [0, M) draw ids [0, 58 M).

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

import importlib.util

import h5py
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
    return run_trento_batch(trento_dir, first_id, n, trento) + (master_seed,)


def run_trento_batch(trento_dir, first_id, n, trento):
    """TRENTo on the configurations already in nuclei_target/ and
    nuclei_projectile/ (one per event, in event order), ids first_id..+n-1."""
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
    return b, npart, mult, entropy, b_max


def pool_size_of(param):
    """control_dict['nucleus_pool_size'] of a parameter file, or None."""
    spec = importlib.util.spec_from_file_location("draw_param", param)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    value = getattr(mod, "control_dict", {}).get("nucleus_pool_size")
    return int(value) if value else None


def sample_slots(trento_dir, side, slots, sampler, processes, chunk):
    """Configurations of pool slots `slots` (consecutive mod M), in that order.

    Returns (positions [len(slots), A, 3] float32, dataset name, file name,
    master seed).  One sampler call per run of at most `chunk` consecutive
    slots: the same addresses (2s + side) K as the chain's run_trento.sh.
    """
    slots = np.asarray(slots, dtype=np.int64)
    breaks = np.nonzero(np.diff(slots) != 1)[0] + 1
    parts, name, fname, seed = [], None, None, None
    for run in np.split(slots, breaks):
        for i in range(0, len(run), chunk):
            s0, n = int(run[i]), int(min(chunk, len(run) - i))
            proc, produced, wanted, seed = sample_nuclei(
                trento_dir, side, s0, n, sampler, processes)
            if proc.wait() != 0:
                raise RuntimeError("nucleus sampler failed")
            fname = sorted(f for f in os.listdir(produced)
                           if f.endswith(".hdf"))[0]
            with h5py.File(os.path.join(produced, fname), "r") as f:
                name = next(iter(f.keys()))
                parts.append(f[name][()])
            shutil.rmtree(produced)
    return np.concatenate(parts), name, fname, seed


def write_configs(trento_dir, side, positions, name, fname):
    """nuclei_<side>/<fname> holding `positions` as TRENTo reads them."""
    out = os.path.join(trento_dir, "nuclei_" + side)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    with h5py.File(os.path.join(out, fname), "w") as f:
        f.create_dataset(name, data=positions)


def draw_pool(trento_dir, pool, r0, w, q0, n_q, args):
    """Events q*pool + r for q0 <= q < q0 + n_q and r0 <= r < r0 + w (see the
    module docstring); each needed slot is sampled once."""
    if r0 < 0 or w < 1 or r0 + w > pool:
        raise ValueError("slots must lie inside [0, %d)" % pool)
    target, t_name, t_file, seed = sample_slots(
        trento_dir, "target", np.arange(r0, r0 + w), args.sampler,
        args.processes, args.chunk)
    proj_slots = np.arange(r0 + q0, r0 + q0 + w + n_q - 1) % pool
    projectile, p_name, p_file, _ = sample_slots(
        trento_dir, "projectile", proj_slots, args.sampler, args.processes,
        args.chunk)
    write_configs(trento_dir, "target", target, t_name, t_file)
    parts, ids, b_max = [], [], None
    for k, q in enumerate(range(q0, q0 + n_q)):
        # event q*pool + r0 + i: target slot r0 + i, projectile slot
        # (r0 + i + q) mod pool, i.e. row i + k of `projectile`
        write_configs(trento_dir, "projectile", projectile[k:k + w], p_name,
                      p_file)
        first = q * pool + r0
        *arrays, b_max = run_trento_batch(trento_dir, first, w, args.trento)
        parts.append(arrays)
        ids.append(np.arange(first, first + w, dtype=np.int64))
    return parts, np.concatenate(ids), b_max, seed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--param", required=True, help="parameter dictionary")
    ap.add_argument("--first-id", type=int, help="first event id of a block")
    ap.add_argument("--n", type=int, help="number of event ids")
    ap.add_argument("--pool-slots", type=int, nargs=2, metavar=("R0", "W"),
                    help="with a nucleus pool: slots [R0, R0+W) instead of "
                    "an id block (module docstring)")
    ap.add_argument("--pool-q", type=int,
                    help="with --pool-slots: events q*M + r for q < this")
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
    pool = pool_size_of(os.path.abspath(args.param))
    by_slots = args.pool_slots is not None
    if by_slots and (pool is None or args.pool_q is None or args.pool_q < 1):
        ap.error("--pool-slots needs control_dict['nucleus_pool_size'] in "
                 "the parameter file and --pool-q >= 1")
    if not by_slots and (args.first_id is None or args.n is None):
        ap.error("give --first-id and --n, or --pool-slots and --pool-q")
    if not by_slots and pool is not None:
        # an id block is correct with a pool too (each event gets its two
        # slots), but samples two nuclei per event: no reuse at all
        print("warning: id-block draw with a nucleus pool reuses nothing; "
              "--pool-slots is up to --pool-q times cheaper", file=sys.stderr)
        if args.first_id // pool != (args.first_id + args.n - 1) // pool:
            ap.error("with a nucleus pool an id block must not cross a "
                     "multiple of nucleus_pool_size")
    t0 = time.time()
    workdir = args.workdir or tempfile.mkdtemp(prefix="draw_events_")
    os.makedirs(workdir, exist_ok=True)
    trento_dir = make_job_folder(os.path.abspath(args.param), workdir,
                                 args.framework)
    parts = []
    b_max = master_seed = None
    extra = {}
    if by_slots:
        r0, w = args.pool_slots
        parts, event_id, b_max, master_seed = draw_pool(
            trento_dir, pool, r0, w, 0, args.pool_q, args)
        extra = dict(nucleus_pool_size=pool, pool_r0=r0, pool_w=w,
                     pool_q=args.pool_q)
    elif pool is not None:
        q, r0 = divmod(args.first_id, pool)
        parts, event_id, b_max, master_seed = draw_pool(
            trento_dir, pool, r0, args.n, q, 1, args)
        extra = dict(nucleus_pool_size=pool)
    else:
        for start in range(args.first_id, args.first_id + args.n, args.chunk):
            n = min(args.chunk, args.first_id + args.n - start)
            *arrays, b_max, master_seed = run_batch(trento_dir, start, n,
                                                    args.trento, args.sampler,
                                                    args.processes)
            parts.append(arrays)
        event_id = np.arange(args.first_id, args.first_id + args.n,
                             dtype=np.int64)
    b, npart, mult, entropy = (np.concatenate(x) for x in zip(*parts))
    np.savez_compressed(args.out,
                        event_id=event_id,
                        b=b,
                        npart=npart,
                        mult=mult,
                        entropy=entropy,
                        b_max=b_max,
                        master_seed=master_seed,
                        first_id=int(event_id[0]),
                        n=len(event_id),
                        **extra)
    if not args.workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    dt = time.time() - t0
    print("drew {} events ({} collided) in {:.0f} s = {:.1f} ms/event -> {}".
          format(len(event_id), int(np.sum(mult > 0)), dt,
                 1e3 * dt / len(event_id), args.out))


if __name__ == "__main__":
    main()
