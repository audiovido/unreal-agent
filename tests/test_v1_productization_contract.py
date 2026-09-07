"""V1 productization release acceptance harness (QA lane).

Validates the 25 release contracts for the upcoming aivido/v1-productization
branch, against the RC1.1 clean-install baseline (aivido/rc1.1-clean-install-
fixes @ 736042d).  This file lives on the TEST/QA lane only: it must never
mutate production implementation, never touch Unreal, and never bind the
live ports 6766 / 8765 / 8844.

Contract map (V1C-01 .. V1C-25)
-------------------------------
V1C-01  clean clone dependency closure        (static import-closure scan)
V1C-02  fresh venv install requirements.txt   (opt-in: AIVIDO_QA_FRESH_VENV=1)
V1C-03  all required runtime imports          (import contract + composition root)
V1C-04  installer idempotency                 (pip re-resolve is a no-op)
V1C-05  second install does not corrupt       (package rebuild determinism)
V1C-06  duplicate backend start protection    (service_lifecycle refuses 2nd)
V1C-07  start -> health PASS                  (real readiness probe)
V1C-08  launcher exits -> backend stays alive (real product_launcher smoke)
V1C-09  stop -> backend actually stops        (real product_launcher smoke)
V1C-10  restart -> backend healthy again      (real product_launcher smoke)
V1C-11  stale PID recovery                    (dead pid file self-heals)
V1C-12  occupied-port truthful failure        (refuses + names the port)
V1C-13  UI /app HTTP 200                      (dev console page served)
V1C-14  backend /api/status PASS              (truthful, editor-offline safe)
V1C-15  Unreal-session API schema             (/api/unreal-coder OpenAPI)
V1C-16  Tailscale unavailable -> local PASS   (loopback-only mode works)
V1C-17  no silent public exposure             (loopback defaults everywhere)
V1C-18  secrets absent from package           (built dist scanned)
V1C-19  temp/cache/worktree junk absent dist  (built dist scanned)
V1C-20  installer failure -> useful logs      (err log carries the traceback)
V1C-21  no fake PASS when process dies        (status flips, mission stays FAIL)
V1C-22  package Quickstart <= 3 user actions  (README contract)
V1C-23  RC1.1 truthfulness regressions kept   (0-step FAIL guard)
V1C-24  capture_unreal_viewport regression    (planner emits read-only EVIDENCE)
V1C-25  REQUESTED_TOOL_MISSING preserved      (impossible work fails up front)

Safety model
------------
- Hermetic by default: temp dirs, ephemeral ports, FastAPI TestClient.
- The launcher lifecycle smoke (V1C-08/09/10) runs the REAL product backend
  (app.product_app) on an EPHEMERAL port only — never 6766/8765/8844.
- V1C-02 needs network + pip and is opt-in via AIVIDO_QA_FRESH_VENV=1.
- The pytest conftest blocks all live Unreal bridge I/O by default.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# -----------------------------------------------------------------------
# shared helpers
# -----------------------------------------------------------------------

STDLIB = getattr(sys, "stdlib_module_names", frozenset())
LOCAL_PKGS = {
    "app", "core", "tools", "assetlib", "scripts", "supervisor", "ui",
    "blender_agent", "tests", "config", "memory", "vendor", "dist",
    "workspace", "uiux_phase1", "uiux_phase2", "ui_validation",
}
RUNTIME_SCAN_DIRS = ("app", "core", os.path.join("tools", "unreal"),
                     os.path.join("tools", "visual"))
RUNTIME_SCAN_FILES = ("run_agent.py", "scripts/product_launcher.py",
                      "scripts/build_product_package.py")

# Third-party modules the runtime imports lazily (function-level) and treats
# as optional features.  They must stay out of module scope so a clean
# requirements.txt install still boots the backend (V1C-01 enforces this).
LAZY_OPTIONAL_THIRD_PARTY = {"mcp", "starlette", "psutil", "httpx2",
                             "sse_starlette"}

REQ_CONTRACT = ("fastapi", "uvicorn", "pillow", "numpy", "pydantic",
                "requests", "rich")
REQ_IMPORT_NAMES = {"fastapi": "fastapi", "uvicorn": "uvicorn",
                    "pillow": "PIL", "numpy": "numpy", "pydantic": "pydantic",
                    "requests": "requests", "rich": "rich"}

SERVICE_NAME = "unreal-agent-product"
HEALTH_PATH = "/api/ua/status"

FORBIDDEN_PACKAGE_FILES = (
    "*.key", "*.pem", "*.pfx", "*.p12", ".env", ".env.*", "*secret*",
    "*credential*", "*apikey*", "*api_key*", "*password*", "*token*",
)
SECRET_CONTENT_PATTERNS = (
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "avmcp_",                      # generated MCP gateway API keys
    "AKIA",                        # AWS access key ids
    "sk-",                         # OpenAI-style keys (heuristic, word-anchored below)
)
SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password)\b[\"']?\s*[:=]\s*[\"']"
    r"[A-Za-z0-9_\-]{16,}[\"']")

JUNK_DIR_PARTS = {"__pycache__", ".pytest_cache", ".tmp-browser", ".freebuff",
                  ".venv", "node_modules", ".git", "microsoft", ".ds_store"}
JUNK_DIR_PREFIXES = ("backup",)  # backup-YYYYMMDD-* timestamped worktree dirs
JUNK_FILE_RE = re.compile(
    r"(?i)(^|/)([^/]*\.pyc|[^/]*\.pyo|[^/]*\.log|[^/]*\.pid|[^/]*\.tmp|"
    r"[^/]*\.bak|[^/]*\.orig|[^/]*\.err|[^/]*\.swp|\.DS_Store|Thumbs\.db|"
    r"desktop\.ini|[^/]*\.broken-[^/]*|[^/]*\.zip)$")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_status(url: str, timeout: float = 2.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return int(r.status)
    except Exception as exc:
        return getattr(exc, "code", 0) or -1


def _requirements_file() -> Path:
    return ROOT / "requirements.txt"


# -----------------------------------------------------------------------
# V1C-01 — clean clone dependency closure (static)
# -----------------------------------------------------------------------

def _module_level_third_party_imports() -> dict:
    """Map third-party top-level import -> runtime files importing it at
    module scope (function-level lazy imports are excluded on purpose)."""
    found: dict = {}
    targets = [ROOT / d for d in RUNTIME_SCAN_DIRS]
    targets += [ROOT / f for f in RUNTIME_SCAN_FILES]
    for base in targets:
        if base.is_file():
            py_files = [base]
        else:
            py_files = sorted(base.rglob("*.py"))
        for p in py_files:
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            if ".venv" in rel or "backup" in rel:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8",
                                             errors="replace"))
            except SyntaxError:
                continue
            module_level = set()
            for node in tree.body:  # module scope only
                if isinstance(node, ast.Import):
                    for a in node.names:
                        module_level.add(a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0:
                        module_level.add(node.module.split(".")[0])
            for m in module_level:
                if m in STDLIB or m in LOCAL_PKGS or m == "__future__":
                    continue
                found.setdefault(m, []).append(rel)
    return found


def test_v1c01_dependency_closure_static():
    """Every module-level third-party import in the runtime tree must be
    satisfied by requirements.txt (single dependency contract)."""
    text = _requirements_file().read_text(encoding="utf-8")
    provided = {line.strip().lower() for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")}
    # pillow is imported as PIL
    provided.add("pil")

    found = _module_level_third_party_imports()
    missing = {m: files for m, files in found.items()
               if m.lower() not in provided}
    assert not missing, (
        "clean-clone dependency closure broken; module-level third-party "
        f"imports missing from requirements.txt: {missing}")
    for pkg in REQ_CONTRACT:
        assert pkg in text.lower(), f"requirements.txt missing {pkg}"


def test_v1c01_lazy_optional_imports_stay_lazy():
    """Optionally-imported third-party features (MCP gateway SDK, psutil,
    ...) must never leak into module scope of runtime files, or clean
    installs crash on boot."""
    found = _module_level_third_party_imports()
    leaks = {m: files for m, files in found.items()
             if m in LAZY_OPTIONAL_THIRD_PARTY}
    assert not leaks, (
        f"optional dependencies imported at module scope (breaks clean "
        f"clone boot): {leaks}")


# -----------------------------------------------------------------------
# V1C-02 — fresh venv install (opt-in; needs network + pip)
# -----------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("AIVIDO_QA_FRESH_VENV") != "1",
    reason="network install contract — opt in with AIVIDO_QA_FRESH_VENV=1")
def test_v1c02_fresh_venv_install(tmp_path):
    """Fresh venv + pip install -r requirements.txt must boot the real
    product entrypoints (selfcheck) with nothing else installed."""
    venv_dir = tmp_path / "fresh-venv"
    py = sys.executable
    r = subprocess.run([py, "-m", "venv", str(venv_dir)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    vpy = venv_dir / "Scripts" / "python.exe"
    if not vpy.exists():
        vpy = venv_dir / "bin" / "python"
    r = subprocess.run([str(vpy), "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check",
                        "-r", str(_requirements_file())],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    # the venv python, from a neutral cwd, must satisfy the runtime import
    # contract and the product selfcheck (composition root included)
    code = ("import fastapi, uvicorn, PIL, numpy, pydantic, requests, rich; "
            "print('IMPORTS_OK')")
    r = subprocess.run([str(vpy), "-c", code], capture_output=True,
                       text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0 and "IMPORTS_OK" in r.stdout, r.stderr
    r = subprocess.run([str(vpy), "product_launcher.py", "selfcheck"],
                       capture_output=True, text=True, timeout=180,
                       cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "app.product_app importable" in r.stdout


# -----------------------------------------------------------------------
# V1C-03 — all required runtime imports
# -----------------------------------------------------------------------

def test_v1c03_runtime_import_contract():
    import importlib
    for pkg, mod in REQ_IMPORT_NAMES.items():
        m = importlib.import_module(mod)
        assert m is not None, f"runtime import failed: {mod} ({pkg})"


def test_v1c03_composition_roots_importable():
    """The two backend composition roots + the launcher path + the packaged
    build script must all import offline (this is what a clean clone runs)."""
    import importlib
    import importlib.util
    for mod in ("app.served", "app.product_app", "app.mcp_gateway",
                "core.product_core", "core.service_lifecycle",
                "core.app_config"):
        importlib.import_module(mod)
    spec = importlib.util.spec_from_file_location(
        "qa_v1c03_build", ROOT / "scripts" / "build_product_package.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


# -----------------------------------------------------------------------
# V1C-04 / V1C-05 — installer idempotency + second install integrity
# -----------------------------------------------------------------------

def _pip_dry_run_report() -> dict:
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--dry-run",
         "--disable-pip-version-check", "--report", "-",
         "-r", str(_requirements_file())],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (
        "pip could not re-resolve the dependency contract offline "
        f"(rc={r.returncode}): {r.stdout}\n{r.stderr}")
    start = r.stdout.find("{")
    assert start >= 0, f"pip --report produced no JSON: {r.stdout!r}"
    return json.loads(r.stdout[start:r.stdout.rfind("}") + 1])


def test_v1c04_installer_idempotent_pip():
    """Re-running the documented install against a satisfied environment
    must be a no-op: nothing to download, nothing to reinstall."""
    report = _pip_dry_run_report()
    to_install = [i.get("metadata", {}).get("name", "?").lower()
                  for i in report.get("install", [])]
    assert to_install == [], (
        f"install contract is not idempotent; pip would install {to_install}")


def test_v1c05_second_install_does_not_corrupt(pkg_dist):
    """A second package build over the first must be deterministic: same
    file list, same bytes, no duplicated/stale artifacts."""
    pkg_dir, manifest1, files1, hashes1 = pkg_dist
    builder = _load_build_module()
    report2 = builder.build(pkg_dir.parent)
    pkg2 = Path(report2["output_dir"])
    manifest2 = json.loads((pkg2 / "manifest.json").read_text(encoding="utf-8"))
    files2 = sorted(
        str(p.relative_to(pkg2)).replace("\\", "/")
        for p in pkg2.rglob("*") if p.is_file())
    hashes2 = {f: _sha256(pkg2 / f) for f in files2
               if f not in ("version.json", "manifest.json",
                            "_build_report.json")}
    assert manifest1["files"] == manifest2["files"], \
        "package manifest drifted between identical installs"
    assert files1 == files2, "package file set changed between installs"
    assert hashes1 == hashes2, "copied file bytes changed between installs"
    dupes = [f for f in files2 if re.search(r"\(\d+\)|copy|copy2", f)]
    assert not dupes, f"second install produced duplicate artifacts: {dupes}"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _load_build_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "qa_v1_pkg_build", ROOT / "scripts" / "build_product_package.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pkg_dist(tmp_path_factory):
    """Build the product package once per module; reuse across contracts
    5 / 18 / 19 / 22."""
    spec = _load_build_module()
    out = tmp_path_factory.mktemp("qa-dist")
    report = spec.build(out)
    pkg_dir = Path(report["output_dir"])
    manifest = json.loads((pkg_dir / "manifest.json").read_text(
        encoding="utf-8"))
    files = sorted(str(p.relative_to(pkg_dir)).replace("\\", "/")
                   for p in pkg_dir.rglob("*") if p.is_file())
    hashes = {f: _sha256(pkg_dir / f) for f in files
              if f not in ("version.json", "manifest.json",
                           "_build_report.json")}
    return pkg_dir, manifest, files, hashes


# -----------------------------------------------------------------------
# V1C-06..V1C-07, V1C-11, V1C-12 — service lifecycle (hermetic, mini ASGI)
# -----------------------------------------------------------------------

MINI_APP = '''"""Tiny ASGI app for QA lifecycle contracts (no FastAPI import cost)."""
async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    body = b'{"ok": true, "service": "qa-mini"}'
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
'''


@pytest.fixture()
def mini_env(monkeypatch, tmp_path):
    """Isolated runtime/log dirs + a tmp cwd exposing the mini ASGI app."""
    from core import service_lifecycle as svc
    (tmp_path / "runtime").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "mini_app.py").write_text(MINI_APP, encoding="utf-8")
    monkeypatch.setattr(svc, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(svc.app_config, "ROOT", tmp_path)
    return tmp_path


def _start_mini(env, port, **kw):
    from core import service_lifecycle as svc
    return svc.start_service("qa-mini-svc", "127.0.0.1", port,
                             "mini_app:app", health_path="/api/ua/status",
                             ready_timeout_s=kw.pop("ready_timeout_s", 20.0),
                             **kw)


def test_v1c06_duplicate_backend_start_protected(mini_env):
    """A second start against a running backend must be refused (no second
    process, same pid, explicit duplicate signal)."""
    from core import service_lifecycle as svc
    port = _free_port()
    first = _start_mini(mini_env, port)
    assert first.get("ok") and first.get("ready"), first
    try:
        second = _start_mini(mini_env, port)
        assert second.get("duplicate") is True, second
        assert second.get("pid") == first.get("pid")
        assert svc.pid_alive(first["pid"]) is True
    finally:
        svc.stop_service("qa-mini-svc", "127.0.0.1", port, grace_s=5)


def test_v1c07_start_health_pass(mini_env):
    """start_service must return only after a REAL health probe passes."""
    port = _free_port()
    res = _start_mini(mini_env, port)
    try:
        assert res.get("ok") is True and res.get("ready") is True, res
        assert _http_status(
            f"http://127.0.0.1:{port}/api/ua/status") == 200
    finally:
        from core import service_lifecycle as svc
        svc.stop_service("qa-mini-svc", "127.0.0.1", port, grace_s=5)


def test_v1c11_stale_pid_recovery(mini_env):
    """A dead pid file must self-heal: status flags it stale and clears it;
    the next start succeeds instead of refusing."""
    from core import service_lifecycle as svc
    port = _free_port()
    svc.write_pid_file("qa-mini-stale", 2 ** 31 - 1, port=port)
    st = svc.service_status("qa-mini-stale", "127.0.0.1", port)
    assert st["state"] == "STALE" and st.get("pid_file"), st
    assert svc.read_pid_file("qa-mini-stale") is None, \
        "stale pid file was not recovered"
    res = _start_mini(mini_env, port)
    try:
        assert res.get("ok") is True and res.get("ready") is True, \
            f"start after stale-pid recovery failed: {res}"
    finally:
        svc.stop_service("qa-mini-svc", "127.0.0.1", port, grace_s=5)


def test_v1c12_occupied_port_truthful_failure(mini_env):
    """When the port is held by another process, start must fail
    truthfully, name the port, and spawn nothing."""
    import sys as _sys
    from core import service_lifecycle as svc
    port = _free_port()
    holder = subprocess.Popen(
        [_sys.executable, "-m", "http.server", str(port), "--bind",
         "127.0.0.1"], cwd=str(mini_env), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 8
        while time.time() < deadline and not svc.port_in_use("127.0.0.1", port):
            time.sleep(0.1)
        assert svc.port_in_use("127.0.0.1", port), "port holder did not start"
        res = _start_mini(mini_env, port, ready_timeout_s=3.0)
        assert res.get("ok") is False, res
        assert str(port) in str(res.get("error", "")), res
        assert svc.read_pid_file("qa-mini-svc") is None, \
            "refused start left a pid file behind"
    finally:
        holder.terminate()
        holder.wait(timeout=10)


# -----------------------------------------------------------------------
# V1C-08/09/10 — REAL launcher lifecycle smoke (ephemeral port only)
# -----------------------------------------------------------------------

def _launcher(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts" + os.sep + "product_launcher.py", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)


def test_v1c08_09_10_launcher_lifecycle_smoke():
    """Full user story on an ephemeral port: start -> healthy; the launcher
    process exits while the backend stays alive; stop kills it; restart
    brings it back healthy.  Uses app.product_app on an ephemeral port —
    never 6766/8765/8844."""
    from core import service_lifecycle as svc
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    try:
        # -- start --------------------------------------------------------
        r = _launcher("start", "--port", str(port), "--retries", "2")
        assert r.returncode == 0, (
            f"launcher start failed rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        # V1C-08: the launcher process has EXITED here; the backend must
        # still be alive and healthy on its own.
        rec = svc.read_pid_file(SERVICE_NAME)
        assert rec and svc.pid_alive(rec["pid"]), \
            f"backend died with the launcher: {rec}"
        assert _http_status(f"{base}{HEALTH_PATH}") == 200
        assert _http_status(f"{base}/api/ua/status") == 200

        # -- stop ---------------------------------------------------------
        r = _launcher("stop", "--port", str(port))
        assert r.returncode == 0, f"stop failed: {r.stdout}\n{r.stderr}"
        deadline = time.time() + 8
        while time.time() < deadline and svc.port_in_use("127.0.0.1", port):
            time.sleep(0.1)
        rec = svc.read_pid_file(SERVICE_NAME)
        assert not (rec and svc.pid_alive(rec["pid"])), \
            "backend survived stop (V1C-09)"
        assert _http_status(f"{base}{HEALTH_PATH}", timeout=1.0) != 200

        # -- restart ------------------------------------------------------
        r = _launcher("restart", "--port", str(port), "--retries", "2")
        assert r.returncode == 0, (
            f"restart failed rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        rec = svc.read_pid_file(SERVICE_NAME)
        assert rec and svc.pid_alive(rec["pid"]), "restart left no live pid"
        assert _http_status(f"{base}{HEALTH_PATH}") == 200, \
            "backend not healthy after restart (V1C-10)"
    finally:
        svc.stop_service(SERVICE_NAME, "127.0.0.1", port, grace_s=5)


# -----------------------------------------------------------------------
# V1C-13..V1C-15 — HTTP surface via TestClient (no ports opened)
# -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def dev_client():
    from fastapi.testclient import TestClient
    from app import api as dev_api
    with TestClient(dev_api.app) as c:
        yield c, dev_api


def test_v1c13_ui_app_http_200(dev_client):
    client, _ = dev_client
    r = client.get("/app")
    assert r.status_code == 200, r.status_code
    assert "text/html" in r.headers.get("content-type", "")
    assert len(r.content) > 1000, "/app served an empty page"
    # the product shell must serve its own entry too
    r2 = client.get("/")
    assert r2.status_code == 200
    assert len(r2.content) > 1000


def test_v1c14_api_status_pass(dev_client):
    client, _ = dev_client
    # conftest blocks all live bridge I/O under pytest, so the editor is
    # truthfully offline here — the endpoint must still answer PASS for the
    # backend itself while reporting the editor as not ok.
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True, data
    assert "models" in data and {"fast", "reasoning", "coder"} <= \
        set(data["models"]), data.get("models")
    # truthful editor state: the offline editor must NOT be reported as ok
    # (canonical /api/status shape reports the editor under "unreal";
    # bridge_status is the legacy alias — accept either, demand truth)
    editor = data.get("bridge_status") or data.get("unreal") or {}
    assert editor.get("ok") is False, data


def test_v1c15_unreal_session_api_schema(dev_client):
    client, _ = dev_client
    schema = client.get("/openapi.json").json()
    paths = set(schema.get("paths", {}))
    required_paths = {
        "/api/unreal-coder",
        "/api/unreal-coder/async",
        "/api/unreal-coder/session",
        "/api/unreal-coder/resume",
        "/api/unreal-coder/capabilities",
        "/api/unreal-coder/mission/{mission_id}",
    }
    missing = required_paths - paths
    assert not missing, f"unreal-coder API surface missing paths: {missing}"
    req_schema_name = schema["paths"]["/api/unreal-coder"]["post"][
        "requestBody"]["content"]["application/json"]["schema"]["$ref"
    ].split("/")[-1]
    req_schema = schema["components"]["schemas"][req_schema_name]
    assert req_schema.get("required") == ["prompt"], req_schema
    for field in ("mode", "read_only", "dry_run", "mission_id", "project"):
        assert field in req_schema.get("properties", {}), field
    # one-sentence contract: prompt-only request is schema-valid and the
    # dry-run path answers without executing
    r = client.post("/api/unreal-coder",
                    json={"prompt": "What can you do?", "dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"mission_id", "status", "verdict"} <= set(body), body.keys()
    r = client.get("/api/unreal-coder/session")
    assert r.status_code == 200
    assert set(r.json()) == {"ok"} or r.json().get("ok") in (True, False)


# -----------------------------------------------------------------------
# V1C-16 / V1C-17 — tailscale-off local mode + no silent public exposure
# -----------------------------------------------------------------------

def test_v1c16_tailscale_unavailable_local_mode_pass(monkeypatch, tmp_path):
    """With no Tailscale/public tunnel configured at all, local mode must
    still come up PASS: loopback-only defaults, doctor never FAILs."""
    from core import env_doctor, app_config
    monkeypatch.delenv("AIVIDO_MCP_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("AIVIDO_BACKEND_URL", raising=False)
    monkeypatch.setenv("AIVIDO_MCP_API_KEY", "qa-key-not-a-secret")
    from app import mcp_gateway
    monkeypatch.setattr(mcp_gateway, "PUBLIC_HOST_FILE",
                        tmp_path / "no-such-public-host")
    monkeypatch.setattr(mcp_gateway, "KEY_FILE", tmp_path / "no-such-key")
    assert not mcp_gateway.load_public_host()
    assert mcp_gateway.BACKEND_URL.startswith("http://127.0.0.1")
    # local doctor: no tailscale dependency anywhere -> never FAIL
    # (canonical doctor vocabulary: PASS / WARNING / FAIL)
    report = env_doctor.run(probe_backend=False, probe_ports=False)
    assert report["overall"] in ("PASS", "WARNING"), report["overall"]
    cfg = app_config.load_config()
    assert cfg.backend_host == "127.0.0.1"
    assert cfg.bridge_host == "127.0.0.1"


def test_v1c17_no_silent_public_exposure():
    """Every default bind must be loopback; exposing publicly must require
    an explicit operator action (flag/env), never a silent default."""
    gw_src = (ROOT / "app" / "mcp_gateway.py").read_text(encoding="utf-8")
    assert 'default="127.0.0.1"' in gw_src, \
        "MCP gateway --host default is not loopback"
    ra_src = (ROOT / "run_agent.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in ra_src and '"0.0.0.0"' not in ra_src, \
        "dev backend does not bind loopback by default"
    from core import app_config
    assert app_config.BACKEND_HOST_DEFAULT == "127.0.0.1"
    assert app_config.BRIDGE_HOST_DEFAULT == "127.0.0.1"
    # product launcher path: service_lifecycle binds the config host, which
    # defaults to loopback (asserted above); no 0.0.0.0 anywhere in defaults
    sl_src = (ROOT / "core" / "service_lifecycle.py").read_text(
        encoding="utf-8")
    assert '"0.0.0.0"' not in sl_src
    bat_src = (ROOT / "START_AGENT.bat").read_text(encoding="utf-8",
                                                   errors="replace")
    assert "8765" in bat_src and "0.0.0.0" not in bat_src


# -----------------------------------------------------------------------
# V1C-18 / V1C-19 — package hygiene (secrets + junk)
# -----------------------------------------------------------------------

def _pkg_files(pkg_dir: Path):
    return [p for p in pkg_dir.rglob("*") if p.is_file()]


def test_v1c18_no_secrets_in_package(pkg_dist):
    import fnmatch
    pkg_dir, _, _, _ = pkg_dist
    offenders = []
    for p in _pkg_files(pkg_dir):
        rel = str(p.relative_to(pkg_dir)).replace("\\", "/")
        if any(fnmatch.fnmatch(p.name.lower(), pat)
               for pat in FORBIDDEN_PACKAGE_FILES):
            offenders.append(("filename", rel))
            continue
        if p.suffix.lower() in (".py", ".json", ".txt", ".html", ".js",
                                ".css", ".md", ".bat", ".cfg", ".toml"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for needle in SECRET_CONTENT_PATTERNS:
                if needle == "sk-":
                    if re.search(r"\bsk-[A-Za-z0-9]{16,}", text):
                        offenders.append((needle, rel))
                elif needle in text:
                    offenders.append((needle, rel))
            if SECRET_ASSIGN_RE.search(text):
                offenders.append(("secret-assignment", rel))
    assert not offenders, f"secret-like material in package: {offenders}"


def test_v1c19_no_junk_in_dist(pkg_dist):
    """dist must contain zero temp/cache/worktree junk.  This includes the
    ui/ tree the packager copies verbatim."""
    pkg_dir, _, _, _ = pkg_dist
    junk = []
    for p in _pkg_files(pkg_dir):
        rel = str(p.relative_to(pkg_dir)).replace("\\", "/")
        parts = {seg.lower() for seg in Path(rel).parts}
        if (parts & JUNK_DIR_PARTS or
                any(seg.lower().startswith(JUNK_DIR_PREFIXES)
                    for seg in Path(rel).parts)):
            junk.append(("dir", rel))
        elif JUNK_FILE_RE.search(rel):
            junk.append(("file", rel))
    assert not junk, (
        "temp/cache/worktree junk packaged into dist (defect for the "
        f"productization branch): {junk}")


# -----------------------------------------------------------------------
# V1C-20 — installer/launcher failure produces useful logs
# -----------------------------------------------------------------------

def test_v1c20_installer_failure_produces_useful_logs(mini_env):
    """A backend that cannot boot must leave a real log file with the
    traceback — never a silent failure."""
    from core import service_lifecycle as svc
    port = _free_port()
    res = svc.start_service("qa-broken-svc", "127.0.0.1", port,
                            "qa_definitely_missing_module:app",
                            ready_timeout_s=6.0)
    assert res.get("ok") is False, res
    log_path = res.get("log")
    assert log_path and Path(log_path).exists(), \
        f"failure did not produce a log: {res}"
    content = Path(log_path).read_text(encoding="utf-8", errors="replace")
    assert content.strip(), "error log is empty"
    assert re.search(r"Traceback|ERROR|Error|ModuleNotFound|error", content), \
        f"error log lacks diagnostic content: {content[:200]!r}"


def test_v1c20_pip_failure_names_the_problem(tmp_path):
    """A broken dependency contract must fail loudly and name the missing
    distribution (offline resolution; no network needed)."""
    bad = tmp_path / "bad_requirements.txt"
    bad.write_text("definitely-not-a-real-package-qax42==9.9.9\n",
                   encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--dry-run",
         "--disable-pip-version-check", "-r", str(bad)],
        capture_output=True, text=True, timeout=300)
    assert r.returncode != 0, "broken contract did not fail"
    combined = (r.stdout + r.stderr).lower()
    assert "definitely-not-a-real-package-qax42" in combined, combined[:500]


# -----------------------------------------------------------------------
# V1C-21 — no fake PASS when the process dies
# -----------------------------------------------------------------------

def test_v1c21_status_truthful_when_process_dies(mini_env):
    """After the backend process is killed, every status surface must flip
    to not-ready — never keep reporting a healthy service."""
    from core import service_lifecycle as svc
    port = _free_port()
    res = _start_mini(mini_env, port)
    assert res.get("ok") and res.get("ready"), res
    pid = res["pid"]
    try:
        assert svc.pid_alive(pid) is True
    finally:
        svc._terminate(pid)
        deadline = time.time() + 8
        while time.time() < deadline and svc.pid_alive(pid):
            time.sleep(0.1)
    assert svc.pid_alive(pid) is False, "process survived termination"
    st = svc.service_status("qa-mini-svc", "127.0.0.1", port)
    assert st["ready"] is False and st["state"] != "RUNNING", st
    assert _http_status(f"http://127.0.0.1:{port}/api/ua/status",
                        timeout=1.0) != 200
    # ensure_running on a dead backend must not fake success either
    out = svc.ensure_running("qa-mini-svc", "127.0.0.1", port,
                             "mini_app:app", max_attempts=1)
    # (either it truthfully restarts it, or it truthfully fails; both fine —
    #  what is forbidden is ok=True without a real ready probe)
    if out.get("ok"):
        assert out.get("pid") and svc.pid_alive(out["pid"]) and \
            svc.http_ready(f"http://127.0.0.1:{port}{HEALTH_PATH}")
        svc.stop_service("qa-mini-svc", "127.0.0.1", port, grace_s=5)
    else:
        assert out.get("error"), out


def test_v1c21_failed_mission_never_reports_pass():
    """A failed mission's canonical response can never carry verdict PASS."""
    from core.mission import MissionState, mission_response
    state = MissionState(mission_id="mission_qa_dead",
                         prompt="qa: process died mid-mission")
    state.status = "failed"
    state.verdict = "FAIL"
    state.why = "backend process died"
    resp = mission_response(state)
    assert resp["verdict"] != "PASS" and resp["status"] == "failed"


