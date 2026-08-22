from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "deleted": unreal.EditorAssetLibrary.delete_asset(
        "/Game/AgentTests/BP_AgentSmoke"
    )
}
'''

pprint.pp(b.execute_python(code))
