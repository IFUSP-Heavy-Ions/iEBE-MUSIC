#!/usr/bin/env python3
"""Merge per-event spvn_results_*.h5 files into one h5, by h5py copy.

Same output as combine_multiple_hdf5.py (one top-level group per event, named
after the global event id, with its datasets) but done in one process: the
h5copy-per-event approach spawns ~10,000 subprocesses for a 10,000-event
design point.  Sub-groups (deltaf_<name>, one per delta f model) and the
attributes of groups and datasets (model list, iSS overrides, toolkit pT grid,
file headers) are copied too.

Usage: merge_dp_h5.py SOURCE_DIR OUTPUT_H5 [--selection PREFIX]

For an importance-sampled design point, --selection names the files written by
scripts/select_events.py (PREFIX.csv, .json, .npz).  The merged file then
carries what is needed to turn its weighted events back into a minimum-bias
sample, as attributes of the root group:

    selection_format   version of this layout (1)
    n_drawn, n_collided, n_no_collision, n_accepted, b_max, master_seed
    covered_centrality [low, high] percent in which events could be accepted
    selection          the whole summary, as a JSON string

and the three files are copied next to it, the list gaining a `status` column
that says what became of each accepted event:

    ok          simulated; its group is in the merged file
    no_surface  a real collision whose fireball never reached the freeze-out
                temperature: an event with no particles, to be counted with
                its weight
    failed      nothing came back (lost job, crash): to be re-run, never to be
                counted as empty
"""
import argparse
import csv
import glob
import json
import os
import shutil
import sys

import h5py


def copy_group(sg, dg):
    """Copy attrs, datasets and sub-groups of sg into the empty group dg."""
    for key, val in sg.attrs.items():
        dg.attrs[key] = val
    for dname in sg.keys():
        obj = sg[dname]
        if isinstance(obj, h5py.Dataset):
            dset = dg.create_dataset(dname, data=obj[()])
            for key, val in obj.attrs.items():
                dset.attrs[key] = val
        elif isinstance(obj, h5py.Group):
            copy_group(obj, dg.create_group(dname))


def merge(src_dir, out_path):
    files = sorted(glob.glob(os.path.join(src_dir, "spvn_results_*.h5")),
                   key=lambda p: int(os.path.basename(p).split("_")[-1].split(".")[0]))
    if not files:
        print("no input files in", src_dir)
        return 1
    skipped = []
    hdf5_sig = b"\x89HDF\r\n\x1a\n"
    with h5py.File(out_path, "w") as out:
        for i, path in enumerate(files):
            # A single truncated file (a killed transfer can leave a 0-byte h5)
            # must not abort the whole design point: skip it and report.
            try:
                with open(path, "rb") as probe:
                    if probe.read(8) != hdf5_sig:
                        skipped.append(os.path.basename(path))
                        continue
            except OSError:
                skipped.append(os.path.basename(path))
                continue
            # Open once to prove the file is readable before copying anything: a
            # truncated file keeps the 8-byte signature but fails inside h5py, and
            # discovering that midway through the group loop would leave a
            # half-copied event in the output.
            try:
                with h5py.File(path, "r") as src:
                    names = list(src.keys())
            except OSError as exc:
                skipped.append("%s (%s)" % (os.path.basename(path), str(exc)[:48]))
                continue
            with h5py.File(path, "r") as src:
                for gname in names:
                    if gname in out:
                        # duplicate event id (re-run overlap): keep the first
                        continue
                    copy_group(src[gname], out.create_group(gname))
            if (i + 1) % 500 == 0:
                print("  merged %d/%d events" % (i + 1, len(files)), flush=True)
    if skipped:
        print("WARNING: skipped %d unreadable file(s): %s" % (len(skipped), ", ".join(skipped[:10])))
    print("merged %d events -> %s" % (len(files) - len(skipped), out_path))
    return 0


def drawn_status(src_dir):
    """event id -> status, from every events_drawn*.csv in src_dir."""
    status = {}
    for name in glob.glob(os.path.join(src_dir, "events_drawn*.csv")):
        with open(name, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    status[int(row["event_id"])] = row.get("status", "")
                except (KeyError, ValueError):
                    continue
    return status


def attach_selection(src_dir, out_path, prefix):
    """Record the event selection in the merged file and next to it."""
    with open(prefix + ".json") as fh:
        summary = json.load(fh)
    with open(prefix + ".csv", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = [c for c in reader.fieldnames if c != "status"]
        accepted = list(reader)
    drawn = drawn_status(src_dir)
    counts = {"ok": 0, "no_surface": 0, "failed": 0}
    with h5py.File(out_path, "a") as out:
        for row in accepted:
            event_id = int(row["event_id"])
            if "spvn_results_{}".format(event_id) in out:
                row["status"] = "ok"
            elif drawn.get(event_id) == "no_surface":
                row["status"] = "no_surface"
            else:
                row["status"] = "failed"
            counts[row["status"]] += 1
        out.attrs["selection_format"] = int(summary.get("format_version", 1))
        for key in ("n_drawn", "n_collided", "n_no_collision", "n_accepted",
                    "b_max", "master_seed"):
            if key in summary:
                out.attrs[key] = summary[key]
        if "covered_centrality" in summary:
            out.attrs["covered_centrality"] = summary["covered_centrality"]
        out.attrs["selection"] = json.dumps(summary)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    base = os.path.basename(prefix)
    tmp = os.path.join(out_dir, base + ".csv.tmp")
    with open(tmp, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns + ["status"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(accepted)
    os.replace(tmp, os.path.join(out_dir, base + ".csv"))
    for ext in (".json", ".npz"):
        src, dst = prefix + ext, os.path.join(out_dir, base + ext)
        if os.path.exists(src) and os.path.abspath(src) != dst:
            shutil.copy(src, dst)
    print("selection: {} accepted -> {} ok, {} no_surface, {} failed".format(
        len(accepted), counts["ok"], counts["no_surface"], counts["failed"]))


if __name__ == "__main__" and "--selection" in sys.argv:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source_dir")
    ap.add_argument("output_h5")
    ap.add_argument("--selection", required=True,
                    help="prefix of the select_events.py files")
    args = ap.parse_args()
    rc = merge(args.source_dir, args.output_h5)
    if rc == 0:
        attach_selection(args.source_dir, args.output_h5, args.selection)
    sys.exit(rc)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(merge(sys.argv[1], sys.argv[2]))
