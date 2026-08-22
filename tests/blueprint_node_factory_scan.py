from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
terms = (
    "blueprintaction",
    "actiondatabase",
    "actionmenu",
    "nodefactory",
    "graphnode",
    "k2node",
    "functionentry",
    "functionresult",
)

matches = [
    x for x in dir(unreal)
    if any(term in x.lower() for term in terms)
]

details = {}

for name in matches:
    try:
        obj = getattr(unreal, name)
        details[name] = [
            x for x in dir(obj)
            if any(k in x.lower() for k in (
                "spawn",
                "create",
                "add",
                "function",
                "node",
                "action"
            ))
        ]
    except Exception as exc:
        details[name] = {"error": repr(exc)}

__bridge_result__ = {
    "matches": matches,
    "details": details,
}
'''

pprint.pp(b.execute_python(code), width=180)
