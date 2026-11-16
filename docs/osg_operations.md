# Running a campaign on OSG: what has gone wrong

Operational lessons from the 2026 campaigns on the OSPool (access point `ap40`,
results pulled to a local mergerfs disk). Each entry is something that cost
hours or days. Paths, host names and numbers are those of that setup; the
failure modes are general. The tooling these notes refer to is in
`scripts/osg/` (collection, pruning, recovery) and `scripts/` (staging,
merging, auditing); the loops and feeders that drove one specific campaign are
kept with its record, e.g. `campaigns/zr96-c2/operations/`.

- **Never overwrite a path already published over OSDF.** OSG caches OSDF content by path, so
  overwriting a `.sif` in place leaves the cache serving the *old* bytes. The failure is
  inconsistent and therefore dangerous: some workers recompute the checksum from the local file
  and go on hold with `Pelican Client Error: checksum mismatch`, while others fetch the cached copy,
  both sides agree, and the job **silently runs the wrong image**. This actually happened —
  `iebe-music_slim.sif` was refreshed under the same name and two batches ran ~10 minutes against
  the previous, uninstrumented image before it was caught. Publish every image under a unique
  commit-named path (`iebe-music_slim_<short-sha>.sif`) and reference *that*; never use a mutable
  alias. When a batch's results are needed, check the image path in the submit file before
  concluding anything about the numbers.
- **Never reuse a published SIF filename, even for a "new" build.** Commit-named paths
  (`iebe-music_slim_<short-sha>.sif`) only protect you if the commit actually changed the
  image. They do not when the `Dockerfile` pin lags `HEAD`: two builds can both be built
  from `HEAD = 4723b7e` while containing different pins, so the second overwrites the first
  under the same path and OSG's OSDF cache keeps serving the stale bytes. That happened here
  and the workers pulled the *previous* image (`def37b56...`) while the server reported the
  current one (`443fcee...`). **Put the md5 prefix in the filename**
  (`iebe-music_slim_<sha>_<md5prefix>.sif`) so uniqueness does not depend on the commit
  having moved, and derive the name from the pinned SHA rather than from `HEAD`.
- **`request_disk = 2 GB` is too small for a 20-event job.** Jobs on both campaigns began
  holding with `Error from slot...: disk usage exceeded allocated disk` (178 A=96 + 15 A=76 in
  one wave): the execute-node sandbox holds all 20 events' hydro intermediates before the quiet
  packer compresses them, which overruns 2 GB on the larger events. Staged submit files now
  request **4 GB** (`stage_campaign.py --disk 4`), and held jobs were fixed in place with
  `condor_qedit ... RequestDisk 4194304` + `condor_release`. Raise the request before releasing
  — releasing alone just re-runs into the same limit.
- **OSG resource requests: ask for 1 GB, not 4.** Peak RSS for a 19-event 76Ge batch on one core
  was 212 MB, so the old 4 GB default requested ~19x what is used purely for scheduling speed.
  `request_disk` must cover the *whole* batch, not one event, because events run sequentially into
  one working directory; it is now settable with `-disk` (default 10 GB). Run large batches from
  the data disk (`/ospool/ap40/data/matthew.luzum`, ~465 GB) so results land there, but keep
  condor `log`/`error`/`output` on the home disk, which the generator already does via an absolute
  `home_log_dir`. Measured over 1990 production jobs (20 events each, decays-only, dx=0.15):
  wall median 1.09 h (p10 0.60, p90 2.33, max 6.2), peak RSS median 269 MB, p99 733 MB, max
  1221 MB. Only 2/1990 jobs exceeded 1 GB, both at one design point, so keep 1 GB as the
  default and `condor_qedit ... RequestMemory 1400` + `condor_release` the rare hold. Memory
  is a property of the design point, not of job length: one dp sat at 733 MB median.
  Output is ~156 KB per event (`spvn_results_<id>.h5`, measured over 30k files), i.e. ~310 MB
  per design point at 2000 events, so the 465 GB data disk holds ~1500 design points at that
  statistics — the quota binds at 2000 points (~620 GB), not earlier.
- **Pulling results: bundle on the AP, never walk the tree file by file.** A design point is
  ~4000 small files (1900 h5 at 156 KB + 2000 trento summaries + 100 drawn CSVs). CephFS
  metadata latency on the AP is ~90 ms per file, so both rsync and `tar cf - | ssh` crawl at
  ~0.8 MB/s however fast the link is (16 parallel raw streams measured 48 MB/s). `tar czf`
  collapses 300 MB to 61 MB (4.9x — float32 h5 data) and the single file moves in ~15 s, so
  pack per design point on the AP and transfer the archive. The packing step parallelizes;
  the per-file walk does not.
