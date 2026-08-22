from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "rename_subobject":
        unreal.SubobjectDataSubsystem.rename_subobject.__doc__
}
'''

pprint.pp(b.execute_python(code))
