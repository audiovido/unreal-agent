"""doctor.py — UNREAL CODER setup doctor (Phase D).

`unreal-coder doctor`: one canonical setup path. Runs structured PASS/WARN/FAIL
checks over every system the product needs and returns a machine-readable
report plus a human summary.

Rules:
- OPTIONAL systems (Blender, local models, remote models) WARN when missing,
  never FAIL, unless the requested mission requires them.
- REQUIRED systems (Python deps, config file, writable dirs, bridge when an
  editor session is expected) FAIL when broken.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

PYTHON_REQUIREMENTS = [
    ("fastapi", "API server"),
    ("pydantic", "request validation"),
    ("PIL", "image analysis (Pillow)"),
    ("requests", "model/HTTP clients"),
    ("uvicorn", "server runtime"),
]

CONFIG_FILE = ROOT / "config" / "settings.json"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766


def _check(name: str, status: str, detail: str,
           hint: str = "", required: bool = True,
           data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if status == WARN and required:
        status = FAIL
    return {"name": name, "status": status, "detail": detail,
            "hint": hint, "required": required, "data": data or {}}


def check_python() -> List[Dict[str, Any]]:
    results = []
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    results.append(_check(
        "python_version",
        PASS if sys.version_info >= (3, 9) else FAIL,
        f"Python {py} at {sys.executable}",
        hint="Python 3.9+ required",
    ))
    for module, purpose in PYTHON_REQUIREMENTS:
        try:
            importlib.import_module(module)
            results.append(_check(
                f"python:{module}", PASS, f"importable ({purpose})"))
        except Exception as exc:
            results.append(_check(
                f"python:{module}", FAIL,
                f"missing ({purpose}): {exc}",
                hint=f"install with: pip install {module}"))
    return results


def check_config() -> List[Dict[str, Any]]:
    results = []
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            results.append(_check(
                "config_file", PASS, f"{CONFIG_FILE} parsed",
                data={"keys": sorted(cfg)[:12]}))
            engine = cfg.get("unreal_engine")
            if engine and Path(engine).is_dir():
                results.append(_check(
                    "unreal_engine_path", PASS, f"engine root exists: {engine}"))
            else:
                results.append(_check(
                    "unreal_engine_path", WARN,
                    f"engine root not found: {engine}",
                    hint="set unreal_engine in config/settings.json or "
                         "UNREAL_AGENT_ENGINE_DIR"))
        except Exception as exc:
            results.append(_check(
                "config_file", FAIL, f"unparseable: {exc}",
                hint="fix config/settings.json JSON syntax"))
    else:
        results.append(_check(
            "config_file", FAIL, f"missing: {CONFIG_FILE}",
            hint="create config/settings.json (see docs/unreal_coder.md)"))
    # Secrets hygiene: secrets may exist in env but must never be in the file.
    from core.config import SECRET_ENV_NAMES, is_secret_key
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            leaked = [k for k in cfg if is_secret_key(k)]
            results.append(_check(
                "secrets_not_in_config_file", PASS if not leaked else FAIL,
                "no secrets in config file" if not leaked
                else f"secret-looking keys committed: {leaked}",
                hint="move secrets to environment variables"))
        except Exception:
            pass
    return results


def check_unreal() -> List[Dict[str, Any]]:
    """Unreal editor exe + live bridge. Editor exe missing = FAIL (required);
    bridge down = WARN because headless/inspection work still functions."""
    results = []
    exe = None
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        engine = Path(cfg.get("unreal_engine") or "")
        candidate = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        if candidate.is_file():
            exe = candidate
    except Exception:
        pass
    results.append(_check(
        "unreal_editor_exe",
        PASS if exe else FAIL,
        str(exe) if exe else "UnrealEditor.exe not found under configured engine",
        hint="set unreal_engine in config/settings.json"))

    bridge = _probe_bridge()
    if bridge.get("ok"):
        results.append(_check(
            "bridge_live", PASS,
            f"editor online: {bridge.get('project_name')} "
            f"({bridge.get('engine')})",
            data=bridge))
    else:
        results.append(_check(
            "bridge_live", WARN,
            "no live editor on 127.0.0.1:%d (%s)" % (
                BRIDGE_PORT, bridge.get("error", "unreachable")),
            hint="open an Unreal project with the UnrealAgent bridge plugin; "
                 "required only for live missions",
            required=False))
    return results


def _probe_bridge() -> Dict[str, Any]:
    try:
        from tools.unreal.unreal_bridge import UnrealBridge
        bridge = UnrealBridge(host=BRIDGE_HOST, port=BRIDGE_PORT, timeout=4)
        identity = bridge.get_identity()
        if identity.get("ok"):
            return {
                "ok": True,
                "project_name": identity.get("project_name"),
                "project_path": identity.get("project_path"),
                "engine": identity.get("engine"),
                "world": identity.get("world"),
                "port": identity.get("port", BRIDGE_PORT),
            }
        return {"ok": False, "error": str(identity.get("error") or "no identity")}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_blender() -> List[Dict[str, Any]]:
    results = []
    try:
        from blender_agent.config import discover_blender
        exe = discover_blender()
        if exe is None:
            results.append(_check(
                "blender", WARN, "Blender executable not found",
                hint="optional: set UNREAL_AGENT_BLENDER_EXE or install "
                     "Blender; required only for DCC repair missions",
                required=False))
        else:
            results.append(_check(
                "blender", PASS, f"found at {exe}"))
    except Exception as exc:
        results.append(_check(
            "blender", WARN, f"probe failed: {exc}", required=False))
    return results


def check_models() -> List[Dict[str, Any]]:
    results = []
    from core.vision_provider import ollama_models
    models = ollama_models()
    if models:
        results.append(_check(
            "local_models", PASS, f"{len(models)} local model(s) available",
            data={"models": models[:8]}))
        vision = [m for m in models
                  if "vl" in m.lower() or "vision" in m.lower()
                  or "llava" in m.lower()]
        results.append(_check(
            "vision_model", PASS if vision else WARN,
            f"vision-capable model: {vision[0]}" if vision
            else "no vision-capable local model (visual review falls back to "
                 "deterministic measurement)",
            hint="optional: pull a vision model (e.g. qwen3-vl) for model-"
                 "based visual review",
            required=False))
    else:
        results.append(_check(
            "local_models", WARN,
            "Ollama not reachable at the configured URL",
            hint="optional: start Ollama for model-based planning/review; "
                 "deterministic visual validation still works without it",
            required=False))
    if os.getenv("UNREAL_AGENT_REMOTE_VISION_URL") and \
            os.getenv("UNREAL_AGENT_REMOTE_API_KEY"):
        results.append(_check(
            "remote_vision", PASS, "remote vision provider configured "
            "(key present, never logged)"))
    else:
        results.append(_check(
            "remote_vision", PASS,
            "remote vision not configured (optional; local provider is the "
            "default path)", required=False))
    return results


def check_ports_and_dirs() -> List[Dict[str, Any]]:
    results = []
    import socket
    # The bridge port being OPEN is good (editor listening); report either way.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        open_ = sock.connect_ex((BRIDGE_HOST, BRIDGE_PORT)) == 0
    finally:
        sock.close()
    results.append(_check(
        "bridge_port", PASS,
        f"{BRIDGE_HOST}:{BRIDGE_PORT} {'listening (editor online)' if open_ else 'free (no editor)'}"))
    writable = [
        ROOT / "memory" / "checkpoints" / "unreal_coder",
        ROOT / "memory",
        ROOT / "config",
    ]
    for path in writable:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".doctor_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            results.append(_check(
                f"writable:{path.name}", PASS, f"{path} writable"))
        except Exception as exc:
            results.append(_check(
                f"writable:{path.name}", FAIL, f"{path} not writable: {exc}",
                hint="fix directory permissions"))
    return results


def check_api_boot() -> List[Dict[str, Any]]:
    results = []
    try:
        from app import api  # noqa: F401  (imports = boots the composition)
        results.append(_check(
            "api_boot", PASS, "FastAPI app imports and composes cleanly"))
    except Exception as exc:
        results.append(_check(
            "api_boot", FAIL, f"composition failed: {type(exc).__name__}: {exc}",
            hint="run the test suite for a detailed trace"))
    return results


def run_doctor(requirements: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run all checks. `requirements` may name optional systems that the
    intended mission REQUIRES (e.g. ['blender']) — those then fail hard."""
    requirements = [r.lower() for r in (requirements or [])]
    checks: List[Dict[str, Any]] = []
    checks.extend(check_python())
    checks.extend(check_config())
    checks.extend(check_unreal())
    checks.extend(check_blender())
    checks.extend(check_models())
    checks.extend(check_ports_and_dirs())
    checks.extend(check_api_boot())
    # Optional-but-requested systems upgrade WARN -> FAIL.
    for check in checks:
        if check["status"] == WARN and check["name"].split(":")[0] in requirements:
            check["status"] = FAIL
            check["detail"] += " (required by requested mission)"
    summary = {s: sum(1 for c in checks if c["status"] == s)
               for s in (PASS, WARN, FAIL)}
    overall = PASS if summary[FAIL] == 0 else (
        "DEGRADED" if summary[FAIL] <= 2 and summary[PASS] > summary[FAIL]
        else FAIL)
    if overall == "DEGRADED" and not requirements:
        overall = "DEGRADED"
    return {
        "doctor": "unreal-coder doctor",
        "overall": overall,
        "summary": summary,
        "checks": checks,
        "generated_at": time.time(),
    }


def human_summary(report: Dict[str, Any]) -> str:
    lines = [
        f"unreal-coder doctor — {report['overall']}",
        f"  PASS {report['summary'].get(PASS, 0)}   "
        f"WARN {report['summary'].get(WARN, 0)}   "
        f"FAIL {report['summary'].get(FAIL, 0)}",
    ]
    for check in report["checks"]:
        if check["status"] != PASS:
            lines.append(
                f"  [{check['status']}] {check['name']}: {check['detail']}"
                + (f" — {check['hint']}" if check["hint"] else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_doctor(requirements=sys.argv[1:])
    print(human_summary(report))
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report["overall"] in (PASS, "DEGRADED") else 1)
