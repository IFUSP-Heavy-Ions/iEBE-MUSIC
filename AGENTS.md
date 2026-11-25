# AGENTS.md — iEBE-MUSIC, QGP-USP chain

Event-by-event relativistic heavy-ion collision simulation driver. This is **not** an importable
library: top-level scripts generate job folders and cluster submission scripts. There is **no test
suite, no linter config, and no typechecker** — verification means running one event end-to-end.

> **Upgrading the chain?** `docs/chain.md` maps every component's source and pin, how the container
> is built and published, the run/submit contracts, and the validate-before-you-launch workflow.
> **Running on OSG?** `docs/osg_operations.md` is the list of what has gone wrong there.
> This file is the list of traps in the code itself.

## Architecture

- `generate_jobs.py` — main entrypoint. Imports a user parameter file with `__import__`, then writes
  `<working_folder>/event_<id>/` (each with `submit_job.script`, `hydro_plus_UrQMD_driver.py`,
  `run_trento.sh`) plus a shared `<working_folder>/model_parameters/` of generated MUSIC / iSS /
  TRENTo input files.
- `config/parameters_dict_master.py` — merges the user dict (and optional bayesian/posterior file)
  and emits the actual solver input files. It is the executable spec of every available parameter;
  read it instead of guessing key names.
- `config/parameters_dict_user_*.py`, `config/design_points/*` — user parameter files. Plain Python
  modules defining top-level dicts (`control_dict`, `trento_dict`, `free_streaming_dict`,
  `music_dict`, `iss_dict`, `isobars_conf_dict_{target,projectile}`, `isobar_seed_file`).
- `codes/` — external physics codes fetched at setup by `get_code_packages.sh`, each at a pinned
  commit (`*_code` dirs are gitignored), plus the in-repo driver
  `codes/hydro_plus_UrQMD_driver.py` (copied into every event folder; takes **positional** args,
  no argparse). The nucleon sampler is `codes/isobar_sampler_code/exec/build_isobars.py`, from
  the Isobar-Sampler fork.
- `campaigns/<name>/` — the record of a campaign that was run: manifest, software lock, design.
- `scripts/` — design generation, OSG staging, merging, auditing, local re-runs; `scripts/osg/`
  — collection and recovery on the OSPool. `docs/` — the chain, OSG operations, numerics.
- `Cluster_supports/{OSG,HTCondor}/generate_submission_script.py` — Singularity+condor generators
  that emit `singularity.submit` + `run_singularity.sh`. These are a *separate* path from
  `generate_jobs.py` (which covers `local`, `nersc`, `wsugrid`, `guillimin`, `mcgill`, `stampede2`,
  `anvil`). See `Cluster_supports/HTCondor/README.md`.
- `analysisKit/` — post-processing from `spvn_results_*.h5` (pickle -> merge -> analyze; see its
  README). `utilities/` — result collection/merging into HDF5.

## Setup

```bash
cd codes && bash get_code_packages.sh && bash compile_code_packages.sh && cd ..   # every code at a pinned commit
```

30–60 min. This also downloads EOS tables, hdf5 delta-f tables, and nucleus configurations.
On NERSC export `PYTHONIOENCODING=utf-8` and `LC_CTYPE=en_US.UTF8` first.

## Commands

```bash
# one event, local machine
python3 generate_jobs.py -w test_dp0 -n 1 -par config/design_points/parameters_dict_user_TRENTo_dp0.py
cd test_dp0/event_0 && bash submit_job.script

# explicit global event range (inclusive; overrides -n)
python3 generate_jobs.py -w dp0 -c local --event_start_id 0 --event_end_id 999 \
  -par config/design_points/parameters_dict_user_TRENTo_dp0.py -n_th 4

# HTCondor/OSG: generate then submit
python3 Cluster_supports/OSG/generate_submission_script.py -param <par.py> -singularity <img.sif> \
  -n 10 -nev 1 -nth 1 -jobid <Name>          # writes singularity.submit
condor_submit singularity.submit

# design-point sweeps: design -> dictionaries -> staged OSG submission
python3 scripts/make_design_a96.py --n 2000 --seed 8675309 --out design/my_design.csv
python3 MakeDictionaries.py --design design/my_design.csv --start-design-point 1 \
    --end-design-point 250 --output-dir my_dicts
python3 scripts/stage_campaign.py --dict-dir my_dicts --dps 1-250 --offsets 0 \
    --jobid-template 'run_b{batch}_dp{dp}' --image osdf:///<path>/<image>.sif \
    --apbase <output dir on the AP> --aphome <staging dir on the AP> --out /tmp/stage

# collect finished events into a merged HDF5
./collect_events.sh <fromFolder> <toFolder>
```

