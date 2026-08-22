from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
classes = [
    "K2Node_CustomEvent",
    "K2Node_CallFunction",
    "K2Node_Event",
    "EdGraph",
]

result = {
    "new_object_doc": unreal.new_object.__doc__,
    "classes": {}
}

for cname in classes:
    cls = getattr(unreal, cname)
    item = {
        "doc": cls.__doc__,
        "class_doc": getattr(cls, "__doc__", None),
    }

    try:
        obj = unreal.new_object(cls)
        item["created"] = True
        item["repr"] = str(obj)

        try:
            item["editor_properties"] = [
                p for p in dir(obj)
                if any(x in p.lower() for x in [
                    "graph",
                    "node",
                    "function",
                    "event",
                    "guid",
                    "outer"
                ])
            ]
        except Exception as e:
            item["properties_error"] = repr(e)

    except Exception as e:
        item["created"] = False
        item["error"] = repr(e)

    result["classes"][cname] = item

__bridge_result__ = result
'''

pprint.pp(b.execute_python(code), width=180)
