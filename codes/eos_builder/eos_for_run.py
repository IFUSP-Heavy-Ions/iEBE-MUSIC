#!/usr/bin/env python3
"""The EoS table of one run (a parameter dictionary with an `eos_dict`).

What the table depends on, and where each piece comes from:
    c_s^2(T) above T_sw   eos_dict: a frozen model (eos_models.py) and the
                          design point's coordinates, or a (T, c_s^2) file
    T_sw                  the run's freeze-out temperature, music_dict's
                          T_freeze (hydro switches to particles there, so it
                          is always the anchor of the hadron gas)
    hadron list           the list iSS samples for this run (particle_list,
                          afterburner), read from the resolved iSS input
T_sw and the list are read from the files the parameter master wrote
(model_parameters/MUSIC/music_input_mode_2, model_parameters/iSS/
iSS_parameters.dat), never from a second copy, so they cannot disagree with
what MUSIC and iSS are given.

    eos_dict = {
        'cs2_model': 'eos_model_<sha>.json',   # frozen model (eos_models.py)
        'cs2_model_sha256': '<sha256 of that file>',   # optional check
        'coordinates': {'eos_z1': 0.31, ...},  # its design columns
    }
or
    eos_dict = {'cs2_table': '<T [GeV], c_s^2 file>',
                'cs2_table_sha256': '...'}     # optional check

Relative paths are taken relative to the parameter file, then (on a grid
worker, where shipped files land in the job folder) as a bare name in the
working directory.

The table is a pure function of its inputs (format version, T_sw, the hadron
list's sha256, the c_s^2 source), whose sha256 names it:
eos_table_<16 hex>.dat.  A table of that name found next to the parameter
file or in the working directory, with the same inputs in its header, is used
as it is (a campaign can build tables once, ship them, and every worker reads
the same bytes); otherwise it is built here.

    eos_for_run.py prebuild <parameter files...> --codes <codes dir>
        [--out-dir DIR]   build each run's table next to its parameter file
                          (or in DIR), running the parameter master for the
                          resolved T_freeze and hadron list; run it where the
                          codes are built (e.g. inside the image)
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_eos_table as bet  # noqa: E402
import eos_models  # noqa: E402

# the name MUSIC is given (not *.dat: run_hydro.sh deletes MUSIC/*.dat before
# every event, and sweeper.sh moves *.dat into the results)
TABLE_IN_MUSIC_INPUT = "eos_table.txt"


def read_key_value(path, sep=None):
    out = {}
    for line in open(path):
        if sep:
            if sep not in line:
                continue
            k, v = line.split(sep, 1)
        else:
            parts = line.split()
            if len(parts) < 2:
                continue
            k, v = parts[0], parts[1]
        out[k.strip()] = v.strip()
    return out


def hadron_list_name(iss, eos_to_use):
    """iSS's choice of particle table (src/data_struct.h particle_list_name,
    with EOS 9 / 91 forcing the UrQMD / SMASH afterburner as in
    src/readindata.cpp)."""
    particle_list = int(float(iss.get("particle_list", 0)))
    if particle_list == 21:
        return "PDG2021Plus"
    if particle_list != 0:
        raise ValueError("unknown particle_list %d" % particle_list)
    afterburner = int(float(iss.get("afterburner_type", 1)))
    if eos_to_use == 9:
        afterburner = 1
    elif eos_to_use == 91:
        afterburner = 2
    return {1: "urqmd_v3.3+", 2: "SMASH"}.get(afterburner, "s95pv1")


def resolve_run(model_parameters, codes_path):
    """(T_sw [GeV], hadron list file) of a run from its resolved inputs."""
    music = read_key_value(
        os.path.join(model_parameters, "MUSIC", "music_input_mode_2"))
    iss = read_key_value(
        os.path.join(model_parameters, "iSS", "iSS_parameters.dat"), "=")
    if int(float(music.get("use_eps_for_freeze_out", 0))) != 0:
        raise ValueError("eos_dict: the hadron gas is anchored at T_freeze, so"
                         " the freeze-out must be at constant temperature "
                         "(music_dict['use_eps_for_freeze_out'] = 0)")
    t_sw = float(music["T_freeze"])
    name = hadron_list_name(iss, int(float(music.get("EOS_to_use", 9))))
    pdg = os.path.join(codes_path, "iSS_code", "iSS_tables",
                       "pdg-%s.dat" % name)
    if not os.path.isfile(pdg):
        raise FileNotFoundError("hadron list %s not found" % pdg)
    return t_sw, pdg


def locate(name, param_dir):
    """A file named in eos_dict: as given, relative to the parameter file, or
    by its bare name in the working directory."""
    cands = [name] if os.path.isabs(name) else [
        os.path.join(param_dir, name), name]
    cands.append(os.path.basename(name))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    raise FileNotFoundError("eos_dict: %s not found (looked in %s)"
                            % (name, ", ".join(cands)))


def cs2_source(eos_dict, param_dir):
    """(description of the c_s^2 source for the table's identity, a function
    returning (T, c_s^2))."""
    if "cs2_model" in eos_dict:
        path = locate(eos_dict["cs2_model"], param_dir)
        digest = eos_models.sha256_of(path)
        want = eos_dict.get("cs2_model_sha256")
        if want and want != digest:
            raise ValueError("eos_dict: %s has sha256 %s, the dictionary "
                             "expects %s" % (path, digest, want))
        coords = {k: eos_dict["coordinates"][k]
                  for k in sorted(eos_dict["coordinates"])}
        desc = {"cs2_model_sha256": digest, "coordinates": coords}

        def make():
            frozen = eos_models.load_frozen(path)
            z = eos_models.coordinates(frozen, coords)
            return eos_models.cs2_of(frozen, z)
        return desc, make
    if "cs2_table" in eos_dict:
        path = locate(eos_dict["cs2_table"], param_dir)
        digest = eos_models.sha256_of(path)
        want = eos_dict.get("cs2_table_sha256")
        if want and want != digest:
            raise ValueError("eos_dict: %s has sha256 %s, the dictionary "
                             "expects %s" % (path, digest, want))

        def make():
            d = np.loadtxt(path, ndmin=2)
            return d[:, 0], d[:, 1]
        return {"cs2_table_sha256": digest}, make
    raise ValueError("eos_dict needs 'cs2_model' (+ 'coordinates') or "
                     "'cs2_table'")


def table_inputs(eos_dict, param_dir, t_sw, pdg):
    desc, make = cs2_source(eos_dict, param_dir)
    inputs = {
        "format": bet.FORMAT,
        "T_sw_GeV": float(t_sw),
        "hadron_list": os.path.basename(pdg),
        "hadron_list_sha256": bet.sha256_of(pdg),
        "cs2_source": desc,
    }
    digest = hashlib.sha256(
        json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return inputs, digest, make


def table_name(digest):
    return "eos_table_%s.dat" % digest[:16]


def build_or_reuse(eos_dict, param_dir, t_sw, pdg, out, search=()):
    """Write the run's table to `out` (reusing a prebuilt one with the same
    inputs if one of the `search` folders has it); returns its header."""
    inputs, digest, make = table_inputs(eos_dict, param_dir, t_sw, pdg)
    name = table_name(digest)
    for folder in list(search) + [param_dir, "."]:
        cand = os.path.join(folder, name)
        if not os.path.isfile(cand):
            continue
        _, header = bet.read_header(cand)
        if header.get("meta", {}).get("inputs") == inputs:
            if os.path.abspath(cand) != os.path.abspath(out):
                shutil.copyfile(cand, out)
            print("EoS table: reusing %s" % cand)
            return header
        raise ValueError("%s does not have the inputs its name says" % cand)
    T, cs2 = make()
    sel = T >= t_sw - 1e-12
    if not np.any(T <= t_sw + 1e-12):
        raise ValueError("c_s^2 starts at %.4f GeV, above T_sw = %.4f GeV"
                         % (T[0], t_sw))
    # start the c_s^2 input exactly at T_sw
    T_in = np.concatenate(([t_sw], T[sel & (T > t_sw + 1e-12)]))
    c_in = np.interp(T_in, T, cs2)
    header = bet.make_table(T_in, c_in, t_sw, pdg, out,
                            meta={"inputs": inputs, "inputs_sha256": digest})
    print("EoS table: built %s (T_sw = %.4f GeV, %s)" % (out, t_sw,
                                                        inputs["hadron_list"]))
    return header


def table_for_run(eos_dict, param_file, model_parameters, codes_path):
    """Build (or reuse) the table of a run into
    model_parameters/MUSIC/eos_table.txt, the file MUSIC is pointed at."""
    t_sw, pdg = resolve_run(model_parameters, codes_path)
    out = os.path.join(model_parameters, "MUSIC", TABLE_IN_MUSIC_INPUT)
    return build_or_reuse(eos_dict, os.path.dirname(os.path.abspath(
        param_file)), t_sw, pdg, out)


def load_eos_dict(param_file):
    import runpy
    return dict(runpy.run_path(param_file).get("eos_dict", {}) or {})


def prebuild(param_file, codes_path, out_dir=None):
    """Build a run's table next to its parameter file (or in out_dir) under
    its content name, for shipping with the jobs."""
    param_file = os.path.abspath(param_file)
    eos_dict = load_eos_dict(param_file)
    if not eos_dict:
        print("%s: no eos_dict" % param_file)
        return None
    master = os.path.join(os.path.dirname(os.path.abspath(codes_path)),
                          "config", "parameters_dict_master.py")
    with tempfile.TemporaryDirectory(prefix="eos_prebuild_") as work:
        subprocess.run([sys.executable, master, "-path", work, "-par",
                        param_file, "-seed", "0"], check=True,
                       cwd=os.path.dirname(master),
                       stdout=subprocess.DEVNULL)
        t_sw, pdg = resolve_run(os.path.join(work, "model_parameters"),
                                codes_path)
    param_dir = os.path.dirname(param_file)
    inputs, digest, _ = table_inputs(eos_dict, param_dir, t_sw, pdg)
    out = os.path.join(out_dir or param_dir, table_name(digest))
    header = build_or_reuse(eos_dict, param_dir, t_sw, pdg, out,
                            search=[out_dir] if out_dir else [])
    return out, header


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prebuild")
    p.add_argument("param_files", nargs="+")
    p.add_argument("--codes", required=True,
                   help="the codes/ folder of a built framework")
    p.add_argument("--out-dir", default=None)
    a = ap.parse_args()
    for f in a.param_files:
        r = prebuild(f, a.codes, a.out_dir)
        if r:
            print("%s -> %s" % (f, r[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