`python3 generate_jobs.py -h` and running `generate_submission_script.py` with no args print full
defaults — prefer those over guessing flags.

## Gotchas

- **Push with `scripts/push.sh`, and do not call a push done until its CI result is in.**
  `scripts/push.sh <remote> <branch> [<commit>]` pushes, then waits for every GitHub Actions run
  on that commit (`scripts/wait_ci.sh`) and prints the failing log lines. A bare `git push` only
  runs the local hook; a red workflow then shows up as an e-mail and nothing else. That is how
  the "Build Test" stayed red from 2026-11-20 (5a970cd) to 11-25: the runner's apt list lacked
  numpy and scipy, which iSS's `make_hrg_eos.py` has needed since the PDG2021+ list, while the
  container build and every local image test passed. The Build Test compiles on a stock Ubuntu
  24.04 with its own package list, which can drift from the Dockerfile's; when a push changes
  its inputs (`BuildTest.yml`, `get_code_packages.sh`, `compile_code_packages.sh`), the pre-push
  hook wants a passing local replica first: `scripts/ci_replica.sh [<commit>]`, about 30-40 min
  in `ubuntu:24.04`. A pin bump is pushed in two steps, the named commit first:
  `scripts/push.sh ifusp QGP-USP HEAD~1 && scripts/push.sh ifusp QGP-USP`.
- **Importance sampling is two phases, and the selection is made exactly once.** Phase 1
  (`scripts/draw_events.py`, `scripts/select_events.py`) draws every event id with the sampler and
  TRENTo in batches, calibrates multiplicity to centrality, and writes the list of accepted events
  with weights `1/P`. Phase 2 runs the chain from that list (`IEBE_EVENT_LIST`; a job owns
  *positions* of the list, files are still named by event id). Never let a worker redo the
  decision: two machines do not agree on the multiplicity to the last bit (up to 4e-7 between a
  local host and OSG), so an event on a bin edge could be kept on one and dropped on another.
  The batch paths (`configuration_stride` in the sampler, `--first-event-id` in TRENTo) exist to
  reproduce single-event runs digit for digit; `tests/sampler_stride.sh` and
  `tests/trento_event_id_mode.sh` check that and must be re-run for a new system or a new TRENTo.
  Phase 1 costs ~13 ms per event (A = 96; the sampler deforms a nucleus in ~5 ms since its
  deformation step was vectorised, bit-identically -- `tests/test_deform_vectorized.py` in the
  sampler repo); one sampler call holds at most ~2000 configurations (HDF5 attribute limit).
  `docs/importance_sampling.md` is the user-facing description.
- **In an importance-sampled campaign the minimum-bias denominator is in the selection summary,
  not in the event files.** `events_drawn.csv` then lists only accepted events, and `sum(w)`
  estimates the collided count only inside the covered centrality range; `n_collided` in
  `selection_dpNNNN.json` (copied to root attributes of the merged file by
  `merge_dp_h5.py --selection`) is the number to normalise percentiles with. Beyond the last
  bin edge the acceptance defaults to the last bin's, not zero, so nothing is unrepresented
  unless a campaign sets `"outside": 0` on purpose.
- **A selection needs the coverage whenever `b_max` cuts into the collision range.** Centrality
  is a fraction of the whole inelastic cross section; zr96-c2's `b_max` holds only 74-94 % of it, depending on the design point
  (`frac_below_bmax` in the `scripts/cross_section` table). Selecting with coverage 1 there puts
  every percentile too high by 1/coverage -- this happened in the first grid test and was caught
  by the analysis adapter. `select_events.py` now refuses when draws near `b_max` still collide
  and no `--xsec-table`/`--coverage` is given. For a new campaign the simpler choice is a
  `b_max` beyond the collision range: importance sampling makes the extra peripheral draws free.
- **An accepted event with no h5 is either empty or lost, and the two need opposite
  treatment.** The driver now writes `status = no_surface` in `events_drawn.csv` when the
  freeze-out surface is empty (a real collision with no particles; count it, with its weight)
  and `hydro_failed` when MUSIC did not finish; before, both stayed `ok` and were only
  distinguishable from a lost job by elimination. `merge_dp_h5.py --selection` turns that into
  a `status` column (`ok` / `no_surface` / `failed`) in the design point's selection list.
- **Every modified physics code lives on a fork, pinned by commit in `codes/get_code_packages.sh`.**
  Nothing is patched or overlaid during the build. The sampler is `mluzum/Isobar-Sampler`; TRENTo,
  MUSIC, iSS and the toolkit are under `github.com/IFUSP-Heavy-Ions`, each on a branch `QGP-USP`.
  To change a component: commit to its fork, bump the SHA, then bump the framework pin in
  `docker/Dockerfile` in the *following* commit. `docs/chain.md` has the full procedure.
