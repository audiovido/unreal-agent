"""proof_store.py — session-isolated proof storage (Phase 8).

Every proof lives under:

    assetlib/proof/product/{session_id}/{execution_id}/...

and each proof file is accompanied by proof.json recording:
    session_id, project_id, execution_id, unreal_pid, bridge identity,
    timestamp, sha256 hash, source path.

Isolation is enforced at the API boundary: ProofStore.list() and resolve()
accept a session_id and refuse to walk outside that session's tree, so proof
from Project B can never satisfy execution A and vice versa.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import app_config

DEFAULT_PROOF_ROOT = Path(app_config.PROOF_DIR)  # assetlib/proof/product


def _sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _safe_segment(value: str) -> str:
    """Sanitize a path segment (session/execution ids)."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_"
                   for ch in str(value or ""))


class ProofStore:
    """Isolated proof tree for one product instance."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DEFAULT_PROOF_ROOT

    # -- paths -----------------------------------------------------------------
    def execution_dir(self, session_id: str, execution_id: str) -> Path:
        return (self.root / _safe_segment(session_id)
                / _safe_segment(execution_id))

    def session_dir(self, session_id: str) -> Path:
        return self.root / _safe_segment(session_id)

    # -- write -----------------------------------------------------------------
    def record(
        self,
        session_id: str,
        execution_id: str,
        source_paths: List[str],
        *,
        project_id: str = "",
        unreal_pid: Optional[int] = None,
        bridge_host: str = "127.0.0.1",
        bridge_port: Optional[int] = None,
        engine_version: str = "",
        active_map: str = "",
    ) -> Dict[str, Any]:
        """Copy capture PNGs into the session/execution tree and write
        proof.json metadata. Returns the recorded proof manifest."""
        out_dir = self.execution_dir(session_id, execution_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        recorded: List[Dict[str, Any]] = []
        for src in (source_paths or []):
            p = Path(str(src))
            if not p.is_file() or p.suffix.lower() not in (".png", ".jpg",
                                                           ".jpeg"):
                continue
            if p.stat().st_size <= 0:
                continue
            name = f"proof_{len(recorded) + 1:02d}{p.suffix.lower()}"
            target = out_dir / name
            try:
                shutil.copy2(p, target)
            except OSError:
                continue
            recorded.append({
                "name": name,
                "source": str(p).replace("\\", "/"),
                "size": target.stat().st_size,
                "sha256": _sha256(target),
                "url": self.url(session_id, execution_id, name),
            })
        if not recorded:
            return {"ok": False, "error": "no capturable proof files",
                    "recorded": []}
        manifest = {
            "schema": "ua.proof.v1",
            "session_id": session_id,
            "project_id": project_id,
            "execution_id": execution_id,
            "unreal_pid": unreal_pid,
            "bridge_identity": {
                "host": bridge_host, "port": bridge_port,
                "endpoint": (f"{bridge_host}:{bridge_port}"
                             if bridge_port else None),
            },
            "engine_version": engine_version,
            "active_map": active_map,
            "created_at": time.time(),
            "proof_id": uuid.uuid4().hex,
            "files": recorded,
        }
        manifest_path = out_dir / "proof.json"
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
        tmp.replace(manifest_path)
        return {"ok": True, "directory": str(out_dir).replace("\\", "/"),
                "proof_id": manifest["proof_id"],
                "files": recorded, "manifest": manifest}

    # -- read (fail closed on cross-session access) -------------------------------
    def list(self, session_id: str,
             execution_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Proof records for ONE session only. Any path outside the session
        tree is refused (session_id is sanitized before any traversal)."""
        base = self.session_dir(session_id)
        if not base.is_dir():
            return []
        out: List[Dict[str, Any]] = []
        for mf in base.glob("*/proof.json"):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("session_id") != session_id:
                continue  # foreign manifest: never returned
            if execution_id and data.get("execution_id") != execution_id:
                continue
            out.append(data)
        out.sort(key=lambda m: m.get("created_at") or 0.0, reverse=True)
        return out

    def files(self, session_id: str,
              execution_id: str) -> List[Dict[str, Any]]:
        manifests = self.list(session_id, execution_id)
        return list(manifests[0].get("files", [])) if manifests else []

    def resolve(self, session_id: str, execution_id: str,
                name: str) -> Optional[Path]:
        """Resolve one proof file, path-traversal safe and session-bound."""
        safe_name = Path(name).name
        p = (self.execution_dir(session_id, execution_id) / safe_name).resolve()
        base = self.execution_dir(session_id, execution_id).resolve()
        if base not in p.parents or not p.is_file():
            return None
        return p

    def url(self, session_id: str, execution_id: str, name: str) -> str:
        return (f"/api/sessions/{_safe_segment(session_id)}/proof/"
                f"{_safe_segment(execution_id)}/{Path(name).name}")


_default_store: Optional[ProofStore] = None
_store_lock = threading.Lock()


def get_default_store() -> ProofStore:
    global _default_store
    with _store_lock:
        if _default_store is None:
            _default_store = ProofStore()
        return _default_store