#!/usr/bin/env python3
"""Pb-Pb 5.02 TeV, every parameter fixed at the JETSCAPE Grad MAP
(arXiv:2011.01430, Table 2; N[5.02 TeV] tuned here, the MAP gives 2.76 only)
except the equation of state, which each design point sets through eos_dict.

Departures from JETSCAPE, chosen by the user (campaigns/pbpb5020-eos/NOTES.md):
constant free-streaming time 1.5 fm (JETSCAPE: tau_R (eps/eps_R)^alpha with
tau_R = 1.46 fm, alpha = 0.031); nuclei from the Isobar-Sampler with a hard
core of 0.8 fm (correlation strength -1) instead of TRENTo's d_min = 1.44 fm;
delta f: iSS 14-moment (bulk_deltaf_kind 11, SMASH-box coefficients).
"""

control_dict = {   'initial_state_type': 'TRENTo',
    'walltime': '40:00:00',
    'afterburner_type': 'SMASH',
    'save_hydro_surfaces': False,
    'save_UrQMD_files': False,
    'deltaf_models': {'Grad': {'deltaf_model': 0, 'bulk_deltaf_kind': 11}},
    'hbt': True}

isobars_conf_dict_target = {   'isobar_samples': {   'description': 'Options for the isobar nucleon-position samples',
                          'number_configs': {   'description': 'Number of configurations to be '
                                                               'sampled.',
                                                'value': 1},
                          'number_nucleons': {   'description': 'Mass number A of the nuclei.',
                                                 'value': 208},
                          'seed_source': {   'description': 'Nucleon seeds: philox (deterministic '
                                                            'from master_seed and pool address) or '
                                                            'file (HDF5 pool).',
                                             'value': 'philox'},
                          'master_seed': {   'description': 'Master seed for the philox source. '
                                                            'Must never change once events exist; '
                                                            'recorded in EMULATOR_SWEEP_PLAN.md.',
                                             'value': 8675309},
                          'pool_modulus': {   'description': 'Size of the virtual nucleus pool, '
                                                             '2**32. Event g maps to addresses '
                                                             '(2g)*2654435761 and '
                                                             '(2g+1)*2654435761 mod this.',
                                              'value': 4294967296},
                          'output_path': {   'description': 'Output directory where to save',
                                             'dirname': 'nuclei_target'},
                          'number_of_parallel_processes': {   'description': 'Number of processes '
                                                                             'to compute in '
                                                                             'parallel.',
                                                              'value': -1}},
    'isobar_properties': {   'description': 'Nuclear properties of isobars to be sampled.',
                             'isobar1': {   'isobar_name': 'target',
                                            'WS_radius': {   'description': 'Woods-Saxon radius '
                                                                            'parameter R',
                                                             'value': 6.62},
                                            'WS_diffusiveness': {   'description': 'Woods-Saxon '
                                                                                   'diffusiveness '
                                                                                   'parameter a',
                                                                    'value': 0.546},
                                            'beta_2': {   'description': 'Quadrupolar deformation',
                                                          'value': 0.0},
                                            'gamma': {   'description': 'Quadrupolar deformation '
                                                                        'angle (rad); design '
                                                                        'matrix supplies degrees',
                                                         'value': 0.0},
                                            'beta_3': {   'description': 'Octupolar deformation',
                                                          'value': 0.0},
                                            'sigma_beta_2': {   'description': 'Event-by-event '
                                                                               'width of beta_2; 0 '
                                                                               'fixes the shape',
                                                                'value': 0.0},
                                            'sigma_beta_3': {   'description': 'Event-by-event '
                                                                               'width of beta_3; 0 '
                                                                               'fixes the shape',
                                                                'value': 0.0},
                                            'sigma_gamma': {   'description': 'Event-by-event '
                                                                              'width of gamma_lit '
                                                                              '(rad); folded onto '
                                                                              '[0, pi/3], 0 fixes '
                                                                              'gamma',
                                                               'value': 0.0},
                                            'beta_max': {   'description': 'Upper bound on '
                                                                           'quadrupole strength '
                                                                           '(Option B); uniform '
                                                                           'wedge prior is '
                                                                           'beta_max/2 with sd '
                                                                           'beta_max/sqrt(12)',
                                                            'value': 0.5},
                                            'shape_distribution': {   'description': 'Per-event '
                                                                                     'shape draw: '
                                                                                     'wedge '
                                                                                     '(Option B) '
                                                                                     'or plane '
                                                                                     '(Gaussian in '
                                                                                     'the '
                                                                                     'deformation '
                                                                                     'plane, '
                                                                                     'folded per '
                                                                                     'draw)',
                                                                      'value': 'plane'},
                                            'sigma_plane': {   'description': 'Width of the '
                                                                              'plane-form '
                                                                              'Gaussian; 0 is '
                                                                              'rigid, and works at '
                                                                              'beta_2 = 0',
                                                               'value': 0.0},
                                            'plane_anisotropy': {   'description': 'Splits '
                                                                                   'sigma_plane '
                                                                                   'with fixed '
                                                                                   'geometric '
                                                                                   'mean; 0 is '
                                                                                   'isotropic, '
                                                                                   'positive '
                                                                                   'favours '
                                                                                   'prolate/oblate, '
                                                                                   'negative '
                                                                                   'favours '
                                                                                   'triaxial',
                                                                    'value': 0.0},
                                            'correlation_length': {   'description': 'Short-range '
                                                                                     'correlation '
                                                                                     'length (fm)',
                                                                      'value': 0.8},
                                            'correlation_strength': {   'description': 'Short-range '
                                                                                       'correlation '
                                                                                       'strength',
                                                                        'value': -1.0}}}}

