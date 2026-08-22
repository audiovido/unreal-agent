from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
def scan_with_docs(obj, words):
    result = {}

    for name in dir(obj):
        low = name.lower()

        if any(word in low for word in words):
            member = getattr(obj, name, None)

            try:
                doc = member.__doc__
            except Exception:
                doc = None

            result[name] = doc

    return result

__bridge_result__ = {
    "BlueprintEditorLibrary": {
        "add_event_override":
            unreal.BlueprintEditorLibrary.add_event_override.__doc__,

        "add_function_override":
            unreal.BlueprintEditorLibrary.add_function_override.__doc__,

        "list_events":
            unreal.BlueprintEditorLibrary.list_events.__doc__,

        "list_functions":
            unreal.BlueprintEditorLibrary.list_functions.__doc__,
    },

    "BlueprintGraphPin": scan_with_docs(
        unreal.BlueprintGraphPin,
        [
            "link",
            "connect",
            "break",
            "default",
            "name",
            "type"
        ]
    ),
}
'''

pprint.pp(b.execute_python(code), width=170)
