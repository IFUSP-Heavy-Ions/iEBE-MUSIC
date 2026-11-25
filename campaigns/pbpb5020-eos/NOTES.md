# pbpb5020-eos (draft, in preparation)

Pb-Pb at 5.02 TeV with every model parameter fixed and only the equation of
state varied. This is the first test of the EoS machinery
(`codes/eos_builder`), of importance sampling to the most central events, and
of the HBT sums together. It is meant mainly for closure tests and
sensitivity studies; no second system (2.76 TeV for 3D HBT radii) for now.

## Fixed parameters

These are the JETSCAPE MAP of arXiv:2011.01430 (Table 2, Grad column: combined
RHIC + LHC fit). `template_pbpb5020.py` holds them.

| | value | note |
|---|---|---|
| TRENTo p, sigma_k, w | 0.063, 1.05 (k = 0.907), 1.12 fm | |
| N[5.02 TeV] | 19.6 | tuned to ALICE dN_ch/deta 0-5% (1943 +- 54). N = 20.0 gave 1956 +- 47 over 12 events evenly in 0-5% (lattice EoS, decays only), and SMASH adds about 1.7%; 19.6 absorbs that (the MAP gives 14.2 at 2.76 TeV only) |
| sigma_NN | 7.0 fm^2 | conventional TRENTo value at 5.02 TeV |
| nuclei | 208Pb, R = 6.62 fm, a = 0.546 fm, spherical | Isobar-Sampler |
| nucleon hard core | 0.8 fm (correlation strength -1) | JETSCAPE's d_min = 1.44 fm is weakly constrained; user's choice |
| free streaming | 1.5 fm, constant | JETSCAPE: tau_R (eps/eps_R)^alpha, tau_R = 1.46 fm, alpha = 0.031 |
| eta/s | T_eta 0.223 GeV, a_low -0.776/GeV, a_high 0.37/GeV, (eta/s)_kink 0.096 | MUSIC option 3, same form |
| zeta/s | max 0.133, T_zeta 0.12 GeV, w_zeta 0.072 GeV, lambda -0.122 | MUSIC option 3 is the same skewed Cauchy |
| b_pi | 4.65 | shear_relax_time_factor |
| T_sw | 0.136 GeV | hadron gas anchored here (SMASH list) |
| afterburner | SMASH | |
| delta f | one variant, "Grad": deltaf_model 0, bulk_deltaf_kind 20, RegVisYield 1 | iSS 22-moment (WSU, NEoS-BQS coefficients); the viscous yield of each species in a cell is capped at 2 N_eq, as JETSCAPE regulated |delta f| <= f_eq |
| b_max | 14.69 fm | MakeDictionaries' formula at sigma_NN 7.0 |
| hydro grid | +-20 fm, 0.2 fm cells, fixed | the adaptive grid was fitted for Zr with a fixed EoS |
| HBT | on (`control_dict['hbt'] = True`) | |

## Equation of state

The prior is in `eos_prior_spec.json`:
- a GP for phi = ln(1/c_s^2 - 1) with its kernel in ln T (l = 0.4) and sigma_phi = 0.6;
- constant mean c_s^2 = 0.22 on 0.13-0.6 GeV;
- 4 KL modes (99.2% of the prior variance);
- above 0.6 GeV, a relaxation to 1/3 over 0.2 GeV, with tables to 5 GeV.

The lattice (WB) c_s^2 sits at |z| <= 1, and 4 modes reproduce it to rms 0.007
(worst 0.023, at the 150 MeV dip).

Design: maximin in Gaussian-quantile space (mildly truncated), not the box
[-2,2]^4. The box corners are 4 sigma out and extremely soft or stiff.

Lattice reference (the template's default `eos_dict`, and the truth for
closure tests):
- below 240 MeV, the user's WB jackknife mean (~/cs2_WB.dat: 120-260 MeV,
  mean, error, 48 samples);
- above 270 MeV, the WB 2014 trace-anomaly parametrization (PLB 730 (2014) 99),
  blended in between;
- the high_T relaxation above 1.5 GeV.

