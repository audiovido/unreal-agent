#!/usr/bin/env bash
# =============================================================================
# AIVIDO V2.0.0 — macOS CONTROL LAUNCHER
# =============================================================================
#
#   ./start-aivido.sh start      start persistent backend (default)
#   ./start-aivido.sh stop       stop backend (bridge/gateway untouched)
#   ./start-aivido.sh restart    stop then start
#   ./start-aivido.sh status     state + health + log paths
#   ./start-aivido.sh doctor     full self-test (PASS/WARN/FAIL)
#   ./start-aivido.sh ui         open http://127.0.0.1:8765/app
#   ./start-aivido.sh logs       print log paths
#
# Bootstrap: if no .venv exists, run install-aivido.sh automatically.
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

COMMAND="${1:-start}"

VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PY" ]; then
    echo "No .venv found - running installer bootstrap..."
    if ! ./install-aivido.sh --no-start; then
        exit 1
    fi
fi
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PY" ]; then
    echo "FAIL: installer did not produce a .venv python" >&2
    exit 1
fi

invoke() {
    "$VENV_PY" "$ROOT/scripts/aivido_runtime.py" "$@"
    exit $?
}

case "$COMMAND" in
    start)
        "$VENV_PY" "$ROOT/scripts/aivido_runtime.py" start || exit 1
        if command -v open >/dev/null 2>&1; then
            open "http://127.0.0.1:8765/app" >/dev/null 2>&1 || true
        fi
        exit 0
        ;;
    stop)    invoke stop ;;
    restart) invoke restart ;;
    status)  invoke status ;;
    ui)      invoke ui ;;
    logs)    invoke logs ;;
    doctor)
        shift
        "$VENV_PY" "$ROOT/scripts/aivido_doctor.py" "$@"
        exit $?
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Commands: start stop restart status ui logs doctor"
        exit 1
        ;;
esac