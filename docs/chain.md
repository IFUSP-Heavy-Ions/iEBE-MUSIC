# The simulation chain: sources, image, runs, upgrades

**Where each piece comes from, how the container is built, how a run is made,
and how to prove that a change did not break anything.** Written as the
hand-off at the end of the zr96-c2 campaign, for whoever next changes the
physics codes; examples use that campaign's design points and paths.

| document | what it is for |
|---|---|
| **this file** | provenance of every component, image build/publish, the upgrade and validation workflow |
| `AGENTS.md` | the traps in the code. **Read it before touching anything.** |
| `docs/osg_operations.md` | the operational traps: submit side, OSG quirks, data handling, merging |
| `campaigns/zr96-c2/` | the record of the campaign: manifest, software lock, design, and `NOTES.md` with the physics configuration and the validation numbers to compare against |
| `README.md` | installing and running a single event |
| `docker/Dockerfile` | the image, commented line by line, including why every pin is a pin |
| `codes/get_code_packages.sh` | every external repository and its exact commit |
| `docs/numerical_precision.md` | what the numerics can resolve, and the reproducibility evidence |

## 1. The chain, in order

| stage | code | lives in | notes |
|---|---|---|---|
| nucleon positions | Isobar-Sampler, branch `QGP-USP` | `codes/isobar_sampler_code/` | the branch carries the deterministic seeds and the deformation fluctuations (`sigma_beta_2/3`, `sigma_gamma`) |
| initial condition | TRENTo | `codes/trento_code/` | `IFUSP-Heavy-Ions/trento`, branch `QGP-USP` |
| free streaming | `freestream` (pip) | — | pinned in the Dockerfile; physics-critical |
| hydrodynamics | MUSIC | `codes/MUSIC_code/` | EOS tables downloaded at build time |
| particlization | iSS | `codes/iSS_code/` | `IFUSP-Heavy-Ions/iSS`, branch `QGP-USP`: carries the PTB delta f |
| afterburner | UrQMD or SMASH, or `decay` (none) | `codes/urqmd_code/`, `codes/smash_code/` | `afterburner_type: "decay"` is what campaign 2 uses |
| analysis | hadronic_afterburner_toolkit | `codes/hadronic_afterburner_toolkit_code/` | `IFUSP-Heavy-Ions/hadronic_afterburner_toolkit`, branch `QGP-USP`: carries the boost-invariant dN/dy |
| glue | `codes/hydro_plus_UrQMD_driver.py`, `generate_jobs.py` | repo root | in-repo, not fetched |

Optional backends that the current path never touches: `3dMCGlauber`, `ipglasma`,
`kompost`, `photonEmission` (dropped from the slim image).

## 2. Provenance: what pins what

Three layers, all immutable by construction:

1. **Base image** — pinned by digest in `docker/Dockerfile`
   (`opensciencegrid/software-base:23-el9-release@sha256:...`). Tags are mutable,
   digests are not.
2. **The framework** — the Dockerfile does `git fetch origin <full-40-char-SHA>`
   from `github.com/IFUSP-Heavy-Ions/iEBE-MUSIC` (pins up to and including
   campaign zr96-c2's `17ae5b4` were fetched from `github.com/mluzum/iEBE-MUSIC`,
   where they remain). The current pin is in `docker/Dockerfile`. It cannot name its own commit, so
   it always points one commit back: bump it in the commit *after* the one you
   want.
3. **Every external code** — `codes/get_code_packages.sh`, one
   `clone_repo_at_commit <url> <dir> <sha>` per package:

