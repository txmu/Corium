#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y sqlite3 bc xxd shellcheck bubblewrap jq rsync iproute2 procps lsof unzip curl git tar patch make gcc openssl gpg ripgrep socat xdelta3 python3-venv libminiupnpc-dev
python3 -m venv "$RUNNER_TEMP/corium-venv"
"$RUNNER_TEMP/corium-venv/bin/pip" install cryptography pystun3 miniupnpc RestrictedPython sqlparse psutil
printf '%s\n' "$RUNNER_TEMP/corium-venv/bin" >> "$GITHUB_PATH"
# Hosted Ubuntu 24.04 restricts unprivileged user namespaces via AppArmor.
if [[ -f /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]]; then
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
fi
