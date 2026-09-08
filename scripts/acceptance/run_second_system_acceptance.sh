#!/usr/bin/env bash
# =============================================================================
# AIVIDO V2.0.0 — SECOND-SYSTEM ACCEPTANCE RUNNER (macOS / POSIX)
# =============================================================================
# One-command installation + acceptance validation for a completely
# different macOS machine. Validates an extracted Aivido V2 package,
# installs the declared runtime dependencies into a fully isolated
# temporary environment, starts the certified backend, exercises the
# live Unreal bridge with ONE read-only mission, verifies fresh
# screenshot evidence, tests a clean restart, and emits a
# machine-readable acceptance JSON.
#
# Usage (run from this checkout on the second machine):
#
#   ./scripts/acceptance/run_second_system_acceptance.sh \
#       --package /path/to/Aivido-V2.0.0-macOS
#
#   ./scripts/acceptance/run_second_system_acceptance.sh \
#       --package /path/to/Aivido-V2.0.0-macOS \
#       --expected-project AividoHQ \
#       --expected-map /Game/Maps/AividoHQ \
#       --output /path/to/acceptance.json
#
# Phases (mirrors the second-system acceptance contract):
#   01 validate package            11 verify active map
#   02 create isolated runtime env 12 verify UI HTTP
#   03 install runtime deps        13 run doctor
#   04 validate python/runtime     14 run one READ-ONLY mission
#   05 detect Unreal installation  15 wait for terminal mission result
#   06 verify expected UE version  16 validate fresh screenshot/evidence
#   07 start Aivido backend        17 verify no stale evidence
#   08 verify backend health       18 test clean restart
#   09 discover/verify bridge      19 emit machine-readable acceptance JSON
#   10 verify project identity     20 shut down only processes it started
#
# Failure model: every failure record contains stage, code, a human
# readable reason, and a suggested remediation. Codes match the Windows
# runner: UNREAL_NOT_INSTALLED, UNSUPPORTED_UNREAL_VERSION,
# PYTHON_RUNTIME_FAILURE, DEPENDENCY_INSTALL_FAILURE, PORT_COLLISION,
# BACKEND_START_FAILURE, BRIDGE_UNAVAILABLE, WRONG_UNREAL_PROJECT,
# WRONG_ACTIVE_MAP, UI_UNAVAILABLE, DOCTOR_FAILURE, MISSION_TIMEOUT,
# MISSION_FAILURE, STALE_EVIDENCE, SCREENSHOT_INVALID, RESTART_FAILURE,
# PACKAGE_INTEGRITY_FAILURE.
#
# Safety guarantees:
#   - never runs git reset/clean or touches any repository
#   - never kills a process it did not start (command line verified)
#   - never mutates the certified AividoHQ project (mission is
#     read-only: no actor spawns, no level save; only the transient
#     proof PNG is written)
#   - cleans only its own temp dirs and processes; preserves logs on
#     failure
#   - --mock / --mock-scenario support hermetic testing without any
#     live Unreal
#
# Requires: bash 3.2+, Python 3.9+, macOS or any POSIX system.
# =============================================================================
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PACKAGE_PATH=""
BACKEND_PORT=8765
BRIDGE_PORT=6766
BASE_URL=""
EXPECTED_PROJECT=""
EXPECTED_MAP="/Game/Maps/AividoHQ"
UNREAL_EXE_PATH=""
OUTPUT_PATH=""
BACKEND_READY_TIMEOUT_S=120
MISSION_TIMEOUT_S=180
PIP_TIMEOUT_S=600
EVIDENCE_MAX_AGE_MIN=60
KEEP_LOGS=0
SKIP_CLEANUP=0
MOCK=0
MOCK_SCENARIO="success"

usage() {
    cat <<EOF
Usage: $0 --package PATH [options]

  --package PATH            extracted Aivido V2.0.0 macOS package (required)
  --backend-port N          backend HTTP port (default 8765)
  --bridge-port N           Unreal bridge port (default 6766)
  --base-url URL            backend base URL (default http://127.0.0.1:8765)
  --expected-project NAME   expected Unreal project name
  --expected-map PATH       expected active map (default /Game/Maps/AividoHQ)
  --unreal-exe PATH         explicit UnrealEditor path override
  --output PATH             report JSON path (default under reports/second_system/)
  --keep-logs               keep temp dirs and logs
  --skip-cleanup            do not stop tracked processes / remove temp dirs
  --mock                    hermetic mock mode (no python, no live Unreal)
  --mock-scenario NAME      mock scenario (success, bridge-down, ...)
  --help                    this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --package) PACKAGE_PATH="${2:-}"; shift 2 ;;
        --package=*) PACKAGE_PATH="${1#--package=}"; shift ;;
        --backend-port) BACKEND_PORT="${2:-8765}"; shift 2 ;;
        --backend-port=*) BACKEND_PORT="${1#--backend-port=}"; shift ;;
        --bridge-port) BRIDGE_PORT="${2:-6766}"; shift 2 ;;
        --bridge-port=*) BRIDGE_PORT="${1#--bridge-port=}"; shift ;;
        --base-url) BASE_URL="${2:-}"; shift 2 ;;
        --base-url=*) BASE_URL="${1#--base-url=}"; shift ;;
        --expected-project) EXPECTED_PROJECT="${2:-}"; shift 2 ;;
        --expected-project=*) EXPECTED_PROJECT="${1#--expected-project=}"; shift ;;
        --expected-map) EXPECTED_MAP="${2:-/Game/Maps/AividoHQ}"; shift 2 ;;
        --expected-map=*) EXPECTED_MAP="${1#--expected-map=}"; shift ;;
        --unreal-exe) UNREAL_EXE_PATH="${2:-}"; shift 2 ;;
        --unreal-exe=*) UNREAL_EXE_PATH="${1#--unreal-exe=}"; shift ;;
        --output) OUTPUT_PATH="${2:-}"; shift 2 ;;
        --output=*) OUTPUT_PATH="${1#--output=}"; shift ;;
        --keep-logs) KEEP_LOGS=1; shift ;;
        --skip-cleanup) SKIP_CLEANUP=1; shift ;;
        --mock) MOCK=1; shift ;;
        --mock-scenario) MOCK_SCENARIO="${2:-success}"; shift 2 ;;
        --mock-scenario=*) MOCK_SCENARIO="${1#--mock-scenario=}"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "unknown argument: $1"; usage; exit 2 ;;
    esac
done

if [ -z "$PACKAGE_PATH" ]; then
    echo "FAIL: --package is required (path to the extracted Aivido V2.0.0 macOS package)"
    usage
    exit 2
fi

RUN_ID="run_$(date +%Y%m%d-%H%M%S)_$(od -An -N3 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' || echo $$)"
RUN_DIR="${TMPDIR:-/tmp}/aivido-second-system-${RUN_ID}"
ENV_DIR="$RUN_DIR/env"
if [ "$MOCK" -eq 1 ]; then
    VENV_PY="$ENV_DIR/.venv/bin/python"
else
    VENV_PY="$ENV_DIR/.venv/bin/python"
fi
LOGS_DIR="$RUN_DIR/logs"
if [ -n "${AIVIDO_ACCEPTANCE_REPORT_DIR:-}" ]; then
    REPORT_DIR="$AIVIDO_ACCEPTANCE_REPORT_DIR/$RUN_ID"
else
    REPORT_DIR="$REPO_ROOT/reports/second_system/$RUN_ID"
fi
REPORT_FILE=""
STEPS_JSON="$RUN_DIR/steps.json"
FAILURES_JSON="$RUN_DIR/failures.json"
WARNINGS_JSON="$RUN_DIR/warnings.json"
STARTED_JSON="$RUN_DIR/started.json"
PACKAGE_VERSION="unknown"
PACKAGE_SHA=""
BACKEND_LOG_OUT=""
BACKEND_LOG_ERR=""
BACKEND_PID=""
BRIDGE_DOWN=0
UNREAL_VERSION=""
UNREAL_BUILDS_JSON="$RUN_DIR/unreal_builds.json"
ENV_REPORT=""
BRIDGE_REPORT=""
DOCTOR_JSON=""
MISSION_RESULT=""
MISSION_TIMED_OUT=0
BASELINE_EVIDENCE_SHA=""
POST_EVIDENCE=""
CLEANUP_RESULT=""
RUN_STARTED="$(date +%s)"
OS_NAME="$(uname -srm 2>/dev/null || echo unknown)"
RUNNER_VERSION=""
if command -v git >/dev/null 2>&1; then
    RUNNER_VERSION="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "")"
