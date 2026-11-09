#!/bin/sh
# The restore agent supplies the captured job file; a standby must not create one.
set -eu
if [ "${SNAPSHOT_RESTORE_STANDBY:-${DYN_SNAPSHOT_RESTORE_STANDBY:-0}}" = 1 ]; then
    exec sleep infinity
fi
: "${SNAPSHOT_CONTROL_DIR:?Snapshot control volume is required}"
exec /snapshot-bootstrap/cuda-checkpoint --launch-job /bin/sh /snapshot-bootstrap/persist-job.sh "$@"
