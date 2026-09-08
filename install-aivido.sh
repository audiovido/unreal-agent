#!/usr/bin/env bash
# =============================================================================
# AIVIDO V2.0.0 — macOS INSTALLER (portable, second-system safe)
# =============================================================================
# Installs Aivido V2.0.0 on macOS from the extracted package directory.
#
#   ./install-aivido.sh                 one-click install + start
#   ./install-aivido.sh --no-start      install only, do not start the backend
#   ./install-aivido.sh --no-browser    start without opening the UI
#   ./install-aivido.sh --upgrade       force dependency reinstall
#   ./install-aivido.sh --project PATH  pin a .uproject
#
# Idempotent: a second run reuses the existing .venv and skips dependency
# installation when the import contract is already satisfied.
#
# No sudo. Everything lives inside the package directory (.venv, config/).
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

NO_START=0
NO_BROWSER=0
UPGRADE=0
PROJECT=""

for arg in "$@"; do
    case "$arg" in
        --no-start) NO_START=1 ;;
        --no-browser) NO_BROWSER=1 ;;
        --upgrade)  UPGRADE=1 ;;
        --project)  PROJECT="${2:-}" ;;
        --project=*) PROJECT="${arg#--project=}" ;;
        -h|--help)
            echo "Usage: ./install-aivido.sh [--no-start] [--no-browser] [--upgrade] [--project PATH]"
            exit 0 ;;
        *) ;;
    esac
done

step()  { printf '\n==> %s\n' "$1"; }
ok()    { printf '    %s\n' "$1"; }
warn()  { printf '    WARN: %s\n' "$1"; }
fail()  { printf '    FAIL: %s\n' "$1"; }

# ---------------------------------------------------------------------------
# 1. Python (3.9+)
# ---------------------------------------------------------------------------
step "1/8 Python"
PYTHON=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver="$("$cand" --version 2>&1 | sed -n 's/^Python \([0-9]*\)\.\([0-9]*\).*/\1.\2/p')"
        if [ -n "$ver" ]; then
            major="${ver%%.*}"
            minor="${ver#*.}"
            if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; }; then
                PYTHON="$cand"
                ok "Python $ver via '$cand'"
                break
            else
                warn "'$cand' is Python $ver (need >= 3.9)"
            fi
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    fail "no usable Python (>= 3.9) found. Install from https://www.python.org/downloads/ and re-run."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. .venv (package-local)
# ---------------------------------------------------------------------------
step "2/8 Virtual environment"
if [ ! -x "$ROOT/.venv/bin/python" ] && [ ! -x "$ROOT/.venv/Scripts/python.exe" ]; then
    ok "creating .venv (first run)"
    if ! "$PYTHON" -m venv "$ROOT/.venv"; then
        fail "could not create .venv"
        exit 1
    fi
else
    ok ".venv exists - reusing"
fi
# macOS venv layout: .venv/bin/python ; Windows layout: .venv/Scripts/python.exe
VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PY" ]; then
    fail ".venv python not found (looked for bin/python and Scripts/python.exe)"
    exit 1
fi

CHECKER="$ROOT/scripts/aivido_install_check.py"

# ---------------------------------------------------------------------------
# 3. Requirements (idempotent)
# ---------------------------------------------------------------------------
step "3/8 Dependencies (idempotent)"
NEED_INSTALL=0
if [ "$UPGRADE" -eq 1 ]; then
    NEED_INSTALL=1
else
    if ! "$VENV_PY" "$CHECKER" imports >/dev/null 2>&1; then
        NEED_INSTALL=1
    fi
fi
if [ "$NEED_INSTALL" -eq 1 ]; then
    ok "installing requirements.txt"
    "$VENV_PY" -m pip install --disable-pip-version-check -q --upgrade pip || {
        fail "pip upgrade failed"; exit 1; }
    "$VENV_PY" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements.txt" || {
        fail "dependency installation failed; see pip output above"; exit 1; }
else
    ok "import contract satisfied - no reinstall"
fi

# ---------------------------------------------------------------------------
# 4. Import validation
# ---------------------------------------------------------------------------
step "4/8 Import validation"
if ! "$VENV_PY" "$CHECKER" imports; then
    fail "runtime imports still broken after install"
    exit 1
fi
ok "all runtime imports resolve"

# ---------------------------------------------------------------------------
# 5. Unreal Editor detection (read-only)
# ---------------------------------------------------------------------------
step "5/8 Unreal Editor"
EDITOR_LINE="$("$VENV_PY" "$CHECKER" editor 2>&1 | tail -n 1)"
case "$EDITOR_LINE" in
    EDITOR=none)
        warn "no Unreal Editor detected (fine when an editor is already open on the bridge)"
        ;;
    EDITOR=probe_error*)
        warn "Unreal build probe reported: $EDITOR_LINE"
        ;;
    EDITOR=*)
        label="${EDITOR_LINE#EDITOR=}"
        exe=""
        if [[ "$label" == *"|"* ]]; then
            exe="${label#*|}"
            label="${label%%|*}"
        fi
        ok "Unreal build: $label -> $exe"
        ;;
    *)
        warn "unexpected editor probe output: $EDITOR_LINE"
        ;;
esac

# ---------------------------------------------------------------------------
# 6. Project detection / selection
# ---------------------------------------------------------------------------
step "6/8 Project"
PROJ_ARGS=("$CHECKER" project)
if [ -n "$PROJECT" ]; then
    PROJ_ARGS+=("$PROJECT")
fi
PROJ_LINE="$("$VENV_PY" "${PROJ_ARGS[@]}" 2>&1 | tail -n 1)"
case "$PROJ_LINE" in
    PROJECT=none|PROJECT=probe_error*)
        warn "no .uproject found; proceeding (bridge editor already open is fine)"
        ;;
    PROJECT=*)
        ok "project selected: ${PROJ_LINE#PROJECT=}"
        ;;
    *)
        warn "unexpected project probe output: $PROJ_LINE"
        ;;
esac

# ---------------------------------------------------------------------------
# 7. Persistent backend
# ---------------------------------------------------------------------------
step "7/8 Persistent backend (survives terminal close)"
if [ "$NO_START" -eq 1 ]; then
    ok "skipped (--no-start); run ./start-aivido.sh start when ready"
else
    if ! "$VENV_PY" "$ROOT/scripts/aivido_runtime.py" start; then
        fail "backend did not start. Run: ./start-aivido.sh status"
        exit 1
    fi
    ok "backend persistent + healthy"
fi

# ---------------------------------------------------------------------------
# 8. UI
# ---------------------------------------------------------------------------
step "8/8 Aivido UI"
echo ""
echo "  Local  : http://127.0.0.1:8765/app"
echo "  Status : ./start-aivido.sh status"
echo "  Stop   : ./start-aivido.sh stop"
if [ "$NO_START" -eq 1 ] || [ "$NO_BROWSER" -eq 1 ]; then
    ok "install complete (UI not opened)"
else
    if command -v open >/dev/null 2>&1; then
        open "http://127.0.0.1:8765/app" >/dev/null 2>&1 || true
        ok "opened UI in your browser"
    fi
fi
echo ""
echo "AIVIDO V2.0.0 INSTALL OK"
exit 0