fi

mkdir -p "$RUN_DIR" "$ENV_DIR" "$LOGS_DIR" "$REPORT_DIR"
: > "$STEPS_JSON"
: > "$FAILURES_JSON"
: > "$WARNINGS_JSON"
: > "$STARTED_JSON"

# A working Python interpreter for the runner's own plumbing (report JSON,
# checksums, HTTP fallback).  Resolved once; never assumed to be `python3`.
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys' >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
[ -z "$PY" ] && { echo "FAIL: Python 3.9+ is required for acceptance runner plumbing" >&2; exit 1; }

# Run-state snapshot dir: survives cleanup so the final report can be
# re-emitted after temp removal.
SNAP_DIR="$REPORT_DIR/run_state"
mkdir -p "$SNAP_DIR"

# ---------------------------------------------------------------------------
# Mock scaffolding (hermetic tests only; never touches a live editor)
# ---------------------------------------------------------------------------
mock_value() {
    # shellcheck disable=SC2317
    case "$1" in
        python_ok) echo 1 ;;
        deps_install_ok) echo 1 ;;
        imports_ok) echo 1 ;;
        unreal_builds) echo '[{"label":"5.8","version":"5.8","editor_exe":"/Applications/UE_5.8/Engine/Binaries/Mac/UnrealEditor"}]' ;;
        unreal_version) echo "5.8" ;;
        port_occupied) echo 0 ;;
        backend_healthy) echo 1 ;;
        bridge_reachable) echo 1 ;;
        bridge_ping_ok) echo 1 ;;
        identity_project) echo "AividoHQ" ;;
        active_map) echo "/Game/Maps/AividoHQ" ;;
        ui_ok) echo 1 ;;
        doctor_ok) echo 1 ;;
        mission_ok) echo 1 ;;
        mission_diag) echo "" ;;
        mission_times_out) echo 0 ;;
        evidence_ok) echo 1 ;;
        evidence_diag) echo "" ;;
        baseline_evidence) echo 1 ;;
        restart_ok) echo 1 ;;
        *) echo 0 ;;
    esac
}

init_mock_values() {
    case "${1:-success}" in
        python-runtime-fail) MOCK_V_python_ok=0 ;;
        dep-install-fail)    MOCK_V_deps_install_ok=0 ;;
        unreal-missing)      MOCK_V_unreal_builds=0 ;;
        unsupported-version) MOCK_V_unreal_version="4.27" ;;
        port-collision)      MOCK_V_port_occupied=1 ;;
        backend-fail)        MOCK_V_backend_healthy=0 ;;
        bridge-down)         MOCK_V_bridge_reachable=0; MOCK_V_bridge_ping_ok=0 ;;
        wrong-project)       MOCK_V_identity_project="SomeOtherProject" ;;
        wrong-map)           MOCK_V_active_map="/Game/Maps/NotAivido" ;;
        ui-down)             MOCK_V_ui_ok=0 ;;
        doctor-fail)         MOCK_V_doctor_ok=0 ;;
        mission-timeout)     MOCK_V_mission_times_out=1 ;;
        mission-fail)        MOCK_V_mission_ok=0; MOCK_V_mission_diag="MISSION_FAILED" ;;
        stale-evidence)      MOCK_V_evidence_ok=0; MOCK_V_evidence_diag="EVIDENCE_STALE" ;;
        screenshot-invalid)  MOCK_V_evidence_ok=0; MOCK_V_evidence_diag="EVIDENCE_INVALID" ;;
        restart-fail)        MOCK_V_restart_ok=0 ;;
    esac
}

MOCK_V_python_ok=1; MOCK_V_deps_install_ok=1; MOCK_V_imports_ok=1
MOCK_V_unreal_builds=1; MOCK_V_unreal_version="5.8"; MOCK_V_port_occupied=0
MOCK_V_backend_healthy=1; MOCK_V_bridge_reachable=1; MOCK_V_bridge_ping_ok=1
MOCK_V_identity_project="AividoHQ"; MOCK_V_active_map="/Game/Maps/AividoHQ"
MOCK_V_ui_ok=1; MOCK_V_doctor_ok=1; MOCK_V_mission_ok=1
MOCK_V_mission_diag=""; MOCK_V_mission_times_out=0; MOCK_V_evidence_ok=1
MOCK_V_evidence_diag=""; MOCK_V_baseline_evidence=1; MOCK_V_restart_ok=1
init_mock_values "$MOCK_SCENARIO"

mock_get() {
    case "$1" in
        python_ok) echo "$MOCK_V_python_ok" ;;
        deps_install_ok) echo "$MOCK_V_deps_install_ok" ;;
        imports_ok) echo "$MOCK_V_imports_ok" ;;
        unreal_builds) test "$MOCK_V_unreal_builds" -eq 1 && echo '[{"label":"5.8","version":"5.8","editor_exe":"/Applications/UE_5.8/Engine/Binaries/Mac/UnrealEditor"}]' || echo '[]' ;;
        unreal_version) echo "$MOCK_V_unreal_version" ;;
        port_occupied) echo "$MOCK_V_port_occupied" ;;
        backend_healthy) echo "$MOCK_V_backend_healthy" ;;
        bridge_reachable) echo "$MOCK_V_bridge_reachable" ;;
        bridge_ping_ok) echo "$MOCK_V_bridge_ping_ok" ;;
        identity_project) echo "$MOCK_V_identity_project" ;;
        active_map) echo "$MOCK_V_active_map" ;;
        ui_ok) echo "$MOCK_V_ui_ok" ;;
        doctor_ok) echo "$MOCK_V_doctor_ok" ;;
        mission_ok) echo "$MOCK_V_mission_ok" ;;
        mission_diag) echo "$MOCK_V_mission_diag" ;;
        mission_times_out) echo "$MOCK_V_mission_times_out" ;;
        evidence_ok) echo "$MOCK_V_evidence_ok" ;;
        evidence_diag) echo "$MOCK_V_evidence_diag" ;;
        baseline_evidence) echo "$MOCK_V_baseline_evidence" ;;
        restart_ok) echo "$MOCK_V_restart_ok" ;;
        *) echo 0 ;;
    esac
}

test_mock() {
    # test_mock key default -> echoes the mock value when mock mode
    if [ "$MOCK" -eq 1 ]; then
        mock_get "$1"
    else
        echo "${2:-}"
    fi
}

