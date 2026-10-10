#!/bin/bash
set -euo pipefail

# Resolve the single production entrypoint without coupling tests to its release name.
resolve_corix() {
    if [[ -n "${CORIX_BIN:-}" ]]; then
        [[ -f "$CORIX_BIN" && -x "$CORIX_BIN" ]] || { echo "CORIX_BIN is not executable: $CORIX_BIN" >&2; return 1; }
        CORIX_BIN=$(realpath "$CORIX_BIN")
    else
        local root candidates=()
        root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
        while IFS= read -r -d '' f; do
            if rg -q 'readonly CORIUM_VERSION="[0-9]+' "$f" 2>/dev/null; then candidates+=("$f"); fi
        done < <(find "$root" -maxdepth 1 -type f -name '*.sh' -print0)
        [[ ${#candidates[@]} -eq 1 ]] || { echo "Expected exactly one executable Corium entrypoint, found ${#candidates[@]}" >&2; printf '%s\n' "${candidates[@]}" >&2; return 1; }
        CORIX_BIN=$(realpath "${candidates[0]}")
    fi
    echo "Using Corium: $CORIX_BIN" >&2
    export CORIX_BIN
}

test_tmpdir() {
    TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/corium-test.XXXXXX")
    if [[ "${CORIUM_TEST_KEEP_TMP:-0}" != 1 ]]; then trap 'rm -rf "$TEST_TMP"' EXIT; fi
    export TEST_TMP CORIUM_ROOT="$TEST_TMP/root" GNUPGHOME="$TEST_TMP/gnupg"
    mkdir -p "$CORIUM_ROOT" "$GNUPGHOME"; chmod 700 "$GNUPGHOME"
}

resolve_corix
test_tmpdir

# Exit 77 means a concrete environment dependency is missing, never a pass.
require_test_runtime() {
    local missing=() dependency
    for dependency in python3 sqlite3 jq openssl curl tar rsync gpg; do
        command -v "$dependency" >/dev/null 2>&1 || missing+=("$dependency")
    done
    if ! python3 -c 'import cryptography' 2>/dev/null; then missing+=("python:cryptography"); fi
    if ((${#missing[@]})); then
        printf 'BLOCKED: missing dependency %s\n' "${missing[@]}" >&2
        exit 77
    fi
}
run_python_tests() {
    require_test_runtime
    PYTHONPATH="$(dirname "$CORIX_BIN")${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest -v "$@"
}
