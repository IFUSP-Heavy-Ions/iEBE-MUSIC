#!/usr/bin/env python3
"""Phase 1, second step: from the drawn events to the list that gets simulated.

Reads the tables written by scripts/draw_events.py for one design point,
calibrates the estimator-to-centrality map on them, applies the campaign's
event selection (codes/event_selection.py) and writes

    <out>.csv   the accepted events, one per line, in event-id order:
                event_id, weight, p_acc, centrality, estimator, u.  This is
                the list the full chain runs from (IEBE_EVENT_LIST)
    <out>.npz   the same plus u and b, and the calibration table
    <out>.json  what is needed to interpret them: the selection, the master
                seed, how many events were drawn and how many collided, the
                accepted count and the effective sample size per bin

Those files replace the full minimum-bias record, which is not kept: it
regenerates from the event ids.

    python3 scripts/select_events.py --draws 'draws_dp0001_*.npz' \\
        --selection campaigns/<name>/event_selection.json --out selection_dp0001

The selection file is the `event_selection` dictionary described in
codes/event_selection.py, without the calibration (it is computed here), e.g.
    {"mode": "bins", "centrality_bins": [0, 0.2, 1, 2, 5, 10, 20, 40, 70]}
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "codes"))
import event_selection as es  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--draws", required=True, help="glob of draw tables")
    ap.add_argument("--selection", required=True, help="selection JSON file")
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--estimator", default="mult", choices=["mult", "entropy"])
    ap.add_argument(
        "--coverage",
        type=float,
        default=1.0,
        help="fraction of the inelastic cross section the drawn sample covers "
        "(below 1 only if b_max cuts into the range where nuclei still collide)")
    args = ap.parse_args()

    files = sorted(glob.glob(args.draws))
    if not files:
        sys.exit("no draw tables match " + args.draws)
    tabs = [np.load(f) for f in files]
    ids = np.concatenate([t["event_id"] for t in tabs])
    if len(np.unique(ids)) != len(ids):
        sys.exit("the draw tables overlap in event id")
    order = np.argsort(ids)
    ids = ids[order]
    est = np.concatenate([t[args.estimator] for t in tabs])[order]
    b = np.concatenate([t["b"] for t in tabs])[order]
    seeds = {int(t["master_seed"]) for t in tabs}
    b_maxes = {float(t["b_max"]) for t in tabs}
    if len(seeds) != 1 or len(b_maxes) != 1:
        sys.exit("the draw tables disagree on master_seed or b_max")
    master_seed, b_max = seeds.pop(), b_maxes.pop()

    with open(args.selection) as fh:
        config = json.load(fh)
    table = es.calibrate(est, coverage=args.coverage)
    config = dict(config, calibration=table)
    cent = es.centrality(est, table)
    p = es.acceptance(cent, config)
    if config.get("mode", "none") == "none":
        u = np.full(len(ids), np.nan)
        accepted = np.ones(len(ids), dtype=bool)
    else:
        u = np.array([es.uniform(master_seed, g) for g in ids])
        accepted = u < p
    # an event that does not collide has nothing to simulate
    accepted &= est > 0
    weight = 1.0 / p[accepted]

    np.savez_compressed(args.out + ".npz",
                        event_id=ids[accepted],
                        weight=weight,
                        p_acc=p[accepted],
                        u=u[accepted],
                        centrality=cent[accepted],
                        estimator=est[accepted],
                        b=b[accepted],
                        calibration_percent=np.array(table["percent"]),
                        calibration_estimator=np.array(table["estimator"]))

    # The list the full chain runs from (IEBE_EVENT_LIST): one line per
    # accepted event, in event-id order.  A job owns a range of its lines.
    with open(args.out + ".csv", "w") as fh:
        fh.write("event_id,weight,p_acc,centrality,estimator,u\n")
        for row in zip(ids[accepted], weight, p[accepted], cent[accepted],
                       est[accepted], u[accepted]):
            fh.write("{:d},{:.10g},{:.10g},{:.6f},{:.10e},{:.10f}\n".format(
                *row))

    summary = {
        "format_version": 1,
        "selection": {k: v
                      for k, v in config.items() if k != "calibration"},
        # where events can be accepted at all; [0, 100] unless there is a cut
        "covered_centrality": es.covered_range(config),
        # the estimator-to-centrality table is this design point's own
        "calibration": "own phase-1 sample of this design point",
        # the same number for the same event id at every design point
        "uniform": "numpy Philox(key=master_seed, counter=[event_id, "
                   "0x53454C45, 0, 0]).random(); accepted if u < p_acc",
        "weight": "1/p_acc, not normalised: the sum of weights estimates the "
                  "number of collided events in the covered range",
        "estimator": args.estimator,
        "coverage": args.coverage,
        "master_seed": master_seed,
        "b_max": b_max,
        "event_ids": [int(ids[0]), int(ids[-1])],
        "n_drawn": int(len(ids)),
        "n_collided": int(np.sum(est > 0)),
        "n_no_collision": int(np.sum(est <= 0)),
        "n_accepted": int(accepted.sum()),
        "effective_size": es.effective_size(weight),
        "sum_of_weights": float(weight.sum()),
    }
    edges = config.get("centrality_bins")
    if edges:
        c_acc = cent[accepted]
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (c_acc >= lo) & (c_acc < hi)
            rows.append({
                "bin": [lo, hi],
                "accepted": int(m.sum()),
                "drawn": int(np.sum((cent >= lo) & (cent < hi) & (est > 0))),
                "effective_size": es.effective_size(weight[m]),
                "p_acc": float(weight[m].size and 1.0 / weight[m].mean())
            })
        summary["bins"] = rows
        m = (c_acc >= edges[-1]) | (c_acc < edges[0])
        summary["outside_bins"] = {
            "accepted": int(m.sum()),
            "drawn": int(np.sum(((cent >= edges[-1]) | (cent < edges[0]))
                                & (est > 0))),
            "p_acc": float(weight[m].size and 1.0 / weight[m].mean())
        }
    with open(args.out + ".json", "w") as fh:
        json.dump(summary, fh, indent=1)
    print("{}: drew {}, collided {}, accepted {} ({:.2f}%), effective size {:.0f}"
          .format(args.out, summary["n_drawn"], summary["n_collided"],
                  summary["n_accepted"],
                  100.0 * summary["n_accepted"] / summary["n_drawn"],
                  summary["effective_size"]))
    for r in summary.get("bins", []):
        print("  {:>5g}-{:<5g}%  accepted {:6d} of {:7d} drawn   p = {:.4f}".
              format(r["bin"][0], r["bin"][1], r["accepted"], r["drawn"],
                     r["p_acc"]))
    if "outside_bins" in summary:
        r = summary["outside_bins"]
        print("  outside the bins  accepted {:6d} of {:7d} drawn   p = {:.4f}".
              format(r["accepted"], r["drawn"], r["p_acc"]))


if __name__ == "__main__":
    main()
