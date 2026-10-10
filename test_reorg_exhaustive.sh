#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/test_helper.sh"
run_python_tests test_reorg
