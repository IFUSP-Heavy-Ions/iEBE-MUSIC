#!/usr/bin/env python3
"""Fit the per-event hydro box rule of pbpb5020-eos (NOTES.md, "Hydro box").

    need = max(R999 + floor_offset, a + b ln(mult) + n_sigma sigma)
    half-width = need + pad

with one (a, b, sigma) per EoS table. `need` is the larger of max|x|, max|y|
of the freeze-out surface, measured in adaptive_grid_calibration.csv:

  smash_28fm  12 design points x 8 events, SMASH hadron list, +-28 fm box
  decay_28fm  every design point, 11 events (3 for the 12 above), +-28 fm,
              afterburner "decay": the table's hadron-gas part differs
              slightly from production (e_fo 0.1146 instead of 0.1174
              GeV/fm^3), which moves the surface by at most 0.2 fm
  pilot_20fm  the OSG pilot on the fixed +-20 fm box; used only where the
              fit says the edge cannot have clipped the surface

R999 in the table is of the free-streamed profile; the driver measures the
raw TRENTo profile, which is 0.35 +- 0.05 fm smaller, and floor_offset
allows for that.

usage: fit_adaptive_grid.py [calibration.csv [adaptive_grid.json]]
"""
import csv
import json
import os
import sys

import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))

# need - R999 (free-streamed) of an event whose surface never grows
DELTA = 0.2
# sigma = max(kappa b, SIGMA_MIN), kappa pooled over the design points
SIGMA_MIN = 0.35
# keep a pilot event if a + b ln(mult) + PILOT_MARGIN b < PILOT_EDGE
PILOT_MARGIN = 3*0.16
PILOT_EDGE = 19.5
RULE = {
    "rule": "lnmult",
    "n_sigma": 2.5,
    "pad": 0.6,
    "floor_quantile": 0.999,
    "floor_offset": 1.5,
    "max_half_width": 28.0,
    "retry_growth": 1.15,
    "max_retries": 3,
}


def hinge(need, mult, r999):
    """Least squares of need = max(r999 + DELTA, a + b ln(mult))."""
    x = np.log(mult)
    best = None
    for b0 in (2.0, 3.0, 4.5, 6.5):
        fit = least_squares(
            lambda p: need - np.maximum(r999 + DELTA, p[0] + p[1]*x),
            [np.max(need - b0*x), b0],
            bounds=([-200, 1.0], [50, 12.0]))
        if best is None or fit.cost < best.cost:
            best = fit
    return best.x


def fit_point(rows):
    """(a, b, residuals on the linear branch, residuals on the floor)."""

    def arrays(sel):
        return tuple(
            np.array([float(r[k]) for r in sel])
            for k in ("need", "mult", "R999"))

    cal = [r for r in rows if r["run"] != "pilot_20fm"]
    a, b = hinge(*arrays(cal))
    # chosen by multiplicity, so the cut does not bias the extent
    cal += [
        r for r in rows if r["run"] == "pilot_20fm"
        and a + b*np.log(float(r["mult"])) + PILOT_MARGIN*b < PILOT_EDGE
    ]
    need, mult, r999 = arrays(cal)
    a, b = hinge(need, mult, r999)
    line = a + b*np.log(mult)
    res = need - np.maximum(r999 + DELTA, line)
    linear = line > r999 + DELTA
    return a, b, res[linear], res[~linear]


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "adaptive_grid_calibration.csv")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        HERE, "adaptive_grid.json")
    by_point = {}
    with open(src) as f:
        for r in csv.DictReader(f):
            by_point.setdefault(int(r["design_point"]), []).append(r)
    fits = {d: fit_point(rows) for d, rows in sorted(by_point.items())}
    rel = np.concatenate([f[2]/f[1] for f in fits.values()])
    kappa = float(np.sqrt(np.mean(rel**2)))
    print("{} design points, sigma/b = {:.3f}".format(len(fits), kappa))
    by_eos = {}
    for d, (a, b, res, _) in fits.items():
        sigma = max(kappa*b, SIGMA_MIN)
        by_eos[by_point[d][0]["eos_key"]] = [
            round(a, 3), round(b, 3), round(sigma, 3)
        ]
        print("dp{:<3d} a {:7.2f} b {:5.2f} sigma {:.2f}  rms {:.2f}"
              "  largest miss {:.2f}".format(d, a, b, sigma, res.std(),
                                             res.max()))
    # an unknown table gets the widest box any calibrated one asks for
    lm = np.log(np.array([300., 1000., 2000., 3000., 4000., 4600.]))
    env = np.max([[f[0] + f[1]*x for x in lm] for f in fits.values()], axis=0)
    b0, a0 = np.polyfit(lm, env, 1)
    a0 += float(np.max(env - (a0 + b0*lm)))
    coeffs = dict(RULE)
    coeffs["default"] = [
        round(a0, 3), round(b0, 3), round(max(kappa*b0, SIGMA_MIN), 3)
    ]
    coeffs["by_eos"] = by_eos
    with open(out, "w") as f:
        json.dump(coeffs, f, indent=1, sort_keys=True)
    floor = np.concatenate([f[3] for f in fits.values()])
    print("default", coeffs["default"])
    print("floor branch: n {} rms {:.2f} largest miss {:.2f}".format(
        floor.size, floor.std(), floor.max()))


if __name__ == "__main__":
    main()
