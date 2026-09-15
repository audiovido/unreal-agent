#!/usr/bin/env python3
import argparse, json, os, signal, socket, subprocess, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/admin/Projects/unreal-agent")
PYTHON = ROOT / ".venv-mac/bin/python"
STATE = ROOT / "runtime/command_jobs.json"
LOGDIR = Path("/Users/admin/Desktop/AIVIDO_MAC_LOGS")
BACKEND_LOG = LOGDIR / "backend.log"
PIDFILE = ROOT / "runtime/aivido_supervisor.pid"
BACKEND_PORT, BRIDGE_PORT, OLD_PROXY_PORT = 8765, 6766, 8777
STALE_SECONDS = 180

def port_open(port, timeout=0.4):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False

def get_json(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def backend_healthy():
    try:
        get_json("http://127.0.0.1:8765/api/status")
        return True
    except Exception:
        return False

def kill_port(port):
    try:
        out = subprocess.check_output(
            ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return
    for p in out.split():
        try:
            os.kill(int(p), signal.SIGTERM)
        except Exception:
            pass

def start_backend():
    LOGDIR.mkdir(parents=True, exist_ok=True)
    f = open(BACKEND_LOG, "ab", buffering=0)
    subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(ROOT), stdout=f, stderr=f, start_new_session=True
    )
    for _ in range(40):
        if backend_healthy():
            return True
        time.sleep(0.25)
    return False

def ensure_backend():
    if backend_healthy():
        return True
    kill_port(BACKEND_PORT)
    time.sleep(0.5)
    return start_backend()

def parse_age(value):
    if value is None:
        return None
    now = time.time()
    if isinstance(value, (int, float)):
        return max(0.0, now - float(value))
    if isinstance(value, str):
        txt = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, now - dt.timestamp())
        except Exception:
            try:
                return max(0.0, now - float(txt))
            except Exception:
                return None
    return None

def stale_running_jobs():
    if not STATE.exists():
        return []
    try:
        data = json.loads(STATE.read_text())
    except Exception:
        return []
    jobs = data.get("jobs", {})
    iterable = jobs if isinstance(jobs, list) else jobs.values()
    stale = []
    for j in iterable:
        if str(j.get("state", "")).lower() != "running":
            continue
        age = parse_age(j.get("updated_at") or j.get("started_at") or j.get("created_at"))
        if age is not None and age > STALE_SECONDS:
            stale.append((j.get("job_id") or j.get("id"), int(age)))
    return stale

def restart_backend_for_stale():
    stale = stale_running_jobs()
    if not stale:
        return []
    kill_port(BACKEND_PORT)
    time.sleep(0.8)
    if not start_backend():
        raise RuntimeError("backend restart failed after stale job detection")
    return stale

def check_once():
    if port_open(OLD_PROXY_PORT):
        kill_port(OLD_PROXY_PORT)
        time.sleep(0.3)
    if not ensure_backend():
        raise RuntimeError("backend unavailable")
    stale = restart_backend_for_stale()
    return {
        "backend": "ready" if backend_healthy() else "down",
        "bridge": "ready" if port_open(BRIDGE_PORT) else "down",
        "old_proxy_8777": "removed" if not port_open(OLD_PROXY_PORT) else "present",
        "stale_recovered": stale,
    }

def loop():
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    if PIDFILE.exists():
        try:
            old = int(PIDFILE.read_text().strip())
            os.kill(old, 0)
            print("supervisor already running", old)
            return 0
        except Exception:
            pass
    PIDFILE.write_text(str(os.getpid()))
    try:
        while True:
            try:
                check_once()
            except Exception as e:
                print("supervisor:", repr(e), flush=True)
            time.sleep(15)
    finally:
        try:
            PIDFILE.unlink()
        except Exception:
            pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    if args.loop:
        return loop()
    print(json.dumps(check_once(), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
