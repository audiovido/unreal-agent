"""app_config.py — product-safe configuration foundation (Lane B).

Smallest deterministic configuration model for the Unreal Agent product
shell.  Normal users never edit JSON/.env by hand: every value has a sane
default, an optional overlay file (written only through the programmatic
API), and an environment override (UA_*).  Reads the pre-existing
`config/settings.json` (dev-console era) for any keys it defines, so one
source of truth keeps working.

Frozen-file rule (Lane B): this module only READS `config/product.json`
/ `config/product_state.json` / `config/settings.json` — it never writes
them and never edits the Step-8 product modules.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Paths & defaults (single source for packaging + doctor + lifecycle)
# ---------------------------------------------------------------------------

CONFIG_DIR = ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"          # dev-console settings (read)
PREF_FILE = CONFIG_DIR / "product_prefs.json"         # product overlay (API-managed)
PRODUCT_STATE_FILE = CONFIG_DIR / "product_state.json"  # Step-8 state (read-only)
PRODUCT_CONFIG_FILE = CONFIG_DIR / "product.json"       # Step-8 known projects (read)
LOG_DIR = ROOT / "config" / "logs"                      # gitignored via logs/ rule
RUNTIME_DIR = CONFIG_DIR / "runtime"                    # pid files, leases
LEASE_DIR = CONFIG_DIR / "leases"
FIRST_RUN_FILE = CONFIG_DIR / "first_run.json"
PROOF_DIR = ROOT / "assetlib" / "proof" / "product"
UI_DIR = ROOT / "ui"

VERSION = "0.1.0"
PRODUCT_NAME = "Unreal Agent"

# Well-known service endpoints (product backend, dev console, editor bridge).
BACKEND_HOST_DEFAULT = "127.0.0.1"
BACKEND_PORT_DEFAULT = 8799
DEV_API_PORT_DEFAULT = 8765
BRIDGE_HOST_DEFAULT = "127.0.0.1"
BRIDGE_PORT_DEFAULT = 6766

_MIN_FREE_BYTES = 1_000_000_000  # warn below 1 GiB free


@dataclass
class ProductConfig:
    """Resolved product configuration.  Frozen after load; mutate through
    `set_pref` only for overlay-managed keys."""

    backend_host: str = BACKEND_HOST_DEFAULT
    backend_port: int = BACKEND_PORT_DEFAULT
    dev_api_port: int = DEV_API_PORT_DEFAULT
    bridge_host: str = BRIDGE_HOST_DEFAULT
    bridge_port: int = BRIDGE_PORT_DEFAULT
    developer_mode: bool = False
    recent_project: Optional[str] = None
    unreal_editor_exe: Optional[str] = None
    backend_url: str = ""
    prefs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend_host": self.backend_host,
            "backend_port": self.backend_port,
            "dev_api_port": self.dev_api_port,
            "bridge_host": self.bridge_host,
            "bridge_port": self.bridge_port,
            "developer_mode": bool(self.developer_mode),
            "recent_project": self.recent_project,
            "unreal_editor_exe": self.unreal_editor_exe,
            "backend_url": self.backend_url,
        }


def _read_json_any(path: Path) -> Dict[str, Any]:
    """BOM-tolerant JSON read (config/settings.json is saved as utf-8-sig)."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def _env(name: str) -> Optional[str]:
    val = os.environ.get(f"UA_{name}", None)
    if val is None or val == "":
        return None
    return val


