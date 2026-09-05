"""app/mcp_gateway.py — Aivido MCP Gateway for ClickUp.

Exposes the EXISTING Unreal Coder mission pipeline to ClickUp Brain /
Super Agents as an MCP server (Streamable HTTP transport) with Bearer
API-key authentication.

The gateway is a thin, authenticated proxy: it performs NO execution
itself. Every tool forwards to the local Aivido backend
(127.0.0.1:8765 — the process that owns the Unreal bridge), which
remains the only execution layer. Mission state is always read from the
real backend checkpoints, so the gateway can never report SUCCESS that
the pipeline did not validate.

Tools: get_status, start_task, get_task_status, run_validation,
get_evidence, retry_task, cancel_task (Unreal missions), plus the
code-task supervisor tools: start_code_task, get_code_task_status,
get_code_evidence, retry_code_task, cancel_code_task, route_prompt.

Security:
- Binds to 127.0.0.1 by default; expose via the local HTTPS tunnel
  (Tailscale serve) instead of binding a public interface.
- Requires `Authorization: Bearer <api-key>` on every MCP request
  (`x-api-key` is also accepted for client compatibility).
- The API key is read from $AIVIDO_MCP_API_KEY or
  config/mcp_gateway.key (auto-generated on first run, gitignored,
  never committed).
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BACKEND_URL = os.environ.get(
    "AIVIDO_BACKEND_URL", "http://127.0.0.1:8765")
KEY_FILE = Path(os.environ.get(
    "AIVIDO_MCP_KEY_FILE", str(ROOT / "config" / "mcp_gateway.key")))
# Public HTTPS hostname allowed through DNS-rebinding protection. Read from
# $AIVIDO_MCP_PUBLIC_HOST or a gitignored config file so the setting survives
# restarts regardless of how the gateway is launched.
PUBLIC_HOST_FILE = Path(os.environ.get(
    "AIVIDO_MCP_PUBLIC_HOST_FILE",
    str(ROOT / "config" / "mcp_gateway.public_host")))

GATEWAY_NAME = "Aivido MCP Gateway"
GATEWAY_VERSION = "1.0.0"

# Browser origins ClickUp's app uses when it connects MCP servers from the
# ClickUp browser app (help.clickup.com: "currently, you can only connect MCP
# servers from the ClickUp browser app"). Server-side fetches (the common
# path) send no Origin header and are unaffected; these entries only matter
# when a real browser page at app.clickup.com talks to the endpoint, and they
# keep the SDK's DNS-rebinding origin check from rejecting that traffic.
CLICKUP_ORIGINS = (
    "https://app.clickup.com",
    "https://clickup.com",
    "https://search.clickup-prod.com",
)

# Mission status -> coarse ClickUp-friendly stage.
MISSION_STAGES = {
    "interpreting": "planning",
    "planning": "planning",
    "executing": "executing",
    "validating": "validating",
    "repairing": "validating",
    "complete": "complete",
    "failed": "failed",
    "blocked": "blocked",
}


# ---------------------------------------------------------------------------
# API key handling (env var wins; otherwise a gitignored local key file)
# ---------------------------------------------------------------------------

def load_or_create_api_key() -> str:
    env_key = os.environ.get("AIVIDO_MCP_API_KEY", "").strip()
    if env_key:
        return env_key

    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key

    key = "avmcp_" + secrets.token_urlsafe(40)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass  # best effort (no-op on Windows)
    return key


def api_key_location() -> str:
    if os.environ.get("AIVIDO_MCP_API_KEY", "").strip():
        return "environment variable AIVIDO_MCP_API_KEY"
    return str(KEY_FILE)


def load_public_host() -> str:
    """Public HTTPS hostname for DNS-rebinding allow-listing: env var wins,
    otherwise a gitignored config file (config/mcp_gateway.public_host)."""
    env_host = os.environ.get("AIVIDO_MCP_PUBLIC_HOST", "").strip()
    if env_host:
        return env_host
    if PUBLIC_HOST_FILE.exists():
        host = PUBLIC_HOST_FILE.read_text(encoding="utf-8").strip()
        if host:
            return host
    return ""


# ---------------------------------------------------------------------------
# Thin backend client (the real execution layer stays in app/api.py)
# ---------------------------------------------------------------------------

class AividoBackend:
    def __init__(self, base_url: str = BACKEND_URL, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, timeout: Optional[float] = None):
        r = requests.get(
            self.base_url + path, timeout=timeout or self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: Optional[dict] = None,
              timeout: Optional[float] = None):
        r = requests.post(
            self.base_url + path,
            json=payload or {},
            timeout=timeout or self.timeout,
        )
        r.raise_for_status()
        return r.json()


def _mission_envelope(mission_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Shape one real mission payload into the gateway's JSON contract:
    task_id, status, stage, result, errors, evidence paths/URLs."""
    status = str(payload.get("status") or "unknown")
    stage = MISSION_STAGES.get(status, status)

    result: Dict[str, Any] = {
        "mission_id": mission_id,
        "verdict": payload.get("verdict"),
        "why": payload.get("why"),
        "interpretation": payload.get("interpretation"),
        "plan": payload.get("plan"),
        "completed_work": payload.get("completed_work"),
        "user_result": payload.get("user_result"),
    }

    errors: List[str] = []
    for key in ("remaining_issues", "blockers", "warnings"):
        for item in (payload.get(key) or []):
            errors.append(f"{key}: {item}")

    evidence_paths: List[str] = []
    for ev in (payload.get("evidence") or []):
        if isinstance(ev, dict):
            p = ev.get("path") or ev.get("file") or ev.get("resource_path")
            if p:
                evidence_paths.append(str(p))

    artifacts: List[str] = []
    for art in (payload.get("artifacts") or []):
        if isinstance(art, dict):
            p = art.get("path") or art.get("resource_path")
            if p:
                artifacts.append(str(p))

    return {
        "ok": True,
        "task_id": mission_id,
        "status": status,
        "stage": stage,
        "result": result,
        "errors": errors or None,
        "evidence": {
            "paths": evidence_paths,
            "artifacts": artifacts,
            "mission_log": payload.get("mission_log"),
        },
    }


