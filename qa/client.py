"""qa/client.py — black-box HTTP client for the running Aivido backend.

The QA bot behaves like an external QA engineer: every product interaction
goes over HTTP to AIVIDO_BACKEND_URL (default http://127.0.0.1:8765). The
only out-of-process probe outside the backend is the READ-ONLY Unreal
bridge (identity / actor list / current level) for scene-preservation
checks — no mutation is ever performed through this module.
"""
from __future__ import annotations

import os
import socket
import time
from typing import Any, Dict, List, Optional

import requests

BACKEND_URL = os.environ.get(
    "AIVIDO_BACKEND_URL", "http://127.0.0.1:8765")
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766


class BackendClient:
    def __init__(self, base_url: str = BACKEND_URL, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- transport ----------------------------------------------------------
    def request(self, method: str, path: str, payload: Any = None,
                timeout: Optional[float] = None) -> Dict[str, Any]:
        url = self.base_url + path
        started = time.time()
        try:
            r = requests.request(
                method, url, json=payload, timeout=timeout or self.timeout)
            latency_ms = round((time.time() - started) * 1000, 1)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:500]}
            return {
                "ok": True,
                "http_status": r.status_code,
                "latency_ms": latency_ms,
                "body": body,
            }
        except requests.exceptions.ConnectionError as exc:
            return {"ok": False, "http_status": 0, "latency_ms": 0,
                    "body": {"error": f"connection refused: {exc}"}}
        except requests.exceptions.Timeout as exc:
            return {"ok": False, "http_status": 0, "latency_ms": 0,
                    "body": {"error": f"timeout: {exc}"}}
        except Exception as exc:
            return {"ok": False, "http_status": 0, "latency_ms": 0,
                    "body": {"error": f"{type(exc).__name__}: {exc}"}}

    def get(self, path: str, timeout: Optional[float] = None):
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, payload: Any = None,
             timeout: Optional[float] = None):
        return self.request("POST", path, payload, timeout=timeout)

    # -- runtime health ------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return self.get("/api/status", timeout=10)

    def doctor(self) -> Dict[str, Any]:
        return self.get("/api/unreal-coder/doctor", timeout=30)

    def workspace(self) -> Dict[str, Any]:
        return self.get("/api/workspace")

    # -- unreal-coder missions ------------------------------------------------
    def start_mission(self, prompt: str, *, read_only: Optional[bool] = None,
                      mode: str = "execute", quality: str = "",
                      timeout: float = 40.0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"prompt": prompt, "mode": mode}
        if read_only is not None:
            payload["read_only"] = read_only
        if quality:
            payload["quality"] = quality
        return self.post("/api/unreal-coder/async", payload, timeout=timeout)

    def mission(self, mission_id: str) -> Dict[str, Any]:
        return self.get(f"/api/unreal-coder/mission/{mission_id}")

    def mission_validate(self, mission_id: str) -> Dict[str, Any]:
        return self.post(f"/api/unreal-coder/mission/{mission_id}/validate",
                         timeout=120)

    def mission_cancel(self, mission_id: str) -> Dict[str, Any]:
        return self.post(f"/api/unreal-coder/mission/{mission_id}/cancel")

    def mission_resume(self, mission_id: str) -> Dict[str, Any]:
        return self.post(f"/api/unreal-coder/mission/{mission_id}/resume",
                         timeout=1800)

    def session_identity(self) -> Dict[str, Any]:
        return self.get("/api/unreal-coder/session")

    def capabilities(self) -> Dict[str, Any]:
        return self.get("/api/unreal-coder/capabilities")

    # -- code tasks -----------------------------------------------------------
    def classify(self, prompt: str) -> Dict[str, Any]:
        return self.post("/api/code/classify", {"prompt": prompt})

    def enqueue_code_task(self, **task_fields) -> Dict[str, Any]:
        return self.post("/api/code/tasks", task_fields)

    def code_tasks(self) -> Dict[str, Any]:
        return self.get("/api/code/tasks")

    def code_task(self, task_id: str) -> Dict[str, Any]:
        return self.get(f"/api/code/tasks/{task_id}")

    def code_task_evidence(self, task_id: str) -> Dict[str, Any]:
        return self.get(f"/api/code/tasks/{task_id}/evidence")

    def code_task_retry(self, task_id: str) -> Dict[str, Any]:
        return self.post(f"/api/code/tasks/{task_id}/retry")

    def code_task_cancel(self, task_id: str) -> Dict[str, Any]:
        return self.post(f"/api/code/tasks/{task_id}/cancel")

    # -- sessions / projects / proof -------------------------------------------
    def sessions(self) -> Dict[str, Any]:
        return self.get("/api/sessions")

    def projects(self) -> Dict[str, Any]:
        return self.get("/api/projects")

    def multiclient_status(self) -> Dict[str, Any]:
        return self.get("/api/multiclient/status")

    def session_proof(self, session_id: str) -> Dict[str, Any]:
        return self.get(f"/api/sessions/{session_id}/proof")

    # -- other product surfaces -------------------------------------------------
    def proof_status(self) -> Dict[str, Any]:
        return self.get("/api/proof/status")

    def proof_latest(self) -> Dict[str, Any]:
        return self.get("/api/proof/latest")

    def workboard_state(self) -> Dict[str, Any]:
        return self.get("/api/workboard/state")

    def resources(self) -> Dict[str, Any]:
        return self.get("/api/resources")


