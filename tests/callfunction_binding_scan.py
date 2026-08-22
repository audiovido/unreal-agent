from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
node = unreal.new_object(unreal.K2Node_CallFunction)

klass = unreal.KismetSystemLibrary.static_class()

__bridge_result__ = {
    "call_method_doc": node.call_method.__doc__,

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

    "kismet_class_members": [
        x for x in dir(klass)
        if any(k in x.lower() for k in [
            "function",
            "find"
        ])
    ],

    "kismet_system_members": [
        x for x in dir(unreal.KismetSystemLibrary)
        if "print" in x.lower()
        or "function" in x.lower()
    ],
}
'''

pprint.pp(b.execute_python(code), width=160)
