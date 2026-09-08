#!/usr/bin/env bash
# =============================================================================
# AIVIDO — acceptance-runner hermetic self-test (mock scenarios)
# =============================================================================
# Validates run_second_system_acceptance.sh end-to-end in --mock mode:
#   - the success scenario passes all 20 phases
#   - every failure scenario FAILS with the exact expected diagnostic code
# No live Unreal, no backend, no network: fully hermetic.
#
# Usage:  bash scripts/acceptance/acceptance_runner_selftest.sh <package_root>
# Exit 0 = all scenarios behave as specified.
# =============================================================================
set -u

PACKAGE="${1:-}"
if [ -z "$PACKAGE" ] || [ ! -d "$PACKAGE" ]; then
    echo "Usage: $0 <extracted-package-root>"
    exit 2
fi
RUNNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_second_system_acceptance.sh"

pass=0
fail=0

run_case() {
    local name="$1" scenario="$2" expect="$3" code="$4"
    local out
    out="$("$RUNNER" --package "$PACKAGE" --mock --mock-scenario "$scenario" \
        --expected-project AividoHQ --expected-map /Game/Maps/AividoHQ \
        --output "${TMPDIR:-/tmp}/aivido-selftest-$scenario.json" 2>&1)"
    local rc=$?
    local verdict
    verdict="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["final_verdict"])' \
        "${TMPDIR:-/tmp}/aivido-selftest-$scenario.json" 2>/dev/null || echo unreadable)"
    local codes_ok=1
    if [ -n "$code" ]; then
        if ! grep -q "\"$code\"" "${TMPDIR:-/tmp}/aivido-selftest-$scenario.json" 2>/dev/null; then
            codes_ok=0
        fi
    fi
    if [ "$verdict" = "$expect" ] && [ "$codes_ok" -eq 1 ]; then
        echo "PASS  $name (verdict=$verdict code=$code)"
        pass=$((pass+1))
    else
        echo "FAIL  $name (verdict=$verdict expected=$expect code=$code found)"
        fail=$((fail+1))
    fi
}

run_case "success path"          "success"            "PASS" ""
run_case "python runtime fail"   "python-runtime-fail" "FAIL" "PYTHON_RUNTIME_FAILURE"
run_case "dep install fail"      "dep-install-fail"    "FAIL" "DEPENDENCY_INSTALL_FAILURE"
run_case "unreal missing"        "unreal-missing"      "FAIL" "UNREAL_NOT_INSTALLED"
run_case "unsupported version"   "unsupported-version" "FAIL" "UNSUPPORTED_UNREAL_VERSION"
run_case "port collision"        "port-collision"      "FAIL" "PORT_COLLISION"
run_case "backend fail"          "backend-fail"        "FAIL" "BACKEND_START_FAILURE"
run_case "bridge down"           "bridge-down"         "FAIL" "BRIDGE_UNAVAILABLE"
run_case "wrong project"         "wrong-project"       "FAIL" "WRONG_UNREAL_PROJECT"
run_case "wrong map"             "wrong-map"           "FAIL" "WRONG_ACTIVE_MAP"
run_case "ui down"               "ui-down"             "FAIL" "UI_UNAVAILABLE"
run_case "doctor fail"           "doctor-fail"         "FAIL" "DOCTOR_FAILURE"
run_case "mission timeout"       "mission-timeout"     "FAIL" "MISSION_TIMEOUT"
run_case "mission fail"          "mission-fail"        "FAIL" "MISSION_FAILURE"
run_case "stale evidence"        "stale-evidence"      "FAIL" "STALE_EVIDENCE"
run_case "screenshot invalid"    "screenshot-invalid"  "FAIL" "SCREENSHOT_INVALID"
run_case "restart fail"          "restart-fail"        "FAIL" "RESTART_FAILURE"

echo ""
echo "selftest: $pass pass / $fail fail"
[ "$fail" -eq 0 ]