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
| N[5.02 TeV] | tuned here | the MAP gives 14.2 at 2.76 TeV only |
| sigma_NN | 7.0 fm^2 | conventional TRENTo value at 5.02 TeV |
| nuclei | 208Pb, R = 6.62 fm, a = 0.546 fm, spherical | Isobar-Sampler |
| nucleon hard core | 0.8 fm (correlation strength -1) | JETSCAPE's d_min = 1.44 fm is weakly constrained; user's choice |
| free streaming | 1.5 fm, constant | JETSCAPE: tau_R (eps/eps_R)^alpha, tau_R = 1.46 fm, alpha = 0.031 |
| eta/s | T_eta 0.223 GeV, a_low -0.776/GeV, a_high 0.37/GeV, (eta/s)_kink 0.096 | MUSIC option 3, same form |
| zeta/s | max 0.133, T_zeta 0.12 GeV, w_zeta 0.072 GeV, lambda -0.122 | MUSIC option 3 is the same skewed Cauchy |
| b_pi | 4.65 | shear_relax_time_factor |
| T_sw | 0.136 GeV | hadron gas anchored here (SMASH list) |
| afterburner | SMASH | |
| delta f | one variant, "Grad": deltaf_model 0, bulk_deltaf_kind 11 | iSS 14-moment; with SMASH it loads the smash_box coefficients |
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

## Status

- [x] template written
- [x] draws work: 110 ms per event at A = 208
- [ ] N[5.02 TeV] tuned to ALICE dN_ch/deta (0-5%: 1943 +- 54) with the lattice EoS
- [ ] cross section and b_max coverage
- [ ] SMASH sampled-rapidity scan; timing, grid extent, oversampling count
- [ ] design generator, importance-sampling bins, OSG pilot