# ---------------------------------------------------------------------------
# Failure catalog + bookkeeping
# ---------------------------------------------------------------------------
add_failure() {
    local stage="$1" code="$2" reason="$3"
    # dedupe (stage, code)
    if grep -q "\"$stage\".*\"$code\"" "$FAILURES_JSON" 2>/dev/null; then
        return
    fi
    local remediation=""
    case "$code" in
        UNREAL_NOT_INSTALLED) remediation="Install Unreal Engine 5.x through the Epic Games Launcher (or pass --unreal-exe pointing at an existing editor), then re-run acceptance." ;;
        UNSUPPORTED_UNREAL_VERSION) remediation="Aivido V2 requires Unreal Engine 5.x. Install/set the required engine version, or pass --unreal-exe to a UE 5.x editor, then re-run." ;;
        PYTHON_RUNTIME_FAILURE) remediation="Install Python 3.9 or newer (python.org or Homebrew), then re-run; a fresh isolated environment is created on every run." ;;
        DEPENDENCY_INSTALL_FAILURE) remediation="The declared runtime dependencies could not be installed. Check network access to PyPI and pip output in the run logs, then re-run." ;;
        PORT_COLLISION) remediation="Another process is already listening on the Aivido backend port (127.0.0.1:$BACKEND_PORT). Stop that process or free the port, then re-run." ;;
        BACKEND_START_FAILURE) remediation="The Aivido backend did not become healthy. Inspect the backend error log listed in the report, fix the cause, then re-run." ;;
        BRIDGE_UNAVAILABLE) remediation="Open the AividoHQ project in the Unreal Editor with the Aivido bridge running on 127.0.0.1:$BRIDGE_PORT (UA_BRIDGE_PORT overrides are supported), wait for the editor to fully load, then re-run." ;;
        WRONG_UNREAL_PROJECT) remediation="The Unreal Editor has the wrong project open. Open the expected project (see report field unreal.project / pass --expected-project), then re-run." ;;
        WRONG_ACTIVE_MAP) remediation="The active map is not the expected Aivido map. Open the expected map (default /Game/Maps/AividoHQ, override with --expected-map), then re-run." ;;
        UI_UNAVAILABLE) remediation="The Aivido UI is not being served over HTTP. Confirm the backend is healthy (step 8) and that the package contains the UI resources, then re-run." ;;
        DOCTOR_FAILURE) remediation="The Aivido doctor self-test reported failures. Review the doctor JSON in the report logs and fix the flagged checks, then re-run." ;;
        MISSION_TIMEOUT) remediation="The read-only mission did not finish within the allowed time. The editor may be busy or unresponsive; wait for it to idle, increase --mission-timeout, then re-run." ;;
        MISSION_FAILURE) remediation="The read-only mission did not pass. Inspect the mission steps in the report and remediate, then re-run." ;;
        STALE_EVIDENCE) remediation="The proof endpoint served evidence that was not freshly produced by this run. Ensure the editor viewport renders (not minimized/occluded), then re-run." ;;
        SCREENSHOT_INVALID) remediation="The viewport capture/proof is missing, too small, or not a valid PNG. Bring the editor viewport to the foreground, then re-run." ;;
        RESTART_FAILURE) remediation="The clean stop/start cycle failed. Check the backend logs for crash-on-start, free the backend port, then re-run." ;;
        PACKAGE_INTEGRITY_FAILURE) remediation="The extracted package is incomplete or not an Aivido V2 package. Re-extract the package zip and verify the required files, then re-run." ;;
        *) remediation="Inspect the run report and logs, remediate, and re-run acceptance." ;;
    esac
    if [ -s "$FAILURES_JSON" ]; then
        printf ',\n' >> "$FAILURES_JSON"
    fi
    printf '{"stage":"%s","code":"%s","reason":"%s","remediation":"%s"}' \
        "$stage" "$code" "$reason" "$remediation" >> "$FAILURES_JSON"
    echo "  FAIL [$code] $stage: $reason"
}

add_warning() {
    echo "$1" >> "$WARNINGS_JSON"
    echo "  WARN: $1"
}

new_step() {
    local num="$1" name="$2"
    STEP_NUM="$num"
    STEP_NAME="$name"
    STEP_STARTED="$(date +%s)"
}

complete_step() {
    local status="$1" detail="$2"
    local duration=$(( $(date +%s) - STEP_STARTED ))
    printf '{"number":%d,"name":"%s","status":"%s","detail":"%s","duration_s":%d}' \
        "$STEP_NUM" "$STEP_NAME" "$status" "$detail" "$duration" >> "$STEPS_JSON"
    printf '\n' >> "$STEPS_JSON"
    local marker="OK"
    [ "$status" = "FAIL" ] && marker="FAIL"
    [ "$status" = "SKIP" ] && marker="SKIP"
    printf '  [%s] %02d %s: %s\n' "$marker" "$STEP_NUM" "$STEP_NAME" "$detail"
}

# ---------------------------------------------------------------------------
# Portable helpers
# ---------------------------------------------------------------------------
json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr '\n' ' '
}

http_get_status() {
    # echo "STATUS BODY" ; body may contain newlines -> use file when needed
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        local code
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)"
        echo "$code"
        return 0
    fi
    if command -v "$PY" >/dev/null 2>&1; then
        "$PY" - "$url" <<'PYEOF'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
        print(r.status)
except Exception:
    print("000")
PYEOF
    else
        echo "000"
    fi
}

http_body() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -s --max-time 8 "$url" 2>/dev/null
    elif command -v "$PY" >/dev/null 2>&1; then
        "$PY" - "$url" <<'PYEOF'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=8) as r:
        print(r.read().decode("utf-8", "replace"))
except Exception:
    pass
PYEOF
    fi
}

tcp_port_open() {
    local port="$1"
    if command -v "$PY" >/dev/null 2>&1; then
        "$PY" - "$port" <<'PYEOF'
import socket, sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2):
        sys.exit(0)
except Exception:
    sys.exit(1)
PYEOF
        return $?
    fi
    return 1
}

osascript_pid_owner() {
    # Not needed: POSIX cleanup uses ps command lines.
    return 0
}

register_started() {
    local pid="$1" cmdline="$2"
    printf '{"pid":%s,"command_line":"%s"}\n' "$pid" "$(json_escape "$cmdline")" >> "$STARTED_JSON"
}

checker_run() {
    # checker_run <timeout> <tag> args...
    local timeout_s="$1"; shift
    local tag="$1"; shift
    if [ "$MOCK" -eq 1 ]; then
        echo '{}' > "$RUN_DIR/out_${tag}.json"
        echo 0
        return 0
    fi
    local out="$RUN_DIR/out_${tag}.json" err="$RUN_DIR/err_${tag}.log"
    "$VENV_PY" "$REPO_ROOT/scripts/acceptance/second_system_checks.py" "$@" \
        > "$out" 2> "$err" &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited+1))
        if [ "$waited" -ge "$timeout_s" ]; then
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            echo -2
            return 0
        fi
    done
    wait "$pid"
    echo $?
}

invoke_bounded() {
    # invoke_bounded <timeout> <tag> output_var cmd...
    local timeout_s="$1" tag="$2"
    local out="$RUN_DIR/out_${tag}_$(date +%s)_$$.log"
    local err="$RUN_DIR/err_${tag}_$(date +%s)_$$.log"
    shift 2
    "$@" > "$out" 2> "$err" &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited+1))
        if [ "$waited" -ge "$timeout_s" ]; then
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            echo "-2|$out|$err"
            return 0
        fi
    done
    wait "$pid"
    echo "$?|$out|$err"
}

invoke_bounded_detached() {
    # invoke_bounded_detached <tag> cmd...  -> echoes pid
    local tag="$1"
    shift
    local out="$RUN_DIR/out_${tag}_$$.log"
    local err="$RUN_DIR/err_${tag}_$$.log"
    nohup "$@" > "$out" 2> "$err" &
    echo $!
    BACKEND_LOG_OUT="$out"
    BACKEND_LOG_ERR="$err"
}

find_system_python() {
    local cand ver major minor
    for cand in python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            ver="$("$cand" --version 2>&1 | sed -n 's/^Python \([0-9]*\)\.\([0-9]*\).*/\1.\2/p')"
            if [ -n "$ver" ]; then
                major="${ver%%.*}"; minor="${ver#*.}"
                if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; }; then
                    echo "$cand|$ver"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

escape_json_str() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
phase01_validate_package() {
    new_step 1 "validate_package"
    PACKAGE_ROOT="$PACKAGE_PATH"
    if [ ! -d "$PACKAGE_ROOT" ]; then
        add_failure "validate_package" "PACKAGE_INTEGRITY_FAILURE" "package path '$PACKAGE_PATH' does not exist or is not a directory"
        complete_step FAIL "package path missing: $PACKAGE_PATH"
        return
    fi
    local missing=""
    for r in requirements.txt version.json app/served.py; do
        [ ! -f "$PACKAGE_ROOT/$r" ] && missing="$missing $r"
    done
    local has_ui=0
    for m in ui/aivido.html ui/index.html; do
        [ -f "$PACKAGE_ROOT/$m" ] && has_ui=1
    done
    [ "$has_ui" -eq 0 ] && missing="$missing ui/aivido.html|ui/index.html"
    local has_launcher=0
    for l in install-aivido.sh start-aivido.sh install-aivido.ps1; do
        [ -f "$PACKAGE_ROOT/$l" ] && has_launcher=1
    done
    [ "$has_launcher" -eq 0 ] && missing="$missing install-aivido.sh|start-aivido.sh"
    if [ -n "$missing" ]; then
        add_failure "validate_package" "PACKAGE_INTEGRITY_FAILURE" "package missing required file(s):$missing"
        complete_step FAIL "missing:$missing"
        return
    fi
    PACKAGE_VERSION=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version","unknown"))' "$PACKAGE_ROOT/version.json" 2>/dev/null || echo unknown)
    PACKAGE_SHA="$(find "$PACKAGE_ROOT" -type f \( -path '*/\.venv/*' -o -path '*/__pycache__/*' -o -path '*/.git/*' -o -path '*/config/logs/*' -o -path '*/config/runtime/*' \) -prune -o -type f -print 2>/dev/null | sort | while read -r f; do
        rel="${f#"$PACKAGE_ROOT"/}"
        printf '%s:%s\n' "$rel" "$("$PY" -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$f" 2>/dev/null)"
    done | "$PY" -c 'import sys,hashlib; h=hashlib.sha256(); [h.update(l.encode()) for l in sys.stdin]; sys.stdout.write(h.hexdigest())' 2>/dev/null)"
    complete_step PASS "files OK; version=$PACKAGE_VERSION checksum=${PACKAGE_SHA:0:12}..."
}

