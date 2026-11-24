#!/usr/bin/env python3
"""Standard per-event output of the chain (docs/standard_output.md, v1, 2D).

Reads the final particle list of one event -- the chain's own binary (decays
only), UrQMD output converted by the toolkit's convert_to_binary, or a SMASH
OSCAR2013 extended binary -- and sums, per species row and pT bin, the
particle count, exp(i n phi) for n <= 10, pT^1..4, mT and pT exp(i n phi) for
n <= 3.  Optionally (control_dict['hbt']) it also sums, per identical
species, K_T bin, Phi bin and q point, the HBT pair weights |S|^2 - N
(section 9 of the document).  The driver calls accumulate() once per delta f
variant and write_event_file() once per event; the merger
(scripts/merge_qn.py) concatenates the per-event files of a design point.

Command line, for tests:

    standard_output.py <decay|urqmd|smash> <particle file> <out.h5>
        [--event-id N] [--y-range YLB YRB] [--y-cut Y] [--iss-table FILE]
        [--hbt [JSON]]
"""

import argparse
import json
import os
import zlib
from decimal import Decimal

import numpy as np

FORMAT = "iebe-music-qn"
FORMAT_VERSION = 1
N_HARMONICS = 11  # n = 0..10, n = 0 is the count
N_QPT = 3  # pT exp(i n phi), n = 1..3
N_PTPOW = 4  # pT^k, k = 1..4
Y_PROFILE_STEP = 0.5
Y_PROFILE_MARGIN = 1.0
OTHER_CHARGED_MASS = 1.1894  # Sigma+; the row is Sigma dominated

# exact decimal edges: 0..3 by 0.05 plus 0.27, 3..5 by 0.25, then 5..10
_edges = [Decimal(i)/20 for i in range(61)] + [Decimal("0.27")]
_edges += [Decimal(3) + Decimal(i)/4 for i in range(1, 9)] + [Decimal(10)]
PT_EDGES = np.array(sorted(float(e) for e in set(_edges)))

SPECIES_PDG = np.array([211, -211, 321, -321, 2212, -2212, 3122, -3122,
                        3312, -3312, 3334, -3334, 311, -311, 0], dtype=np.int32)
# row 0 (other charged) holds both signs; its 1 only marks it as charged
SPECIES_CHARGE = np.array([1, -1, 1, -1, 1, -1, 0, 0, -1, 1, -1, 1, 0, 0, 1],
                          dtype=np.int32)
# highest harmonic stored per row: every charged row keeps n <= 10, because
# all charged hadrons are their sum; the neutral rows stop at 6.  Entries
# above a row's limit are not stored (written as 0, to be read as missing).
SPECIES_NMAX = np.array([10, 10, 10, 10, 10, 10, 6, 6, 10, 10, 10, 10, 6, 6,
                         10], dtype=np.int32)
N_SPECIES = len(SPECIES_PDG)
OTHER_ROW = N_SPECIES - 1

# record layouts
CHAIN_DT = np.dtype([("pdg", "<i4"), ("mass", "<f4"), ("t", "<f4"),
                     ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("E", "<f4"),
                     ("px", "<f4"), ("py", "<f4"), ("pz", "<f4")])
URQMD_DT = np.dtype([("ityp", "<i4"), ("iso3", "<i4"), ("charge", "<i4"),
                     ("ncoll", "<i4"), ("parent", "<i4"), ("ptype", "<i4"),
                     ("mass", "<f4"), ("t", "<f4"), ("x", "<f4"), ("y", "<f4"),
                     ("z", "<f4"), ("E", "<f4"), ("px", "<f4"), ("py", "<f4"),
                     ("pz", "<f4")])
