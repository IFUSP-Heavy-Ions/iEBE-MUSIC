# Standard per-event output (draft, format version 1, 2D)

**Status:** layout agreed with the soft-sector analysis
(`soft-sector-data-curation`; its reader will live in `soft-sector-sim-adapters`)
on 2026-11-20. Written by `codes/standard_output.py` (called from the driver,
settings in `control_dict['standard_output']`, `afterburner_y_cut`,
`afterburner_edge_margin`) and merged by `scripts/merge_qn.py`.

The goal is one output that serves the decays-only path, UrQMD and SMASH alike,
carries the exact sums the analysis needs (instead of tables it has to rebuild
Q-vectors from), and reads fast for ~10^7 events. It replaces, once validated,
the `hadronic_afterburner_toolkit` tables in `spvn_results_<id>.h5` and the
`.npz` of `codes/analysis_cli_optimized.py`. Files already written in the old
layouts (zr96-c2 and earlier) are not touched; the adapter keeps reading them.

This version covers boost-invariant (2+1)-d runs. 3D is reserved (last section).

## 1. What is summed

For each event, each delta f variant, each species row and each pT bin, over
every particle of every oversampled particlization of that event that passes
the collection rule (section 3):

| quantity | definition |
|---|---|
| `Q[..., 0, :]` | number of particles (real part; imaginary part 0) |
| `Q[..., n, :]`, n = 1..10 | sum of exp(i n phi), up to the row's `species_nmax` |
| `ptsum[..., k-1, :]`, k = 1..4 | sum of pT^k [GeV^k] |
| `mtsum` | sum of mT = sqrt(pT^2 + m^2) [GeV] |
| `Qpt[..., n-1, :]`, n = 1..3 | sum of pT exp(i n phi) [GeV] |

`/grid/species_nmax` is the highest harmonic stored for each row: 10 for every
charged row (all charged hadrons are their sum) and 6 for Lambda, anti-Lambda,
K0 and anti-K0. **Entries of `Q` above a row's `species_nmax` are not stored:**
the file holds zeros there, which must be read as a missing harmonic, never as
Q_n = 0.

Sums are raw: not divided by the number of oversamples or by any width.
Accumulation is in float64; storage is complex64 / float32 (counts are exact
below 2^24 per cell).

**Species rows** (`/grid/species_pdg`, with `/grid/species_mass` and
`/grid/species_charge`), 15 disjoint rows: pi+ 211, pi- -211, K+ 321, K- -321,
p 2212, pbar -2212, Lambda 3122, anti-Lambda -3122, Xi- 3312, anti-Xi+ -3312,
Omega- 3334, anti-Omega+ -3334, K0 311, anti-K0 -311, and **0 = other
charged**: every charged final particle not in another row (Sigma+-, their
antiparticles, light nuclei if a code makes them, anything else). All charged
hadrons are the sum of the rows with non-zero `species_charge`, exactly. Each
row is cut in eta with its own mass (the y -> eta Jacobian); the other-charged
row is Sigma-dominated and about 1-2 % of charged, and its mass is recorded as
the Sigma+ mass, 1.1894 GeV. The masses of the named rows are those of the
particle table the code used.

**pT bins** (`/grid/pt_edges`, GeV): 0 to 3 in steps of 0.05 with an extra edge
at 0.27, then 3 to 5 in steps of 0.25, then one bin 5 to 10. 70 bins. Particles
above 10 GeV are not summed. The edges are written as the float64 values of
those decimals (not accumulated steps), and the code bins on exactly the array
it writes. The cuts in use (0.15, 0.2, 0.27, 0.3, 0.4, 0.45, 0.5, 2, 3, 4.5, 5)
are all edges.

**Final state.** Hadrons stable under strong and electromagnetic interactions,
no weak decays: K0 and anti-K0 are stored as such (K0S = half their sum), and
Lambda, Sigma+-, Xi, Omega are final, as in the experiments' primary-particle
definition. The decays-only path already does this. **SMASH and UrQMD do not
quite:** they end with eta and Sigma0 undecayed (per unit rapidity in a central
zr96-c2 event: about 12 eta and 1.2 Sigma0 against 230 charged hadrons and
3 Lambda). Without those decays charged hadrons are about 3 % low and Lambda
about 30 % low (Sigma0 -> Lambda gamma). `codes/standard_output.py` decays them
after the cascade, before summing, with the channels of iSS's
`pdg-urqmd_v3.3+.dat` (phase space, seeded by event id and variant); the number
done is the variant attribute `end_decays`. phi decays before it can be counted
on every path; it is not a row in version 1.

