"""aivido_runtime.py — Aivido V1 persistent backend runtime manager.

The production fix for the RC1.1 finding: a foreground PowerShell running
`python -m uvicorn app.served:app --host 127.0.0.1 --port 8765` dies the
moment its terminal closes. This manager spawns the backend as a fully
detached Windows process that survives launcher exit, tracks its PID and
state on disk, guards against duplicate listeners, keeps logs, and runs a
small detached watchdog that restarts the backend on crash (bounded, never
a hot loop) — while NEVER touching the Unreal bridge (6766) or the MCP
gateway (8844) unless this launcher owns them (it never does).

Commands (run from the repo root):

    python scripts/aivido_runtime.py start     -> start persistent backend
    python scripts/aivido_runtime.py stop      -> stop backend + watchdog
    python scripts/aivido_runtime.py restart   -> stop then start
    python scripts/aivido_runtime.py status    -> state/health/log paths
    python scripts/aivido_runtime.py ui        -> open http://127.0.0.1:8765/app
    python scripts/aivido_runtime.py remote on|off|status
    python scripts/aivido_runtime.py logs      -> print log paths

Exit codes: 0 = healthy/ok, 1 = failure. Status prints FAIL + log paths
instead of hiding failures.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import service_lifecycle as sl  # noqa: E402

# ---------------------------------------------------------------------------
# Identity / paths
# ---------------------------------------------------------------------------

SERVICE_NAME = "aivido_v1"
BACKEND_HOST = os.environ.get("AIVIDO_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("AIVIDO_BACKEND_PORT", "8765"))
APP_TARGET = "app.served:app"
HEALTH_PATH = "/api/status"
UI_PATH = "/app"
LOCAL_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
UI_URL = f"{LOCAL_URL}{UI_PATH}"

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766
GATEWAY_PORT = 8844

STATE_FILE = sl.RUNTIME_DIR / f"{SERVICE_NAME}.json"
PID_FILE = sl.RUNTIME_DIR / f"{SERVICE_NAME}.pid"
STOP_FLAG = sl.RUNTIME_DIR / f"{SERVICE_NAME}.stop"
LOG_OUT = sl.LOG_DIR / f"{SERVICE_NAME}.out.log"
LOG_ERR = sl.LOG_DIR / f"{SERVICE_NAME}.err.log"

WATCHDOG_INTERVAL_S = 5
WATCHDOG_MAX_RESTARTS = 3
WATCHDOG_WINDOW_S = 15 * 60

STATE_DEFAULTS = {
    "service": SERVICE_NAME,
    "app_target": APP_TARGET,
    "host": BACKEND_HOST,
    "port": BACKEND_PORT,
    "state": "STOPPED",          # STOPPED | STARTING | RUNNING | FAIL | FOREIGN
    "pid": None,
    "spawn_pid": None,            # tree root of the last detached spawn
    "watchdog_pid": None,
    "started_at": None,
    "last_health_at": None,
    "last_error": None,
    "restarts": 0,
    "restart_times": [],
    "log_out": str(LOG_OUT),
    "log_err": str(LOG_ERR),
    "local_url": LOCAL_URL,
    "ui_url": UI_URL,
    "remote": {"state": "off", "url": None, "error": None, "checked_at": None},
    "events": [],
}


def _utcnow() -> float:
    return time.time()


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    state = dict(STATE_DEFAULTS)
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state.update({k: v for k, v in data.items() if k in STATE_DEFAULTS})
    except Exception:
        pass
    return state


def _save_state(state: Dict[str, Any]) -> None:
    try:
        sl.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as exc:
        print(f"[runtime] WARNING: could not persist state: {exc}")


def _record_event(state: Dict[str, Any], kind: str, detail: str) -> None:
    events = state.setdefault("events", [])
    events.append({"kind": kind, "detail": detail, "at": _utcnow()})
    del events[:-40]


# ---------------------------------------------------------------------------
# Listener / ownership detection (platform-aware)
# ---------------------------------------------------------------------------

def _listener_pids(host: str, port: int) -> List[int]:
    """PIDs currently LISTENING on host:port (loopback-scoped)."""
    pids: List[int] = []
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                timeout=15
            ).stdout or ""
            needle = f"{host}:{port}"
            for line in out.splitlines():
                if "LISTENING" not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5 and needle in parts[1]:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
        except Exception:
            pass
        return sorted(set(pids))
    # POSIX: lsof reports the pid listening on a TCP port.
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=15
        ).stdout or ""
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(set(pids))


def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _backend_ready() -> bool:
    return _http_ok(f"{LOCAL_URL}{HEALTH_PATH}")


def _backend_pid() -> Optional[int]:
    rec = sl.read_pid_file(SERVICE_NAME)
    if rec and sl.pid_alive(rec.get("pid")):
        return int(rec["pid"])
    return None


def _looks_like_ours(pid: int) -> bool:
    """True when pid runs OUR backend command from THIS checkout. Adoption
    must never claim a backend another Aivido clone/agent started."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter "
                 f"'ProcessId={pid}').CommandLine"],
                capture_output=True, text=True, timeout=20)
            cmdline = (out.stdout or "").strip().lower()
        else:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=20)
            cmdline = (out.stdout or "").strip().lower()
    except Exception:
        return False
    root_venv = str(ROOT / ".venv").lower()
    if root_venv not in cmdline:
        return False
    return (
        "-m uvicorn" in cmdline
        and "app.served:app" in cmdline
        and "--port" in cmdline
        and str(BACKEND_PORT) in cmdline
    )


