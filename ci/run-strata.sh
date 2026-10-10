#!/usr/bin/env bash
set -euo pipefail
pm=${1:?PM required}
mkdir -p ci-logs
case "$pm" in
  apt) image=debian:bookworm; sudo apt-get install -y debootstrap ;;
  pacman)
    image=archlinux:base
    sudo apt-get install -y arch-install-scripts pacman-package-manager
    sudo mkdir -p /etc/pacman.d
    echo 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch' | sudo tee /etc/pacman.d/mirrorlist
    ;;
  dnf) image=fedora:43; sudo apt-get install -y dnf rpm ;;
  portage) image=gentoo/stage3:latest ;;
  *) exit 2 ;;
esac
docker pull "$image"
container=$(docker create "$image")
trap 'docker rm -f "$container" >/dev/null' EXIT
archive="$RUNNER_TEMP/corium-${pm}-rootfs.tar"
docker export "$container" --output "$archive"
if [[ "$pm" == pacman ]]; then
  docker cp "$container:/etc/pacman.conf" "$RUNNER_TEMP/pacman.conf"
  sudo cp "$RUNNER_TEMP/pacman.conf" /etc/pacman.conf
  docker cp "$container:/etc/pacman.d/gnupg" "$RUNNER_TEMP/pacman-gnupg"
  sudo cp -a "$RUNNER_TEMP/pacman-gnupg" /etc/pacman.d/gnupg
fi
sudo env PATH="$PATH" PYTHONPATH="$PWD" CORIUM_STRATA_PM="$pm" CORIUM_STRATA_ROOTFS="$archive" \
  python3 -m unittest -v ci.test_strata 2>&1 | tee "ci-logs/strata-${pm}.log"
