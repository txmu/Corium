#!/usr/bin/env bash
set -euo pipefail
pm=${1:?PM required}
mkdir -p ci-logs
if [[ "$pm" == pip || "$pm" == npm ]]; then
  CORIUM_PM_REPORT="$PWD/ci-logs" bash ci/test-external-pm.sh "$pm" 2>&1 | tee "ci-logs/external-${pm}.log"
  exit
fi
if [[ "$pm" == pkgsrc ]]; then
  sudo apt-get install -y build-essential libncurses-dev zlib1g-dev libssl-dev
  work="$RUNNER_TEMP/pkgsrc-native"
  mkdir -p "$work"
  curl --fail --location --retry 3 https://cdn.netbsd.org/pub/pkgsrc/current/pkgsrc.tar.gz | tar -xz -C "$work"
  (cd "$work/pkgsrc/bootstrap"; ./bootstrap --unprivileged --prefix "$work/pkg" --workdir "$work/bootstrap-work")
  export PATH="$work/pkg/bin:$work/pkg/sbin:$PATH"
  CORIUM_PM_REPORT="$PWD/ci-logs" bash ci/test-external-pm.sh "$pm" 2>&1 | tee "ci-logs/external-${pm}.log"
  exit
fi
case "$pm" in
  apt) image=ubuntu:24.04; install='apt-get update && apt-get install -y bash coreutils findutils python3 jq openssl curl' ;;
  pacman) image=archlinux:base; install='pacman -Syu --noconfirm python jq openssl curl diffutils' ;;
  dnf) image=fedora:43; install='dnf install -y bash coreutils findutils python3 jq openssl curl diffutils' ;;
  portage) image=gentoo/stage3:latest; install='emerge --sync && emerge --ask=n app-portage/gentoolkit app-misc/jq' ;;
  xbps) image=ghcr.io/void-linux/void-glibc-full:latest; install='xbps-install -Suy && xbps-install -y bash coreutils findutils python3 jq openssl curl diffutils' ;;
  zypper) image=opensuse/leap:15.6; install='zypper --non-interactive install bash coreutils findutils python3 jq openssl curl diffutils' ;;
  *) exit 2 ;;
esac
docker run --rm -v "$PWD:/work" -w /work -e CORIUM_PM_REPORT=/work/ci-logs "$image" \
  sh -c "$install && bash ci/test-external-pm.sh '$pm'" 2>&1 | tee "ci-logs/external-${pm}.log"