# ---------------------------------------------------------------------------
# Read-only Unreal bridge probes
# ---------------------------------------------------------------------------


class BridgeProbe:
    """READ-ONLY Unreal editor probe. Only identity/actor-list/level reads;
    never executes anything that mutates the world, project or editor."""

    def __init__(self, host: str = BRIDGE_HOST, port: int = BRIDGE_PORT,
                 timeout: float = 6.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._bridge = None

    def _get_bridge(self):
        if self._bridge is None:
            try:
                from tools.unreal.unreal_bridge import UnrealBridge
                self._bridge = UnrealBridge(host=self.host, port=self.port,
                                            timeout=self.timeout)
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return self._bridge

    def ping(self) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not isinstance(bridge, dict):
            try:
                result = bridge.ping()
                return {"ok": bool(result), "raw": result}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return bridge

    def identity(self) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if isinstance(bridge, dict):
            return bridge
        try:
            result = bridge.get_identity()
            if isinstance(result, dict):
                return {"ok": bool(result.get("ok")), **result}
            return {"ok": False, "error": f"unexpected identity: {result!r}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def current_level(self) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if isinstance(bridge, dict):
            return bridge
        try:
            result = bridge.get_current_level()
            if isinstance(result, dict):
                return {"ok": bool(result.get("ok")), **result}
            return {"ok": False, "error": f"unexpected level result: {result!r}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def actor_names(self) -> Dict[str, Any]:
        """List of actor names in the current level (read-only)."""
        bridge = self._get_bridge()
        if isinstance(bridge, dict):
            return bridge
        try:
            result = bridge.list_level_actors()
            if not isinstance(result, dict):
                return {"ok": False, "error": f"unexpected: {result!r}"}
            payload = result.get("result")
            if isinstance(payload, dict) and isinstance(payload.get("result"),
                                                        dict):
                payload = payload["result"]
            if isinstance(payload, dict) and isinstance(payload.get("actors"),
                                                        list):
                return {"ok": True, "actors": payload["actors"],
                        "count": len(payload["actors"]),
                        "raw": result}
            names = payload.get("actors") if isinstance(payload, dict) else payload
            if isinstance(names, list):
                return {"ok": True, "actors": names, "count": len(names),
                        "raw": result}
            return {"ok": False, "error": "no actor list in bridge result",
                    "raw": result}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Environment snapshot
# ---------------------------------------------------------------------------


def environment_snapshot() -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "backend_url": BACKEND_URL,
        "bridge": {"host": BRIDGE_HOST, "port": BRIDGE_PORT},
        "captured_at": time.time(),
    }
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        snap["backend_listening"] = sock.connect_ex(
            ("127.0.0.1", 8765)) == 0
        sock.close()
    except Exception:
        snap["backend_listening"] = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        snap["bridge_listening"] = sock.connect_ex(
            (BRIDGE_HOST, BRIDGE_PORT)) == 0
        sock.close()
    except Exception:
        snap["bridge_listening"] = False
    return snap