#!/bin/sh
# Follow Snapshot v0.1.0's source-job contract, retaining one stable CUDA job.
set -eu
: "${CUDA_CHECKPOINT_JOB_FILE:?R610 launch-job did not supply a CUDA job file}"
: "${SNAPSHOT_CONTROL_DIR:?Snapshot control volume is required}"
test -s "$CUDA_CHECKPOINT_JOB_FILE"
umask 077
job_file="$SNAPSHOT_CONTROL_DIR/cuda-checkpoint-job"
# A source job must never silently reuse/overwrite another job's identity.
set -C
cat "$CUDA_CHECKPOINT_JOB_FILE" > "$job_file"
set +C
export CUDA_CHECKPOINT_JOB_FILE="$job_file"
echo "SNAPSHOT_CUDA_JOB_PERSISTED $job_file" >&2
exec "$@"