## 2. File layout

The worker writes one file per event, `qn_<event_id>.h5`, with exactly the
layout below and an event axis of length 1. The merger concatenates them along
the event axis, sorted by event id, into one file per design point,
`qn_dpNNNN.h5` (a new name, so that no reader of the old `dpNNNN.h5` mistakes
one for the other). Every dataset with an event axis has it first, chunked by
128 events, gzip level 1 with shuffle.

```
/                      attrs: format = "iebe-music-qn", format_version = 1,
                              mode = "2D", variants = "Grad22,CE,PTB" (order kept),
                              afterburner = "decay" | "UrQMD" | "SMASH",
                              chain_revision, parameter_file, b_max, master_seed,
                              n_events (rows), n_drawn, n_collided,
                              n_no_collision (from /drawn; with a selection,
                              the selection's counts),
                              + the selection-format-1 attributes when the
                              campaign is importance-sampled (section 5)
/grid/
    pt_edges           [71]           float64
    species_pdg        [15]           int32   0 = other charged
    species_mass       [15]           float64 GeV
    species_charge     [15]           int32
    harmonics          [11]           int32   0..10 (Q); Qpt carries 1..3
    species_nmax       [15]           int32   highest stored harmonic per row
    y_profile_edges    [ny+1]         float64
/events/               one row per collided event that reached particlization
    event_id           [E]   int64    global event id (common random numbers)
    status             [E]   uint8    0 ok, 2 no_surface (see section 4)
    weight             [E]   float64  1/P with importance sampling, else 1
    p_acc, centrality, estimator
                       [E]   float64  selection values, NaN without selection
    b                  [E]   float32  impact parameter [fm]
    mult               [E]   float32  TRENTo total (the selection estimator)
/hydro/                MUSIC's per-time tables, the rows as MUSIC writes them
                       (columns in the attrs columns_<name>); NaN where an
                       event froze out before a time was reached
    tau                [E, T]
    ecc_ed             [E, T, 12]     eta_s, integral of e, then (cos, sin) of
                                      ecc_n for n = 1..5 (MUSIC's own header
                                      says n = 1-6; the rows hold 1..5)
    ecc_nB, ecc_nQ     [E, T, 12]     the same for n_B and n_Q
    momentum_anisotropy[E, T, 7]      eta_s, then ideal, shear, full: (cos, sin)
    meanpT_estimators  [E, T, 5]      eta_s, dS/deta, dE/deta, [s], [r^2]
/drawn/                one row per drawn event id of this design point,
                       including no_collision and failed (replaces csv.tgz and
                       selection_dpNNNN.csv)
    event_id, status, b, b_over_bmax, mult, weight, p_acc, centrality,
    estimator, u, selection_check      (attr status_codes: the codes below)
/deltaf_<name>/        one group per delta f variant, same event rows as /events
    attrs: iss_overrides (as in campaign 2), bulk_deltaf_kind, deltaf_model,
           deltaf_newRTA_gamma (effective values, always written),
           y_sampled = [y_LB, y_RB], collection = "all" | "window",
           y_cut, dy_width (section 3), sums = "raw over nsamples"
    nsamples           [E]                 int32
    Q                  [E, 15, 11, 70]     complex64
    ptsum              [E, 15, 4, 70]      float32
    mtsum              [E, 15, 70]         float32
    Qpt                [E, 15, 3, 70]      complex64
    y_profile          [E, ny, 4]          float32   charged: N, sum pT,
                                                     Re and Im of sum exp(2i phi)
```

Without `control_dict['deltaf_models']` there is one variant, `deltaf_default`.
The `Q` axis order (event, species, harmonic, pT) is the adapter's
`QVectorData` order.

Size per event and variant, uncompressed: about 140 kB (Q 92 kB, Qpt 25 kB,
ptsum 17 kB, the rest 6 kB). Three variants: 420 kB per event, against 253 kB
for campaign 2's merged files; one variant of a 20,000-event design point is
2.8 GB in memory.

## 3. Rapidity: what the sums cover

