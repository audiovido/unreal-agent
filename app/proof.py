"""AvaLive proof serving — viewport-capture discovery and the /api/proof endpoints.

Ownership: the only mutable module state is the default project file, provided
by the composition root (served.py) via setup(). The endpoints are plain
handlers; served.py registers them on the FastAPI app so the public paths and
response shapes live where the rest of the routing lives.
"""
from __future__ import annotations

from pathlib import Path
from fastapi.responses import FileResponse

_PROJECT_FILE = None
_AVALIVE_PROOF_DIR = Path(r"C:/Users/Shadow/Desktop/AvaLive/AvaLive/Saved/UnrealAgent")


def setup(project_file):
    """Provide the default project file (uproject path) from the composition root."""
    global _PROJECT_FILE
    _PROJECT_FILE = Path(str(project_file))


def _proof_candidates():
    """Candidate viewport-capture dirs: the default project plus whichever
    project the live Unreal Bridge currently has open. The freshest real file
    wins, so proof follows the editor the agent actually operated on.
    """
    dirs = []
    try:
        dirs.append(_PROJECT_FILE.resolve().parent)
    except Exception:
        pass
    try:
        from tools.unreal.unreal_bridge import UnrealBridge
        identity = UnrealBridge(timeout=8).get_project_identity()
        info = identity.get("result") if isinstance(identity, dict) else None
        project_path = (info or {}).get("project_path")
        if project_path:
            dirs.append(Path(str(project_path)).resolve().parent)
    except Exception:
        pass
    return dirs


def _capture_dirs():
    """Capture dirs (…/Saved/UnrealAgent) for the default project plus whichever
    project the live Unreal Bridge currently has open."""
    return [d / "Saved" / "UnrealAgent" for d in _proof_candidates()]


def _proof_files(dirs, names=None):
    """Single source of truth: freshest non-empty viewport PNGs under the given
    capture dirs. names=None globs all *.png (AvaLive live feed); otherwise only
    the named capture files are considered (latest/status feeds).
    """
    files = []
    for capture_dir in dirs:
        try:
            candidates = [capture_dir / n for n in names] if names else capture_dir.glob("*.png")
            for candidate in candidates:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    files.append(candidate)
        except Exception:
            continue
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def proof_latest():
    """Serve the freshest Unreal viewport capture so the UI can show real
    proof of what the agent did (screenshot written by the bridge).
    """
    try:
        files = _proof_files(_capture_dirs(), ("viewport_latest.png", "pie_viewport_latest.png"))
        if files:
            return FileResponse(
                str(files[0]),
                media_type="image/png",
                headers={"Cache-Control": "no-store"},
            )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": False, "error": "no screenshot captured yet"}


def proof_live_status():
    """AvaLive-scoped PiP feed status: the chat UI always shows the MetaHuman
    viewport, never another editor's captures."""
    try:
        files = _proof_files([_AVALIVE_PROOF_DIR])
        if files:
            candidate = files[0]
            return {
                "ok": True,
                "path": str(candidate).replace("\\", "/"),
                "size": candidate.stat().st_size,
                "mtime": candidate.stat().st_mtime,
                "url": "/api/proof/live",
            }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": False, "error": "no AvaLive capture yet"}


def proof_live():
    """Serve the freshest AvaLive viewport capture for the chat PiP."""
    try:
        files = _proof_files([_AVALIVE_PROOF_DIR])
        if files:
            return FileResponse(
                str(files[0]),
                media_type="image/png",
                headers={"Cache-Control": "no-store"},
            )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": False, "error": "no AvaLive capture yet"}


def proof_status():
    """Return whether proof evidence exists and its path/size."""
    try:
        files = _proof_files(_capture_dirs(), ("viewport_latest.png", "pie_viewport_latest.png"))
        if files:
            candidate = files[0]
            return {
                "ok": True,
                "path": str(candidate).replace("\\", "/"),
                "size": candidate.stat().st_size,
                "mtime": candidate.stat().st_mtime,
                "url": "/api/proof/latest",
            }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": False, "error": "no screenshot captured yet"}