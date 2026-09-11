import unreal
mel = unreal.MaterialEditingLibrary
def doc(n):
    f = getattr(mel, n, None)
    return (n, f.__doc__ if f is not None else None)
out = {}
for n in ("connect_material_property","create_material_expression","recompile_material","set_material_usage_flag","delete_all_material_expressions"):
    out[n] = doc(n)[1] if doc(n)[1] else "NO DOC"
# also check MaterialProperty enum
out["has_MaterialProperty"] = hasattr(unreal, "MaterialProperty")
print(json.dumps(out, indent=1)) if False else None
import json as _j
__bridge_result__ = _j.dumps(out)[:2000] if len(_j.dumps(out))>0 else out
