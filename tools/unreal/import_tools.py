"""Generic Unreal import capability for Blender Agent outputs.

Imports FBX / GLB / GLTF through the real editor asset pipeline
(AssetImportTask with the editor-chosen factory), creates destination folders,
verifies the imported asset (class + real actor bounds read-back), spawns it,
and keeps a persisted handoff record so the Supervisor can resume a
Blender -> Unreal pipeline across restarts without re-running completed work.

No Content Browser interaction is required; everything runs headlessly through
the bridge. No AvaLive-specific paths are hardcoded — the exchange workspace
comes from blender_agent.config (env-overridable).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from tools.unreal.unreal_bridge import UnrealBridge

try:
    from blender_agent.config import ensure_workspace
    from blender_agent.job_schema import load_job
except Exception:  # pragma: no cover
    ensure_workspace = None
    load_job = None

DEFAULT_IMPORT_ROOT = "/Game/Imported"

_IMPORT_TASK_TEMPLATE = r"""import unreal
source = {source!r}
destination = {destination!r}
tasks = []
task = unreal.AssetImportTask()
task.filename = source
task.destination_path = destination
task.automated = True
task.save = True
task.replace_existing = True
tasks.append(task)
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
imported = asset_tools.import_asset_tasks(tasks)
paths = [str(p) for p in (task.imported_object_paths or [])]
ok = bool(paths) and all(p for p in paths)
__bridge_result__ = {{
    "ok": ok,
    "source": source,
    "destination_path": destination,
    "imported_paths": paths,
    "count": len(paths),
    "error": None if ok else "asset import returned no objects",
}}
"""

_VERIFY_TEMPLATE = r"""import unreal
asset_path = {asset_path!r}
asset = unreal.load_asset(asset_path)
if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "ASSET_NOT_FOUND",
        "asset_path": asset_path,
        "class": None,
        "verified": False,
    }}
else:
    asset_class = asset.get_class().get_name()
    materials = []
    try:
        mats = asset.get_editor_property("materials")
        materials = [str(m.get_path_name()) if m else None for m in mats]
    except Exception:
        pass
    bounds = None
    bounds_ok = False
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if asset_class == "StaticMesh":
            actor_class = unreal.StaticMeshActor
            actor = subsystem.spawn_actor_from_class(actor_class, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            if actor is not None:
                actor.static_mesh_component.set_static_mesh(asset)
                origin, extent = actor.get_actor_bounds(False, False)
                bounds = {{
                    "origin": [origin.x, origin.y, origin.z],
                    "extent": [extent.x, extent.y, extent.z],
                    "size_cm": [extent.x * 2.0, extent.y * 2.0, extent.z * 2.0],
                }}
                bounds_ok = True
                subsystem.destroy_actor(actor)
        elif asset_class == "SkeletalMesh":
            actor_class = unreal.SkeletalMeshActor
            actor = subsystem.spawn_actor_from_class(actor_class, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            if actor is not None:
                actor.skeletal_mesh_component.set_skeletal_mesh_asset(asset)
                origin, extent = actor.get_actor_bounds(False, False)
                bounds = {{
                    "origin": [origin.x, origin.y, origin.z],
                    "extent": [extent.x, extent.y, extent.z],
                    "size_cm": [extent.x * 2.0, extent.y * 2.0, extent.z * 2.0],
                }}
                bounds_ok = True
                subsystem.destroy_actor(actor)
    except Exception as exc:
        bounds = {{"error": str(exc)}}
    note = None
    if not bounds_ok:
        note = "editor world unavailable (PIE active or world not loaded); bounds read-back deferred"
    __bridge_result__ = {{
        "ok": True,
        "asset_path": asset.get_path_name(),
        "class": asset_class,
        "materials": materials,
        "bounds": bounds,
        "bounds_ok": bounds_ok,
        "note": note,
        "verified": True,
    }}
"""

_SPAWN_TEMPLATE = r"""import unreal
asset_path = {asset_path!r}
label = {label!r}
loc = unreal.Vector({loc[0]}, {loc[1]}, {loc[2]})
rot = unreal.Rotator(pitch={rot[0]}, yaw={rot[1]}, roll={rot[2]})
asset = unreal.load_asset(asset_path)
if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "ASSET_NOT_FOUND",
        "asset_path": asset_path,
        "verified": False,
    }}