def _backend_error(task_id: Optional[str], exc: Exception) -> Dict[str, Any]:
    status_code = ""
    if isinstance(exc, requests.exceptions.HTTPError) and \
            exc.response is not None:
        status_code = str(exc.response.status_code)
    return {
        "ok": False,
        "task_id": task_id,
        "status": "error",
        "stage": "error",
        "result": None,
        "errors": [f"backend HTTP {status_code}: {exc}".strip()],
        "evidence": [],
    }


# ---------------------------------------------------------------------------
# MCP tools (each forwards to the real backend pipeline)
# ---------------------------------------------------------------------------

def tool_get_status() -> Dict[str, Any]:
    """Gateway + Aivido backend health. Never invents state: every field is
    read from the real backend (GET /api/status), including live Unreal
    bridge and Ollama reachability."""
    try:
        st = AividoBackend()._get("/api/status", timeout=10)
    except Exception as exc:
        return _backend_error(None, exc)
    return {
        "ok": bool(st.get("ok")),
        "task_id": None,
        "status": "ready" if st.get("ok") else "degraded",
        "stage": "health",
        "result": {
            "backend_version": st.get("version"),
            "execution_active": bool(st.get("execution_active")),
            "pending_approvals": int(st.get("pending_approvals") or 0),
            "unreal_bridge": st.get("unreal"),
            "ollama": st.get("ollama"),
            "models": st.get("models"),
        },
        "errors": None,
        "evidence": [],
    }


