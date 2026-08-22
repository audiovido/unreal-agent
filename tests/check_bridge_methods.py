from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "methods": [
        x for x in dir(unreal.UnrealAgentBlueprintLibrary)
        if (
            "pin" in x.lower()
            or "graph" in x.lower()
            or "save" in x.lower()
            or "call" in x.lower()
        )
    ]
}
'''

pprint.pp(b.execute_python(code))
