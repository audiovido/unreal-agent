"""Blender discovery and generic workspace layout.

No AvaLive-specific or project-specific paths are hardcoded here. The Blender
executable can be provided explicitly (env var), auto-discovered on standard
Windows paths, or resolved from the vendored portable install under this repo.
The asset exchange workspace lives under ``<repo>/workspace/assets`` (override
with env var UNREAL_AGENT_WORKSPACE) and is shared by the Blender Agent and the
Unreal import tools.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# env overrides ---------------------------------------------------------------
ENV_EXE = "UNREAL_AGENT_BLENDER_EXE"
ENV_WORKSPACE = "UNREAL_AGENT_WORKSPACE"

# candidate locations searched in order ---------------------------------------
VENDORED = ROOT / "vendor" / "blender"
BLENDER_DIR_NAME = "blender-4.2.0-windows-x64"

STANDARD_PATHS = [
    Path("C:/Program Files/Blender Foundation"),
    Path("C:/Program Files (x86)/Blender Foundation"),
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/Public") + "/Programs"),
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/Public") + "/Blender Foundation"),
    Path.home() / "AppData" / "Roaming" / "Blender Foundation",
    Path("D:/Blender Foundation"),
    Path("D:/Program Files/Blender Foundation"),
]


def _candidate_exes() -> list[Path]:
    """Ordered list of plausible blender.exe locations."""
    exes: list[Path] = []

    env = os.getenv(ENV_EXE)
    if env:
        exes.append(Path(env))

    # Vendored portable install.
    vendored = VENDORED / BLENDER_DIR_NAME / "blender.exe"
    if vendored.exists():
        exes.append(vendored)

    # Wildcard scan of standard roots: root/Blender*/blender.exe
    for root in STANDARD_PATHS:
        if not root.exists():
            continue
        try:
            for child in sorted(root.iterdir()):
                if "blender" not in child.name.lower():
                    continue
                exe = child / "blender.exe"
                if exe.exists():
                    exes.append(exe)
        except OSError:
            continue

    # PATH lookup.
    found = shutil.which("blender")
    if found:
        exes.append(Path(found))

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for exe in exes:
        key = str(exe).lower()
        if key not in seen:
            seen.add(key)
            unique.append(exe)
    return unique


def discover_blender() -> Path | None:
    """Return the first existing Blender executable, or None."""
    for exe in _candidate_exes():
        try:
            if exe.exists() and os.access(exe, os.X_OK):
                return exe
        except OSError:
            continue
    return None


def blender_executable() -> Path:
    """Return the resolved Blender executable or raise BlenderNotFound."""
    exe = discover_blender()
    if exe is None:
        raise FileNotFoundError(
            "Blender executable not found. Set UNREAL_AGENT_BLENDER_EXE or "
            "install Blender to a standard location, or use the vendored "
            "portable install under vendor/blender/."
        )
    return exe


def blender_version(exe: Path | None = None) -> dict:
    """Probe ``blender --version``. Never raises for a missing binary."""
    exe = exe or discover_blender()
    if exe is None:
        return {"ok": False, "error": "blender not found", "exe": None}
    try:
        out = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        first = (out.stdout or out.stderr or "").strip().splitlines()
        return {
            "ok": True,
            "exe": str(exe).replace("\\", "/"),
            "version": first[0] if first else "unknown",
            "output": (out.stdout or "")[:400],
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "exe": str(exe), "error": f"{type(exc).__name__}: {exc}"}


def workspace_layout() -> dict:
    """Generic asset-exchange layout shared by Blender and Unreal agents."""
    root = Path(os.getenv(ENV_WORKSPACE, str(ROOT / "workspace" / "assets")))
    return {
        "root": root,
        "incoming": root / "incoming",
        "blender_work": root / "blender_work",
        "exports": root / "exports",
        "unreal_import": root / "unreal_import",
        "proof": root / "proof",
        "jobs": root / "blender_work" / "jobs",
        "handoff": root / "unreal_import" / "last_handoff.json",
    }


_FILE_KEYS = {"handoff"}


def ensure_workspace() -> dict:
    """Create the exchange directories (file entries like the handoff are
    never created as directories); returns the layout dict."""
    layout = workspace_layout()
    for key, path in layout.items():
        if key in _FILE_KEYS or key == "root":
            continue
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return layout


def in_blender() -> bool:
    """True when running inside Blender's embedded Python."""
    return "bpy" in sys.modules
