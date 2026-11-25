#!/usr/bin/env bash

Green='\033[0;32m'
NC='\033[0m'

CCFlag=$1
CXXFlag=$2
FCFlag=$3

if [ -z "$CCFlag" ]; then
    CCFlag=gcc
fi
if [ -z "$CXXFlag" ]; then
    CXXFlag=g++
fi
if [ -z "$FCFlag" ]; then
    FCFlag=gfortran
fi

machine="$(uname -s)"
case "${machine}" in
    Linux*)     number_of_cores=`nproc --all`;;
    Darwin*)    number_of_cores=`sysctl -n hw.ncpu`;;
    *)          number_of_cores=1;;
esac
number_of_cores_to_compile=$(( ${number_of_cores} > 2 ? 2 : ${number_of_cores} ))


# compile TRENTo
echo -e "${Green}compile TRENTo ... ${NC}"
(
    cd trento_code
    rm -fr build
    mkdir -p build
    cd build
    # TRENTo declares cmake_minimum_required(VERSION 3.4), and CMake 4 refuses
    # anything below 3.5.  The policy floor lets it configure unchanged; CMake 3
    # ignores the variable.
    cmake .. -DNATIVE=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi



# validate Isobar-Sampler (Python package, no compilation needed)
echo -e "${Green}validate Isobar-Sampler ... ${NC}"
for script in isobar_sampler_code/exec/build_isobars.py isobar_sampler_code/exec/make_seeds.py; do
    if [ ! -f "$script" ]; then
        echo "Error: $script not found. Run get_code_packages.sh first."
        exit 1
    fi
done
echo -e "${Green}Isobar-Sampler OK${NC}"



# compile 3dMCGlauber
echo -e "${Green}compile 3dMCGlauber ... ${NC}"
(
    cd 3dMCGlauber_code
    ./get_LHAPDF.sh
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake .. -Dlink_with_lib=OFF
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi

# compile IPGlasma
echo -e "${Green}compile IPGlasma ... ${NC}"
(
    cd ipglasma_code
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake .. -DdisableMPI=ON
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi

# compile KoMPoST
echo -e "${Green}compile KoMPoST ... ${NC}"
(
    cd kompost_code
    CXX=${CXXFlag} make
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi

# compile MUSIC
echo -e "${Green}compile MUSIC ... ${NC}"
(
    cd MUSIC_code
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake .. -Dlink_with_lib=OFF
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi
mkdir -p MUSIC
if [ -f MUSIC_code/example_inputfiles/IPGlasma_2D/music_input_mode_2 ]; then
    cp MUSIC_code/example_inputfiles/IPGlasma_2D/music_input_mode_2 MUSIC/
elif [ -f MUSIC_code/example_inputfiles/2D_IPGlasma/IPGlasma_2D_testEvent/music_input_mode_2 ]; then
    cp MUSIC_code/example_inputfiles/2D_IPGlasma/IPGlasma_2D_testEvent/music_input_mode_2 MUSIC/
else
    echo "Error: could not find MUSIC music_input_mode_2 template"
    exit 1
fi
cp MUSIC_code/utilities/sweeper.sh MUSIC/
(cd MUSIC; mkdir -p initial)

# compile photonEmission_hydroInterface
echo -e "${Green}compile photonEmission_hydroInterface ... ${NC}"
(
    cd photonEmission_hydroInterface_code
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake ..
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi

# download iSS particle sampler
echo -e "${Green}compile iSS ... ${NC}"
(
    cd iSS_code
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake .. -Dlink_with_lib=OFF
    make -j${number_of_cores_to_compile}
    make install
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi

# download UrQMD afterburner
echo -e "${Green}compile UrQMD ... ${NC}"
(
    cd urqmd_code
    FC=${FCFlag} make -j${number_of_cores_to_compile}
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi
mkdir -p osc2u
cp urqmd_code/osc2u/osc2u.e osc2u/
mkdir -p urqmd
cp urqmd_code/urqmd/runqmd.sh urqmd/
cp urqmd_code/urqmd/uqmd.burner urqmd/


# compile SMASH
echo -e "${Green}compile SMASH ... ${NC}"
(
cd smash_code
rm -fr build
# SMASH adds -march=native unconditionally, with no option to turn it off, in
# its own CMakeLists.txt and in those of the bundled Cuba and einhard, so the
# binary carries whatever the build host supports. Built on a Zen 2 host it
# held ~94k VEX (AVX2/FMA/BMI2) instructions and died with "Illegal
# instruction" on x86-64-v2 workers, ~9% of OSPool slots (7 of 30 jobs of the
# 2026-11-25 pbpb5020-eos pilot). Build it for the baseline like every other
# code here (0 VEX instructions), and refuse to go on if a SMASH update brings
# the flag back some other way.
grep -rl --include=CMakeLists.txt -e '"-march=native"' . \
    | xargs -r sed -i 's/"-march=native"//'
mkdir -p build && cd build
CC=${CCFlag} CXX=${CXXFlag} cmake \
        -DPythia_CONFIG_EXECUTABLE="${HOME}/pythia8315/bin/pythia8-config" \
        -DTRY_USE_HEPMC=OFF \
        ..
if grep -rq --include=flags.make -e "-march=native" .; then
    echo "SMASH would still be built with -march=native:" >&2
    grep -rl --include=flags.make -e "-march=native" . >&2
    exit 1
fi
    make -j${number_of_cores_to_compile} smash
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi
mkdir -p smash
cp smash_code/build/smash smash/



# download hadronic afterner
echo -e "${Green}compile hadronic afterburner toolkit ... ${NC}"
(
    cd hadronic_afterburner_toolkit_code
    rm -fr build
    mkdir -p build
    cd build
    CC=${CCFlag} CXX=${CXXFlag} cmake .. -Dlink_with_lib=OFF
    make -j${number_of_cores_to_compile}
    make install
    cd ../ebe_scripts
    ${CXXFlag} convert_to_binary.cpp -lz -o convert_to_binary.e
    mv convert_to_binary.e ../
    ${CXXFlag} concatenate_binary_files.cpp -lz -o concatenate_binary_files.e
    mv concatenate_binary_files.e ../
)
status=$?
if [ $status -ne 0 ]; then
    exit $status
fi
mkdir -p hadronic_afterburner_toolkit
cp hadronic_afterburner_toolkit_code/convert_to_binary.e hadronic_afterburner_toolkit/
cp hadronic_afterburner_toolkit_code/concatenate_binary_files.e hadronic_afterburner_toolkit/
cp hadronic_afterburner_toolkit_code/parameters.dat hadronic_afterburner_toolkit/
cp hadronic_afterburner_toolkit_code/ebe_scripts/average_event_HBT_correlation_function.py hadronic_afterburner_toolkit/

# Every binary has to run on any x86-64 worker, and OSPool still has
# x86-64-v2 slots (no AVX2). A VEX-encoded (AVX) instruction means a build
# picked up the build host's instruction set, as SMASH's -march=native did
# (2026-11-25: "Illegal instruction" on 7 of 30 pilot jobs).
if command -v objdump >/dev/null 2>&1 && command -v file >/dev/null 2>&1; then
    vex_bad=0
    while IFS= read -r -d '' f; do
        file -b "$f" | grep -q '^ELF' || continue
        n=$(objdump -d --no-show-raw-insn "$f" 2>/dev/null \
            | grep -cE '^\s+[0-9a-f]+:\s+v[a-z0-9]+\s')
        if [ "$n" -gt 0 ]; then
            echo "not portable: $f has $n VEX (AVX) instructions" >&2
            vex_bad=1
        fi
    done < <(find . \( -name CMakeFiles -o -name .git \) -prune -o -type f \
                \( -perm -u+x -o -name '*.so' -o -name '*.so.*' \) -print0)
    if [ $vex_bad -ne 0 ]; then
        exit 1
    fi
    echo -e "${Green}instruction-set check: no AVX in any binary${NC}"
else
    echo "objdump or file missing: skipping the instruction-set check" >&2
fi
