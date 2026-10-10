#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"
export CORIUM_TEST_SEED="${CORIUM_TEST_SEED:-108}" CORIUM_SOAK_ROUNDS="${CORIUM_SOAK_ROUNDS:-8}"
echo "Mixed soak seed=$CORIUM_TEST_SEED rounds=$CORIUM_SOAK_ROUNDS"
run_python_tests test_soak
