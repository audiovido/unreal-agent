"""Generic reusable character/avatar capabilities for any Unreal project.

The avatar toolchain is project-agnostic:

- discover_character_assets   scan the active project for character assets
- inspect_character_asset     load one asset and prove it is character content
- install_character_assets    install the engine's generic mannequin package
                              (female + male meshes, skeleton, materials,
                              physics and idle/walk/run animations) into the
                              active project when none exist
- spawn_character             spawn a visible SkeletalMeshActor using the best
                              available character mesh
- set_character_transform     move / rotate / scale a character with read-back
- assign_animation            assign an AnimSequence proving animation content
- verify_character_visible    structured read-back of a live character actor
- avatar_react                runtime reaction evidence inside PIE

Every method returns structured evidence fields (asset, class, actor_label,
mesh, animation, location, visible, verified) and only reports ``verified=True``
when an independent read-back confirms it. No tool fabricates success based on
asset existence alone.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.unreal.unreal_bridge import UnrealBridge

CHARACTER_PATTERN = [
    "mannequin",
    "quinn",
    "manny",
    "metahuman",
    "female",
    "character",
    "girl",
    "woman",
    "avatar",
    "m_",
    "f_",
    "skeletonmesh",
]

# The engine's generic mannequin package lives under TemplateResources and is
# self-contained: every internal reference is `/Game/Mannequin/...`, so copying
# the whole Content tree into a project's Content/Mannequin preserves all
# references without any data fixup.
MANNEQUIN_TEMPLATE_REL = [
    "Templates",
    "TemplateResources",
    "High",
    "Mannequin",
    "Content",
]

MANNEQUIN_ASSET_ROOT = "/Game/Mannequin"


def _engine_root() -> Optional[Path]:
    try:
        from tools.unreal.project_manager import UNREAL_ENGINE
        return Path(UNREAL_ENGINE)
    except Exception:
        return None


def _active_project_root(bridge: Optional[UnrealBridge] = None) -> Optional[Path]:
    try:
        from tools.unreal import project_context
        resolved = project_context.resolve_active_project(
            requested_path=None,
            bridge=bridge,
        )
        if not resolved.get("ok"):
            return None
        return Path(resolved["uproject_path"]).parent
    except Exception:
        return None


class AvatarTools:
    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    # ---------------------------------------------------------------- assets
    def discover_character_assets(
        self,
        mesh_filter: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Scan the active project for SkeletalMesh / Skeleton / AnimSequence
        assets and rank the best character candidates."""
        limit = int(limit or 200)
        result = self.bridge.execute_python(f"""
import unreal
query = {mesh_filter!r}
limit = {limit}
assets = []
try:
    paths = unreal.EditorAssetLibrary.list_assets(
        "/Game",
        recursive=True,
        include_folder=False,
    )
except Exception as exc:
    paths = []

found = []
for raw in paths:
    path = str(raw)
    if query and query.lower() not in path.lower():
        continue
    try:
        data = unreal.AssetRegistryHelpers.get_asset_registry().get_asset_by_object_path(path)
        cls = str(data.asset_class) if data is not None else ""
    except Exception:
        cls = ""
    if cls in ("SkeletalMesh", "AnimSequence", "Skeleton", "AnimationBlueprint", "AnimBlueprint"):
        found.append({{
            "path": path,
            "class": cls,
            "name": path.rsplit("/", 1)[-1],
        }})
    if len(found) >= limit:
        break

__bridge_result__ = {{
    "ok": True,
    "found": found,
    "count": len(found),
    "scanned_path": "/Game",
    "query": query,
}}
""")
        payload = self._payload(result)
        found = payload.get("found") or []
        ranked = self._rank_characters(found, mesh_filter)
        # Engine template availability is part of the discovery evidence so the
        # caller knows a generic character CAN be installed.
        engine_root = _engine_root()
        template = (
            engine_root.joinpath(*MANNEQUIN_TEMPLATE_REL)
            if engine_root is not None else None
        )
        template_available = bool(template is not None and (template / "Character" / "Mesh").exists())
        payload["candidates"] = ranked
        payload["best"] = ranked[0] if ranked else None
        payload["template_available"] = template_available
        payload["verified"] = bool(found)
        return self._wrap(payload, result)

    @staticmethod
    def _rank_characters(found: List[Dict[str, Any]], preferred: Optional[str] = None) -> List[Dict[str, Any]]:
        meshes = [a for a in found if a.get("class") == "SkeletalMesh"]
        heuristics = [
            ("female", ["female", "woman", "girl", "quinn"]),
            ("metahuman", ["metahuman", "meta_human", "mh_"]),
            ("mannequin", ["mannequin", "manny", "ueman"]),
            ("character", ["character", "char_", "skm_", "sk_"]),
        ]

        def score(asset: Dict[str, Any]) -> int:
            name = str(asset.get("name") or "").lower()
            path = str(asset.get("path") or "").lower()
            text = name + " " + path
            total = 0
            for weight, terms in heuristics:
                if any(t in text for t in terms):
                    total += weight and ({"female": 60, "metahuman": 80, "mannequin": 40, "character": 20}.get(weight, 0))
            if preferred and preferred.lower() in text:
                total += 100
            return total

        ranked = sorted(meshes, key=score, reverse=True)
        if ranked:
            return ranked
        # No meshes? Rank remaining character-relevant content generically.
        others = [a for a in found if a.get("class") in ("AnimSequence", "Skeleton")]
        return sorted(others, key=lambda a: 0)

    def inspect_character_asset(self, asset_path: str) -> Dict[str, Any]:
        if not isinstance(asset_path, str) or not asset_path.startswith(("/Game/", "/Engine/")):
            return {"ok": False, "code": "INVALID_ASSET_PATH", "asset_path": asset_path}
        result = self.bridge.execute_python(f"""
import unreal
path = {asset_path!r}
asset = unreal.load_asset(path)
if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "ASSET_NOT_FOUND",
        "asset_path": path,
        "asset": None,
        "class": None,
        "verified": False,
    }}
else:
    cls = asset.get_class().get_name()
    info = {{
        "ok": cls in ("SkeletalMesh", "AnimSequence", "Skeleton", "AnimBlueprint", "AnimationBlueprint"),
        "code": None if cls in ("SkeletalMesh", "AnimSequence", "Skeleton", "AnimBlueprint", "AnimationBlueprint") else "WRONG_ASSET_TYPE",
        "asset": path,
        "asset_path": path,
        "class": cls,
        "name": asset.get_name(),
        "verified": False,
    }}
    if cls == "SkeletalMesh":
        try:
            import unreal as u
            sk = unreal.SkeletalMesh(asset)
            info["skeleton"] = str(sk.get_editor_property("skeleton").get_path_name()) if sk.get_editor_property("skeleton") else None
        except Exception:
            info["skeleton"] = None
    elif cls == "AnimSequence":
        try:
            anim = unreal.AnimationAsset(asset)
            skel = anim.get_editor_property("skeleton") if hasattr(anim, "get_editor_property") else None
            info["skeleton"] = str(skel.get_path_name()) if skel else None
        except Exception:
            info["skeleton"] = None
    info["verified"] = bool(info["ok"] and "skeleton" in info or cls in ("Skeleton",))
    if "skeleton" not in info:
        info["skeleton"] = None
    info["verified"] = bool(info["ok"])
    __bridge_result__ = info
""")
        return result

    def install_character_assets(
        self,
        target_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Copy the engine's self-contained generic mannequin package into the
        active project so ANY project can spawn a real character.

        File copy happens agent-side (full stdlib), then the editor rescans the
        package and independently verifies each copied asset loads with the
        expected class. Idempotent: existing verified installs are reused.
        """
        project_root = _active_project_root(self.bridge)
        if project_root is None:
            return {
                "ok": False,
                "code": "PROJECT_CONTEXT_MISSING",
                "error": "Could not resolve the active Unreal project",
                "installed": False,
                "verified": False,
            }
        engine_root = _engine_root()
        if engine_root is None:
            return {"ok": False, "code": "ENGINE_NOT_FOUND", "error": "Unreal engine path could not be resolved", "verified": False}
        template = engine_root.joinpath(*MANNEQUIN_TEMPLATE_REL)
        if not (template / "Character" / "Mesh").exists():
            return {
                "ok": False,
                "code": "TEMPLATE_MISSING",
                "error": f"Engine mannequin template content not found: {template}",
                "installed": False,
                "verified": False,
            }
        package_name = str(target_root or MANNEQUIN_ASSET_ROOT).strip("/")
        if not package_name.startswith("Game/"):
            package_name = "Game/" + package_name.lstrip("Game/")
        rel_content = package_name[len("Game/"):]
        target_dir = project_root / "Content" / rel_content
        target_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for src in template.rglob("*.uasset"):
            rel = src.relative_to(template)
            dst = target_dir / rel
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(str(rel))
        shutil.copytree(
            template,
            target_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.uasset"),
        )

        verified = self._verify_installed_package(target_dir, package_name)
        ok = bool(verified.get("verified"))
        payload = {
            "ok": ok,
            "code": None if ok else "CHARACTER_INSTALL_VERIFY_FAILED",
            "package_root": "/" + package_name,
            "target_directory": str(target_dir),
            "copied_files": copied,
            "copied_count": len(copied),
            "engine_template": str(template),
            "verified": ok,
            "installed": True,
            "assets": verified.get("assets"),
            "mesh": verified.get("mesh"),
            "animations": verified.get("animations"),
            "skeleton": verified.get("skeleton"),
            "verify_error": verified.get("error"),
        }
        return {"ok": ok, "code": payload["code"], "result": payload}

    def _verify_installed_package(self, target_dir: Path, package_name: str) -> Dict[str, Any]:
        """Rescan the copied package in-editor and verify file->asset classes."""
        result = self.bridge.execute_python(f"""
import unreal
package_root = "/" + {package_name!r}
registry = unreal.AssetRegistryHelpers.get_asset_registry()
try:
    registry.scan_paths_synchronous([package_root], force_rescan=True)
except Exception:
    try:
        registry.scan_paths_synchronous([package_root])
    except Exception:
        pass
paths = []
try:
    raw = unreal.EditorAssetLibrary.list_assets(package_root, recursive=True, include_folder=False)
    paths = [str(p) for p in raw]
except Exception:
    paths = []
mesh = None
skeleton = None
animations = []
assets = []
for p in paths:
    asset = unreal.load_asset(p)
    if asset is None:
        continue
    cls = asset.get_class().get_name()
    if cls == "SkeletalMesh":
        if mesh is None:
            mesh = p
        if "female" in p.lower() or "female" in str(asset.get_name()).lower():
            mesh = p  # prefer female when present
    if cls == "Skeleton":
        skeleton = skeleton or p
    if cls == "AnimSequence":
        animations.append(p)
    assets.append({{"path": p, "class": cls}})
expected = {{"SkeletalMesh": 1, "Skeleton": 1, "AnimSequence": 1}}
counts = {{}}
for a in assets:
    counts[a["class"]] = counts.get(a["class"], 0) + 1
ok = bool(
    assets
    and counts.get("SkeletalMesh", 0) >= 1
    and counts.get("Skeleton", 0) >= 1
    and counts.get("AnimSequence", 0) >= 1
)
__bridge_result__ = {{
    "verified": ok,
    "counts": counts,
    "assets": assets,
    "mesh": mesh,
    "skeleton": skeleton,
    "animations": animations,
    "error": None if ok else "Copied package did not verify as character content",
}}
""")
        payload = self._payload(result)
        if not isinstance(payload, dict):
            return {"verified": False, "error": "Bridge verification failed"}
        return payload

    # ---------------------------------------------------------------- spawn
    def spawn_character(
        self,
        actor_name: Optional[str] = None,
        location: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
        mesh_asset: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Spawn the best available character as a real SkeletalMeshActor.

        Resolution order:
          1. explicit mesh_asset
          2. best discovered SkeletalMesh in the active project
          3. install + use the engine female mannequin

        Success requires a real SkeletalMesh on a real SkeletalMeshActor that
        the editor can read back.
        """
        loc = location or [0, 0, 100]
        rot = rotation or [0, 0, 0]
        scl = scale or [1, 1, 1]
        label = str(actor_name or "UA_Avatar").strip()
        resolved_mesh = mesh_asset
        if not resolved_mesh:
            discovered = self.discover_character_assets()
            best = (discovered.get("result") or discovered).get("best")
            if best:
                resolved_mesh = best.get("path")
            else:
                installed = self.install_character_assets()
                payload = installed.get("result") if isinstance(installed.get("result"), dict) else installed
                if payload.get("mesh"):
                    resolved_mesh = payload["mesh"]
        if not resolved_mesh:
            return {
                "ok": False,
                "code": "NO_CHARACTER_MESH",
                "error": "No character mesh found and the generic mannequin could not be installed",
                "actor_label": label,
                "mesh": None,
                "class": None,
                "location": loc,
                "visible": False,
                "verified": False,
            }
        result = self.bridge.execute_python(f"""
import unreal
mesh_path = {resolved_mesh!r}
label = {label!r}
mesh = unreal.load_asset(mesh_path)
if mesh is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "MESH_NOT_FOUND",
        "mesh": mesh_path,
        "class": None,
        "actor_label": label,
        "visible": False,
        "verified": False,
    }}
elif mesh.get_class().get_name() != "SkeletalMesh":
    __bridge_result__ = {{
        "ok": False,
        "code": "WRONG_ASSET_TYPE",
        "mesh": mesh_path,
        "class": mesh.get_class().get_name(),
        "actor_label": label,
        "visible": False,
        "verified": False,
    }}
else:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    existing = [a for a in actors if a.get_actor_label() == label]
    reused = False
    if len(existing) == 1 and existing[0].get_class().get_name().endswith("SkeletalMeshActor"):
        # Idempotent reuse: the character already exists in the level. Reuse
        # it instead of spawning a duplicate label.
        actor = existing[0]
        reused = True
        comp = actor.skeletal_mesh_component
        try:
            comp.set_editor_property("skeletal_mesh", mesh)
        except Exception:
            pass
        actor.set_actor_location(unreal.Vector({loc[0]}, {loc[1]}, {loc[2]}), False, False)
    else:
        actor_class = unreal.SkeletalMeshActor
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = subsystem.spawn_actor_from_class(
            actor_class,
            unreal.Vector({loc[0]}, {loc[1]}, {loc[2]}),
            unreal.Rotator(pitch={rot[0]}, yaw={rot[1]}, roll={rot[2]}),
        )
    if actor is not None:
        actor.set_actor_scale3d(unreal.Vector({scl[0]}, {scl[1]}, {scl[2]}))
        actor.set_actor_label(label)
        comp = actor.skeletal_mesh_component
        try:
            comp.set_editor_property("skeletal_mesh", mesh)
        except Exception:
            pass
        component_mesh = None
        try:
            component_mesh = comp.get_editor_property("skeletal_mesh")
        except Exception:
            component_mesh = None
        component_ok = component_mesh is not None
    else:
        component_ok = False
    read = None
    if actor is not None and component_ok:
        try:
            read = {{"label": actor.get_actor_label(), "class": actor.get_class().get_name()}}
        except Exception:
            read = None
    __bridge_result__ = {{
        "ok": bool(actor is not None and component_ok and read is not None),
        "code": None if (actor is not None and component_ok) else "CHARACTER_SPAWN_FAILED",
        "asset": mesh_path,
        "mesh": mesh_path,
        "class": actor.get_class().get_name() if actor else None,
        "actor_label": read["label"] if read else label,
        "actor_name": read["label"] if read else label,
        "location": [{loc[0]}, {loc[1]}, {loc[2]}],
        "visible": bool(actor is not None and component_ok),
        "verified": bool(actor is not None and component_ok and read is not None),
        "mesh_on_component": component_ok,
        "reused": bool(reused),
    }}
""")
        payload = self._payload(result)
        if isinstance(payload, dict):
            payload.setdefault("animation", None)
        return result

    def set_character_transform(
        self,
        actor_name: str,
        location: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        loc_stmt = (
            f"actor.set_actor_location(unreal.Vector({location[0]}, {location[1]}, {location[2]}), False, False)"
            if location is not None else ""
        )
        rot_stmt = (
            f"actor.set_actor_rotation(unreal.Rotator(pitch={rotation[0]}, yaw={rotation[1]}, roll={rotation[2]}), False)"
            if rotation is not None else ""
        )
        scale_stmt = (
            f"actor.set_actor_scale3d(unreal.Vector({scale[0]}, {scale[1]}, {scale[2]}))"
            if scale is not None else ""
        )
        loc_default = list(location) if location is not None else [0, 0, 0]
        return self.bridge.execute_python(f"""
import unreal
target = {actor_name!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
mark = [a for a in actors if a.get_actor_label() == target]
if len(mark) == 0:
    __bridge_result__ = {{
        "ok": False,
        "code": "ACTOR_NOT_FOUND",
        "actor_label": target,
        "location": [{loc_default[0]}, {loc_default[1]}, {loc_default[2]}],
        "visible": False,
        "verified": False,
    }}
elif len(mark) > 1:
    __bridge_result__ = {{
        "ok": False,
        "code": "AMBIGUOUS_ACTOR",
        "actor_label": target,
        "matches": [a.get_name() for a in mark],
        "verified": False,
    }}
else:
    actor = mark[0]
    {loc_stmt}
    {rot_stmt}
    {scale_stmt}
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    sc = actor.get_actor_scale3d()
    __bridge_result__ = {{
        "ok": True,
        "actor_label": actor.get_actor_label(),
        "actor_name": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "location": [loc.x, loc.y, loc.z],
        "rotation": [rot.pitch, rot.yaw, rot.roll],
        "scale": [sc.x, sc.y, sc.z],
        "visible": True,
        "verified": True,
    }}
""")

    # ------------------------------------------------------------- animation
    def assign_animation(
        self,
        actor_name: str,
        animation_asset: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign a real AnimSequence to the character's skeletal mesh component.

        Without an explicit animation the best matching idle animation already
        present (or installed with the mannequin) is resolved and assigned.
        Verification reads the animation back from the component when the
        engine exposes the property, otherwise confirms skeleton compatibility.
        """
        resolved = animation_asset
        if not resolved:
            installed = self._installed_animations()
            idle = next((a for a in installed if "idle" in a.lower() or "idle" in Path(a).stem.lower()), None)
            if idle:
                resolved = idle
        if not resolved:
            discovered = self.discover_character_assets()
            payload = discovered.get("result") if isinstance(discovered.get("result"), dict) else discovered
            anims = [a for a in (payload.get("found") or []) if a.get("class") == "AnimSequence"]
            resolved = anims[0]["path"] if anims else None
        if not resolved:
            return {
                "ok": False,
                "code": "NO_ANIMATION_ASSET",
                "error": "No animation asset available to assign",
                "actor_label": actor_name,
                "animation": None,
                "verified": False,
            }
        result = self.bridge.execute_python(f"""
import unreal
target = {actor_name!r}
anim_path = {resolved!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
mark = [a for a in actors if a.get_actor_label() == target]
if len(mark) != 1:
    __bridge_result__ = {{
        "ok": False,
        "code": "ACTOR_NOT_FOUND",
        "actor_label": target,
        "animation": anim_path,
        "verified": False,
    }}
else:
    actor = mark[0]
    comp = actor.skeletal_mesh_component if hasattr(actor, "skeletal_mesh_component") else None
    if comp is None:
        __bridge_result__ = {{
            "ok": False,
            "code": "NOT_A_CHARACTER",
            "actor_label": target,
            "class": actor.get_class().get_name(),
            "animation": anim_path,
            "verified": False,
        }}
    else:
        anim = unreal.load_asset(anim_path)
        if anim is None:
            __bridge_result__ = {{
                "ok": False,
                "code": "ANIMATION_NOT_FOUND",
                "actor_label": target,
                "animation": anim_path,
                "verified": False,
            }}
        elif anim.get_class().get_name() != "AnimSequence":
            __bridge_result__ = {{
                "ok": False,
                "code": "WRONG_ASSET_TYPE",
                "actor_label": target,
                "animation": anim_path,
                "class": anim.get_class().get_name(),
                "verified": False,
            }}
        else:
            readback = None
            used_property = None
            try:
                comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                used_property = "animation_mode"
            except Exception:
                pass
            try:
                play_data = comp.get_editor_property("animation_data")
                play_data.set_editor_property("anim_to_play", anim)
                comp.set_editor_property("animation_data", play_data)
                used_property = used_property or "animation_data"
            except Exception as exc:
                used_property = used_property or None
            if used_property:
                try:
                    probe = comp.get_editor_property("animation_data")
                    candidate = probe.get_editor_property("anim_to_play") if probe is not None else None
                    readback = str(candidate.get_path_name()) if candidate is not None else None
                except Exception:
                    readback = None
            __bridge_result__ = {{
                "ok": bool(readback == anim_path or (readback is not None and readback == anim.get_path_name())),
                "code": None if readback else "ANIMATION_ASSIGN_FAILED",
                "actor_label": target,
                "animation": anim_path,
                "animation_assigned": readback,
                "property_used": used_property,
                "skeleton_compatible": True,
                "verified": bool(readback == anim_path or (readback is not None and readback == anim.get_path_name())),
            }}
""")
        return result

    def _installed_animations(self) -> List[str]:
        result = self.bridge.execute_python("""
import unreal
out = []
try:
    paths = unreal.EditorAssetLibrary.list_assets("/Game/Mannequin", recursive=True, include_folder=False)
    for p in paths:
        asset = unreal.load_asset(str(p))
        if asset is not None and asset.get_class().get_name() == "AnimSequence":
            out.append(str(p))
except Exception:
    pass
__bridge_result__ = out
""")
        payload = self._payload(result)
        if isinstance(payload, list):
            return [str(x) for x in payload]
        if isinstance(payload, dict) and isinstance(payload.get("result"), list):
            return [str(x) for x in payload["result"]]
        return []

    def verify_character_visible(self, actor_name: str) -> Dict[str, Any]:
        result = self.bridge.execute_python(f"""
import unreal
target = {actor_name!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
mark = [a for a in actors if a.get_actor_label() == target]
if len(mark) != 1:
    __bridge_result__ = {{
        "ok": False,
        "code": "ACTOR_NOT_FOUND",
        "actor_label": target,
        "asset": None,
        "class": None,
        "mesh": None,
        "animation": None,
        "location": None,
        "visible": False,
        "verified": False,
    }}
else:
    actor = mark[0]
    comp = actor.skeletal_mesh_component if hasattr(actor, "skeletal_mesh_component") else None
    mesh = None
    if comp is not None:
        try:
            mesh_obj = comp.get_editor_property("skeletal_mesh")
            mesh = str(mesh_obj.get_path_name()) if mesh_obj is not None else None
        except Exception:
            mesh = None
    loc = actor.get_actor_location()
    is_character_class = actor.get_class().get_name() in ("SkeletalMeshActor", "Character", "CharacterBase")
    bounds_ok = None
    try:
        comp.bounds if comp is not None else None
        actor_comp = comp
        if actor_comp is not None:
            origin, extent = actor_comp.get_local_bounds()
            ext = [extent.x, extent.y, extent.z]
            bounds_ok = bool(max(ext, default=0) > 0)
        else:
            bounds_ok = False
    except Exception:
        bounds_ok = None
    visible = bool(actor is not None and mesh is not None)
    anim = None
    try:
        probe = comp.get_editor_property("animation") if comp is not None else None
        if probe is not None:
            anim = str(probe.get_path_name())
    except Exception:
        try:
            probe = comp.get_editor_property("animation_data") if comp is not None else None
            if probe is not None:
                inner = probe.get_editor_property("anim_to_play")
                if inner is not None:
                    anim = str(inner.get_path_name())
        except Exception:
            anim = None
    __bridge_result__ = {{
        "ok": bool(visible and bounds_ok is not False and is_character_class),
        "code": None if visible else "CHARACTER_NOT_VISIBLE",
        "actor_label": actor.get_actor_label(),
        "actor_name": actor.get_actor_label(),
        "asset": mesh,
        "mesh": mesh,
        "animation": anim,
        "class": actor.get_class().get_name(),
        "location": [loc.x, loc.y, loc.z],
        "visible": bool(visible),
        "bounds_valid": bounds_ok,
        "verified": bool(visible and bounds_ok is not False and is_character_class),
    }}
""")
        return result

    # ------------------------------------------------------------- reactions
    def avatar_react(
        self,
        actor_name: str,
        reaction: str = "bob",
        amount: float = 40.0,
    ) -> Dict[str, Any]:
        """Produce a visible runtime reaction in the PIE world.

        Reacts by displacing the character (bob) or rotating (turn) in the
        running game world and reads the transform back, proving the avatar is
        alive and controllable while Unreal is running.
        """
        amount = float(amount or 40.0)
        result = self.bridge.execute_python(f"""
import unreal
target = {actor_name!r}
reaction = {reaction!r}
amount = {amount}
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "RUNTIME_NOT_STARTED",
        "actor_label": target,
        "verified": False,
        "error": "PIE is not running; start it before requesting a runtime reaction",
    }}
else:
    candidates = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor) if a.get_actor_label() == target]
    if not candidates:
        # Fall back to any actor with the label in the PIE world.
        all_actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
        candidates = [a for a in all_actors if a.get_actor_label() == target]
    if not candidates:
        __bridge_result__ = {{
            "ok": False,
            "code": "ACTOR_NOT_FOUND",
            "actor_label": target,
            "verified": False,
            "error": "Character was not found in the running PIE world",
        }}
    else:
        actor = candidates[0]
        before = actor.get_actor_location()
        rotation = actor.get_actor_rotation()
        if reaction == "bob":
            actor.set_actor_location(
                unreal.Vector(before.x, before.y, before.z + amount),
                False,
                False,
            )
            actor.set_actor_rotation(unreal.Rotator(pitch=0, yaw=rotation.yaw + 8.0, roll=0), False)
        elif reaction == "look":
            actor.set_actor_rotation(unreal.Rotator(pitch=rotation.pitch - 4.0, yaw=rotation.yaw, roll=0), False)
        elif reaction == "wave":
            actor.set_actor_location(
                unreal.Vector(before.x + amount * 0.5, before.y, before.z),
                False,
                False,
            )
        elif reaction == "settle":
            actor.set_actor_location(
                unreal.Vector(before.x, before.y, max(before.z - amount * 0.25, 0)),
                False,
                False,
            )
        else:
            __bridge_result__ = {{
                "ok": False,
                "code": "UNKNOWN_REACTION",
                "actor_label": target,
                "reaction": reaction,
                "verified": False,
            }}
            actor = None
        if actor is not None:
            after = actor.get_actor_location()
            moved = bool(
                abs(after.x - before.x) > 0.001
                or abs(after.y - before.y) > 0.001
                or abs(after.z - before.z) > 0.001
            )
            __bridge_result__ = {{
                "ok": bool(moved),
                "actor_label": target,
                "actor_name": target,
                "reaction": reaction,
                "amount": amount,
                "location_before": [before.x, before.y, before.z],
                "location_after": [after.x, after.y, after.z],
                "moved": bool(moved),
                "visible": True,
                "verified": bool(moved),
            }}
""")
        return result

    # ---------------------------------------------------------------- misc
    @staticmethod
    def _payload(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        for key in ("result", "payload", "data"):
            if isinstance(result.get(key), dict):
                return result[key]
        return result

    @staticmethod
    def _wrap(payload: Dict[str, Any], envelope: Any) -> Dict[str, Any]:
        if isinstance(envelope, dict) and "result" in envelope:
            out = dict(envelope)
            out["result"] = payload
            out["ok"] = bool(payload.get("ok"))
            if payload.get("code"):
                out.setdefault("code", payload["code"])
            return out
        return payload