isobars_conf_dict_projectile = {   'isobar_samples': {   'description': 'Options for the isobar nucleon-position samples',
                          'number_configs': {   'description': 'Number of configurations to be '
                                                               'sampled.',
                                                'value': 1},
                          'number_nucleons': {   'description': 'Mass number A of the nuclei.',
                                                 'value': 208},
                          'seed_source': {   'description': 'Nucleon seeds: philox (deterministic '
                                                            'from master_seed and pool address) or '
                                                            'file (HDF5 pool).',
                                             'value': 'philox'},
                          'master_seed': {   'description': 'Master seed for the philox source. '
                                                            'Must never change once events exist; '
                                                            'recorded in EMULATOR_SWEEP_PLAN.md.',
                                             'value': 8675309},
                          'pool_modulus': {   'description': 'Size of the virtual nucleus pool, '
                                                             '2**32. Event g maps to addresses '
                                                             '(2g)*2654435761 and '
                                                             '(2g+1)*2654435761 mod this.',
                                              'value': 4294967296},
                          'output_path': {   'description': 'Output directory where to save',
                                             'dirname': 'nuclei_projectile'},
                          'number_of_parallel_processes': {   'description': 'Number of processes '
                                                                             'to compute in '
                                                                             'parallel.',
                                                              'value': -1}},
    'isobar_properties': {   'description': 'Nuclear properties of isobars to be sampled.',
                             'isobar1': {   'isobar_name': 'projectile',
                                            'WS_radius': {   'description': 'Woods-Saxon radius '
                                                                            'parameter R',
                                                             'value': 6.62},
                                            'WS_diffusiveness': {   'description': 'Woods-Saxon '
                                                                                   'diffusiveness '
                                                                                   'parameter a',
                                                                    'value': 0.546},
                                            'beta_2': {   'description': 'Quadrupolar deformation',
                                                          'value': 0.0},
                                            'gamma': {   'description': 'Quadrupolar deformation '
                                                                        'angle (rad); design '
                                                                        'matrix supplies degrees',
                                                         'value': 0.0},
                                            'beta_3': {   'description': 'Octupolar deformation',
                                                          'value': 0.0},
                                            'sigma_beta_2': {   'description': 'Event-by-event '
                                                                               'width of beta_2; 0 '
                                                                               'fixes the shape',
                                                                'value': 0.0},
                                            'sigma_beta_3': {   'description': 'Event-by-event '
                                                                               'width of beta_3; 0 '
                                                                               'fixes the shape',
                                                                'value': 0.0},
                                            'sigma_gamma': {   'description': 'Event-by-event '
                                                                              'width of gamma_lit '
                                                                              '(rad); folded onto '
                                                                              '[0, pi/3], 0 fixes '
                                                                              'gamma',
                                                               'value': 0.0},
                                            'beta_max': {   'description': 'Upper bound on '
                                                                           'quadrupole strength '
                                                                           '(Option B); uniform '
                                                                           'wedge prior is '
                                                                           'beta_max/2 with sd '
                                                                           'beta_max/sqrt(12)',
                                                            'value': 0.5},
                                            'shape_distribution': {   'description': 'Per-event '
                                                                                     'shape draw: '
                                                                                     'wedge '
                                                                                     '(Option B) '
                                                                                     'or plane '
                                                                                     '(Gaussian in '
                                                                                     'the '
                                                                                     'deformation '
                                                                                     'plane, '
                                                                                     'folded per '
                                                                                     'draw)',
                                                                      'value': 'plane'},
                                            'sigma_plane': {   'description': 'Width of the '
                                                                              'plane-form '
                                                                              'Gaussian; 0 is '
                                                                              'rigid, and works at '
                                                                              'beta_2 = 0',
                                                               'value': 0.0},
                                            'plane_anisotropy': {   'description': 'Splits '
                                                                                   'sigma_plane '
                                                                                   'with fixed '
                                                                                   'geometric '
                                                                                   'mean; 0 is '
                                                                                   'isotropic, '
                                                                                   'positive '
                                                                                   'favours '
                                                                                   'prolate/oblate, '
                                                                                   'negative '
                                                                                   'favours '
                                                                                   'triaxial',
                                                                    'value': 0.0},
                                            'correlation_length': {   'description': 'Short-range '
                                                                                     'correlation '
                                                                                     'length (fm)',
                                                                      'value': 0.8},
                                            'correlation_strength': {   'description': 'Short-range '
                                                                                       'correlation '
                                                                                       'strength',
                                                                        'value': -1.0}}}}