| directory | repository | pin | what the fork adds |
|---|---|---|---|
| `isobar_sampler_code` | `github.com/mluzum/Isobar-Sampler` (`QGP-USP`) | `b5eab93` | deterministic seeds, faster sampler, fluctuating deformation, many events per call, on top of `Public_Release` `bc586de` |
| `trento_code` | `github.com/IFUSP-Heavy-Ions/trento` (`QGP-USP`) | `54aa461` | nucleon-configuration interface, event-id mode, on top of Duke-QCD `10960b2` |
| `MUSIC_code` | `github.com/IFUSP-Heavy-Ions/MUSIC` (`QGP-USP`) | `d1323e8` | resummed transport coefficients (`FlagResumTransportCoeff`, off by default) and the tabulated EoS 24 of luizafperin/MUSIC, on top of upstream `XSCAPE` `cfcc264` |
| `iSS_code` | `github.com/IFUSP-Heavy-Ions/iSS` (`QGP-USP`) | `24ae580` | PTB delta f and the RTA delta f with τ_R ∝ E^γ (upstream branch `newRTA`), on top of upstream `XSCAPE` `d242555` |
| `hadronic_afterburner_toolkit_code` | `github.com/IFUSP-Heavy-Ions/hadronic_afterburner_toolkit` (`QGP-USP`) | `d00b6c9` | boost-invariant dN/dy, on top of upstream `2326ba2` |
| `3dMCGlauber_code` | `github.com/mluzum/3dMCGlauber` | `1d9856c` | (optional backend) |
| `ipglasma_code` | `github.com/chunshen1987/ipglasma` | `bf92fe1` | (optional backend) |
| `kompost_code` | `github.com/chunshen1987/KoMPoST` | `ad5fe9d` | (optional backend) |
| `photonEmission_hydroInterface_code` | `github.com/chunshen1987/photonEmission_hydroInterface` | `b80fb78` | (optional backend) |
| `urqmd_code` | `bitbucket.org/Chunshen1987/urqmd_afterburner` | `09eeac2` | (optional backend) |
| `smash_code` | `github.com/smash-transport/smash` | tag `SMASH-3.2.2` | (optional backend) |

Nothing is patched or overlaid during the build: every modification this chain
makes to a physics code is an ordinary commit on the `QGP-USP` branch of its
fork. To change a component, commit to the fork, then bump its SHA in
`codes/get_code_packages.sh`. (Campaign zr96-c2 was built the old way -- two
patches from `codes/patches/` and an in-tree `build_isobars.py` copied over the
clone; the fork branches reproduce those trees exactly, and
`campaigns/zr96-c2/components.lock.yaml` records what that image used.)

Check the framework pin before pushing (it replays the Dockerfile's own git
sequence):

```bash
scripts/check_docker_pin.sh
```

## 3. Building and publishing the image

```bash
# full image (all backends)
docker build --build-arg WITH_OPTIONAL_CODES=1 -t iebe-music:full docker/

# slim image (TRENTo + hydro + iSS + decays; what campaign 2 runs)
docker build --build-arg WITH_OPTIONAL_CODES=0 -t iebe-music:slim docker/
```

The build takes ~13 min of CI plus the compile of every package. `WITH_OPTIONAL_CODES=0`
deletes SMASH, UrQMD, osc2u, IPGlasma, KoMPoST, photon emission, 3dMCGlauber and
`/opt/pythia8315`, and then **asserts** that everything an event folder needs is
still present — if you add a dependency to the driver, add it to that keep-list
or the slimming will silently drop it and the assert will tell you.

Publish under a name that cannot collide, and never reuse one:

```bash
docker save iebe-music:slim | gzip > iebe-music_slim.tar.gz
singularity build iebe-music_slim_<short-sha>_<md5prefix8>.sif docker-archive://iebe-music_slim.tar.gz
md5sum iebe-music_slim_<short-sha>_<md5prefix8>.sif      # record this
# copy to the AP data disk, e.g. /ospool/ap40/data/matthew.luzum/
```

The submit files then reference `osdf:///ospool/ap40/data/matthew.luzum/<that name>`.
**The md5 prefix is not decoration**: OSDF caches by path, so overwriting a SIF
in place serves the *old* bytes to some workers and the new ones to others — some
fail with `Pelican Client Error: checksum mismatch`, others silently run the
wrong image. This has happened twice. Derive the name from the pinned SHA (not
HEAD) *and* include the md5, because two builds can share a SHA.