def tool_start_task(
    prompt: str,
    project: Optional[str] = None,
    quality: Optional[str] = None,
    platform: Optional[str] = None,
    mode: str = "execute",
) -> Dict[str, Any]:
    """Start a new Aivido mission. Forwards to the real mission pipeline
    (POST /api/unreal-coder/async); the backend plans, executes through the
    Unreal bridge, validates and checkpoints the mission. Returns the real
    mission id as task_id plus 'accepted' status — SUCCESS is only ever
    reported after the pipeline's own validation passes."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return {
            "ok": False, "task_id": None, "status": "error",
            "stage": "error", "result": None,
            "errors": ["prompt is required"], "evidence": [],
        }
    body: Dict[str, Any] = {"prompt": prompt, "mode": mode or "execute"}
    for key, value in (("project", project), ("quality", quality),
                       ("platform", platform)):
        if value:
            body[key] = str(value)
    try:
        r = AividoBackend()._post("/api/unreal-coder/async", body, timeout=30)
    except Exception as exc:
        return _backend_error(None, exc)
    mission_id = str(r.get("mission_id") or "")
    return {
        "ok": bool(r.get("ok")),
        "task_id": mission_id or None,
        "status": str(r.get("status") or "accepted"),
        "stage": "accepted",
        "result": {
            "message": r.get("message"),
            "poll": f"get_task_status('{mission_id}')",
        },
        "errors": None,
        "evidence": [],
    }


def tool_get_task_status(task_id: str) -> Dict[str, Any]:
    """Real mission state from the backend checkpoint
    (GET /api/unreal-coder/mission/{task_id})."""
    try:
        payload = AividoBackend()._get(
            f"/api/unreal-coder/mission/{task_id}", timeout=20)
    except Exception as exc:
        return _backend_error(task_id, exc)
    return _mission_envelope(task_id, payload)


def tool_run_validation(task_id: str) -> Dict[str, Any]:
    """Re-run REAL validation on a mission through the existing pipeline
    (POST /api/unreal-coder/mission/{task_id}/validate): the backend's
    technical gate plus a fresh visual-acceptance capture/score. Returns the
    pipeline's own verdict/errors/evidence — never a fabricated PASS."""
    try:
        payload = AividoBackend()._post(
            f"/api/unreal-coder/mission/{task_id}/validate", timeout=300)
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            try:
                live = AividoBackend()._get(
                    f"/api/unreal-coder/mission/{task_id}", timeout=20)
            except Exception as get_exc:
                return _backend_error(task_id, get_exc)
            env = _mission_envelope(task_id, live)
            env["stage"] = "not_ready"
            env["errors"] = [
                "Validation not run yet: mission has not finished executing. "
                "Poll get_task_status until stage reaches validating/complete."
            ] + (env["errors"] or [])
            return env
        return _backend_error(task_id, exc)
    except Exception as exc:
        return _backend_error(task_id, exc)
    return _mission_envelope(task_id, payload)


def tool_get_evidence(task_id: str) -> Dict[str, Any]:
    """Evidence produced by the REAL pipeline for a mission: viewport
    captures, artifacts and the mission log path from the backend
    checkpoint (GET /api/unreal-coder/mission/{task_id})."""
    try:
        payload = AividoBackend()._get(
            f"/api/unreal-coder/mission/{task_id}", timeout=20)
    except Exception as exc:
        return _backend_error(task_id, exc)
    env = _mission_envelope(task_id, payload)
    return {
        "ok": env["ok"],
        "task_id": env["task_id"],
        "status": env["status"],
        "stage": "evidence",
        "result": {
            "evidence_paths": env["evidence"]["paths"],
            "artifacts": env["evidence"]["artifacts"],
            "mission_log": env["evidence"]["mission_log"],
            "verdict": (env["result"] or {}).get("verdict"),
            "why": (env["result"] or {}).get("why"),
        },
        "errors": env["errors"],
        "evidence": env["evidence"],
    }


def tool_retry_task(task_id: str) -> Dict[str, Any]:
    """Retry/resume one mission through the real engine
    (POST /api/unreal-coder/mission/{task_id}/resume). Completed steps are
    skipped from the checkpoint; failed/pending steps re-dispatch through
    the existing executor and validation runs again. Blocks until the
    pipeline finishes and returns the pipeline's real result."""
    try:
        payload = AividoBackend()._post(
            f"/api/unreal-coder/mission/{task_id}/resume",
            timeout=3600)
    except Exception as exc:
        return _backend_error(task_id, exc)
    return _mission_envelope(task_id, payload)


def tool_cancel_task(task_id: str) -> Dict[str, Any]:
    """Cancel a running mission (POST
    /api/unreal-coder/mission/{task_id}/cancel). The backend stops the
    worker at the next step boundary and finalizes the checkpoint as
    CANCELLED — never SUCCESS."""
    try:
        payload = AividoBackend()._post(
            f"/api/unreal-coder/mission/{task_id}/cancel", timeout=30)
    except Exception as exc:
        return _backend_error(task_id, exc)
    return _mission_envelope(task_id, payload)


