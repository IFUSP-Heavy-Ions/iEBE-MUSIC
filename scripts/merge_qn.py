#!/usr/bin/env python3
"""Merge the per-event qn_<id>.h5 files of one design point (standard output,
docs/standard_output.md) into one file with the event axis first.

Usage: merge_qn.py SOURCE_DIR OUTPUT_H5 [--selection PREFIX [--first N]]

SOURCE_DIR holds the qn_<id>.h5 files and the events_drawn*.csv tables of the
design point.  Rows are sorted by event id.  Events whose fireball never
reached freeze-out (status no_surface in events_drawn) become rows with all
sums 0 and nsamples 0.  /drawn lists every drawn id with its fate.  With
--selection (the PREFIX.csv/.json files of scripts/select_events.py) the
selection-format-1 attributes are added and accepted events that never came
back are listed in /drawn as failed.

--first N is for a campaign run in stages from a rank-ordered list
(select_events.py --order rank): only the first N lines of the list are
merged.  Events from further down the list are left out even if their files
are there, because which of them have arrived depends on how long they ran.
The attributes selection_first = N and selection_fraction = N / (lines in the
list) are added; the weights stay 1/p_acc, so their sum estimates
selection_fraction times the number of collided events.

A per-event file that cannot be read is skipped and named; its event then
appears in /drawn as failed.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

import h5py
import numpy as np

BLOCK = 128  # rows written at a time; equal to the chunk length
STATUS = {"ok": 0, "no_collision": 1, "no_surface": 2, "hydro_failed": 3,
          "failed": 4}
VARIANT_DATA = ("Q", "ptsum", "mtsum", "Qpt", "y_profile")
# optional (control_dict['hbt']); a design point has them in every file or
# in none, per variant
HBT_DATA = ("hbt_num", "hbt_pairs", "hbt_N")
EVENT_FLOAT = ("weight", "p_acc", "centrality", "estimator")


def event_id_of(name):
    return int(re.match(r"qn_(\d+)\.h5$", os.path.basename(name)).group(1))


def read_drawn(src_dir):
    """event id -> row of events_drawn*.csv (all of them)."""
    rows = {}
    for name in sorted(glob.glob(os.path.join(src_dir, "events_drawn*.csv"))):
        with open(name, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    rows[int(row["event_id"])] = row
                except (KeyError, ValueError):
                    continue
    return rows


def num(row, key, default=np.nan):
    try:
        return float(row.get(key))
    except (TypeError, ValueError):
        return default


GRID_CHECKED = ("pt_edges", "harmonics", "species_pdg", "species_nmax",
                "y_profile_edges")


def same_grid(a, b):
    """Equal, floats to 1e-12: workers with different CPUs compute the same
    grid to the last bit or two (seen: hbt_q_weight, 7e-16)."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return False
    if a.dtype.kind == "f" and b.dtype.kind == "f":
        return bool(np.allclose(a, b, rtol=1e-12, atol=0.0, equal_nan=True))
    return bool(np.array_equal(a, b))


def check_grid(h, h0, name, variants):
    """Refuse a file whose grid (Q binning, HBT grid) or HBT rapidity window
    differs from the first file's: the merged file has one grid, so its sums
    could not be read correctly."""
    keys = sorted(k for k in set(h0["grid"]) | set(h["grid"])
                  if k.startswith("hbt_") or k in GRID_CHECKED)
    for k in keys:
        if (k not in h["grid"] or k not in h0["grid"]
                or not same_grid(h["grid/" + k][()], h0["grid/" + k][()])):
            raise ValueError("%s: /grid/%s differs from the first file's" %
                             (name, k))
    for v in variants:
        a = h["deltaf_" + v].attrs.get("hbt_y_cut")
        b = h0["deltaf_" + v].attrs.get("hbt_y_cut")
        if (a is None) != (b is None) or (a is not None and a != b):
            raise ValueError("%s: deltaf_%s hbt_y_cut %s, the first file %s" %
                             (name, v, a, b))


def create(group, name, shape, dtype):
    chunks = (min(BLOCK, max(shape[0], 1)),) + tuple(shape[1:])
    return group.create_dataset(name, shape=shape, dtype=dtype, chunks=chunks,
                                compression="gzip", compression_opts=1,
                                shuffle=True, maxshape=(None,) + tuple(shape[1:]))


