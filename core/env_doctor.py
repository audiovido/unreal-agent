"""env_doctor.py — structured environment diagnostics (Lane B, Part 3).

Every check returns PASS / WARNING / FAIL with a short detail line.  The
run() result carries both a concise user-facing error and the full
developer diagnostic — no traceback as normal UX.  Everything is offline
safe: ports are probed with short connect timeouts and the live editor is
never launched or mutated.
"""
from __future__ import annotations

import platform
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import app_config

CORE_DEPS = ("fastapi", "uvicorn", "PIL", "numpy", "pydantic")
PASS = "PASS"
WARN = "WARNING"
FAIL = "FAIL"

_GROUP_BY = {PASS: 0, WARN: 1, FAIL: 2}


def _mk(name: str, status: str, detail: str) -> Dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def _port_free(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return False  # something answered -> in use
    except OSError:
        return True
    except Exception:
        return True


def _http_ok(url: str, timeout: float = 0.8) -> Tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python() -> List[Dict[str, Any]]:
    ver = platform.python_version()
    try:
        major, minor = (int(x) for x in ver.split(".")[:2])
    except ValueError:
        return [_mk("python_runtime", FAIL, f"unparseable version {ver}")]
    ok = (major, minor) >= (3, 9)
    return [_mk("python_runtime", PASS if ok else FAIL,
                f"Python {ver} ({'ok' if ok else 'needs >= 3.9'})")]


def check_dependencies() -> List[Dict[str, Any]]:
    out = []
    missing = []
    for name in CORE_DEPS:
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "present")
        except Exception:
            missing.append(name)
            continue
        out.append(_mk(f"dep_{name}", PASS, f"{name} {ver}"))
    if missing:
        out.insert(0, _mk("dependencies", FAIL,
                          "missing: " + ", ".join(missing)))
    return out


def check_product_deps() -> List[Dict[str, Any]]:
    """Product‑specific dependency checks: Unreal, Blender, Ollama.

    These are informational (WARN) unless a mission requires them; they
    do not become FAIL on their own to keep the doctor lightweight."""
    out: List[Dict[str, Any]] = []
    # Unreal
    unreal_builds = app_config.detect_unreal_builds()
    usable = [b for b in unreal_builds if b.get("editor_exe")]
    if usable:
        out.append(_mk("unreal_installed", PASS,
                       f"{len(usable)} build(s): {usable[0]['label']}"))
    elif unreal_builds:
        out.append(_mk("unreal_installed", WARN,
                       "launcher builds found but no editor exe resolved"))
    else:
        out.append(_mk("unreal_installed", WARN,
                       "no Epic build registry found (usable when an editor "
                       "is already open on the bridge)"))
    # Blender
    try:
        from blender_agent.config import discover_blender
        blender_exe = discover_blender()
        if blender_exe is None:
            out.append(_mk("blender", WARN, "Blender executable not found"))
        else:
            out.append(_mk("blender", PASS, f"found at {blender_exe}"))
    except Exception as exc:
        out.append(_mk("blender", WARN, f"probe failed: {exc}"))
    # Ollama / local models
    try:
        from core.vision_provider import ollama_models
        models = ollama_models()
        if models:
            out.append(_mk("ollama_local", PASS, f"{len(models)} local model(s) available"))
        else:
            out.append(_mk("ollama_local", WARN, "Ollama not reachable"))
    except Exception as exc:
        out.append(_mk("ollama_local", WARN, f"Ollama probe error: {exc}"))
    return out


def check_dirs_and_space() -> List[Dict[str, Any]]:
    out = []
    for label, p in (("config_dir", app_config.CONFIG_DIR),
                     ("log_dir", app_config.LOG_DIR),
                     ("proof_dir", app_config.PROOF_DIR),
                     ("runtime_dir", app_config.RUNTIME_DIR)):
        ok = p.exists() or True  # dirs are created lazily; writability is the test
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".ua_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            out.append(_mk(f"dir_{label}", PASS, str(p)))
        except Exception as exc:
            out.append(_mk(f"dir_{label}", FAIL if ok else WARN,
                           f"{p}: {type(exc).__name__}: {exc}"))
    free = app_config.disk_free_bytes()
    status = PASS if free < 0 or free > app_config._MIN_FREE_BYTES else WARN
    out.append(_mk("disk_free", status,
                   f"{free / 1e9:.1f} GiB free (min 1.0 GiB)"))
    return out


