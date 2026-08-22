from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
names = [
    x for x in dir(unreal)
    if (
        "kismet" in x.lower()
        or "systemlibrary" in x.lower()
        or "system_library" in x.lower()
    )
]

__bridge_result__ = {
    "matching_unreal_names": names
}
'''

pprint.pp(b.execute_python(code), width=160)
