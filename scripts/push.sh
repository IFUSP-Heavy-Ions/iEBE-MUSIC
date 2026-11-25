#!/usr/bin/env bash
# Push a commit to a branch of a GitHub remote, then wait for the GitHub Actions
# runs on it and report them. Use this instead of a bare `git push`: the push
# only runs the local pre-push checks, and a failing workflow otherwise shows up
# only as an e-mail -- which is how the Build Test stayed red from 2026-11-20 to
# 11-25 unnoticed.
#
#   scripts/push.sh <remote> <branch> [<commit>]      (commit defaults to HEAD)
#   e.g. scripts/push.sh ifusp QGP-USP
#
# A Dockerfile pin bump is its own commit after the commit it names, and the
# pre-push hook checks that the pin is fetchable, so push the named commit first:
#   scripts/push.sh ifusp QGP-USP HEAD~1 && scripts/push.sh ifusp QGP-USP
#
# Exit status: that of scripts/wait_ci.sh (0 all runs succeeded, 1 a run failed,
# 3 timeout or no runs), or 2 if the push itself failed.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -ge 2 ]] || { sed -n '2,19p' "$0"; exit 2; }
remote="$1"; branch="$2"
sha="$(git -C "${REPO_ROOT}" rev-parse --verify -q "${3:-HEAD}^{commit}")" \
    || { echo "no such commit: ${3:-HEAD}" >&2; exit 2; }
url="$(git -C "${REPO_ROOT}" remote get-url "${remote}")"
slug="$(sed -E 's#^(git@github\.com:|ssh://git@github\.com/|https://github\.com/)##; s#\.git$##' <<<"${url}")"
[[ "${slug}" =~ ^[^/]+/[^/]+$ ]] || { echo "not a GitHub remote: ${url}" >&2; exit 2; }

git -C "${REPO_ROOT}" push "${remote}" "${sha}:refs/heads/${branch}" || exit 2
exec "${REPO_ROOT}/scripts/wait_ci.sh" "${slug}" "${sha}"
