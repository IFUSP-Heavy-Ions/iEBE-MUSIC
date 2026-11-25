#!/usr/bin/env python3
"""Write event_selection.json for pbpb5020-eos (mode "curve").

The density of simulated events per percent of centrality is
    n(c) = N1 (c / 1%)^-alpha        c < 1%     (ultra-central, nested bins)
    n(c) = N1                        1-5%       (v_n{4} in 1% bins)
    n_wide / width of each wide bin  5-60%      (5-10, 10-20, ..., 50-60)
    n_floor                          beyond 60% (keeps final-state centrality
                                                 classes unbiased near 60%)
with geometric tapers instead of steps at 5% (over 5-6%), 10% and 60%. A
final-state estimator smears the TRENTo centrality (a 2% multiplicity scatter
is about 0.5% in centrality at 5%), so a step would let a few heavy events
leak across it and cut the effective size of the bins next to it.

The acceptance is P(c) = n(c) / (draws per percent) <= 1, where
draws per percent = n_draw / (100 coverage); n_draw counts the drawn events
with b < b_max. P depends on n_draw, so fix it before drawing. Below the
centrality where P reaches 1 every drawn event is simulated. Any P is unbiased
(weights 1/P); only the efficiency depends on these choices.

    python3 make_selection.py --n1 5000 --n-draw 15000000 --out event_selection.json

The decisions behind the defaults (2026-11-25) are in NOTES.md.
"""
import argparse
import json

import numpy as np

COVERAGE = 0.746  # fraction of sigma_inel below b_max = 14.69 fm (NOTES.md)
WIDE = [(5, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60)]


def density(c, a):
    """Simulated events per percent of centrality at c (percent)."""
    c = np.asarray(c, dtype=float)
    n = np.where(c < 1.0, a.n1*np.maximum(c, 1e-12)**(-a.alpha), a.n1)
    for lo, hi in WIDE:
        n = np.where((c >= lo) & (c < hi), a.n_wide/(hi - lo), n)
    n = np.where(c >= 60.0, a.n_floor, n)

    def taper(n, lo, hi, n_lo, n_hi):
        s = (c >= lo) & (c < hi)
        t = (c - lo)/(hi - lo)
        return np.where(s, n_lo*(n_hi/n_lo)**t, n)

    n = taper(n, 5.0, 6.0, a.n1, a.n_wide/5.0)
    n = taper(n, 10.0, 11.0, a.n_wide/5.0, a.n_wide/10.0)
    n = taper(n, 60.0, 65.0, a.n_wide/10.0, a.n_floor)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n1", type=float, default=5000,
                    help="events per 1%% bin in 1-5%%")
    ap.add_argument("--alpha", type=float, default=0.5,
                    help="ultra-central slope, n ~ c^-alpha below 1%%")
    ap.add_argument("--n-wide", type=float, default=1500,
                    help="events per wide bin in 5-60%%")
    ap.add_argument("--n-floor", type=float, default=10,
                    help="events per percent beyond 60%%")
    ap.add_argument("--n-draw", type=float, required=True,
                    help="drawn events with b < b_max")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    per_pct = a.n_draw/(100.0*COVERAGE)

    knots = np.unique(np.concatenate([
        np.logspace(-5, 0, 61), np.linspace(1, 5, 5), np.linspace(5, 6, 6),
        [8.0, 9.99], np.linspace(10, 11, 5), [20.0, 40.0, 59.99],
        np.linspace(60, 65, 6), [80.0, 100.0]]))
    p = np.minimum(1.0, density(knots, a)/per_pct)
    curve = [[0.0, float(p[0])]] + [[float(round(c, 6)), float("%.6g" % q)]
                                    for c, q in zip(knots, p)]
    config = {
        "mode": "curve",
        "curve": curve,
        "description": ("pbpb5020-eos importance sampling: N1 %g per 1%% in "
                        "1-5%%, n ~ c^-%g below 1%%, %g per wide bin in "
                        "5-60%%, %g per %% beyond, for %g draws (coverage "
                        "%g); campaigns/pbpb5020-eos/make_selection.py" %
                        (a.n1, a.alpha, a.n_wide, a.n_floor, a.n_draw,
                         COVERAGE)),
    }
    with open(a.out, "w") as fh:  # one [c, P] knot per line
        text = json.dumps(dict(config, curve="@CURVE@"), indent=1)
        rows = ",\n  ".join(json.dumps(k) for k in curve)
        fh.write(text.replace('"@CURVE@"', "[\n  " + rows + "\n ]") + "\n")

    # expected counts with the interpolated curve, as select_events applies it
    c = np.concatenate([np.logspace(-6, 0, 30000, endpoint=False),
                        np.linspace(1, 100, 99001)])
    dc = np.gradient(c)
    pc = np.interp(c, [k[0] for k in curve], [k[1] for k in curve])
    n = pc*per_pct
    w = 1.0/pc

    def stats(lo, hi):
        s = (c >= lo) & (c < hi)
        N = np.sum(n[s]*dc[s])
        ess = np.sum(n[s]*w[s]*dc[s])**2/np.sum(n[s]*w[s]**2*dc[s])
        return N, ess

    print("%s: P = 1 below c = %.4f%%" %
          (a.out, (a.n1/per_pct)**(1.0/a.alpha)))
    for lo, hi in [(0, 0.005), (0, 0.02), (0, 0.2), (0, 1), (0, 2.5),
                   (2.5, 5), (1, 2), (2, 3), (3, 4), (4, 5), (0.005, 0.57)
                   ] + WIDE + [(60, 100)]:
        N, ess = stats(lo, hi)
        print("  %6.3f-%-6g%%: %7.0f events, effective %7.0f" % (lo, hi, N,
                                                               ess))
    s = c < 100.0*COVERAGE
    print("  total %.0f events (b < b_max)" % np.sum(n[s]*dc[s]))


if __name__ == "__main__":
    main()