phase02_create_env() {
    new_step 2 "create_env"
    if [ "$MOCK" -eq 1 ]; then
        mkdir -p "$ENV_DIR/.venv/bin"
        complete_step PASS "isolated env prepared (mock, no venv build)"
        return
    fi
    local py
    py="$(find_system_python)" || {
        add_failure "create_env" "PYTHON_RUNTIME_FAILURE" "no usable Python (>= 3.9) found on PATH"
        complete_step FAIL "Python >= 3.9 not found"
        return
    }
    local cmd="${py%%|*}" ver="${py#*|}"
    if ! "$cmd" -m venv "$ENV_DIR/.venv" > "$RUN_DIR/venv.out.log" 2> "$RUN_DIR/venv.err.log"; then
        add_failure "create_env" "PYTHON_RUNTIME_FAILURE" "venv creation failed (python $cmd); see $RUN_DIR/venv.err.log"
        complete_step FAIL "venv creation failed"
        return
    fi
    if [ ! -x "$VENV_PY" ]; then
        add_failure "create_env" "PYTHON_RUNTIME_FAILURE" "venv python missing at $VENV_PY"
        complete_step FAIL "venv python missing"
        return
    fi
    complete_step PASS "venv created with Python $ver at $VENV_PY"
}

phase03_install_deps() {
    new_step 3 "install_dependencies"
    local req="$PACKAGE_ROOT/requirements.txt"
    if [ ! -f "$req" ]; then
        add_failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "requirements.txt missing in package"
        complete_step FAIL "requirements.txt missing"
        return
    fi
    if [ "$MOCK" -eq 1 ]; then
        if [ "$(mock_get deps_install_ok)" != "1" ]; then
            add_failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "declared runtime dependencies could not be installed (mock)"
            complete_step FAIL "pip install failed (mock)"
            return
        fi
        complete_step PASS "declared runtime dependencies installed (mock)"
        return
    fi
    local r1 r2
    r1="$(invoke_bounded "$PIP_TIMEOUT_S" "pippip" "$VENV_PY" -m pip install --disable-pip-version-check -q --upgrade pip)"
    r2="$(invoke_bounded "$PIP_TIMEOUT_S" "pipreq" "$VENV_PY" -m pip install --disable-pip-version-check -q -r "$req")"
    local code="${r2%%|*}"
    if [ "$code" != "0" ]; then
        local err="${r2#*|}"
        err="${err#*|}"
        add_failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "pip install -r requirements.txt failed (exit $code); see $err"
        complete_step FAIL "pip install exit $code"
        return
    fi
    complete_step PASS "declared runtime dependencies installed"
}

phase04_validate_runtime() {
    new_step 4 "validate_runtime"
    if [ "$MOCK" -eq 1 ]; then
        local py_ok imports_ok
        py_ok="$(mock_get python_ok)"; imports_ok="$(mock_get imports_ok)"
        if [ "$py_ok" != "1" ] || [ "$imports_ok" != "1" ]; then
            add_failure "validate_runtime" "PYTHON_RUNTIME_FAILURE" "isolated Python runtime is not usable (mock)"
            complete_step FAIL "python runtime invalid"
            return
        fi
        complete_step PASS "python + import contract OK (mock)"
        return
    fi
    local rc
    rc="$(checker_run 90 "env" env --ports "$BACKEND_PORT,$((BACKEND_PORT+1))" --bridge-port "$BRIDGE_PORT")"
    local out="$RUN_DIR/out_env.json"
    if [ "$rc" != "0" ] || [ ! -s "$out" ]; then
        add_failure "validate_runtime" "PYTHON_RUNTIME_FAILURE" "runtime probe produced no parseable output (exit $rc); see $RUN_DIR/err_env.log"
        complete_step FAIL "runtime probe unreadable"
        return
    fi
    ENV_REPORT="$(cat "$out")"
    local py_ok imports_ok
    py_ok="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["python"]["ok"])' "$out" 2>/dev/null)"
    imports_ok="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["imports"]["ok"])' "$out" 2>/dev/null)"
    if [ "$py_ok" != "True" ]; then
        add_failure "validate_runtime" "PYTHON_RUNTIME_FAILURE" "isolated Python runtime is not usable"
        complete_step FAIL "python runtime invalid"
        return
    fi
    if [ "$imports_ok" != "True" ]; then
        add_failure "validate_runtime" "DEPENDENCY_INSTALL_FAILURE" "runtime import contract unresolved in isolated environment"
        complete_step FAIL "import contract missing"
        return
    fi
    complete_step PASS "python + import contract OK"
}

phase05_detect_unreal() {
    new_step 5 "detect_unreal"
    local builds=""
    if [ "$MOCK" -eq 1 ]; then
        builds="$(mock_get unreal_builds)"
    elif [ -n "$UNREAL_EXE_PATH" ] && [ -x "$UNREAL_EXE_PATH" ]; then
        local label
        label="$(basename "$(dirname "$(dirname "$(dirname "$(dirname "$UNREAL_EXE_PATH")")")")")"
        builds="[{\"label\":\"${label#UE_}\",\"editor_exe\":\"$UNREAL_EXE_PATH\"}]"
    else
        local line
        line="$("$VENV_PY" "$REPO_ROOT/scripts/aivido_install_check.py" editor 2>/dev/null | tail -n 1)"
        case "$line" in
            EDITOR=*|EDITOR=none)
                if [ "$line" != "EDITOR=none" ] && [[ "$line" != EDITOR=probe_error* ]]; then
                    local payload="${line#EDITOR=}"
                    local label="${payload%%|*}" exe="${payload#*|}"
                    [ "$exe" = "$label" ] && exe=""
                    builds="[{\"label\":\"$label\",\"editor_exe\":\"$exe\"}]"
                fi
                ;;
            *) add_warning "Unreal build probe reported: $line" ;;
        esac
    fi
    echo "$builds" > "$UNREAL_BUILDS_JSON"
    UNREAL_BUILDS="$builds"
    if [ -z "$builds" ] || [ "$builds" = "[]" ]; then
        add_failure "detect_unreal" "UNREAL_NOT_INSTALLED" "no Unreal Engine build found in common macOS locations and no --unreal-exe given"
        complete_step FAIL "no Unreal Editor build detected"
        return
    fi
    complete_step PASS "found: $(echo "$builds" | "$PY" -c 'import json,sys; print(", ".join(b["label"] for b in json.load(sys.stdin)))' 2>/dev/null)"
}

phase06_verify_unreal_version() {
    new_step 6 "verify_unreal_version"
    local version
    if [ "$MOCK" -eq 1 ]; then
        version="$(mock_get unreal_version)"
    else
        version="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[0].get("label",""))' "$UNREAL_BUILDS_JSON" 2>/dev/null)"
    fi
    UNREAL_VERSION="$version"
    local major
    major="$(printf '%s' "$version" | sed -n 's/^\([0-9]*\).*/\1/p')"
    if [ -z "$major" ]; then
        add_failure "verify_unreal_version" "UNSUPPORTED_UNREAL_VERSION" "could not parse UE version from build label '$version'"
        complete_step FAIL "unparseable UE version '$version'"
        return
    fi
    if [ "$major" -lt 5 ]; then
        add_failure "verify_unreal_version" "UNSUPPORTED_UNREAL_VERSION" "detected UE $version; Aivido V2 requires UE 5.x"
        complete_step FAIL "UE $version not supported"
        return
    fi
    complete_step PASS "UE $version supported"
}

