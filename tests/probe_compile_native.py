from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

ok = unreal.UnrealAgentBlueprintLibrary.compile_and_save_blueprint(
    "/Game/AgentTests/BP_GraphBridgeSmoke"
)

__bridge_result__ = {"compile_ok": bool(ok)}
"""

pprint.pp(b.execute_python(code))
