#!/usr/bin/env bash
# Print a key for the inputs of the "Build Test" workflow at one commit:
# .github/workflows/BuildTest.yml (the runner's packages and steps) and the two
# scripts it runs, codes/get_code_packages.sh (every component pin) and
# codes/compile_code_packages.sh. Two commits with the same key run the same
# Build Test. scripts/ci_replica.sh records the key it passed on, and the
# pre-push hook compares keys to decide whether a push needs a replica.
#
#   scripts/ci_build_key.sh [<commit>]      (default HEAD)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
commit="$(git -C "${REPO_ROOT}" rev-parse --verify -q "${1:-HEAD}^{commit}")" \
    || { echo "no such commit: ${1:-HEAD}" >&2; exit 1; }
for f in .github/workflows/BuildTest.yml codes/get_code_packages.sh \
         codes/compile_code_packages.sh; do
    git -C "${REPO_ROOT}" rev-parse -q --verify "${commit}:${f}" || echo "missing ${f}"
done | sha1sum | cut -c1-40