The parametrization's coefficients were taken from memory. They agree with the
jackknife data within about 1 sigma above 180 MeV, but should be checked
against the paper. The data file `lattice_cs2_WB_blend.dat` is not in git
(the user's data).


## Delta f: why not iSS's 14-moment option (2026-11-24)

Context: the Grad MAP's zeta/s is still about 0.125 at T_sw = 0.136 GeV
(T_zeta 0.12, w_zeta 0.072), so the freeze-out surface carries a large bulk
pressure. In central events Pi/(e+P) averages -0.06, from -0.17 to +0.12.
The positive values are the cells frozen at tau_0, which carry free
streaming's e/3 - P(e) but only 0.6% of the emission.

Test: event 3729's surface (b = 0.8 fm, lattice EoS, N = 17.2) re-sampled
with each iSS setting.

| iSS setting | charged/unit y vs no delta f | <pT>_ch | p/pi+ |
|---|---|---|---|
| no delta f | x1.00 | 0.685 | 0.034 |
| 14-moment, bulk_deltaf_kind 11 (OSU tables) | x138 | 0.732 | 0.058 |
| kind 11 with RegVisYield 1 | x1.65 | 0.728 | 0.043 |
| 22-moment, kind 20 (campaign 2's Grad22) | x1.04 | 0.636 | 0.065 |
| kind 20 with RegVisYield 1 (this campaign) | x1.01 | 0.622 | 0.060 |
| Chapman-Enskog, kind 21 | x1.01 | 0.623 | 0.069 |
| PTB | x1.24 | 0.506 | 0.038 |

A negative Pi should lower <pT> and raise heavy-particle fractions, at
nearly the same yield. Kinds 20 and 21 do exactly that. Kind 11 raises
<pT> and multiplies the yields, and without the cap the most central events
came out 20-140 times too large. So kind 11 is wrong in this iSS (a sign,
unit or table-convention error); no campaign has used it.

## Cross section (2026-11-24)

From `scripts/cross_section/xsec_point.py`, n_conf 600:
- sigma_inel = 908.2 +- 0.7 fm^2; TRENTo brute force gives 911.6 +- 3.6.
- 74.6% of it is below b_max = 14.69 fm. Importance sampling must use
  coverage 0.746.
- No event beyond b_max reaches the 60% multiplicity threshold (tail share
  0); at 70% the share is 1.2%, at 80% 7.8%. So 0-60% is complete.

## SMASH sampled-rapidity scan (2026-11-24)

Three central events (708, 2452, 3019), N = 20.0, lattice EoS, Grad, HBT on,
image full-44d5e53, iSS sampled range y = +-2.5, +-3.5, +-4.5.

- In the summed window (sampled range minus 1.25), dN_ch/deta is 1961-1967:
  about 1.7% above decays only on the same events.
- Up to |y| = range - 1.25, the charged dN/dy is flat within about 1% and
  <pT> within 0.4% (0.5-unit bins of y_profile).
- The freeze-out surface reaches r = 13-15 fm, inside the +-20 fm box.
- Time per central event: 1523-1594 s (+-2.5), 1711-1804 s (+-3.5),
  1796-1897 s (+-4.5). MUSIC takes 265-278 s of it.
- iSS's `number_of_particles_needed` = 100000 gave 41 samples per event. It
  counts per unit rapidity (samples = needed / (6 dN/dy of thermal pi+)), so
  the sample count does not depend on the sampled range.
- SMASH runs about 27 s per sample at +-2.5 and 34 s at +-4.5: 90% of the
  time per event.

SMASH stops at End_Time = 100 fm/c (lab time). In the +-4.5 runs, about
5,800 particles per sample were still unformed (t = tau cosh eta_s >
100 fm/c) when it stopped; in the +-2.5 runs, about 290. Those particles
never rescatter. The charged plateau above is not sensitive to that; see
the next section.

## SMASH End_Time and the rapidity window (2026-11-25)

Event 2452, sampled +-4.5, the same 10 iSS samples run through SMASH twice:
End_Time 100 with fixed 0.1 fm/c steps (the default), and 400 fm/c with no
time steps (Time_Step_Mode None). Ratios 400/100, 0.5-unit bins of |y|:
- Charged particles: dN/dy and <pT> agree within 0.4% at every |y| up to 4.5.
- Pions: within about 1% up to |y| = 2.5, then <pT> 1.3-1.6% lower at 2.5-3.5.
- Protons and antiprotons, 2 < |y| < 3.5: <pT> 5-16% higher, yields 5-10%
  lower. This is the pion-wind and annihilation rescattering that stops at
  100 fm/c.
- At |y| < 2: no difference beyond the noise of 10 samples (about 5% for
  protons).

That matches tau cosh eta_s = 100 fm/c: rescattering up to tau = 26 fm is
contained at |eta_s| < 2.

A third run kept the fixed 0.1 fm/c steps and moved only End_Time to 400:
- |y| < 2: again nothing beyond noise (proton <pT> ratios 0.99-1.01, pions
  within 1%).
- 2 < |y| < 3.5: p, pbar and Lambda <pT> are 8-12% higher, kaons 3-5%.
So the effect is the end time, not the time-step mode.
- End_Time 400 with fixed steps costs about 12 min per sample, against
  0.5 min at 100, so it is out.
- Time_Step_Mode None at 400 fm/c costs about 1.8 times the default per sample.

Choice: keep End_Time 100, sample y over +-3.25, and sum every observable,
HBT included, over |y| < 2 (afterburner_y_cut = range - 1.25; hbt
{'y_cut': 2.0}).

## Oversampling (2026-11-25)

How the chain oversamples:
- run_afterburner.sh ran iSS 10 times per hydro event (hard-coded), and the
  master divided number_of_particles_needed by 10.
- Each iSS run draws max(1, int(N/10/(6 dN/dy of thermal pi+))) samples.
- So every event got at least 10 samples; a central event got 40 at N = 1e5.
- The loop count is now control_dict['iss_calls'] (default 10, unchanged).

For <pT>, integrated flow and 4-particle cumulants the event-by-event
fluctuations dominate once an event has M particles with M v_n^2 well
above 1.
- One central sample has about 9000 charged particles in |y| < 2:
  M v3^2 = 5.6 for v3 = 0.025.
- <pT> noise per sample is 0.8%, against dynamical fluctuations of about 1%.
- With hydro about 6 min and SMASH about 30 s per sample, the optimum is
  2-5 samples per central event.

Template: iss_calls 1, number_of_particles_needed 10000. Measured, with
the machine loaded:

| event | samples | wall time | SMASH per sample |
|---|---|---|---|
| 2452 (central) | 4 | 7.6 min (was about 30) | 29 s |
| 1707 (55%) | 60 | 5.5 min | 2 s |

SMASH's cost scales with the particle count, so peripheral events, which
get more samples, cost no more than central ones.

## Centrality: where the knee is (2026-11-25)

40,000 TRENTo events at b < 4 fm (5.53% of sigma_inel), plus the
minimum-bias draws for b > 4:
- At b < 0.5 fm the multiplicity fluctuates by sigma/m = 5.0% (skew +0.16).
- The knee, the mean multiplicity at b = 0, sits at 0.57% centrality.

Bin edges, in sigma above the knee:

| centrality | 2.5% | 1% | 0.5% | 0.2% | 0.1% | 0.02% | 0.005% | 0.001% |
|---|---|---|---|---|---|---|---|---|
| (N - m0)/sigma | -1.9 | -0.55 | +0.1 | +0.8 | +1.2 | +2.0 | +2.6 | +3.2 |

These are for TRENTo's own multiplicity. A final-state, finite-resolution
estimator such as V0M makes the experimental bins less extreme, so the
selection density should be smooth, with no cliffs at bin edges.

## Importance sampling (user's decision, 2026-11-25)

Targets:
- equal statistics in each 1% bin of 0-5%, for v_n{4};
- the ALICE v_n{2} nested bins 0-0.005, 0-0.02, 0-0.2, 0-1, 0-2.5 and 2.5-5%,
  with fewer events in the narrowest;
- coverage between the knee and 0.005% for the <pT> slope;
- wider bins beyond 5%.

Density of simulated events per percent of centrality (`make_selection.py`,
mode "curve"):
- 1-5%: N1 = 5000 per 1% bin (the user's choice);
- below 1%: N1 (c/1%)^-1/2;
- 5-60%: 1500 per wide bin;
- beyond 60%: 10 per percent;
- geometric tapers over 5-6%, 10-11% and 60-65%.

It assumes 15 million drawn events below b_max (coverage 0.746). Below
0.0006% every drawn event is simulated.

Cost of the draws:
- On one core, the hard-core nucleon sampler takes 184 ms per Pb nucleus
  locally (0.4-0.6 s per event with two nuclei on OSG cores), against 6 ms
  for TRENTo.
- With two fresh nuclei per event, 15M draws would be about 7,500
  CPU-hours. A first OSG run (cluster 16215973) was stopped and removed
  before any block finished.

At the user's request the campaign now reuses nuclei from a pool:
- control_dict['nucleus_pool_size'] = 2^18. Event q 2^18 + r takes target
  slot r and projectile slot (r + q) mod 2^18; TRENTo rotates every use at
  random, seeded by the event id.
- Draws: q < 58, ids [0, 15,204,352). event_selection.json is made for that
  count.
- 128 OSG jobs of 2048 slots (draw_events.py --pool-slots), about 130
  CPU-hours.
- Each configuration serves about 58 events. In 0-0.005% (585 events, 1170
  nucleus slots out of 524,288) about one configuration appears twice, each
  time with its own orientation and partner.

Tested exactly, in the image, with M = 64:
- With no pool the draws equal the earlier ones bit for bit.
- Pooled ids below M equal the no-pool events.
- Id-block and slot-mode draws agree.
- The chain's run_trento.sh regenerates reused-nucleus events (70, 150,
  and 127, which wraps around the pool) with identical b, npart, mult and
  entropy.
- The OSG smoke test of the id-block draws reproduced local draws bit for
  bit.
TRENTo is the same at every design point, so the draws, the calibration and
the accepted list are made once and shared.

| bin | events | effective (weights) |
|---|---|---|
| 0-0.005% | 583 | 520 |
| 0-0.02% | 1,292 | 1,060 |
| 0-0.2% | 4,357 | 3,362 |
| 0-1% | 9,896 | 7,516 |
| 0-2.5% | 17,395 | 14,431 |
| 2.5-5% | 12,500 | 12,500 |
| each of 1-2, ..., 4-5% | 5,000 | 5,000 |
| 0.005-0.57% (knee region) | 6,859 | 5,581 |
| 5-10% | 2,917 | 1,734 |
| each of 10-20, ..., 50-60% | about 1,500 | about 1,500 |
| 60-100% | 615 | 436 |
| total | 40,740 | |

## Design (2026-11-25)

There are 50 training points and no held-out validation set. That was the
user's decision, because simulation compute is the bottleneck. The emulator
is validated by leave-one-out and leave-a-block-out cross-validation.
- `design.csv` is a maximin Latin hypercube in Gaussian-quantile space of
  the 4 KL coordinates (alpha 0.01, so |z_k| <= 2.33):
  `make_eos_design.py --n 50 --seed 1 --iters 60000`.
- Seeds 1-10 are all equivalent (median gap from a prior draw to its nearest
  point 0.233 in u). Seed 1 has the smallest worst-case gap (0.472).
- The lattice truth runs once more on the same events, for the closure test.
  It is not a training point.
  - Lattice z = (-0.80, 0.49, 0.40, 0.85), |z| = 1.32.
  - Its nearest design point is 0.243 away in u, a typical gap, so the
    closure test is not flattered by a neighbour.
  - 4 modes miss the lattice c_s^2 by at most 0.027 above T_sw (at the
    150 MeV dip); the larger miss below T_sw never enters the hydro.

Budget: 51 runs x 40,740 events x about 7 min = about 240,000 CPU-hours.

## Status

- [x] template written
- [x] draws work: 110 ms per event at A = 208
- [x] N[5.02 TeV] = 19.6 (20.0 decays only, minus SMASH's +1.7%)
- [x] cross section and b_max coverage (0.746 of sigma_inel below b_max; 0-60% complete)
- [x] SMASH sampled-rapidity scan; timing, grid extent
- [x] SMASH End_Time (100 fm/c) vs the forward rapidities: window |y| < 2, range +-3.25
- [x] oversampling: iss_calls 1, N 10000 (4 samples central)
- [x] importance-sampling allocation (N1 = 5000), event_selection.json
- [x] design: 50 points (seed 1), design.csv
- [x] image iebe-music_full_ca8b92d_0783f574.sif (md5 0783f574...), published on OSDF;
      reference runs bit-identical to d7a76b0, Pb-Pb pool template = timing runs
- [x] pooled draws: 15,204,352 ids, 128 OSG jobs (cluster 16216036), 0.84 h mean,
      2.0 h max, 293 MB max; /data/mluzum/pbpb5020_eos/draws_pool
- [x] shared selection list: 40,723 events, every bin within Poisson of the
      allocation table; /data/mluzum/pbpb5020_eos/selection_v2/sel.{csv,json,npz}.
      The first attempt (selection/) starved 0-0.2% (2 events in 0-0.005%
      instead of 585): the calibration table had no knots below 0.037%.
      Fixed in codes/event_selection.py (geometric knots in the top 1%).
- [x] dictionaries: /data/mluzum/pbpb5020_eos/dps (DesignPoint1-50, and
      DesignPoint51 = the lattice truth, DesignPoint1 with the lattice eos_dict)
- pilot: dp 39 (softest, <c_s^2> 0.093 over 0.15-0.3 GeV), dp 19 (stiffest,
  0.459) and the lattice (0.234), about 40 events each across centrality
- [ ] OSG pilot: SIF from d7a76b0, a few design points
