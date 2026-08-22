from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

asset = unreal.EditorAssetLibrary.load_asset(
    "/Game/AgentTests/BP_GraphBridgeSmoke"
)

ok = False
if asset:
    ok = unreal.EditorAssetLibrary.save_loaded_asset(asset)

__bridge_result__ = {
    "asset_loaded": asset is not None,
    "save_ok": bool(ok)
}
"""

pprint.pp(b.execute_python(code))
