#!/usr/bin/env bash
# Backwards-compatible entry: every invocation now checks every module.
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/check_all_formal.sh" "$@"