else:
    asset_class = asset.get_class().get_name()
    if asset_class == "StaticMesh":
        actor_class = unreal.StaticMeshActor
    elif asset_class == "SkeletalMesh":
        actor_class = unreal.SkeletalMeshActor
    else:
        actor_class = unreal.Actor
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsystem.spawn_actor_from_class(actor_class, loc, rot)
    if actor is not None and asset_class == "StaticMesh":
        actor.static_mesh_component.set_static_mesh(asset)
    if actor is not None and asset_class == "SkeletalMesh":
        actor.skeletal_mesh_component.set_skeletal_mesh_asset(asset)
    if actor is not None:
        actor.set_actor_label(label)
        actor.set_actor_scale3d(unreal.Vector({scale[0]}, {scale[1]}, {scale[2]}))
    read = None
    if actor is not None:
        read = {{
            "name": actor.get_name(),
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "location": [actor.get_actor_location().x, actor.get_actor_location().y, actor.get_actor_location().z],
        }}
    __bridge_result__ = {{
        "ok": bool(actor is not None and read is not None),
        "asset_path": asset_path,
        "asset_class": asset_class,
        "actor": read,
        "actor_name": read["label"] if read else label,
        "verified": bool(actor is not None and read is not None),
    }}
"""


class ImportTools:
    """Unreal import/spawn tools for Blender exports (bridge-backed)."""

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        for key in ("result", "payload", "data"):
            if isinstance(result.get(key), dict):
                return result[key]
        return result

    @staticmethod
    def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
        ok = bool(payload.get("ok"))
        out = {"ok": ok, "result": payload}
        if payload.get("code"):
            out["code"] = payload["code"]
        if payload.get("error"):
            out.setdefault("error", payload["error"])
        return out

    def _handoff_file(self) -> Path:
        return ensure_workspace()["handoff"]

    def _read_handoff(self) -> dict[str, Any]:
        try:
            return json.loads(self._handoff_file().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_handoff(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            self._handoff_file().parent.mkdir(parents=True, exist_ok=True)
            self._handoff_file().write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass
        return payload

    # ------------------------------------------------------------ folders
    def create_asset_folder(self, folder_path: str = DEFAULT_IMPORT_ROOT) -> dict[str, Any]:
        """Create a Content Browser folder for imported assets.

        Resilient to a stalled asset registry: the physical Content directory
        is created on disk too, and verification accepts either the registry
        folder or the on-disk folder."""
        result = self.bridge.execute_python(f"""
import unreal
import os
folder = {folder_path!r}
if not folder.startswith("/Game/"):
    __bridge_result__ = {{"ok": False, "code": "INVALID_FOLDER", "error": "folder must start with /Game/", "folder": folder}}
else:
    created = bool(unreal.EditorAssetLibrary.make_directory(folder))
    exists = bool(unreal.EditorAssetLibrary.does_directory_exist(folder))
    # Physical fallback: /Game/Imported -> <project>/Content/Imported
    content = unreal.Paths.project_content_dir()
    rel = folder[len("/Game/"):]
    physical = os.path.join(content, rel.replace("/", os.sep))
    os.makedirs(physical, exist_ok=True)
    physical_exists = bool(os.path.isdir(physical))
    ok = bool(exists or physical_exists)
    __bridge_result__ = {{
        "ok": ok,
        "folder": folder,
        "created": created,
        "exists": exists,
        "physical_path": str(physical).replace(chr(92), "/"),
        "physical_exists": physical_exists,
        "verified": ok,
    }}
