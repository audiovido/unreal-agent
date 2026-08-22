from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
node = unreal.new_object(unreal.K2Node_CallFunction)
lib = unreal.SystemLibrary

__bridge_result__ = {
    "system_print_members": [
        x for x in dir(lib)
        if "print" in x.lower()
    ],

    "call_node_members": [
        x for x in dir(node)
        if any(k in x.lower() for k in [
            "function",
            "reference",
            "member",
            "allocate",
            "reconstruct",
            "pin"
        ])
    ],

    "call_method_doc": getattr(
        getattr(node, "call_method", None),
        "__doc__",
        None
    ),

    "system_library_doc": lib.__doc__,
}
'''

pprint.pp(b.execute_python(code), width=180)