phase07_start_backend() {
    new_step 7 "start_backend"
    if [ "$MOCK" -eq 1 ]; then
        if [ "$(mock_get port_occupied)" = "1" ]; then
            add_failure "start_backend" "PORT_COLLISION" "port 127.0.0.1:$BACKEND_PORT occupied by a foreign process (mock)"
            complete_step FAIL "port $BACKEND_PORT in use by foreign process (mock)"
            return
        fi
        BACKEND_PID="424242"
        BACKEND_LOG_OUT="$LOGS_DIR/backend.out.log"
        BACKEND_LOG_ERR="$LOGS_DIR/backend.err.log"
        complete_step PASS "backend started (mock)"
        return
    fi
    if tcp_port_open "$BACKEND_PORT"; then
        add_failure "start_backend" "PORT_COLLISION" "port 127.0.0.1:$BACKEND_PORT occupied by a foreign process"
        complete_step FAIL "port $BACKEND_PORT in use"
        return
    fi
    local pid
    pid="$(invoke_bounded_detached "backend" "$VENV_PY" -m uvicorn app.served:app --host 127.0.0.1 --port "$BACKEND_PORT" --log-level info)"
    pid="$(printf '%s' "$pid" | tr -d ' \n')"
    # invoke_bounded_detached echoes pid and leaves BACKEND_LOG_OUT/ERR set
    BACKEND_PID="$(pgrep -f "uvicorn app.served:app.*--port $BACKEND_PORT" | head -n 1 || echo "$pid")"
    register_started "$BACKEND_PID" "uvicorn app.served:app --port $BACKEND_PORT"
    complete_step PASS "backend spawned pid $BACKEND_PID (isolated env)"
}

phase08_backend_health() {
    new_step 8 "backend_health"
    local healthy=0
    if [ "$MOCK" -eq 1 ]; then
        healthy="$(mock_get backend_healthy)"
    else
        local waited=0
        while [ "$waited" -lt "$BACKEND_READY_TIMEOUT_S" ]; do
            local code body
            code="$(http_get_status "http://127.0.0.1:$BACKEND_PORT/api/status")"
            if [ "$code" = "200" ]; then
                body="$(http_body "http://127.0.0.1:$BACKEND_PORT/api/status")"
                if printf '%s' "$body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
                    healthy=1
                    break
                fi
            fi
            sleep 2
            waited=$((waited+2))
        done
    fi
    if [ "$healthy" != "1" ]; then
        add_failure "backend_health" "BACKEND_START_FAILURE" "backend did not answer /api/status healthy within ${BACKEND_READY_TIMEOUT_S}s (log: $BACKEND_LOG_ERR)"
        complete_step FAIL "backend unhealthy after ${BACKEND_READY_TIMEOUT_S}s"
        return
    fi
    complete_step PASS "/api/status healthy on 127.0.0.1:$BACKEND_PORT"
}

phase09_discover_bridge() {
    new_step 9 "discover_bridge"
    local reachable=0 ping_ok=0 engine=""
    if [ "$MOCK" -eq 1 ]; then
        reachable="$(mock_get bridge_reachable)"
        ping_ok="$(mock_get bridge_ping_ok)"
        engine="5.8.0"
        BRIDGE_REPORT="{\"tcp_ok\":true,\"ping_ok\":$ping_ok,\"engine\":\"$engine\",\"project_name\":\"$(mock_get identity_project)\",\"world_path\":\"$(mock_get active_map)\"}"
    else
        if tcp_port_open "$BRIDGE_PORT"; then
            reachable=1
            local rc
            rc="$(checker_run 60 "bridge" bridge --bridge-host 127.0.0.1 --bridge-port "$BRIDGE_PORT")"
            local out="$RUN_DIR/out_bridge.json"
            if [ "$rc" = "0" ] && [ -s "$out" ]; then
                BRIDGE_REPORT="$(cat "$out")"
                ping_ok="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("ping_ok",False))' "$out" 2>/dev/null)"
                engine="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("engine",""))' "$out" 2>/dev/null)"
            fi
        fi
    fi
    if [ "$reachable" != "1" ] || [ "$ping_ok" != "True" ] && [ "$ping_ok" != "1" ] && [ "$ping_ok" != "true" ]; then
        [ "$MOCK" -eq 1 ] && [ "$ping_ok" = "0" ] || [ "$reachable" = "0" ]
        add_failure "discover_bridge" "BRIDGE_UNAVAILABLE" "Unreal bridge not reachable on 127.0.0.1:$BRIDGE_PORT (is the editor open with the Aivido bridge running?)"
        BRIDGE_DOWN=1
        complete_step FAIL "bridge 127.0.0.1:$BRIDGE_PORT unreachable"
        return
    fi
    complete_step PASS "bridge alive on 127.0.0.1:$BRIDGE_PORT engine=$engine"
}

phase10_project_identity() {
    new_step 10 "project_identity"
    if [ "$BRIDGE_DOWN" -eq 1 ]; then
        complete_step SKIP "bridge unavailable at step 9; root cause reported there"
        return
    fi
    local project
    if [ "$MOCK" -eq 1 ]; then
        project="$(mock_get identity_project)"
    else
        project="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("project_name",""))' "$RUN_DIR/out_bridge.json" 2>/dev/null)"
    fi
    if [ -z "$project" ]; then
        add_failure "project_identity" "WRONG_UNREAL_PROJECT" "bridge did not report a project identity"
        complete_step FAIL "no project identity from bridge"
        return
    fi
    if [ -n "$EXPECTED_PROJECT" ] && [ "$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "$EXPECTED_PROJECT" | tr '[:upper:]' '[:lower:]')" ]; then
        add_failure "project_identity" "WRONG_UNREAL_PROJECT" "editor project '$project' does not match expected '$EXPECTED_PROJECT'"
        complete_step FAIL "project '$project' != expected '$EXPECTED_PROJECT'"
        return
    fi
    complete_step PASS "project=$project"
}

phase11_active_map() {
    new_step 11 "active_map"
    if [ "$BRIDGE_DOWN" -eq 1 ]; then
        complete_step SKIP "bridge unavailable at step 9; root cause reported there"
        return
    fi
    local world_path
    if [ "$MOCK" -eq 1 ]; then
        world_path="$(mock_get active_map)"
    else
        world_path="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("world_path",""))' "$RUN_DIR/out_bridge.json" 2>/dev/null)"
    fi
    case "$world_path" in
        "$EXPECTED_MAP"*) : ;;
        *)
            add_failure "active_map" "WRONG_ACTIVE_MAP" "active map '$world_path' does not start with expected '$EXPECTED_MAP'"
            complete_step FAIL "map '$world_path' != '$EXPECTED_MAP'"
            return
            ;;
    esac
    complete_step PASS "map=$world_path"
}

phase12_ui_http() {
    new_step 12 "ui_http"
    local ok=0 status="000" url="http://127.0.0.1:$BACKEND_PORT/app"
    if [ "$MOCK" -eq 1 ]; then
        status="200"
        [ "$(mock_get ui_ok)" = "1" ] && ok=1
    else
        status="$(http_get_status "$url")"
        if [ "$status" = "200" ]; then
            local body
            body="$(http_body "$url")"
            printf '%s' "$body" | grep -qiE 'Aivido|Director' && ok=1
        fi
    fi
    if [ "$ok" != "1" ]; then
        add_failure "ui_http" "UI_UNAVAILABLE" "$url returned HTTP $status without the Aivido UI marker"
        complete_step FAIL "$url -> HTTP $status"
        return
    fi
    complete_step PASS "$url -> HTTP 200 (UI marker present)"
}

