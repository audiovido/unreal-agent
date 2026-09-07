"""build_v1_package.py — assemble the distributable Aivido V1 package.

Produces dist/Aivido-V1/ containing only the files a normal user needs to
install and run Aivido V1 on a Windows machine:

  install-aivido.ps1 / .cmd     one-click installer (idempotent)
  start-aivido.ps1 / .cmd       start/stop/restart/status/doctor/smoke
  stop-aivido.cmd
  requirements.txt              runtime dependency contract
  app/ core/ tools/ ui/         runtime code (source only, no caches)
  blender_agent/                optional-module config (WARN-if-absent)
  memory/                       tracked baseline files only
  config/settings.json          machine settings (no secrets)
  scripts/aivido_runtime.py     persistent backend runtime
  scripts/aivido_watchdog.py    crash watchdog
  scripts/aivido_doctor.py      V1 self-test
  scripts/aivido_smoke.py       bounded Unreal smoke mission
  README-QUICKSTART.md          three-action quickstart
  version.json                  build identity (branch + SHA + time)

Excludes: .venv, __pycache__, *.log, .git, dist/, backups, editor
projects/content, private credentials and generated state.

Usage: python scripts/build_v1_package.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOP_LEVEL_PY_DIRS = ["app", "core", "tools", "blender_agent"]
# app/mcp_gateway.py is a standalone MCP server requiring the external `mcp`
# SDK (not part of the requirements.txt runtime contract). The V1 product
# runtime (app.served) never imports it, so it is excluded to keep the
# package's dependency contract clean and installable.
PACKAGE_EXCLUDE_FILES = {"app/mcp_gateway.py"}
TOP_LEVEL_FILES = [
    "requirements.txt",
    "install-aivido.ps1",
    "start-aivido.ps1",
    "install-aivido.cmd",
    "start-aivido.cmd",
    "stop-aivido.cmd",
]
SCRIPTS = [
    "aivido_runtime.py", "aivido_watchdog.py", "aivido_doctor.py",
    "aivido_smoke.py", "aivido_install_check.py",
]
UI_EXCLUDE = ("backup-", ".zip", ".agentboard_backup", ".broken-encoding")


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _ignore_py(dirpath, names):
    out = []
    for n in names:
        p = Path(dirpath) / n
        if n == "__pycache__" or n.endswith(".pyc"):
            out.append(n)
        elif p.is_file() and n.endswith(".py"):
            continue  # keep source
        elif p.is_file():
            out.append(n)  # drop non-py files inside python dirs
        else:
            out.append(n)  # drop subdirs of python packages we do not need
    return out


def _copy_py_src(src: Path, dst: Path) -> List[str]:
    """Copy .py files recursively, skipping caches and __init__-less dirs."""
    copied: List[str] = []
    for p in sorted(src.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(src)
        rel_global = str(Path(src.name) / rel).replace("\\", "/")
        if rel_global in PACKAGE_EXCLUDE_FILES:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        copied.append(rel_global)
    return copied


def build(out_root: Path) -> Dict:
    version = _git("rev-parse", "--short", "HEAD") or "dev"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    full_sha = _git("rev-parse", "HEAD") or "unknown"
    pkg = out_root / "Aivido-V1"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    files: List[str] = []

    # entry points + requirements
    for name in TOP_LEVEL_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, pkg / name)
            files.append(name)

    # python source trees
    for d in TOP_LEVEL_PY_DIRS:
        src = ROOT / d
        if not src.is_dir():
            continue
        copied = _copy_py_src(src, pkg / d)
        files += copied

    # scripts needed by the launchers/doctor/smoke
    (pkg / "scripts").mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS:
        src = ROOT / "scripts" / name
        if src.exists():
            shutil.copy2(src, pkg / "scripts" / name)
            files.append(f"scripts/{name}")

    # ui assets (no backups/zips)
    ui_dst = pkg / "ui"
    ui_dst.mkdir(parents=True, exist_ok=True)
    for src in sorted((ROOT / "ui").iterdir()):
        if src.is_dir():
            continue
        if any(x in src.name for x in UI_EXCLUDE):
            continue
        if src.name.endswith((".html", ".js", ".css", ".json", ".txt")):
            shutil.copy2(src, ui_dst / src.name)
            files.append(f"ui/{src.name}")

    # config: settings.json only (no secrets/leases/runtime state)
    (pkg / "config").mkdir(exist_ok=True)
    settings = ROOT / "config" / "settings.json"
    if settings.exists():
        shutil.copy2(settings, pkg / "config" / "settings.json")
        files.append("config/settings.json")

    # memory baseline (tracked only, no conversation/session state)
    mem_src = ROOT / "memory"
    if mem_src.is_dir():
        tracked = set()
        try:
            out = subprocess.run(["git", "-C", str(ROOT), "ls-files",
                                  "memory"], capture_output=True, text=True,
                                 timeout=15)
            tracked = {ln.strip() for ln in (out.stdout or "").splitlines()
                       if ln.strip()}
        except Exception:
            pass
        if tracked:
            for rel in sorted(tracked):
                src = ROOT / rel
                if src.is_file():
                    target = pkg / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    files.append(rel.replace("\\", "/"))

    # README quickstart
    readme = pkg / "README-QUICKSTART.md"
    readme.write_text(QUICKSTART, encoding="utf-8")
    files.append("README-QUICKSTART.md")

    # version identity
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version_meta = {
        "product": "Aivido V1",
        "branch": branch,
        "sha": full_sha,
        "sha_short": version,
        "built_at": now,
        "python": sys.version.split()[0],
        "entrypoint": "install-aivido.ps1",
    }
    (pkg / "version.json").write_text(
        json.dumps(version_meta, indent=2), encoding="utf-8")
    files.append("version.json")

    report = {
        "ok": True,
        "output_dir": str(pkg),
        "files_count": len(files),
        "branch": branch,
        "sha": full_sha,
        "built_at": now,
    }
    (pkg / "_build_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return report


QUICKSTART = """# Aivido V1 — Quickstart (3 actions)