SMASH_DT = np.dtype([("t", "<f8"), ("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
                     ("mass", "<f8"), ("E", "<f8"), ("px", "<f8"),
                     ("py", "<f8"), ("pz", "<f8"), ("pdg", "<i4"),
                     ("id", "<i4"), ("charge", "<i4"), ("ncoll", "<i4"),
                     ("form_time", "<f8"), ("xsecfac", "<f8"),
                     ("proc_id", "<i4"), ("proc_type", "<i4"),
                     ("t_last", "<f8"), ("mother1", "<i4"),
                     ("mother2", "<i4"), ("baryon", "<i4"),
                     ("strangeness", "<i4")])
# the common in-memory form; (t, x, y, z) is where the code last recorded the
# particle [fm]: the emission or decay point (decays only, UrQMD after a
# collision), or the end of the run (UrQMD without a collision, SMASH).  The
# HBT sums use coordinates that do not change under free streaming, so any
# point on the particle's straight line gives the same result.
PART_DT = np.dtype([("pdg", "<i4"), ("charge", "<i4"), ("mass", "<f8"),
                    ("E", "<f8"), ("px", "<f8"), ("py", "<f8"),
                    ("pz", "<f8"), ("t", "<f8"), ("x", "<f8"), ("y", "<f8"),
                    ("z", "<f8")])
KINE = ("E", "px", "py", "pz", "t", "x", "y", "z")

# UrQMD particle types -> PDG, keyed by (ityp, charge); only what the rows,
# the end-of-cascade decays and the bookkeeping need
URQMD_TO_PDG = {
    (101, 1): 211, (101, -1): -211, (101, 0): 111,
    (106, 1): 321, (106, 0): 311, (-106, -1): -321, (-106, 0): -311,
    (1, 1): 2212, (1, 0): 2112, (-1, -1): -2212, (-1, 0): -2112,
    (27, 0): 3122, (-27, 0): -3122,
    (40, 1): 3222, (40, 0): 3212, (40, -1): 3112,
    (-40, -1): -3222, (-40, 0): -3212, (-40, 1): -3112,
    (49, -1): 3312, (49, 0): 3322, (-49, 1): -3312, (-49, 0): -3322,
    (55, -1): 3334, (-55, 1): -3334,
    (102, 0): 221, (100, 0): 22,
}

# Decays the experiments count as primary but the cascades leave undone (both
# SMASH and UrQMD end with eta and Sigma0).  Channels and masses from iSS's
# pdg-urqmd_v3.3+.dat, the table the decays-only path uses.
END_DECAYS = {
    221: [(0.401, (22, 22)), (0.327, (111, 111, 111)),
          (0.230, (211, 111, -211)), (0.042, (211, -211, 22))],
    3212: [(1.0, (3122, 22))],
    -3212: [(1.0, (-3122, 22))],
}
DAUGHTER = {22: (0.0, 0), 111: (0.138, 0), 211: (0.138, 1), -211: (0.138, -1),
            3122: (1.116, 0), -3122: (1.116, 0)}
# widths [GeV] of the END_DECAYS mothers, for the decay vertices (c tau of
# 1.5e5 fm and 2.2e4 fm: their daughters are uncorrelated in HBT)
END_DECAY_WIDTH = {221: 1.31e-6, 3212: 8.9e-6, -3212: 8.9e-6}
HBARC = 0.19733  # GeV fm


# ----------------------------------------------------------------- readers
def _chain_events(name, charge_of):
    data = np.fromfile(name, dtype=np.uint8)
    off = 0
    while off < data.size:
        n = int(data[off:off + 4].view("<i4")[0])
        off += 4
        rec = data[off:off + n*CHAIN_DT.itemsize].view(CHAIN_DT)
        off += n*CHAIN_DT.itemsize
        out = np.empty(n, PART_DT)
        for k in ("pdg", "mass") + KINE:
            out[k] = rec[k]
        out["charge"] = charge_of(rec["pdg"])
        yield out


def _urqmd_events(name):
    data = np.fromfile(name, dtype=np.uint8)
    off = 0
    keys = np.array([k[0]*16 + k[1] for k in URQMD_TO_PDG])
    vals = np.array(list(URQMD_TO_PDG.values()))
    order = np.argsort(keys)
    keys, vals = keys[order], vals[order]
    while off < data.size:
        n = int(data[off:off + 4].view("<i4")[0])
        off += 4 + 8*4
        rec = data[off:off + n*URQMD_DT.itemsize].view(URQMD_DT)
        off += n*URQMD_DT.itemsize
        out = np.empty(n, PART_DT)
        for k in ("charge", "mass") + KINE:
            out[k] = rec[k]
        key = rec["ityp"].astype(np.int64)*16 + rec["charge"]
        i = np.clip(np.searchsorted(keys, key), 0, len(keys) - 1)
        out["pdg"] = np.where(keys[i] == key, vals[i], 0)
        yield out


def _smash_header(data, off, name):
    if bytes(data[off:off + 4]) != b"SMSH":
        raise ValueError("%s: no SMASH header at byte %d" % (name, off))
    version, variant = data[off + 4:off + 8].view("<u2")
    if (int(version), int(variant)) != (10, 1):
        raise ValueError("SMASH binary format %s.%s: expected 10.1 (extended)"
                         % (version, variant))
    return off + 12 + int(data[off + 8:off + 12].view("<u4")[0])


def _smash_events(name):
    """Events of one SMASH binary, or of several concatenated (the driver
    joins the outputs of all particlizations with cat)."""
    data = np.fromfile(name, dtype=np.uint8)
    off = _smash_header(data, 0, name)
    while off < data.size:
        if bytes(data[off:off + 4]) == b"SMSH":
            off = _smash_header(data, off, name)
            continue
        block = bytes(data[off:off + 1])
        off += 1
        if block == b"p":
            n = int(data[off + 8:off + 12].view("<u4")[0])
            off += 12
            rec = data[off:off + n*SMASH_DT.itemsize].view(SMASH_DT)
            off += n*SMASH_DT.itemsize
            out = np.empty(n, PART_DT)
            for k in ("pdg", "charge", "mass") + KINE:
                out[k] = rec[k]
            yield out
        elif block == b"f":
            off += 4 + 4 + 8 + 1
        elif block == b"i":  # interaction blocks are not expected here
            raise ValueError("SMASH binary with interaction blocks")
        else:
            raise ValueError("unknown SMASH block %r at byte %d" % (block, off))


def iss_charge_table(name):
    """pdg -> charge from an iSS particle table (column 11 of a species line)."""
    table = {}
    for line in open(name):
        c = line.split()
        if len(c) >= 12 and not c[1].lstrip("-").isdigit():
            pdg, charge = int(c[0]), int(c[10])
            table[pdg] = charge
            table.setdefault(-pdg, -charge)
    keys = np.array(sorted(table))
    vals = np.array([table[k] for k in keys])

    def charge_of(pdg):
        i = np.clip(np.searchsorted(keys, pdg), 0, len(keys) - 1)
        if np.any(keys[i] != pdg):
            raise ValueError("particle ids not in %s: %s" %
                             (name, np.unique(pdg[keys[i] != pdg])[:10]))
        return vals[i]
    return charge_of


def read_events(kind, name, iss_table=None):
    if kind == "decay":
        return _chain_events(name, iss_charge_table(iss_table))
    if kind == "urqmd":
        return _urqmd_events(name)
    if kind == "smash":
        return _smash_events(name)
    raise ValueError("unknown particle-list kind %r" % kind)


# --------------------------------------------------------- end-of-cascade decays
def _two_body_p(M, m1, m2):
    return np.sqrt(np.maximum(
        (M*M - (m1 + m2)**2)*(M*M - (m1 - m2)**2), 0.0))/(2.0*M)


def _isotropic(rng, n):
    c = rng.uniform(-1.0, 1.0, n)
    s = np.sqrt(1.0 - c*c)
    phi = rng.uniform(0.0, 2.0*np.pi, n)
    return np.stack([s*np.cos(phi), s*np.sin(phi), c], axis=1)


def _boost(p4, parent):
    """Boost 4-vectors p4 [n, 4] (E, p) from the rest frame of parent [n, 4]."""
    M = np.sqrt(np.maximum(parent[:, 0]**2 - np.sum(parent[:, 1:]**2, 1), 1e-30))
    beta = parent[:, 1:]/parent[:, :1]
    gamma = parent[:, 0]/M
    bp = np.sum(beta*p4[:, 1:], 1)
    b2 = np.sum(beta*beta, 1)
    fac = np.where(b2 > 0, (gamma - 1.0)*bp/np.where(b2 > 0, b2, 1.0), 0.0)
    out = np.empty_like(p4)
    out[:, 0] = gamma*(p4[:, 0] + bp)
    out[:, 1:] = p4[:, 1:] + (fac + gamma*p4[:, 0])[:, None]*beta
    return out


def _decay(rng, parent, masses):
    """Phase-space decay of parents [n, 4] into len(masses) bodies; returns a
    list of daughter 4-vectors [n, 4] in the lab."""
    n = len(parent)
    M = np.sqrt(np.maximum(parent[:, 0]**2 - np.sum(parent[:, 1:]**2, 1), 0.0))
    if len(masses) == 2:
        m1, m2 = masses
        p = _two_body_p(M, m1, m2)
        d = _isotropic(rng, n)*p[:, None]
        a = np.column_stack([np.sqrt(m1*m1 + p*p), d])
        b = np.column_stack([np.sqrt(m2*m2 + p*p), -d])
        return [_boost(a, parent), _boost(b, parent)]
    m1, m2, m3 = masses
    # m12 with density p(M -> m12 m3) q(m12 -> m1 m2), by acceptance
    m12 = np.empty(n)
    todo = np.arange(n)
    lo, hi = m1 + m2, M - m3
    wmax = _two_body_p(M, lo, m3)*_two_body_p(hi, m1, m2)*1.0001 + 1e-12
    wmax = np.maximum(wmax, _two_body_p(M, 0.5*(lo + hi), m3)
                      *_two_body_p(0.5*(lo + hi), m1, m2)*1.5)
    while todo.size:
        x = lo[todo] + rng.uniform(0, 1, todo.size)*(hi[todo] - lo[todo]) \
            if np.ndim(lo) else lo + rng.uniform(0, 1, todo.size)*(hi[todo] - lo)
        w = _two_body_p(M[todo], x, m3)*_two_body_p(x, m1, m2)
        ok = rng.uniform(0, 1, todo.size)*wmax[todo] < w
        m12[todo[ok]] = x[ok]
        todo = todo[~ok]
    p = _two_body_p(M, m12, m3)
    d = _isotropic(rng, n)*p[:, None]
    pair = _boost(np.column_stack([np.sqrt(m12**2 + p*p), d]), parent)
    third = _boost(np.column_stack([np.sqrt(m3*m3 + p*p), -d]), parent)
    q = _two_body_p(m12, m1, m2)
    e = _isotropic(rng, n)*q[:, None]
    a = _boost(np.column_stack([np.sqrt(m1*m1 + q*q), e]), pair)
    b = _boost(np.column_stack([np.sqrt(m2*m2 + q*q), -e]), pair)
    return [a, b, third]


def end_decays(parts, rng, rng_vertex=None):
    """Decay eta and Sigma0 (END_DECAYS) in a particle array; returns the new
    array and the number of decays done.

    The daughters start at the decay vertex: the mother's recorded point plus
    its velocity times a lab lifetime drawn from rng_vertex (at the mother's
    point when rng_vertex is None).  The vertices draw from their own
    generator, so the momenta are the same with or without them."""
    todo = np.isin(parts["pdg"], list(END_DECAYS))
    if not todo.any():
        return parts, 0
    keep = [parts[~todo]]
    mothers = parts[todo]
    for pdg, channels in END_DECAYS.items():
        sel = mothers[mothers["pdg"] == pdg]
        if not len(sel):
            continue
        p4 = np.column_stack([sel["E"], sel["px"], sel["py"], sel["pz"]])
        # decay vertex: proper lifetime tau0 [fm], lab displacement p/M tau0
        tau0 = (rng_vertex.exponential(HBARC/END_DECAY_WIDTH[pdg], len(sel))
                if rng_vertex is not None else np.zeros(len(sel)))
        mass = np.maximum(sel["mass"], 1e-6)
        vtx = np.column_stack([sel["t"] + sel["E"]/mass*tau0,
                               sel["x"] + sel["px"]/mass*tau0,
                               sel["y"] + sel["py"]/mass*tau0,
                               sel["z"] + sel["pz"]/mass*tau0])
        u = rng.uniform(0, 1, len(sel))
        cum = np.cumsum([c[0] for c in channels])
        cum /= cum[-1]
        ich = np.searchsorted(cum, u, side="right")
        for k, (_, daughters) in enumerate(channels):
            m = ich == k
            if not m.any():
                continue
            out = _decay(rng, p4[m], [DAUGHTER[d][0] for d in daughters])
            for d, v in zip(daughters, out):
                arr = np.empty(len(v), PART_DT)
                arr["pdg"], arr["charge"] = d, DAUGHTER[d][1]
                arr["mass"] = DAUGHTER[d][0]
                arr["E"], arr["px"], arr["py"], arr["pz"] = v.T
                arr["t"], arr["x"], arr["y"], arr["z"] = vtx[m].T
                keep.append(arr)
    return np.concatenate(keep), int(todo.sum())


# ------------------------------------------------------------------ sums
def _rows(parts):
    """Species row of every particle, -1 when it is in no row."""
    pdg = parts["pdg"]
    order = np.argsort(SPECIES_PDG[:OTHER_ROW])
    keys = SPECIES_PDG[:OTHER_ROW][order]
    i = np.clip(np.searchsorted(keys, pdg), 0, len(keys) - 1)
    row = np.where(keys[i] == pdg, order[i], -1)
    row = np.where((row < 0) & (parts["charge"] != 0), OTHER_ROW, row)
    return row


# ------------------------------------------------------------- HBT sums
# Optional (docs/standard_output.md, section 9).  For every particle of a
# species, the emission coordinates in its own LCMS (pT along "out", pz = 0):
#     a = x_out - beta_T t,  b = x_side,  c = z    (beta_T = pT/mT)
# which do not change under free streaming; per event, per (species, K_T bin,
# lab Phi bin) and per q point S(q) = sum_i exp[i (q_o a + q_s b + q_l c)/hbarc]
# over all oversamples, and the file holds |S|^2 - N = sum over pairs i != j
# of cos(q.dx~), summed over the species of a row.  C(q) - 1 of a set of
# events is sum(hbt_num)/sum(hbt_pairs), summed over Phi bins as real values
# (never by adding S of different Phi bins: out and side are per particle).

# half of the 26-point Lebedev rule (C(-q) = C(q)): 3 axes, 6 face diagonals,
# 4 body diagonals, with the full-sphere weight of each point
LEBEDEV26_HALF = (
    [((1, 0, 0), 1/21), ((0, 1, 0), 1/21), ((0, 0, 1), 1/21)]
    + [(d, 4/105) for d in ((1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1),
                            (0, 1, 1), (0, 1, -1))]
    + [(d, 27/840) for d in ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1))])
