#!/usr/bin/env python3
"""Speed-of-sound models: map a design point's EoS coordinates to c_s^2(T).

The chain itself only needs c_s^2(T) from T_sw up (build_eos_table.py adds
the hadron gas below T_sw and integrates).  A campaign chooses the model and
its prior in a spec file (JSON); `freeze` turns the spec into a frozen model
file holding everything needed to evaluate it (grid, mean, basis), so that
every design point, now or years later, is evaluated from the same numbers.

Model "gp_logit_cs2" -- a Gaussian process for phi = ln(1/c_s^2 - 1) (so that
0 < c_s^2 < 1), as in github.com/luizafperin/generate_gpEOS, written in its
Karhunen-Loeve form so that a design point is a short vector of coordinates:

    phi(T) = phi_mean(T) + sum_{k=1..K} z_k sqrt(lambda_k) psi_k(T),
    c_s^2(T) = 1/(1 + exp(phi(T)))

with (lambda_k, psi_k) the leading eigenpairs of the kernel on the grid and
z_k ~ N(0, 1) under the prior.  K = all grid points is the full GP.

Spec keys:
    model           "gp_logit_cs2"
    T_grid_GeV      [T_min, T_max, step]; T_min at or below every T_sw of the
                    campaign (the same z then means the same c_s^2(T) at
                    every T_sw), T_max the table's top
    mean            {"constant": c} (c_s^2), or {"file": path} with columns
                    T [GeV], c_s^2 covering the grid (linear in between); the
                    file's numbers are copied into the frozen model
    kernel          {"type": "squared_exponential", "length_GeV": l,
                     "sigma_phi": s}: Cov[phi(T), phi(T')] =
                    s^2 exp(-(T - T')^2/(2 l^2)).  generate_gpEOS's
                    (l, sigma) is length_GeV = l/1000 and
                    sigma_phi = 0.05*sqrt(sigma) (its draws are scaled by 0.05)
    n_modes         K, or "all"
    coordinates     "columns" (default): design columns <prefix>1..<prefix>K
                    hold z; "seed": one integer column <prefix>seed, and
                    z = numpy default_rng(seed).standard_normal(K) -- draws
                    from the prior without an emulator in mind
    column_prefix   default "eos_z"

    eos_models.py freeze <spec.json> <frozen.json>
    eos_models.py cs2 <frozen.json> <z1,z2,...|seed=N> <out.dat>
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

MODELS = ("gp_logit_cs2",)


def _grid(spec):
    t_min, t_max, step = (float(x) for x in spec["T_grid_GeV"])
    n = int(round((t_max - t_min)/step))
    if n < 2 or abs(t_min + n*step - t_max) > 1e-9:
        raise ValueError("T_grid_GeV: (T_max - T_min) must be a multiple of"
                         " the step")
    return t_min + step*np.arange(n + 1)


def _mean_cs2(spec, T, base_dir):
    mean = spec["mean"]
    if "constant" in mean:
        return np.full(T.shape, float(mean["constant"])), None
    path = mean["file"]
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    d = np.loadtxt(path, ndmin=2)
    if d[0, 0] > T[0] + 1e-12 or d[-1, 0] < T[-1] - 1e-12:
        raise ValueError("mean file %s covers %.4f-%.4f GeV, the grid "
                         "%.4f-%.4f" % (path, d[0, 0], d[-1, 0], T[0], T[-1]))
    return np.interp(T, d[:, 0], d[:, 1]), d[:, :2].tolist()


def freeze(spec, base_dir="."):
    """Frozen model (a JSON-able dict) from a spec."""
    if spec.get("model") not in MODELS:
        raise ValueError("model must be one of %s" % (MODELS,))
    T = _grid(spec)
    cs2_mean, mean_table = _mean_cs2(spec, T, base_dir)
    if np.any(cs2_mean <= 0) or np.any(cs2_mean >= 1):
        raise ValueError("mean c_s^2 outside (0, 1)")
    kern = spec["kernel"]
    if kern.get("type", "squared_exponential") != "squared_exponential":
        raise ValueError("kernel: only squared_exponential is implemented")
    ell, sig = float(kern["length_GeV"]), float(kern["sigma_phi"])
    C = sig**2*np.exp(-(T[:, None] - T[None, :])**2/(2*ell**2))
    lam, psi = np.linalg.eigh(C)
    order = np.argsort(lam)[::-1]
    lam, psi = np.clip(lam[order], 0.0, None), psi[:, order]
    K = len(T) if spec["n_modes"] == "all" else int(spec["n_modes"])
    if not 1 <= K <= len(T):
        raise ValueError("n_modes must be between 1 and the grid size")
    lam, psi = lam[:K], psi[:, :K]
    # sign convention: each mode positive where it is largest
    for k in range(K):
        if psi[np.argmax(np.abs(psi[:, k])), k] < 0:
            psi[:, k] *= -1
    total = sig**2*len(T)  # trace of C
    coords = spec.get("coordinates", "columns")
    if coords not in ("columns", "seed"):
        raise ValueError("coordinates: 'columns' or 'seed'")
    prefix = spec.get("column_prefix", "eos_z")
    frozen = {
        "model": spec["model"],
        "spec": spec,
        "mean_table": mean_table,
        "T_GeV": T.tolist(),
        "phi_mean": np.log(1.0/cs2_mean - 1.0).tolist(),
        "basis": (psi*np.sqrt(lam)[None, :]).T.tolist(),  # K rows
        "variance_fraction": (lam/total).tolist(),
        "columns": ([prefix + "seed"] if coords == "seed"
                    else ["%s%d" % (prefix, k + 1) for k in range(K)]),
    }
    return frozen


def coordinates(frozen, values):
    """z from the design columns of one design point (a dict)."""
    K = len(frozen["basis"])
    cols = frozen["columns"]
    missing = [c for c in cols if str(values.get(c, "")).strip() == ""]
    if missing:
        raise ValueError("EoS model needs the design column(s) %s" % missing)
    if frozen["spec"].get("coordinates", "columns") == "seed":
        seed = int(float(values[cols[0]]))
        return np.random.default_rng(seed).standard_normal(K)
    return np.array([float(values[c]) for c in cols])


def cs2_of(frozen, z):
    """(T [GeV], c_s^2) of the model at the coordinates z."""
    z = np.asarray(z, float)
    B = np.asarray(frozen["basis"])
    if z.shape != (B.shape[0],):
        raise ValueError("need %d coordinates, got %d" % (B.shape[0], z.size))
    phi = np.asarray(frozen["phi_mean"]).copy()
    for k in range(B.shape[0]):  # fixed summation order
        phi += z[k]*B[k]
    return np.asarray(frozen["T_GeV"]), 1.0/(1.0 + np.exp(phi))


def save_frozen(frozen, path):
    with open(path, "w") as f:
        json.dump(frozen, f, sort_keys=True)
    return sha256_of(path)


def load_frozen(path):
    with open(path) as f:
        return json.load(f)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("spec")
    f.add_argument("frozen")
    c = sub.add_parser("cs2")
    c.add_argument("frozen")
    c.add_argument("coords", help="z1,z2,... or seed=N")
    c.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "freeze":
        spec = json.load(open(a.spec))
        frozen = freeze(spec, os.path.dirname(os.path.abspath(a.spec)))
        digest = save_frozen(frozen, a.frozen)
        vf = np.cumsum(frozen["variance_fraction"])
        print("%s: %d modes, prior variance kept %.4f, columns %s, sha256 %s"
              % (a.frozen, len(frozen["basis"]), vf[-1],
                 ",".join(frozen["columns"]), digest))
    else:
        frozen = load_frozen(a.frozen)
        if a.coords.startswith("seed="):
            z = coordinates(frozen, {frozen["columns"][0]: a.coords[5:]})
        else:
            z = [float(x) for x in a.coords.split(",")]
        T, cs2 = cs2_of(frozen, z)
        np.savetxt(a.out, np.column_stack((T, cs2)), fmt="%.10e")
    return 0


if __name__ == "__main__":
    sys.exit(main())