phase13_doctor() {
    new_step 13 "doctor"
    local doctor_path="$PACKAGE_ROOT/scripts/aivido_doctor.py"
    if [ ! -f "$doctor_path" ]; then
        doctor_path="$REPO_ROOT/scripts/aivido_doctor.py"
        add_warning "package has no scripts/aivido_doctor.py; using runner checkout doctor"
    fi
    local doctor_json_path="$REPORT_DIR/doctor.json"
    local exit_code=0
    if [ "$MOCK" -eq 1 ]; then
        local ok
        ok="$(mock_get doctor_ok)"
        DOCTOR_JSON="{\"overall\":\"$([ "$ok" = "1" ] && echo PASS || echo FAIL)\",\"summary\":{\"pass\":13,\"warn\":0,\"fail\":$([ "$ok" = "1" ] && echo 0 || echo 1)},\"checks\":[]}"
        exit_code=$([ "$ok" = "1" ] && echo 0 || echo 1)
        printf '%s' "$DOCTOR_JSON" > "$doctor_json_path"
    else
        local res
        res="$(invoke_bounded 120 "doctor" "$VENV_PY" "$doctor_path" --quick --json)"
        exit_code="${res%%|*}"
        local rest="${res#*|}"
        local err="${rest#*|}"
        local out="${rest%%|*}"
        if [ -f "$out" ]; then
            cp "$out" "$doctor_json_path"
            DOCTOR_JSON="$(cat "$doctor_json_path")"
        fi
    fi
    if [ "$exit_code" != "0" ] || [ -z "$DOCTOR_JSON" ]; then
        add_failure "doctor" "DOCTOR_FAILURE" "doctor exited $exit_code with overall FAIL (report: $doctor_json_path)"
        complete_step FAIL "doctor exit $exit_code"
        return
    fi
    local overall
    overall="$(printf '%s' "$DOCTOR_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("overall",""))' 2>/dev/null)"
    [ "$overall" = "WARN" ] && add_warning "doctor overall WARN"
    complete_step PASS "overall=$overall"
}

phase14_run_mission() {
    new_step 14 "mission"
    BASELINE_EVIDENCE_SHA=""
    if [ "$MOCK" -eq 1 ]; then
        if [ "$(mock_get baseline_evidence)" = "1" ]; then
            BASELINE_EVIDENCE_SHA="baseline-sha-placeholder"
        fi
        if [ "$(mock_get mission_times_out)" = "1" ]; then
            MISSION_TIMED_OUT=1
            add_failure "mission" "MISSION_TIMEOUT" "read-only mission exceeded the ${MISSION_TIMEOUT_S}s bound (mock)"
            complete_step FAIL "mission timed out"
            return
        fi
        local br_ok mission_ok diag
        br_ok="$(mock_get bridge_reachable)"; mission_ok="$(mock_get mission_ok)"
        diag="$(mock_get mission_diag)"
        [ "$br_ok" != "1" ] && diag="BRIDGE_UNAVAILABLE"
        MISSION_RESULT="{\"overall\":\"$([ "$br_ok" = "1" ] && [ "$mission_ok" = "1" ] && echo PASS || echo FAIL)\",\"diag\":\"$diag\",\"mission_id\":\"second_system_mock\",\"steps\":[{\"name\":\"bridge_tcp\",\"status\":\"$([ "$br_ok" = "1" ] && echo PASS || echo FAIL)\",\"detail\":\"mock\"},{\"name\":\"viewport_capture\",\"status\":\"$([ "$mission_ok" = "1" ] && echo PASS || echo FAIL)\",\"detail\":\"mock\"}],\"evidence\":{\"path\":\"$LOGS_DIR/mock_evidence.png\",\"mtime\":$RUN_STARTED,\"size\":2048,\"ok\":$mission_ok}}"
        complete_step PASS "mission launched (mock)"
        return
    fi
    # Baseline evidence snapshot BEFORE the mission (for the stale check)
    local rc
    rc="$(checker_run 60 "baseline" evidence --base-url "http://127.0.0.1:$BACKEND_PORT")"
    local out="$RUN_DIR/out_baseline.json"
    if [ "$rc" = "0" ] && [ -s "$out" ]; then
        BASELINE_EVIDENCE_SHA="$("$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["detail"].get("sha256","") if d.get("overall")=="PASS" else "")' "$out" 2>/dev/null)"
    fi
    local mission_json="$RUN_DIR/mission.json"
    local checker="$REPO_ROOT/scripts/acceptance/second_system_checks.py"
    "$VENV_PY" "$checker" mission --bridge-host 127.0.0.1 --bridge-port "$BRIDGE_PORT" --expected-map "$EXPECTED_MAP" \
        > "$mission_json" 2> "$RUN_DIR/mission.err.log" &
    local pid=$!
    register_started "$pid" "second_system_checks.py mission"
    local waited=0
    local finished=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited+1))
        if [ "$waited" -ge "$MISSION_TIMEOUT_S" ]; then
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            MISSION_TIMED_OUT=1
            add_failure "mission" "MISSION_TIMEOUT" "read-only mission exceeded the ${MISSION_TIMEOUT_S}s bound"
            complete_step FAIL "mission timed out after ${MISSION_TIMEOUT_S}s"
            return
        fi
    done
    wait "$pid"
    complete_step PASS "mission completed (exit $?)"
}

phase15_mission_result() {
    new_step 15 "mission_result"
    if [ "$MISSION_TIMED_OUT" -eq 1 ]; then
        complete_step SKIP "mission timed out at step 14; no terminal result produced"
        return
    fi
    local overall diag
    if [ "$MOCK" -eq 1 ]; then
        overall="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["overall"])' 2>/dev/null)"
        diag="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("diag",""))' 2>/dev/null)"
    else
        local mission_json="$RUN_DIR/mission.json"
        if [ ! -s "$mission_json" ]; then
            add_failure "mission_result" "MISSION_FAILURE" "mission produced no terminal result JSON (log: $mission_json)"
            complete_step FAIL "no mission result"
            return
        fi
        MISSION_RESULT="$(cat "$mission_json")"
        overall="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("overall",""))' 2>/dev/null)"
        diag="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("diag",""))' 2>/dev/null)"
    fi
    if [ "$overall" != "PASS" ]; then
        case "$diag" in
            BRIDGE_UNAVAILABLE*)
                if ! grep -q '"discover_bridge"' "$FAILURES_JSON" 2>/dev/null; then
                    add_failure "mission_result" "BRIDGE_UNAVAILABLE" "mission could not reach the bridge: $diag"
                fi ;;
            CAPTURE_FAILED*) add_failure "mission_result" "SCREENSHOT_INVALID" "mission viewport capture failed: $diag" ;;
            *) add_failure "mission_result" "MISSION_FAILURE" "mission overall FAIL: $diag" ;;
        esac
        complete_step FAIL "mission overall=$overall diag=$diag"
        return
    fi
    complete_step PASS "mission_id=$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["mission_id"])' 2>/dev/null) overall=PASS"
}

phase16_evidence_fresh() {
    new_step 16 "evidence_fresh"
    local capture_path="" min_mtime=0
    if [ -n "$MISSION_RESULT" ]; then
        capture_path="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; m=json.load(sys.stdin); print(m["evidence"].get("path") or "")' 2>/dev/null)"
        min_mtime="$(printf '%s' "$MISSION_RESULT" | "$PY" -c 'import json,sys; m=json.load(sys.stdin); print(m["evidence"].get("mtime") or 0)' 2>/dev/null)"
    fi
    local ok=0 diag=""
    if [ "$MOCK" -eq 1 ]; then
        ok="$(mock_get evidence_ok)"
        diag="$(mock_get evidence_diag)"
        POST_EVIDENCE="{\"overall\":\"$([ "$ok" = "1" ] && echo PASS || echo FAIL)\",\"diag\":\"$diag\",\"detail\":{\"sha256\":\"$([ "$ok" = "1" ] && echo post-sha-placeholder || echo bad-sha)\",\"bytes\":2048,\"path\":\"$capture_path\"}}"
    else
        local args=("$VENV_PY" "$REPO_ROOT/scripts/acceptance/second_system_checks.py" evidence --base-url "http://127.0.0.1:$BACKEND_PORT" --max-age-minutes "$EVIDENCE_MAX_AGE_MIN")
        [ -n "$capture_path" ] && args+=(--expected-path "$capture_path")
        if [ -n "$min_mtime" ] && [ "$min_mtime" != "0" ] && [ "$min_mtime" != "0.0" ]; then
            args+=(--min-mtime "$min_mtime")
        fi
        local out="$RUN_DIR/out_evidence.json"
        "${args[@]}" > "$out" 2> "$RUN_DIR/err_evidence.log"
        if [ -s "$out" ]; then
            POST_EVIDENCE="$(cat "$out")"
            ok="$(printf '%s' "$POST_EVIDENCE" | "$PY" -c 'import json,sys; print(1 if json.load(sys.stdin).get("overall")=="PASS" else 0)' 2>/dev/null)"
            diag="$(printf '%s' "$POST_EVIDENCE" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("diag") or "")' 2>/dev/null)"
        else
            diag="EVIDENCE_MISSING"
        fi
    fi
    if [ "$ok" != "1" ]; then
        case "$diag" in
            EVIDENCE_STALE*) add_failure "evidence_fresh" "STALE_EVIDENCE" "served evidence is stale: $diag" ;;
            *) add_failure "evidence_fresh" "SCREENSHOT_INVALID" "evidence invalid or missing: $diag" ;;
        esac
        complete_step FAIL "evidence check failed ($diag)"
        return
    fi
    local sha
    sha="$(printf '%s' "$POST_EVIDENCE" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["detail"].get("sha256",""))' 2>/dev/null)"
    complete_step PASS "fresh evidence validated (sha=$sha)"
}

