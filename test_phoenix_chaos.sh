#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"
export CORIUM_TEST_SEED="${CORIUM_TEST_SEED:-108}" CORIUM_CHAOS_ROUNDS="${CORIUM_CHAOS_ROUNDS:-8}"
echo "Phoenix chaos seed=$CORIUM_TEST_SEED rounds=$CORIUM_CHAOS_ROUNDS"
run_python_tests test_core.CoreTests.test_phoenix_seeded_derived_chaos test_core.CoreTests.test_phoenix_deterministic_replay_from_corrupted_local_derived_state test_core.CoreTests.test_phoenix_destroy_restore_repeat_and_again