trento_dict = {   'type': 'self',
    'projectile': ['nuclei_target/target.hdf', 'nuclei_projectile/projectile.hdf'],
    'number-events': 1,
    'quiet': False,
    'output': 'initial_condition',
    'reduced-thickness': 0.063,
    'fluctuation': 0.9070294784580498,
    'nucleon-width': 1.12,
    'cross-section': 7.0,
    'normalization': 17.2,
    'b-min': 0,
    'b-max': 14.689433,
    'grid-max': 20.0,
    'grid-step': 0.2}

free_streaming_dict = {'tau': 1.5, 'grid_max': 20.0, 'grid_step': 0.2}

music_dict = {   'beastMode': 2,
    'Initial_profile': 9,
    's_factor': 1.0,
    'Initial_time_tau_0': 1.5,
    'Delta_Tau': 0.005,
    'X_grid_size_in_fm': 40.0,
    'Y_grid_size_in_fm': 40.0,
    'Grid_size_in_x': 200,
    'Grid_size_in_y': 200,
    'boost_invariant': 1,
    'EOS_to_use': 24,
    'quest_revert_strength': 1.0,
    'Viscosity_Flag_Yes_1_No_0': 1,
    'Include_Shear_Visc_Yes_1_No_0': 1,
    'T_dependent_Shear_to_S_ratio': 3,
    'shear_viscosity_3_eta_over_s_T_kink_in_GeV': 0.223,
    'shear_viscosity_3_eta_over_s_low_T_slope_in_GeV': -0.776,
    'shear_viscosity_3_eta_over_s_high_T_slope_in_GeV': 0.37,
    'shear_viscosity_3_eta_over_s_at_kink': 0.096,
    'shear_relax_time_factor': 4.65,
    'Include_Bulk_Visc_Yes_1_No_0': 1,
    'T_dependent_zeta_over_s': 3,
    'bulk_viscosity_3_zeta_over_s_max': 0.133,
    'bulk_viscosity_3_zeta_over_s_T_peak_in_GeV': 0.12,
    'bulk_viscosity_3_zeta_over_s_width_in_GeV': 0.072,
    'bulk_viscosity_3_zeta_over_s_lambda_asymm': -0.122,
    'Include_second_order_terms': 1,
    'Include_vorticity_terms': 0,
    'use_eps_for_freeze_out': 0,
    'T_freeze': 0.136,
    'N_freeze_out': 1}

iss_dict = {   'hydro_mode': 1,
    'include_deltaf_shear': 1,
    'include_deltaf_bulk': 1,
    'bulk_deltaf_kind': 11,
    'sample_upto_desired_particle_number': 1,
    'number_of_particles_needed': 100000,
    'local_charge_conservation': 0,
    'global_momentum_conservation': 0}

# the toolkit tables are off (control_dict['toolkit_tables']); the master still
# reads this dictionary
hadronic_afterburner_toolkit_dict = {   'event_buffer_size': 100000,
    'compute_correlation': 0,
    'flag_charge_dependence': 0,
    'compute_corr_rap_dep': 0,
    'resonance_weak_feed_down_flag': 0,
    'pT_min': 0.0,
    'pT_max': 5.0,
    'npT': 100,
    'rap_min': -1.0,
    'rap_max': 1.0,
    'rap_type': 1,
    'vn_rapidity_dis_pT_min': 0.2,
    'vn_rapidity_dis_pT_max': 2.0}

# Default equation of state: the lattice reference (the user's WB jackknife mean
# below 240 MeV, the WB 2014 parametrization above 270 MeV, relaxing to 1/3
# above 1.5 GeV), anchored to the SMASH hadron gas at T_freeze by
# codes/eos_builder.  The file is not in git; it is found next to the
# parameter file or in the job folder.  Design points replace this eos_dict
# (MakeDictionaries --eos-model).
eos_dict = {
    'cs2_table': 'lattice_cs2_WB_blend.dat',
    'high_T': {'relax_to': 0.3333333333333333, 'scale_GeV': 0.2, 'top_GeV': 5.0},
}