def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def load_config(overlay: Optional[Path] = None) -> ProductConfig:
    """Resolve product config: defaults <- prefs overlay <- UA_* env vars."""
    settings = _read_json_any(SETTINGS_FILE)
    prefs_path = overlay or PREF_FILE
    prefs = _read_json_any(prefs_path)

    def pick(key: str, env: str, default: Any, section: str = "") -> Any:
        e = _env(env)
        if e is not None:
            return e
        for src in (prefs, settings):
            if section:
                got = (src.get(section) or {}).get(key)
            else:
                got = src.get(key)
            if got is not None:
                return got
        return default

    backend_port = _env_int("BACKEND_PORT", int(pick("backend_port", "PORT",
                                                     BACKEND_PORT_DEFAULT)))
    bridge_port = _env_int("BRIDGE_PORT", int(pick("bridge_port", "",
                                                   BRIDGE_PORT_DEFAULT)))
    dev_port = _env_int("DEV_API_PORT", int(pick("dev_api_port", "",
                                                 DEV_API_PORT_DEFAULT)))
    host = str(pick("backend_host", "HOST", BACKEND_HOST_DEFAULT))
    cfg = ProductConfig(
        backend_host=host,
        backend_port=backend_port,
        dev_api_port=dev_port,
        bridge_host=str(pick("bridge_host", "", BRIDGE_HOST_DEFAULT)),
        bridge_port=bridge_port,
        developer_mode=_env("DEVELOPER_MODE") in ("1", "true", "yes") or
        bool(pick("developer_mode", "", False)),
        recent_project=_env("RECENT_PROJECT") or
        (prefs.get("recent_project") or None),
        unreal_editor_exe=_env("UNREAL_EDITOR") or
        (prefs.get("unreal_editor_exe") or
         (settings.get("unreal") or {}).get("editor_exe") or None),
        prefs=dict(prefs),
    )
    cfg.backend_url = f"http://{cfg.backend_host}:{cfg.backend_port}"
    return cfg


def set_pref(key: str, value: Any,
             overlay: Optional[Path] = None) -> Dict[str, Any]:
    """Persist one product preference through the API (not hand-edited).

    Keys live under a fixed allow-list so a typo cannot silently create an
    unknown setting.  Returns the merged prefs dict.
    """
    allowed = {"backend_host", "backend_port", "dev_api_port", "bridge_port",
               "developer_mode", "recent_project", "unreal_editor_exe"}
    if key not in allowed:
        raise ValueError(f"unknown product preference: {key!r}")
    path = overlay or PREF_FILE
    prefs = _read_json_any(path)
    prefs[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # pragmatic: config write must never crash boot
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "prefs": prefs}
    return {"ok": True, "prefs": prefs}


# ---------------------------------------------------------------------------
# Unreal installation discovery (read-only registry scan; never launches)
# ---------------------------------------------------------------------------

def detect_unreal_builds() -> List[Dict[str, Any]]:
    """Discover installed Unreal Editor builds without starting anything.

    Windows: reads the Epic Games launcher registry key
    ``HKLM:\\SOFTWARE\\EpicGames\\Unreal Engine\\Builds``.  Everywhere else
    (or when the key is absent) returns [] and the doctor reports it as a
    WARNING rather than a hard FAIL.
    """
    builds: List[Dict[str, Any]] = []
    if sys.platform != "win32":
        return builds
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\EpicGames\Unreal Engine\Builds")
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            exe = Path(str(value)) / "Engine" / "Binaries" / "Win64" / \
                "UnrealEditor.exe"
            builds.append({"label": name, "path": str(value),
                           "editor_exe": str(exe) if exe.exists() else None})
        winreg.CloseKey(key)
    except OSError:
        return []
    return builds


def unreal_editor_candidates(config: Optional[ProductConfig] = None) -> List[str]:
    """Ordered candidates for a usable Unreal Editor executable."""
    cfg = config or load_config()
    candidates: List[str] = []
    if cfg.unreal_editor_exe:
        candidates.append(cfg.unreal_editor_exe)
    for b in detect_unreal_builds():
        if b.get("editor_exe"):
            candidates.append(b["editor_exe"])
    return candidates


def validate_uproject(path: Optional[str]) -> Dict[str, Any]:
    """Validate a .uproject path (existence + minimal parse)."""
    if not path:
        return {"ok": False, "error": "no project path configured"}
    p = Path(str(path))
    if not p.exists():
        return {"ok": False, "error": f"project file not found: {p}"}
    if p.suffix.lower() != ".uproject":
        return {"ok": False, "error": f"not a .uproject file: {p.name}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"unparseable .uproject: {exc}"}
    return {"ok": True, "path": str(p.resolve()),
            "name": data.get("FileVersion", "unknown"),
            "engine_association": data.get("EngineAssociation")}


def disk_free_bytes(path: Optional[Path] = None) -> int:
    try:
        return shutil.disk_usage(path or ROOT).free
    except Exception:
        return -1
