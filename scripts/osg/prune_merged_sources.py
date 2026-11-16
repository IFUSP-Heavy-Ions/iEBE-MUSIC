#!/usr/bin/env python3
"""Delete raw archives for design points that are fully merged and verified.

Why this exists: inodes, not bytes, are the binding constraint on /data.  A
design point costs ~100 archive files per batch, so campaign 2 at 1,000 points x
3 batches is ~300k files, and the local branch was already 69 % full with ~300k
inodes free.  One merged h5 is a single file instead of ~300, so pruning a fully
merged point returns ~299 inodes and costs 450 MB instead of 280 MB -- a bad
trade in bytes and the only sensible one in files.

The danger is the reverse of the usual one: after the raw archives are gone, a
batch that arrives *later* cannot be merged, because the merge reads the
archives.  So a point is pruned only when all of this holds:

  1. merged/<dp>/<dp>.h5 opens and its last group reads (not truncated);
  2. it holds events from all THREE batch id ranges (0-1999, 2000-3999,
     4000-5999), each at >= --min-per-batch (default 1900 of 2000 drawn), so
     every batch has arrived and been merged -- batch 3 is the last one;
  3. it holds the three delta f model subgroups (campaign-2 layout);
  4. sources.txt's archive count equals the number of raw archives on disk, i.e.
     the merge included every archive present (nothing newer sits unmerged);
  5. the merge log is newer than the newest raw archive.

Anything that fails is reported with the reason and left alone.  Dry run by
default.

Run it when no consolidation is in progress: the merger writes <dp>.h5.tmp and
renames it, and opening a file mid-write blocks on the HDF5 lock (a full-range run
then looks like a hang and loses its buffered output when killed).

Usage:
    python3 scripts/osg/prune_merged_sources.py [--apply] [--merged DIR] [--raw DIR]
                                            [--dps 1-1000] [--min-per-batch 1900]
"""
import argparse
import glob
import os
import re
import sys

BATCHES = ((0, 1999), (2000, 3999), (4000, 5999))

# set from --events-per-job; each job writes this many events
args_events_per_job = 20


def group_ids(h5file):
    ids = []
    for key in h5file.keys():
        m = re.search(r"spvn_results_(\d+)$", key)
        if m:
            ids.append(int(m.group(1)))
    return ids


def archives_of(dp_dir):
    """Raw archives for one design point, in either layout.

    Takes the design point's own directory (not the campaign root) -- globbing
    "dp*" beneath it found nothing, which made every point look already pruned.
    """
    # Only real job archives: "spvn_results_*.tar.gz" (batch 1) and
    # "spvn_results_e<offset>_*.tar.gz" (later batches).  A plain "*.tar.gz" also
    # matched "raw_spvn_results.tar.gz", the whole-directory bundle left by the
    # old layout, which made the count one higher than sources.txt and refused 62
    # otherwise-complete design points.
    files = glob.glob(os.path.join(dp_dir, "tarballs", "spvn_results_*.tar.gz"))
    files += glob.glob(os.path.join(dp_dir, "spvn_results_*.tar.gz"))
    return files