phase17_no_stale_evidence() {
    new_step 17 "no_stale_evidence"
    local post_sha=""
    if [ -n "$POST_EVIDENCE" ]; then
        post_sha="$(printf '%s' "$POST_EVIDENCE" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["detail"].get("sha256",""))' 2>/dev/null)"
    fi
    if [ -n "$BASELINE_EVIDENCE_SHA" ] && [ -n "$post_sha" ] && [ "$BASELINE_EVIDENCE_SHA" = "$post_sha" ]; then
        add_failure "no_stale_evidence" "STALE_EVIDENCE" "evidence unchanged from the pre-mission baseline (served sha identical)"
        complete_step FAIL "evidence sha identical to baseline"
        return
    fi
    local note="no pre-mission baseline"
    [ -n "$BASELINE_EVIDENCE_SHA" ] && note="baseline superseded"
    complete_step PASS "$note"
}

phase18_restart() {
    new_step 18 "restart"
    local ok=1
    if [ "$MOCK" -eq 1 ]; then
        ok="$(mock_get restart_ok)"
    elif [ -n "$BACKEND_PID" ]; then
        # Stop our own backend only (registered in STARTED_JSON).
        kill "$BACKEND_PID" 2>/dev/null
        local waited=0
        while tcp_port_open "$BACKEND_PORT" && [ "$waited" -lt 30 ]; do
            sleep 1
            waited=$((waited+1))
        done
        if tcp_port_open "$BACKEND_PORT"; then
            add_failure "restart" "RESTART_FAILURE" "backend port $BACKEND_PORT still occupied after stopping our own backend"
            complete_step FAIL "port not released after stop"
            return
        fi
        local pid
        pid="$(invoke_bounded_detached "backend2" "$VENV_PY" -m uvicorn app.served:app --host 127.0.0.1 --port "$BACKEND_PORT" --log-level info)"
        BACKEND_PID="$(pgrep -f "uvicorn app.served:app.*--port $BACKEND_PORT" | head -n 1 || echo "$pid")"
        register_started "$BACKEND_PID" "uvicorn app.served:app --port $BACKEND_PORT"
        local waited2=0
        ok=0
        while [ "$waited2" -lt "$BACKEND_READY_TIMEOUT_S" ]; do
            local code body
            code="$(http_get_status "http://127.0.0.1:$BACKEND_PORT/api/status")"
            if [ "$code" = "200" ]; then
                body="$(http_body "http://127.0.0.1:$BACKEND_PORT/api/status")"
                if printf '%s' "$body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
                    ok=1
                    break
                fi
            fi
            sleep 2
            waited2=$((waited2+2))
        done
        if [ "$ok" != "1" ]; then
            add_failure "restart" "RESTART_FAILURE" "backend not healthy after clean restart"
            complete_step FAIL "unhealthy after restart"
            return
        fi
    fi
    if [ "$ok" != "1" ]; then
        add_failure "restart" "RESTART_FAILURE" "clean stop/start cycle failed"
        complete_step FAIL "restart cycle failed"
        return
    fi
    complete_step PASS "clean stop/start cycle healthy"
}

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
steps_json_array() {
    "$PY" - "$STEPS_JSON" <<'PYEOF'
import json, sys
rows = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
print(json.dumps(rows))
PYEOF
}

failures_json_array() {
    "$PY" - "$FAILURES_JSON" <<'PYEOF'
import json, sys
rows = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    data = line
    if data.startswith(","):
        data = data[1:]
    while data.endswith(","):
        data = data[:-1]
    try:
        rows.append(json.loads(data))
    except Exception:
        try:
            rows.append(json.loads("[" + data + "]"))
        except Exception:
            pass
print(json.dumps(rows))
PYEOF
}

warnings_json_array() {
    "$PY" - "$WARNINGS_JSON" <<'PYEOF'
import json, sys
rows = [line.strip() for line in open(sys.argv[1]) if line.strip()]
print(json.dumps(rows))
PYEOF
}

started_json_array() {
    "$PY" - "$STARTED_JSON" <<'PYEOF'
import json, sys
rows = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
print(json.dumps(rows))
PYEOF
}

