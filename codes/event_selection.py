#!/usr/bin/env python3
"""Importance sampling of events: who gets simulated, and with what weight.

Hydrodynamics is the expensive stage, and a minimum-bias sample spends almost
all of it far from the narrow centrality bins one wants to measure.  This
module decides, from a cheap scalar computed on the initial condition (TRENTo's
total entropy, called the *estimator* here), whether an event is simulated, and
records the weight that makes averages over the simulated events unbiased:

    accepted with probability P  ->  weight 1/P
    <O> = sum_i w_i O_i / sum_i w_i

Three properties are deliberate.

* **Unbiased whatever the calibration.**  P only has to be positive and
  recorded.  A poor estimator-to-centrality calibration costs efficiency,
  never correctness.
* **Common random numbers.**  The uniform number that decides event g depends
  only on (master_seed, g), so two design points make the same draw for the
  same event and differ only where their acceptance probabilities differ.
* **Off by default.**  With no selection configured every event is accepted
  with weight 1, which is the behaviour of every campaign before this existed.

Configuration (a plain dict, e.g. `event_selection_dict` in a parameter file):

    {"mode": "none"}                                  # default
    {"mode": "bins",                                  # ~equal accepted events per bin
     "centrality_bins": [0, 0.2, 1, 2, 5, 10, 20, 40, 70],
     "min_acceptance": 0.02,                          # floor inside the bins
     "outside": 0.02}                                 # beyond the last edge
    {"mode": "curve",                                 # explicit P(centrality %)
     "curve": [[0, 1.0], [1, 1.0], [10, 0.05], [100, 0.05]]}

plus, for either active mode, the calibration that turns the estimator into a
centrality percentile (see `calibrate`).

`outside` defaults to the acceptance of the last bin, so that every part of
the cross section stays represented and centrality percentiles computed from
the weighted sample are unbiased everywhere.  `"outside": 0` is a hard cut:
cheaper, but the events beyond it do not exist in the output, and classes
defined on final-state multiplicity are biased within a few percent of the
cut, because the initial and the final ordering of events are not the same.
"""

import numpy as np

# Domain tag mixed into the counter so this stream can never coincide with the
# nucleon-pool stream, which uses the same master seed.
_STREAM_TAG = 0x53454C45  # "SELE"


def uniform(master_seed, event_id):
    """The uniform number in [0, 1) that decides `event_id`.  Pure function."""
    bit_gen = np.random.Philox(key=int(master_seed),
                               counter=[int(event_id), _STREAM_TAG, 0, 0])
    return float(np.random.Generator(bit_gen).random())


def calibrate(estimators, coverage=1.0, n_knots=2001, top_events=10,
              top_fraction=0.01, knots_per_decade=50):
    """Estimator-to-centrality table from a minimum-bias sample.

    `estimators` holds one value per *drawn* event; events that did not collide
    (estimator <= 0) are dropped, since centrality is a fraction of the
    inelastic cross section.  `coverage` is the fraction of the inelastic cross
    section the drawn sample covers: 1 unless the impact parameter was cut
    below the range where collisions still happen, in which case the most
    peripheral event of the sample sits at 100*coverage percent, not 100.

    The knots are `n_knots` evenly spaced fractions plus geometrically spaced
    ones (`knots_per_decade`) from the fraction holding the `top_events` most
    central events up to `top_fraction` of the sample.  Without the geometric part
    the first segment spans 100*coverage/(n_knots - 1) percent (0.037% for
    2001 knots at coverage 0.746), and since the top of the estimator
    distribution is a thin tail, linear interpolation inside it put almost
    every event near the segment's far end: on 15M Pb-Pb draws, 2 events fell
    in 0-0.005% instead of 1019, and the ultra-central bins of a selection
    were starved by the same factor.  The geometric knots continue to
    `top_fraction` because the tail's curvature still costs a few percent of
    centrality per segment up to about 0.2%.

    Returns {"percent": [...], "estimator": [...]}: the estimator value at
    each centrality percentile, most central first (estimator decreasing).
    """
    x = np.asarray(estimators, dtype=float)
    x = np.sort(x[x > 0.0])[::-1]
    if len(x) < 2:
        raise ValueError("calibration needs at least two collided events")
    frac = (np.arange(len(x)) + 0.5) / len(x)  # 0 = most central
    knots = np.linspace(0.0, 1.0, n_knots)
    f0, f1 = top_events / len(x), max(top_fraction, knots[1])
    if knots_per_decade > 0 and f0 < f1:
        n_log = int(np.ceil(knots_per_decade * np.log10(f1 / f0)))
        knots = np.unique(np.concatenate([knots, np.geomspace(f0, f1, n_log + 1)]))
    values = np.interp(knots, frac, x)
    return {
        "percent": (100.0 * coverage * knots).tolist(),
        "estimator": values.tolist()
    }


