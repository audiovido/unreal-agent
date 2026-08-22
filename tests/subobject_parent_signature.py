from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
__bridge_result__ = {
    "gather": unreal.SubobjectDataSubsystem.k2_gather_subobject_data_for_blueprint.__doc__,
    "is_root": unreal.SubobjectDataBlueprintFunctionLibrary.is_root_component.__doc__,
    "is_component": unreal.SubobjectDataBlueprintFunctionLibrary.is_component.__doc__,
    "get_object": unreal.SubobjectDataBlueprintFunctionLibrary.get_object.__doc__
}
'''

pprint.pp(b.execute_python(code))
