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
| N[5.02 TeV] | 20.0 | tuned to ALICE dN_ch/deta 0-5% (1943 +- 54): 1956 +- 47 over 12 events evenly in 0-5%, lattice EoS, decays only (the MAP gives 14.2 at 2.76 TeV only) |
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

## Status

- [x] template written
- [x] draws work: 110 ms per event at A = 208
- [x] N[5.02 TeV] = 20.0 (decays only; to be checked with SMASH)
- [x] cross section and b_max coverage (0.746 of sigma_inel below b_max; 0-60% complete)
- [ ] SMASH sampled-rapidity scan; timing, grid extent, oversampling count
- [ ] design generator, importance-sampling bins, OSG pilot