# -----------------------------------------------------------------------
# V1C-22 — package Quickstart <= 3 user actions
# -----------------------------------------------------------------------

def test_v1c22_quickstart_max_3_actions(pkg_dist):
    pkg_dir, _, _, _ = pkg_dist
    readme = (pkg_dir / "README-packaging.txt").read_text(encoding="utf-8")
    actions = re.findall(r"python product_launcher\.py[^\n#]*", readme)
    # count distinct user commands, ignoring the no-arg serve shorthand
    # (double-click / single command) separately
    assert len(actions) <= 3, (
        f"Quickstart requires {len(actions)} actions (contract: <= 3): "
        f"{actions}")
    assert readme.count("product_launcher.py") >= 1
    # zip ships alongside the dir for the one-step download story
    assert (pkg_dir.parent / (pkg_dir.name + ".zip")).exists()


# -----------------------------------------------------------------------
# V1C-23 / V1C-24 / V1C-25 — RC1.1 truthfulness regressions
# -----------------------------------------------------------------------

def test_v1c23_rc11_truthfulness_zero_step_guard():
    """The zero-completed-steps FAIL guard must remain in the mission
    validator (a 0-step execute can never be verified PASS)."""
    import inspect
    from core import mission as mission_mod
    source = inspect.getsource(mission_mod)
    assert ("0 executed steps" in source) or (
        "Mission executed 0 steps" in source), \
        "zero-step FAIL guard removed from mission validation"
    from core.universal_intent import interpret_intent
    d = interpret_intent("Capture the current Unreal viewport").to_dict()
    assert d["read_only"] is True and d["capture_only"] is True


