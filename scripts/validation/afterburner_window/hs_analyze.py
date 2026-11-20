#!/usr/bin/env python3
"""Edge reach from the high-statistics runs: dN/dy, <pT>, v2, v3 against the
distance from the nearest edge of the sampled rapidity window.

    hs_analyze.py <base dir> <afterburner> <event> <width> [plateau distance=2]
"""
import glob
import os
import sys
import numpy as np

base, ab, ev, W = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
dplat = float(sys.argv[5]) if len(sys.argv) > 5 else 2.0
files = sorted(glob.glob(os.path.join(base, "hs", "%s_ev%d_W%g" % (ab, ev, W), "job*", "profile_*.npz")))
files = [f for f in files if "/job0/" not in f]
if not files:
    sys.exit("no chunks")
tot = {}
nev = 0
npart = 0
for f in files:
    p = np.load(f)
    nev += int(p["nevents"])
    npart += int(p["npart"].sum())
    for g in ("charged", "pi", "K", "p"):
        tot[g] = tot.get(g, 0) + p[g]
edges = p["edges"]
y = 0.5*(edges[:-1] + edges[1:])
dy = edges[1] - edges[0]
dist = W/2.0 - np.abs(y)
print("%s event %d, window width %g: %d chunks, %d cascade events, %.0f particles per event" %
      (ab, ev, W, len(files), nev, npart/nev))
dedges = np.arange(0, W/2.0 + 1e-9, 0.25)
for g in ("charged", "pi", "K", "p"):
    a = tot[g]
    plat = dist > dplat
    Np = a[0][plat].sum()
    dn_ref = Np/nev/(plat.sum()*dy)
    pt_ref = a[1][plat].sum()/Np
    ref = {}
    psi = {}
    for n, (ic, isn) in ((2, (2, 3)), (3, (4, 5))):
        C, S = a[ic][plat].sum(), a[isn][plat].sum()
        psi[n] = np.arctan2(S, C)/n
        ref[n] = np.hypot(C, S)/Np
    print("\n%s   plateau (distance > %g): dN/dy %.3f  <pT> %.4f  v2 %.5f +- %.5f  v3 %.5f +- %.5f" %
          (g, dplat, dn_ref, pt_ref, ref[2], 1/np.sqrt(2*Np), ref[3], 1/np.sqrt(2*Np)))
    print("  distance    dN/dy ratio        <pT> ratio         v2 ratio          v3 ratio")
    for i in range(len(dedges) - 1):
        m = (dist > dedges[i]) & (dist < dedges[i+1])
        if not m.any():
            continue
        N = a[0][m].sum()
        if N == 0:
            continue
        r_dn = N/nev/(m.sum()*dy)/dn_ref
        r_pt = a[1][m].sum()/N/pt_ref
        out = "  %4.2f-%4.2f   %6.4f +- %6.4f   %6.4f +- %6.4f" % (
            dedges[i], dedges[i+1], r_dn, r_dn/np.sqrt(N), r_pt, 0.6/np.sqrt(N))
        for n, (ic, isn) in ((2, (2, 3)), (3, (4, 5))):
            v = (a[ic][m].sum()*np.cos(n*psi[n]) + a[isn][m].sum()*np.sin(n*psi[n]))/N
            err = np.hypot(1/np.sqrt(2*N), v/ref[n]/np.sqrt(2*Np))/ref[n]
            out += "   %6.3f +- %5.3f" % (v/ref[n], err)
        print(out)