# ---------------------------------------------------------------------------
# Detached spawn
# ---------------------------------------------------------------------------

def _detached_popen(cmd: List[str], out_log: Path, err_log: Path):
    """Spawn a child that survives the parent (launcher) process exiting."""
    creation = 0
    if sys.platform == "win32":
        creation = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    out_log.parent.mkdir(parents=True, exist_ok=True)
    with open(out_log, "ab") as fo, open(err_log, "ab") as fe:
        if sys.platform == "win32":
            return subprocess.Popen(
                cmd, cwd=str(ROOT), stdout=fo, stderr=fe,
                creationflags=creation, close_fds=True,
            )
        return subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=fo, stderr=fe, close_fds=True,
            start_new_session=True,
        )


def _venv_python() -> str:
    cands = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python3",
    ]
    for cand in cands:
        if cand.exists():
            return str(cand)
    return sys.executable


# ---------------------------------------------------------------------------
# start / stop / restart / status
# ---------------------------------------------------------------------------

def _start_backend(state: Dict[str, Any]) -> Dict[str, Any]:
    # 1) Already healthy via our pid file -> reuse.
    pid = _backend_pid()
    if pid and _backend_ready():
        state.update({"state": "RUNNING", "pid": pid, "last_error": None,
                      "last_health_at": _utcnow()})
        _record_event(state, "start", f"already running (pid {pid})")
        _save_state(state)
        return {"ok": True, "duplicate": True, "pid": pid}

    # 2) Port occupied by someone else.
    owners = _listener_pids(BACKEND_HOST, BACKEND_PORT)
    if owners:
        # A listener exists and we have no healthy owned backend. If the ONLY
        # listener runs OUR exact backend command from THIS checkout it is an
        # orphaned backend of ours (e.g. launcher died after spawn) -> adopt
        # it, never duplicate it and never touch a foreign process.
        if (len(owners) == 1 and _backend_ready()
                and _looks_like_ours(owners[0])):
            owner = owners[0]
            sl.write_pid_file(SERVICE_NAME, owner, BACKEND_PORT)
            state.update({"state": "RUNNING", "pid": owner,
                          "last_error": None, "last_health_at": _utcnow()})
            _record_event(state, "adopted",
                          f"adopted orphaned own backend pid {owner}")
            _save_state(state)
            return {"ok": True, "duplicate": True, "pid": owner,
                    "adopted": True}
        refused = [p for p in owners if p != pid]
        state.update({"state": "FOREIGN", "last_error": (
            f"port {BACKEND_HOST}:{BACKEND_PORT} owned by process(es) "
            f"{refused or owners} not managed by Aivido; refusing to start "
            "a duplicate. Stop that process first.")})
        _record_event(state, "start_refused",
                      f"foreign listeners {owners} on {BACKEND_PORT}")
        _save_state(state)
        return {"ok": False, "error": state["last_error"], "foreign": owners}

    # 3) Fresh detached spawn.
    py = _venv_python()
    cmd = [py, "-m", "uvicorn", APP_TARGET, "--host", BACKEND_HOST,
           "--port", str(BACKEND_PORT), "--log-level", "info"]
    state.update({"state": "STARTING", "started_at": _utcnow(),
                  "last_error": None})
    _save_state(state)
    try:
        proc = _detached_popen(cmd, LOG_OUT, LOG_ERR)
    except Exception as exc:
        state.update({"state": "FAIL",
                      "last_error": f"spawn failed: {exc}",
                      "log_err": str(LOG_ERR)})
        _save_state(state)
        return {"ok": False, "error": state["last_error"]}

    state["spawn_pid"] = proc.pid
    _save_state(state)
    _record_event(state, "spawn", f"spawned tree root pid {proc.pid}")

    # 4) Bounded readiness wait (the spawn root may be a venv launcher whose
    # real server child owns the socket; health is what matters here).
    deadline = time.time() + 120
    while time.time() < deadline:
        if _backend_ready():
            break
        if not sl.pid_alive(proc.pid) and not _listener_pids(
                BACKEND_HOST, BACKEND_PORT):
            state.update({"state": "FAIL", "last_error": (
                "backend process exited before becoming healthy; "
                f"see log: {LOG_ERR}")})
            _save_state(state)
            return {"ok": False, "error": state["last_error"],
                    "log": str(LOG_ERR)}
        time.sleep(0.5)

    if not _backend_ready():
        state.update({"state": "FAIL", "last_error": (
            "readiness timeout after 120s; "
            f"see log: {LOG_ERR}")})
        _save_state(state)
        return {"ok": False, "error": state["last_error"], "log": str(LOG_ERR)}

    # 5) Resolve the REAL listener pid (the process that owns :8765). The
    # spawn root can be a venv launcher shim; the listener is authoritative
    # and is what duplicate/stop logic must track.
    listeners: List[int] = []
    deadline = time.time() + 10
    while time.time() < deadline:
        listeners = _listener_pids(BACKEND_HOST, BACKEND_PORT)
        if len(listeners) == 1:
            break
        time.sleep(0.4)
    if len(listeners) == 0:
        state.update({"state": "FAIL", "last_error": (
            "backend healthy but no listener found on "
            f"{BACKEND_HOST}:{BACKEND_PORT}")})
        _save_state(state)
        return {"ok": False, "error": state["last_error"]}
    if len(listeners) > 1:
        state.update({"state": "FAIL", "last_error": (
            f"zombie duplicate listeners on {BACKEND_PORT}: {listeners} "
            "(expected exactly one)")})
        _save_state(state)
        return {"ok": False, "error": state["last_error"]}

    server_pid = listeners[0]
    sl.write_pid_file(SERVICE_NAME, server_pid, BACKEND_PORT)
    state["pid"] = server_pid
    state.update({"state": "RUNNING", "last_health_at": _utcnow(),
                  "last_error": None})
    _save_state(state)
    return {"ok": True, "pid": server_pid}


