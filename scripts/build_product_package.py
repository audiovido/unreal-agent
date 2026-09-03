"""build_product_package.py — reproducible package layout (Lane B, Part 7).

Builds dist/unreal-agent-<version>/ containing:

  product_launcher.py          entrypoint (doctor/status/start/…/serve)
  core/                        product + lane-B modules (read-only copies)
  app/                         product backend module
  ui/                          end-user UI resources
  config/settings.json         dev-console settings (copied verbatim)
  version.json / manifest.json build metadata
  README-packaging.txt         how to run the package

Runtime note: this layout targets the project's Python environment (the
.venv).  Producing a standalone native .exe additionally requires a
packager (e.g. PyInstaller) which is not vendored in the repo — the build
records that as an explicit, evidence-backed packaging blocker if absent.

Usage:  python scripts/build_product_package.py [--out DIR]
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
from core import app_config  # noqa: E402

COPY_DIRS = ["ui"]
COPY_FILES = [
    "product_launcher.py",          # scripts/product_launcher.py at pkg root
    "version.json",
    "manifest.json",
]
MODULES_CORE = [
    "app_config.py", "env_doctor.py", "service_lifecycle.py",
    "editor_lease.py", "first_run.py", "product_core.py",
    "config.py", "doctor.py", "observability.py", "project_safety.py",
]
MODULES_APP = ["product_app.py"]

README = """Unreal Agent — product shell package
====================================

Run with the project Python environment (the .venv):

  python product_launcher.py doctor        # environment diagnostics
  python product_launcher.py status        # backend + lease status
  python product_launcher.py               # start the product backend (serve)

No terminal is required in normal use once this is launched from the
desktop (double-click wrapper) — ports/hosts come from defaults or
UA_* environment variables.  This layout is a Python package bundle; a
native .exe build additionally needs a packager such as PyInstaller.

Dependencies (installed in the .venv): fastapi, uvicorn, pillow, numpy,
pydantic.
"""


def git_head() -> str:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short",
                            "HEAD"], capture_output=True, text=True,
                           timeout=10)
        return (r.stdout or "").strip()[:12] or "unknown"
    except Exception:
        return "unknown"


def build(out_dir: Path) -> Dict:
    version = app_config.VERSION
    pkg = out_dir / f"unreal-agent-{version}"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    (pkg / "core").mkdir()
    (pkg / "app").mkdir()
    (pkg / "config").mkdir()

    # entrypoint
    shutil.copy2(ROOT / "scripts" / "product_launcher.py",
                 pkg / "product_launcher.py")

    # lane-B + product modules (read-only copies of source files)
    copied_core: List[str] = []
    for mod in MODULES_CORE:
        src = ROOT / "core" / mod
        if src.exists():
            shutil.copy2(src, pkg / "core" / mod)
            copied_core.append(f"core/{mod}")
    copied_app: List[str] = []
    for mod in MODULES_APP:
        src = ROOT / "app" / mod
        if src.exists():
            shutil.copy2(src, pkg / "app" / mod)
            copied_app.append(f"app/{mod}")
    shutil.copy2(ROOT / "app" / "__init__.py", pkg / "app" / "__init__.py")

    # UI resources + settings (settings.json has no secrets; kept for parity)
    for d in COPY_DIRS:
        shutil.copytree(ROOT / d, pkg / d,
                        ignore=shutil.ignore_patterns("*.agentboard_backup"))
    settings_src = ROOT / "config" / "settings.json"
    if settings_src.exists():
        shutil.copy2(settings_src, pkg / "config" / "settings.json")

    # metadata
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version_meta = {"product": app_config.PRODUCT_NAME, "version": version,
                    "built_at": now, "git_head": git_head(),
                    "python": sys.version.split()[0]}
    manifest = {
        "name": f"unreal-agent-{version}", "version": version,
        "entrypoint": "product_launcher.py",
        "runtime": "python3 (project .venv)",
        "files": sorted(copied_core + copied_app + COPY_DIRS +
                        ["product_launcher.py", "config/settings.json"]),
        "built_at": now,
    }
    (pkg / "version.json").write_text(
        json.dumps(version_meta, indent=2), encoding="utf-8")
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (pkg / "README-packaging.txt").write_text(README, encoding="utf-8")

    # zip
    shutil.make_archive(str(pkg), "zip", pkg.parent, pkg.name)

    # packager availability evidence
    packager = shutil.which("pyinstaller")
    report = {
        "ok": True,
        "output_dir": str(pkg),
        "zip": str(pkg) + ".zip",
        "entrypoint": str(pkg / "product_launcher.py"),
        "version": version,
        "git_head": version_meta["git_head"],
        "files_count": len(manifest["files"]),
        "native_exe": {"available": bool(packager),
                       "evidence": packager or "pyinstaller not on PATH"},
    }
    (pkg / "_build_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Build the product package layout.")
    p.add_argument("--out", default=str(ROOT / "dist"))
    args = p.parse_args()
    build(Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