- **A campaign is recorded in `campaigns/<name>/`, and the record is small on purpose.** Manifest,
  software lock (`scripts/campaign_lock.py`), design CSV, one submit file and the worker wrapper.
  Parameter dictionaries are *not* tracked: they regenerate byte-identically from the design, and
  the manifest carries a digest. Consequently **the text `MakeDictionaries.py` writes is frozen** --
  changing a description string in it or in the template changes every dictionary and breaks the
  digest of a recorded campaign. Framework pins up to zr96-c2's `17ae5b4` were fetched from
  `github.com/mluzum/iEBE-MUSIC` and must stay reachable there.
- **System packages are pinned to a frozen OS snapshot in `docker/Dockerfile`.** Without that, a
  rebuild takes the compiler of the day: 17 days after the zr96-c2 image the same recipe produced
  different binaries (the reference events still agreed bit for bit, but that is luck, not a
  guarantee).
- **Every binary must run on any x86-64 worker; nothing may be built with `-march=native`.**
  OSPool still has x86-64-v2 slots (no AVX2, ~9% in 2026-11). SMASH adds `-march=native`
  unconditionally, in its own CMakeLists.txt and in the bundled Cuba and einhard, so images up
  to `ca8b92d` carried a SMASH with ~94k AVX2/FMA instructions from the Zen 2 build host. It
  died with "Illegal instruction" on 7 of the 30 pbpb5020-eos pilot jobs (Clemson-Palmetto,
  Utah-Kingspeak, Hawaii-Koa), while MUSIC ran fine on the same nodes. The SMASH output of those
  images is valid where it ran; only portability was lost. `compile_code_packages.sh` strips the
  flag and ends by scanning every built ELF file for VEX instructions; it fails the build if
  it finds one. To run an old image on OSG anyway, add
  `(TARGET.Microarch =?= "x86_64-v3" || TARGET.Microarch =?= "x86_64-v4")` to Requirements.
- **Reproducibility is assumed, not demonstrated.** The seed scheme is counter-based and the
  container pins the framework to an exact SHA, but nobody has yet run the same event twice on
  local HTCondor and once on OSG and diffed the nucleus HDF5. The common-random-numbers design
  rests entirely on this. See Phase E2 in `docs/notes/EMULATOR_SWEEP_PLAN.md`; treat it as blocking.
  First data point (2026-10-30, `scripts/rerun_events_local.py`, campaign image
  `slim-3001ee9` under local docker, 1 thread): zr96 dp0583 event 220 re-ran **bit-identical**
  to the OSG output; event 10 had the same TRENTo event and initial eccentricities, MUSIC
  output equal to ~1e-8 relative, but particle tables differing by 0.1-1%, i.e. last-bit
  numerics differ between the OSG worker and this host (CPU-dependent libm paths are the
  usual suspect) and that reseeds iSS's sampling stream. Two local runs of the same event
  are bit-identical. So the initial state is common across machines; the sampled particles
  are common only on matching hardware.
- **Pin thread counts.** OpenMP/MPI reduction order in MUSIC can change `v2` in the last bits for
  *identical* input, so a 4-thread and an 8-thread run are not bit-identical even when the nucleon
  configurations are. Pin `OMP_NUM_THREADS`/`MKL_NUM_THREADS` in the job script and record the
  value in the event's output directory, so a future mismatch is diagnosable. Do not assert
  bit-identity of observables without measuring it — assert it of the nucleus HDF5, which must be
  exact.
- **Merge results by event id, never by completion order.** Each event owns a global id
  (`--event_start_id`/`--event_end_id`); parallel jobs finish out of order.
- **`tar` output must not depend on directory iteration order** if archives are compared across
  runs.
- **The sign of `beta_3` is a rotation, not a physical degree of freedom.** `Y_30` is odd in `z`, so
  a π rotation about x maps the `beta_3 = +b` surface onto `beta_3 = -b` (verified to 6.7e-16). The
  magnitude is the parameter. Do not spend a design axis on the sign.
- **Fetched code packages may be absent.** `codes/hadronic_afterburner_toolkit`,
  `codes/hadronic_afterburner_toolkit_code/ebe_scripts/average_event_spvn_h5.py` and
  `config/hadronic_afterburner_toolkit` are gitignored; without them `generate_jobs.py` cannot
  build a full event tree. Run `codes/get_code_packages.sh`.
- **Run `generate_jobs.py` from the repo root.** `isobar_seed_file` is resolved with
  `os.path.abspath` against the *current working directory*, not the parameter file's directory.
  This only applies to the legacy `seed_source: "file"` path — the default `philox` path reads no
  file at all.
