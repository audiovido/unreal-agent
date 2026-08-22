from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
def scan(cls):
    wanted = [
        "add", "node", "pin", "link", "connect",
        "function", "event", "allocate",
        "reconstruct", "graph"
    ]
    return [
        x for x in dir(cls)
        if any(w in x.lower() for w in wanted)
    ]

def docs(cls, names):
    out = {}
    for name in names:
        obj = getattr(cls, name, None)
        if obj is not None:
            try:
                out[name] = obj.__doc__
            except Exception:
                out[name] = None
    return out

classes = {
    "EdGraph": unreal.EdGraph,
    "EdGraphNode": unreal.EdGraphNode,
    "K2Node": unreal.K2Node,
    "K2Node_Event": unreal.K2Node_Event,
    "K2Node_CustomEvent": unreal.K2Node_CustomEvent,
    "K2Node_CallFunction": unreal.K2Node_CallFunction,
}

result = {}

for name, cls in classes.items():
    names = scan(cls)
    result[name] = {
        "members": names,
        "docs": docs(cls, names)
    }

result["global_helpers"] = [
    x for x in dir(unreal)
    if any(w in x.lower() for w in [
        "new_object",
        "graphschema",
        "blueprintnode",
        "nodecreator",
        "kismetcompiler"
    ])
]

__bridge_result__ = result
'''

pprint.pp(b.execute_python(code), width=160)