The campaign-2 image is `iebe-music_slim_17ae5b4_f5242628.sif`
(`/data/mluzum/iebe-music_slim_17ae5b4_f5242628.sif` locally).
The image of framework revision `6604e5f` (importance sampling, faster nucleus
sampler; same physics, reference events bit-identical to campaign 2) is
`iebe-music_slim_6604e5f_2271081a.sif`, md5 `2271081afc8156eb530c732d53133884`.

## 4. How a run is made

### Event identity — do not change this if you want comparability

An event is `(MASTER_SEED = 8675309, seed_add = 0, event_id, iev)`:

- nucleon-pool address depends only on `event_id`
  (`(2g)K`, `(2g+1)K mod 2^32`, `K = 2654435761`), so the same id at every design
  point uses the same nuclei;
- TRENTo seed is `event_id + 1`;
- the freeze-out seed is `np.random.default_rng([seed_add, event_id, iev])`;
- batch *k* uses event ids `[k·2000, k·2000+1999]`, so a new batch adds *new*
  events at every design point.

This is the common-random-number design the whole emulator rests on. Changing any
part of it silently invalidates comparisons with existing results.

### Local path (one event, or a handful)

```bash
python3 generate_jobs.py -w test_dp0 -n 1 -par config/design_points/parameters_dict_user_TRENTo_dp0.py
cd test_dp0/event_0 && bash submit_job.script
```

### OSG path (a tranche)

```bash
python3 scripts/stage_campaign.py \
  --dict-dir <DesignPointN dirs> --dps 1-1000 --offsets 0,2000,4000 \
  --jobid-template 'zr96_b{batch}_dp{dp}' \
  --image osdf:///ospool/ap40/data/matthew.luzum/iebe-music_slim_17ae5b4_f5242628.sif \
  --apbase /ospool/ap40/data/<user>/zr96_prod \
  --aphome /home/<user>/zr96_stage \
  --out /tmp/stage
```

then ship `dicts/ run/ submit/` to the AP and `condor_submit` one file per
design point. The worker runs `run_singularity.sh`, whose positional contract is
fixed by `generate_jobs.py:266`:

```
run_singularity.sh <dict.py> <processId> <nEvents> <nThreads> <nUrqmdSamples> <eventOffset> [seedFile]
```

`event_start_id = eventOffset + processId * nEvents`, and the output archive is
`spvn_results<tag>_<processId>.tar.gz` where `tag = "_e<offset>"` when
`offset % 2000 == 0`. **The job index comes from argv, not from the slot's
ProcId** — that is what makes single-job repairs possible (write the index
literally and set `transfer_output_files` to match), but forgetting to change the
template's `queue 100` submits 100 identical jobs.

### Parameters

`config/parameters_dict_master.py` is the executable spec of every parameter: the
user dictionary is merged into it by `dict.update()`. Two consequences:

- a misspelt key is silently ignored and the master default wins (this once
  zeroed out twelve design axes);
- if the chain needs a new knob, add it to the master *and* to `MakeDictionaries.py`,
  then to the generated input files.

### Equation of state from a table (MUSIC `EOS_to_use 24`)

MUSIC can read one table of a Gaussian-process EoS ensemble at mu_B = 0 (from
Luiza Perin's MUSIC fork; tables in `github.com/luizafperin/MUSIC-EOS-data`,
never in the chain). In `music_dict`: `EOS_to_use = 24` and `EOS_gp_l`,
`EOS_gp_sigma`, `T_sw` [MeV], `EOS_gp_type` (hrg, pwr, w), `EOS_gp_sample`
(s0, s1, ...), `gp_type` (constrained, unconstrained, training),
`EOS_gp_mean` (unconstrained only), with MUSIC's defaults 400, 15, 150, hrg,
s0, constrained, 0_3. In `control_dict`: `EOS_gp_dir`, the folder that holds
`EOS-gp/` as MUSIC's `EOS/download_EOS-gp.sh` lays it out. `generate_jobs.py`
links the one table an event needs into its `MUSIC/EOS/EOS-gp/`; the OSG
generator and `stage_campaign.py` ship that table (~20 MB) with every job,
and on the worker it is found in the job folder. `MakeDictionaries.py` takes
the same names as optional design columns (and `--eos-gp-dir`). iSS has to
accept the number too (iSS pin `24ae580`). Keep `T_freeze` below `T_sw`
(generate_jobs.py warns): above it the freeze-out falls in the part of the
table that is not the hadron gas iSS samples. A run with a table takes about
40 % longer than with `EOS_to_use 9` (each lookup searches a 175,000-row
non-uniform table).