HBT_DEFAULTS = {
    # delta f variants that get HBT sums: "all" or a list of names
    # (control_dict['deltaf_models'] keys; "default" without them)
    "variants": "all",
    # one output row per group: like-sign pairs of each species, summed over
    # the group (pi+pi+ and pi-pi- together by default)
    "rows": [[211, -211]],
    # single-particle pT = K_T under the smoothness approximation [GeV]
    "kt_edges": [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60,
                 0.70, 0.75, 0.80, 1.00, 1.50, 2.00],
    "n_phi": 12,
    # |q| [GeV] along each of the 13 directions
    "q_mags": [0.005, 0.015, 0.025, 0.035, 0.045, 0.055, 0.065, 0.075, 0.085,
               0.095, 0.12, 0.14, 0.16, 0.18, 0.20, 0.23, 0.26, 0.30, 0.40,
               0.50],
    # |y| < y_cut; None: the sampled range minus edge_margin (decays only),
    # the standard output's own y_cut (UrQMD, SMASH)
    "y_cut": None,
    "edge_margin": 1.0,
}
HBT_CHUNK = 8000  # particles per block of exponentials (~100 MB peak)


def hbt_settings(user):
    """Resolved HBT settings (defaults filled in, grids built) from the
    control_dict['hbt'] entry; None when HBT is off."""
    if not user:
        return None
    s = dict(HBT_DEFAULTS)
    if isinstance(user, dict):
        unknown = set(user) - set(HBT_DEFAULTS) - {"enabled"}
        if unknown:
            raise ValueError("hbt: unknown keys %s" % sorted(unknown))
        if not user.get("enabled", True):
            return None
        s.update({k: v for k, v in user.items() if k != "enabled"})
    rows = [list(map(int, r)) for r in s["rows"]]
    species = []
    for r in rows:
        for p in r:
            if p in species:
                raise ValueError("hbt: species %d in more than one row" % p)
            species.append(p)
    kt = np.array(s["kt_edges"], float)
    if np.any(np.diff(kt) <= 0):
        raise ValueError("hbt: kt_edges must increase")
    mags = np.array(s["q_mags"], float)
    if np.any(np.diff(mags) <= 0) or mags[0] <= 0:
        raise ValueError("hbt: q_mags must be positive and increase")
    dirs = np.array([d for d, _ in LEBEDEV26_HALF], float)
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    wdir = np.array([w for _, w in LEBEDEV26_HALF])
    # shells around each |q|: midpoints, from 0 to half a step past the last
    shell = np.concatenate(([0.0], 0.5*(mags[1:] + mags[:-1]),
                            [mags[-1] + 0.5*(mags[-1] - mags[-2])]))
    vshell = 4.0*np.pi/3.0*(shell[1:]**3 - shell[:-1]**3)
    q = (dirs[:, None, :]*mags[None, :, None]).reshape(-1, 3)
    # d^3q of each point in the half space q.(1,1,1)-side: sum = half ball
    qw = (wdir[:, None]*vshell[None, :]).reshape(-1)
    n_phi = int(s["n_phi"])
    member = np.array([[1 if p in r else 0 for p in species] for r in rows],
                      np.int8)
    return {"variants": s["variants"], "rows": rows, "species": species,
            "member": member, "kt_edges": kt, "n_phi": n_phi,
            "phi_edges": np.linspace(-np.pi, np.pi, n_phi + 1),
            "q_dirs": dirs, "q_mags": mags, "q": q, "q_weight": qw,
            "q_shell_edges": shell, "y_cut": s["y_cut"],
            "edge_margin": float(s["edge_margin"])}


