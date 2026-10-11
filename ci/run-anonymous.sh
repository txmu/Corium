#!/usr/bin/env bash
set -euo pipefail
backend=${1:?backend required}
mkdir -p ci-logs
if [[ "$backend" == tor ]]; then
  sudo apt-get install -y tor
  sudo systemctl stop tor || true
else
  sudo apt-get install -y i2pd
  sudo systemctl stop i2pd || true
  # The Ubuntu profile restricts writes to /var/lib/i2pd; this runner uses disposable datadirs.
  for profile in /etc/apparmor.d/i2pd /etc/apparmor.d/usr.bin.i2pd /etc/apparmor.d/usr.sbin.i2pd; do
    if [[ -f "$profile" ]]; then sudo apparmor_parser -R "$profile"; fi
  done
fi
CORIUM_ANONYMOUS_BACKEND="$backend" python3 -m unittest -v ci.test_anonymous 2>&1 | tee "ci-logs/anonymous-${backend}.log"
