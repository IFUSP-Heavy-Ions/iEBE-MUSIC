#!/usr/bin/env python3
"""Checks of codes/event_selection.py.  Run: python3 tests/test_event_selection.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "codes"))
import event_selection as es

SEED = 8675309
rng = np.random.default_rng(7)

# a toy minimum-bias sample: estimator falls with impact parameter, with noise
n = 400000
b = np.sqrt(rng.random(n))                       # b/b_max, flat in area
est = np.clip(1000 * (1 - b**1.5) * rng.gamma(20, 1 / 20, n), 0, None)
est[b > 0.97] = 0.0                              # some never collide
obs = np.sqrt(est) + rng.normal(0, 1, n)         # an "observable"
ids = np.arange(n)

# 1. the default accepts everything with weight 1 and draws nothing
d = es.decide(5, 123.0, {}, SEED)
assert d["accepted"] and d["weight"] == 1.0 and d["p_acc"] == 1.0

# 2. the decision is a pure function of (seed, event id)
assert es.uniform(SEED, 42) == es.uniform(SEED, 42) != es.uniform(SEED, 43)
u = np.array([es.uniform(SEED, i) for i in range(20000)])
assert abs(u.mean() - 0.5) < 0.01 and abs(np.mean(u < 0.1) - 0.1) < 0.01

# 3. calibration: percentiles of the calibration sample are flat in [0, 100]
table = es.calibrate(est)
c = es.centrality(est, table)
coll = est > 0
assert abs(np.mean(c[coll] < 1.0) - 0.01) < 5e-4 and abs(np.mean(c[coll] < 50) - 0.5) < 2e-3
assert np.all(c[~coll] == 100.0)

# 4. "bins" gives about equal accepted counts per bin, and unbiased averages
cfg = {"mode": "bins", "centrality_bins": [0, 0.2, 1, 2, 5, 10, 20, 40, 70],
       "min_acceptance": 0.0, "outside": 0.0, "calibration": table}
p = es.acceptance(c, cfg)
uu = np.array([es.uniform(SEED, i) for i in ids])
acc = uu < p
w = np.where(acc, 1 / np.maximum(p, 1e-300), 0.0)
edges = np.array(cfg["centrality_bins"])
counts = np.histogram(c[acc], edges)[0]
print("accepted per bin:", counts.tolist(), " of", n, "drawn ->", acc.sum(), "simulated (%.1f%%)" % (100 * acc.mean()))
assert counts.max() / counts.min() < 1.25
for lo, hi in zip(edges[:-1], edges[1:]):
    full = (c >= lo) & (c < hi)
    truth = obs[full].mean()
    est_w = np.sum(w[full] * obs[full]) / np.sum(w[full])
    err = obs[full & acc].std() / np.sqrt(max(1, (full & acc).sum()))
    assert abs(est_w - truth) < 5 * err, (lo, hi, est_w, truth, err)
# the weighted count reproduces the number of events in every bin
assert np.allclose(np.histogram(c[acc], edges, weights=w[acc])[0], np.histogram(c, edges)[0], rtol=0.05)

# 4b. beyond the last edge: the last bin's acceptance unless a cut is asked for
cfg_floor = {k: v for k, v in cfg.items() if k != "outside"}
assert np.allclose(es.acceptance([69.0, 71.0, 99.0], cfg_floor), 0.2 / 30)
assert np.all(es.acceptance([71.0, 99.0], cfg) == 0.0)
assert es.covered_range(cfg) == [0.0, 70.0]
assert es.covered_range(cfg_floor) == [0.0, 100.0]
assert es.covered_range({"mode": "none"}) == [0.0, 100.0]
# with every region represented the weights add up to the collided events
pf = es.acceptance(c, cfg_floor)
tot = np.sum(1 / pf[(uu < pf) & coll])
assert abs(tot / coll.sum() - 1) < 0.03, tot / coll.sum()

# 5. an explicit curve, and two design points sharing the draw
cfg2 = {"mode": "curve", "curve": [[0, 1.0], [1, 1.0], [10, 0.05], [100, 0.05]], "calibration": table}
pA = es.acceptance(c, cfg2)
est_B = est * 1.3 * rng.gamma(200, 1 / 200, n)   # another design point: rescaled, slightly reshuffled
tabB = es.calibrate(est_B)
pB = es.acceptance(es.centrality(est_B, tabB), cfg2)
accA, accB = uu < pA, uu < pB
both = np.mean(accA & accB) / np.mean(accA | accB)
print("two design points, common draw: overlap of accepted sets %.3f (independent draws would give %.3f)"
      % (both, np.mean(pA * pB) / np.mean(pA + pB - pA * pB)))
assert both > 0.85

# 6. coverage: a sample cut in impact parameter does not reach 100%
t60 = es.calibrate(est[b < 0.6], coverage=0.6)
assert abs(max(t60["percent"]) - 60.0) < 1e-9
print("effective size of the accepted sample: %.0f of %d" % (es.effective_size(w[acc]), acc.sum()))
print("all checks passed")