def hbt_wanted(settings, variant):
    if settings is None:
        return False
    v = settings["variants"]
    return v == "all" or variant in (v if isinstance(v, (list, tuple)) else [v])


def hbt_y_cut(settings, kind, y_range, y_cut):
    """|y| window of the HBT sums for one particlization."""
    if settings["y_cut"] is not None:
        return float(settings["y_cut"])
    if kind != "decay" and y_cut is not None:
        return float(y_cut)
    return min(-y_range[0], y_range[1]) - settings["edge_margin"]


class HBTSums:
    """S and N of one event and variant, accumulated over its oversamples."""

    def __init__(self, settings, y_cut):
        self.s = settings
        self.y_cut = y_cut
        self.ns = len(settings["species"])
        self.nk = len(settings["kt_edges"]) - 1
        self.nphi = settings["n_phi"]
        self.ncell = self.ns*self.nk*self.nphi
        self.S = np.zeros((self.ncell, len(settings["q"])), np.complex128)
        self.N = np.zeros(self.ncell)
        self.buf = []
        self.nbuf = 0
        self.qq = settings["q"]/HBARC

    def add(self, parts):
        """Particles of one oversample (PART_DT)."""
        isp = np.full(len(parts), -1)
        for k, p in enumerate(self.s["species"]):
            isp[parts["pdg"] == p] = k
        sel = isp >= 0
        if not sel.any():
            return
        p = parts[sel]
        isp = isp[sel]
        pt = np.hypot(p["px"], p["py"])
        mt = np.sqrt(np.maximum(p["E"]**2 - p["pz"]**2, 1e-30))
        with np.errstate(divide="ignore", invalid="ignore"):
            rap = 0.5*np.log((p["E"] + p["pz"])/(p["E"] - p["pz"]))
        phi = np.arctan2(p["py"], p["px"])
        ik = np.searchsorted(self.s["kt_edges"], pt, side="right") - 1
        iphi = np.clip(np.floor((phi + np.pi)/(2*np.pi)*self.nphi).astype(int),
                       0, self.nphi - 1)
        ok = (ik >= 0) & (ik < self.nk) & np.isfinite(rap) \
            & (np.abs(rap) < self.y_cut)
        if not ok.any():
            return
        p, isp, ik, iphi, pt, mt = p[ok], isp[ok], ik[ok], iphi[ok], pt[ok], mt[ok]
        # LCMS of the particle: boost along z to pz = 0, rotate pT onto out
        bl = p["pz"]/p["E"]
        gl = p["E"]/mt
        tt = gl*(p["t"] - bl*p["z"])
        zz = gl*(p["z"] - bl*p["t"])
        c, s_ = p["px"]/np.where(pt > 0, pt, 1.0), p["py"]/np.where(pt > 0, pt, 1.0)
        a = p["x"]*c + p["y"]*s_ - pt/mt*tt
        b = -p["x"]*s_ + p["y"]*c
        cell = (isp*self.nk + ik)*self.nphi + iphi
        self.buf.append((cell, a, b, zz))
        self.nbuf += len(cell)
        if self.nbuf >= HBT_CHUNK:
            self._flush()

    def _flush(self):
        if not self.buf:
            return
        cell = np.concatenate([x[0] for x in self.buf])
        coords = [np.concatenate([x[i] for x in self.buf]) for i in (1, 2, 3)]
        self.buf, self.nbuf = [], 0
        order = np.argsort(cell, kind="stable")
        cell = cell[order]
        a, b, c = (x[order] for x in coords)
        self.N += np.bincount(cell, minlength=self.ncell)
        for i0 in range(0, len(cell), HBT_CHUNK):
            sl = slice(i0, i0 + HBT_CHUNK)
            ph = (np.outer(a[sl], self.qq[:, 0]) + np.outer(b[sl], self.qq[:, 1])
                  + np.outer(c[sl], self.qq[:, 2]))
            e = np.exp(1j*ph)
            cs = cell[sl]
            starts = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1]])
            self.S[cs[starts]] += np.add.reduceat(e, starts, axis=0)

    def result(self):
        """{'num' [nrow, nk, nphi, nq], 'pairs' [nrow, nk, nphi],
        'N' [ns, nk, nphi], 'y_cut', 'settings'}"""
        self._flush()
        shape = (self.ns, self.nk, self.nphi)
        S = self.S.reshape(shape + (-1,))
        N = self.N.reshape(shape)
        num_s = np.abs(S)**2 - N[..., None]
        pairs_s = N*(N - 1.0)
        member = self.s["member"]
        num = np.einsum("rs,s...->r...", member.astype(float), num_s)
        pairs = np.einsum("rs,s...->r...", member.astype(float), pairs_s)
        return {"num": num, "pairs": pairs, "N": N, "y_cut": self.y_cut,
                "settings": self.s}


