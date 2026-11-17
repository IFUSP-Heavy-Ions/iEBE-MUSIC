# Importance sampling of events

Hydrodynamics is the expensive stage, and a minimum-bias sample spends nearly
all of it far from the narrow centrality classes one wants to measure (a 0–0.2 %
class gets one event in 500). With importance sampling the chain simulates a
chosen subset of the events and records, per event, the weight that makes
averages over the subset unbiased.

It is off by default: with no selection configured every event is simulated
with weight 1, as in every campaign before this existed.

## The idea

Each event is accepted for simulation with a probability `P` that depends on
its centrality, estimated from the TRENTo initial condition alone, and carries
the weight `w = 1/P`:

    <O> = sum_i w_i O_i / sum_i w_i          over the simulated events

`P` only has to be positive and recorded, so a poor centrality estimate costs
efficiency, never correctness.

The random number that decides event `g` depends only on `(master_seed, g)`.
Every design point therefore makes the same draw for the same event, and the
accepted sets of two design points differ only where their acceptance
probabilities differ. That keeps the common-random-number pairing between
design points that the emulator relies on.

## Two phases

The decision is made **once**, before any hydrodynamics, and never again on a
worker: two machines do not agree on the initial multiplicity to the last bit
(up to 4e-7 relative between a local host and OSG workers), so an event next to
a class edge could be kept on one machine and dropped on another.

**Phase 1 — draw and select** (sampler + TRENTo only, about 13 ms per event for
A = 96, i.e. 3.5 CPU-hours per million events and design point):

```bash
# inside the image; any number of these in parallel, on disjoint id blocks
python3 scripts/draw_events.py --param <dictionary of design point N> \
    --first-id 0 --n 200000 --out draws_dp0001_0.npz

# then, per design point
python3 scripts/select_events.py --draws 'draws_dp0001_*.npz' \
    --selection campaigns/<name>/event_selection.json --out selection_dp0001
```

`draw_events.py` runs the events in batches (one sampler call and one TRENTo
call per thousand events). They are the *same* events the chain later
regenerates one at a time from their ids: `tests/sampler_stride.sh` and
`tests/trento_event_id_mode.sh` check that digit for digit, and have to be
re-run for a new collision system or a new TRENTo (done for A = 96 and for
Pb-208 at 2.76 TeV).

`select_events.py` builds the multiplicity-to-centrality table from that design
point's own draws, applies the selection, and writes

| file | content |
|---|---|
| `selection_dpNNNN.csv` | the accepted events: `event_id, weight, p_acc, centrality, estimator, u` |
| `selection_dpNNNN.json` | counts (`n_drawn`, `n_collided`, `n_no_collision`, `n_accepted`), `b_max`, the selection, the centrality range it covers, accepted and effective counts per bin |
| `selection_dpNNNN.npz` | the same list plus the calibration table |

The full minimum-bias record is not kept; it regenerates from the event ids.

By default the centrality table is recomputed from whatever draws are given.
To add events to a design point later without changing any earlier decision,
freeze it: `select_events.py --calibration selection_dp0001.npz` reuses the
table of an earlier selection (the summary records which).

**Phase 2 — simulate the list.** Stage as usual, pointing at the lists:

```bash
python3 scripts/stage_campaign.py --selection-dir <dir with selection_dpNNNN.csv> ...
```

Each design point gets as many jobs as its list needs; a job owns *positions*
of the list (`IEBE_EVENT_LIST`), while every file is still named by event id.
The driver checks that the multiplicity it regenerates is the one the event was
selected on (`selection_check` in `events_drawn.csv`).

This path was run end to end on the OSPool on 2026-11-17 (design point 583 of
zr96-c2, 13 accepted events in three jobs at three sites, image
`iebe-music_slim_6604e5f_2271081a.sif`): every event passed its
`selection_check`; eight were bit-identical to the same events run locally and
the five that ran on different hardware differed by 1e-9 in initial
multiplicity and by less than 0.1 % in pion yield, the usual cross-machine
level.

## Choosing the selection

`event_selection.json` is one of

```json
{"mode": "none"}

{"mode": "bins", "centrality_bins": [0, 0.2, 1, 2, 5, 10, 20, 40, 70],
 "min_acceptance": 0.02}

{"mode": "curve", "curve": [[0, 1.0], [1, 1.0], [10, 0.05], [100, 0.05]]}
```

* `bins` gives about the same number of simulated events in every listed bin:
  a bin of width `d` percent gets `P = d_min/d`, the narrowest bin is fully
  accepted, and `min_acceptance` is a floor. The number of events to draw in
  phase 1 follows from the narrowest bin: a 0.2 % bin with 1,000 events needs
  500,000 collisions drawn.
* `curve` is the acceptance probability as a function of centrality percent,
  interpolated linearly between the points given.
* Beyond the last bin edge the acceptance is that of the last bin, unless
  `"outside"` is given. `"outside": 0` is a hard cut: cheaper, but those
  events do not exist in the output, and classes defined on final-state
  multiplicity are biased within a few percent of the cut because the initial
  and final ordering of events differ. The summary records the range as
  `covered_centrality`.

Example, 200,000 draws at one A = 96 design point with bins
`[0, 0.5, 1, 2, 5, 10, 20, 40, 70]` and `min_acceptance` 0.02: 8,823 events
simulated (4.4 %), 895–1,135 per bin, against 188,416 for the same statistics
in the 0–0.5 % bin without selection.

`b_max` remains a per-campaign choice in the parameter dictionary. If it cuts
into the range where nuclei still collide, pass the fraction of the inelastic
cross section it covers to `select_events.py --coverage`.

## What the results carry

Per event (`spvn_results_<id>.h5`, and the merged file), as attributes of the
event group: `event_weight`, `selection_p_acc`, `selection_centrality`,
`selection_estimator`. **An event without `event_weight` has weight 1.**

`events_drawn.csv` lists only the accepted events in such a campaign, with the
extra columns `weight, p_acc, centrality, selection_check`. Its `status`
column says how far each event got: `ok`, `no_collision`, `no_surface` (a real
collision whose fireball never reached the freeze-out temperature), or
`hydro_failed`.

Merging with the selection attached,

```bash
python3 scripts/merge_dp_h5.py <dir with the per-event files> dpNNNN.h5 --selection selection_dpNNNN
```

copies the counts and the selection into root attributes of `dpNNNN.h5`
(`n_drawn`, `n_collided`, `n_no_collision`, `n_accepted`, `b_max`,
`covered_centrality`, `selection`) and puts the three selection files next to
it, the list gaining a `status` column:

| status | meaning | treatment |
|---|---|---|
| `ok` | simulated; its group is in the merged file | use with its weight |
| `no_surface` | collided, nothing to particlize | an event with no particles, with its weight |
| `failed` | nothing came back (lost job, crash) | re-run; never count as empty |

## Using the weights

* Every event average is `sum(w O)/sum(w)`.
* The minimum-bias denominator for centrality percentiles is `n_collided`
  from the summary, not the number of simulated events and not `sum(w)`:
  `sum(w)` estimates the number of collided events only inside
  `covered_centrality`. The fraction of the cross section above a multiplicity
  `M` is `sum(w_i [M_i > M]) / n_collided`.
* The statistical power of a set of events is its effective size,
  `(sum w)^2 / sum w^2`. Thresholds on "number of events" should count
  simulated events, not summed weights.
* Within one listed bin all weights are equal, so weighting only matters for
  classes that straddle bin edges and for anything integrated over centrality.