# ===========================================================================
# CODE-TASK tools (autonomous supervisor: repo/code work, isolated worker)
# ===========================================================================
# These forward to the backend's /api/code/* domain (app/code_tasks.py). The
# backend is still the ONLY execution layer: it owns the durable queue, the
# single-flight worker and the isolated git worktree. The gateway never
# reports PASS itself — it relays the backend's verdict/evidence.
# ===========================================================================

CODE_STAGES = {
    "queued": "queued",
    "running": "running",
    "passed": "complete",
    "failed": "failed",
    "blocked": "blocked",
    "cancelled": "cancelled",
}


def _code_error(task_id: Optional[str], exc: Exception) -> Dict[str, Any]:
    detail = ""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        try:
            body = exc.response.json()
            detail = str(body.get("detail") or body)[:500]
        except Exception:
            detail = exc.response.text[:500]
    return {
        "ok": False,
        "task_id": task_id,
        "status": "error",
        "stage": "error",
        "result": None,
        "errors": [detail or f"backend {exc}"],
        "evidence": [],
    }


def _code_call(method: str, path: str, payload: Optional[dict] = None,
               timeout: float = 30.0):
    backend = AividoBackend()
    if method == "GET":
        return backend._get(path, timeout=timeout)
    return backend._post(path, payload, timeout=timeout)


def _code_envelope(task: Dict[str, Any]) -> Dict[str, Any]:
    status = str(task.get("status") or "queued")
    verdict = task.get("verdict")
    return {
        "ok": True,
        "task_id": task.get("id"),
        "status": status,
        "stage": CODE_STAGES.get(status, status),
        "result": {
            "title": task.get("title"),
            "routing": task.get("routing"),
            "priority": task.get("priority"),
            "verdict": verdict,
            "attempt": task.get("attempt"),
            "max_attempts": task.get("max_attempts"),
            "depends_on": task.get("depends_on"),
            "summary": (task.get("result") or {}).get("summary")
            if isinstance(task.get("result"), dict) else None,
            "branch": (task.get("result") or {}).get("branch")
            if isinstance(task.get("result"), dict) else None,
            "commit": (task.get("result") or {}).get("commit")
            if isinstance(task.get("result"), dict) else None,
            "finished": verdict is not None,
            "prompt": task.get("prompt"),
        },
        "errors": [task["error"]] if task.get("error") else
                  ([task["blocked_reason"]] if task.get("blocked_reason") else None),
        "evidence": {
            "paths": list(task.get("evidence") or []),
            "files": None,
        },
    }


