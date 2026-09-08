"""Canonical filesystem and runtime paths for an installed Aivido package."""
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


def python_executable() -> Path:
    """Resolve the interpreter without requiring a development checkout."""
    override = os.environ.get("AIVIDO_PYTHON", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local = PACKAGE_ROOT / ".venv" / "Scripts" / "python.exe"
    return local if local.is_file() else Path(sys.executable).resolve()


def local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA", "").strip()
    return Path(value).expanduser().resolve() if value else RUNTIME_DIR


def vision_review_script() -> Path:
    return local_app_data() / "UnrealAgent" / "vision_review.ps1"


def unreal_editor_executable() -> Path | None:
    """Resolve Unreal from an override or the Epic Launcher registry."""
    override = os.environ.get("UNREAL_AGENT_ENGINE_DIR", "").strip()
    if override:
        return (Path(override).expanduser().resolve() / "Engine" /
                "Binaries" / "Win64" / "UnrealEditor.exe")
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
                candidate = (Path(str(value)) / "Engine" / "Binaries" /
                             "Win64" / "UnrealEditor.exe")
                if candidate.is_file():
                    winreg.CloseKey(key)
                    return candidate.resolve()
            winreg.CloseKey(key)
        except OSError:
            pass
    return None


def vision_review_commands() -> tuple[str, ...]:
    """Accepted spellings of the installed read-only visual-review helper."""
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