- **Nucleon seeds are generated, not shipped (default `seed_source: "philox"`).** Event *g* maps to
  pool addresses `(2g)*2654435761` and `(2g+1)*2654435761 mod 2**32`, and each row is drawn from
  `numpy.random.Philox(key=master_seed, counter=address*2**24)`. **The address must depend only on
  the global event id, never on any nuclear parameter** — that is what keeps design points
  synchronised, so each sees the same nuclei and the deformation shows up as a small shift in
  positions. `MASTER_SEED = 8675309` is recorded in `docs/notes/EMULATOR_SWEEP_PLAN.md` and in every generated
  parameter dictionary; changing it invalidates all existing results. The committed
  `shared_seeds/nucleon-seeds.hdf` remains only for the legacy `seed_source: "file"` path.
- **`build_isobars.py` caches its step+Gaussian fit.** `Rst_w_from_WS` (a BFGS `minimize` over
  `quad`/`polylog`) costs ~2.4 s and is a pure function of `(WS_radius, WS_diffusiveness)`, but the
  shipped configs don't set `step_radius`/`step_diffusiveness`. The sampler therefore writes the
  result back into the run's own YAML with the `(R_ws, a_ws)` signature it came from, and later
  events in the same event folder reuse it. `run_trento.sh` rewrites that YAML per event via
  load-modify-dump, so the cache survives. Don't "clean up" the `_step_gaussian_cache` /
  `step_radius` keys — removing them silently costs ~2.4 s per invocation.
- **A nucleus pool reuses configurations; the mapping is part of event identity.** With
  `control_dict['nucleus_pool_size'] = M`, event `g = qM + r` uses target slot `r` and projectile
  slot `(r + q) mod M` (`generate_jobs.py` writes it into `run_trento.sh`; `draw_events.py`
  mirrors it). Changing M changes every event with `g >= M`, so a campaign's M is fixed once
  events exist, like `MASTER_SEED`. Draw pooled campaigns with `--pool-slots`; an id-block draw
  is correct but samples two nuclei per event, the cost the pool exists to avoid.
- The committed `shared_seeds/nucleon-seeds.hdf` is 63 MB with shape `(10000, 300, 6)`.
  `isobar_samples.number_nucleons.value` must be **<= 300**: `build_isobars.py` truncates each seed
  row to `number_nucleons` and exits 1 if `A` exceeds the available entries. Shipped templates use
  96/197, which is fine.
- Without `--nocopy`, `generate_jobs.py` `copytree`s the entire `codes/` tree into the working
  folder. `-c osg` forces `--nocopy` and also does `seed += job_id`.
- **`Cluster_supports/HTCondor/generate_submission_script.py` and the OSG one are separate
  submission paths from `generate_jobs.py`.** The HTCondor generator has its own defects history:
  it used to omit `--event_start_id`, so every job recomputed the same events, and it globs
  `EVENT_RESULTS_$(Process)` although the driver names results after the *global* event id. It now
  mirrors the OSG path (job *P* owns events `[P·N, P·N+N-1]`) and collects via an EXIT trap into
  `results_$(Process)/`. If you touch one generator, check whether the other needs the same change.
- **The OSG generator has one code path for every afterburner (since 2026-11-25).** SMASH used
  to have its own writers in `Cluster_supports/OSG/generate_submission_script.py`, an older copy
  without the event range, the event list, the per-job archive or the campaign seed: every SMASH
  job ran `event_0`. They are gone; SMASH uses the same writers as decay and UrQMD (the
  `*_urqmd` names are historical), and the afterburner comes from the parameter file.
- Root-level `collect_events.sh`, `combine_multiple_hdf5.py`, `average_event_spvn_h5.py` are
  gitignored because `generate_jobs.py` copies them into the CWD. Missing-from-git is not a bug.
- `MakeDictionaries.py` defaults to a `./design` CSV that is **not in the repo** — supply your own.
  Columns are strict: `WS_radius`, `WS_diffuseness`, `beta_2`, `gamma`, `beta_3`, `nucleon-width`,
  `tau`, `reduced-thickness`, `sigma_k`, `shear_viscosity_3_*`, `bulk_viscosity_3_*`, `T_freeze`
  (plus optional `beta_max`, `number_nucleons`). `sigma_k` is the JETSCAPE axis and is converted
  to TRENTo's `fluctuation` as `k = 1/sigma_k**2`; a `fluctuation` column (k itself) is only used
  when `sigma_k` is absent. `number_nucleons` is *not* taken from the CSV — it stays at the
  template value unless a `number_nucleons` column is supplied.
- **`gamma` is degrees in the CSV and radians in the isobar YAML.** The sampler treats
  `isobar_conf['gamma']['value']` as radians everywhere (see its own comment at
  `build_isobars.py:375`), while the design matrix documents `gamma` in degrees (prior
  [0, 60]). `MakeDictionaries.py` converts; if you write a parameter file by hand, convert
  there too, or 60 becomes 60 rad.