def hbt_empty(settings, y_cut):
    """HBT sums of an event without particles."""
    return HBTSums(settings, y_cut).result()


def accumulate(kind, name, y_range, y_cut=None, iss_table=None, seed=None,
               hbt=None):
    """Sums of one particle list (one event, one variant).

    y_range = (y_LB, y_RB) iSS sampled over; y_cut None sums every particle
    (decays only), else only |y| < y_cut.  seed feeds the end-of-cascade
    decays (UrQMD, SMASH).  hbt: resolved settings (hbt_settings()) to add
    the HBT sums, else None.
    """
    npt = len(PT_EDGES) - 1
    ncell = N_SPECIES*npt
    Q = np.zeros((N_HARMONICS, ncell), np.complex128)
    Qpt = np.zeros((N_QPT, ncell), np.complex128)
    ptsum = np.zeros((N_PTPOW, ncell))
    mtsum = np.zeros(ncell)
    yedges = np.arange(y_range[0] - Y_PROFILE_MARGIN,
                       y_range[1] + Y_PROFILE_MARGIN + 1e-9, Y_PROFILE_STEP)
    nyb = len(yedges) - 1
    yprof = np.zeros((4, nyb))
    rng = np.random.default_rng(seed) if kind != "decay" else None
    # decay vertices draw from their own stream (the momenta stay as before)
    rng_vertex = None
    if rng is not None:
        rng_vertex = np.random.default_rng(
            None if seed is None else list(np.atleast_1d(seed)) + [0x7E47])
    hbt_acc = None
    if hbt is not None:
        hbt_acc = HBTSums(hbt, hbt_y_cut(hbt, kind, y_range, y_cut))
    nsamples = 0
    ndecays = 0
    unknown_neutral = 0
    for parts in read_events(kind, name, iss_table):
        nsamples += 1
        if rng is not None:
            parts, nd = end_decays(parts, rng, rng_vertex)
            ndecays += nd
        if not len(parts):
            continue
        if hbt_acc is not None:
            hbt_acc.add(parts)
        E, pz = parts["E"], parts["pz"]
        px, py = parts["px"], parts["py"]
        pt = np.hypot(px, py)
        with np.errstate(divide="ignore", invalid="ignore"):
            y = 0.5*np.log((E + pz)/(E - pz))
        row = _rows(parts)
        unknown_neutral += int(np.sum((parts["pdg"] == 0) & (parts["charge"] == 0)))
        # rapidity profile of charged particles, before the collection cut
        ch = (parts["charge"] != 0) & np.isfinite(y)
        iy = np.floor((y[ch] - yedges[0])/Y_PROFILE_STEP).astype(int)
        ok = (iy >= 0) & (iy < nyb)
        iy = iy[ok]
        z2 = ((px[ch] + 1j*py[ch])/np.where(pt[ch] > 0, pt[ch], 1.0))[ok]**2
        yprof[0] += np.bincount(iy, minlength=nyb)
        yprof[1] += np.bincount(iy, weights=pt[ch][ok], minlength=nyb)
        yprof[2] += np.bincount(iy, weights=z2.real, minlength=nyb)
        yprof[3] += np.bincount(iy, weights=z2.imag, minlength=nyb)
        # the sums
        ib = np.searchsorted(PT_EDGES, pt, side="right") - 1
        sel = (row >= 0) & (ib >= 0) & (ib < npt) & np.isfinite(y)
        if y_cut is not None:
            sel &= np.abs(y) < y_cut
        cell = row[sel]*npt + ib[sel]
        p = pt[sel]
        z = (px[sel] + 1j*py[sel])/np.where(p > 0, p, 1.0)
        m = parts["mass"][sel]
        zn = np.ones_like(z)
        for n in range(N_HARMONICS):
            if n:
                zn = zn*z
            Q[n] += np.bincount(cell, weights=zn.real, minlength=ncell) \
                + 1j*np.bincount(cell, weights=zn.imag, minlength=ncell)
            if 1 <= n <= N_QPT:
                Qpt[n - 1] += np.bincount(cell, weights=p*zn.real, minlength=ncell) \
                    + 1j*np.bincount(cell, weights=p*zn.imag, minlength=ncell)
        pk = np.ones_like(p)
        for k in range(N_PTPOW):
            pk = pk*p
            ptsum[k] += np.bincount(cell, weights=pk, minlength=ncell)
        mtsum += np.bincount(cell, weights=np.sqrt(p*p + m*m), minlength=ncell)

    def shape(a, lead):
        return a.reshape(lead + (N_SPECIES, npt))
    Qs = np.moveaxis(shape(Q, (N_HARMONICS,)), 0, 1)
    for r, nmax in enumerate(SPECIES_NMAX):
        Qs[r, nmax + 1:] = 0.0
    out = {
        "nsamples": nsamples,
        "Q": Qs,
        "Qpt": np.moveaxis(shape(Qpt, (N_QPT,)), 0, 1),
        "ptsum": np.moveaxis(shape(ptsum, (N_PTPOW,)), 0, 1),
        "mtsum": shape(mtsum, ()),
        "y_profile": yprof.T,
        "y_profile_edges": yedges,
        "end_decays": ndecays,
        "unknown_neutral": unknown_neutral,
    }
    if hbt_acc is not None:
        out["hbt"] = hbt_acc.result()
    return out


