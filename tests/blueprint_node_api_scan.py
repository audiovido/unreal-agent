from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
def matches(obj, words):
    out = []
    for name in dir(obj):
        low = name.lower()
        if any(w in low for w in words):
            out.append(name)
    return sorted(out)

__bridge_result__ = {
    "BlueprintEditorLibrary": matches(
        unreal.BlueprintEditorLibrary,
        ["node", "graph", "pin", "function", "event"]
    ),
    "KismetEditorUtilities": (
        matches(
            unreal.KismetEditorUtilities,
            ["node", "graph", "pin", "function", "event"]
        )
        if hasattr(unreal, "KismetEditorUtilities")
        else None
    ),
    "classes": [
        x for x in dir(unreal)
        if any(w in x.lower() for w in [
            "edgraph",
            "k2node",
            "blueprintnode",
            "graphnode"
        ])
    ],
}
'''

pprint.pp(b.execute_python(code), width=140)