### Viscous corrections at particlization (delta f)

Which delta f iSS samples with is set by three `iss_dict` keys:

| model | `bulk_deltaf_kind` | `deltaf_model` | notes |
|---|---|---|---|
| 22-moment (Grad) | 20 | 0 | linear |
| Chapman-Enskog | 21 | 0 | linear |
| PTB | 21 | 1 | positive by construction |
| RTA, τ_R ∝ E^γ | 31 | 0 | linear; `deltaf_newRTA_gamma` = γ, 0 ≤ γ ≤ 1.5 (tables at 0, 0.5, 1, 1.5, interpolated); shear and bulk, no conserved charges |

The linear ones are clamped by the sampler to |delta f| ≤ 1. There are two ways
to run them:

* **One model per event.** Set the keys in `iss_dict`, e.g.
  `iss_dict['bulk_deltaf_kind'] = 31; iss_dict['deltaf_newRTA_gamma'] = 0.7`,
  and leave `control_dict['deltaf_models']` out.
* **Several models on the same hydro surface.**
  `control_dict['deltaf_models'] = {name: {iSS overrides}}` particlizes every
  surface once per entry, with the same seeds, into `deltaf_<name>`; each group
  records its overrides in the attribute `iss_overrides`. An extra model costs
  30–55 s per event on top of 80–170 s for hydro plus one model (zr96-c2 dp 583),
  so a scan in γ is about three times cheaper this way than as separate events.

`MakeDictionaries.py` writes either for a whole design:
`--deltaf-models CE,PTB,RTA050,RTA100` (`RTA<nnn>` is γ = nnn/100 at every
design point), or a design column `deltaf_newRTA_gamma` for a γ that varies with
the design point (model name `RTA`; combine with others as
`--deltaf-models PTB,RTA`; `--deltaf-models none` gives the single flat
particlization).

## 5. What comes out, and how it is merged

Per event, `spvn_results_<id>.h5` holds one group per event with the hydro-level
datasets and one subgroup per delta-f model (`deltaf_Grad22`, `deltaf_CE`,
`deltaf_PTB` in zr96-c2), with attributes `deltaf_models`,
`toolkit_npT/pT_min/pT_max`, and `iss_overrides` on each subgroup.
Next to it, `qn_<id>.h5` is the standard per-event output
(`docs/standard_output.md`, written by `codes/standard_output.py` for every
afterburner; SMASH events have only this file): exact per-species, per-pT-bin
sums of the final particles, which `scripts/merge_qn.py` merges into one dense
`qn_dpNNNN.h5` per design point. Since 2026-11-20 the toolkit tables are no
longer written (`control_dict['toolkit_tables'] = True` brings them back,
e.g. to compare with an earlier campaign); `scripts/osg/consolidate_dps.sh`
merges whichever format a design point has, and only one of them, because the
analysis adapter refuses a folder holding both.
Per job, one tarball with 20 event h5 files (both kinds) plus the TRENTo
summaries, grid extents and `events_drawn_<proc>.csv`.

`scripts/osg/consolidate_dps.sh` extracts the tarballs one design point at a time and
`scripts/merge_dp_h5.py` writes `merged/<dp>/<dp>.h5` plus `sources.txt` (a
fingerprint of how many archives went in) and `csv.tgz`. It re-merges when the
fingerprint changes: immediately at a multiple of 100 archives, otherwise at most
once per `MERGE_AGE` (2 h), so a trickling block does not cause dozens of merges
and a point that genuinely ends short is not stranded forever. `MIN_SOURCES=90`:
a 100-job block yields 90–99 archives because jobs whose events all skip the
freeze-out surface produce none.

