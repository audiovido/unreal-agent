"""aivido_install_check.py — python-side checks for install-aivido.ps1.

The installer invokes this helper as a plain native command, which avoids
fragile multi-line `python -c` argument passing under Windows PowerShell
5.1. Modes:

  imports  -> exit 0 when the runtime import contract resolves, else exit 1
  editor   -> print EDITOR=<label>|<editor_exe> or EDITOR=none
  project  -> print PROJECT=<path> (pinned/recent/scanned) or PROJECT=none

Only reads files/registry; never starts anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from core import app_config  # noqa: E402
except Exception:
    app_config = None

IMPORT_CONTRACT = ("fastapi", "uvicorn", "PIL", "numpy", "pydantic",
                   "requests", "rich")


def cmd_imports() -> int:
    missing = []
    for mod in IMPORT_CONTRACT:
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        print("missing: " + ", ".join(missing))
        return 1
    print("import contract OK")
    return 0


def cmd_editor() -> int:
    try:
        builds = [b for b in app_config.detect_unreal_builds()
                  if b.get("editor_exe")]
        if builds:
            print(f"EDITOR={builds[0]['label']}|{builds[0]['editor_exe']}")
            return 0
    except Exception as exc:
        print(f"EDITOR=probe_error:{type(exc).__name__}:{exc}")
        return 1
    print("EDITOR=none")
    return 0


def cmd_project(pinned: str = "") -> int:
    try:
        found = _candidates(pinned)
        if found:
            app_config.set_pref("recent_project", found[0])
            print("PROJECT=" + found[0])
            return 0
    except Exception as exc:
        print(f"PROJECT=probe_error:{type(exc).__name__}:{exc}")
        return 1
    print("PROJECT=none")
    return 0


def _candidates(pinned: str):
    out = []
    if pinned and Path(pinned).is_file():
        out.append(pinned)
    cfg = app_config.load_config()
    if cfg.recent_project and Path(cfg.recent_project).is_file():
        out.append(cfg.recent_project)
    settings = {}
    try:
        import json as _j
        settings = _j.loads(app_config.SETTINGS_FILE.read_text(
            encoding="utf-8-sig"))
    except Exception:
        pass
    for key in ("uproject", "recent_project"):
        v = settings.get(key) or settings.get("unreal", {}).get(key)
        if v and Path(str(v)).is_file():
            out.append(str(v))
    scan = [Path(ROOT) / "assetlib" / "tests" / "ue",
            Path.home() / "Desktop" / "Unreal-Agent" / "assetlib" / "tests" /
            "ue",
            Path.home() / "Desktop"]
    for base in scan:
        if base and base.is_dir():
            for up in sorted(base.rglob("*.uproject")):
                if len(out) >= 12:
                    break
                out.append(str(up))
    seen, uniq = set(), []
    for p in out:
        key = str(Path(p).resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(str(Path(p).resolve()))
    return uniq


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    mode = args[0] if args else "imports"
    pinned = args[1] if len(args) > 1 else ""
    if mode == "imports":
        return cmd_imports()
    if mode == "editor":
        return cmd_editor()
    if mode == "project":
        return cmd_project(pinned)
    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())