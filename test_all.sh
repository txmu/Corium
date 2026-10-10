#!/bin/bash
set -uo pipefail
root=$(cd "$(dirname "$0")" && pwd)
logs=${CORIUM_TEST_LOG_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/corium-suite.XXXXXX")}
mkdir -p "$logs"
failed=0;blocked=0;passed=0
: > "$logs/summary.tsv"
for test in test_call.sh test_command_surface.sh test_functional_smoke.sh test_core_regression.sh test_phoenix_adversarial.sh test_phoenix_chaos.sh test_reorg_exhaustive.sh test_soak_long_running.sh; do
    echo "RUN $test"
    bash "$root/$test" > "$logs/$test.log" 2>&1; status=$?
    case "$status" in
        0) result=PASS; passed=$((passed+1));;
        77) result=BLOCKED; blocked=$((blocked+1));;
        *) result=FAIL; failed=$((failed+1));;
    esac
    printf '%s\t%s\t%s\n' "$test" "$result" "$status" | tee -a "$logs/summary.tsv"
    if ((status!=0)); then tail -n 25 "$logs/$test.log"; fi
done
printf 'RESULT passed=%s blocked=%s failed=%s logs=%s\n' "$passed" "$blocked" "$failed" "$logs"
((failed==0)) || exit 1
((blocked==0)) || exit 77
