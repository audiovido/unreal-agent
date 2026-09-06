"""Worker 3 takeover: probe live UE bridge state (project, level, existing props)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=120)

print("ping:", json.dumps(BRIDGE.ping(), default=str)[:300])

probe = r"""
import unreal
info = {}
info["project_dir"] = unreal.Paths.project_dir()
info["project_content_dir"] = unreal.Paths.project_content_dir()
les = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = les.get_editor_world()
info["level_name"] = world.get_name()
info["level_path"] = world.get_path_name()
info["props_dir_exists"] = unreal.EditorAssetLibrary.does_directory_exist("/Game/AividoHQ/Props")
info["hq_map_exists"] = unreal.EditorAssetLibrary.does_asset_exist("/Game/Maps/AividoHQ")
ar = unreal.AssetRegistryHelpers.get_asset_registry()
props = ar.get_assets_by_path("/Game/AividoHQ/Props", recursive=True)
info["props_asset_count"] = len(props)
info["props_assets"] = [str(p.package_name) for p in props][:50]
__bridge_result__ = info
"""
out = BRIDGE.execute_python(probe)
print("ok:", out.get("ok"))
print(json.dumps(out.get("result"), indent=1, default=str))
if out.get("error"):
    print("error:", out["error"][:600])
