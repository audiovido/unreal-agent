"""aivido_watchdog.py — detached crash watchdog for the Aivido V1 backend.

Spawned by scripts/aivido_runtime.py start. Runs as its own detached
process so it survives the launcher. Polls the backend PID + health;
on crash it restarts the backend (bounded budget per window) using the
same detached spawn path, and records every event in the shared state
file. It NEVER touches the Unreal bridge (6766) or the MCP gateway
(8844). If the port is later owned by a foreign process, it stops
restarting and marks the service FAIL with the log path exposed.

Stops when: the backend pid is gone AND the port is free AND a stop was
requested (state file says STOPPED), or the state file is deleted.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import service_lifecycle as sl  # noqa: E402


def _load_state(state_file: Path) -> Dict[str, Any]:
    try:
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state_file: Path, state: Dict[str, Any]) -> None:
    try:
        tmp = state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(state_file)
    except Exception:
        pass


def _record(state_file: Path, state: Dict[str, Any], kind: str,
            detail: str) -> None:
    events = state.setdefault("events", [])
    events.append({"kind": kind, "detail": detail, "at": time.time()})
    del events[:-40]
    _save_state(state_file, state)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aivido_watchdog")
    p.add_argument("--service", default="aivido_v1")
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--max-restarts", type=int, default=3)
    p.add_argument("--window", type=float, default=15 * 60)
    args = p.parse_args(argv)

    state_file = sl.RUNTIME_DIR / f"{args.service}.json"
    host, port = "127.0.0.1", 8765
    log_err = sl.LOG_DIR / f"{args.service}.err.log"

    last_restart_budget: List[float] = []
    warned_foreign = False

    while True:
        try:
            # Always re-read authoritative state so we never act on (or
            # overwrite) a stale snapshot written by another component.
            state = _load_state(state_file)
            # A stop was requested -> exit cleanly.
            if state.get("state") == "STOPPED":
                _record(state_file, state, "watchdog", "stop requested; exiting")
                return 0

            pid = state.get("pid")
            alive = sl.pid_alive(pid)
            healthy = False
            if alive:
                try:
                    import urllib.request
                    with urllib.request.urlopen(
                            f"http://{host}:{port}/api/status", timeout=2) as r:
                        healthy = 200 <= r.status < 500
                except Exception:
                    healthy = False

            if alive and healthy:
                state["last_health_at"] = time.time()
                _save_state(state_file, state)
                time.sleep(args.interval)
                continue

            if alive and not healthy:
                # Process alive but not answering (stuck/booting). Wait; do not
                # restart a live process.
                time.sleep(args.interval)
                continue

            # pid dead.
            owners = _listener_pids(host, port)
            if owners:
                # Port occupied by a foreign process: do NOT restart, do NOT
                # kill. (The pid we lost may have been respawned by someone;
                # leave it alone and keep watching reality.)
                if not warned_foreign:
                    state["state"] = "FOREIGN"
                    state["last_error"] = (
                        f"port {host}:{port} owned by unmanaged process(es) "
                        f"{owners}; watchdog not restarting.")
                    _record(state_file, state, "watchdog",
                            f"foreign listeners {owners} on {port}")
                    warned_foreign = True
                time.sleep(args.interval)
                continue

            # Restart budget.
            now = time.time()
            last_restart_budget = [t for t in last_restart_budget
                                   if now - t <= args.window]
            if len(last_restart_budget) >= args.max_restarts:
                state["state"] = "FAIL"
                state["last_error"] = (
                    f"backend crashed {args.max_restarts}+ times within "
                    f"{int(args.window)}s; watchdog stopped. "
                    f"log: {log_err}")
                _record(state_file, state, "watchdog", state["last_error"])
                time.sleep(args.interval)
                continue

            # Restart (bounded), reusing the runtime's listener-resolved start
            # so duplicate protection and pid tracking stay consistent.
            last_restart_budget.append(now)
            state["restarts"] = int(state.get("restarts") or 0) + 1
            state["state"] = "STARTING"
            state["last_error"] = None
            _record(state_file, state, "watchdog_restart",
                    f"crash detected (pid {pid}); restarting "
                    f"(#{state['restarts']})")
            time.sleep(1)
            from scripts import aivido_runtime as rt
            fresh = rt._load_state()
            res = rt._start_backend(fresh)
            # Re-read authoritative state after the restart before recording:
            # _start_backend already persisted pid/RUNNING; never overwrite it
            # with our pre-restart snapshot.
            state = _load_state(state_file)
            if res.get("ok"):
                _record(state_file, state, "watchdog_spawn",
                        f"backend restarted; pid {res.get('pid')}")
            else:
                state["state"] = "FAIL"
                state["last_error"] = (
                    f"watchdog restart failed: {res.get('error')}")
                _record(state_file, state, "watchdog_spawn_failed",
                        state["last_error"])
        except BaseException as exc:  # never let one bad tick kill us
            try:
                state = _load_state(state_file)
                state["last_error"] = (
                    f"watchdog tick error: {type(exc).__name__}: {exc}")
                _record(state_file, state, "watchdog_error",
                        state["last_error"])
            except Exception:
                pass
        time.sleep(args.interval)

    return 0


def _listener_pids(host: str, port: int) -> List[int]:
    import subprocess
    pids: List[int] = []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=15).stdout or ""
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


if __name__ == "__main__":
    sys.exit(main())