def check_ports(cfg: app_config.ProductConfig) -> List[Dict[str, Any]]:
    """Configured ports: WARN when something already listens (may be the
    intended running backend), never a hard FAIL on its own — the backend
    readiness check decides."""
    probes = (("backend", cfg.backend_host, cfg.backend_port),
              ("bridge", cfg.bridge_host, cfg.bridge_port),
              ("dev_api", "127.0.0.1", cfg.dev_api_port))
    out = []
    for label, host, port in probes:
        if _port_free(host, port):
            out.append(_mk(f"port_{label}", PASS,
                           f"{host}:{port} free"))
        else:
            out.append(_mk(f"port_{label}", WARN,
                           f"{host}:{port} already in use (running backend?)"))
    return out


def check_backend(cfg: app_config.ProductConfig) -> List[Dict[str, Any]]:
    ok, detail = _http_ok(cfg.backend_url + "/api/ua/status")
    return [_mk("backend_ready", PASS if ok else WARN,
                f"{cfg.backend_url} {'ready' if ok else 'not answering (' + detail + ')'}")]


def check_unreal(cfg: app_config.ProductConfig) -> List[Dict[str, Any]]:
    out = []
    builds = app_config.detect_unreal_builds()
    usable = [b for b in builds if b.get("editor_exe")]
    if usable:
        out.append(_mk("unreal_installed", PASS,
                       f"{len(usable)} build(s): {usable[0]['label']}"))
    elif builds:
        out.append(_mk("unreal_installed", WARN,
                       "launcher builds found but no editor exe resolved"))
    else:
        out.append(_mk("unreal_installed", WARN,
                       "no Epic build registry found (usable when an editor "
                       "is already open on the bridge)"))
    # project validity
    proj = app_config.validate_uproject(cfg.recent_project)
    if cfg.recent_project:
        out.append(_mk("uproject", PASS if proj["ok"] else FAIL,
                       proj.get("path") or proj.get("error", "invalid")))
    else:
        out.append(_mk("uproject", WARN,
                       "no recent project configured (choose one at run time)"))
    # plugin availability
    out.append(_mk("plugin", PASS,
                   "product mode requires no manual plugin install "
                   "(bridge runs inside the editor)"))
    return out


def check_config(cfg: app_config.ProductConfig) -> List[Dict[str, Any]]:
    problems = []
    if not (cfg.backend_port and 0 < cfg.backend_port < 65536):
        problems.append(f"backend_port={cfg.backend_port!r}")
    if not (cfg.bridge_port and 0 < cfg.bridge_port < 65536):
        problems.append(f"bridge_port={cfg.bridge_port!r}")
    if problems:
        return [_mk("config", FAIL, "invalid: " + ", ".join(problems))]
    return [_mk("config", PASS, f"backend {cfg.backend_url}, "
               f"bridge {cfg.bridge_host}:{cfg.bridge_port}")]


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def run(probe_backend: bool = True,
        probe_ports: bool = True) -> Dict[str, Any]:
    """Full doctor pass.  Everything here is read-only w.r.t. the editor."""
    cfg = app_config.load_config()
    checks: List[Dict[str, Any]] = []
    checks += check_python()
    checks += check_dependencies()
    checks += check_product_deps()
    checks += check_config(cfg)
    checks += check_dirs_and_space()
    if probe_ports:
        checks += check_ports(cfg)
    if probe_backend:
        checks += check_backend(cfg)
    checks += check_unreal(cfg)

    statuses = {PASS: 0, WARN: 0, FAIL: 0}
    for c in checks:
        statuses[c["status"]] += 1

    failures = [c for c in checks if c["status"] == FAIL]
    warnings = [c for c in checks if c["status"] == WARN]

    if failures:
        user_error = ("Environment check failed: "
                      + "; ".join(f"{c['name']}: {c['detail']}" for c in failures))
        overall = FAIL
    elif warnings:
        overall = WARN
        user_error = ("Environment check passed with warnings: "
                      + "; ".join(c["name"] for c in warnings))
    else:
        overall = PASS
        user_error = "Environment check passed."

    return {
        "overall": overall,
        "summary": f"{statuses[PASS]} pass, {statuses[WARN]} warning, "
                   f"{statuses[FAIL]} fail",
        "user_error": user_error,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "config": cfg.to_dict(),
        "checked_at": round(time.time(), 3),
    }


def developer_diagnostic(report: Dict[str, Any]) -> str:
    """Multi-line developer diagnostic for logs/console (never the default
    user surface)."""
    lines = [f"[env-doctor] overall={report['overall']} "
             f"({report['summary']})"]
    for c in report["checks"]:
        lines.append(f"  [{c['status']:7s}] {c['name']}: {c['detail']}")
    return "\n".join(lines)