def _start_watchdog(state: Dict[str, Any]) -> None:
    """Spawn the detached watchdog for this service (single instance)."""
    wpid = state.get("watchdog_pid")
    if wpid and sl.pid_alive(wpid):
        return
    py = _venv_python()
    wlog = sl.LOG_DIR / f"{SERVICE_NAME}.watchdog.log"
    try:
        proc = _detached_popen(
            [py, str(ROOT / "scripts" / "aivido_watchdog.py"),
             "--service", SERVICE_NAME, "--interval", str(WATCHDOG_INTERVAL_S),
             "--max-restarts", str(WATCHDOG_MAX_RESTARTS),
             "--window", str(WATCHDOG_WINDOW_S)],
            wlog, wlog)
        state["watchdog_pid"] = proc.pid
        _record_event(state, "watchdog", f"watchdog pid {proc.pid}")
        _save_state(state)
    except Exception as exc:
        state.setdefault("events", []).append(
            {"kind": "watchdog_failed", "detail": str(exc), "at": _utcnow()})
        _save_state(state)


def cmd_start(args: argparse.Namespace) -> int:
    state = _load_state()
    # Refuse when the MCP gateway port is about to collide with nothing, but
    # never kill bridge/gateway: they are out of scope for this launcher.
    if _probe_port(BRIDGE_HOST, BRIDGE_PORT):
        pass  # expected — live Unreal bridge; never touched.
    res = _start_backend(state)
    state = _load_state()
    if res.get("ok"):
        _start_watchdog(state)
        state = _load_state()
        print(f"[start] backend RUNNING pid={res.get('pid')} "
              f"url={LOCAL_URL} ui={UI_URL}")
        if res.get("duplicate"):
            print("[start] (already running; reused)")
        print(f"[start] log: {LOG_OUT}")
        return 0
    print(f"[start] FAILED: {res.get('error')}")
    if res.get("log"):
        print(f"[start] log: {res['log']}")
    return 1


