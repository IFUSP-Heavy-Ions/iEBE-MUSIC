#!/usr/bin/env python3
"""Design matrix for an EoS-only campaign: a maximin Latin hypercube in the
Gaussian-quantile space of an EoS model's KL coordinates, plus the campaign's
fixed columns, ready for MakeDictionaries.py --eos-model.

The coordinates z_k are N(0, 1) under the prior, so a design that fills the
box [-a, a]^K uniformly puts most of its points where the prior has almost no
mass (a corner of [-2, 2]^4 is 4 sigma out).  Here the Latin hypercube lives
in u = Phi(z) in [alpha, 1 - alpha]^K: every quantile slice of every mode gets
one point, the points spread by maximin (Morris-Mitchell phi_p), and
z = Phi^-1(u) follows the prior, mildly truncated at |z| <= Phi^-1(1 - alpha).

    make_eos_design.py --model eos_prior_spec.json --n 50 --seed 1 \\
        --fixed fixed_columns.json --out design.csv \\
        [--validation 10 --validation-out validation.csv] [--alpha 0.01]

--model: a spec or frozen model (codes/eos_builder/eos_models.py); its design
columns (eos_z1..eos_zK) name the coordinates.  --fixed: a JSON object of the
other design columns and their constant values (the MAP parameters), copied
into every row.  The validation set is a separate maximin hypercube (seed + 1).
"""
import argparse
import csv
import json
import math
import sys

import numpy as np
from scipy.stats import norm


def model_columns(path):
    with open(path) as f:
        m = json.load(f)
    if "columns" in m:  # frozen model
        return list(m["columns"])
    if m.get("coordinates", "columns") != "columns":
        raise ValueError("the model must use coordinates 'columns'")
    prefix = m.get("column_prefix", "eos_z")
    k = m["n_modes"]
    if k == "all":
        raise ValueError("n_modes 'all' has no finite design")
    return ["%s%d" % (prefix, i + 1) for i in range(int(k))]


def phi_p(u, p=50.0):
    d = np.sqrt(((u[:, None, :] - u[None, :, :])**2).sum(-1))
    d = d[np.triu_indices(len(u), 1)]
    return (np.sum(d**(-p)))**(1.0/p), d.min()


def maximin_lhs(n, k, rng, iters=20000):
    """Latin hypercube in [0, 1]^k (cell midpoints jittered), improved by
    column swaps that lower phi_p, with a slowly cooling acceptance."""
    u = np.empty((n, k))
    for j in range(k):
        u[:, j] = (rng.permutation(n) + rng.random(n))/n
    best, _ = phi_p(u)
    t = 0.05*best
    for it in range(iters):
        j = rng.integers(k)
        a, b = rng.choice(n, 2, replace=False)
        u[[a, b], j] = u[[b, a], j]
        new, _ = phi_p(u)
        if new <= best or rng.random() < math.exp(-(new - best)/t):
            best = new
        else:
            u[[a, b], j] = u[[b, a], j]
        t *= 0.9997
    return u


def write(path, cols, fixed, z):
    names = list(fixed) + cols
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(names)
        for row in z:
            w.writerow([fixed[k] for k in fixed] + ["%.6f" % x for x in row])


def summary(tag, z):
    r = np.sqrt((z**2).sum(1))
    _, dmin = phi_p(norm.cdf(z))
    print("%s: %d points, |z| %.2f-%.2f (median %.2f), max |z_k| %.2f, "
          "min distance in u %.3f" % (tag, len(z), r.min(), r.max(),
                                      np.median(r), np.abs(z).max(), dmin))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--fixed", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--alpha", type=float, default=0.01,
                    help="quantile truncation: |z| <= Phi^-1(1 - alpha)")
    ap.add_argument("--validation", type=int, default=0)
    ap.add_argument("--validation-out")
    ap.add_argument("--iters", type=int, default=20000)
    a = ap.parse_args()
    cols = model_columns(a.model)
    with open(a.fixed) as f:
        fixed = json.load(f)
    clash = set(fixed) & set(cols)
    if clash:
        sys.exit("fixed columns overlap the model's coordinates: %s" % clash)
    lo, hi = a.alpha, 1.0 - a.alpha
    u = maximin_lhs(a.n, len(cols), np.random.default_rng(a.seed), a.iters)
    z = norm.ppf(lo + (hi - lo)*u)
    write(a.out, cols, fixed, z)
    summary(a.out, z)
    if a.validation:
        if not a.validation_out:
            sys.exit("--validation needs --validation-out")
        uv = maximin_lhs(a.validation, len(cols),
                         np.random.default_rng(a.seed + 1), a.iters)
        zv = norm.ppf(lo + (hi - lo)*uv)
        write(a.validation_out, cols, fixed, zv)
        summary(a.validation_out, zv)


if __name__ == "__main__":
    main()