def species_mass(iss_table=None):
    """Masses of the named rows from an iSS table (else PDG values)."""
    pdg_mass = {211: 0.13957, 321: 0.493677, 2212: 0.938272, 3122: 1.115683,
                3312: 1.32171, 3334: 1.67245, 311: 0.497611}
    if iss_table:
        for line in open(iss_table):
            c = line.split()
            if len(c) >= 12 and not c[1].lstrip("-").isdigit():
                if int(c[0]) in pdg_mass:
                    pdg_mass[int(c[0])] = float(c[2])
    out = [pdg_mass[abs(int(p))] if p else OTHER_CHARGED_MASS
           for p in SPECIES_PDG]
    return np.array(out)


# ------------------------------------------------------------ driver helpers
def parse_iss_args(iss_args):
    """{key: value} from an iSS override string "k1=v1 k2=v2"."""
    out = {}
    for item in (iss_args or "").split():
        if "=" in item:
            k, v = item.split("=", 1)
            out[k] = v
    return out


def read_iss_parameters(fname, iss_args=""):
    """The iSS parameters of one particlization: the file plus overrides."""
    par = {}
    for line in open(fname):
        line = line.split("#")[0]
        if "=" in line:
            k, v = line.split("=", 1)
            par[k.strip()] = v.strip()
    par.update(parse_iss_args(iss_args))
    return par


