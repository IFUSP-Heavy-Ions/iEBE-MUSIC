#!/bin/bash
# high-statistics edge measurement: hs_inner.sh <SMASH|UrQMD> <event> <width> <job id> <chunks> <events per chunk> <base dir>
ab=$1; ev=$2; W=$3; job=$4; NCH=$5; NS=$6; base=$7
export OMP_NUM_THREADS=1
src=$(ls -d $base/${ab}_ev$ev/playground/event_*)
sub=$src/${ab}ev_0
surf=$(ls $src/EVENT_RESULTS_$ev/hydro_results_$ev/surface_eps_*.dat)
wd=$base/hs/${ab}_ev${ev}_W${W}/job$job
rm -rf $wd; mkdir -p $wd/iSS/results; cd $wd/iSS
cp -P $sub/iSS/iSS.e $sub/iSS/iSS_tables . ; cp $sub/iSS/iSS_parameters.dat .
ln -s $surf results/surface.dat; cp $src/EVENT_RESULTS_$ev/hydro_results_$ev/music_input results/
half=$(python3 -c "print($W/2.0)")
cd $wd
if [ "$ab" = "SMASH" ]; then
  mkdir -p SMASH/list; cp -P $sub/SMASH/smash SMASH/
else
  mkdir -p urqmd osc2u; cp -P $sub/urqmd/urqmd.e $sub/urqmd/runqmd.sh $sub/urqmd/tables.dat urqmd/; cp -P $sub/osc2u/osc2u.e osc2u/
fi
tcas=0
for ch in $(seq 1 $NCH); do
  seed=$((20261119 + job*1000 + ch))
  (cd iSS && ./iSS.e randomSeed=$seed y_LB=-$half y_RB=$half sample_upto_desired_particle_number=0 number_of_repeated_sampling=$NS > run.log 2>&1)
  t0=$(date +%s.%N)
  if [ "$ab" = "SMASH" ]; then
    mv iSS/OSCAR.DAT SMASH/list/OSCAR.DAT0
    sed "s/Nevents: .*/Nevents: $NS/; s/Randomseed: .*/Randomseed: $seed/" $sub/SMASH/list/config.yaml > SMASH/list/config.yaml
    (cd SMASH && rm -rf data && unset PYTHIA8DATA && ./smash -i list/config.yaml > run.log 2>&1)
    out=SMASH/data/0/particles_oscar2013_extended.bin; kind=smash
  else
    (cd osc2u && ./osc2u.e < ../iSS/OSCAR.DAT > run.log 2>&1 && mv fort.14 ../urqmd/OSCAR.input)
    rm -f iSS/OSCAR.DAT
    sed "s/^#rsd .*/rsd $seed/" $sub/urqmd/uqmd.burner > urqmd/uqmd.burner
    (cd urqmd && ./runqmd.sh > run.log 2>&1)
    $src/hadronic_afterburner_toolkit/convert_to_binary.e urqmd/particle_list.dat binary > convert.log 2>&1
    out=urqmd/particle_list.bin; kind=urqmd
  fi
  t1=$(date +%s.%N)
  python3 $base/profile.py $kind $out $wd/profile_$ch.npz 6 0.25 >> profile.log 2>&1
  rm -f SMASH/list/OSCAR.DAT0 $out urqmd/OSCAR.input urqmd/particle_list.dat urqmd/particle_list.f1* urqmd/particle_list.f20
  tcas=$(python3 -c "print($tcas + $t1 - $t0)")
done
echo "$ab ev$ev W=$W job $job: $(ls $wd/profile_*.npz 2>/dev/null | wc -l)/$NCH chunks of $NS events, cascade $tcas s"
