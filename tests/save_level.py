from tools.unreal.unreal_bridge import UnrealBridge
import pprint

code = r'''
saved = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)

__bridge_result__ = {
    "saved": bool(saved)
}
'''

pprint.pp(UnrealBridge().execute_python(code))