- **Never edit a shell script while instances of it are running.** bash reads a script
  incrementally by byte offset, so an in-place edit makes the running instance resume in the
  middle of new text — this produced `syntax error near unexpected token ';;'` mid-pull and
  silently killed two waves.  Launch long runs from a timestamped copy
  (`cp scripts/x.sh /tmp/opencode/x_$(date +%s).sh && bash /tmp/opencode/x_*.sh ...`).
  Pair this with `ControlMaster=auto,ControlPath=/tmp/opencode/cm_osg,ControlPersist=600` in
  the pull tooling: a per-dp probe+count+copy is three connections, and multiplexing them onto
  one TCP stream is what keeps the AP from blackholing ssh during a 300-point sweep.
- **The AP rate-limits ssh: a connection burst gets port 22 blackholed for ~30 min.** Eight
  parallel workers opening 4 connections each per design point was enough. The symptoms look
  like an outage but are not: `ssh` says "Network is unreachable" (the AP resolves to IPv6,
  which the local host has no route for) or times out, while port 443 on the same host
  answers "connection refused" and `ap41.uw.osg-htc.org:22` / `ap42.uw.osg-htc.org:22` stay
  open. Keep concurrency <= 3, use 1-2 connections per design point, reuse a ControlMaster
  for short control commands, and do not keep retrying during a block — retries can extend
  it. Running OSG jobs are unaffected: they talk to the schedd, not to our ssh.
- **Result layout changes at dp0461: one archive per job.** In quiet mode the worker now packs
  `spvn_results/` into `spvn_results_<proc>.tar.gz` on local scratch and the submit file lists
  that single file instead of the directory (~100 files/job). Packing on the AP instead costs
  ~90 ms per file of CephFS latency; on the worker it is seconds. It also cuts the stored
  footprint ~5x, which is what keeps 2000 design points inside the 465 GB quota (620 GB of
  loose h5 vs ~124 GB of archives). dp0001-0460 keep the directory layout, so tooling must
  handle both: `scripts/osg/osg_pull_results.sh` pulls either, `scripts/osg/osg_merge_reruns.sh`
  folds re-run output back in either (renaming `spvn_results_0.tar.gz` to the block it covered,
  because re-runs are single jobs with ProcessId 0).
- **The data disk quota binds on FILES, not bytes: ~2M (`ceph.dir.rfiles`).** `quota -s` only
  reports the local mounts and `df` reports the whole CephFS, so both look healthy while every
  write fails with `errno 122 Disk quota exceeded` and jobs pile up on transfer holds
  (`HoldReason` naming the file it failed to write). A directory-layout design point is ~4000
  files (1900 h5 + 2000 trento summaries + 100 drawn), so ~460 points exhausted 2M; the archive
  layout is 100 files per point and would fit ~20,000. Consequences: (a) the AP is staging, not
  the archive — pull, verify, delete; (b) purging old points with `rm -rf` on CephFS is slow
  (~10-30 files/s for 4000-file directories) and running several in parallel pushed the AP to
  load average >1000, at which point `condor_submit` and even `ssh` hang. Delete at low
  concurrency (2-4), and check `uptime` before blaming a hung command on the script.
- **When the AP's CephFS metadata server is saturated, put every submit-side file on the AP's
  local `/tmp`.** Measured during a 2026-10-24 storm: `mkdir` on the data disk took 1m51s and
  file creation ~3 min, so a 378-dp staging pass spent 53 min on `mkdir` and wrote ~40 of 756
  files in two hours — while the 7.3k-job queue drained to zero and the pool idled. With the
  submit files, parameter dictionaries, and `run_singularity.sh` on `/tmp` (and `initialdir`
  still pointing at the data-disk dp dir), submission is **0.6 s per cluster** instead of
  10 min. Two site quirks: (a) `condor_submit` given several submit files silently submits only
  the **last** one (a 378-file bulk call created exactly one cluster); loop one file per
  invocation. (b) tar-extracted submit files can lack a trailing newline, producing
  `ERROR: Failed to parse command file (line N)` on the final `queue` line — `echo >>` fixes it.
- **Merging per-event h5 into one file per dp: use `scripts/merge_dp_h5.py`, not
  `combine_multiple_hdf5.py`.** The latter spawns one `h5copy` per event, which is ~10,000
  subprocesses for a 10,000-event design point (~1 h). The in-process merger copies groups and
  datasets with h5py and does dp0001's 1,894 events in ~60 s with byte-identical output
  (verified: same group names, same 46 datasets, values equal). `scripts/osg/consolidate_dps.sh`
  uses it and records `merged/<dp>/sources.txt` (number of archives merged); a dp is re-merged
  automatically when its source count changes (`100 -> 300 -> 500` as augmentation batches
  land) and once it reaches `MIN_SOURCES` (default 90), so a half-delivered batch never
  produces a partial file. `MIN_SOURCES` is 90, not 100, because a 100-job batch ends
  with 96-99 archives: events whose freeze-out surface is empty produce no h5, so a
  ">= 100" gate never merged a single-batch point at all (campaign-2 A=96 sat at 33
  points pulled, 0 merged until `2efabae`).
