"""Check live spawned monitor actor materials + BP SCS templates."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=120)

code = r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ_PropsStage")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
live = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    if a.get_actor_label() == "W3P_Monitor":
        live = a
        break
live_out = []
if live is not None:
    for c in live.get_components_by_class(unreal.StaticMeshComponent):
        om = c.get_editor_property("override_materials")
        live_out.append({
            "comp": c.get_name(),
            "om": [str(m.get_name()) for m in om] if om else None,
        })

bp = unreal.EditorAssetLibrary.load_asset("/Game/AividoHQ/Props/BPs/BP_Aivido_Prop_Monitor")
subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
handles = subsystem.k2_gather_subobject_data_for_blueprint(bp)
scs_out = []
for handle in handles:
    data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
    obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)
    if obj is not None and obj.get_class().get_name() == "StaticMeshComponent":
        om = obj.get_editor_property("override_materials")
        scs_out.append({
            "name": obj.get_name(),
            "om": [str(m.get_name()) for m in om] if om else None,
        })
les.load_level("/Game/Maps/AividoHQ")
__bridge_result__ = {"live": live_out, "scs": scs_out}
"""

out = BRIDGE.execute_python(code)
print(json.dumps(out.get("result"), indent=1))
if out.get("error"):
    print("error:", out["error"][:800])
