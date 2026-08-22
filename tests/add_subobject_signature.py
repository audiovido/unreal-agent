from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "add_new_subobject":
        unreal.SubobjectDataSubsystem.add_new_subobject.__doc__,

    "params_class":
        getattr(unreal, "AddNewSubobjectParams", None).__doc__
        if getattr(unreal, "AddNewSubobjectParams", None)
        else None
}
'''

pprint.pp(b.execute_python(code))
