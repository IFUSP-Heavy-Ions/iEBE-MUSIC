#!/bin/bash
# inside the full image: one (afterburner, event, width) point of the window scan
# scan_inner.sh <SMASH|UrQMD> <event> <width> <n samples> <base dir>
ab=$1; ev=$2; W=$3; NS=$4; base=$5
export OMP_NUM_THREADS=1
src=$(ls -d $base/${ab}_ev$ev/playground/event_*)
sub=$src/${ab}ev_0
surf=$(ls $src/EVENT_RESULTS_$ev/hydro_results_$ev/surface_eps_*.dat)
wd=$base/scan/${ab}_ev${ev}_W$W
rm -rf $wd; mkdir -p $wd/iSS/results; cd $wd/iSS
cp -P $sub/iSS/iSS.e $sub/iSS/iSS_tables . ; cp $sub/iSS/iSS_parameters.dat .
ln -s $surf results/surface.dat; cp $src/EVENT_RESULTS_$ev/hydro_results_$ev/music_input results/
half=$(python3 -c "print($W/2.0)")
t0=$(date +%s.%N)
./iSS.e randomSeed=20261119 y_LB=-$half y_RB=$half sample_upto_desired_particle_number=0 number_of_repeated_sampling=$NS > run.log 2>&1
t1=$(date +%s.%N)
cd $wd
if [ "$ab" = "SMASH" ]; then
  mkdir -p SMASH/list; cp -P $sub/SMASH/smash SMASH/; cp iSS/OSCAR.DAT SMASH/list/OSCAR.DAT0
  sed "s/Nevents: .*/Nevents: $NS/; s/Randomseed: .*/Randomseed: 20261119/" $sub/SMASH/list/config.yaml > SMASH/list/config.yaml
  cd SMASH; unset PYTHIA8DATA
  /usr/bin/time -f "%e %U %M" -o ../time.txt ./smash -i list/config.yaml > run.log 2>&1
  cd ..; out=SMASH/data/0/particles_oscar2013_extended.bin; kind=smash
else
  mkdir -p urqmd osc2u; cp -P $sub/urqmd/urqmd.e $sub/urqmd/runqmd.sh $sub/urqmd/uqmd.burner $sub/urqmd/tables.dat urqmd/ 2>/dev/null; cp -P $sub/osc2u/osc2u.e osc2u/
  cd osc2u; ./osc2u.e < ../iSS/OSCAR.DAT > run.log 2>&1; mv fort.14 ../urqmd/OSCAR.input; cd ../urqmd
  /usr/bin/time -f "%e %U %M" -o ../time.txt ./runqmd.sh > run.log 2>&1
  cd ..; $src/hadronic_afterburner_toolkit/convert_to_binary.e urqmd/particle_list.dat binary > convert.log 2>&1
  out=urqmd/particle_list.bin; kind=urqmd
fi
python3 $base/profile.py $kind $out $wd/profile.npz 6 0.25 > profile.log 2>&1
echo "$ab ev$ev W=$W NS=$NS iSS $(python3 -c "print(round($t1-$t0,1))") s; cascade wall/user/maxRSS(kB): $(cat time.txt 2>/dev/null | tail -1); $(tail -1 profile.log)"
rm -f iSS/OSCAR.DAT SMASH/list/OSCAR.DAT0 urqmd/OSCAR.input urqmd/particle_list.dat urqmd/particle_list.f1*
