#!/usr/bin/env bash
set -euo pipefail
mkdir -p ci-logs
image="$RUNNER_TEMP/corium-enospc.img"
volume="$RUNNER_TEMP/corium-enospc"
truncate -s 192M "$image"
mkfs.ext4 -F -m 0 "$image"
mkdir -p "$volume"
sudo mount -o loop "$image" "$volume"
trap 'sudo umount "$volume"' EXIT
sudo env PATH="$PATH" PYTHONPATH="$PWD" TMPDIR="$volume" CORIUM_FAULT_VOLUME="$volume" \
  python3 -m unittest -v ci.test_faults 2>&1 | tee ci-logs/faults.log