def centrality(estimator, table):
    """Centrality percentile of an estimator value (array or scalar)."""
    pct = np.asarray(table["percent"], dtype=float)
    est = np.asarray(table["estimator"], dtype=float)
    # np.interp wants increasing x: reverse the (decreasing) estimator axis
    c = np.interp(np.asarray(estimator, dtype=float), est[::-1], pct[::-1])
    # no collision: beyond everything
    return np.where(np.asarray(estimator, dtype=float) <= 0.0, 100.0, c)


def acceptance_from_bins(edges, min_acceptance=0.0):
    """Acceptance per bin giving roughly equal accepted events in every bin.

    A bin of width d percent holds a fraction d/100 of the cross section, so
    P = d_min/d fills each bin equally; the narrowest bin is fully accepted.
    """
    edges = np.asarray(edges, dtype=float)
    if len(edges) < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError("centrality_bins must be increasing")
    width = np.diff(edges)
    return np.maximum(width.min() / width, float(min_acceptance))


def acceptance(centrality_pct, config):
    """Acceptance probability at a centrality percentile (array or scalar)."""
    c = np.asarray(centrality_pct, dtype=float)
    mode = config.get("mode", "none")
    if mode == "none":
        return np.ones_like(c)
    if mode == "bins":
        edges = np.asarray(config["centrality_bins"], dtype=float)
        p_bin = acceptance_from_bins(edges, config.get("min_acceptance", 0.0))
        idx = np.clip(np.searchsorted(edges, c, side="right") - 1, 0,
                      len(p_bin) - 1)
        p = p_bin[idx]
        outside = (c < edges[0]) | (c >= edges[-1])
        p_outside = config.get("outside")
        if p_outside is None:
            p_outside = p_bin[-1]
        return np.where(outside, float(p_outside), p)
    if mode == "curve":
        pts = np.asarray(config["curve"], dtype=float)
        return np.interp(c, pts[:, 0], pts[:, 1])
    raise ValueError("unknown event selection mode: {}".format(mode))


def covered_range(config):
    """[low, high] centrality percent in which events can be accepted at all."""
    mode = config.get("mode", "none")
    grid = np.linspace(0.0, 100.0, 100001)
    grid = grid[:-1]  # 100 is where events that never collide are put
    ok = np.nonzero(acceptance(grid, config) > 0.0)[0]
    if mode == "none" or len(ok) == len(grid):
        return [0.0, 100.0]
    if len(ok) == 0:
        return [0.0, 0.0]
    step = grid[1] - grid[0]
    return [float(round(grid[ok[0]], 3)), float(round(grid[ok[-1]] + step, 3))]


def decide(event_id, estimator, config, master_seed):
    """Decision record for one event.

    Returns a dict with the centrality percentile, the acceptance probability,
    the uniform draw, whether the event is simulated, and its weight (0 if it
    is not).  With mode "none" nothing is drawn and the weight is 1.
    """
    if config.get("mode", "none") == "none":
        return {"centrality": float("nan"), "p_acc": 1.0, "u": float("nan"),
                "accepted": True, "weight": 1.0}
    c = float(centrality(estimator, config["calibration"]))
    p = float(acceptance(c, config))
    u = uniform(master_seed, event_id)
    accepted = u < p
    return {"centrality": c, "p_acc": p, "u": u, "accepted": bool(accepted),
            "weight": 1.0 / p if accepted else 0.0}


def effective_size(weights):
    """Kish effective sample size, (sum w)^2 / sum w^2."""
    w = np.asarray(weights, dtype=float)
    s2 = np.sum(w * w)
    return float(np.sum(w)**2 / s2) if s2 > 0 else 0.0