- **Every key `MakeDictionaries.py` writes must match `config/parameters_dict_master.py`
  exactly.** The merge is `dict.update()`, so a misspelt key is silently carried along
  unused and the master default wins — no error, no warning. This hid the whole `zeta/s`
  block: `bulk_viscosity_3_max` vs the master's `bulk_viscosity_3_zeta_over_s_max` meant
  axes 10-12 of the design were constants. Audit with
  `set(user_dict) - set(master_dict)` per dictionary. (`music_dict['T_freeze']` is the one
  expected extra: the driver reads it out of the generated MUSIC input.)
- **The yield normalisation uses the same window it counts in.** The toolkit's
  `drapidity = rap_max - rap_min` and its particle cut are the same window, so
  `dN/dy = N(in window)/(window width)`. That is right *only* because the density is flat
  in rapidity: identified species (`rap_type = 1`) are flat to 0.7 % for |y| < 4, but the
  all-charged references `9999`/`99999` are forced to `rap_type = 0`, i.e. pseudorapidity,
  whose y→η Jacobian gives a ~25 % mid-rapidity dip and a window-dependent "yield". Use
  identified particles in rapidity for the yield. The `_vndata_diff_y_-0.5_0.5` filename
  suffix is hardcoded and stale — the table is filled over `rap_min..rap_max`.
- **Tabulated EoS (MUSIC `EOS_to_use 24`) needs MUSIC, iSS and the table.** MUSIC pin `d1323e8` (or later)
  reads it (port of luizafperin/MUSIC); iSS before `24ae580` exits on an EoS number it does not
  know, which left events without particles that the driver then recorded as fine. The driver now
  calls an event whose particle list holds no event `particlization_failed`. Tables never go into
  the chain: `control_dict['EOS_gp_dir']`, and the job ships the one table it needs (20 MB). See
  "Equation of state" in `docs/chain.md`.
- **Prefer `eos_dict` to the EOS-gp tables, and never anchor an EoS anywhere but `T_freeze`.**
  Luiza's tables count the photon as a hadron and drop the antibaryons, so at T_sw = 136 MeV
  their P is 42 % and e 19 % above iSS's gas for the same list: iSS reads T = 139.3 MeV off the
  freeze-out e and the particles carry 5.6 % less entropy than the fluid (fewer, hotter
  particles: protons up, pions down, which is what the first EoS-24 test showed). An
  `eos_dict` run builds its table from c_s^2 above `T_freeze` and the hadron gas of the very list
  iSS samples (`codes/eos_builder`, matches iSS's `HRGEOS_PST-*.dat` to 3e-5), reading
  `T_freeze` and the list from the master's output, so they cannot drift apart. In the MUSIC
  folder the table is `eos_table.txt`, not `.dat`: `run_hydro.sh` runs `rm -fr *.dat` there
  before every event (a `.dat` link was silently deleted and MUSIC found no table). The
  iSS lists' charm/bottom columns are unreliable (omega has bottom = 3 in the UrQMD and s95p
  lists), so heavy flavour is read from the PDG code.
- **The toolkit tables are off by default** (`control_dict['toolkit_tables']`); the output is
  `qn_<id>.h5`. A regression against an earlier campaign's `spvn_results_<id>.h5` needs
  `toolkit_tables = True`.
- **SMASH runs once per particlization** (all ten iSS calls, one input file each, read in turn by
  SMASH's List modus): its ~17 s start-up before the first event was paid ten times per event and
  delta f model before.
- **UrQMD and SMASH: four traps, fixed together with the standard output** (details in
  `docs/notes/afterburner_rapidity_window.md`). (a) UrQMD continuing events from a file reads
  `rsd` only after seeding itself from the clock, so every run differed; its event header says
  `random seed: N (auto)`. `codes/patches/urqmd_fixed_seed.patch` (applied by
  `get_code_packages.sh`) makes it `(fixed)`. (b) SMASH numbers its output folders
  (`data/0`, `data/1`, ...): the old script ran it ten times per event and copied `data/0`
  each time, i.e. kept one run in ten; it now writes to a fixed folder with `-o ... -f`.
  (c) SMASH's `Nevents` was fixed at 50 while iSS writes as many samples as the event needs
  (34 aborted SMASH, 540 lost 490); it is now counted from `OSCAR.DAT` per run. (d) Both
  cascades end with eta and Sigma0 undecayed; `codes/standard_output.py` decays them before
  summing. The toolkit tables of a UrQMD run still lack (d).
- **HBT comes from the standard output's optional sums (`control_dict['hbt']`), not from the
  toolkit's `analyze_HBT`** (`docs/standard_output.md` section 9, `docs/notes/hbt_sums.md`).
  The toolkit's pair HBT gives all zeros on decays-only lists (its `read_in_mode 9` reader
  never advances the event index; upstream too). On UrQMD output it is biased: file 13 puts
  the 35% of pions that never collide at t = 8000 fm, and the pair weight is not invariant
  under free streaming. Two rules for anyone reading the sums: (a) never add `S` across Phi
  bins, because out and side are per particle; sum `hbt_num`/`hbt_pairs` as real values
  (adding S makes peripheral R_out and R_side 15-25% too large). (b) Compare radii, not
  lambda: each particle in its own LCMS gives radii within 1-3% of exact pairs but lambda
  1-8% high.