## 6. The upgrade workflow

For each component you bump:

1. **Pin.** External code → commit to its fork's `QGP-USP` branch and change the SHA in `codes/get_code_packages.sh`.
   Framework → change the SHA in `docker/Dockerfile` (in the commit *after* the
   one you want; the pin cannot name its own commit).
2. **Verify the pin.** `scripts/check_docker_pin.sh` (full 40-char SHA, differs
   from the containing commit, reachable on the remote).
3. **Build both images.** `WITH_OPTIONAL_CODES=0` first — it is smaller and
   faster to iterate on.
4. **Smoke test.** One event locally through `generate_jobs.py` + `submit_job.script`.
5. **Validate against the reference event.** `dp0583` is the campaign's reference
   point; `campaigns/zr96-c2/NOTES.md` §6 lists the numbers it must reproduce.

   ```bash
   # generate the dictionaries first: dictionaries.regenerate in campaigns/zr96-c2/campaign.yaml
   python3 scripts/rerun_events_local.py \
     --param zr96_design_c2/DesignPoint583/parameter_dictionary_design_point_583.py \
     --events 101,140,377 --out /tmp/upgrade --variant new \
     --image iebe-music:slim-<newsha> --jobs 3
   ```

   Run the same events with the old image (`--variant old`) and compare. For code
   changes that should be *transparent*, use `--bind` to overlay just the changed
   file on the old image and diff event by event — that isolates the change from
   the rebuild.
6. **Publish** under `<name>_<sha>_<md5prefix>.sif`, record the md5.
7. **Canary.** One design point (100 jobs) on the real submit path; confirm the
   archive tag, the collector, the merge and the toolkit attributes before
   launching a tranche. Almost every naming/transfer bug shows up here.
8. **Record provenance** with `campaigns/zr96-c2/operations/build_reproduction_package.py` once results
   exist.

### What each upgrade will move

| component | expect | watch for |
|---|---|---|
| TRENTo | everything shifts | normalization, `reduced-thickness`, `fluctuation` (= 1/σ_k²), nucleon width |
| isobar sampler | nuclear shape, hence all flow | `gamma` is **degrees in the design CSV, radians in the YAML**; `beta_3` sign is a rotation, not a degree of freedom |
| MUSIC | spectra, v_n, ⟨p_T⟩ | EOS choice; `music_dict` decides the viscosity — the JETSCAPE parametrisation is `T_dependent_Shear_to_S_ratio = 3`; option 7 has no amplitude knob; `FlagResumTransportCoeff = 1` is a different set of equations, not a refinement (⟨p_T⟩ +3 to +14 % at zr96-c2 dp 583) |
| iSS | yields, delta-f | the MC_sampling 4 sampler clamps linear delta f to [-1,1]; `restrict_deltaf` does nothing there; use `deltaf_model 1` (PTB) if you want positivity; `bulk_deltaf_kind 31` (RTA with τ_R ∝ E^γ) is linear too |
| afterburner | spectra, especially baryons | `decay` vs UrQMD changes the pT grid interpretation downstream |
| toolkit | every table the analysis reads | pT bins are `pT_min + i·(pT_max-pT_min)/npT`; identified species are flat in *rapidity*, all-charged references are pseudorapidity |
| free streaming | initial energy/flow | `Initial_profile 92` throws away the flow; 9 keeps the full T^munu |

## 7. Validation toolbox

| tool | what it proves |
|---|---|
| `scripts/rerun_events_local.py` | re-runs a campaign event in the image, with `--bind`/`--set` to isolate a change; deterministic locally |
| `scripts/check_freestream_table.py` | the free-streaming table carries e, u^mu and π^munu, in MUSIC's frame and units |
| `analysis/scripts/scan_missing_tables.py` | every event has all 26 tables per delta-f model, 2-D, with the expected pT grid |
| `scripts/audit_event_losses.py` | drawn events vs produced events per block |
| `docs/numerical_precision.md` §6, §9 | what is and is not bit-reproducible |