def merge(src_dir, out_path, selection=None, first_n=None):
    files = {}
    for f in glob.glob(os.path.join(src_dir, "qn_*.h5")):
        try:
            with h5py.File(f, "r") as h:
                h["events/event_id"][0]
            files[event_id_of(f)] = f
        except Exception as exc:  # truncated or empty file
            print("skipped unreadable %s (%s)" % (f, exc), flush=True)
    if not files:
        print("no readable qn_*.h5 in %s" % src_dir)
        return 1
    drawn = read_drawn(src_dir)
    accepted = None
    summary = None
    if selection:
        with open(selection + ".json") as fh:
            summary = json.load(fh)
        with open(selection + ".csv", newline="") as fh:
            accepted = {int(r["event_id"]): r for r in csv.DictReader(fh)}
        n_listed = len(accepted)
        if first_n is not None:
            if summary.get("order") != "rank":
                print("--first needs a list made with select_events.py "
                      "--order rank; %s.json says order = %r" %
                      (selection, summary.get("order", "event_id")))
                return 1
            if not 0 < first_n <= n_listed:
                print("--first %d: the list has %d lines" % (first_n, n_listed))
                return 1
            accepted = dict(list(accepted.items())[:first_n])
            beyond = sorted(ev for ev in files if ev not in accepted)
            if beyond:
                print("left out %d events beyond line %d of the list" %
                      (len(beyond), first_n), flush=True)
            files = {ev: f for ev, f in files.items() if ev in accepted}
            drawn = {ev: r for ev, r in drawn.items() if ev in accepted}
            if not files:
                print("no event of the first %d lines in %s" % (first_n, src_dir))
                return 1

    # fate of every drawn id
    fate = {}
    for ev, row in drawn.items():
        st = row.get("status", "")
        fate[ev] = st if st in STATUS else "failed"
        if fate[ev] == "ok" and ev not in files:
            fate[ev] = "failed"
    for ev in files:
        fate[ev] = "ok"
    if accepted is not None:
        for ev in accepted:
            fate.setdefault(ev, "failed")
    rows = sorted(ev for ev, st in fate.items() if st in ("ok", "no_surface"))
    n = len(rows)

    first = files[min(files)]
    with h5py.File(first, "r") as h0, h5py.File(out_path + ".tmp", "w") as out:
        for k, v in h0.attrs.items():
            out.attrs[k] = v
        variants = [v for v in h0.attrs["variants"].split(",") if v]
        h0.copy("grid", out)
        # variant attributes and shapes from the first file
        vshape = {}
        vdata = {}
        for v in variants:
            g = out.create_group("deltaf_" + v)
            for k, val in h0["deltaf_" + v].attrs.items():
                if k != "end_decays":
                    g.attrs[k] = val
            vdata[v] = VARIANT_DATA + tuple(
                d for d in HBT_DATA if d in h0["deltaf_" + v])
            vshape[v] = {d: h0["deltaf_%s/%s" % (v, d)].shape[1:] for d in vdata[v]}
            vshape[v]["dtype"] = {d: h0["deltaf_%s/%s" % (v, d)].dtype for d in vdata[v]}
        hydro_keys = list(h0["hydro"].keys()) if "hydro" in h0 else []
        hydro_cols = {k: h0["hydro/" + k].shape[2:] for k in hydro_keys}
        if "hydro" in h0:
            hg = out.create_group("hydro")
            for k, val in h0["hydro"].attrs.items():
                hg.attrs[k] = val
        # largest number of hydro times over all files
        T = 0
        for f in files.values():
            with h5py.File(f, "r") as h:
                if "hydro/tau" in h:
                    T = max(T, h["hydro/tau"].shape[1])

        e = out.create_group("events")
        ds = {"event_id": create(e, "event_id", (n,), np.int64),
              "status": create(e, "status", (n,), np.uint8),
              "b": create(e, "b", (n,), np.float32),
              "mult": create(e, "mult", (n,), np.float32)}
        for k in EVENT_FLOAT:
            ds[k] = create(e, k, (n,), np.float64)
        vds = {v: {"nsamples": create(out["deltaf_" + v], "nsamples", (n,), np.int32)}
               for v in variants}
        for v in variants:
            for d in vdata[v]:
                vds[v][d] = create(out["deltaf_" + v], d, (n,) + vshape[v][d],
                                   vshape[v]["dtype"][d])
        hds = {}
        for k in hydro_keys:
            shape = (n, T) + hydro_cols[k]
            hds[k] = create(out["hydro"], k, shape, np.float32)

        end_decays = {v: 0 for v in variants}
        for b0 in range(0, n, BLOCK):
            ids = rows[b0:b0 + BLOCK]
            m = len(ids)
            buf = {k: np.full(m, np.nan) for k in EVENT_FLOAT + ("b", "mult")}
            st = np.zeros(m, np.uint8)
            vb = {v: {d: np.zeros((m,) + vshape[v][d], vshape[v]["dtype"][d])
                      for d in vdata[v]} for v in variants}
            ns = {v: np.zeros(m, np.int32) for v in variants}
            hb = {k: np.full((m, T) + hydro_cols[k], np.nan, np.float32)
                  for k in hydro_keys}
            for i, ev in enumerate(ids):
                if ev in files:
                    with h5py.File(files[ev], "r") as h:
                        if h.attrs["variants"] != ",".join(variants):
                            raise ValueError("%s has variants %s, expected %s" %
                                             (files[ev], h.attrs["variants"],
                                              ",".join(variants)))
                        check_grid(h, h0, files[ev], variants)
                        for k in buf:
                            if "events/" + k in h:
                                buf[k][i] = h["events/" + k][0]
                            elif k == "weight":
                                buf[k][i] = 1.0
                        for v in variants:
                            g = h["deltaf_" + v]
                            ns[v][i] = g["nsamples"][0]
                            end_decays[v] += int(g.attrs.get("end_decays", 0))
                            has = tuple(d for d in HBT_DATA if d in g)
                            if VARIANT_DATA + has != vdata[v]:
                                raise ValueError(
                                    "%s: deltaf_%s has HBT data %s, the first "
                                    "file %s" % (files[ev], v, has or "none",
                                                 vdata[v][len(VARIANT_DATA):]
                                                 or "none"))
                            for d in vdata[v]:
                                vb[v][d][i] = g[d][0]
                        for k in hydro_keys:
                            if "hydro/" + k in h:
                                a = h["hydro/" + k][0]
                                hb[k][i, :a.shape[0]] = a
                else:  # no_surface: no particles, weight from the selection
                    st[i] = STATUS["no_surface"]
                    row = drawn.get(ev, {})
                    sel = accepted.get(ev, {}) if accepted else {}
                    buf["weight"][i] = num(sel, "weight", num(row, "weight", 1.0))
                    for k in ("p_acc", "centrality", "estimator"):
                        buf[k][i] = num(sel, k, num(row, k))
                    buf["b"][i] = num(row, "b")
                    buf["mult"][i] = num(row, "mult")
            sl = slice(b0, b0 + m)
            ds["event_id"][sl] = ids
            ds["status"][sl] = st
            for k in buf:
                ds[k][sl] = buf[k]
            for v in variants:
                vds[v]["nsamples"][sl] = ns[v]
                for d in vdata[v]:
                    vds[v][d][sl] = vb[v][d]
            for k in hydro_keys:
                hds[k][sl] = hb[k]
        for v in variants:
            out["deltaf_" + v].attrs["end_decays"] = end_decays[v]

        # every drawn id
        all_ids = sorted(fate)
        d = out.create_group("drawn")
        sel = accepted or {}

        def col(key, default=np.nan):
            return np.array([num(sel.get(ev, {}), key,
                                 num(drawn.get(ev, {}), key, default))
                             for ev in all_ids])
        d.create_dataset("event_id", data=np.array(all_ids, np.int64))
        d.create_dataset("status", data=np.array([STATUS[fate[ev]] for ev in all_ids], np.uint8))
        for key in ("b", "b_over_bmax", "mult", "p_acc", "centrality",
                    "estimator", "u"):
            d.create_dataset(key, data=col(key))
        d.create_dataset("weight", data=col("weight", 1.0))
        d.create_dataset("selection_check", data=np.array(
            [str(drawn.get(ev, {}).get("selection_check", "")) for ev in all_ids],
            dtype=h5py.string_dtype()))
        d.attrs["status_codes"] = json.dumps(STATUS)
        b_max = [num(r, "b_max") for r in drawn.values() if num(r, "b_max") == num(r, "b_max")]
        if b_max:
            out.attrs["b_max"] = b_max[0]
        # counts from the drawn table (an importance-sampled design point
        # overwrites them with the selection's, which cover every drawn id)
        out.attrs["n_drawn"] = len(fate)
        out.attrs["n_no_collision"] = sum(1 for s_ in fate.values() if s_ == "no_collision")
        out.attrs["n_collided"] = len(fate) - out.attrs["n_no_collision"]
        if summary is not None:
            out.attrs["selection_format"] = int(summary.get("format_version", 1))
            for key in ("n_drawn", "n_collided", "n_no_collision", "n_accepted",
                        "b_max", "master_seed"):
                if key in summary:
                    out.attrs[key] = summary[key]
            if "covered_centrality" in summary:
                out.attrs["covered_centrality"] = summary["covered_centrality"]
            # as in selection format 1 (merge_dp_h5.py): the whole summary
            out.attrs["selection"] = json.dumps(summary)
            if first_n is not None:
                out.attrs["selection_first"] = int(first_n)
                out.attrs["selection_fraction"] = first_n / n_listed
        out.attrs["n_events"] = n
    os.replace(out_path + ".tmp", out_path)
    counts = {k: sum(1 for s in fate.values() if s == k) for k in STATUS}
    print("%s: %d rows (%s)" % (out_path, n, ", ".join("%s %d" % kv for kv in counts.items() if kv[1])))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source_dir")
    ap.add_argument("output_h5")
    ap.add_argument("--selection", help="prefix of the select_events.py files")
    ap.add_argument("--first", type=int,
                    help="merge only the first N lines of a rank-ordered list")
    args = ap.parse_args()
    if args.first is not None and not args.selection:
        ap.error("--first needs --selection")
    sys.exit(merge(args.source_dir, args.output_h5, args.selection,
                   args.first))


if __name__ == "__main__":
    main()
