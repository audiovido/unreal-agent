"""editor_lease.py — exclusive Unreal editor ownership/lease (Lane B, Part 6).

A pure, editor-independent lease registry keyed by **canonical project /
editor identity** (never just a port).  Semantics:

* A MUTATING task must hold the exclusive mutating lease before touching an
  editor.  Only one mutating lease per identity may be live at a time.
* READ-ONLY inspection never needs exclusivity: any number of read-only
  watchers may coexist and never overwrite the mutating lease.
* A mutating acquire against a live mutating lease returns a structured
  BUSY/OWNED response (owner_id, task_id, expires_at, expires_in_s).
* Leases self-expire; renew()/heartbeat keep them alive.
* A dead/stale owner is recovered automatically by the next acquire once
  the lease expired; force_release() clears immediately.  A crash can
  never lock the editor forever (persistence + expiry bound it).

Storage: one JSON file per identity under config/leases/ (schema v2).
Cross-process access is serialised with an O_EXCL lock file.

Integration API for Worker A (NOT wired into the product pipeline here):

    from core.editor_lease import LeaseRegistry
    reg = LeaseRegistry()                      # default config/leases
    reg.acquire(project_identity, owner_id, task_id)      # exclusive
    reg.acquire(..., read_only=True)           # concurrent inspector
    reg.renew(identity, owner_id); reg.release(identity, owner_id)
    reg.status(identity); reg.force_release(identity); reg.list_leases()
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import app_config

DEFAULT_LEASE_S = 120.0
_LOCK_TIMEOUT_S = 5.0


def canonical_identity(project_identity: Any) -> str:
    """One key per project/editor, normalised across path flavours."""
    if project_identity is None:
        raise ValueError("project_identity is required")
    if isinstance(project_identity, str):
        raw = project_identity
    elif isinstance(project_identity, dict):
        raw = (project_identity.get("project_path")
               or project_identity.get("uproject_path")
               or project_identity.get("project_name")
               or "")
    else:
        raise TypeError(f"unsupported project_identity: {type(project_identity)}")
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("project_identity has no usable path/name")
    return raw.replace("\\", "/").casefold().rstrip("/")


class _FileLock:
    """Small O_EXCL spin lock so two processes cannot corrupt one lease."""

    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def __enter__(self) -> "_FileLock":
        deadline = time.time() + _LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                if time.time() > deadline:
                    try:
                        self.path.unlink()  # stale lock -> steal
                    except OSError:
                        pass
                    deadline = time.time() + _LOCK_TIMEOUT_S
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if self._held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def _now_epoch() -> float:
    return time.time()


def _lease_doc(owner_id: str, task_id: str, now: float, lease_s: float,
               read_only: bool) -> Dict[str, Any]:
    return {
        "owner_id": owner_id,
        "task_id": task_id,
        "read_only": bool(read_only),
        "mutating": not read_only,
        "acquired_at": round(now, 3),
        "heartbeat_at": round(now, 3),
        "lease_s": float(lease_s),
        "expires_at": round(now + float(lease_s), 3),
    }


class LeaseRegistry:
    """Persisted, thread-safe lease store for one product instance."""

    def __init__(self, lease_dir: Optional[Path] = None,
                 clock: Optional[Any] = None):
        self.dir = Path(lease_dir) if lease_dir else Path(app_config.LEASE_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock if clock is not None else time
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ---------------- storage ----------------------------------------------
    def _path(self, key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        return self.dir / f"{safe}.json"

    def _read(self, key: str) -> Optional[Dict[str, Any]]:
        """Authoritative read: the on-disk record is ALWAYS the truth so
        separate registry instances (separate product processes) never serve
        a stale in-memory view of who owns the editor.  _mem is kept only as
        a session-local write log for list_leases bookkeeping."""
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_locked(self, key: str, rec: Dict[str, Any]) -> None:
        """Persist one record.  Caller must already hold the per-identity
        file lock (or the in-process lock) when a read-modify-write must be
        atomic across registry instances."""
        self._mem[key] = dict(rec)
        p = self._path(key)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.dir), prefix=p.stem + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2)
            os.replace(tmp_name, str(p))
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def _write(self, key: str, rec: Dict[str, Any]) -> None:
        with _FileLock(self._path(key).with_suffix(".lock")):
            self._write_locked(key, rec)

    def _delete(self, key: str) -> None:
        self._mem.pop(key, None)
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            pass

    # ---------------- helpers ----------------------------------------------
    def _now(self) -> float:
        return float(self._clock.time())

    @staticmethod
    def _expired(doc: Optional[Dict[str, Any]], now: float) -> bool:
        return bool(doc is None or now >= float(doc.get("expires_at") or 0.0))

    @staticmethod
    def _prune(rec: Dict[str, Any], now: float) -> Dict[str, Any]:
        """Drop expired read-only watchers in place and return the record."""
        watchers = [w for w in rec.get("read_only", [])
                    if now < float(w.get("expires_at") or 0.0)]
        rec["read_only"] = watchers
        if rec.get("mutating") and LeaseRegistry._expired(
                rec.get("mutating"), now):
            rec["mutating"] = None
        return rec

    def _blank(self, key: str) -> Dict[str, Any]:
        return {"schema": "ua.lease.v2", "identity": key,
                "mutating": None, "read_only": []}

    # ---------------- core ops ---------------------------------------------
    def acquire(self, project_identity: Any, owner_id: str, task_id: str,
                lease_s: float = DEFAULT_LEASE_S,
                read_only: bool = False) -> Dict[str, Any]:
        """Request ownership.  read_only inspectors never conflict with
        anyone; a mutating acquire is exclusive per identity."""
        key = canonical_identity(project_identity)
        if not owner_id:
            raise ValueError("owner_id is required")
        with self._lock:
            now = self._now()
            # The whole read-check-write must be atomic ACROSS registry
            # instances (two product processes racing for a free identity), so
            # the per-identity file lock wraps the critical section, not just
            # the final write.  Returns inside the `with` release the lock.
            with _FileLock(self._path(key).with_suffix(".lock")):
                raw = self._read(key) or self._blank(key)
                rec = self._prune(dict(raw), now)

                if not read_only:
                    cur = rec.get("mutating")
                    if cur is not None:
                        return {
                            "ok": False,
                            "conflict": {
                                "owner_id": cur.get("owner_id"),
                                "task_id": cur.get("task_id"),
                                "expires_at": round(float(cur.get("expires_at") or 0), 3),
                                "expires_in_s": round(
                                    float(cur.get("expires_at") or 0) - now, 2),
                                "read_only": False,
                            },
                            "identity": key,
                            "lease": None,
                        }
                    stale = rec.get("mutating") is None and \
                        (raw.get("mutating") is not None)
                    doc = _lease_doc(owner_id, task_id, now, lease_s,
                                     read_only=False)
                    doc["recovered_stale"] = bool(stale)
                    rec["mutating"] = doc
                else:
                    watchers = rec.setdefault("read_only", [])
                    watchers.append(_lease_doc(owner_id, task_id, now, lease_s,
                                               read_only=True))
                self._write_locked(key, rec)
                return {"ok": True,
                        "lease": rec.get("mutating") or
                        (rec.get("read_only") or [])[-1],
                        "identity": key, "conflict": None}

    def renew(self, project_identity: Any, owner_id: str,
              lease_s: Optional[float] = None) -> Dict[str, Any]:
        """Heartbeat: extend the owner's lease (mutating or read-only)."""
        key = canonical_identity(project_identity)
        with self._lock:
            now = self._now()
            rec = self._read(key) or self._blank(key)
            rec = self._prune(dict(rec), now)
            targets = []
            if rec.get("mutating"):
                targets.append(rec["mutating"])
            targets += rec.get("read_only", [])
            mine = [t for t in targets if t.get("owner_id") == owner_id]
            if not mine:
                return {"ok": False,
                        "error": "lease not owned by this owner",
                        "identity": key}
            for t in mine:
                if now >= float(t.get("expires_at") or 0.0):
                    return {"ok": False,
                            "error": "lease already expired; re-acquire",
                            "identity": key}
                t["heartbeat_at"] = round(now, 3)
                t["expires_at"] = round(
                    now + float(lease_s or t.get("lease_s")
                                or DEFAULT_LEASE_S), 3)
            self._write(key, rec)
            return {"ok": True, "lease": dict(mine[-1]), "identity": key}

    def release(self, project_identity: Any, owner_id: str) -> Dict[str, Any]:
        key = canonical_identity(project_identity)
        with self._lock:
            rec = self._read(key)
            if not rec:
                return {"ok": True, "note": "no lease present",
                        "identity": key}
            rec = self._prune(dict(rec), self._now())
            owner_of_other = False
            if rec.get("mutating") and \
                    rec["mutating"].get("owner_id") == owner_id:
                rec["mutating"] = None
                self._write(key, rec)
                return {"ok": True, "released_owner": owner_id,
                        "identity": key, "kind": "mutating"}
            watchers = [w for w in rec.get("read_only", [])
                        if w.get("owner_id") != owner_id]
            removed = len(watchers) != len(rec.get("read_only", []))
            rec["read_only"] = watchers
            if removed:
                self._write(key, rec)
                return {"ok": True, "released_owner": owner_id,
                        "identity": key, "kind": "read_only"}
            other = rec.get("mutating") or (rec.get("read_only") or [None])[0]
            if other and other.get("owner_id") != owner_id:
                return {"ok": False,
                        "error": f"lease owned by {other.get('owner_id')}, "
                        f"not {owner_id}",
                        "identity": key}
            return {"ok": True, "note": "nothing owned", "identity": key}

    def force_release(self, project_identity: Any,
                      reason: str = "manual override") -> Dict[str, Any]:
        key = canonical_identity(project_identity)
        with self._lock:
            cur = self._read(key)
            self._delete(key)
            return {"ok": True, "released": cur, "reason": reason,
                    "identity": key}

    def status(self, project_identity: Any) -> Dict[str, Any]:
        key = canonical_identity(project_identity)
        with self._lock:
            now = self._now()
            raw = self._read(key)
            if not raw:
                return {"ok": True, "identity": key, "owned": False,
                        "lease": None, "owner_id": None, "expired": False,
                        "read_only_watchers": 0, "mutating": None}
            raw_mut = raw.get("mutating")
            expired_raw = self._expired(raw_mut, now)
            rec = self._prune(dict(raw), now)
            mut = rec.get("mutating")
            mut_live = mut is not None
            watchers_live = bool(rec.get("read_only"))
            return {"ok": True, "identity": key,
                    "owned": mut_live or watchers_live,
                    "mutating": dict(mut) if mut else None,
                    "owner_id": (mut or {}).get("owner_id"),
                    "task_id": (mut or {}).get("task_id"),
                    "read_only_watchers": len(rec.get("read_only", [])),
                    "expires_at": round(
                        float((raw_mut or {}).get("expires_at") or 0.0), 3),
                    "expires_in_s": round(
                        max(0.0, float((raw_mut or {}).get("expires_at") or 0.0)
                            - now), 2),
                    "expired": expired_raw,
                    "stale_recoverable": expired_raw}

    def list_leases(self) -> List[Dict[str, Any]]:
        """Disk-truth view (files only) — the same view every registry
        instance sees, regardless of which process wrote the lease."""
        out: List[Dict[str, Any]] = []
        seen: Dict[str, bool] = {}
        for p in sorted(self.dir.glob("*.json")):
            if p.name.endswith((".lock", ".tmp")):
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(rec, dict) or not rec.get("identity"):
                continue
            self._flatten(rec, out, seen)
        return out

    @staticmethod
    def _flatten(rec: Dict[str, Any], out: List[Dict[str, Any]],
                 seen: Dict[str, bool]) -> None:
        key = rec.get("identity")
        if rec.get("mutating"):
            doc = dict(rec["mutating"])
            doc["identity"] = key
            if key not in seen:
                out.append(doc)
                seen[key] = True
        for w in rec.get("read_only", []):
            doc = dict(w)
            doc["identity"] = key
            if (key, doc.get("owner_id")) not in seen:
                out.append(doc)
                seen[(key, doc.get("owner_id"))] = True
