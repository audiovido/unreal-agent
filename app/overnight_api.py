from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "overnight_audio_vivo.py"


def _active_project_root():
    """Resolve the active project root through the standard priority chain
    instead of a baked-in legacy demo path. Falls back to the repo workspace
    dir on machines with no Unreal project yet."""
    try:
        from tools.unreal import project_context as _pc
        resolved = _pc.resolve_active_project()
        if resolved and resolved.get("ok") and resolved.get("uproject_path"):
            return Path(resolved["uproject_path"]).resolve().parent
    except Exception:
        pass
    return ROOT / "workspace"


PROJECT = _active_project_root()

OVERNIGHT_DIR = (
    PROJECT / "Saved" / "UnrealAgent" / "Overnight"
)

STATE_FILE = OVERNIGHT_DIR / "overnight_state.json"
CONTROL_FILE = OVERNIGHT_DIR / "overnight_control.json"
PID_FILE = OVERNIGHT_DIR / "overnight.pid"

router = APIRouter(prefix="/api/overnight")

_lock = threading.Lock()
_process: subprocess.Popen | None = None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_control(**updates):
    OVERNIGHT_DIR.mkdir(parents=True, exist_ok=True)

    data = _read_json(
        CONTROL_FILE,
        {
            "pause": False,
            "stop": False,
        },
    )

    data.update(updates)
    data["updated_at"] = time.time()

    CONTROL_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    return data


def _latest_log():
    try:
        logs = sorted(
            OVERNIGHT_DIR.glob("overnight_*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not logs:
            return None, []

        path = logs[0]

        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

        return str(path), lines[-60:]

    except Exception:
        return None, []


def _process_running():
    global _process

    if _process is not None:
        return _process.poll() is None

    return False


def _status():
    control = _read_json(
        CONTROL_FILE,
        {
            "pause": False,
            "stop": False,
        },
    )

    state = _read_json(
        STATE_FILE,
        {},
    )

    log_path, log_tail = _latest_log()

    tasks = state.get("tasks") or []

    current = None

    for task in reversed(tasks):
        if task.get("status") in (
            "PENDING",
            "RUNNING",
        ):
            current = task
            break

    if current is None and tasks:
        current = tasks[-1]

    return {
        "ok": True,
        "running": _process_running(),
        "paused": bool(control.get("pause")),
        "stop_requested": bool(control.get("stop")),
        "pid": (
            _process.pid
            if _process is not None
            and _process.poll() is None
            else None
        ),
        "state": state,
        "current": current,
        "log_path": log_path,
        "log_tail": log_tail,
    }


@router.post("/start")
def overnight_start():
    global _process

    with _lock:
        if _process_running():
            return {
                **_status(),
                "message": "Overnight mission is already running.",
            }

        OVERNIGHT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        _write_control(
            pause=False,
            stop=False,
        )

        _process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
            ],
            cwd=str(ROOT),
        )

        PID_FILE.write_text(
            str(_process.pid),
            encoding="utf-8",
        )

        result = _status()
        result["message"] = "Overnight mission started."
        return result


@router.get("/status")
def overnight_status():
    return _status()


@router.post("/pause")
def overnight_pause():
    if not _process_running():
        return {
            **_status(),
            "ok": False,
            "message": "No Overnight mission is running.",
        }

    _write_control(pause=True)

    return {
        **_status(),
        "message": "Pause requested.",
    }


@router.post("/resume")
def overnight_resume():
    _write_control(
        pause=False,
        stop=False,
    )

    return {
        **_status(),
        "message": "Mission resumed.",
    }


@router.post("/stop")
def overnight_stop():
    if not _process_running():
        _write_control(
            pause=False,
            stop=True,
        )

        return {
            **_status(),
            "message": "Mission is not running.",
        }

    _write_control(
        pause=False,
        stop=True,
    )

    return {
        **_status(),
        "message": "Stop requested.",
    }
