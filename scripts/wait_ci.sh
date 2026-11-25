#!/usr/bin/env bash
# Wait for every GitHub Actions run on one commit and report how each ended.
#
#   scripts/wait_ci.sh <owner/repo> <commit sha>
#
# CI_WAIT_MINUTES (default 90) bounds the wait; the container build takes about
# 15 minutes and the Build Test 10-40. Exit 0 if every run succeeded (or was
# skipped), 1 if any failed (its failing log lines are printed), 3 if no run
# appeared within 3 minutes or they did not finish in time.
set -uo pipefail
slug="$1"; sha="$2"
limit_min="${CI_WAIT_MINUTES:-90}"
start=$(date +%s)
fields=databaseId,workflowName,status,conclusion,url
last=""
while :; do
    runs="$(gh run list -R "${slug}" --commit "${sha}" --json "${fields}" 2>/dev/null || echo '[]')"
    n="$(jq length <<<"${runs}")"
    now=$(date +%s)
    if [[ "${n}" -eq 0 ]]; then
        if (( now - start > 180 )); then
            echo "CI: no workflow run on ${sha} after 3 minutes (${slug})" >&2
            exit 3
        fi
        sleep 15; continue
    fi
    state="$(jq -r '.[] | "\(.workflowName): \(if .status == "completed" then .conclusion else .status end)"' <<<"${runs}" | sort)"
    if [[ "${state}" != "${last}" ]]; then
        echo "CI $(date +%H:%M:%S):"; sed 's/^/  /' <<<"${state}"; last="${state}"
    fi
    pending="$(jq '[.[] | select(.status != "completed")] | length' <<<"${runs}")"
    if [[ "${pending}" -eq 0 ]]; then
        failed="$(jq -r '.[] | select(.conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral") | .databaseId' <<<"${runs}")"
        if [[ -z "${failed}" ]]; then
            echo "CI: all ${n} runs on ${sha:0:7} succeeded"
            exit 0
        fi
        for id in ${failed}; do
            echo "CI: run ${id} failed: $(jq -r --argjson i "${id}" '.[] | select(.databaseId == $i) | .url' <<<"${runs}")" >&2
            gh run view "${id}" -R "${slug}" --log-failed 2>/dev/null | tail -15 >&2
        done
        exit 1
    fi
    if (( now - start > limit_min*60 )); then
        echo "CI: runs on ${sha:0:7} still pending after ${limit_min} minutes" >&2
        exit 3
    fi
    sleep 30
done