`nsamples` is the number of oversampled particlizations of the event; each
covers the sampled rapidity range `y_sampled`. The number of particles per unit
rapidity is `Q[..., 0, :] / (nsamples * dy_width)`, and the particles are flat
in y over the width `dy_width`, which is what the adapter's `rap_max` means
(`rap_max = dy_width / 2`).

* **Decays only** (`collection = "all"`): every final particle is summed,
  whatever its rapidity, and `dy_width = y_RB - y_LB`. In a boost-invariant
  sample the daughters that leave the range are replaced on average by those
  that enter it, so no edge correction is needed; this is the estimator the
  campaign-2 `_boostinv` tables already use.
* **UrQMD, SMASH** (`collection = "window"`): only particles with
  |y| < `y_cut` are summed, and `dy_width = 2 y_cut`. The cascade is 3+1-d, so
  particles near the ends of the sampled range miss collision partners. Measured
  for zr96-c2 (UrQMD, 176,000 cascade events,
  `docs/notes/afterburner_rapidity_window.md`): yields and
  <pT> of charged hadrons are within 0.2 % of the plateau beyond 1.25 units
  from the edge and within 0.05 % beyond 1.5; v2 and v3 agree with the plateau
  to 1-2 % beyond 1 unit. Cascade time grows like N^1.5 to N^1.9, so the
  sampled range has an optimum: for Zr+Zr, usable particles per CPU second
  peak for a sampled width of 6-8 units. **Default for Zr+Zr:**
  `y_sampled = [-3.5, 3.5]`, `y_cut = 2.25`. Other systems need their own scan
  (Pb+Pb has six times the particles).

`y_profile` (charged hadrons, bins of 0.5 in y over the sampled range plus one
unit on each side) is stored for every event so that the plateau can be checked
in any campaign rather than trusted.

## 4. Event status

`/events` holds the collided events that reached particlization:

| status | meaning | rows in the variant groups |
|---|---|---|
| 0 `ok` | simulated | the sums, `nsamples` > 0 |
| 2 `no_surface` | collided, fireball never reached freeze-out | all sums 0, `nsamples` = 0: an event with no particles, with its weight |

`/drawn` lists every drawn id with its fate: 0 ok, 1 no_collision, 2
no_surface, 3 hydro_failed, 4 failed (nothing came back; re-run, never count
as empty). Only 0 and 2 appear in `/events`.

## 5. Importance sampling

The selection-format-1 contract (`docs/importance_sampling.md`) carries over
unchanged in content: root attributes `selection_format = 1`, `n_drawn`,
`n_collided`, `n_no_collision`, `n_accepted`, `covered_centrality`,
`selection` (the whole summary of `select_events.py` as a JSON string, as in
format 1). The per-event
weight and selection values are the `/events` datasets instead of attributes
of each event group, and `/drawn` replaces the selection csv. The minimum-bias
denominator remains `n_collided`, not the number of rows and not sum(weight).

## 6. Reproducibility

Every random stream depends only on `(master_seed, seed_add, event id,
oversample index)`. The cascades get the seed of the iSS call whose particles
they continue (`run_afterburner.sh`): SMASH through `Randomseed` in a per-run
copy of its config, UrQMD through `rsd`. UrQMD needs
`codes/patches/urqmd_fixed_seed.patch` for that: when it continues events read
from a file it reads `rsd` only after seeding itself from the clock, so before
the patch every run differed whatever `rsd` said (its event header then says
`(auto)`; with the patch `(fixed)`).

## 7. Validation before the toolkit tables are dropped

1. Decays only, campaign-2 reference events (dp 583, events 101, 140, 377):
   counts, <pT> and Q_n for n <= 5 from the new sums must equal the toolkit's
   `_boostinv` tables after summing bins (every edge above except 0.27 is an
   edge of the toolkit's 0-5 GeV / 100 grid).
2. UrQMD and SMASH: the window sums against a wide-window reference run, and
   the eta/Sigma0 decays checked against the decays-only path.
3. A test file through the new adapter reader and `check_sim_package`.

## 8. 3D (reserved)

Fully differential output for charged hadrons only, as
`/deltaf_<name>/Q3_ch [E, eta, pT, harmonic]` with `/grid/eta_edges` (at least
|eta| < 5.2, 0.1 wide), possibly with fewer harmonics and coarser pT forward;
identified particles reduced to what the data need. To be specified when the
first 3D campaign is planned.
