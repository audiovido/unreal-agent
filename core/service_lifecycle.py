"""service_lifecycle.py — local service lifecycle (Lane B, Part 5).

Manages one local backend process deterministically:

  detect  -> probe the port AND read the pid file
  start   -> spawn the service detached (single instance guaranteed)
  health  -> HTTP readiness probe (or raw port probe for non-HTTP)
  stop    -> terminate the pid, then clean up stale pid file
  restart -> bounded retries with backoff, never an infinite loop

No file in the Step-8 product lane is modified: pid/state files live under
`config/runtime/` and logs under `config/logs/`.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import app_config

RUNTIME_DIR = app_config.RUNTIME_DIR
LOG_DIR = app_config.LOG_DIR

_CTYPES_AVAILABLE = True
try:
    import ctypes
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
except Exception:  # pragma: no cover - non-Windows or exotic
    _CTYPES_AVAILABLE = False


# ---------------------------------------------------------------------------
# pid helpers
# ---------------------------------------------------------------------------

def _pid_alive_windows(pid: int) -> bool:
    if not _CTYPES_AVAILABLE:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle,
                                                       ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        # STILL_ACTIVE (259) means the process is alive.
        return bool(ok and exit_code.value == 259)
    except Exception:
        return False


def pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_file(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    return RUNTIME_DIR / f"{safe}.pid"


def write_pid_file(name: str, pid: int, port: Optional[int] = None) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "pid": int(pid), "port": port,
               "written_at": round(time.time(), 3)}
    tmp = _pid_file(name).with_suffix(".pid.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(_pid_file(name))


def read_pid_file(name: str) -> Optional[Dict[str, Any]]:
    p = _pid_file(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pid_file(name: str) -> None:
    try:
        _pid_file(name).unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------

def port_in_use(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return False


def http_ready(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

def stop_service(name: str, host: str, port: int,
                 grace_s: float = 3.0) -> Dict[str, Any]:
    """Stop a service by pid file (+ port fallback).  Idempotent."""
    record = read_pid_file(name)
    pid = record.get("pid") if record else None
    results = {"pid_file": record, "terminated": [], "port": port,
               "still_running": False}
    if pid and pid_alive(pid):
        _terminate(pid)
        results["terminated"].append(pid)
        # wait briefly for the port to free
        deadline = time.time() + grace_s
        while time.time() < deadline and port_in_use(host, port):
            time.sleep(0.1)
    elif pid and not pid_alive(pid):
        results["note"] = "pid already dead (stale file)"
    clear_pid_file(name)
    results["still_running"] = port_in_use(host, port)
    if results["still_running"]:
        results["ok"] = False
        results["error"] = (f"port {host}:{port} still occupied after stop "
                            "(different process?)")
    else:
        results["ok"] = True
    return results


def _terminate(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# start / ensure
# ---------------------------------------------------------------------------

def start_service(name: str, host: str, port: int,
                  app_target: str,
                  health_path: str = "/api/ua/status",
                  python_exe: Optional[str] = None,
                  ready_timeout_s: float = 25.0,
                  log_suffix: str = "backend") -> Dict[str, Any]:
    """Start ONE detached backend and wait for real readiness.

    Refuses to start when the port is already answered by a live process
    (duplicate-instance protection).  Uses a bounded readiness wait, never
    an infinite one.
    """
    existing = read_pid_file(name)
    if existing and pid_alive(existing.get("pid")):
        return {"ok": True, "duplicate": True, "pid": existing["pid"],
                "note": "already running (pid file)",
                "ready": http_ready(f"http://{host}:{port}{health_path}")}
    if port_in_use(host, port):
        return {"ok": False, "error":
                f"port {host}:{port} already in use by another process; "
                "refusing to start a duplicate",
                "duplicate": True}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    out_log = LOG_DIR / f"{log_suffix}.out.log"
    err_log = LOG_DIR / f"{log_suffix}.err.log"
    py = python_exe or sys.executable

    cmd = [py, "-m", "uvicorn", app_target, "--host", host,
           "--port", str(port), "--log-level", "warning"]
    creation = 0
    if sys.platform == "win32":
        creation = subprocess.CREATE_NEW_PROCESS_GROUP | \
            subprocess.DETACHED_PROCESS
    try:
        with open(out_log, "ab") as fo, open(err_log, "ab") as fe:
            proc = subprocess.Popen(cmd, cwd=str(app_config.ROOT),
                                    stdout=fo, stderr=fe,
                                    creationflags=creation)
    except Exception as exc:
        return {"ok": False, "error": f"spawn failed: {exc}"}
    write_pid_file(name, proc.pid, port)
    if not pid_alive(proc.pid):
        return {"ok": False, "error": "process exited immediately",
                "pid": proc.pid, "log": str(err_log)}

    # bounded readiness
    deadline = time.time() + ready_timeout_s
    while time.time() < deadline:
        if http_ready(f"http://{host}:{port}{health_path}"):
            return {"ok": True, "pid": proc.pid, "port": port,
                    "ready": True, "duplicate": False,
                    "log": str(out_log), "started_at": round(time.time(), 3)}
        time.sleep(0.25)
    return {"ok": False, "error": "readiness timeout",
            "pid": proc.pid, "log": str(err_log)}


def ensure_running(name: str, host: str, port: int, app_target: str,
                   health_path: str = "/api/ua/status",
                   max_attempts: int = 3,
                   backoff_s: float = 1.0,
                   log_suffix: str = "backend") -> Dict[str, Any]:
    """Bounded restart wrapper: probe -> start -> health, retrying at most
    `max_attempts` times with backoff.  Never loops forever."""
    history: List[Dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        rec = start_service(name, host, port, app_target,
                            health_path=health_path, log_suffix=log_suffix)
        rec["attempt"] = attempt
        history.append(rec)
        if rec.get("ok") and rec.get("ready"):
            return {"ok": True, "attempts": attempt, "history": history,
                    "pid": rec.get("pid")}
        if rec.get("ok") and not rec.get("ready"):
            time.sleep(backoff_s * attempt)
            continue
        # start refused (duplicate or immediate death): diagnose
        if rec.get("duplicate"):
            return {"ok": False, "attempts": attempt,
                    "error": rec.get("error") or "duplicate backend",
                    "history": history}
        time.sleep(backoff_s * attempt)
    return {"ok": False, "attempts": max_attempts,
            "error": "backend did not become ready after bounded retries",
            "history": history}


# ---------------------------------------------------------------------------
# status / single source of truth
# ---------------------------------------------------------------------------

def service_status(name: str, host: str, port: int,
                   health_path: str = "/api/ua/status",
                   app_target: Optional[str] = None) -> Dict[str, Any]:
    record = read_pid_file(name)
    alive = pid_alive((record or {}).get("pid"))
    listening = port_in_use(host, port)
    ready = http_ready(f"http://{host}:{port}{health_path}") if listening \
        else False
    if record and not alive:
        # stale pid file (crash or unclean exit) -> auto-recoverable
        clear_pid_file(name)
        record["stale_recovered"] = True
    return {"name": name, "port": port, "pid": (record or {}).get("pid"),
            "pid_file": record is not None, "pid_alive": alive,
            "listening": listening, "ready": ready,
            "app_target": app_target,
            "state": ("RUNNING" if ready else
                      "LISTENING" if listening else
                      "STALE" if record else "STOPPED")}
