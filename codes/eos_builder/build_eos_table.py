#!/usr/bin/env python3
"""Equation of state at mu_B = 0 for MUSIC (EOS_to_use 24) from a speed of
sound c_s^2(T) above the switching temperature and the hadron gas of the
particlization list below it.

    build_eos_table.py --cs2 <T [GeV], cs2 file> --T-sw <GeV>
                       --hadron-list <pdg-*.dat> --out <table>

Below T_sw the fluid is the ideal hadron-resonance gas of the list iSS samples:
every light-flavour species of the table at its pole mass and spin
degeneracy, antibaryons added (the tables list baryons only), photon left out,
quantum statistics --
the same gas as iSS's own HRGEOS_PST-*.dat tables (iSS/utilities/
make_hrg_eos.py), so e, P and s are continuous with what iSS samples, and iSS
(regulateEOS) finds T_sw again from the freeze-out energy density.

Above T_sw the input c_s^2(T) (linear between its points) is integrated with
the hadron gas at T_sw as the anchor:

    s(T) = s_HRG(T_sw) exp( int_{T_sw}^{T} dT' / (T' c_s^2(T')) )
    P(T) = P_HRG(T_sw) + int_{T_sw}^{T} s dT'
    e(T) = T s - P

so the table is thermodynamically consistent (e + P = T s, s = dP/dT) and
continuous in e, P, s at T_sw; c_s^2 itself may jump there.

Output (MUSIC's EOS_gp reader): first line the number of rows N followed by a
JSON header that MUSIC ignores (T_sw, the hadron list and its sha256, the
sha256 of the c_s^2 input and anything passed with --meta); then N rows of
e [GeV/fm^3], T [GeV], P [GeV/fm^3], c_s^2, s [1/fm^3], strictly increasing in
e, starting with e = 0.  Rows are spaced by about 0.4% in e (a few thousand),
which keeps MUSIC's linear interpolation at the 1e-6 level.
"""
import argparse
import hashlib
import json
import os

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.special import k0, k1

HBARC = 0.19733  # GeV fm, MUSIC's Util::hbarc
NTERMS = 20  # terms of the Bessel series of the quantum distributions
FORMAT = "iebe-music-eos-table-1"
T_LOW = 0.010  # GeV, lowest tabulated temperature above the e = 0 row
DLN_E = 0.004  # target spacing of the rows in ln e
T_STEP_UP = 2e-5  # GeV, integration step above T_sw


# ── hadron gas ──────────────────────────────────────────────────────────────