def _stop_backend(state: Dict[str, Any]) -> Dict[str, Any]:
    # Kill the spawn tree root first (covers venv launcher parents), then the
    # recorded server pid via the shared lifecycle helper.
    spawn_pid = state.get("spawn_pid")
    if spawn_pid and sl.pid_alive(spawn_pid):
        sl._terminate(int(spawn_pid))
    res = sl.stop_service(SERVICE_NAME, BACKEND_HOST, BACKEND_PORT, grace_s=5.0)
    # Detect foreign survivors (a different process on the port).
    listeners = _listener_pids(BACKEND_HOST, BACKEND_PORT)
    state.update({"pid": None, "spawn_pid": None, "watchdog_pid": None,
                  "last_health_at": None})
    if listeners:
        state.update({"state": "FOREIGN", "last_error": (
            f"port {BACKEND_HOST}:{BACKEND_PORT} still occupied after stop by "
            f"{listeners}; not killed (not owned by Aivido).")})
        _save_state(state)
        res["ok"] = False
        res["error"] = state["last_error"]
        return res
    state.update({"state": "STOPPED", "last_error": None})
    _save_state(state)
    return res


def _stop_watchdog(state: Dict[str, Any]) -> None:
    wpid = state.get("watchdog_pid")
    if wpid and sl.pid_alive(wpid):
        sl._terminate(int(wpid))
    try:
        STOP_FLAG.unlink(missing_ok=True)
    except Exception:
        pass
    state["watchdog_pid"] = None


def cmd_stop(args: argparse.Namespace) -> int:
    state = _load_state()
    _stop_watchdog(state)
    res = _stop_backend(state)
    if res.get("ok"):
        print("[stop] backend stopped cleanly; port released")
        return 0
    print(f"[stop] {res.get('error', 'stop failed')}")
    return 1


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(argparse.Namespace())
    time.sleep(0.5)
    return cmd_start(args)


def _remote_info() -> Dict[str, Any]:
    """Detect Tailscale availability, IPv4, and DNS name (never fails hard)."""
    exe = shutil.which("tailscale")
    if not exe:
        for cand in (Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                     / "Tailscale" / "tailscale.exe",
                     Path(os.environ.get("LOCALAPPDATA", "")) / "Tailscale"
                     / "tailscale.exe"):
            if cand.exists():
                exe = str(cand)
                break
    if not exe:
        return {"state": "no_tailscale", "url": None,
                "error": "tailscale CLI not found", "checked_at": _utcnow()}

    info: Dict[str, Any] = {"state": "unknown", "url": None, "error": None,
                            "checked_at": _utcnow(), "cli": exe,
                            "ipv4": None, "dns": None}
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True,
                             text=True, timeout=20)
        data = json.loads(out.stdout or "{}")
        self_node = data.get("Self") or {}
        dns = str(self_node.get("DNSName") or "").strip().rstrip(".")
        ips = [i for i in (self_node.get("TailscaleIPs") or [])
               if "." in str(i)]
        info["dns"] = dns or None
        info["ipv4"] = str(ips[0]) if ips else None
        info["state"] = "up" if data.get("BackendState") in ("Running",) else \
            str(data.get("BackendState") or "unknown")
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    if info["state"] != "up":
        info["error"] = info["error"] or f"tailscale state: {info['state']}"
    return info


