from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
targets = {
    "create_blueprint_asset_with_parent":
        unreal.BlueprintEditorLibrary.create_blueprint_asset_with_parent,

    "compile_blueprint":
        unreal.BlueprintEditorLibrary.compile_blueprint,

    "add_member_variable":
        unreal.BlueprintEditorLibrary.add_member_variable,

    "get_basic_type_by_name":
        unreal.BlueprintEditorLibrary.get_basic_type_by_name,

    "list_member_variable_names":
        unreal.BlueprintEditorLibrary.list_member_variable_names,

    "create_new_bp_component":
        unreal.SubobjectDataSubsystem.create_new_bp_component,

    "k2_gather_subobject_data_for_blueprint":
        unreal.SubobjectDataSubsystem.k2_gather_subobject_data_for_blueprint,

    "save_loaded_asset":
        unreal.EditorAssetLibrary.save_loaded_asset,
}

__bridge_result__ = {
    "ok": True,
    "docs": {
        name: getattr(fn, "__doc__", None)
        for name, fn in targets.items()
    }
}
'''

pprint.pp(b.execute_python(code))