def tool_start_code_task(
    prompt: str,
    title: str = "",
    routing: str = "auto",
    priority: int = 50,
    depends_on: Optional[List[str]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    tests: Optional[List[str]] = None,
    acceptance: Optional[List[str]] = None,
    scope: Optional[List[str]] = None,
    unreal_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a CODE task on the autonomous supervisor (repo/code/test work).

    Machine-readable contract (natural-language-only prompts are BLOCKED,
    never guessed):
      steps:      [{"op": "create_file", "path": "app/x.py",
                    "content": "..."}]   (new files only, isolated worktree)
      tests:      ["pytest tests/test_x.py", "py_compile app/x.py"]
      acceptance: ["exists app/x.py", "contains tests/test_x.py|assert"]
      scope:      [allowed relative paths]
      unreal_prompt: (mixed tasks only) prompt for the Unreal mission stage,
                    run AFTER the code stage passes, in dependency order.
    Unreal/editor/content prompts are routed away (use start_task). Returns
    task_id immediately; poll get_code_task_status."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return {
            "ok": False, "task_id": None, "status": "error",
            "stage": "error", "result": None,
            "errors": ["prompt is required"], "evidence": [],
        }
    body: Dict[str, Any] = {"prompt": prompt, "routing": routing or "auto"}
    if title:
        body["title"] = str(title)
    if priority:
        body["priority"] = int(priority)
    for key, value in (("depends_on", depends_on), ("steps", steps),
                       ("tests", tests), ("acceptance", acceptance),
                       ("scope", scope), ("unreal_prompt", unreal_prompt)):
        if value:
            body[key] = value
    try:
        payload = _code_call("POST", "/api/code/tasks", body, timeout=30)
    except Exception as exc:
        return _code_error(None, exc)
    task = payload.get("task") or {}
    return _code_envelope(task)


def tool_get_code_task_status(task_id: str) -> Dict[str, Any]:
    """Real code-task state from the backend's durable queue
    (GET /api/code/tasks/{task_id}). Returns status, verdict, attempts,
    summary, error/blocked reason and evidence paths."""
    try:
        payload = _code_call("GET", f"/api/code/tasks/{task_id}", timeout=20)
    except Exception as exc:
        return _code_error(task_id, exc)
    return _code_envelope(payload.get("task") or {})


def tool_get_code_evidence(task_id: str) -> Dict[str, Any]:
    """Full evidence bundle for a code task (GET
    /api/code/tasks/{task_id}/evidence): the evidence.json with the
    verified commit, per-check logs, acceptance results and the change
    patch, plus inline file contents."""
    try:
        payload = _code_call(
            "GET", f"/api/code/tasks/{task_id}/evidence", timeout=20)
    except Exception as exc:
        return _code_error(task_id, exc)
    evidence = payload.get("evidence") or {}
    return {
        "ok": bool(payload.get("ok")),
        "task_id": evidence.get("task_id") or task_id,
        "status": evidence.get("status"),
        "stage": "evidence",
        "result": {
            "verdict": evidence.get("verdict"),
            "title": evidence.get("title"),
            "result": evidence.get("result"),
            "blocked_reason": evidence.get("blocked_reason"),
            "error": evidence.get("error"),
        },
        "errors": [evidence.get("blocked_reason") or evidence.get("error")]
        if evidence.get("blocked_reason") or evidence.get("error") else None,
        "evidence": {
            "paths": list(evidence.get("evidence_files") or []),
            "files": evidence.get("files"),
        },
    }


def tool_retry_code_task(task_id: str) -> Dict[str, Any]:
    """Re-queue a failed/blocked/cancelled code task for another bounded
    attempt (POST /api/code/tasks/{task_id}/retry). The worker re-runs and
    re-validates from scratch inside a fresh isolated worktree."""
    try:
        payload = _code_call(
            "POST", f"/api/code/tasks/{task_id}/retry", {}, timeout=30)
    except Exception as exc:
        return _code_error(task_id, exc)
    return _code_envelope(payload.get("task") or {})


def tool_cancel_code_task(task_id: str) -> Dict[str, Any]:
    """Cancel a queued/running code task; the backend records verdict
    CANCELLED, never PASS (POST /api/code/tasks/{task_id}/cancel)."""
    try:
        payload = _code_call(
            "POST", f"/api/code/tasks/{task_id}/cancel", {}, timeout=30)
    except Exception as exc:
        return _code_error(task_id, exc)
    return _code_envelope(payload.get("task") or {})


def tool_route_prompt(prompt: str) -> Dict[str, Any]:
    """Routing decision for a task prompt: 'code' (repo/code/test work),
    'unreal' (existing mission pipeline via start_task) or 'mixed'.
    The supervisor uses this to pick the owning pipeline."""
    try:
        payload = _code_call(
            "POST", "/api/code/classify", {"prompt": str(prompt or "")},
            timeout=20)
    except Exception as exc:
        return _code_error(None, exc)
    return {
        "ok": bool(payload.get("ok")),
        "task_id": None,
        "status": "ready",
        "stage": "routing",
        "result": {"routing": payload.get("routing")},
        "errors": None,
        "evidence": [],
    }


# ---------------------------------------------------------------------------
# App assembly: Bearer-auth FastAPI app + mounted MCP Streamable HTTP server
# ---------------------------------------------------------------------------

def build_mcp_server(api_key: str):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        GATEWAY_NAME,
        version=GATEWAY_VERSION,
        instructions=(
            "Aivido MCP gateway for the autonomous supervisor. Two owning "
            "pipelines: (1) Unreal/editor/content tasks -> start_task (mission "
            "pipeline, unchanged); (2) repository/code/test/cleanup tasks -> "
            "start_code_task (isolated code worker). start_code_task needs a "
            "machine-readable spec (steps/tests/acceptance/scope) and returns "
            "a task_id immediately; poll get_code_task_status; get_code_evidence "
            "returns the verified commit + evidence; retry_code_task re-queues; "
            "cancel_code_task stops. route_prompt tells you the owner for a "
            "prompt. Never assume PASS/SUCCESS — read the real verdict."
        ),
    )

    tools = [
        (tool_get_status, "get_status",
         "Read gateway + Aivido backend health (real backend /api/status: "
         "Unreal bridge, Ollama, execution state). No arguments."),
        (tool_start_task, "start_task",
         "Start a new Aivido mission. Forwards to the real mission pipeline "
         "(async). Args: prompt (required, natural language task), optional "
         "project, quality, platform, mode (default 'execute'). Returns "
         "task_id immediately with status 'accepted'; real validation "
         "happens in the backend."),
        (tool_get_task_status, "get_task_status",
         "Real mission state from the backend checkpoint. Args: task_id "
         "(mission id from start_task). Returns status, stage, verdict, "
         "result, errors, evidence."),
        (tool_run_validation, "run_validation",
         "Re-run REAL validation on a mission through the existing pipeline: "
         "technical gate + fresh visual-acceptance capture/score. Args: "
         "task_id. Returns the pipeline's own verdict/errors/evidence."),
        (tool_get_evidence, "get_evidence",
         "Evidence produced by the real pipeline for a mission: capture "
         "paths, artifacts, mission log. Args: task_id."),
        (tool_retry_task, "retry_task",
         "Retry/resume one mission through the real engine; failed/pending "
         "steps re-execute and validation runs again. Args: task_id. Blocks "
         "until the pipeline finishes and returns the real result."),
        (tool_cancel_task, "cancel_task",
         "Cancel a running mission; the backend finalizes the checkpoint as "
         "CANCELLED, never SUCCESS. Args: task_id."),
        (tool_start_code_task, "start_code_task",
         "Start a CODE task on the autonomous supervisor (repo/code/test "
         "work, isolated git worktree + branch, verified commit only). "
         "Args: prompt (required), title, routing ('auto'/'code'), priority, "
         "steps (create_file ops: path + content), tests (pytest/py_compile), "
         "acceptance (exists/contains/imports), scope. Natural-language-only "
         "prompts are BLOCKED, never guessed. Unreal tasks are rejected here "
         "(use start_task). Returns task_id immediately."),
        (tool_get_code_task_status, "get_code_task_status",
         "Real code-task state from the durable backend queue. Args: task_id. "
         "Returns status, verdict, attempts, summary, error/blocked reason."),
        (tool_get_code_evidence, "get_code_evidence",
         "Full evidence bundle for a code task: evidence.json (verified "
         "commit, checks, acceptance results) + change patch. Args: task_id."),
        (tool_retry_code_task, "retry_code_task",
         "Re-queue a failed/blocked/cancelled code task for another bounded "
         "attempt in a fresh worktree. Args: task_id."),
        (tool_cancel_code_task, "cancel_code_task",
         "Cancel a queued/running code task; verdict CANCELLED, never PASS. "
         "Args: task_id."),
        (tool_route_prompt, "route_prompt",
         "Routing decision for a prompt: code | unreal | mixed. Args: prompt."),
    ]

    for fn, name, description in tools:
        server.add_tool(fn, name=name, description=description)

    return server


