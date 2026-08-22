from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
cls = unreal.SystemLibrary.static_class()

__bridge_result__ = {
    "print_string_doc":
        unreal.SystemLibrary.print_string.__doc__,

    "class_members": [
        x for x in dir(cls)
        if any(k in x.lower() for k in [
            "function",
            "find",
            "method"
        ])
    ],

    "node_call_method_tests": {}
}

node = unreal.new_object(unreal.K2Node_CallFunction)

for method_name in [
    "SetFromFunction",
    "SetFromField",
    "AllocateDefaultPins",
    "ReconstructNode"
]:
    try:
        __bridge_result__["node_call_method_tests"][method_name] = {
            "callable": True,
            "result": str(node.call_method(method_name))
        }
    except Exception as exc:
        __bridge_result__["node_call_method_tests"][method_name] = {
            "callable": False,
            "error": repr(exc)
        }
'''

pprint.pp(b.execute_python(code), width=170)
