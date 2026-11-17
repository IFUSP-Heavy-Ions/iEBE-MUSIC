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
import csv
import glob
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "codes"))
import event_selection as es  # noqa: E402


def sha256(name):
    h = hashlib.sha256()
    with open(name, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve_coverage(args, ids, est, b, b_max):
    """Fraction of the inelastic cross section inside b_max, and where from.

    Centrality is a fraction of the *whole* inelastic cross section, but the
    draws only reach b_max.  If collisions still happen at b_max the sample
    misses the most peripheral ones, and a selection that ignores that puts
    every percentile too high by 1/coverage.  The draws cannot measure what
    lies beyond b_max, so the number has to come from outside; what they can
    do is show that it is needed.
    """
    n = len(ids)
    hit = est > 0
    # b^2 is uniform up to b_max^2, so the outer shell b > x b_max holds
    # n (1 - x^2) draws; b is recorded for the ones that collided
    x = 0.95
    p_edge = float(np.sum(hit & (b > x * b_max)) / (n * (1 - x * x)))
    if args.xsec_table:
        if args.coverage is not None:
            sys.exit("give --coverage or --xsec-table, not both")
        if args.dp is None:
            sys.exit("--xsec-table needs --dp")
        row = None
        with open(args.xsec_table, newline="") as fh:
            for r in csv.DictReader(fh):
                if int(r["dp"]) == args.dp:
                    row = r
                    break
        if row is None:
            sys.exit("design point {} is not in {}".format(
                args.dp, args.xsec_table))
        if abs(float(row["b_max"]) - b_max) > 1e-6 * b_max:
            sys.exit("b_max of the draws ({}) is not the table's ({})".format(
                b_max, row["b_max"]))
        coverage = float(row["frac_below_bmax"])
        source = "frac_below_bmax of {} (sha256 {}), dp {}".format(
            os.path.basename(args.xsec_table), sha256(args.xsec_table),
            args.dp)
        # the table also predicts how many draws collide; a disagreement means
        # the table belongs to other nuclei or another cross section
        if "p_hit_below_bmax" in row:
            p_tab = float(row["p_hit_below_bmax"])
            p_obs = float(np.mean(hit))
            err = np.sqrt(max(p_tab * (1 - p_tab), 1e-12) / n)
            if abs(p_obs - p_tab) > 5 * err + 1e-3:
                sys.exit("collided fraction of the draws {:.4f} disagrees "
                         "with the table's {:.4f}".format(p_obs, p_tab))
    elif args.coverage is not None:
        coverage = args.coverage
        source = "given on the command line"
    else:
        if p_edge > 0.01:
            sys.exit(
                "b_max cuts into the collision range: {:.0f}% of the draws "
                "with b > {} b_max still collide.  The coverage (fraction of "
                "the inelastic cross section inside b_max) is needed: "
                "--xsec-table/--dp from scripts/cross_section, or --coverage."
                .format(100 * p_edge, x))
        coverage = 1.0
        source = ("assumed 1: {:.2g} of the draws with b > {} b_max collide"
                  .format(p_edge, x))
    if not 0.0 < coverage <= 1.0:
        sys.exit("coverage must be in (0, 1]")
    return coverage, source


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--draws", required=True, help="glob of draw tables")
    ap.add_argument("--selection", required=True, help="selection JSON file")
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--estimator", default="mult", choices=["mult", "entropy"])
    ap.add_argument(
        "--coverage",
        type=float,
        help="fraction of the inelastic cross section inside b_max.  Needed "
        "whenever b_max cuts into the range where nuclei still collide; "
        "centralities are wrong by 1/coverage without it.  Give it here, or "
        "let --xsec-table supply it")
    ap.add_argument(
        "--xsec-table",
        help="summary_<campaign>.csv of scripts/cross_section: the coverage "
        "is read from its frac_below_bmax column, row --dp")
    ap.add_argument("--dp", type=int, help="design point, for --xsec-table")
    ap.add_argument(
        "--calibration",
        help="take the estimator-to-centrality table from this earlier "
        "<out>.npz instead of computing it from --draws.  A frozen table "
        "keeps earlier decisions unchanged when more events are drawn later "
        "(an augmentation batch), and lets design points share one table")
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

    coverage, coverage_source = resolve_coverage(args, ids, est, b, b_max)
    args.coverage = coverage

    with open(args.selection) as fh:
        config = json.load(fh)
    if args.calibration:
        ref = np.load(args.calibration)
        table = {"percent": ref["calibration_percent"].tolist(),
                 "estimator": ref["calibration_estimator"].tolist()}
        calibration = {
            "file": os.path.basename(args.calibration),
            "sha256": sha256(args.calibration),
            "n_drawn": int(ref["n_drawn"]) if "n_drawn" in ref else None,
            "coverage": float(ref["coverage"]) if "coverage" in ref else None,
        }
        # A table built on another coverage puts the percentiles on another
        # scale: the same mistake as a wrong --coverage.
        if calibration["coverage"] is None:
            sys.exit("{} does not record the coverage it was built with; "
                     "redo that selection first".format(args.calibration))
        if abs(calibration["coverage"] - coverage) > 1e-9:
            sys.exit("the calibration table assumes coverage {}, this "
                     "selection {}".format(calibration["coverage"], coverage))
        calibration_source = "external"
    else:
        table = es.calibrate(est, coverage=coverage)
        calibration = {"n_drawn": int(len(ids)), "coverage": coverage}
        calibration_source = "own"
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
                        n_drawn=len(ids),
                        coverage=coverage,
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

    # Percent of the inelastic cross section, like every centrality here; the
    # drawn sample itself ends at 100 * coverage.
    covered = es.covered_range(config)
    covered[1] = min(covered[1], 100.0 * args.coverage)
    summary = {
        "format_version": 1,
        "selection": {k: v
                      for k, v in config.items() if k != "calibration"},
        # where events can be accepted at all; [0, 100] unless there is a cut
        "covered_centrality": covered,
        # the estimator-to-centrality table: "own" (computed from these
        # draws) or "external" (a frozen table from an earlier selection)
        "calibration_source": calibration_source,
        "calibration": calibration,
        "coverage_source": coverage_source,
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
