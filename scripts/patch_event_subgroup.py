#!/usr/bin/env python3
"""Repair one event of one design point from a local re-run.

Two failure modes seen in production output:
  * a single deltaf_* subgroup missing some identified-particle tables;
  * a whole event group written only partially (few tables, no attrs).
The second needs the group replaced; the first only needs the affected subgroup,
because the other models in that event were complete and are left byte-for-byte
as produced.

The fix is applied to BOTH copies: the merged h5 (the analysis product) and the
per-event h5 inside the raw archive, so a later re-merge inherits the correction
instead of reintroducing the damage.  The archive is repacked in place and the
pre-patch copy kept alongside as .bak.

Usage:
    patch_event_subgroup.py --src RERUN.h5 --merged DP.h5 --archive TARBALL \\
        --event 1116 --model Grad22        # or --model whole
    add --dry-run to report what would change
"""
import argparse
import glob
import os
import shutil
import sys
import tarfile
import tempfile

import h5py


def group_name(event):
    return "spvn_results_%d" % event


def copy_group(src, dst):
    for k, v in src.attrs.items():
        dst.attrs[k] = v
    for name in src:
        o = src[name]
        if isinstance(o, h5py.Dataset):
            d = dst.create_dataset(name, data=o[()])
            for k, v in o.attrs.items():
                d.attrs[k] = v
        else:
            copy_group(o, dst.create_group(name))


def patch_h5(path, src_path, group, model, dry):
    """Apply the repair to one h5 file; return a short description."""
    with h5py.File(src_path, "r") as fs, h5py.File(path, "r+") as ft:
        sg = fs[list(fs.keys())[0]] if group not in fs else fs[group]
        if group not in ft:
            return "%s: group absent (nothing to patch)" % os.path.basename(path)
        g = ft[group]
        if model == "whole":
            before = len(g.keys())
            if not dry:
                del ft[group]
                copy_group(sg, ft.create_group(group))
            return "%s: group replaced (%d -> %d subgroups, attrs now %d)" % (
                os.path.basename(path), before, len(sg.keys()), len(sg.attrs))
        key = "deltaf_" + model          # subgroups are deltaf_Grad22, ...
        if key not in sg:
            return "%s: source has no %s" % (os.path.basename(path), key)
        before = len(g[key].keys()) if key in g else 0
        if not dry:
            if key in g:
                del g[key]
            copy_group(sg[key], g.create_group(key))
        return "%s: %s %d -> %d tables" % (os.path.basename(path), key, before,
                                           len(sg[key].keys()))


def patch_archive(path, src_path, event, model, dry):
    if not os.path.exists(path):
        return "archive missing: %s" % path
    group = group_name(event)
    inner = "spvn_results/spvn_results_%d.h5" % event
    tmpd = tempfile.mkdtemp(prefix="patch_", dir="/tmp")
    try:
        with tarfile.open(path) as t:
            names = t.getnames()
            if inner not in names:
                return "archive has no %s" % inner
            if not dry:
                t.extractall(path=tmpd)  # the WHOLE archive: repacking one entry
                                         # would drop every other event in it
            else:
                t.extract(inner, path=tmpd)
        hp = os.path.join(tmpd, inner)
        msg = patch_h5(hp, src_path, group, model, dry)
        if dry:
            return "archive(dry): " + msg
        entries = sorted(set(n.split("/")[0] for n in names))
        shutil.copy2(path, path + ".bak")
        with tarfile.open(path, "w:gz") as t:
            for e in entries:
                t.add(os.path.join(tmpd, e), arcname=e)
        with tarfile.open(path) as t:
            after = len(t.getnames())
        return "archive: %s (%d -> %d files)" % (msg, len(names), after)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--merged", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--event", type=int, required=True)
    ap.add_argument("--model", required=True,
                    help="Grad22 | CE | PTB | whole")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    group = group_name(a.event)
    print(patch_h5(a.merged, a.src, group, a.model, a.dry_run))
    print(patch_archive(a.archive, a.src, a.event, a.model, a.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