- **RTA delta f with τ_R ∝ E^γ: `bulk_deltaf_kind 31` + `deltaf_newRTA_gamma`, since iSS pin `bbc4f9e`.**
  A backport of upstream iSS's branch `newRTA`, which was never merged there and renames the
  parameter to `deltaf_kind`; the fork keeps `bulk_deltaf_kind`. γ must be in [0, 1.5] (iSS exits
  otherwise; the tables are at 0, 0.5, 1, 1.5). The tables live in the fork
  (`iSS_tables/deltaf_tables/newRTA`), not behind a download. Run one γ per event through
  `iss_dict`, or several on the same surface through `control_dict['deltaf_models']`
  (`MakeDictionaries.py --deltaf-models ...,RTA050,RTA100`, or a design column
  `deltaf_newRTA_gamma`); see "Viscous corrections at particlization" in `docs/chain.md`. Model
  names end up as h5 group names (`deltaf_<name>`), so tell the analysis side which names a
  campaign uses.
- **`FlagResumTransportCoeff` works since MUSIC pin `f072672`; before, it was silently ignored.**
  The master has carried the flag since upstream's 2025-01 update, but the chain's MUSIC is the
  `XSCAPE` branch, which split from upstream `main` before the scheme was merged there and does not
  read unknown keys. The fork now carries a backport (upstream `main` `febb2ab` plus the
  `|Pi|/(e + P)` fix of `chun_dev` `b2c918a`). With the flag at 0 results are bit-identical to
  campaign 2; with 1 the change is large (zr96-c2 dp 583: pion ⟨p_T⟩ +3.5 % central, +14 %
  peripheral), so the two must never be mixed in one emulator. MUSIC does not complain about a key
  it does not know: when a new `music_dict` key seems to do nothing, grep
  `codes/MUSIC_code/src/read_in_parameters.cpp` for it (`FlagResetCausality` is still such a key).
