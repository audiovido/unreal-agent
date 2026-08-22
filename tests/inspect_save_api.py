from tools.unreal.unreal_bridge import UnrealBridge
import pprint

code = r'''
names = [
    n for n in dir(unreal.EditorLoadingAndSavingUtils)
    if "dirty" in n.lower() or "save" in n.lower()
]

__bridge_result__ = {
    "methods": names
}
'''

pprint.pp(UnrealBridge().execute_python(code))
