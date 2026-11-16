#!/usr/bin/env bash
set -e

parafile=$1
processId=$2
nHydroEvents=$3
nthreads=$4
nUrqmdSamples=1
seed=$5
# Global event-id offset of this batch: batch k uses ids [k*B, k*B+B-1] so a
# later batch draws events no earlier batch used, while the same id at another
# design point is the identical event (seed_add is a campaign constant).
eventOffset=${6:-0}
output_mode="quiet"

export PYTHONIOENCODING=utf-8
export PATH="${PATH}:/usr/lib64/openmpi/bin:/usr/local/gsl/2.5/x86_64/bin"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/lib:/usr/local/gsl/2.5/x86_64/lib64"

SCRATCH_DIR="${PWD}"
cd "${SCRATCH_DIR}"
export HOME="${SCRATCH_DIR}"
export XDG_DATA_HOME="${HOME}/.local/share"
export XDG_CACHE_HOME="${HOME}/.cache"
export TRENTO_CACHE="${HOME}/.trento"
mkdir -p "${XDG_DATA_HOME}"
mkdir -p "${XDG_CACHE_HOME}"
mkdir -p "${TRENTO_CACHE}"
mkdir -p "${XDG_DATA_HOME}/trento"
export HOME="${SCRATCH_DIR}"
export XDG_DATA_HOME="${HOME}/.local/share"
export XDG_CACHE_HOME="${HOME}/.cache"
export TRENTO_CACHE="${HOME}/.trento"
mkdir -p "${XDG_DATA_HOME}"
mkdir -p "${XDG_CACHE_HOME}"
mkdir -p "${TRENTO_CACHE}"
mkdir -p "${XDG_DATA_HOME}/trento"

if [ ! -f "$(basename "${parafile}")" ] && [ -f "${parafile}" ]; then
    cp "${parafile}" "$(basename "${parafile}")"
fi
if [ ! -f "$(basename "${parafile}")" ]; then
    echo "Missing parameter file in scratch dir: ${parafile}" >&2
    ls -la "${SCRATCH_DIR}" >&2 || true
    exit 1
fi
parafile="$(basename "${parafile}")"

printf "Start time: `/bin/date`\n"
printf "Job is running on node: `/bin/hostname`\n"
printf "system kernel: `uname -r`\n"
printf "Job running as user: `/usr/bin/id`\n"
printf "Working directory: ${SCRATCH_DIR}\n"


seedfile="${7:-}"
seed_name=$(basename "${seedfile:-}")
if [ -n "${seed_name}" ] && [ -f "${seed_name}" ] && [ ! -f "shared_seeds/${seed_name}" ]; then
    mkdir -p shared_seeds
    cp "${seed_name}" "shared_seeds/${seed_name}"
fi
if [ -n "${seed_name}" ] && [ ! -f "shared_seeds/${seed_name}" ]; then
    echo "Seed file missing from sandbox after transfer: ${seedfile:-<unset>}" >&2
    exit 1
fi

event_start_id=$(( eventOffset + processId * nHydroEvents ))
event_end_id=${event_start_id}

/opt/iEBE-MUSIC/generate_jobs.py -w playground -c OSG -par ${parafile} -id ${processId} -n_th ${nthreads} -n_urqmd ${nUrqmdSamples} -n_hydro ${nHydroEvents} -seed ${seed} --event_start_id ${event_start_id} --event_end_id ${event_end_id} --nocopy --continueFlag
status=$?
if [ $status -ne 0 ]; then
    echo "generate_jobs.py failed with exit code ${status}" >&2
    exit $status
fi

event_start_id=${event_start_id:-0}
event_end_id=${event_end_id:-$(( event_start_id + nHydroEvents - 1 ))}

job_event_dirs=()
for (( ev = event_start_id; ev <= event_end_id; ev++ )); do
    candidate="${SCRATCH_DIR}/playground/event_${ev}"
    if [ -d "${candidate}" ] && [ -f "${candidate}/submit_job.script" ]; then
        job_event_dirs+=("${candidate}")
    fi
