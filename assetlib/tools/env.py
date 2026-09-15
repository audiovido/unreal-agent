"""Shared environment/path discovery for the FREEBUFF ASSET library.

Pure stdlib, host-side. Reads the repo layout without importing product
modules so this library stays decoupled. Blender and UE locations come from
the repo config / vendor tree with env overrides.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
ASSETLIB = ROOT / "assetlib"

BLENDER_DIR_NAME = "blender-4.2.0-windows-x64"
VENDOR_BLENDER = ROOT / "vendor" / "blender" / BLENDER_DIR_NAME / "blender.exe"

SETTINGS_PATH = ROOT / "config" / "settings.json"


def repo_root() -> Path:
    return ROOT


def assetlib_root() -> Path:
    return ASSETLIB


def paths() -> dict:
    return {
        "root": str(ROOT),
        "assetlib": str(ASSETLIB),
        "content": str(ASSETLIB / "content"),
        "source": str(ASSETLIB / "source"),
        "downloads": str(ASSETLIB / "downloads"),
        "projects": str(ASSETLIB / "projects"),
        "tests": str(ASSETLIB / "tests"),
        "tests_blender": str(ASSETLIB / "tests" / "blender"),
        "tests_ue": str(ASSETLIB / "tests" / "ue"),
        "proof": str(ASSETLIB / "proof"),
        "proof_screens": str(ASSETLIB / "proof" / "screens"),
        "reports": str(ASSETLIB / "reports"),
        "catalog": str(ASSETLIB / "catalog"),
        "catalog_json": str(ASSETLIB / "catalog" / "catalog.json"),
    }


def ensure_layout() -> dict:
    p = paths()
    dirs = [
        "content", "source", "downloads", "projects", "tests",
        "tests_blender", "tests_ue", "proof", "proof_screens",
        "reports", "catalog",
    ]
    for key in dirs:
        Path(p[key]).mkdir(parents=True, exist_ok=True)
    return p


def discover_blender() -> Path:
    """Blender exe: env override -> vendored portable -> standard paths."""
    env = os.getenv("ASSETLIB_BLENDER_EXE")
    candidates = []
    if env:
        candidates.append(Path(env))
    if VENDOR_BLENDER.exists():
        candidates.append(VENDOR_BLENDER)
    for root in [
        Path("C:/Program Files/Blender Foundation"),
        Path("C:/Program Files (x86)/Blender Foundation"),
        Path("D:/Program Files/Blender Foundation"),
        Path(os.environ.get("LOCALAPPDATA", "C:/Users/Public")) / "Programs",
    ]:
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if "blender" not in child.name.lower():
                continue
            exe = child / "blender.exe"
            if exe.exists():
                candidates.append(exe)
    found = shutil.which("blender")
    if found:
        candidates.append(Path(found))
    for exe in candidates:
        if exe.exists():
            return exe
    raise FileNotFoundError(
        "Blender executable not found. Set ASSETLIB_BLENDER_EXE or install "
        "Blender 4.2 LTS to a standard location / vendor/blender/."
    )


def _settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
    return {}


def discover_unreal() -> dict:
    """Return editor + cmd exe paths from repo settings, else defaults."""
    engine = Path(os.getenv("ASSETLIB_UE_ENGINE") or
                  _settings().get("unreal_engine") or "D:/Program Files/Epic Games/UE_5.8")
    binaries = engine / "Engine" / "Binaries" / "Win64"
    return {
        "engine": str(engine),
        "editor": str(binaries / "UnrealEditor.exe"),
        "cmd": str(binaries / "UnrealEditor-Cmd.exe"),
    }
