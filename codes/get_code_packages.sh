#!/usr/bin/env bash

set -euo pipefail

# download the code package

clone_repo_at_commit() {
  local repo_url=$1
  local repo_dir=$2
  local target_commit=$3
  local target_branch=${4:-}

  rm -fr "${repo_dir}"
  if [ -n "${target_branch}" ]; then
    git clone --depth=1 -b "${target_branch}" "${repo_url}" "${repo_dir}"
  else
    git clone --depth=1 "${repo_url}" "${repo_dir}"
  fi
  (
    cd "${repo_dir}"
    git fetch --depth=1 origin "${target_commit}"
    git checkout "${target_commit}"
    test "$(git rev-parse HEAD)" = "${target_commit}"
  )
  rm -fr "${repo_dir}/.git"
}

clone_repo_at_tag() {
  local repo_url=$1
  local repo_dir=$2
  local target_tag=$3

  rm -fr "${repo_dir}"
  git clone --depth=1 -b "${target_tag}" "${repo_url}" "${repo_dir}"
  rm -fr "${repo_dir}/.git"
}

# Every code that this chain modifies is fetched from a fork that carries the
# modification as ordinary commits on its QGP-USP branch -- nothing is patched
# or overlaid here.  To change a component, commit to its fork and bump the
# SHA below.  The forks are:
#   github.com/mluzum/Isobar-Sampler                         (the sampler's home)
#   github.com/IFUSP-Heavy-Ions/{trento,MUSIC,iSS,hadronic_afterburner_toolkit}

# download Isobar-Sampler (used by TRENTo initial conditions)
# QGP-USP = Public_Release bc586de + deterministic (Philox) nucleon seeds, the
# 2.8x faster sampler and event-by-event beta2/beta3/gamma fluctuations; the
# pin adds configuration_stride (one call for the nuclei of many events).
clone_repo_at_commit \
  https://github.com/mluzum/Isobar-Sampler.git \
  isobar_sampler_code \
  b5eab9313f9884ddc97c4d0bcab7152e0345c25f \
  QGP-USP

# download TRENTo (used by TRENTo initial conditions)
# QGP-USP = Duke-QCD/trento 10960b2 + the nucleon-configuration interface
# (4837013, previously fetched from jppicchetti/trento_sync); the pin adds
# --first-event-id, a batch mode that reproduces single-event runs exactly.
clone_repo_at_commit \
  https://github.com/IFUSP-Heavy-Ions/trento.git \
  trento_code \
  54aa4617f81c25aed0ed99e92de361de3dd25f26 \
  QGP-USP

# download 3DMCGlauber
clone_repo_at_commit \
  https://github.com/mluzum/3dMCGlauber \
  3dMCGlauber_code \
  1d9856c6ce2bbad28059ed8815ebdf246aa37cdf

# download IPGlasma
clone_repo_at_commit \
  https://github.com/chunshen1987/ipglasma \
  ipglasma_code \
  bf92fe1758a61acc5cf84dff2428b83570ea81fa \
  ipglasma_jimwlk

# download KoMPoST
clone_repo_at_commit \
  https://github.com/chunshen1987/KoMPoST \
  kompost_code \
  ad5fe9d3b26434bb1d5c29820499ef26808b5a47

# download MUSIC (XSCAPE branch for SMASH/UrQMD compatibility)
# QGP-USP = MUSIC-fluid/MUSIC XSCAPE at cfcc264, unmodified
clone_repo_at_commit \
  https://github.com/IFUSP-Heavy-Ions/MUSIC.git \
  MUSIC_code \
  cfcc26455450588961e81139045dc0eef387437c \
  QGP-USP

# download iSS particle sampler
# QGP-USP = chunshen1987/iSS XSCAPE at d242555 (OSCAR2013 output compatible with
# SMASH) + the PTB (Pratt-Torrieri-Bernhard) delta f: iss_dict['deltaf_model'] = 1
# samples a positive-definite modified equilibrium instead of the linear delta f,
# which the MC_sampling 4 sampler clamps to [-1, 1]; deltaf_model 0 (default) is
# byte-identical to upstream.
clone_repo_at_commit \
  https://github.com/IFUSP-Heavy-Ions/iSS.git \
  iSS_code \
  77d8a3ef441d2ddbf73465908f11c48117867d02 \
  QGP-USP
if ! grep -q "deltaf_model_" iSS_code/src/FSSW.cpp; then
  echo "ERROR: iSS_code does not carry the PTB delta f" >&2
  exit 1
fi

# download photonEmission wrapper
clone_repo_at_commit \
  https://github.com/chunshen1987/photonEmission_hydroInterface \
  photonEmission_hydroInterface_code \
  b80fb78c154cc9131162c8205615faffc86d6a49

