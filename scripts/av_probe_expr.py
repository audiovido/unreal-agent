import unreal
out = {}
for clsname in ("MaterialExpressionConstant","MaterialExpressionConstant3Vector","MaterialExpressionScalarParameter","MaterialExpressionVectorParameter"):
    cls = getattr(unreal, clsname, None)
    if cls is None:
        out[clsname] = "NO CLASS"
        continue
    try:
        o = unreal.material_editing_library.create_material_expression(unreal.Material, cls, 0, 0) if False else None
    except Exception:
        o = None
    # list properties via a temp material
    import unreal as u
    to = u.AssetToolsHelpers.get_asset_tools()
    tmp = None
    try:
        tmp = to.create_asset("TMPX","/Game/Studio/Materials", unreal.Material, unreal.MaterialFactoryNew())
    except Exception:
        pass
    props = []
    if tmp is not None:
        try:
            ex = u.MaterialEditingLibrary.create_material_expression(tmp, cls, 0, 0)
            allowed = ex.get_property_names()
            props = list(allowed)
        except Exception as e:
            props = ["ERR:"+str(e)[:120]]
        try:
            u.EditorAssetLibrary.delete_asset(str(tmp.get_path_name()))
        except Exception:
            pass
    out[clsname] = props[:40]
__bridge_result__ = out
