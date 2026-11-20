# Rapidity window for UrQMD and SMASH

Scripts behind `docs/notes/afterburner_rapidity_window.md`. They start from
event folders kept by a chain run (`rerun_event_inner.sh` with
`save_hydro_surfaces = True`, `save_UrQMD_files = True`, one folder per
afterburner and event, named `<UrQMD|SMASH>_ev<id>` under a base directory)
and re-run only iSS and the cascade, with the full image
(`WITH_OPTIONAL_CODES=1`):

| script | does |
|---|---|
| `scan_inner.sh <ab> <event> <width> <n> <base>` | one point of the width scan: iSS with `y_LB/y_RB = -+width/2`, the cascade, timing, profile |
| `hs_inner.sh <ab> <event> <width> <job> <chunks> <n> <base>` | high-statistics chunks at one width, fixed seeds |
| `profile.py <smash\|urqmd\|bin> <file> <out.npz>` | rapidity profiles (N, sum pT, Q2, Q3 per 0.25) of a SMASH binary, a UrQMD list converted by the toolkit's `convert_to_binary`, or the chain's own binary |
| `analyze.py <base>` | time against width, edge reach (all widths pooled), usable particles per second |
| `hs_analyze.py <base> <ab> <event> <width>` | edge reach of dN/dy, <pT>, v2, v3 from the high-statistics chunks |

Each `*_inner.sh` runs inside the image, e.g.

    docker run --rm --user $(id -u):$(id -g) -v $BASE:$BASE --entrypoint bash \
        iebe-music:full-241af6c $BASE/scan_inner.sh UrQMD 140 6 200 $BASE

with the scripts copied into `$BASE`.