build_report() {
    local fail_count
    fail_count="$("$PY" -c 'import json,sys; print(len(json.loads(sys.stdin.read())))' <<< "$(failures_json_array)" 2>/dev/null || echo 0)"
    local verdict="PASS"
    [ "$fail_count" != "0" ] && verdict="FAIL"
    local ui_status="000"
    [ "$MOCK" -eq 1 ] && ui_status="200" || ui_status="$(http_get_status "http://127.0.0.1:$BACKEND_PORT/app")"
    "$PY" - "$REPORT_FILE" "$RUN_ID" "$OS_NAME" "$PACKAGE_ROOT" "$PACKAGE_VERSION" "$PACKAGE_SHA" \
        "$BACKEND_PORT" "$BRIDGE_PORT" "$UNREAL_VERSION" "$UNREAL_BUILDS_JSON" "$BRIDGE_REPORT" \
        "$DOCTOR_JSON" "$MISSION_RESULT" "$POST_EVIDENCE" "$ui_status" "$verdict" "$RUN_STARTED" \
        "$REPO_ROOT" "$RUNNER_VERSION" "$BACKEND_PID" "$BACKEND_LOG_OUT" "$BACKEND_LOG_ERR" "$BASE_URL" \
        <<'PYEOF'
import json, os, sys, time

(REPORT_FILE, RUN_ID, OS_NAME, PACKAGE_ROOT, PACKAGE_VERSION, PACKAGE_SHA,
 BACKEND_PORT, BRIDGE_PORT, UNREAL_VERSION, UNREAL_BUILDS_JSON, BRIDGE_REPORT,
 DOCTOR_JSON, MISSION_RESULT, POST_EVIDENCE, UI_STATUS, VERDICT, RUN_STARTED,
 REPO_ROOT, RUNNER_VERSION, BACKEND_PID, BACKEND_LOG_OUT, BACKEND_LOG_ERR,
 BASE_URL) = sys.argv[1:]

def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def parse(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default

def jsonl_array(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip(",")
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows

def steps_array():
    return jsonl_array(os.path.join(os.environ.get("RUN_DIR", ""), "steps.json"))

def failures_array():
    return jsonl_array(os.path.join(os.environ.get("RUN_DIR", ""), "failures.json"))

def warnings_array():
    try:
        with open(os.path.join(os.environ.get("RUN_DIR", ""), "warnings.json"), encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def started_array():
    return jsonl_array(os.path.join(os.environ.get("RUN_DIR", ""), "started.json"))

RUN_DIR_ENV = os.environ.get("RUN_DIR", "")
steps = steps_array()
failures = failures_array()
warnings = warnings_array()
started = started_array()
unreal_builds = load(UNREAL_BUILDS_JSON, [])
bridge = parse(BRIDGE_REPORT, {}) or {}
doctor = parse(DOCTOR_JSON, {}) or {}
mission = parse(MISSION_RESULT, {}) or {}
evidence = parse(POST_EVIDENCE, {}) or {}
base_url = BASE_URL or f"http://127.0.0.1:{BACKEND_PORT}"

failed = [f for f in failures]
report = {
    "runner": "run_second_system_acceptance.sh",
    "runner_version": RUNNER_VERSION or "unknown",
    "run_id": RUN_ID,
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "machine": os.uname().nodename if hasattr(os, "uname") else "unknown",
    "os": OS_NAME,
    "package_path": PACKAGE_ROOT,
    "package_version": PACKAGE_VERSION,
    "package_sha": PACKAGE_SHA,
    "backend": {
        "port": int(BACKEND_PORT),
        "healthy": not any(f.get("stage") == "backend_health" for f in failed),
        "pid": int(BACKEND_PID) if str(BACKEND_PID).isdigit() else None,
        "log_out": BACKEND_LOG_OUT,
        "log_err": BACKEND_LOG_ERR,
    },
    "bridge": {
        "host": "127.0.0.1",
        "port": int(BRIDGE_PORT),
        "reachable": not any(f.get("stage") == "discover_bridge" for f in failed),
        "ping_ok": not any(f.get("stage") == "discover_bridge" for f in failed),
        "engine": bridge.get("engine", ""),
    },
    "unreal": {
        "installed_builds": unreal_builds,
        "detected_version": UNREAL_VERSION,
        "supported": not any(f.get("code") in ("UNREAL_NOT_INSTALLED", "UNSUPPORTED_UNREAL_VERSION") for f in failed),
        "project": bridge.get("project_name", ""),
        "map": bridge.get("world_path", ""),
    },
    "ui": {
        "url": f"{base_url}/app",
        "http_status": UI_STATUS,
        "ok": not any(f.get("stage") == "ui_http" for f in failed),
    },
    "doctor": {
        "overall": doctor.get("overall", "not_run"),
        "summary": doctor.get("summary"),
        "json_path": os.path.join(REPORT_FILE and os.path.dirname(REPORT_FILE) or "", "doctor.json"),
    },
    "mission": {
        "id": mission.get("mission_id", ""),
        "result": mission.get("overall", "not_run"),
        "diag": mission.get("diag", ""),
        "steps": mission.get("steps", []),
        "evidence": mission.get("evidence"),
    },
    "evidence": {
        "path": (evidence.get("detail") or {}).get("path", ""),
        "bytes": (evidence.get("detail") or {}).get("bytes", 0),
        "sha256": (evidence.get("detail") or {}).get("sha256", ""),
        "validated": evidence.get("overall") == "PASS",
        "age_minutes": (evidence.get("detail") or {}).get("age_minutes"),
    },
    "restart": {
        "ok": not any(f.get("stage") == "restart" for f in failed),
    },
    "duration_s": round(time.time() - float(RUN_STARTED), 1),
    "warnings": warnings,
    "failures": failures,
    "steps": steps,
    "final_verdict": VERDICT,
    "cleanup": json.loads(os.environ.get("CLEANUP_RESULT", "{}") or "{}"),
}
with open(REPORT_FILE, "w") as f:
    json.dump(report, f, indent=2, default=str)
PYEOF
}

emit_report() {
    new_step 19 "report"
    local report_file
    if [ -n "$OUTPUT_PATH" ]; then
        REPORT_FILE="$OUTPUT_PATH"
    else
        REPORT_FILE="$REPORT_DIR/acceptance.json"
    fi
    export RUN_DIR
    build_report
    local verdict
    verdict="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["final_verdict"])' "$REPORT_FILE" 2>/dev/null)"
    printf '\n==============================================\n'
    printf ' AIVIDO V2 SECOND-SYSTEM ACCEPTANCE %s\n' "$verdict"
    printf ' run_id   : %s\n' "$RUN_ID"
    printf ' package  : %s (%s...)\n' "$PACKAGE_VERSION" "${PACKAGE_SHA:0:12}"
    printf ' report   : %s\n' "$REPORT_FILE"
    complete_step PASS "acceptance JSON written to $REPORT_FILE"
}

# ---------------------------------------------------------------------------
# Cleanup (only our own processes + temp dirs)
# ---------------------------------------------------------------------------
runner_cleanup() {
    local stopped="" refused=""
    if [ -f "$STARTED_JSON" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local pid cmdline
            pid="$(printf '%s' "$line" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["pid"])' 2>/dev/null)"
            cmdline="$(printf '%s' "$line" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["command_line"])' 2>/dev/null)"
            [ -z "$pid" ] && continue
            if ! kill -0 "$pid" 2>/dev/null; then
                continue
            fi
            local ps_line
            ps_line="$(ps -p "$pid" -o command= 2>/dev/null || echo "")"
            case "$ps_line" in
                *"$VENV_PY"*|*"second_system_checks.py mission"*|*"uvicorn app.served:app"*)
                    kill "$pid" 2>/dev/null
                    stopped="$stopped $pid"
                    ;;
                *)
                    refused="$refused $pid"
                    add_warning "refusing to stop pid $pid: command line does not match anything this runner started"
                    ;;
            esac
        done < "$STARTED_JSON"
    fi
    local removed=""
    if [ "$KEEP_LOGS" -eq 1 ] || [ "$SKIP_CLEANUP" -eq 1 ]; then
        removed="kept $RUN_DIR"
    else
        # Snapshot run state so the final report can still be rebuilt
        # after the temp dir is removed.
        mkdir -p "$SNAP_DIR"
        for f in "$STEPS_JSON" "$FAILURES_JSON" "$WARNINGS_JSON" \
                 "$STARTED_JSON" "$UNREAL_BUILDS_JSON"; do
            [ -f "$f" ] && cp "$f" "$SNAP_DIR/" 2>/dev/null
        done
        rm -rf "$RUN_DIR" 2>/dev/null
        removed="removed $RUN_DIR"
        STEPS_JSON="$SNAP_DIR/steps.json"
        FAILURES_JSON="$SNAP_DIR/failures.json"
        WARNINGS_JSON="$SNAP_DIR/warnings.json"
        STARTED_JSON="$SNAP_DIR/started.json"
        UNREAL_BUILDS_JSON="$SNAP_DIR/unreal_builds.json"
        RUN_DIR="$SNAP_DIR"
        export RUN_DIR
    fi
    CLEANUP_RESULT="{\"stopped\":\"$stopped\",\"refused\":\"$refused\",\"temp_dirs\":\"$removed\"}"
    export CLEANUP_RESULT
}

phase20_cleanup() {
    new_step 20 "cleanup"
    runner_cleanup
    complete_step PASS "stopped processes:$CLEANUP_RESULT"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
BASE_URL="${BASE_URL:-http://127.0.0.1:$BACKEND_PORT}"
if [ -n "${AIVIDO_UNREAL_ENGINE_DIR:-}" ] && [ -z "$UNREAL_EXE_PATH" ]; then
    UNREAL_EXE_PATH="$AIVIDO_UNREAL_ENGINE_DIR"
fi

printf '==============================================\n'
printf ' AIVIDO V2.0.0 - SECOND-SYSTEM ACCEPTANCE (macOS)\n'
printf ' run id    : %s\n' "$RUN_ID"
printf ' machine   : %s\n' "$OS_NAME"
printf ' package   : %s\n' "$PACKAGE_PATH"
printf ' mock      : %s (%s)\n' "$([ "$MOCK" -eq 1 ] && echo yes || echo no)" "$MOCK_SCENARIO"
printf '==============================================\n'

phase01_validate_package
if [ ! -s "$FAILURES_JSON" ]; then
    phase02_create_env
    phase03_install_deps
    phase04_validate_runtime
    phase05_detect_unreal
    phase06_verify_unreal_version
    phase07_start_backend
    phase08_backend_health
    phase09_discover_bridge
    phase10_project_identity
    phase11_active_map
    phase12_ui_http
    phase13_doctor
    phase14_run_mission
    phase15_mission_result
    phase16_evidence_fresh
    phase17_no_stale_evidence
    phase18_restart
fi

emit_report
if [ "$SKIP_CLEANUP" -ne 1 ]; then
    phase20_cleanup
    # re-emit report with cleanup results
    export RUN_DIR
    build_report
fi

local_fail=$("$PY" -c 'import json,sys; print(len(json.loads(sys.stdin.read())))' <<< "$(failures_json_array)" 2>/dev/null || echo 0)
if [ "$local_fail" != "0" ]; then
    printf '\nSECOND_SYSTEM_ACCEPTANCE FAIL\n'
    exit 1
fi
printf '\nSECOND_SYSTEM_ACCEPTANCE PASS\n'
exit 0