def heavy_flavour(pdg):
    """True if one of the quark digits of the PDG code is c or b."""
    a = abs(pdg)
    return any((a // 10**k) % 10 in (4, 5) for k in (1, 2, 3))


def read_species(pdg_file):
    """(mass, degeneracy, statistics) arrays of an iSS particle table;
    statistics -1 Bose, +1 Fermi.  Same rules as iSS's make_hrg_eos.py:
    antibaryons added, photon (22) left out, decay lines skipped; charm and
    bottom hadrons left out as well (iSS's HRGEOS_PST-SMASH.dat has none; the
    other lists contain none).  Heavy flavour is read from the PDG code's
    quark digits, because the tables' charm/bottom columns are not reliable
    (omega(782) has bottom = 3 in pdg-urqmd_v3.3+.dat and pdg-s95pv1.dat)."""
    m, g, stat = [], [], []
    for line in open(pdg_file):
        c = line.split()
        if len(c) < 12 or c[1].lstrip("-").isdigit():
            continue  # decay lines
        pdg, mass, deg, baryon = int(c[0]), float(c[2]), int(c[4]), int(c[5])
        if pdg == 22 or heavy_flavour(pdg):
            continue
        copies = 2 if baryon != 0 else 1
        for _ in range(copies):
            m.append(mass)
            g.append(deg)
            stat.append(1 if baryon != 0 else -1)
    return np.array(m), np.array(g, float), np.array(stat, float)


def hrg_thermo(T, species, chunk=200, with_dedT=False):
    """P and e [GeV/fm^3] of the hadron gas at the temperatures T [GeV], and
    de/dT [1/fm^3] if with_dedT.  Per species and term n of the series, with
    x = n m/T and C = (-stat)^(n+1) g m^2/(2 pi^2 n^2):
        P = C T^2 K2(x),  e = C T^2 (3 K2 + x K1),
        de/dT = C T (12 K2 + 5 x K1 + x^2 K0)."""
    m, g, stat = species
    T = np.atleast_1d(np.asarray(T, float))
    P = np.zeros(T.shape)
    e = np.zeros(T.shape)
    dedT = np.zeros(T.shape)
    for c in range(0, T.size, chunk):
        t = T[c:c + chunk, None]
        for n in range(1, NTERMS + 1):
            x = n*m[None, :]/t
            sign = (-stat)**(n + 1)
            pref = sign*g/(2*np.pi**2)*m**2/n**2
            ok = x < 300
            xs = np.minimum(x, 300)
            K0 = np.where(ok, k0(xs), 0.0)
            K1 = np.where(ok, k1(xs), 0.0)
            K2 = np.where(ok, K0 + 2*K1/xs, 0.0)
            P[c:c + chunk] += t[:, 0]**2*np.sum(pref*K2, axis=1)
            e[c:c + chunk] += t[:, 0]**2*np.sum(pref*(3*K2 + x*K1), axis=1)
            if with_dedT:
                dedT[c:c + chunk] += t[:, 0]*np.sum(
                    pref*(12*K2 + 5*x*K1 + x**2*K0), axis=1)
    conv = 1.0/HBARC**3
    if with_dedT:
        return P*conv, e*conv, dedT*conv
    return P*conv, e*conv


# ── table ───────────────────────────────────────────────────────────────────

def thin_by_ln_e(e, keep_last=True):
    """Indices of rows spaced by at least DLN_E in ln e (first row kept)."""
    keep = [0]
    last = np.log(e[0])
    for i in range(1, len(e)):
        if np.log(e[i]) - last >= DLN_E:
            keep.append(i)
            last = np.log(e[i])
    if keep_last and keep[-1] != len(e) - 1:
        keep.append(len(e) - 1)
    return np.array(keep)


def build_table(T_cs2, cs2, T_sw, species):
    """Rows (e, T, P, cs2, s) of the table; T_cs2, cs2: the input c_s^2(T)
    [GeV], which must cover T_sw .. its last point (the table's T_max)."""
    T_cs2 = np.asarray(T_cs2, float)
    cs2 = np.asarray(cs2, float)
    if np.any(np.diff(T_cs2) <= 0):
        raise ValueError("c_s^2 input: temperatures must increase")
    if T_cs2[0] > T_sw + 1e-12 or T_cs2[-1] <= T_sw:
        raise ValueError("c_s^2 input covers %.4f-%.4f GeV, not T_sw = %.4f"
                         % (T_cs2[0], T_cs2[-1], T_sw))
    if np.any(cs2 <= 0) or np.any(cs2 > 1):
        raise ValueError("c_s^2 input outside (0, 1]")
    if not T_LOW < T_sw:
        raise ValueError("T_sw = %g GeV is below the table's lowest T" % T_sw)

    # hadron gas, T_LOW .. T_sw: rows uniform in ln e (placed with a spline
    # of ln T(ln e) on a coarse grid, then evaluated exactly), T_sw the last
    T_c = T_LOW*np.exp(np.linspace(0.0, np.log(T_sw/T_LOW), 400))
    ln_e_c = np.log(hrg_thermo(T_c, species)[1])
    ln_T_of_ln_e = CubicSpline(ln_e_c, np.log(T_c))
    n_lo = int(np.ceil((ln_e_c[-1] - ln_e_c[0])/DLN_E))
    T_lo = np.exp(ln_T_of_ln_e(np.linspace(ln_e_c[0], ln_e_c[-1], n_lo + 1)))
    T_lo[0], T_lo[-1] = T_LOW, T_sw
    P_lo, e_lo, dedT_lo = hrg_thermo(T_lo, species, with_dedT=True)
    s_lo = (e_lo + P_lo)/T_lo
    c_lo = s_lo/dedT_lo  # dP/de = (dP/dT)/(de/dT)
    P_sw, e_sw, s_sw = P_lo[-1], e_lo[-1], s_lo[-1]

    # above T_sw: integrate c_s^2 on a fine uniform grid
    T_max = T_cs2[-1]
    n_up = int(np.ceil((T_max - T_sw)/T_STEP_UP))
    T_up = np.linspace(T_sw, T_max, n_up + 1)
    c_up = np.interp(T_up, T_cs2, cs2)
    f = 1.0/(T_up*c_up)
    ln_s = np.concatenate(([0.0], np.cumsum(0.5*(f[1:] + f[:-1])
                                             * np.diff(T_up))))
    s_up = s_sw*np.exp(ln_s)
    P_up = P_sw + np.concatenate(([0.0], np.cumsum(0.5*(s_up[1:] + s_up[:-1])
                                                   * np.diff(T_up))))
    e_up = T_up*s_up - P_up
    if np.any(np.diff(e_up) <= 0):
        raise ValueError("e(T) does not increase above T_sw")
    keep = thin_by_ln_e(e_up)[1:]  # T_sw itself is the last hadron-gas row
    T_up, P_up, e_up, s_up, c_up = (T_up[keep], P_up[keep], e_up[keep],
                                    s_up[keep], c_up[keep])

    rows = np.vstack([
        [[0.0, 0.0, 0.0, c_lo[0], 0.0]],
        np.column_stack((e_lo, T_lo, P_lo, c_lo, s_lo)),
        np.column_stack((e_up, T_up, P_up, c_up, s_up)),
    ])
    if np.any(np.diff(rows[:, 0]) <= 0):
        raise ValueError("table energy densities do not increase")
    return rows, {"e_sw": e_sw, "P_sw": P_sw, "s_sw": s_sw}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_table(out, rows, header):
    with open(out, "w") as f:
        f.write("%d %s\n" % (len(rows), json.dumps(header, sort_keys=True)))
        for r in rows:
            f.write("%.10e %.10e %.10e %.10e %.10e\n" % tuple(r))


def read_header(table):
    """(number of rows, header dict) of a table written by write_table."""
    with open(table) as f:
        first = f.readline().split(None, 1)
    n = int(first[0])
    header = json.loads(first[1]) if len(first) > 1 else {}
    return n, header


def make_table(T_cs2, cs2, T_sw, hadron_list, out, meta=None):
    """Build and write a table; returns its header."""
    species = read_species(hadron_list)
    rows, anchor = build_table(T_cs2, cs2, T_sw, species)
    cs2_digest = hashlib.sha256(
        np.ascontiguousarray(np.column_stack((T_cs2, cs2)),
                             dtype="<f8").tobytes()).hexdigest()
    header = {
        "format": FORMAT,
        "T_sw_GeV": float(T_sw),
        "hadron_list": os.path.basename(hadron_list),
        "hadron_list_sha256": sha256_of(hadron_list),
        "cs2_sha256": cs2_digest,
        "T_max_GeV": float(T_cs2[-1]),
        "e_sw_GeV_fm3": float(anchor["e_sw"]),
        "P_sw_GeV_fm3": float(anchor["P_sw"]),
        "s_sw_fm3": float(anchor["s_sw"]),
    }
    if meta:
        header["meta"] = meta
    write_table(out, rows, header)
    return header


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cs2", required=True,
                    help="two columns: T [GeV], c_s^2 (from T_sw up)")
    ap.add_argument("--T-sw", type=float, required=True, help="GeV")
    ap.add_argument("--hadron-list", required=True, help="iSS pdg-*.dat")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d = np.loadtxt(a.cs2, ndmin=2)
    header = make_table(d[:, 0], d[:, 1], a.T_sw, a.hadron_list, a.out)
    print(json.dumps(header, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
