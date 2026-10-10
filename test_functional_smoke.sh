#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"

export CORIUM_TEST_NO_DAEMONS=1 CORIUM_NETWORK_ID_OVERRIDE=functional
export CORIUM_TEST_P2P_PORT=19734 CORIUM_TEST_GATEWAY_PORT=19780

run_ok() {
    local name=$1; shift
    local out
    out=$("$CORIX_BIN" "$@" 2>&1) || { echo "FAIL: $name" >&2; echo "$out" >&2; return 1; }
    echo "PASS: $name"
}

run_ok version --version
run_ok help help
missing=()
for dep in curl git tar sha256sum patch make gcc openssl awk sqlite3 python3 bc jq xxd rsync ip pgrep pkill lsof unzip numfmt getopt timeout; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
done
for module in cryptography stun miniupnpc RestrictedPython sqlparse psutil; do
    python3 -c "import $module" 2>/dev/null || missing+=("python:$module")
done
if ((${#missing[@]})); then printf 'BLOCKED: init requires %s\n' "${missing[@]}" >&2; exit 77; fi
run_ok init init

root="$CORIUM_ROOT"
chain=$(find "$root" -type f -name chain.db -print -quit)
forum=$(find "$root" -type f -name forum.db -print -quit)
dht=$(find "$root" -type f -name dht.db -print -quit)
[[ -f "$chain" && -f "$forum" && -f "$dht" ]] || { echo "FAIL: expected databases missing" >&2; exit 1; }
for db in "$chain" "$forum" "$dht"; do
    [[ "$(sqlite3 "$db" 'PRAGMA integrity_check;')" == ok ]] || { echo "FAIL: sqlite integrity $db" >&2; exit 1; }
done
echo "PASS: database initialization and integrity"

pub=$(find "$root" -type f -name 'identity.key.pub' -print -quit)
[[ -s "$pub" ]] || { echo "FAIL: identity key missing" >&2; exit 1; }
echo "PASS: identity material"
[[ -s "$root/etc/corix/networks/functional/corix.conf" ]] && echo "PASS: configuration" || { echo "FAIL: configuration" >&2; exit 1; }
[[ -d "$root/var/lib/corix" ]] && echo "PASS: persistent state layout" || { echo "FAIL: persistent state" >&2; exit 1; }

[[ -s "$chain" ]] && echo "PASS: blockchain database" || exit 1

if "$CORIX_BIN" p2p add-peer 127.0.0.1:1 >/dev/null 2>&1; then
    echo "FAIL: unreachable P2P peer reported success" >&2; exit 1
fi
echo "PASS: unreachable P2P peer rejected"

sqlite3 "$chain" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null
echo "FUNCTIONAL SMOKE PASS"