def create_gateway_app(api_key: str):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    # The MCP Starlette app must stay the TOP-LEVEL app so its own lifespan
    # runs (it starts the StreamableHTTP session manager task group). We add
    # the auth middleware and the public /health probe directly onto it.
    from mcp.server.transport_security import TransportSecuritySettings

    mcp_server = build_mcp_server(api_key)
    # Keep the SDK's DNS-rebinding protection ON: allow the loopback hosts
    # (local use) plus the public HTTPS tunnel hostname
    # (AIVIDO_MCP_PUBLIC_HOST, e.g. <something>.trycloudflare.com) that
    # Cloudflare's edge presents as the Host header. Both plain and ":*"
    # forms are listed so exact-match and port-suffixed Hosts both pass.
    allowed_hosts = [
        "127.0.0.1", "127.0.0.1:*",
        "localhost", "localhost:*",
        "[::1]", "[::1]:*",
    ]
    public_host = load_public_host()
    if public_host:
        allowed_hosts.append(public_host)
        allowed_hosts.append(public_host + ":*")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        # Loopback dev/test origins plus the ClickUp browser-app origins.
        # API-key auth is still enforced on every POST; this only relaxes the
        # SDK's Origin-header check for ClickUp's documented connect flow.
        allowed_origins=list(CLICKUP_ORIGINS) + [
            "http://127.0.0.1:*", "http://localhost:*",
            "http://[::1]:*",
        ],
    )
    app = mcp_server.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        # ClickUp-compatible response mode: every POST is answered with ONE
        # complete application/json response instead of an open-ended
        # text/event-stream. SSE streams are correct for streaming-capable
        # clients, but ClickUp's connection-validation HTTP layer buffers
        # until the stream ends and therefore spins forever. JSON responses
        # stay fully Streamable-HTTP compliant (the spec mandates JSON when
        # the client does not ask for SSE) and keep Bearer auth intact.
        json_response=True,
        transport_security=security,
    )

    # CORS for the ClickUp browser-app connect flow. The browser needs an
    # explicit preflight answer (OPTIONS) plus response headers; without them
    # a cross-origin POST from app.clickup.com is blocked before it reaches
    # the MCP handler (and the browser hides the mcp-session-id header, which
    # breaks sessioned clients). Only known ClickUp / loopback origins get
    # CORS headers; everyone else sees a plain response with no ACAO, so the
    # browser still enforces same-origin policy. Bearer auth is untouched.
    class CorsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            origin = request.headers.get("origin", "")
            allowed = (
                origin in CLICKUP_ORIGINS
                or origin.startswith("http://localhost")
                or origin.startswith("http://127.0.0.1")
            )

            if request.method == "OPTIONS":
                headers = {} if not allowed else {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods":
                        "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": (
                        "Authorization, Content-Type, Accept, "
                        "Mcp-Session-Id, Mcp-Protocol-Version, "
                        "Last-Event-ID, X-Api-Key"
                    ),
                    "Access-Control-Max-Age": "86400",
                    "Vary": "Origin",
                }
                # Bodyless 204: a JSONResponse with content=None would render
                # a "null" body + Content-Length on a no-body status, which
                # h11 rejects mid-write and proxies surface as 502.
                from starlette.responses import Response as StarletteResponse
                return StarletteResponse(status_code=204, headers=headers)

            response = await call_next(request)
            if allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Expose-Headers"] = (
                    "Mcp-Session-Id, Mcp-Protocol-Version, "
                    "WWW-Authenticate, Content-Type"
                )
                response.headers.setdefault("Vary", "Origin")
            return response

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            # Health probe + CORS/SSE-upgrade preflight stay reachable so MCP
            # clients can discover the endpoint; they expose no data and no
            # tools. GET is not authenticated per the MCP transport spec
            # (clients never send Authorization on GET); every POST (all MCP
            # tool calls) requires the Bearer API key.
            if path in ("/health", "/") or request.method in ("GET", "OPTIONS"):
                return await call_next(request)

            auth = request.headers.get("authorization", "")
            api_key_header = request.headers.get("x-api-key", "")
            ok = (
                auth.startswith("Bearer ")
                and secrets.compare_digest(auth[len("Bearer "):], api_key)
            ) or (
                bool(api_key_header)
                and secrets.compare_digest(api_key_header, api_key)
            )
            if not ok:
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "error": "unauthorized"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return await call_next(request)

    def health(request):
        backend_ok = False
        try:
            backend_ok = bool(
                AividoBackend()._get("/api/status", timeout=5).get("ok"))
        except Exception:
            backend_ok = False
        return JSONResponse({
            "ok": True,
            "gateway": GATEWAY_NAME,
            "version": GATEWAY_VERSION,
            "auth": "Bearer api-key (Authorization header)",
            "backend_reachable": backend_ok,
            "mcp_endpoint": "/mcp",
        })

    app.add_middleware(AuthMiddleware)
    app.add_middleware(CorsMiddleware)
    app.add_route("/health", health, methods=["GET"])
    return app


def main():
    parser = argparse.ArgumentParser(description=GATEWAY_NAME)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8844)
    parser.add_argument("--print-key", action="store_true",
                        help="print the API key once (e.g. for ClickUp setup)")
    args = parser.parse_args()

    api_key = load_or_create_api_key()
    if args.print_key:
        print(f"AIVIDO_MCP_API_KEY={api_key}", flush=True)
        return

    app = create_gateway_app(api_key)
    import uvicorn
    print(
        f"[{GATEWAY_NAME}] key source: {api_key_location()} "
        f"(use --print-key to reveal)", flush=True)
    print(
        f"[{GATEWAY_NAME}] MCP endpoint: http://{args.host}:{args.port}/mcp "
        f"(Streamable HTTP, Bearer auth)", flush=True)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()