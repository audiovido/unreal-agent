"""
Durable Active Project Context for Unreal Agent.

The active project is the single most important piece of ambient state an
autonomous Unreal task depends on. It must survive backend restarts, Freebuff
restarts, Unreal Editor restarts and execution retries.

This module owns ONE source of truth for that context and drives the resolution
priority chain that turns "inspect_project with no path" into a real, verified
project instead of an immediate "uproject not found":

    1. explicit project_path in the current task payload
    2. persisted ActiveProjectContext
    3. currently open Unreal Editor project (live bridge identity)
    4. last successfully opened/created project
    5. known project registry
    6. safe (bounded) search of allowed roots for *.uproject

Only when every source fails does resolution report PROJECT_CONTEXT_MISSING.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ACTIVE_CONTEXT_FILE = ROOT / "memory" / "active_project_context.json"

# Fixed high-probability projects we know about. Tried before any open-ended
# disk scan so resolution stays fast and deterministic in the common case.
KNOWN_PROJECT_PATHS = [
    Path(r"C:\Users\Shadow\Desktop\AvaLive\AvaLive\AvaLive.uproject"),
    Path(r"C:\Users\Shadow\Desktop\AvaLive\AvaLive.uproject"),
    Path(r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject"),
]

# Allowed roots for the bounded last-resort search. Real-time OS shells and
# engine directories are intentionally excluded.
def _default_search_roots():
    home = Path.home()
    roots = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    # Known product root regardless of notebook home location.
    desktop = home / "Desktop"
    for candidate in (
        desktop / "app",
        desktop / "AvaLive",
    ):
        if candidate not in roots:
            roots.append(candidate)
    return roots


SEARCH_DEPTH = 4

CONTEXT_FIELDS = (
    "project_name",
    "uproject_path",
    "project_root",
    "engine_version",
    "bridge_project_name",
    "bridge_project_path",
    "last_verified_at",
    "source_of_truth",
    "validity",
    "active_map_path",
)


# ============================================================
# PERSISTENCE
# ============================================================

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_active_context():
    """Load the durable Active Project Context, or an empty skeleton.

    Never raises: a corrupted/missing file yields an empty, recoverable context
    identical to a fresh backend after restart.
    """
    empty = {field: None for field in CONTEXT_FIELDS}
    if not ACTIVE_CONTEXT_FILE.exists():
        return empty
    try:
        data = json.loads(ACTIVE_CONTEXT_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return empty
        ctx = {field: data.get(field) for field in CONTEXT_FIELDS}
        ctx["_file"] = str(ACTIVE_CONTEXT_FILE)
        return ctx
    except Exception:
        return empty


def save_active_context(ctx):
    """Atomically persist the Active Project Context to disk (durable)."""
    payload = {}
    for field in CONTEXT_FIELDS:
        if field in ctx:
            payload[field] = ctx[field]
    ACTIVE_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload["saved_at"] = _now_iso()
    tmp = ACTIVE_CONTEXT_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(ACTIVE_CONTEXT_FILE)
    if "_file" not in ctx:
        ctx["_file"] = str(ACTIVE_CONTEXT_FILE)
    return ctx


def clear_active_context():
    try:
        ACTIVE_CONTEXT_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return load_active_context()


# ============================================================
# CONTEXT UPDATE
# ============================================================

def _normalized(value):
    return str(value or "").replace("\\", "/")


def read_engine_version(uproject_path):
    try:
        data = json.loads(Path(uproject_path).read_text(encoding="utf-8-sig"))
        engine = data.get("EngineAssociation")
        if engine:
            return str(engine)
    except Exception:
        pass
    return None


def update_active_context(
    *,
    uproject_path=None,
    project_name=None,
    engine_version=None,
    source_of_truth="persisted",
    bridge_project_name=None,
    bridge_project_path=None,
    active_map_path=None,
):
    """Refresh the durable context from a confirmed project and save it.

    Returns the persisted context. Call after create/open/bridge-connect/
    inspect success so the context is always current and survives restarts.
    """
    ctx = load_active_context()

    if uproject_path:
        p = Path(uproject_path).resolve()
        ctx["uproject_path"] = str(p)
        ctx["project_root"] = str(p.parent)
        ctx["project_name"] = project_name or p.stem
        if not ctx.get("engine_version"):
            ctx["engine_version"] = read_engine_version(p)

    if project_name:
        ctx["project_name"] = project_name

    if engine_version:
        ctx["engine_version"] = engine_version

    if bridge_project_path:
        ctx["bridge_project_path"] = _normalized(bridge_project_path)
    if bridge_project_name:
        ctx["bridge_project_name"] = bridge_project_name
    if active_map_path:
        ctx["active_map_path"] = _normalized(active_map_path)

    ctx["source_of_truth"] = source_of_truth
    ctx["last_verified_at"] = _now_iso()
    ctx["validity"] = "valid"
    return save_active_context(ctx)


# ============================================================
# RESOLUTION PRIORITY CHAIN
# ============================================================

def _is_nonempty_path(value):
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    lowered = text.lower()
    if any(t in lowered for t in (
        "/path/to/", "path/to/your", "placeholder", "<project",
        "your_project", "/game/",
    )):
        return False
    return text.endswith(".uproject")


def _strict_exists(value):
    try:
        return Path(value).resolve().is_file()
    except Exception:
        return False


def _bounded_search(roots=None, max_depth=SEARCH_DEPTH):
    if roots is None:
        roots = _default_search_roots()
    found = []
    seen = set()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            cur, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                entries = list(cur.iterdir())
            except Exception:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        stack.append((entry, depth + 1))
                    elif entry.suffix.lower() == ".uproject":
                        key = str(entry.resolve()).casefold()
                        if key not in seen:
                            seen.add(key)
                            found.append(str(entry.resolve()))
                except Exception:
                    continue
    return sorted(found)


def resolve_active_project(requested_path=None, bridge=None, max_candidates=6):
    """Resolve the active project .uproject through the priority chain.

    Returns:
        {"ok": True, "uproject_path": str, "source_of_truth": str,
         "context": {...}}
      or
        {"ok": False, "code": "PROJECT_CONTEXT_MISSING", "requested_path": ...,
         "persisted_context": {...}, "bridge_context": {...},
         "candidates": [...], "recoverable": True}
    """
    persisted = load_active_context()
    bridge_ctx = {}

    # 1. Explicit path in the payload. Honored when it resolves to a real file.
    if _strict_exists(requested_path):
        return {
            "ok": True,
            "uproject_path": str(Path(requested_path).resolve()),
            "source_of_truth": "explicit",
            "bridge_context": _live_bridge_context(bridge),
            "context": persisted,
        }

    # 2. Persisted ActiveProjectContext (validate the .uproject still exists).
    persisted_path = persisted.get("uproject_path")
    if _strict_exists(persisted_path):
        return {
            "ok": True,
            "uproject_path": str(Path(persisted_path).resolve()),
            "source_of_truth": "persisted",
            "bridge_context": _live_bridge_context(bridge),
            "context": persisted,
        }

    # 3. Currently open Unreal Editor project via the live bridge.
    bridge_ctx = _live_bridge_context(bridge)
    bridge_path = (
        bridge_ctx.get("project_path")
        or bridge_ctx.get("result", {}).get("project_path")
    )
    if bridge_path and _strict_exists(bridge_path):
        return {
            "ok": True,
            "uproject_path": str(Path(bridge_path).resolve()),
            "source_of_truth": "bridge",
            "bridge_context": bridge_ctx,
            "context": persisted,
        }

    # 4. Last successfully opened/created project (bridge report path).
    last_opened = persisted.get("bridge_project_path")
    if last_opened and _strict_exists(last_opened):
        return {
            "ok": True,
            "uproject_path": str(Path(last_opened).resolve()),
            "source_of_truth": "last_opened",
            "bridge_context": bridge_ctx,
            "context": persisted,
        }

    # 5. Known project registry.
    for candidate in KNOWN_PROJECT_PATHS:
        if _strict_exists(candidate):
            return {
                "ok": True,
                "uproject_path": str(candidate.resolve()),
                "source_of_truth": "registry",
                "bridge_context": bridge_ctx,
                "context": persisted,
            }

    # 6. Safe bounded search of allowed roots for *.uproject.
    candidates = _bounded_search()
    if candidates:
        chosen = candidates[0]
        return {
            "ok": True,
            "uproject_path": chosen,
            "source_of_truth": "search",
            "bridge_context": bridge_ctx,
            "context": persisted,
        }

    return {
        "ok": False,
        "code": "PROJECT_CONTEXT_MISSING",
        "requested_path": requested_path,
        "persisted_context": persisted,
        "bridge_context": bridge_ctx,
        "candidates": candidates[:max_candidates],
        "recoverable": True,
    }


def _live_bridge_context(bridge):
    """Pull the currently open project identity from the live bridge.

    Falls back to the persisted bridge identity when the bridge is not
    reachable or the pull fails. Uses the lazily-imported bridge binding.
    """
    identity = {}
    if bridge is None:
        try:
            from tools.unreal.unreal_bridge import UnrealBridge
            bridge = UnrealBridge(host="127.0.0.1", port=6766, timeout=8)
        except Exception:
            bridge = None
    if bridge is not None:
        try:
            result = bridge.get_project_identity()
            if isinstance(result, dict) and result.get("ok"):
                inner = result.get("result")
                if isinstance(inner, dict) and inner.get("ok"):
                    identity = {
                        "project_path": inner.get("project_path"),
                        "project_name": inner.get("project_name"),
                        "engine": inner.get("engine"),
                    }
            elif isinstance(result, dict) and result.get("result"):
                inner = result["result"]
                if isinstance(inner, dict):
                    identity = dict(inner)
        except Exception:
            identity = {}
    return identity


def _preferred_live_project():
    """Ordered list of verified candidate paths from bridge + persisted state."""
    persisted = load_active_context()
    resolved = resolve_active_project()
    if resolved.get("ok"):
        return [resolved["uproject_path"]]
    candidates = []
    bridge_ctx = resolved.get("bridge_context") or {}
    bp = bridge_ctx.get("project_path")
    if bp and _strict_exists(bp):
        candidates.append(str(Path(bp).resolve()))
    ppp = persisted.get("uproject_path")
    if ppp and _strict_exists(ppp):
        candidates.append(str(Path(ppp).resolve()))
    return candidates