- **The merged h5 is written uncompressed on purpose — do not "fix" that.** Merged
  cost is ~253 KB per event (campaign 2, three `deltaf_*` models, 100 pT bins) against
  a 204 KB raw payload, i.e. ~24 % HDF5 metadata, and ~1.5 TB for 6,000 events at
  1,000 design points. Compressing each dataset the way the per-event files are
  (gzip 9, chunk = full shape) makes the merged file **1.8x larger** (442 KB/event):
  every event contributes 98 tiny arrays that are too small to amortise a chunk
  header plus a gzip stream, which is also why the per-event h5 is 456 KB while the
  same data is only 168 KB inside the job tarball. Only whole-file gzip wins
  (156 KB/event, 63 %), so it belongs in cold storage, not in the merger.
- **Local `/data` is mergerfs over `/mnt/data1..5`, and `df` hides per-branch inode exhaustion.**
  The branch holding the repo/results hit **953,888/953,888 inodes = 100%** while `df -h` showed
  3.6 TB free; every write then failed with `No space left on device` (including a 10 KB
  `mkdir`), and pulls silently failed. A directory-layout design point costs ~6,000 inodes
  (1,900 event h5 + 2,000 TRENTo summaries + 100 drawn CSVs), so ~160 dps filled the table.
  Check `df -i /mnt/data5`, not `df -h`, before blaming space. Remedy: consolidate each dp to
  one h5 (`scripts/osg/consolidate_dps.sh`, ~1 file instead of ~4,000), keep the
  `events_drawn_*.csv` files (they are NOT inside the merged h5), and only then delete the raw
  tree. Merged-vs-raw parity was verified group-for-group (122/122) before the first cleanup.
  **Archive-layout pulls must keep the per-job tarballs and never extract them**: extraction
  costs ~6,200 files per dp (20 events x h5 + TRENTO summary + grid extent per job tarball),
  which refilled the table after only ~90 points. `osg_pull_results.sh` now keeps the 100
  tarballs per dp and verifies by listing archive contents; consolidation extracts one dp at a
  time into /tmp.
- **A single `condor_rm -constraint` may remove only a fraction of a large queue.** Purging the
  campaign-1 queue (21,508 jobs: `regexp("iEBEMUSIC_(ge76|zr96)_", JobBatchName)`) marked only
  8,438 for removal; 10,015 idle jobs survived and were still visible afterwards.  Re-issuing the
  removal (split per campaign: `iEBEMUSIC_ge76`, `iEBEMUSIC_zr96_`) cleared them within a minute.
  When switching campaigns, verify `condor_q -af JobBatchName | grep -c <old pattern>` reaches 0
  rather than trusting the one-shot command's "marked for removal" message.  Constrain on the
  campaign prefix, not the campaign-2 name, so `zr96c2_` survives.
- **The AP caps in-flight jobs at 50,000 per owner, and excess submissions are deferred, not
  rejected.** `condor_config_val -schedd MAX_JOBS_PER_OWNER` returns 50000. When the queue is at
  the cap, `condor_submit` still prints "submitted to cluster N" (the cluster object is created)
  but the individual jobs are committed only as the owner's total drops; `condor_q` shows the
  cluster with no jobs, and `job.<cluster>.0.log` contains the 035 "Cluster submitted" line but
  no 000 job-submission line. Observed directly: cluster 16053576 had 0 queued jobs, then 12
  ten minutes later, with the owner total steady at ~49,994. **Never resubmit a design point
  just because its cluster is not in `condor_q`** — wait, and confirm via
  `~/log/job.<cluster>.0.log` or by watching the count; a duplicate submission runs the same
  deterministic events again and only wastes core-hours. Practical consequence: the queue
  self-refills to ~50k from already-submitted work, so a tranche larger than the remaining
  headroom is safe to submit in one go.
- **Never put `checkpoint_exit_code` in an OSG submit file.** A submit file
  carrying it makes the schedd inject `TARGET.HasSelfCheckpointTransfers` into
  the job's Requirements.  Nothing in the pool advertises that attribute, so
  **every slot rejects every job** -- and it fails silently: jobs stay idle,
  `condor_q` looks normal, and the only clue is `condor_q -better-analyze`
  saying "0 slots match" plus a stale "Last successful match".  On 2026-11-01
  this cost ~18 h of zero placement on 34,122 queued jobs; the same line was in
  both `Cluster_supports/*/generate_submission_script.py` templates, with the
  checkpointing code long unused.  Requirements are also *baked into the job
  classad at submit time*, so fixing the submit file does not help already-queued
  jobs: they need
  `condor_qedit -constraint 'JobStatus == 1 && ...' Requirements '<expr without the clause>'`.
  Diagnose placement failures with `condor_q -better-analyze <cluster>`, never by
  reading `condor_q`'s totals.
