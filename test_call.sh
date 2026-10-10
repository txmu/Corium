#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"
bash -n "$CORIX_BIN"
# Source without launching CLI/daemons, then require actual production entrypoints.
bash -c 'source "$CORIX_BIN"; for function in blockchain_mine_block _blockchain_reorganize_to _internal_export_chain_state _internal_import_phoenix_state _internal_verify_exodus_quorum _cbb_sync_messages dep_resolve_topological corix_remove _internal_ibc_generate_state_proof; do declare -F "$function" >/dev/null || exit 1; done'
"$CORIX_BIN" --version | grep -q '108'
if CORIUM_NETWORK_ID_OVERRIDE='../escape' "$CORIX_BIN" --version >/dev/null 2>&1; then echo 'FAIL: unsafe network id accepted' >&2; exit 1; fi
echo 'FUNCTION CALL / SOURCE PASS'
