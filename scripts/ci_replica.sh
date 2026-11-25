#!/usr/bin/env bash
# Run the "Build Test" workflow (.github/workflows/BuildTest.yml) locally: a
# clean clone of one commit, built in a stock ubuntu:24.04 container with the
# workflow's own apt packages and its two build steps.
#
#   scripts/ci_replica.sh [<commit>]      (default HEAD; about 30-40 minutes)
#
# Why: that workflow compiles the chain against the runner's Ubuntu packages,
# not inside our container, so it can fail while the container build and every
# local test pass. From 2026-11-20 to 11-25 it failed on every push (iSS's
# make_hrg_eos.py needs numpy and scipy, which the runner's apt list lacked)
# and nobody noticed. The pre-push hook asks for a passing replica whenever a
# push changes the workflow's inputs (scripts/ci_build_key.sh).
#
# The apt packages are read from the commit's BuildTest.yml, so this cannot
# drift from the workflow. The runner also preinstalls a toolchain (compilers,
# cmake, git, curl, python3); BASE below stands in for it. If the replica fails
# on a tool the runner has, add the tool to BASE, not to the workflow.
#
# On success the key is recorded in <git dir>/ci-replica/<key>.ok; the build log
# is kept as <git dir>/ci-replica/<key>.log either way.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
commit="$(git -C "${REPO_ROOT}" rev-parse --verify -q "${1:-HEAD}^{commit}")" \
    || { echo "no such commit: ${1:-HEAD}" >&2; exit 1; }
key="$("${REPO_ROOT}/scripts/ci_build_key.sh" "${commit}")"
records="$(git -C "${REPO_ROOT}" rev-parse --path-format=absolute --git-common-dir)/ci-replica"
mkdir -p "${records}"
log="${records}/${key}.log"
# what the GitHub ubuntu-24.04 runner image already has and the build uses
# (rsync: the Pythia 8 install step; found missing on the first replica)
BASE="build-essential cmake git curl wget rsync ca-certificates gfortran python3 pkg-config unzip xz-utils file"

pkgs="$(git -C "${REPO_ROOT}" show "${commit}:.github/workflows/BuildTest.yml" \
        | sed -n 's/.*apt-get install \(.*\)$/\1/p' | tr -d '\r' | tr '\n' ' ')"
[[ -n "${pkgs// /}" ]] || { echo "no 'apt-get install' line in BuildTest.yml at ${commit}" >&2; exit 1; }

work="$(mktemp -d "${TMPDIR:-/tmp}/ci_replica_XXXXXX")"
trap 'rm -rf "${work}"' EXIT
git clone -q "${REPO_ROOT}" "${work}/iEBE-MUSIC"
git -C "${work}/iEBE-MUSIC" checkout -q "${commit}"

echo "commit   : ${commit}"
echo "key      : ${key}"
echo "packages : ${pkgs}"
echo "log      : ${log}"
set +e
docker run --rm -v "${work}:/work" -w /work/iEBE-MUSIC/codes \
    -e PKGS="${pkgs}" -e BASE="${BASE}" -e OWNER="$(id -u):$(id -g)" \
    ubuntu:24.04 bash -c '
        trap "chown -R ${OWNER} /work" EXIT
        set -e
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq ${BASE} > /dev/null
        apt-get install -y -qq ${PKGS} > /dev/null
        # the workflow step "Build the iEBE-MUSIC framework"
        ./get_code_packages.sh
        ./compile_code_packages.sh' > "${log}" 2>&1
status=$?
set -e
if [[ ${status} -eq 0 ]]; then
    date -u +%FT%TZ > "${records}/${key}.ok"
    echo "OK: the Build Test replica passed on ${commit}"
else
    echo "FAIL: the Build Test replica failed on ${commit} (exit ${status}); last lines of ${log}:" >&2
    tail -15 "${log}" >&2
    exit 1
fi