# download UrQMD afterburner
clone_repo_at_commit \
  https://Chunshen1987@bitbucket.org/Chunshen1987/urqmd_afterburner.git \
  urqmd_code \
  09eeac28b5861d68d166c1f89b2e97e0a0ebfe8f

# download SMASH afterburner
clone_repo_at_tag \
  https://github.com/smash-transport/smash.git \
  smash_code \
  SMASH-3.2.2

# download and build Pythia8 (required to compile SMASH)
#
# Cloned from the ALICE mirror at an exact commit instead of downloaded from
# pythia.org. Every pythia.org tarball path now returns 404 from CI, including
# the current release, and those paths are not stable anyway -- the previous
# pythia8315.tgz URL worked when this image was last built on 2026-10-08 and
# stopped working afterwards. A git pin is immutable in a way a URL is not.
# The tag is v8315-alice1, i.e. PYTHIA 8.3.15, the version SMASH is built against.
#
# PYTHIA_INSTALL_DIR must remain ${HOME}/pythia8315: compile_code_packages.sh
# hardcodes that path via -DPythia_CONFIG_EXECUTABLE when configuring SMASH.
PYTHIA_REPO="https://github.com/alisw/pythia8.git"
PYTHIA_COMMIT="3c980c58fc8fd2a089e5f3aa40135208463c9b38"  # tag v8315-alice1
PYTHIA_VERSION="pythia8315"
PYTHIA_INSTALL_DIR="${HOME}/${PYTHIA_VERSION}"
if [ ! -f "${PYTHIA_INSTALL_DIR}/bin/pythia8-config" ]; then
    echo "Building Pythia8 (${PYTHIA_VERSION}) in ${PYTHIA_INSTALL_DIR} ..."
    (
        cd /tmp
        rm -rf pythia8-src
        git clone --quiet "${PYTHIA_REPO}" pythia8-src
        cd pythia8-src
        git checkout --quiet "${PYTHIA_COMMIT}"
        test "$(git rev-parse HEAD)" = "${PYTHIA_COMMIT}"
        # Defensive: some CI/container checkouts run with core.fileMode=false,
        # which would leave configure non-executable.
        chmod +x configure
        ./configure --prefix="${PYTHIA_INSTALL_DIR}"
        make -j2
        make install
        cd /tmp
        rm -rf pythia8-src
    )
    if [ ! -f "${PYTHIA_INSTALL_DIR}/bin/pythia8-config" ]; then
        echo "ERROR: Pythia8 install did not produce ${PYTHIA_INSTALL_DIR}/bin/pythia8-config" >&2
        exit 1
    fi
else
    echo "Pythia8 already installed at ${PYTHIA_INSTALL_DIR}, skipping."
fi


# download hadronic afterburner toolkit
# QGP-USP = chunshen1987/hadronic_afterburner_toolkit main at 2326ba2 + the
# boost-invariant (2+1)-d dN/dy: keep every particle and divide by the rapidity
# width iSS sampled the parents from, instead of cutting at an acceptance window
# and dividing by that window. Without this the yield is biased low by the
# daughters that leak outside the window, and it costs ~10x the statistics.
clone_repo_at_commit \
  https://github.com/IFUSP-Heavy-Ions/hadronic_afterburner_toolkit.git \
  hadronic_afterburner_toolkit_code \
  d00b6c95b8e17cad22de45c340a80ed15586f9eb \
  QGP-USP
if ! grep -q "dNdy_normalization_width" hadronic_afterburner_toolkit_code/src/Analysis.cpp; then
  echo "ERROR: hadronic_afterburner_toolkit_code does not carry the boost-invariant dN/dy" >&2
  exit 1
fi

#download deltaf_tables for iSS
(
  cd iSS_code/iSS_tables/deltaf_tables/urqmd
  # Older iSS layouts required downloading these tables; the pinned commit
  # already ships them. Keep backward compatibility by running the script
  # only when it exists.
  if [ -x download_NEoS4D_deltafCoeffs.sh ]; then
    bash download_NEoS4D_deltafCoeffs.sh
  elif [ -f download_NEoS4D_deltafCoeffs.sh ]; then
    bash ./download_NEoS4D_deltafCoeffs.sh
  else
    echo "download_NEoS4D_deltafCoeffs.sh not found; using bundled deltaf tables"
  fi
)

# download nucleus configurations for 3D-Glauber
(cd 3dMCGlauber_code/tables; bash download_nucleusTables.sh;)
# download nucleus configurations for IP-Glasma
(cd ipglasma_code/nucleusConfigurations; bash download_nucleusTables.sh;)
# download essential EOS files for hydro simulations
# SMASH_binary argument provides binary EOS tables required when SMASH is the afterburner
(cd MUSIC_code/EOS; bash download_hotQCD.sh SMASH_binary; bash download_hotQCD.sh; bash download_Neos2D.sh bqs;)