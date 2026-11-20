#!/usr/bin/env python3
"""Window-width scan: cascade time against width, and how far the edges reach."""
import os
import sys
import numpy as np

base = sys.argv[1]
WIDTHS = (1, 2, 3, 4, 6, 8, 10)
np.set_printoptions(linewidth=200, precision=3, suppress=True)


def load(ab, ev, W):
    d = os.path.join(base, "scan", "%s_ev%d_W%d" % (ab, ev, W))
    try:
        p = np.load(os.path.join(d, "profile.npz"))
        wall, user, rss = (float(x) for x in open(os.path.join(d, "time.txt")).read().split()[-3:])
    except Exception as exc:
        return None
    return p, wall, user, rss


def profile(p, group):
    a = p[group]
    nev = int(p["nevents"])
    y = 0.5*(p["edges"][:-1] + p["edges"][1:])
    dy = p["edges"][1] - p["edges"][0]
    return y, dy, nev, a


for ab in ("SMASH", "UrQMD"):
    for ev in (140, 101):
        rows = {W: load(ab, ev, W) for W in WIDTHS}
        if rows[10] is None:
            print(ab, ev, "reference width missing")
            continue
        print("=" * 100)
        print("%s  event %d" % (ab, ev))
        # ---- reference plateau from the widest run, |y| < 2.5
        p10 = rows[10][0]
        y, dy, nev, a = profile(p10, "charged")
        core = np.abs(y) < 2.5
        ref_dn = a[0][core].sum()/nev/(core.sum()*dy)
        ref_pt = a[1][core].sum()/a[0][core].sum()
        psi = 0.5*np.arctan2(a[3][core].sum(), a[2][core].sum())
        ref_v2 = (a[2][core].sum()*np.cos(2*psi) + a[3][core].sum()*np.sin(2*psi))/a[0][core].sum()
        print("reference (W = 10, |y| < 2.5): dNch/dy %.2f  <pT> %.4f  v2 %.4f" % (ref_dn, ref_pt, ref_v2))
        print("%3s %5s %9s %9s %10s %9s %8s" % ("W", "NS", "N/event", "wall [s]", "s/event", "maxRSS MB", "ncoll/N"))
        times = {}
        for W in WIDTHS:
            if rows[W] is None:
                print("%3d  missing" % W)
                continue
            p, wall, user, rss = rows[W]
            n = int(p["nevents"])
            times[W] = wall/n
            print("%3d %5d %9.0f %9.1f %10.3f %9.0f %8.2f" %
                  (W, n, p["npart"].mean(), wall, wall/n, rss/1024.0, float(p["ncoll"])/p["npart"].sum()))
        # ---- power law between successive widths
        ws = sorted(times)
        if len(ws) > 2:
            lw, lt = np.log(ws), np.log([times[w] for w in ws])
            print("local exponent d ln t / d ln W:", " ".join("%d-%d: %.2f" % (ws[i], ws[i+1], (lt[i+1]-lt[i])/(lw[i+1]-lw[i])) for i in range(len(ws)-1)))
        # ---- edge reach: quantities against the distance to the nearest edge
        dist_edges = np.arange(0, 3.01, 0.25)
        for group in ("charged", "pi", "p"):
            num = np.zeros((3, len(dist_edges)-1))
            den = np.zeros((3, len(dist_edges)-1))
            yr, dyr, nevr, ar = profile(p10, group)
            corer = np.abs(yr) < 2.5
            rdn = ar[0][corer].sum()/nevr/(corer.sum()*dyr)
            rpt = ar[1][corer].sum()/ar[0][corer].sum()
            psir = 0.5*np.arctan2(ar[3][corer].sum(), ar[2][corer].sum())
            rv2 = (ar[2][corer].sum()*np.cos(2*psir) + ar[3][corer].sum()*np.sin(2*psir))/ar[0][corer].sum()
            for W in WIDTHS:
                if rows[W] is None or W < 2:
                    continue
                yy, dyy, nn, aa = profile(rows[W][0], group)
                dist = W/2.0 - np.abs(yy)
                for i in range(len(dist_edges)-1):
                    m = (dist > dist_edges[i]) & (dist < dist_edges[i+1])
                    if not m.any():
                        continue
                    N = aa[0][m].sum()
                    num[0, i] += N
                    den[0, i] += nn*m.sum()*dyy*rdn
                    num[1, i] += aa[1][m].sum()
                    den[1, i] += N*rpt
                    num[2, i] += aa[2][m].sum()*np.cos(2*psir) + aa[3][m].sum()*np.sin(2*psir)
                    den[2, i] += N*rv2
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = num/den
                err = 1.0/np.sqrt(np.maximum(num[0], 1))
            print("%s: ratio to the plateau against the distance from the nearest edge (all widths >= 2 pooled)" % group)
            print("   distance   ", " ".join("%6.2f" % (0.5*(dist_edges[i]+dist_edges[i+1])) for i in range(len(dist_edges)-1)))
            print("   dN/dy      ", " ".join("%6.3f" % r for r in ratio[0]))
            print("   <pT>       ", " ".join("%6.3f" % r for r in ratio[1]))
            print("   v2         ", " ".join("%6.2f" % r for r in ratio[2]))
            print("   stat (dN)  ", " ".join("%6.3f" % e for e in err))
        # ---- usable particles per second for a few edge widths
        print("usable charged particles per cascade second, (W - 2 Delta) dNch/dy / (s per event):")
        print("   Delta  " + " ".join("W=%-6d" % w for w in ws))
        for delta in (0.5, 1.0, 1.5, 2.0):
            print("   %4.1f   " % delta + " ".join("%-8.1f" % (max(w - 2*delta, 0)*ref_dn/times[w]) for w in ws))