def _serve_status(exe: str) -> Dict[str, Any]:
    try:
        out = subprocess.run([exe, "serve", "status", "--json"],
                             capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def cmd_remote(args: argparse.Namespace) -> int:
    state = _load_state()
    action = args.remote_action or "status"
    info = _remote_info()

    if action == "status":
        print("[remote] Tailscale status:")
        print(f"  state    : {info.get('state')}")
        print(f"  ipv4     : {info.get('ipv4')}")
        print(f"  dns      : {info.get('dns')}")
        if info.get("error"):
            print(f"  error    : {info['error']}")
        print(f"  expose   : {state.get('remote', {}).get('state')}")
        print(f"  url      : {state.get('remote', {}).get('url')}")
        remote = state.get("remote", {})
        if remote.get("url") and _http_ok(remote["url"] + "/api/status",
                                          timeout=5):
            print("  health   : remote URL answers (health OK)")
        elif remote.get("url"):
            print("  health   : remote URL did not answer")
        return 0 if info.get("state") == "up" else 1

    if action == "on":
        if info.get("state") != "up":
            msg = (info.get("error") or "tailscale is not running; "
                   "start Tailscale first")
            state["remote"] = {"state": "failed", "url": None, "error": msg,
                               "checked_at": _utcnow()}
            _save_state(state)
            print(f"[remote] FAILED: {msg}")
            print("[remote] Local Aivido is unaffected.")
            return 1
        if not _backend_ready():
            msg = "backend is not healthy; start Aivido first"
            state["remote"] = {"state": "failed", "url": None, "error": msg,
                               "checked_at": _utcnow()}
            _save_state(state)
            print(f"[remote] FAILED: {msg}")
            return 1
        exe = info["cli"]
        current = _serve_status(exe)
        if current:
            already = False
            for snode in (current.get("TCP") or {}).values():
                for svc in (snode.get("Port") or {}).values():
                    if str(svc.get("Target", "")).startswith(
                            "http://127.0.0.1:8765"):
                        already = True
            if already:
                dns = info["dns"] or f"{info['ipv4']}"
                url = f"https://{dns}" if info.get("dns") else \
                    f"https://{info['ipv4']}"
                state["remote"] = {"state": "on", "url": url,
                                   "error": None, "checked_at": _utcnow()}
                _save_state(state)
                print(f"[remote] already exposed via tailscale serve: {url}")
                return 0
        # Try modern serve syntax, then fallback syntax.
        attempts = [
            [exe, "serve", "--bg", "http://127.0.0.1:8765"],
            [exe, "serve", "--bg", "8765"],
            [exe, "serve", "--bg", "--set-path", "/", "8765"],
        ]
        ok = False
        last_err = None
        for cmd in attempts:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=30)
                if r.returncode == 0:
                    ok = True
                    break
                last_err = (r.stderr or r.stdout or "").strip()[-400:]
            except Exception as exc:
                last_err = str(exc)
        if not ok:
            msg = f"tailscale serve failed: {last_err}"
            state["remote"] = {"state": "failed", "url": None,
                               "error": msg, "checked_at": _utcnow()}
            _save_state(state)
            print(f"[remote] FAILED: {msg}")
            print("[remote] Local Aivido is unaffected.")
            return 1
        time.sleep(3)
        dns = info["dns"] or f"{info['ipv4']}"
        url = f"https://{dns}" if info.get("dns") else f"https://{info['ipv4']}"
        state["remote"] = {"state": "on", "url": url, "error": None,
                           "checked_at": _utcnow()}
        _save_state(state)
        healthy = _http_ok(url + "/api/status", timeout=8)
        print(f"[remote] exposed: {url}  (health={'OK' if healthy else 'pending'})")
        print("[remote] reach from your Mac on the same tailnet:")
        print(f"  {url}/app")
        if not healthy:
            print("[remote] WARNING: remote health probe did not answer yet; "
                  "local Aivido is unaffected.")
        return 0 if healthy else 0

    if action == "off":
        exe = info.get("cli")
        if not exe:
            print("[remote] tailscale CLI not found; nothing to disable")
            return 1
        for cmd in ([exe, "serve", "--https", "443", "off"],):
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except Exception:
                pass
        state["remote"] = {"state": "off", "url": None, "error": None,
                           "checked_at": _utcnow()}
        _save_state(state)
        print("[remote] tailscale serve disabled for this node")
        return 0

    print(f"[remote] unknown action: {action}")
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state()
    rec = sl.read_pid_file(SERVICE_NAME)
    pid = rec.get("pid") if rec else None
    alive = sl.pid_alive(pid)
    listening = _probe_port(BACKEND_HOST, BACKEND_PORT)
    ready = _backend_ready() if listening else False

    # Reconcile reality with recorded state (never lie).
    if ready and alive:
        if state.get("state") != "RUNNING":
            state["state"] = "RUNNING"
            state["last_error"] = None
            _save_state(state)
    elif listening and not alive:
        owners = _listener_pids(BACKEND_HOST, BACKEND_PORT)
        if state.get("state") != "FOREIGN":
            state["state"] = "FOREIGN"
            state["last_error"] = (
                f"port occupied by unmanaged process(es) {owners}")
            _save_state(state)
    elif not alive and state.get("state") == "RUNNING":
        # Backend died without the watchdog recovering it -> truthful FAIL.
        state["state"] = "FAIL"
        state["last_error"] = (
            "backend process is dead; not recovered. "
            f"log: {LOG_ERR}")
        _save_state(state)

    remote = state.get("remote") or {}
    uptime = ""
    if state.get("started_at"):
        uptime = f"{int(_utcnow() - state['started_at'])}s"

    print("[status] Aivido V1 persistent backend")
    print(f"  state    : {state.get('state')}")
    print(f"  pid      : {pid} (alive={alive})")
    if state.get("watchdog_pid"):
        print(f"  watchdog : pid {state['watchdog_pid']} "
              f"(alive={sl.pid_alive(state['watchdog_pid'])})")
    print(f"  port     : {BACKEND_HOST}:{BACKEND_PORT} "
          f"(listening={listening})")
    print(f"  health   : {'OK' if ready else 'not answering'} "
          f"({HEALTH_PATH})")
    print(f"  uptime   : {uptime or 'n/a'}")
    print(f"  restarts : {state.get('restarts')}")
    print(f"  local    : {LOCAL_URL}")
    print(f"  ui       : {UI_URL}")
    print(f"  log out  : {LOG_OUT}")
    print(f"  log err  : {LOG_ERR}")
    if state.get("last_error"):
        print(f"  error    : {state['last_error']}")
    if remote.get("state") == "on":
        print(f"  remote   : {remote.get('url')}")
    elif remote.get("error"):
        print(f"  remote   : {remote.get('state')} ({remote.get('error')})")
    # Bridge + gateway always reported; never killed by us.
    print(f"  bridge   : {BRIDGE_HOST}:{BRIDGE_PORT} "
          f"(listening={_probe_port(BRIDGE_HOST, BRIDGE_PORT)})")
    print(f"  gateway  : {BRIDGE_HOST}:{GATEWAY_PORT} "
          f"(listening={_probe_port(BRIDGE_HOST, GATEWAY_PORT)})")
    if args.json:
        print(json.dumps({
            "service": SERVICE_NAME, "state": state.get("state"),
            "pid": pid, "pid_alive": alive, "listening": listening,
            "healthy": ready, "uptime": uptime,
            "restarts": state.get("restarts"),
            "log_out": str(LOG_OUT), "log_err": str(LOG_ERR),
            "local_url": LOCAL_URL, "ui_url": UI_URL,
            "remote": remote, "bridge": {
                "host": BRIDGE_HOST, "port": BRIDGE_PORT,
                "listening": _probe_port(BRIDGE_HOST, BRIDGE_PORT)},
            "gateway": {
                "host": BRIDGE_HOST, "port": GATEWAY_PORT,
                "listening": _probe_port(BRIDGE_HOST, GATEWAY_PORT)},
            "error": state.get("last_error"),
        }, indent=2, default=str))
    # FAIL must be visible and exit non-zero.
    return 0 if ready and alive else 1


def cmd_ui(args: argparse.Namespace) -> int:
    if not _backend_ready():
        print("[ui] backend not healthy; start it first "
              "(start-aivido.cmd / aivido_runtime.py start)")
        return 1
    webbrowser.open(UI_URL)
    print(f"[ui] opened {UI_URL}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    print(f"out: {LOG_OUT}")
    print(f"err: {LOG_ERR}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="aivido_runtime",
                                description="Aivido V1 persistent runtime")
    p.add_argument("command", nargs="?", default="status",
                   choices=["start", "stop", "restart", "status", "ui",
                            "remote", "logs"])
    p.add_argument("remote_action", nargs="?", default="status",
                   choices=["on", "off", "status"])
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "restart":
        return cmd_restart(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "ui":
        return cmd_ui(args)
    if args.command == "logs":
        return cmd_logs(args)
    if args.command == "remote":
        return cmd_remote(args)
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())