def test_v1c24_capture_unreal_viewport_regression():
    """Capture prompts must still produce a real READ-ONLY
    capture_unreal_viewport EVIDENCE step (RC1.1 defect 2)."""
    from core.universal_intent import expand_requirements, interpret_intent
    from core.universal_planner import build_universal_planner
    from core.tool_registry import build_registry
    from core import orchestrator
    registry = build_registry(
        orchestrator.discover_projects, orchestrator.inspect_project,
        orchestrator.open_project, orchestrator.create_project,
        orchestrator.read_text_file, orchestrator.write_text_file,
        orchestrator.run_powershell, orchestrator.unreal_status,
        bridge=None)
    planner = build_universal_planner(registry)
    intent = interpret_intent("Capture the current Unreal viewport")
    plan = planner.build_plan(intent, expand_requirements(intent), {})
    steps = plan.to_dict()["steps"]
    capture = [s for s in steps
               if s.get("preferred_tool") == "capture_unreal_viewport"]
    assert capture, f"no capture step planned: {steps}"
    assert any(s.get("phase") == "EVIDENCE" for s in capture)
    tools = {s.get("preferred_tool") for s in steps}
    assert not (tools & {"spawn_actor", "delete_actor", "open_project",
                         "write_text_file", "run_powershell"}), tools


def test_v1c25_requested_tool_missing_preserved():
    """Explicit unsatisfiable tool requests must still fail truthfully up
    front with REQUESTED_TOOL_MISSING (release-95 behavior)."""
    import inspect
    from core.session_execution import _extract_requested_tools
    from core.tool_registry import build_registry
    from core import orchestrator
    got = _extract_requested_tools(
        "read only: call the tool named definitely_not_a_real_tool_xyz "
        "and report its exact result")
    assert got == {"definitely_not_a_real_tool_xyz"}
    registry = build_registry(
        orchestrator.discover_projects, orchestrator.inspect_project,
        orchestrator.open_project, orchestrator.create_project,
        orchestrator.read_text_file, orchestrator.write_text_file,
        orchestrator.run_powershell, orchestrator.unreal_status,
        bridge=None)
    assert "definitely_not_a_real_tool_xyz" not in registry
    from core import session_execution
    source = inspect.getsource(session_execution)
    assert "REQUESTED_TOOL_MISSING" in source
    assert "refusing to report success" in source