done

if [ ${#job_event_dirs[@]} -eq 0 ]; then
    echo "Missing event directories for event range ${event_start_id}..${event_end_id}" >&2
    ls -la "${SCRATCH_DIR}/playground" >&2 || true
    exit 1
fi

cleanup_job_scratch() {
    find "${SCRATCH_DIR}" -maxdepth 1 -type f \( -name 'nucleon-seeds_*.hdf' -o -name 'nucleon-seeds.hdf' \) -exec rm -f {} + || true
    rm -f "${SCRATCH_DIR}/nucleon-seeds_*.hdf" "${SCRATCH_DIR}/nucleon-seeds.hdf" || true
}

finalize_job_output() {
    cleanup_job_scratch
    # Batch tag, mirroring the submit-side transfer_output_files entry: batch 1
    # (offset 0) keeps the historical untagged names, later batches add _e<offset>
    # so they can never overwrite an earlier batch's files.
    tag=""
    if [ "${eventOffset}" != "0" ] && [ $((eventOffset % 2000)) -eq 0 ]; then tag="_e${eventOffset}"; fi

    quiet_out_dir="${SCRATCH_DIR}/spvn_results"
    mkdir -p "${quiet_out_dir}"
    find "${SCRATCH_DIR}/playground" -type f \(         -name 'spvn_results_*.h5' -o         -name 'trento_event_summary_*.txt' -o         -name 'grid_extent_*.csv' -o         -name 'target_nucleus.hdf'     \) -exec cp -f {} "${quiet_out_dir}/" \; || true
    # The driver runs once per event, so each event writes its own
    # events_drawn.csv with a single row. Concatenate them into one table per
    # job, keeping the header from the first file only.
    drawn_csv="${quiet_out_dir}/events_drawn${tag}_${processId}.csv"
    rm -f "${drawn_csv}"
    for drawn in $(find "${SCRATCH_DIR}/playground" -type f -name 'events_drawn.csv'); do
        if [ ! -s "${drawn_csv}" ]; then
            cp -f "${drawn}" "${drawn_csv}"
        else
            tail -n +2 "${drawn}" >> "${drawn_csv}"
        fi
    done || true

    if [ "${output_mode}" != "quiet" ]; then
        job_output_tar="${SCRATCH_DIR}/job_output_${processId}.tar.gz"
        job_paths=()
        for (( ev = event_start_id; ev <= event_end_id; ev++ )); do
            if [ -d "${SCRATCH_DIR}/playground/event_${ev}" ]; then
                job_paths+=("playground/event_${ev}")
            fi
        done

        if [ ${#job_paths[@]} -gt 0 ]; then
            tar -czf "${job_output_tar}" -C "${SCRATCH_DIR}" "${job_paths[@]}" || true
        else
            placeholder=".job_output_${processId}_empty"
            : > "${SCRATCH_DIR}/${placeholder}"
            tar -czf "${job_output_tar}" -C "${SCRATCH_DIR}" "${placeholder}" || true
            rm -f "${SCRATCH_DIR}/${placeholder}" || true
        fi
        ls -lh "${job_output_tar}" || true
    else
        # quiet mode: ship the collected results as a single archive (the submit
        # file only lists this file in transfer_output_files)
        ( cd "${SCRATCH_DIR}" && tar czf "spvn_results${tag}_${processId}.tar.gz" spvn_results ) || true
        ls -lh "${SCRATCH_DIR}/spvn_results_${processId}.tar.gz" || true
    fi
}

trap finalize_job_output EXIT

event_fail=0
for event_dir in "${job_event_dirs[@]}"; do
    cd "${event_dir}"
    bash submit_job.script
    status=$?
    if [ $status -ne 0 ]; then
        echo "submit_job.script failed with exit code ${status} in ${event_dir}" >&2
        event_fail=${status}
    fi
done

if [ ${event_fail} -ne 0 ]; then
    exit ${event_fail}
fi
