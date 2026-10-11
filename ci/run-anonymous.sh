#!/usr/bin/env bash
set -euo pipefail
backend=${1:?backend required}
mkdir -p ci-logs
if [[ "$backend" == tor ]]; then
  sudo apt-get install -y tor
  sudo systemctl stop tor || true
else
  # Noble's 2.49.0 crashes on current network traffic; use the upstream Noble build.
  i2pd_package="${RUNNER_TEMP:?}/i2pd_2.61.0-1noble1_amd64.deb"
  curl --fail --location --retry 3 --max-time 120 \
    https://github.com/PurpleI2P/i2pd/releases/download/2.61.0/i2pd_2.61.0-1noble1_amd64.deb \
    --output "$i2pd_package"
  printf '%s  %s\n' 5d4138be6cb448c1d59bba8c1e67e99f6cdbfea3e6f8697d3cce0252cfe24cf8 "$i2pd_package" | sha256sum --check -
  sudo apt-get install -y "$i2pd_package"
  i2pd --version
  sudo systemctl stop i2pd || true
  # The Ubuntu profile restricts writes to /var/lib/i2pd; this runner uses disposable datadirs.
  for profile in /etc/apparmor.d/i2pd /etc/apparmor.d/usr.bin.i2pd /etc/apparmor.d/usr.sbin.i2pd; do
    if [[ -f "$profile" ]]; then sudo apparmor_parser -R "$profile"; fi
  done
fi
CORIUM_ANONYMOUS_BACKEND="$backend" python3 -m unittest -v ci.test_anonymous 2>&1 | tee "ci-logs/anonymous-${backend}.log"