Aivido V1 is a Windows product that turns a live Unreal Engine 5.8 editor
into an autonomous production studio. It installs its own Python runtime,
starts a persistent backend that survives terminal close, and gives you a
Director's Booth UI plus real Unreal mission execution.

## Requirements
- Windows 10/11 with Python 3.9+ installed (https://www.python.org/downloads/)
- A running Unreal Editor 5.8 with the Aivido bridge plugin listening on
  127.0.0.1:6766 (the ASSET_Showcase2 / AividoHQ session)
- Optional: Tailscale (free) for remote access from another machine

## Quickstart — 3 actions

1. **Install** — double-click `install-aivido.cmd` (or run
   `powershell -ExecutionPolicy Bypass -File install-aivido.ps1`).
   This creates `.venv`, installs `requirements.txt` (only once), validates
   imports, detects Unreal + your project, and starts the backend. A second
   run is a no-op re-check — it never reinstalls unnecessarily.

2. **Start / control** — double-click `start-aivido.cmd` to start and open
   the UI. Same launcher for everything:
   ```
   start-aivido.ps1 status     # state, health, log paths (FAIL is visible)
   start-aivido.ps1 stop       # stop backend (bridge/gateway untouched)
   start-aivido.ps1 restart    # stop then start
   start-aivido.ps1 doctor     # full V1 self-test (PASS/WARN/FAIL)
   start-aivido.ps1 smoke      # real bounded Unreal smoke mission
   ```

3. **Open the UI** — the installer opens it for you:
   ```
   Local:   http://127.0.0.1:8765/app
   Remote:  https://<your-tailscale-name>.ts.net/app  (start-aivido.ps1 remote on)
   ```

## Persistence
The backend runs as a detached Windows process with a small watchdog. It
survives the launcher terminal closing, restarts itself after a crash
(bounded, max 3 restarts / 15 min), refuses duplicate starts, and NEVER
touches the Unreal bridge (6766) or the MCP gateway (8844). Logs:
`config/logs/aivido_v1.{out,err}.log`. `status` prints FAIL + the log path
instead of hiding failures.

## Self test
`start-aivido.ps1 doctor` verifies release SHA, Python, requirements,
backend health, UI HTTP 200, bridge 6766, Unreal session identity, active
map (AividoHQ), the proof endpoint, duplicate-start protection, a
stop/start cycle, and process persistence after launcher exit.
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Build the Aivido V1 package.")
    p.add_argument("--out", default=str(ROOT / "dist"))
    args = p.parse_args()
    report = build(Path(args.out))
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())