def read_hydro_tables(folder):
    """MUSIC's per-time tables of a boost-invariant event: {name: [1, T, ncol]},
    'tau': [1, T], and the column headers.  Missing folder: empty dict."""
    import glob
    import re
    out, headers = {}, {}
    names = (("ecc_ed", "eccentricities_evo_ed_tau_"),
             ("ecc_nB", "eccentricities_evo_nB_tau_"),
             ("ecc_nQ", "eccentricities_evo_nQ_tau_"),
             ("momentum_anisotropy", "momentum_anisotropy_tau_"),
             ("meanpT_estimators", "meanpT_estimators_tau_"))
    taus = set()
    files = {}
    for key, prefix in names:
        for f in glob.glob(os.path.join(folder, prefix + "*.dat")):
            m = re.match(re.escape(prefix) + r"([0-9.eE+-]+)\.dat$",
                         os.path.basename(f))
            if m:
                files[(key, float(m.group(1)))] = f
                taus.add(float(m.group(1)))
    if not files:
        return {}, {}
    taus = sorted(taus)
    out["tau"] = np.array([taus])
    for key, _ in names:
        rows = []
        for t in taus:
            f = files.get((key, t))
            if f is None:
                rows.append(None)
                continue
            with open(f) as fh:
                first = fh.readline()
            if first.startswith("#"):
                headers[key] = first.lstrip("#").strip()
            if key.startswith("ecc_"):
                # MUSIC's header says n=1-6, but it writes n = 1..5
                headers[key] = ("eta_s, integral of the density, then "
                                "(cos, sin) of ecc_n for n = 1..5")
            data = np.loadtxt(f, ndmin=2)
            rows.append(data[0])
        ncol = max((len(r) for r in rows if r is not None), default=0)
        if not ncol:
            continue
        arr = np.full((1, len(taus), ncol), np.nan)
        for i, r in enumerate(rows):
            if r is not None:
                arr[0, i, :len(r)] = r
        out[key] = arr
    return out, headers


# ------------------------------------------------------------------ files
def _ds(group, name, data, dtype=None):
    data = np.asarray(data, dtype=dtype)
    if data.ndim and data.shape[0]:
        chunks = (min(128, data.shape[0]),) + data.shape[1:]
        group.create_dataset(name, data=data, chunks=chunks,
                             compression="gzip", compression_opts=1,
                             shuffle=True, maxshape=(None,) + data.shape[1:])
    else:
        group.create_dataset(name, data=data)


def write_event_file(path, root_attrs, events, variants, hydro=None,
                     drawn=None, masses=None):
    """One event in the layout of docs/standard_output.md (event axis 1).

    root_attrs: dict; events: dict of 1-D arrays (length 1); variants: list
    of (name, attrs, sums); hydro: dict name -> array [1, T, k] or None;
    drawn: dict of 1-D arrays or None.
    """
    import h5py
    tmp = path + ".tmp"
    with h5py.File(tmp, "w") as f:
        f.attrs["format"] = FORMAT
        f.attrs["format_version"] = FORMAT_VERSION
        f.attrs["mode"] = "2D"
        f.attrs["variants"] = ",".join(v[0] for v in variants)
        for k, v in root_attrs.items():
            f.attrs[k] = v
        g = f.create_group("grid")
        g.create_dataset("pt_edges", data=PT_EDGES)
        g.create_dataset("species_pdg", data=SPECIES_PDG)
        g.create_dataset("species_mass",
                         data=masses if masses is not None else species_mass())
        g.create_dataset("species_charge", data=SPECIES_CHARGE)
        g.create_dataset("harmonics", data=np.arange(N_HARMONICS, dtype=np.int32))
        g.create_dataset("species_nmax", data=SPECIES_NMAX)
        g["species_nmax"].attrs["meaning"] = (
            "highest harmonic stored in Q for the row; entries above it are "
            "not stored (zeros in the file), not Q_n = 0")
        g.attrs["other_charged"] = ("species_pdg 0: every charged final "
                                    "particle not in another row, both signs")
        if variants:
            g.create_dataset("y_profile_edges",
                             data=variants[0][2]["y_profile_edges"])
        hbt = [v[2]["hbt"]["settings"] for v in variants if "hbt" in v[2]]
        if hbt:
            _write_hbt_grid(g, hbt)
        e = f.create_group("events")
        for k, v in events.items():
            _ds(e, k, v)
        if hydro:
            h = f.create_group("hydro")
            for k, v in hydro.items():
                if k == "headers":
                    for name, text in v.items():
                        h.attrs["columns_" + name] = text
                    continue
                _ds(h, k, v, np.float32)
        if drawn:
            d = f.create_group("drawn")
            for k, v in drawn.items():
                _ds(d, k, v)
        for name, attrs, s in variants:
            v = f.create_group("deltaf_" + name)
            v.attrs["sums"] = "raw over nsamples"
            for k, val in attrs.items():
                v.attrs[k] = val
            v.attrs["end_decays"] = s["end_decays"]
            _ds(v, "nsamples", np.array([s["nsamples"]], np.int32))
            _ds(v, "Q", s["Q"][None], np.complex64)
            _ds(v, "ptsum", s["ptsum"][None], np.float32)
            _ds(v, "mtsum", s["mtsum"][None], np.float32)
            _ds(v, "Qpt", s["Qpt"][None], np.complex64)
            _ds(v, "y_profile", s["y_profile"][None], np.float32)
            if "hbt" in s:
                h = s["hbt"]
                v.attrs["hbt_y_cut"] = h["y_cut"]
                _ds(v, "hbt_num", h["num"][None], np.float32)
                _ds(v, "hbt_pairs", h["pairs"][None], np.float64)
                _ds(v, "hbt_N", h["N"][None], np.float32)
    os.replace(tmp, path)


