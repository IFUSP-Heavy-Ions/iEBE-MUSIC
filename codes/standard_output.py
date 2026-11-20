#!/usr/bin/env python3
"""Standard per-event output of the chain (docs/standard_output.md, v1, 2D).

Reads the final particle list of one event -- the chain's own binary (decays
only), UrQMD output converted by the toolkit's convert_to_binary, or a SMASH
OSCAR2013 extended binary -- and sums, per species row and pT bin, the
particle count, exp(i n phi) for n <= 10, pT^1..4, mT and pT exp(i n phi) for
n <= 3.  The driver calls accumulate() once per delta f variant and
write_event_file() once per event; the merger (scripts/merge_qn.py)
concatenates the per-event files of a design point.

Command line, for tests:

    standard_output.py <decay|urqmd|smash> <particle file> <out.h5>
        [--event-id N] [--y-range YLB YRB] [--y-cut Y] [--iss-table FILE]
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
# the common in-memory form
PART_DT = np.dtype([("pdg", "<i4"), ("charge", "<i4"), ("mass", "<f8"),
                    ("E", "<f8"), ("px", "<f8"), ("py", "<f8"),
                    ("pz", "<f8")])

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
        for k in ("pdg", "mass", "E", "px", "py", "pz"):
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
        for k in ("charge", "mass", "E", "px", "py", "pz"):
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
            for k in ("pdg", "charge", "mass", "E", "px", "py", "pz"):
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


def end_decays(parts, rng):
    """Decay eta and Sigma0 (END_DECAYS) in a particle array; returns the new
    array and the number of decays done."""
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


def accumulate(kind, name, y_range, y_cut=None, iss_table=None, seed=None):
    """Sums of one particle list (one event, one variant).

    y_range = (y_LB, y_RB) iSS sampled over; y_cut None sums every particle
    (decays only), else only |y| < y_cut.  seed feeds the end-of-cascade
    decays (UrQMD, SMASH).
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
    nsamples = 0
    ndecays = 0
    unknown_neutral = 0
    for parts in read_events(kind, name, iss_table):
        nsamples += 1
        if rng is not None:
            parts, nd = end_decays(parts, rng)
            ndecays += nd
        if not len(parts):
            continue
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
    return {
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
    os.replace(tmp, path)


def empty_sums(y_range):
    """Sums of an event without particles (no_surface)."""
    npt = len(PT_EDGES) - 1
    yedges = np.arange(y_range[0] - Y_PROFILE_MARGIN,
                       y_range[1] + Y_PROFILE_MARGIN + 1e-9, Y_PROFILE_STEP)
    return {"nsamples": 0,
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
    args = ap.parse_args()
    collection = "all" if args.y_cut is None else "window"
    s = accumulate(args.kind, args.particles, args.y_range, args.y_cut,
                   args.iss_table, decay_seed(args.event_id, args.variant))
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