- **Give maintenance jobs `JobPrio 100`.** A single re-run or test job submitted while a
  tranche is in flight sits behind tens of thousands of idle jobs and can look "lost" (it has
  no hold reason and no history record because it never started). `condor_qedit <cluster>.0
  JobPrio 100` gets it scheduled promptly. Note `condor_q <cluster> | tail -2` prints the
  queue summary, not the job — use `condor_q -af ClusterId ProcId JobStatus | awk '$1==<c>'`.
- **A job that skips one event must still transfer its other 19.** `prepare_surface_files_for_urqmd`
  returns False when the freeze-out surface is empty (very peripheral / tiny fireball), the
  driver skips that event *silently* (no print), and at the end exits 73. The submit template
  used to carry `periodic_remove = (ExitCode == 73)`, which races the output transfer: when
  the remove wins the whole job's 20 events vanish with no HoldReason, exit code, or message,
  and the job simply disappears from the queue. That cost 47 of 2000 blocks (~2.3%) in the
  first production batch and was only found by diffing h5 files against `events_drawn.csv`.
  `periodic_remove` is gone. Expect ~1-2% of drawn events to be skipped for real (surface
  size 0); they stay in `events_drawn.csv` with `mult > 0` and are visible as drawn-but-missing
  h5, which is exactly the set to re-run.
- **A `condor_rm` with an empty cluster id and a `-constraint` deletes the whole queue.** Parsing
  the cluster out of a failed `condor_submit` yields `""`, and `condor_rm "" -constraint '...'` is
  not a no-op: it applied the constraint to every job the owner had, removing ~26,000 queued
  batch-2 jobs on 2026-11-05 (the intended target was 89 procs of one cluster). The surviving
  3,130 were the procs the constraint happened to keep, scattered across 294 points. Always verify
  the cluster id is non-empty before using it, and prefer explicit `<cluster>.<proc>` ids over a
  constraint. Recovery is resubmission, which is exact because events are deterministic, but it
  costs a full transit of the queue.
- **A 0-byte job archive (the packing step died) strands its whole design point.** It cannot pass a
  non-empty arrival check, so the collector never deletes it and the point is never pruned; and the
  merger's `tar xzf` fails, aborting the point. `osg_fetch_prune.sh` now reads sizes in the same
  listing it already does, removes empty archives on both sides and logs `REMOTE_EMPTY`, and
  `consolidate_dps.sh` skips them with `SKIP_EMPTY`. The job still has to be re-run (dp2310 job 18).
- **An h5 truncated inside an archive keeps the HDF5 signature.** The merger's signature check
  passed it, then h5py failed mid-copy and aborted the point with a traceback that did not name the
  file — dp2358 lost four days to 14 such files, all from one job (12 of 0 bytes, 2 truncated at a
  page boundary). `merge_dp_h5.py` now opens each file once before copying anything, names any it
  cannot read, and skips it, so one bad job costs 20 events instead of the whole point. Repair is a
  re-run of those events, replaced inside that one archive (entry count before/after must match).
- **Merge only at batch boundaries.** A batch is 100 archives and is complete at `MIN_SOURCES` (90),
  so a count in between (101–189) is a moving target: the point re-merges on every arrival. With
  partial batch-2 blocks trickling in, 294 points sat in that range. `batch_complete()` merges only
  when `n % 100 == 0` or `n % 100 >= MIN_SOURCES`; a point that genuinely ends short still merges.
- **`condor_history` and `condor_q` are per-schedd but cluster ids are shared with other users.**
  A range filter (`ClusterId >= X && <= Y`) returns strangers' jobs (`opt12_*`, `s34_test_*`), which
  looks like our jobs finishing with no output. Filter on `JobBatchName`, never on a cluster range.
- **A single-job repair must rewrite both `$(Process)` and `queue 100`.** The staged submit files
  are blocks of 100 jobs, so `arguments = <dict> $(Process) 20 1 0 2000` plus `queue 100` reproduces
  one block. To re-run one job of a block, write the index literally in `arguments` (the worker dials
  `event_start_id = eventOffset + processId*20` and names the archive after `processId`, both taken
  from argv, not from the slot's ProcId), point `transfer_output_files` at that exact name, and
  change the queue line to `queue 1`. Leaving `queue 100` in place submits 100 identical jobs that
  all write the same archive -- the result is correct but costs 100x the core-hours (done once:
  five repairs, 499 redundant jobs).
