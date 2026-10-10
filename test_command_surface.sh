#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"
export CORIUM_TEST_NO_DAEMONS=1 CORIUM_NETWORK_ID_OVERRIDE=surface
export CORIUM_TEST_P2P_PORT=19834 CORIUM_TEST_GATEWAY_PORT=19880

help=$($CORIX_BIN --help)
commands=(install remove upgrade sync search info rebuild autoremove site wiki forum user group broadcast message mail maillist find validator work consensus compute governance network build strata snapshot backup key identity acl stop clean init status gen-build alias service theme exodus)
for command in "${commands[@]}"; do
    grep -Eq "(^|[[:space:]])${command}([[:space:]]|\(|$)" <<<"$help" || { echo "FAIL: command missing from help: $command" >&2; exit 1; }
done
echo "PASS: all public commands documented (${#commands[@]})"

if "$CORIX_BIN" __definitely_unknown_command__ >/dev/null 2>&1; then
    echo "FAIL: unknown command accepted" >&2; exit 1
fi
echo "PASS: unknown command rejected"

for option in --version --help; do
    "$CORIX_BIN" "$option" >/dev/null || { echo "FAIL: global option $option" >&2; exit 1; }
done
echo "PASS: global options"
echo "COMMAND SURFACE PASS"
