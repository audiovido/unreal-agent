from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "doc": unreal.SubobjectDataSubsystem.create_new_bp_component.__doc__
}
'''

pprint.pp(b.execute_python(code))