def check_point(dp, raw_root, merged_root, min_per_batch, campaign_complete,
                require_models):
    """Return (ok, reason, n_archives, bytes).

    campaign_complete skips the per-batch event count: for a campaign whose
    submission has definitively finished, "no more archives will arrive" is
    known, so the only requirement is that everything on disk was merged.  The
    batch check exists for a *running* campaign, where a batch still to come
    would silently strand its events (campaign 1 used four offsets and most of
    its points carry a single batch, so the campaign-2 assumption would refuse
    every one of them).
    """
    mdir = os.path.join(merged_root, dp)
    h5 = os.path.join(mdir, dp + ".h5")
    if not os.path.exists(h5):
        return False, "no merged h5", 0, 0

    raw = archives_of(os.path.join(raw_root, dp))
    nraw = len(raw)
    if nraw == 0:
        return False, "no raw archives (already pruned?)", 0, 0
    nbytes = sum(os.path.getsize(p) for p in raw)

    try:
        import h5py
    except ImportError:
        return False, "h5py not available", nraw, nbytes

    try:
        with h5py.File(h5, "r") as f:
            ids = group_ids(f)
            if not ids:
                return False, "merged h5 has no event groups", nraw, nbytes
            # (1) not truncated: read a real dataset from the last group
            last = f[sorted(f.keys())[-1]]
            datasets = [k for k in last.keys()
                        if not k.startswith("deltaf_")]
            if datasets:
                last[datasets[0]][()]
            # (2) all three batches present
            per_batch = [sum(1 for i in ids if lo <= i <= hi)
                         for lo, hi in BATCHES]
            if (not campaign_complete) and any(c < min_per_batch
                                               for c in per_batch):
                return (False,
                        "batches incomplete: %s (need >=%d each)" %
                        (per_batch, min_per_batch), nraw, nbytes)
            # (3) campaign-2 model subgroups
            models = [k for k in last.keys() if k.startswith("deltaf_")]
            if len(models) < require_models:
                return False, "only %d deltaf subgroup(s)" % len(models), \
                       nraw, nbytes
    except Exception as exc:  # noqa: BLE001 - any read failure blocks deletion
        return False, "unreadable h5: %s" % str(exc)[:60], nraw, nbytes

    # (4) the merge included every archive on disk
    src = os.path.join(mdir, "sources.txt")
    if not os.path.exists(src):
        return False, "no sources.txt", nraw, nbytes
    m = re.search(r"tars=(\d+)", open(src).read())
    if not m:
        return False, "sources.txt unparsable", nraw, nbytes
    if int(m.group(1)) != nraw:
        return (False, "sources.txt says %s archives, %d on disk"
                % (m.group(1), nraw), nraw, nbytes)

    # (5) the merged file actually covers the archives on disk.
    # Comparing mtimes was wrong: an archive re-pulled from the AP has a fresh
    # mtime and identical content, so every re-pulled point looked stale (626 of
    # 1000 in campaign-1 A=96, each with 95-99 % event coverage, i.e. merged).
    # Each job writes --events-per-job events, and a few percent are legitimately
    # skipped (empty freeze-out surface), so require 90 % coverage.
    expected = args_events_per_job * nraw
    if expected and len(ids) < 0.90 * expected:
        return (False, "covers %d of ~%d events (%.0f %%)"
                % (len(ids), expected, 100.0 * len(ids) / expected), nraw, nbytes)

    return True, "ok", nraw, nbytes


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="/data/mluzum/zr96c2_results/merged")
    ap.add_argument("--raw", default="/data/mluzum/zr96c2_results/prod")
    ap.add_argument("--dps", default="1-1000",
                    help="design-point range, e.g. 1-1000")
    ap.add_argument("--min-per-batch", type=int, default=1900,
                    help="events required in each batch id range (default 1900)")
    ap.add_argument("--events-per-job", type=int, default=20,
                    help="events written per job, for the coverage check "
                         "(default 20)")
    ap.add_argument("--models", type=int, default=3,
                    help="deltaf_* subgroups required per event group "
                         "(3 for campaign 2, 0 for campaign 1)")
    ap.add_argument("--campaign-complete", action="store_true",
                    help="submission has finished: skip the per-batch event "
                         "count and require only that everything on disk was "
                         "merged (use for campaign 1)")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; default is a dry run")
    args = ap.parse_args()

    m = re.match(r"(\d+)-(\d+)$", args.dps)
    if not m:
        raise SystemExit("--dps must look like 1-1000")
    lo, hi = int(m.group(1)), int(m.group(2))
    global args_events_per_job
    args_events_per_job = args.events_per_job

    pruned = skipped = files_freed = bytes_freed = 0
    reasons = {}
    for i in range(lo, hi + 1):
        dp = "dp%04d" % i
        ok, reason, n, nb = check_point(dp, args.raw, args.merged,
                                        args.min_per_batch,
                                        args.campaign_complete, args.models)
        if ok:
            pruned += 1
            files_freed += n
            bytes_freed += nb
            print("%s %s delete %d archives (%.0f MB)" %
                  (dp, "WOULD" if not args.apply else "DELETED", n, nb / 1e6))
            if args.apply:
                for p in archives_of(os.path.join(args.raw, dp)):
                    try:
                        os.remove(p)
                    except OSError as exc:
                        print("   remove failed: %s" % exc)
        else:
            skipped += 1
            reasons[reason.split(":")[0]] = reasons.get(
                reason.split(":")[0], 0) + 1

    print()
    print("design points prunable : %d" % pruned)
    print("design points left alone: %d" % skipped)
    print("files removed          : %d   (inodes returned)" % files_freed)
    print("bytes in those archives: %.1f GB" % (bytes_freed / 1e9))
    if skipped:
        print("reasons:")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print("  %5d  %s" % (c, r))
    if not args.apply and pruned:
        print("\nre-run with --apply to delete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