def _write_hbt_grid(g, settings_list):
    s = settings_list[0]
    for other in settings_list[1:]:
        for k in ("species", "rows", "n_phi"):
            if other[k] != s[k]:
                raise ValueError("HBT settings differ between variants")
        for k in ("kt_edges", "q"):
            if not np.array_equal(other[k], s[k]):
                raise ValueError("HBT settings differ between variants")
    g.create_dataset("hbt_species", data=np.array(s["species"], np.int32))
    g.create_dataset("hbt_rows", data=s["member"])
    g["hbt_rows"].attrs["meaning"] = (
        "hbt_rows[r, s] = 1 if species hbt_species[s] is in output row r: "
        "row r sums the like-sign pairs of each of its species")
    g.create_dataset("hbt_kt_edges", data=s["kt_edges"])
    g["hbt_kt_edges"].attrs["meaning"] = (
        "single-particle pT [GeV] (= K_T in the smoothness approximation)")
    g.create_dataset("hbt_phi_edges", data=s["phi_edges"])
    g["hbt_phi_edges"].attrs["meaning"] = "lab azimuth of pT [rad]"
    g.create_dataset("hbt_q", data=s["q"])
    g["hbt_q"].attrs["frame"] = ("LCMS of each particle: (q_out, q_side, "
                                 "q_long), out along its pT")
    g["hbt_q"].attrs["unit"] = "GeV"
    g["hbt_q"].attrs["order"] = ("hbt_q[i*n_mag + k] = hbt_q_magnitudes[k] "
                                 "* hbt_q_directions[i]")
    g.create_dataset("hbt_q_directions", data=s["q_dirs"])
    g.create_dataset("hbt_q_magnitudes", data=s["q_mags"])
    g.create_dataset("hbt_q_shell_edges", data=s["q_shell_edges"])
    g.create_dataset("hbt_q_weight", data=s["q_weight"])
    g["hbt_q_weight"].attrs["meaning"] = (
        "d^3q [GeV^3] of each point (26-point Lebedev weight x shell "
        "volume): sum_i w_i f(q_i) approximates the integral of an even f "
        "over half of q-space, |q| < hbt_q_shell_edges[-1]")
    g.attrs["hbt_coordinates"] = (
        "a = x_out - beta_T t, b = x_side, c = z in each particle's LCMS; "
        "hbt_num = |S|^2 - N with S = sum exp(i q.(a, b, c)/hbarc) over all "
        "oversamples, per (row species, K_T bin, Phi bin); sum Phi bins as "
        "real values, never by adding S across Phi bins")


def empty_sums(y_range, hbt=None, kind="decay", y_cut=None):
    """Sums of an event without particles (no_surface)."""
    npt = len(PT_EDGES) - 1
    yedges = np.arange(y_range[0] - Y_PROFILE_MARGIN,
                       y_range[1] + Y_PROFILE_MARGIN + 1e-9, Y_PROFILE_STEP)
    extra = {}
    if hbt is not None:
        extra["hbt"] = hbt_empty(hbt, hbt_y_cut(hbt, kind, y_range, y_cut))
    return {**extra, "nsamples": 0,
            "Q": np.zeros((N_SPECIES, N_HARMONICS, npt), np.complex128),
            "Qpt": np.zeros((N_SPECIES, N_QPT, npt), np.complex128),
            "ptsum": np.zeros((N_SPECIES, N_PTPOW, npt)),
            "mtsum": np.zeros((N_SPECIES, npt)),
            "y_profile": np.zeros((len(yedges) - 1, 4)),
            "y_profile_edges": yedges, "end_decays": 0,
            "unknown_neutral": 0}


def decay_seed(event_id, variant):
    """Seed of the end-of-cascade decays: event id and variant only."""
    return [0x51E4D, int(event_id), zlib.crc32(variant.encode())]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind", choices=("decay", "urqmd", "smash"))
    ap.add_argument("particles")
    ap.add_argument("out")
    ap.add_argument("--event-id", type=int, default=0)
    ap.add_argument("--variant", default="default")
    ap.add_argument("--y-range", type=float, nargs=2, default=(-5.0, 5.0))
    ap.add_argument("--y-cut", type=float, default=None)
    ap.add_argument("--iss-table", default=None,
                    help="iSS particle table (decays only: gives the charges)")
    ap.add_argument("--hbt", nargs="?", const="{}", default=None,
                    metavar="JSON",
                    help="add the HBT sums; optional JSON overrides of the "
                         "defaults (HBT_DEFAULTS), e.g. '{\"n_phi\": 24}'")
    args = ap.parse_args()
    collection = "all" if args.y_cut is None else "window"
    hbt = hbt_settings(json.loads(args.hbt) or True) if args.hbt else None
    s = accumulate(args.kind, args.particles, args.y_range, args.y_cut,
                   args.iss_table, decay_seed(args.event_id, args.variant),
                   hbt=hbt)
    attrs = {"y_sampled": list(args.y_range), "collection": collection,
             "y_cut": np.nan if args.y_cut is None else args.y_cut,
             "dy_width": (args.y_range[1] - args.y_range[0]
                          if args.y_cut is None else 2*args.y_cut)}
    write_event_file(args.out, {"afterburner": args.kind},
                     {"event_id": np.array([args.event_id], np.int64),
                      "status": np.array([0], np.uint8),
                      "weight": np.array([1.0])},
                     [(args.variant, attrs, s)],
                     masses=species_mass(args.iss_table))
    print(json.dumps({"nsamples": s["nsamples"], "end_decays": s["end_decays"],
                      "particles": float(s["Q"][:, 0].real.sum()),
                      "unknown_neutral": s["unknown_neutral"]}))


if __name__ == "__main__":
    main()
