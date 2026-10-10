#!/usr/bin/env bash
set -euo pipefail
backend=${1:?backend required}
mkdir -p ci-logs
image="$RUNNER_TEMP/corium-${backend}.img"
truncate -s 2G "$image"
if [[ "$backend" == btrfs ]]; then
  sudo apt-get install -y btrfs-progs
  sudo mkfs.btrfs -f "$image"
  mount_dir="$RUNNER_TEMP/corium-btrfs"
  mkdir -p "$mount_dir"
  sudo mount -o loop "$image" "$mount_dir"
  trap 'sudo umount "$mount_dir"' EXIT
else
  sudo apt-get install -y zfsutils-linux
  sudo modprobe zfs
  sudo zpool create -f corium_ci_pool "$image"
  export CORIUM_ZPOOL=corium_ci_pool
  trap 'sudo zpool destroy corium_ci_pool' EXIT
  mount_dir="$RUNNER_TEMP/corium-zfs-tests"
  mkdir -p "$mount_dir"
fi
# Namespace/storage tests run as root only inside an ephemeral hosted runner.
sudo env PATH="$PATH" TMPDIR="$mount_dir" PYTHONPATH="$PWD" CORIUM_FS_BACKEND="$backend" CORIUM_ZPOOL="${CORIUM_ZPOOL:-}" \
  python3 -m unittest -v ci.test_filesystems 2>&1 | tee "ci-logs/${backend}.log"