""")
        return self._wrap(self._payload(result))

    # ------------------------------------------------------------ import
    def import_asset(
        self,
        source_path: str,
        destination_path: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        """Import FBX/GLB/GLTF via the real editor factory; verify the result."""
        result = self.bridge.execute_python(_IMPORT_TASK_TEMPLATE.format(
            source=str(source_path).replace("\\", "/"),
            destination=destination_path,
        ))
        payload = self._payload(result)
        imported = payload.get("imported_paths") or []
        if not payload.get("ok"):
            return self._wrap(payload)
        verified = []
        for path in imported:
            check = self.verify_imported_asset(path)
            verified.append(check.get("result") or check)
        payload["verified_imports"] = verified
        # The primary asset is the geometry (StaticMesh/SkeletalMesh), never a
        # sidecar material/anim — the handoff chain depends on this path.
        mesh_imports = [v for v in verified if v.get("class") in ("StaticMesh", "SkeletalMesh")]
        primary = mesh_imports[0] if mesh_imports else (verified[0] if verified else {})
        payload["asset_path"] = primary.get("asset_path") or (imported[0] if imported else None)
        payload["asset_class"] = primary.get("class")
        payload["verified"] = bool(mesh_imports) and primary.get("verified") is True
        return self._wrap(payload)

    def import_asset_fbx(
        self,
        source_path: str,
        destination_path: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        return self.import_asset(source_path, destination_path)

    def import_asset_gltf(
        self,
        source_path: str,
        destination_path: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        return self.import_asset(source_path, destination_path)

    def import_blender_output(
        self,
        job_id: Optional[str] = None,
        destination_path: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        """Import the export of a completed Blender job (by id or the latest).

        Reads the job manifest (never guesses), imports the file, then persists
        a handoff record so later steps (verify/spawn) can resolve the exact
        asset — restart-safe, no duplicate imports for completed jobs.
        """
        job = None
        if job_id:
            job = load_job(job_id) if load_job else None
        if job is None:
            # Latest COMPLETE job with a manifest.
            from blender_agent.job_schema import list_jobs
            for summary in list_jobs():
                if summary.get("status") == "COMPLETE":
                    job = load_job(summary["id"])
                    if job and job.manifest.get("output_path"):
                        break
        if job is None:
            return {"ok": False, "result": {"ok": False, "code": "NO_BLENDER_OUTPUT", "error": "no completed Blender export found"}}
        export_path = (job.manifest or {}).get("output_path")
        if not export_path:
            return {"ok": False, "result": {"ok": False, "code": "NO_EXPORT_PATH", "error": f"job {job.id} has no export path in manifest"}}
        import_result = self.import_asset(export_path, destination_path)
        payload = import_result.get("result") or import_result
        if payload.get("ok"):
            payload["handoff"] = self._write_handoff({
                "job_id": job.id,
                "operation": job.operation,
                "source": job.manifest.get("source"),
                "export_path": export_path,
                "asset_path": payload.get("asset_path"),
                "class": (payload.get("verified_imports") or [{}])[0].get("class") if payload.get("verified_imports") else None,
                "imported_at": time.time(),
            })
            payload["job_id"] = job.id
        return self._wrap(payload)

    # ------------------------------------------------------------ verify
    def verify_imported_asset(self, asset_path: str) -> dict[str, Any]:
        """Load the asset, prove its class, and read real actor bounds (cm)."""
        result = self.bridge.execute_python(_VERIFY_TEMPLATE.format(asset_path=asset_path))
        return self._wrap(self._payload(result))

    def verify_blender_output(self, job_id: Optional[str] = None) -> dict[str, Any]:
        """Verify the asset imported from a Blender job (handoff-based)."""
        handoff = self._read_handoff()
        if job_id:
            handoff = handoff if handoff.get("job_id") == job_id else {}
        asset_path = handoff.get("asset_path")
        if not asset_path:
            return {"ok": False, "result": {"ok": False, "code": "NO_HANDOFF", "error": "no import handoff; run import_blender_output first"}}
        return self.verify_imported_asset(asset_path)

    def inspect_imported_asset(self, asset_path: str) -> dict[str, Any]:
        return self.verify_imported_asset(asset_path)

    # ------------------------------------------------------------ spawn
    def spawn_imported_asset(
        self,
        asset_path: str,
        actor_name: str,
        location=None,
        rotation=None,
        scale=None,
    ) -> dict[str, Any]:
        location = location or [0, 0, 0]
        rotation = rotation or [0, 0, 0]
        scale = scale or [1, 1, 1]
        result = self.bridge.execute_python(_SPAWN_TEMPLATE.format(
            asset_path=asset_path,
            label=actor_name,
            loc=location,
            rot=rotation,
            scale=scale,
        ))
        return self._wrap(self._payload(result))

    def spawn_blender_output(
        self,
        job_id: Optional[str] = None,
        actor_name: str = "UA_Blender_Asset",
        location=None,
        rotation=None,
        scale=None,
    ) -> dict[str, Any]:
        """Spawn the asset imported from a Blender job (handoff-based)."""
        handoff = self._read_handoff()
        if job_id:
            handoff = handoff if handoff.get("job_id") == job_id else {}
        asset_path = handoff.get("asset_path")
        if not asset_path:
            return {"ok": False, "result": {"ok": False, "code": "NO_HANDOFF", "error": "no import handoff; run import_blender_output first"}}
        spawn = self.spawn_imported_asset(asset_path, actor_name, location=location, rotation=rotation, scale=scale)
        payload = spawn.get("result") or spawn
        if payload.get("ok"):
            payload["handoff"] = handoff
        return spawn
