#!/usr/bin/env python3
"""Rapidity profiles of a particle list (SMASH binary or the chain's binary).

    profile.py <smash|bin> <file> <out.npz> [y_half_range=6] [dy=0.25]

Per species group (charged, pi, K, p) and rapidity bin, summed over all
oversampled events of the file: N, sum pT, sum cos/sin 2 phi.
"""
import sys
import numpy as np

SMASH_DT = np.dtype([("t", "<f8"), ("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
                     ("mass", "<f8"), ("p0", "<f8"), ("px", "<f8"),
                     ("py", "<f8"), ("pz", "<f8"), ("pdg", "<i4"),
                     ("id", "<i4"), ("charge", "<i4"), ("ncoll", "<i4"),
                     ("form_time", "<f8"), ("xsecfac", "<f8"),
                     ("proc_id", "<i4"), ("proc_type", "<i4"),
                     ("t_last", "<f8"), ("mother1", "<i4"), ("mother2", "<i4"),
                     ("baryon", "<i4"), ("strangeness", "<i4")])
BIN_DT = np.dtype([("pdg", "<i4"), ("mass", "<f4"), ("t", "<f4"), ("x", "<f4"),
                   ("y", "<f4"), ("z", "<f4"), ("p0", "<f4"), ("px", "<f4"),
                   ("py", "<f4"), ("pz", "<f4")])
URQMD_DT = np.dtype([("ityp", "<i4"), ("iso3", "<i4"), ("charge", "<i4"),
                     ("ncoll", "<i4"), ("parent", "<i4"), ("ptype", "<i4"),
                     ("mass", "<f4"), ("t", "<f4"), ("x", "<f4"), ("y", "<f4"),
                     ("z", "<f4"), ("p0", "<f4"), ("px", "<f4"), ("py", "<f4"),
                     ("pz", "<f4")])
# charges of the hadrons that are stable in the chain (for the chain's binary,
# which carries no charge column)
CHARGED = {211, 321, 2212, 3222, 3112, 3312, 3334}


def read_smash(name):
    data = open(name, "rb").read()
    assert data[:4] == b"SMSH", data[:4]
    version, variant, nver = np.frombuffer(data, "<u2,<u2,<u4", 1, 4)[0]
    off = 12 + int(nver)
    events = []
    while off < len(data):
        block = data[off:off + 1]
        off += 1
        if block == b"p":
            ev, ens, n = np.frombuffer(data, "<i4,<i4,<u4", 1, off)[0]
            off += 12
            events.append(np.frombuffer(data, SMASH_DT, int(n), off))
            off += int(n)*SMASH_DT.itemsize
        elif block == b"f":
            off += 4 + 4 + 8 + 1
        else:
            raise ValueError("unknown block %r at %d" % (block, off))
    return events, (int(version), int(variant))


def read_bin(name):
    data = open(name, "rb").read()
    off = 0
    events = []
    while off < len(data):
        n = int(np.frombuffer(data, "<i4", 1, off)[0])
        off += 4
        events.append(np.frombuffer(data, BIN_DT, n, off))
        off += n*BIN_DT.itemsize
    return events, None


def read_urqmd(name):
    """UrQMD output converted by the toolkit's convert_to_binary."""
    data = open(name, "rb").read()
    off = 0
    events = []
    while off < len(data):
        n = int(np.frombuffer(data, "<i4", 1, off)[0])
        off += 4 + 8*4
        events.append(np.frombuffer(data, URQMD_DT, n, off))
        off += n*URQMD_DT.itemsize
    return events, None


def main():
    kind, name, out = sys.argv[1:4]
    ymax = float(sys.argv[4]) if len(sys.argv) > 4 else 6.0
    dy = float(sys.argv[5]) if len(sys.argv) > 5 else 0.25
    events, version = {"smash": read_smash, "bin": read_bin,
                       "urqmd": read_urqmd}[kind](name)
    edges = np.arange(-ymax, ymax + 0.5*dy, dy)
    nb = len(edges) - 1
    groups = ("charged", "pi", "K", "p")
    # rows: N, sum pT, cos 2phi, sin 2phi, cos 3phi, sin 3phi
    acc = {g: np.zeros((6, nb)) for g in groups}
    npart = []
    pdg_count = {}
    ncoll_sum = 0.0
    for ev in events:
        npart.append(len(ev))
        pdg = ev["ityp"] if kind == "urqmd" else ev["pdg"]
        e, pz = ev["p0"].astype("f8"), ev["pz"].astype("f8")
        px, py = ev["px"].astype("f8"), ev["py"].astype("f8")
        ok = e > np.abs(pz)
        yrap = np.full(len(ev), np.nan)
        yrap[ok] = 0.5*np.log((e[ok] + pz[ok])/(e[ok] - pz[ok]))
        pt = np.hypot(px, py)
        phi = np.arctan2(py, px)
        apdg = np.abs(pdg)
        if kind in ("smash", "urqmd"):
            charged = ev["charge"] != 0
            ncoll_sum += float(ev["ncoll"].sum())
        else:
            charged = np.isin(apdg, list(CHARGED))
        if kind == "urqmd":
            sel = {"charged": charged, "pi": (apdg == 101) & charged,
                   "K": (apdg == 106) & charged, "p": (apdg == 1) & charged}
        else:
            sel = {"charged": charged, "pi": apdg == 211, "K": apdg == 321,
                   "p": apdg == 2212}
        ib = np.floor((yrap + ymax)/dy)
        inside = np.isfinite(yrap) & (ib >= 0) & (ib < nb)
        for g in groups:
            m = sel[g] & inside
            i = ib[m].astype(int)
            acc[g][0] += np.bincount(i, minlength=nb)
            acc[g][1] += np.bincount(i, weights=pt[m], minlength=nb)
            acc[g][2] += np.bincount(i, weights=np.cos(2*phi[m]), minlength=nb)
            acc[g][3] += np.bincount(i, weights=np.sin(2*phi[m]), minlength=nb)
            acc[g][4] += np.bincount(i, weights=np.cos(3*phi[m]), minlength=nb)
            acc[g][5] += np.bincount(i, weights=np.sin(3*phi[m]), minlength=nb)
        u, c = np.unique(pdg, return_counts=True)
        for a, b in zip(u, c):
            pdg_count[int(a)] = pdg_count.get(int(a), 0) + int(b)
    np.savez(out, edges=edges, nevents=len(events), npart=np.array(npart),
             ncoll=ncoll_sum,
             pdg=np.array(sorted(pdg_count)),
             pdg_n=np.array([pdg_count[k] for k in sorted(pdg_count)]),
             **{g: acc[g] for g in groups})
    print("%s: %d events, %.0f particles per event (min %d, max %d)%s" %
          (name, len(events), np.mean(npart), min(npart), max(npart),
           "" if version is None else ", format %s" % (version,)))


if __name__ == "__main__":
    main()
