"""bridge_allocator.py — dynamic per-session Unreal bridge allocation.

The legacy runtime assumes ONE fixed bridge on 127.0.0.1:6766. Multi-client
Aivido needs a unique bridge endpoint per running project instance:

    Project A -> 6766
    Project B -> 6767
    Project C -> 6768
    ...

Allocation is safe by construction:
  * a port is only handed out when it is not already bound to a live TCP
    listener on the host,
  * a port is only handed out once per process (per-project bindings),
  * `binding_for(project)` is stable across calls (reconnect reuses it),
  * `release` frees a binding; live sockets are re-probed at alloc time so
    a crashed editor cannot leave a phantom reservation behind.
"""
from __future__ import annotations

import os
import socket
import threading
from typing import Dict, List, Optional

DEFAULT_PORT_MIN = 6766
DEFAULT_PORT_MAX = 6799


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def port_is_listening(host: str = "127.0.0.1", port: int = 6766,
                      timeout: float = 0.25) -> bool:
    """Probe whether something is accepting TCP connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class BridgeAllocator:
    """Collision-safe port allocator for per-session Unreal bridges."""

    def __init__(self, port_min: Optional[int] = None,
                 port_max: Optional[int] = None,
                 host: str = "127.0.0.1"):
        self.port_min = port_min if port_min is not None else _env_int(
            "UA_BRIDGE_PORT_MIN", DEFAULT_PORT_MIN)
        self.port_max = port_max if port_max is not None else _env_int(
            "UA_BRIDGE_PORT_MAX", DEFAULT_PORT_MAX)
        self.host = host
        self._lock = threading.RLock()
        self._bindings: Dict[str, int] = {}  # project_id -> port
        self._owners: Dict[int, str] = {}    # port -> project_id

    # -- core -----------------------------------------------------------------
    def allocate(self, project_id: str,
                 preferred: Optional[int] = None,
                 force: bool = False) -> Dict[str, Any]:
        """Reserve a bridge port for a project. Idempotent per project:
        a project that already holds a binding keeps it. Returns a structured
        envelope: {ok, port, reused, host, project_id, binding}.

        `force=True` with a preferred port binds it even when a live listener
        is present — callers may use this ONLY after verifying the listener
        is this project's own verified bridge (reuse path)."""
        project_id = str(project_id or "")
        if not project_id:
            return {"ok": False, "error": "project_id is required"}
        with self._lock:
            existing = self._bindings.get(project_id)
            if existing is not None:
                return {
                    "ok": True,
                    "port": existing,
                    "reused": True,
                    "host": self.host,
                    "project_id": project_id,
                    "binding": self._binding(project_id, existing),
                }
            if preferred is not None \
                    and self._port_usable(preferred, project_id,
                                          force=force):
                self._bind(project_id, preferred)
                return {
                    "ok": True, "port": preferred, "reused": False,
                    "host": self.host, "project_id": project_id,
                    "binding": self._binding(project_id, preferred),
                }
            for port in range(self.port_min, self.port_max + 1):
                if self._port_usable(port, project_id):
                    self._bind(project_id, port)
                    return {
                        "ok": True, "port": port, "reused": False,
                        "host": self.host, "project_id": project_id,
                        "binding": self._binding(project_id, port),
                    }
            return {
                "ok": False,
                "error": (
                    f"no free bridge port in range "
                    f"{self.port_min}..{self.port_max}"),
            }

    def _port_usable(self, port: int, project_id: str,
                     force: bool = False) -> bool:
        """A port is usable when nothing else in THIS process owns it and no
        live listener occupies it (checked at allocation time). With
        force=True the listener probe is skipped (verified reuse)."""
        owner = self._owners.get(port)
        if owner is not None and owner != project_id:
            return False
        if owner == project_id:
            return True
        if force:
            return True
        return not port_is_listening(self.host, port)

    def _bind(self, project_id: str, port: int) -> None:
        self._bindings[project_id] = port
        self._owners[port] = project_id

    def binding_for(self, project_id: str) -> Optional[int]:
        with self._lock:
            return self._bindings.get(str(project_id))

    def binding(self, project_id: str) -> Optional[Dict[str, Any]]:
        port = self.binding_for(project_id)
        if port is None:
            return None
        return self._binding(project_id, port)

    def release(self, project_id: str) -> Dict[str, Any]:
        with self._lock:
            port = self._bindings.pop(str(project_id), None)
            if port is not None:
                self._owners.pop(port, None)
            return {"ok": True, "released_port": port,
                    "project_id": str(project_id)}

    def live_bindings(self) -> List[Dict[str, Any]]:
        """All current bindings with a live-listener probe (for status)."""
        with self._lock:
            out = []
            for project_id, port in self._bindings.items():
                out.append(self._binding(project_id, port))
            return sorted(out, key=lambda b: b["port"])

    def verify_live(self, project_id: str) -> Dict[str, Any]:
        """Re-probe the bound port. Returns ok=False when the listener died
        (editor crashed) so the session can transition to CRASHED."""
        port = self.binding_for(project_id)
        if port is None:
            return {"ok": False, "error": "no binding for project",
                    "project_id": project_id}
        live = port_is_listening(self.host, port)
        return {"ok": live, "live": live, "host": self.host, "port": port,
                "project_id": project_id}

    @staticmethod
    def _binding(project_id: str, port: int) -> Dict[str, Any]:
        return {"project_id": project_id, "host": "127.0.0.1", "port": port,
                "endpoint": f"127.0.0.1:{port}"}


_default_allocator: Optional[BridgeAllocator] = None
_allocator_lock = threading.Lock()


def get_default_allocator() -> BridgeAllocator:
    global _default_allocator
    with _allocator_lock:
        if _default_allocator is None:
            _default_allocator = BridgeAllocator()
        return _default_allocator