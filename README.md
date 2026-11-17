# iEBE-MUSIC — QGP-USP chain

Event-by-event simulation of relativistic heavy-ion collisions, as run by the
heavy-ion group at the University of São Paulo. This is a fork of
[chunshen1987/iEBE-MUSIC](https://github.com/chunshen1987/iEBE-MUSIC): the
scripts that assemble the stages of the simulation, build them into one
container, and run it at scale. Branch `QGP-USP` is the group's working branch;
`main` follows upstream.

What this fork adds to upstream is a TRENTo-based chain with deformed nuclei,
built so that a large design-point sweep is **reproducible** and its points are
**statistically synchronized** (the same event number is the same pair of
nuclei at every design point).

## The chain

| stage | code | source |
|---|---|---|
| nucleon positions (deformed, fluctuating shapes) | Isobar-Sampler | [mluzum/Isobar-Sampler](https://github.com/mluzum/Isobar-Sampler) |
| initial condition | TRENTo | [IFUSP-Heavy-Ions/trento](https://github.com/IFUSP-Heavy-Ions/trento) |
| free streaming | `freestream` | PyPI, pinned |
| viscous hydrodynamics | MUSIC | [IFUSP-Heavy-Ions/MUSIC](https://github.com/IFUSP-Heavy-Ions/MUSIC) |
| particlization | iSS | [IFUSP-Heavy-Ions/iSS](https://github.com/IFUSP-Heavy-Ions/iSS) |
| hadronic stage | resonance decays, UrQMD or SMASH | upstream |
| observables | hadronic_afterburner_toolkit | [IFUSP-Heavy-Ions/hadronic_afterburner_toolkit](https://github.com/IFUSP-Heavy-Ions/hadronic_afterburner_toolkit) |

Each fork carries this chain's changes as ordinary commits on a branch
`QGP-USP`, and `codes/get_code_packages.sh` fetches every code at a pinned
commit. The upstream backends (IP-Glasma, 3D MC-Glauber, KoMPoST, photon
emission) are still fetched and built as in upstream.

## Quick start

With Docker — builds every code from pinned sources with a pinned toolchain:

```bash
docker build --build-arg WITH_OPTIONAL_CODES=0 -t iebe-music:slim docker/   # TRENTo + hydro + iSS + decays
docker build -t iebe-music:full docker/                                    # every backend
```

Or natively (Ubuntu 24.04 is what CI tests; 30–60 min):

```bash
sudo apt-get install build-essential gfortran cmake git wget python3-pip \
    libfftw3-dev hdf5-tools libhdf5-dev libgsl-dev libeigen3-dev libboost-all-dev
pip install numpy scipy h5py PyYAML freestream
cd codes && ./get_code_packages.sh && ./compile_code_packages.sh && cd ..
```

Run one event:

```bash
python3 generate_jobs.py -w test -n 1 -par config/design_points/parameters_dict_user_TRENTo_dp0.py
cd test/event_0 && bash submit_job.script       # a few minutes; writes spvn_results_<id>.h5
```

`python3 generate_jobs.py -h` lists the options. Parameters are plain Python
dictionaries; `config/parameters_dict_master.py` defines every one that exists,
and a user file overrides a subset.

## A design-point sweep

```bash
python3 scripts/make_design_a96.py --n 2000 --seed 8675309 --out design/my_design.csv
python3 MakeDictionaries.py --design design/my_design.csv \
    --start-design-point 1 --end-design-point 250 --output-dir my_dicts
python3 scripts/stage_campaign.py --dict-dir my_dicts --dps 1-250 --offsets 0 ...   # OSG submit files
```

An event is identified by `(master seed, seed_add, event id, sub-event)`, and
the nucleon configurations depend only on the event id, so every design point
sees the same nuclei.

## Where things are

| | |
|---|---|
| [`campaigns/`](campaigns/) | the record of each campaign that was run: code revisions, container, design, seeds — enough to reproduce it |
| [`docs/chain.md`](docs/chain.md) | where each component comes from, how the image is built and published, how to upgrade a component and validate the result |
| [`docs/importance_sampling.md`](docs/importance_sampling.md) | simulating a weighted subset of events, for good statistics in narrow centrality classes |
| [`docs/osg_operations.md`](docs/osg_operations.md) | running at scale on the Open Science Grid: what has gone wrong |
| [`docs/numerical_precision.md`](docs/numerical_precision.md) | grid, time-step and sampling convergence of the chain |
| [`docs/deformation_sampling.md`](docs/deformation_sampling.md) | parameterization of fluctuating nuclear deformation |
| [`AGENTS.md`](AGENTS.md) | architecture and the traps in the code, for anyone (or any coding agent) about to change it |
| `scripts/` | design generation, staging, merging, auditing, local re-runs; `scripts/osg/` for collection and recovery on the OSPool |
| `analysisKit/`, `utilities/` | post-processing of `spvn_results_*.h5` (from upstream) |
| `docs/notes/` | historical working documents |

## Reproducibility

- Every source is pinned: the framework by commit in `docker/Dockerfile`, each
  physics code by commit in `codes/get_code_packages.sh`, the base image by
  digest, Python packages by version, system packages by a frozen OS snapshot.
- `scripts/campaign_lock.py` writes that whole chain of revisions into a
  campaign's record.
- Re-running an event on the same machine is bit-identical. Across machines
  the initial state and hydro agree and the sampled particles differ at the
  0.1–1 % level.

## Upstream

For IP-Glasma, 3D MC-Glauber and the other upstream workflows, the Sphinx
documentation in `docs/SphinxDoc/`, and the mailing list, see
[chunshen1987/iEBE-MUSIC](https://github.com/chunshen1987/iEBE-MUSIC). On NERSC,
export `PYTHONIOENCODING=utf-8` and `LC_CTYPE=en_US.UTF8` first.

Python code is formatted with YAPF (`.style.yapf`; run `./formatCode.sh`).
