# Rapidity window for UrQMD and SMASH in boost-invariant runs (2026-11-19)

A (2+1)-d hydro surface is particlized over a finite rapidity range and the
particles are passed to a 3+1-d cascade. Near the ends of the range particles
miss collision partners, so only a central part of the range is usable, while
the cascade's cost grows faster than linearly with the number of particles.
This note measures both, for zr96-c2, to choose the sampled range and the
collection cut. Scripts: `scripts/validation/afterburner_window/`.

**Setup.** Design point 583 of zr96-c2 (`T_freeze` 0.138 GeV), events 140
(central, dNch/dy 230) and 101 (peripheral, dNch/dy 15); image
`iebe-music:full-241af6c` (UrQMD as in `codes/get_code_packages.sh`, SMASH
3.2.2); CE delta f; particles sampled uniformly in y over a total width W.
SMASH ran on MUSIC's EOS 91, UrQMD on EOS 9, as the chain sets them.

## Edge reach

UrQMD, W = 6, 76,000 cascade events for event 140 and 100,000 for event 101.
Charged hadrons, ratio to the plateau (distance > 2 from the edge):

| distance from edge | dN/dy (140) | <pT> (140) | v2 (140) | v2 (101) | v3 (140) |
|---|---|---|---|---|---|
| 0-0.25 | 0.815 | 1.055 | 1.14 +- 0.02 | 0.90 +- 0.02 | 0.92 +- 0.02 |
| 0.25-0.5 | 0.916 | 1.049 | 1.08 +- 0.02 | 0.97 +- 0.02 | 0.94 +- 0.02 |
| 0.5-0.75 | 0.965 | 1.026 | 1.06 +- 0.02 | 0.98 +- 0.02 | 0.96 +- 0.02 |
| 0.75-1.0 | 0.987 | 1.012 | 1.01 +- 0.02 | 0.97 +- 0.02 | 1.03 +- 0.02 |
| 1.0-1.25 | 0.996 | 1.004 | 0.98 +- 0.02 | 0.98 +- 0.02 | 1.01 +- 0.02 |
| 1.25-1.5 | 0.9986 | 1.002 | 1.01 +- 0.02 | 1.00 +- 0.02 | 1.02 +- 0.02 |
| 1.5-1.75 | 1.0004 | 0.9998 | 0.97 +- 0.02 | 1.01 +- 0.02 | 0.98 +- 0.02 |

Statistical errors of dN/dy and <pT> are 0.03 % and 0.02 % (event 140); the
peripheral event follows the same curve within 0.1 %. Averaged over 1-2 units,
v2 is 0.995 +- 0.011 (140) and 1.004 +- 0.011 (101). The edge moves v2 up in
the central event and down in the peripheral one, and v3 down; v3 of the
peripheral event (0.002) is too small to measure. Pions set the reach; kaons
are flat beyond 0.75 units and protons beyond 0.5. A lower-statistics scan over
W = 2-10 gives the same curve for SMASH (yields and <pT>; its flow was not
measured at this precision).

**A cut of 1.25 units per side leaves at most 0.2 % in yields and <pT> and
no visible effect on v2, v3; 1.5 units leaves less than 0.05 %.**

## Cost against width

Seconds per cascade event, many runs sharing one 48-core machine:

| W | particles (140) | UrQMD (140) | SMASH (140) | UrQMD (101) | SMASH (101) |
|---|---|---|---|---|---|
| 1 | 380 | 0.075 | 3.1 | 0.027 | 0.87 |
| 2 | 770 | 0.20 | 3.7 | 0.028 | 0.64 |
| 4 | 1,530 | 0.51 | 3.6 | 0.024 | 0.72 |
| 6 | 2,290 | 0.95 | 5.4 | 0.032 | 0.75 |
| 8 | 3,050 | 1.61 | 5.3 | 0.042 | 0.79 |
| 10 | 3,800 | 2.44 | 6.1 | 0.070 | 0.88 |

UrQMD grows like N^1.5 at small sizes and N^1.85 at the largest. The SMASH
figures include a start-up of about 30 s per process, spread over 24 (event
140) or 100 (event 101) events; without it SMASH takes about 2 s at 390
particles and 5 s at 3,800, nearly flat because it runs 1,000 fixed time steps
regardless of size.

Usable charged particles per cascade second, (W - 2 x cut) dNch/dy / time:

| W | 3 | 4 | 6 | 8 | 10 |
|---|---|---|---|---|---|
| UrQMD 140, cut 1.0 | 700 | 890 | 960 | 850 | 750 |
| UrQMD 140, cut 1.5 | - | 450 | 720 | 710 | 660 |
| UrQMD 101, cut 1.0 | 560 | 1,220 | 1,840 | 2,100 | 1,700 |
| SMASH 140, cut 1.0 | 70 | 130 | 170 | 260 | 310 |

For UrQMD the optimum is broad, W = 6-8 for Zr+Zr, slightly wider for
peripheral events. SMASH is 3-15 times more expensive per usable particle at
these sizes and has not reached its optimum by W = 10.

**Default for Zr+Zr:** sample |y| < 3.5, collect |y| < 2.25. Pb+Pb has about six
times the particles, which moves the UrQMD optimum to narrower ranges; repeat
the scan there.

## Found on the way

* Neither cascade was reproducible: SMASH ran with `Randomseed: -1` and UrQMD's
  `rsd` line is commented out.
* Both leave eta and Sigma0 undecayed at the end (central event: about 12 eta
  and 1.2 Sigma0 per unit rapidity), which the experiments' primary-particle
  definition decays (charged hadrons about 3 % low, Lambda about 30 % low).
* SMASH is configured for 50 events, but iSS writes a number of samples that
  depends on the event (34 for event 140: SMASH aborts; 540 for event 101:
  490 are ignored).
* With `control_dict['deltaf_models']`, the UrQMD path is rejected by the final
  check, which expects the `_boostinv` tables that only the decays-only path
  writes.
