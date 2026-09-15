import unreal
from pathlib import Path
out = {"materials": {}}

proj = Path(unreal.SystemLibrary.get_project_directory())
ini = proj / "Config" / "DefaultEngine.ini"
text = ini.read_text(encoding="utf-8") if ini.exists() else ""
sec = "[/Script/Engine.RendererSettings]"
add = ["r.DynamicGlobalIlluminationMethod=1","r.ReflectionMethod=1","r.Shadow.Virtual.Enable=1","r.GenerateMeshDistanceFields=1"]
if sec not in text: text += ("\n"+sec+"\n")
lines = text.splitlines()
out_lines = [l for l in lines if not l.strip().startswith(("r.DynamicGlobalIlluminationMethod=","r.ReflectionMethod=","r.Shadow.Virtual.Enable=","r.GenerateMeshDistanceFields="))]
if sec in out_lines:
    out_lines[out_lines.index(sec)+1:out_lines.index(sec)+1] = add
ini.write_text("\n".join(out_lines)+"\n", encoding="utf-8")
out["ini"] = text.count("r.DynamicGlobalIlluminationMethod=1")>=1 or "\n".join(out_lines).count("r.DynamicGlobalIlluminationMethod=1")>=1

atools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
MP = unreal.MaterialProperty

def vec(*x): return unreal.LinearColor(float(x[0]), float(x[1]), float(x[2]), 1.0)

def make_mat(name):
    m = unreal.load_asset("/Game/Studio/Materials/"+name)
    if m is None:
        m = atools.create_asset(name, "/Game/Studio/Materials", unreal.Material, unreal.MaterialFactoryNew())
    return m

def build(mat, bc, metal, rough, emissive, idx):
    try:
        mel.delete_all_material_expressions(mat)
        x = -700.0
        e0 = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, x, 0)
        e0.set_editor_property("parameter_name", "BC_"+str(idx)); e0.set_editor_property("default_value", vec(*bc))
        mel.connect_material_property(e0, "RGB", MP.MP_BASE_COLOR)
        e1 = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, x, 130)
        e1.set_editor_property("parameter_name", "ME_"+str(idx)); e1.set_editor_property("default_value", float(metal))
        mel.connect_material_property(e1, "", MP.MP_METALLIC)
        e2 = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, x, 230)
        e2.set_editor_property("parameter_name", "RO_"+str(idx)); e2.set_editor_property("default_value", float(rough))
        mel.connect_material_property(e2, "", MP.MP_ROUGHNESS)
        e3 = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, x, 330)
        e3.set_editor_property("parameter_name", "EM_"+str(idx)); e3.set_editor_property("default_value", vec(*emissive))
        mel.connect_material_property(e3, "RGB", MP.MP_EMISSIVE_COLOR)
        errs = mel.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        return "ok" if not errs else "ERRCO:"+";".join(str(x) for x in errs)[:140]
    except Exception as e:
        import traceback; return "BUILD_ERR:"+traceback.format_exc()[-220:]

specs = [
    ("M_Floor_GlossDark", (0.012,0.014,0.017), 0.0, 0.16, (0,0,0)),
    ("M_Wall_Dark",       (0.02,0.022,0.03), 0.35, 0.55, (0,0,0)),
    ("M_Trim_Metal",      (0.03,0.032,0.038), 1.0, 0.28, (0,0,0)),
    ("M_Glow_Cyan",       (0,0,0), 0.0, 0.4, (0.5,2.0,3.0)),
    ("M_Glow_Warm",       (0,0,0), 0.0, 0.4, (6.0,3.0,1.0)),
    ("M_Glow_Soft",       (0,0,0), 0.0, 0.4, (0.6,0.9,1.4)),
    ("M_Stage_Dark",      (0.02,0.022,0.026), 0.25, 0.35, (0,0,0)),
]
for i,(name,bc,met,ro,em) in enumerate(specs):
    m = make_mat(name)
    out["materials"][name] = "CREATE_FAIL" if m is None else build(m, bc, met, ro, em, i)
unreal.EditorAssetLibrary.save_directory("/Game/Studio", only_if_is_dirty=False)
__bridge_result__ = out