## 8. Traps that have already cost days (condensed)

Full list and dates in `AGENTS.md` and `docs/osg_operations.md`; these are the ones that bite an upgrade:

- **`checkpoint_exit_code` in a submit file** makes every slot reject every job,
  silently (jobs stay idle). It must never be in the submit file.
- **Reusing a SIF path** serves stale bytes from the OSDF cache; always a new name.
- **Pin the thread count** (`OMP_NUM_THREADS`); MUSIC's reduction order changes
  the last bits of v2 between 4 and 8 threads.
- **0-byte and truncated archives**: a killed packing step leaves one; the
  collector drops empty ones, the merger quarantines unreadable ones — but only
  *after* checking `gzip -t`, because a transient ENOSPC once quarantined 103
  perfectly good archives.
- **`condor_rm <cluster> -constraint`**: if the cluster id parses to empty, the
  constraint applies to your whole queue (once removed ~26,000 jobs).
- **Cluster ids are shared** across users on the schedd; filter history by
  `JobBatchName`, never by a cluster range.
- **Never edit a shell script that is running**; bash resumes at a byte offset.
- **`merge_dp_h5` and the toolkit attributes**: a group without `toolkit_*` makes
  the adapter fall back to the campaign-1 pT grid, and the analysis silently
  discards the point.

## 9. Safe to change vs breaks comparability

- **Safe**: submit-side tooling, collectors, mergers, analysis scripts, documentation.
- **Breaks common random numbers** (and therefore comparability with every
  existing point): the seed scheme, the event-id → pool-address mapping,
  `seed_add`, the batch offsets.
- **Breaks physics comparability**: any code pin, any parameter in the master
  dictionary, EOS, delta-f model, afterburner choice, freeze-out temperature,
  pT grid.

If an upgrade is meant to *replace* the campaign rather than extend it, say so
explicitly and start a new results tree; do not mix pins inside one campaign.

## 10. Open items as of this hand-off

- **Cross-machine reproducibility is only half demonstrated.** The nucleus HDF5
  is bit-identical across machines; the sampled particles are not (0.1–1 % in the
  tables, because iSS's stream is reseeded by last-bit differences in the hydro).
  Local re-runs are bit-identical. Treat "same event ⇒ same particles" as false
  across hardware.
- **The OSG SMASH branch hardcodes `event_0`** (no event range). Use the UrQMD
  branch, or `afterburner_type: "decay"`, until that is fixed.
- **No main-design status file** exists (the extension has `STATUS_A96_c2_ext.md`);
  the 1,000-point design has to be summarised from `merged/*/sources.txt` and the
  drawn-event CSVs.
- **Batch 3 (event ids 4000–5999) is not staged.** Nothing exists for it beyond
  the ability to run `stage_campaign.py --offsets 4000`.

## 11. Where the results live

```
/data/mluzum/zr96c2_results/prod/<dp>/tarballs/     per-job archives (the raw record)
/data/mluzum/zr96c2_results/merged/<dp>/<dp>.h5     the analysis product
/data/mluzum/zr96c2_results/merged/<dp>/sources.txt fingerprint of what went in
/data/mluzum/zr96c2_results/design/                 the design CSV(s)
/data/mluzum/zr96c2_results/analysis/               the downstream session (notes, scripts, results)
/data/mluzum/zr96c2_results/merged/REPRODUCTION/    SIF md5, binary md5s, revision, design, dictionaries, submit files
```

`scripts/osg/consolidate_dps.sh`, `scripts/osg/osg_fetch_prune.sh`,
`campaigns/zr96-c2/operations/campaign2_loops.sh` and the two feeders (`feed_batch2.sh`,
`feed_ext_b2.sh`) are the operational layer; `scripts/osg/osg_recover_held.sh` handles
jobs held by the memory bug or the 12-hour checkpoint.
