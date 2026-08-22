from tools.unreal.unreal_bridge import UnrealBridge
import pprint

bridge = UnrealBridge()

code = r'''
targets = {}

classes = [
    "BlueprintEditorLibrary",
    "KismetEditorUtilities",
    "AssetToolsHelpers",
    "BlueprintFactory",
    "EditorAssetLibrary",
    "SubobjectDataSubsystem",
    "SubobjectDataBlueprintFunctionLibrary",
]

for class_name in classes:
    obj = getattr(unreal, class_name, None)

    if obj is None:
        targets[class_name] = {
            "available": False,
            "methods": []
        }
        continue

    methods = [
        name
        for name in dir(obj)
        if not name.startswith("_")
    ]

    targets[class_name] = {
        "available": True,
        "methods": methods
    }

__bridge_result__ = {
    "ok": True,
    "blueprint_api": targets
}
'''

result = bridge.execute_python(code)

pprint.pp(result)