- **The master's `music_dict` is the only thing that decides the viscosity.** MUSIC has always
  supported the JETSCAPE parametrisation (`T_dependent_Shear_to_S_ratio = 3` with
  `shear_viscosity_3_eta_over_s_{T_kink_in_GeV,low_T_slope_in_GeV,high_T_slope_in_GeV,at_kink}`,
  and `T_dependent_zeta_over_s = 3` with `bulk_viscosity_3_zeta_over_s_{max,T_peak_in_GeV,
  width_in_GeV,lambda_asymm}`), but the master only forwarded a constant `Shear_to_S_ratio` and
  the fixed-shape option 7 until 2026-10-22, and `shear_relax_time_factor` was never forwarded at
  all (so every run silently used MUSIC's default 5.0). Option 7 has **no** amplitude knob, so
  `(zeta/s)_max` was not a tunable parameter before the switch. Every ge76 param file inherits
  this block from the master, so changing the master changes every run that does not override it;
  set `T_dependent_Shear_to_S_ratio = 0` + `Shear_to_S_ratio = 0.12` + `T_dependent_zeta_over_s = 7`
  to reproduce anything from before that date.
- The OSG/HTCondor generator copies the seed HDF5 next to the param file and references it by
  basename. That root-level `nucleon-seeds.hdf` is **not** gitignored — do not commit it.
- `hydro_plus_UrQMD_driver.py`'s positional argument order is assembled in
  `generate_full_job_script()` (`generate_jobs.py:266`) — change both sides together.
- **`hadronic_afterburner_toolkit`'s `Analysis.cpp` ignores `rap_min`/`rap_max`.** `FlowAnalysis()`
  constructs one `singleParticleSpectra` per entry of a hardcoded list of experimental acceptance
  windows (ALICE ±0.5, STAR ±1, CMS ±2.4, ATLAS ±2.5/±4.9, V0A/V0C, PHENIX BBC, ...) and calls
  `paraRdr.setVal("rap_min", ...)` before each. Editing `rap_min` in `parameters.dat` changes
  nothing. The identified-species `_vndata_y_-0.5_0.5` files are ALICE's window, not yours. Any new
  rapidity analysis has to be added as another entry in that list - see the boost-invariant
  `_boostinv` block (commit `d00b6c9` on branch `QGP-USP` of
  `IFUSP-Heavy-Ions/hadronic_afterburner_toolkit`).
- **Boost-invariant dN/dy must not be cut in rapidity.** For (2+1)-d runs the density is flat and
  `dN/dy = N(all particles)/(y_RB - y_LB)`. The toolkit's `dN_ev_avg = Q0/N_events/(rap_max-rap_min)`
  computed on a cut window loses the daughters that decayed outside it and is biased low (0.7 % at
  ±4, worse toward the edge). `dNdy_normalization_width` switches to the no-cut estimator and is
  derived from `iss_dict` only when `music_dict['boost_invariant'] == 1`; it must stay 0 for
  (3+1)-d runs. The `9999`/`99999` references use pseudorapidity and never get it.
- **Batch augmentation is event-id based and already wired: batch k uses ids
  `[k*B, (k+1)*B-1]` via `-event_start_id` (the 6th job argument, `eventOffset` in
  `run_singularity.sh`).** Batch 1 is 0..1999. New ids are new events (freeze-out seed
  `default_rng([seed_add, event_id, iev])`, nucleon-pool address from the id, TRENTo seed
  `event_id+1`) and the same id is the same event at every design point. Since batch 1's
  archives are named `spvn_results_<Process>.tar.gz`, later batches carry a tag: batch 2
  submits with `-event_start_id 2000` and produces `spvn_results_e2000_<Process>.tar.gz`
  plus `events_drawn_e2000_<Process>.csv` (the generator and the worker packing script both
  derive the tag from the offset; batch 1 stays untagged for compatibility). In the merged
  h5 nothing is ambiguous anyway: groups are named by global event id
  (`spvn_results_2000`...), so a batch is `2000 <= id <= 3999` regardless of file names.
  `audit_event_losses.py` accepts the optional tag; `--blocks` must become 300 for a
  three-batch design point.
- **An event's initial state depends on its id alone; its particle sample, until now, also on its
  job.** The nucleon pool address depends only on `event_id` and the TRENTo seed is `event_id + 1`
  (`seed_add` enters the 3D-Glauber path and is a campaign constant, `CAMPAIGN_SEED_ADD = 0`; it
  used to be drawn at random per submission, which silently gave every design point a private
  event set). The iSS and analysis seeds are different: `generate_jobs.py` writes them once per job
  folder from the id the folder *starts at*, and `run_afterburner.sh` adds only the sub-event and
  oversampling indices (`$SubEventId` is the `UrQMDev_<n>` index, not an event id). So all events of
  a job share one particle-sampling seed, and an event's seed depends on its job's block of ids.
  That is harmless while every design point uses the same block layout, and it is why
  `scripts/rerun_events_local.py` rebuilds the block (`--per-job`). In event-list mode the driver
  resets both seeds per event (`pin_event_seeds`) to a function of the event id.
- **`b_max` is per design point on purpose; do not "simplify" it to a campaign constant.** It is
  computed from `WS_radius`, `WS_diffusiveness`, `nucleon-width`, the 2-sigma deformation and (since
  campaign 2) TRENTo's sigma_NN (+ sqrt(sigma_NN/pi) - sqrt(4.23/pi), zero at 200 GeV), so a
  larger nucleus draws a proportionally larger `b`. That is what keeps `b/b_max` — not `b` — the
  synchronised variable between design points: the same event index at a bigger `WS_radius` stays at
  the same centrality instead of drifting more central. Fixing `b` in fm instead would *reduce* the
  cancellation of statistical error between design points.
- **`events_drawn.csv` records every drawn event, including the ones that never collide.** TRENTo
  returns `mult = 0` when two randomly oriented deformed nuclei miss each other, and such an event
  produces no `spvn_results`, so without this file it is invisible downstream and the merged HDF5
  just has fewer rows than were requested. The CSV (`event_id, b, b_max, b_over_bmax, mult, status,
  seed_add`) is rewritten per event, keyed by event id, so the adaptive-grid rerun cannot duplicate
  rows. Centrality percentiles need the count of failures, not only the count of survivors.
- **`Initial_profile 92` threw the free-streaming flow away; 9 keeps the full T^munu.** Until
  `d365f42` `connect_trento_event` wrote only the Landau-matched e, so hydro started at rest
  and lost ~17% of the energy (tau_fs 0.93); the first zr96/ge76 campaigns ran that way. The
  table now always carries e, u^mu and pi^munu and `Initial_profile` picks what MUSIC uses
  (92 is bit-identical to before). Two traps if you touch the writer: MUSIC reads the SLOW
  table index as x while the arrays keep TRENTo's rows = y (components are written in
  MUSIC's frame), and MUSIC reads pi in 1/fm^4 but e in GeV/fm^3.
  `scripts/check_freestream_table.py` checks all of it.
- **The MC_sampling 4 sampler clamps the linear delta f to [-1, 1].** iSS's FSSW accepts a
  momentum with probability (1 + delta f)/2 clipped to [0, 1]; `restrict_deltaf` and
  `deltaf_max_ratio` are read only by the older samplers and do nothing here. With
  pi/(e+P) ~ 0.1 at freeze-out (eta/s ~ 0.35 at T_f, e.g. zr96 dp0583) the CE delta f
  exceeds 1 for most of the emission above 1 GeV and the result is the clamp (single-cell
  closure: CE reproduces 64% of pi at pi/(e+P) = 0.15). `deltaf_model 1` (PTB,
  commit `77d8a3e` on branch `QGP-USP` of `IFUSP-Heavy-Ions/iSS`) is positive definite and reproduces pi to 5% there;
  `deltaf_model 0` is byte-identical to the upstream sampler.
- **One particlization per delta f model, one h5 per event.** With
  `control_dict['deltaf_models']` the driver runs iSS + decays + analysis once per model on
  the same surface and seeds, and `spvn_results_<id>.h5` holds each model's tables in
  `deltaf_<name>` (hydro-level files stay at the top; attrs `deltaf_models`,
  `toolkit_pT_min/max`, `toolkit_npT`). Readers must pick a model; `merge_dp_h5.py` copies
  sub-groups and attributes (before `e4ffea5` it silently dropped both). analysisKit still
  expects the flat layout.
- **Toolkit pT bins are edges pT_min + i (pT_max - pT_min)/npT** (`single_particleSpectra.cpp`:
  dpT = (pT_max - pT_min)/npT, centre pT_min + (i + 0.5) dpT). The first campaigns' 0.2-2.0 /
  41 gave 0.0439 GeV bins; the campaign2 template uses 0-5 GeV / 100 (0.05 GeV edges).
- **Decays-only yields before iSS pin `67f4a4f` are ~2 % low.** iSS's decayer handled only
  two- and three-body channels and silently dropped the mother for anything else: the 21
  four-body channels and the 45 channels the UrQMD table marks closed at the pole masses
  (negative daughter count). Measured on the one-cell test surface: π± −2.1 %, K −1.3 %,
  p −1.1 %, Λ −0.75 %, each matching the analytic feed-down of the dropped channels. Every
  decays-only campaign so far (zr96/ge76 campaigns 1 and 2) has it; flow coefficients are
  barely affected, yields and ratios are. The fixed decayer honours the table's branching
  ratios (closed channels opened through the daughters' Breit-Wigner tails, see
  `docs/chain.md`), and was checked against exact phase-space marginals (3-5 bodies), the
  analytic feed-down of every species of both lists, and exact E, p, Q, B, S conservation.
- **`iss_dict['particle_list'] = 21` (PDG2021+) needs a matching EoS.** The list is fetched at
  build time (GPL-3; never commit `pdg-PDG2021Plus.dat` or the SMASH files). EoS 9/91 come
  from other hadron lists, so particlization with PDG2021+ is slightly inconsistent unless the
  EoS is built from PDG2021+ (an `eos_dict` run with `particle_list = 21` does that). With SMASH the master now keeps
  `EOS_to_use 24` instead of forcing 91.
- **`MUSIChydro`'s md5 changes with every framework commit, even at the same MUSIC pin.**
  `get_code_packages.sh` deletes each component's `.git`, and MUSIC's CMake stamps
  `git log -1` into the binary (`GIT_COMMIT_HASH`), so it finds the framework repository and
  stamps the framework's HEAD. Images 8a7294f and 5a970cd (same MUSIC d1323e8) differ in
  exactly that 40-character string and the 20-byte build ID; hydro output is bit-identical.
  Compare MUSIC binaries with those two ranges masked, or compare outputs, not md5s.
- **Test framework changes in the image before building one.** `scripts/rerun_events_local.py`
  re-runs any campaign event in the job folder it originally ran in (same seeds); `--bind`
  mounts a modified file (driver, generate_jobs, master, a patched iSS.e) over the image's,
  `--set` appends parameter overrides. Local reruns are deterministic; across machines the
  initial state and hydro agree but iSS samples can differ (see Reproducibility above).

## Style

YAPF only, google-based, configured in `.style.yapf` (2-space before comments, split before
arithmetic/logical operators). Run `./formatCode.sh` before committing; it formats the repo root and
`analysisKit/` to depth 2 and silently no-ops if `yapf` is not installed. Match the surrounding
spacing of generated files rather than reformatting them wholesale — many are machine-generated with
odd indentation.