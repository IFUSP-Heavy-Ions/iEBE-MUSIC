# HBT sums: method and validation (2026-11-24)

The optional HBT output of the standard output (`docs/standard_output.md`,
section 9) is checked here against exact pair kinematics. These are the tests
behind its rules.

## Why not the toolkit's HBT

Upstream iEBE-MUSIC runs the toolkit's pair analysis (`analyze_HBT = 1`). It
loops over pairs of identical pions in |y| < 0.5, each adding cos(q.dx) to a
cell of a 31^3 grid, with mixed events for the denominator. Four things rule
it out for campaigns:

1. **Size and cost.** About 240,000 numbers per event and variant; O(N^2) in
   the pions; capped at 3e7 pairs per K_T bin; 90% of a boost-invariant
   sample unused.
2. **Decays-only files.** `read_in_mode 9` (the chain's decays-only binary)
   never increments its event index (`particleSamples.cpp`; upstream main as
   of 2026-11-17 too). Every particle of a buffer lands in event 0, the mixed
   events are empty, and the correlation functions come out as zeros. The
   flow tables are unaffected apart from per-event quantities: the new
   `*_covMatrix.dat` upstream, and the order of the toolkit's own weak decays.
   The fix is two lines and was prepared for upstream.
3. **UrQMD output.** UrQMD's file 13 (`particle_list.dat`) gives the particles
   that never collide (ncoll = 0, 35% of pi+ in a central Zr+Zr event) the
   coordinates at the end of the run, `tim` = 8000 fm. The pair weight
   cos(q.dx) is not invariant under free streaming at O(q^2), so those pions
   become a halo: lambda 0.39 instead of about 0.79, and the radii of the
   rescattered pions only (R_long 9.2 fm, against 7.3 fm with every pion at
   its emission point). SMASH's end-of-run positions would do the same.
4. **Weak decays in campaign 2.** The campaign-2 dictionaries set
   `resonance_weak_feed_down_flag = 1`, so the toolkit decays K0 and Lambda
   itself, adding 3% pions far from the source and lowering lambda by about
   6%. The standard output keeps weak decays out.

## Method

Each particle gets coordinates in its own LCMS: a = x_out - beta_T t,
b = x_side, c = z. These are invariant under free streaming. Per (species,
K_T, Phi) bin and per q point, S(q) = sum exp(i q.(a, b, c)/hbarc), and
|S|^2 - N = sum over pairs i != j of cos(q.dx~), at O(N) per q point instead
of O(N^2). Every pair of the bin counts at every q, and pairs across
oversamples sample the same freeze-out surface.

The approximation is the smoothness approximation: each particle in its own
LCMS instead of the pair's. Its error is O(q/K) in the frame and
O(q^2 t / E) in the phase.

## Tests

Design point 583 of zr96-c2, PTB, re-run in `iebe-music:*-5c19ce8` with the
particle lists kept. The reference is the exact pair weight on the same
particles (the toolkit with read_in_mode 9 fixed and weak feed-down off, plus
an independent numpy pair loop). Fits are a 3D Gaussian (lambda, R_o, R_s,
R_l, R_os, R_ol), |q| < 0.08 GeV, pi+, |y| < 0.5.

Decays only:
- Events 916 (central), 1031 (mid-central) and 101 (peripheral), K_T bins
  0.15-0.25-0.35-0.45-0.55.
- Radii within 1-2%, except R_long up to 2-5% low at K_T > 0.35 in the
  non-central events (about 2 sigma of the reference).
- lambda 1-2% higher (mid-central, peripheral), up to 6% (central, lowest
  K_T).
- Same-pair check (central, K_T 0.15-0.25): the exact weight gives lambda
  0.684 and R 5.23/4.61/6.53 fm; the own-LCMS phase with the pair's q gives
  0.677 and 5.21/4.57/6.42. So the phase approximation itself is good.
  Grid-q against pair-q accounts for the rest (cell averaging alone is about
  1.5% in lambda).

UrQMD, event 916, only the pions with ncoll >= 1 (all positions physical):
- Radii within 1-3%, lambda 6-8% higher (0.829 against 0.785 in K_T
  0.15-0.25).
- With every pion included, the sums give lambda 0.80 and R
  5.8/5.0/7.3 fm, while exact pairs give lambda 0.39 and the radii of the
  rescattered subset (item 3 above).

Phi bins:
- No binning (adding S over all Phi) inflates R_o and R_s by 15-25%
  (peripheral), 3-5% (mid-central) and 1% (central). This comes from
  event-by-event shifts of the emission centre seen in different frames.
- 4 bins: about 3% (peripheral). 12, 24 and 48 bins agree within 0.5%.

K_T merging: summing |S|^2 - N over two 0.05 GeV bins, or summing their S
first, gives the same fits within statistics in every bin tested.

Rapidity window (2D runs): fits are flat within about 1% for |y| from 1 to
4.5 with the sampled range ±5. The default is the sampled range minus 1 unit,
about 10x the statistics of |y| < 0.5.

q points and weights:
- Fitting the 13-direction star unweighted gives lambda +0.07 and radii
  +5-15% against a 3D-grid fit of the same sums: the non-Gaussian small-q
  peak is oversampled.
- With d^3q weights the star reproduces the grid fit within 1-3% for 20 |q|
  values, and within 3-7% for 13.

Implementation (`codes/standard_output.py`):
- Against the prototype the HBT values agree to float32 precision.
- Every pre-existing dataset is byte-identical with HBT on or off, for
  decays-only and UrQMD.
- The eta and Sigma0 decays after the cascade now carry decay vertices, from
  their own random stream, so their momenta are unchanged.
- 4 s and about 190 MB peak per event and variant (central event, 600,000
  pions in |y| < 4).

Open: the Levy alpha of the sums against exact pairs. alpha comes from the
same small-q shape as the lambda offset.
