import unreal
names = [a for a in dir(unreal.MaterialProperty) if not a.startswith("_")]
__bridge_result__ = {"members": names, "sample": [ (n, getattr(unreal.MaterialProperty, n).value if hasattr(getattr(unreal.MaterialProperty,n),'value') else None) for n in names[:30] ]}
