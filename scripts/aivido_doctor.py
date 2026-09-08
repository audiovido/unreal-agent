"""aivido_doctor.py — Aivido V1 installer/runtime self-test (doctor).

Checks, in order:

  01 release_sha        exact release commit identity (base ancestor + clean)
  02 python_runtime     venv present + Python version
  03 requirements       requirements.txt + runtime import contract
  04 backend_health     /api/status answers healthy on 127.0.0.1:8765
  05 ui_http            GET /app returns 200 HTML
  06 bridge_health      Unreal bridge 6766 ping
  07 unreal_identity    live Unreal session identity (project + engine)
  08 active_map         active level is /Game/Maps/AividoHQ
  09 proof_endpoint     /api/proof/status serves real capture evidence
  10 duplicate_start    second start refuses; exactly one 8765 listener
  11 stop_start_cycle   stop releases port; start becomes healthy again
  12 persistence        backend survives launcher process exit
  13 foreign_protection bridge 6766 + gateway 8844 untouched by us

Full mode runs the destructive cycle (10-12) and leaves the backend
RUNNING. --quick skips 10-12 for use against a live session.

Output: PASS / WARN / FAIL per check plus overall. Exit 0 = no FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import service_lifecycle as sl  # noqa: E402
from core import app_config  # noqa: E402

RELEASE_BASE_SHA = "736042ddafb45f34dfed88607e750be73e2877f2"
SERVICE = "aivido_v1"
HOST = os.environ.get("AIVIDO_BACKEND_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIVIDO_BACKEND_PORT", "8765"))
LOCAL = f"http://{HOST}:{PORT}"
UI_URL = f"{LOCAL}/app"
BRIDGE_PORT = int(os.environ.get("AIVIDO_BRIDGE_PORT", "6766"))
GATEWAY_PORT = 8844
IMPORT_CONTRACT = ("fastapi", "uvicorn", "PIL", "numpy", "pydantic",
                   "requests", "rich")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Check:
    def __init__(self, name: str):
        self.name = name
        self.status = WARN
        self.detail = "not run"

    def ok(self, detail: str) -> "Check":
        self.status, self.detail = PASS, detail
        return self

    def warn(self, detail: str) -> "Check":
        self.status, self.detail = WARN, detail
        return self

    def fail(self, detail: str) -> "Check":
        self.status, self.detail = FAIL, detail
        return self

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "status": self.status,
                "detail": self.detail}


def _http(url: str, timeout: float = 3.0) -> Tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def _bridge():
    from tools.unreal.unreal_bridge import UnrealBridge
    return UnrealBridge(host=HOST, port=BRIDGE_PORT, timeout=15)


def _listener_count() -> int:
    import scripts.aivido_runtime as rt
    return len(rt._listener_pids(HOST, PORT))


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip()
    except Exception:
        return ""


class Doctor:
    def __init__(self, quick: bool = False):
        self.quick = quick
        self.checks: List[Check] = []

    def run(self) -> Dict[str, Any]:
        self.checks = [
            self.check_release_sha(),
            self.check_python(),
            self.check_requirements(),
            self.check_backend_health(),
            self.check_ui(),
            self.check_bridge(),
            self.check_unreal_identity(),
            self.check_active_map(),
            self.check_proof(),
        ]
        if not self.quick:
            self.checks += [
                self.check_duplicate_start(),
                self.check_stop_start_cycle(),
                self.check_persistence(),
            ]
        self.checks.append(self.check_foreign_protection())

        statuses = [c.status for c in self.checks]
        if FAIL in statuses:
            overall = FAIL
        elif WARN in statuses:
            overall = WARN
        else:
            overall = PASS
        return {
            "product": "Aivido V1",
            "mode": "quick" if self.quick else "full",
            "overall": overall,
            "checks": [c.to_dict() for c in self.checks],
            "summary": {
                "pass": statuses.count(PASS),
                "warn": statuses.count(WARN),
                "fail": statuses.count(FAIL),
            },
            "ran_at": time.time(),
        }

    # ------------------------------------------------------------------
    def check_release_sha(self) -> Check:
        c = Check("release_sha")
        head = _git("rev-parse", "HEAD")
        if not head:
            # Shipped package: no .git. Fall back to the recorded build
            # identity (version.json) produced by build_v1_package.py.
            version_file = ROOT / "version.json"
            try:
                meta = json.loads(version_file.read_text(encoding="utf-8"))
                sha = str(meta.get("sha") or "")
                if sha:
                    return c.ok(f"packaged build sha={sha[:12]} "
                                f"(version.json; base {RELEASE_BASE_SHA[:12]})")
            except Exception:
                pass
            return c.fail("no git HEAD and no version.json "
                          "(not a git checkout or package)")
        is_ancestor = _git("merge-base", "--is-ancestor",
                           RELEASE_BASE_SHA, "HEAD")
        base_ok = is_ancestor == "" and _git("rev-parse", RELEASE_BASE_SHA)
        dirty = _git("status", "--porcelain", "--", "app", "core",
                     "scripts", "ui", "requirements.txt")
        detail = (f"HEAD={head[:12]} base={RELEASE_BASE_SHA[:12]} "
                  f"ancestor={base_ok}")
        if not base_ok:
            return c.fail(detail + " (base SHA not an ancestor of HEAD)")
        if dirty:
            return c.warn(detail + f" dirty runtime files: {dirty[:200]}")
        return c.ok(detail)

    def check_python(self) -> Check:
        c = Check("python_runtime")
        ver = platform.python_version()
        venv_py = (ROOT / ".venv" / "Scripts" / "python.exe"
                   if sys.platform == "win32"
                   else ROOT / ".venv" / "bin" / "python")
        if not venv_py.exists():
            return c.fail(f"venv missing: {venv_py}")
        major, minor = (int(x) for x in ver.split(".")[:2])
        if (major, minor) < (3, 9):
            return c.fail(f"Python {ver} needs >= 3.9")
        return c.ok(f"Python {ver} at {venv_py}")

    def check_requirements(self) -> Check:
        c = Check("requirements")
        req = ROOT / "requirements.txt"
        if not req.exists():
            return c.fail("requirements.txt missing")
        missing = []
        for mod in IMPORT_CONTRACT:
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        if missing:
            return c.fail(f"import contract missing: {missing} "
                          f"(reinstall with the platform installer: "
                          "install-aivido.ps1 / install-aivido.sh)")
        return c.ok("requirements.txt present; all imports resolve")

    def check_backend_health(self) -> Check:
        c = Check("backend_health")
        try:
            status, body = _http(f"{LOCAL}/api/status")
            data = json.loads(body.decode("utf-8", "replace"))
            if status == 200 and data.get("ok"):
                unreal = data.get("unreal") or {}
                detail = (f"HTTP 200 ok=true unreal="
                          f"{'ok' if unreal.get('ok') else 'down'}")
                return c.ok(detail)
            return c.fail(f"HTTP {status} or ok=false "
                          f"(log: {sl.LOG_DIR / SERVICE + '.err.log'})")
        except Exception as exc:
            return c.fail(f"{type(exc).__name__}: {exc} "
                          f"(log: {sl.LOG_DIR / SERVICE + '.err.log'})")

    def check_ui(self) -> Check:
        c = Check("ui_http")
        try:
            status, body = _http(UI_URL)
            text = body.decode("utf-8", "replace")
            if status == 200 and ("Aivido" in text or "aivido" in text
                                  or "Director" in text):
                return c.ok(f"{UI_URL} -> HTTP 200 (aivido UI marker present)")
            return c.warn(f"{UI_URL} -> HTTP {status} (marker not detected)")
        except Exception as exc:
            return c.fail(f"{UI_URL} -> {type(exc).__name__}: {exc}")

    def check_bridge(self) -> Check:
        c = Check("bridge_health")
        try:
            ping = _bridge().ping()
            if ping.get("ok"):
                return c.ok(f"6766 ping ok "
                            f"engine={ping.get('engine', '?')}")
            return c.fail(f"6766 ping failed: {ping.get('error')}")
        except Exception as exc:
            return c.fail(f"6766 probe error: {exc}")

    def check_unreal_identity(self) -> Check:
        c = Check("unreal_identity")
        try:
            ident = _bridge().get_project_identity()
            info = ident.get("result") if isinstance(ident, dict) else None
            if isinstance(info, dict) and info.get("ok"):
                return c.ok(f"{info.get('project_name')} "
                            f"engine={info.get('engine')}")
            return c.fail(f"identity failed: "
                          f"{(info or ident).get('error', 'unknown')}")
        except Exception as exc:
            return c.fail(f"identity error: {exc}")

    def check_active_map(self) -> Check:
        c = Check("active_map")
        try:
            lvl = _bridge().get_current_level()
            info = lvl.get("result") if isinstance(lvl, dict) else None
            path = str((info or {}).get("world_path") or "")
            if path.startswith("/Game/Maps/AividoHQ"):
                return c.ok(f"AividoHQ loaded ({path})")
            if path.startswith("/Game/"):
                return c.warn(f"map loaded is {path}, not AividoHQ")
            return c.fail(f"no /Game map loaded: {path or info}")
        except Exception as exc:
            return c.fail(f"map probe error: {exc}")

    def check_proof(self) -> Check:
        c = Check("proof_endpoint")
        try:
            status, body = _http(f"{LOCAL}/api/proof/status")
            data = json.loads(body.decode("utf-8", "replace"))
            if status == 200 and data.get("ok"):
                return c.ok(f"proof present: {data.get('path')} "
                            f"({data.get('size')} bytes)")
            return c.warn("proof endpoint answers but no capture yet "
                          "(run the V1 smoke mission)")
        except Exception as exc:
            return c.fail(f"proof endpoint error: {exc}")

    def check_duplicate_start(self) -> Check:
        c = Check("duplicate_start")
        import scripts.aivido_runtime as rt
        # Backend must be running for this check.
        ensure = rt.cmd_start(None)
        if ensure != 0:
            return c.fail("could not establish running backend "
                          "before duplicate test")
        time.sleep(1)
        listeners_before = _listener_count()
        again = rt.cmd_start(None)
        listeners_after = _listener_count()
        if again == 0 and listeners_before == 1 and listeners_after == 1:
            return c.ok("second start reused/refused; exactly one "
                        "127.0.0.1:8765 listener")
        return c.fail(f"duplicate protection failed "
                      f"(before={listeners_before} after={listeners_after} "
                      f"rc={again})")

    def check_stop_start_cycle(self) -> Check:
        c = Check("stop_start_cycle")
        import scripts.aivido_runtime as rt
        if rt.cmd_stop(None) != 0:
            return c.fail("stop failed")
        deadline = time.time() + 20
        while time.time() < deadline and rt._probe_port(HOST, PORT):
            time.sleep(0.3)
        if rt._probe_port(HOST, PORT):
            return c.fail("port still occupied after stop")
        time.sleep(0.5)
        if rt.cmd_start(None) != 0:
            return c.fail(f"start after stop failed "
                          f"(log: {sl.LOG_DIR / SERVICE + '.err.log'})")
        deadline = time.time() + 90
        while time.time() < deadline and not rt._backend_ready():
            time.sleep(0.5)
        if not rt._backend_ready():
            return c.fail("backend not healthy after restart "
                          f"(log: {sl.LOG_DIR / SERVICE + '.err.log'})")
        if _listener_count() != 1:
            return c.fail("listener count != 1 after cycle")
        return c.ok("stop released port; start healthy; single listener")

    def check_persistence(self) -> Check:
        c = Check("persistence")
        import scripts.aivido_runtime as rt
        # Ensure stopped so we spawn through a launcher process.
        rt.cmd_stop(None)
        deadline = time.time() + 20
        while time.time() < deadline and rt._probe_port(HOST, PORT):
            time.sleep(0.3)
        py = rt._venv_python()
        launcher = subprocess.Popen(
            [py, str(ROOT / "scripts" / "aivido_runtime.py"), "start"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        rc = launcher.wait(timeout=150)  # launcher process fully exits
        pid_after = rt._backend_pid()
        ready_after = rt._backend_ready()
        if rc != 0 or not ready_after or not pid_after:
            return c.fail(
                f"launcher exited rc={rc} but backend "
                f"pid={pid_after} healthy={ready_after} "
                f"(log: {sl.LOG_DIR / SERVICE + '.err.log'})")
        if not sl.pid_alive(pid_after):
            return c.fail("backend pid died after launcher exit")
        time.sleep(1)
        if _listener_count() != 1:
            return c.fail("listener count != 1 after persistence test")
        return c.ok(f"launcher exited rc=0; backend pid {pid_after} "
                    "still healthy")

    def check_foreign_protection(self) -> Check:
        c = Check("foreign_protection")
        bridge_alive = _probe_port("127.0.0.1", BRIDGE_PORT)
        gateway_alive = _probe_port("127.0.0.1", GATEWAY_PORT)
        if not bridge_alive:
            return c.fail(f"bridge {BRIDGE_PORT} not listening "
                          "(expected; we must never kill it)")
        if not gateway_alive:
            return c.warn(f"gateway {GATEWAY_PORT} not listening "
                          "(expected; we must never kill it)")
        return c.ok(f"bridge {BRIDGE_PORT} and gateway {GATEWAY_PORT} "
                    "untouched and alive")


def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="aivido_doctor")
    p.add_argument("--quick", action="store_true",
                   help="skip duplicate/cycle/persistence tests")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    doc = Doctor(quick=args.quick).run()

    if args.json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print("AIVIDO V1 DOCTOR")
        print(f"mode: {doc['mode']}  overall: {doc['overall']}")
        for c in doc["checks"]:
            print(f"  [{c['status']:>4}] {c['name']:24} {c['detail']}")
        s = doc["summary"]
        print(f"summary: {s['pass']} pass / {s['warn']} warn / "
              f"{s['fail']} fail")
        if doc["overall"] == FAIL:
            fails = [c for c in doc["checks"] if c["status"] == FAIL]
            print("FAILURES:")
            for f in fails:
                print(f"  - {f['name']}: {f['detail']}")
            print(f"backend log: {sl.LOG_DIR / SERVICE + '.err.log'}")
    return 0 if doc["overall"] != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())