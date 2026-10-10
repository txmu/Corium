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
fi
CORIUM_ANONYMOUS_BACKEND="$backend" python3 -m unittest -v ci.test_anonymous 2>&1 | tee "ci-logs/anonymous-${backend}.log"
