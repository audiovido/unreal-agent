"""Canonical filesystem and runtime paths for an installed Aivido package.

Portable contract: every path resolves relative to the package itself
(AIVIDO_HOME) or to well-known per-user locations; nothing depends on the
original repository checkout, a developer venv, the Windows registry, or
Shadow-specific paths.  The same module serves the Windows and macOS
distributions; platform-specific branches are guarded by ``sys.platform``
and are inert on the other OS.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolved_env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


PACKAGE_ROOT = _resolved_env_path(
    "AIVIDO_HOME", Path(__file__).resolve().parents[1])
PROJECT_ROOT = _resolved_env_path(
    "AIVIDO_PROJECT_ROOT", Path.home() / "Documents" / "Aivido" / "Projects")
RUNTIME_DIR = PACKAGE_ROOT / "config" / "runtime"
BRIDGE_PORT = int(os.environ.get("AIVIDO_BRIDGE_PORT", "6766"))


def _venv_python_candidates() -> tuple[Path, ...]:
    if sys.platform == "win32":
        return (PACKAGE_ROOT / ".venv" / "Scripts" / "python.exe",)
    return (PACKAGE_ROOT / ".venv" / "bin" / "python",
            PACKAGE_ROOT / ".venv" / "bin" / "python3")


def python_executable() -> Path:
    """Resolve the interpreter without requiring a development checkout."""
    override = os.environ.get("AIVIDO_PYTHON", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    for cand in _venv_python_candidates():
        if cand.is_file():
            return cand.resolve()
    return Path(sys.executable).resolve()


def local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA", "").strip()
    if value:
        return Path(value).expanduser().resolve()
    return RUNTIME_DIR


def vision_review_script() -> Path:
    if sys.platform == "win32":
        return local_app_data() / "UnrealAgent" / "vision_review.ps1"
    return Path.home() / ".local" / "share" / "UnrealAgent" / "vision_review.sh"


def _editor_binaries(engine_root: Path) -> tuple[Path, ...]:
    """Candidate editor executables under an engine install root."""
    root = Path(engine_root)
    return (
        root / "Engine" / "Binaries" / "Mac" / "UnrealEditor",
        root / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" /
        "Contents" / "MacOS" / "UnrealEditor",
        root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe",
    )


def unreal_editor_executable() -> Path | None:
    """Resolve Unreal from an override, the Epic registry, or common macOS
    install locations.  Never starts anything; read-only detection."""
    override = os.environ.get("UNREAL_AGENT_ENGINE_DIR", "").strip()
    if override:
        for exe in _editor_binaries(Path(override).expanduser().resolve()):
            if exe.is_file():
                return exe.resolve()
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\EpicGames\Unreal Engine\Builds")
            index = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                for exe in _editor_binaries(Path(str(value))):
                    if exe.is_file():
                        winreg.CloseKey(key)
                        return exe.resolve()
            winreg.CloseKey(key)
        except OSError:
            pass
    for base in _unreal_scan_dirs():
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or not child.name.upper().startswith("UE_"):
                continue
            for exe in _editor_binaries(child):
                if exe.is_file():
                    return exe.resolve()
    return None


def _unreal_scan_dirs() -> tuple[Path, ...]:
    """Directories scanned for UE_* engine installs on non-Windows hosts.

    ``AIVIDO_UNREAL_SCAN_DIRS`` (os.pathsep-separated) overrides the defaults
    and is also honoured on Windows so detection is testable anywhere.
    """
    value = os.environ.get("AIVIDO_UNREAL_SCAN_DIRS", "").strip()
    if value:
        return tuple(Path(p).expanduser().resolve()
                     for p in value.split(os.pathsep) if p.strip())
    if sys.platform == "win32":
        return ()
    return (Path("/Users/Shared/Epic Games"),
            Path("/Applications/Epic Games"),
            Path("/Applications"))


def vision_review_commands() -> tuple[str, ...]:
    """Accepted spellings of the installed read-only visual-review helper."""
    if sys.platform == "win32":
        env_path = r"$env:LOCALAPPDATA\UnrealAgent\vision_review.ps1"
        concrete = str(vision_review_script())
        commands = {
            f'& "{env_path}"',
            f'& "{env_path.replace(chr(92), chr(92) * 2)}"',
            f'& "{concrete}"',
            f'& "{concrete.replace(chr(92), chr(92) * 2)}"',
            concrete,
            concrete.replace(chr(92), chr(92) * 2),
        }
        return tuple(sorted(commands))
    concrete = str(vision_review_script())
    return tuple(sorted({f'"{concrete}"', concrete}))