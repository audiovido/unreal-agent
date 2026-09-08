"""Read-only preservation probe for the Aivido V2 final release gate.

Runs every preservation check against the LIVE Unreal editor bridge with
ZERO mutation:
  - project identity / engine version
  - full editor-world census (characters, props, screens, UI text, lights,
    materials, broken roots)
  - map identity (AividoHQ loaded)
  - CineMRQ isolation check (render assets still isolated under /Game/CineMRQ)
  - dirty-state readback (informational; the probe never saves)

Deliberately omits the recert probe's save + reopen + PIE idle-motion steps:
the release gate runs against the certified editor state and must not mutate
it. Writes a single JSON blob to stdout; exit code 0 iff every gate passed.

Usage:
  <venv-python> scripts/recert/v2_release_preservation_probe.py [--out PATH]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BR = UnrealBridge(host="127.0.0.1", port=6766, timeout=300)

EXPECTED_CHARS = [
    "Master", "Creative", "Visual", "Technical",
    "Audio", "Animation", "Lighting", "VFX",
]

# Certified screen set (POLISH_90_EVIDENCE/final_telemetry_v3.json
# regression_gate: AVIDO_VD_GradeStrip and AVIDO_VD_Wall do not contain the
# word "screen" but belong to the certified screen category).
CERTIFIED_SCREENS = [
    "AVIDO_Command_SideScreen_E", "AVIDO_Command_SideScreen_W",
    "AVIDO_Console_Screen", "AVIDO_Hub_Screen",
    "AVIDO_VD_GradeStrip", "AVIDO_VD_Screen_A", "AVIDO_VD_Screen_B",
    "AVIDO_VD_Wall",
]


def py(code: str) -> dict:
    out = BR.execute_python(code)
    if not isinstance(out, dict) or not out.get("ok"):
        return {"ok": False, "error": (out or {}).get("error", "bridge call failed"), "raw": out}
    res = out.get("result")
    if isinstance(res, str):
        # bridge stringified the payload (non-JSON-serializable content)
        try:
            import ast
            res = ast.literal_eval(res)
        except Exception:
            return {"ok": False, "error": "bridge result stringified and unparseable", "raw": res}
    if isinstance(res, dict) and "ok" in res:
        return res
    if isinstance(res, dict):
        return {"ok": True, **res}
    return {"ok": True, "result": res}


# ---------------------------------------------------------------- census
CENSUS_CODE = r"""
import unreal
w = unreal.EditorLevelLibrary.get_editor_world()
res = {"world": w.get_path_name() if w else None}
CERTIFIED_SCREENS = ["AVIDO_Command_SideScreen_E", "AVIDO_Command_SideScreen_W", "AVIDO_Console_Screen", "AVIDO_Hub_Screen", "AVIDO_VD_GradeStrip", "AVIDO_VD_Screen_A", "AVIDO_VD_Screen_B", "AVIDO_VD_Wall"]
if w is not None:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    res["total_actors"] = len(actors)
    chars, props, screens, texts, lights, bad_mesh, broken_root = [], [], [], [], [], [], []
    all_labels = set()
    for a in actors:
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        cls = a.get_class().get_name()
        all_labels.add(label)
        if (label.startswith("AVIDO_Human") or label.startswith("AVIDO_Agent")):
            loc = a.get_actor_location()
            root = None
            try:
                root = a.get_root_component()
            except Exception:
                try:
                    root = a.root_component
                except Exception:
                    root = None
            chars.append({"label": label, "class": cls,
                          "valid_root": root is not None,
                          "z": round(loc.z, 2)})
        elif label.startswith("W3I_"):
            props.append(label)
        elif "Screen" in label or "screen" in label:
            screens.append(label)
        elif cls == "TextRenderActor":
            texts.append(label)
        elif cls.endswith("Light"):
            mobility = None
            try:
                mobility = str(a.root_component.mobility)
            except Exception:
                pass
            lights.append({"label": label, "mobility": mobility})
        try:
            if cls.startswith("StaticMeshActor"):
                for comp in a.get_components_by_class(unreal.StaticMeshComponent):
                    mesh = comp.static_mesh
                    if mesh is not None:
                        for m in mesh.get_editor_property("materials"):
                            if m is None:
                                bad_mesh.append(label)
                                break
                        break
        except Exception:
            pass
        if label.startswith("Default") or cls in ("WorldSettings", "LevelBounds"):
            continue
        try:
            root = a.get_root_component()
            if root is None and cls not in ("Info", "WorldSettings"):
                broken_root.append(label)
        except Exception:
            pass
    res["characters"] = chars
    res["prop_count"] = len(props)
    res["screens"] = screens
    res["certified_screens_present"] = [s for s in CERTIFIED_SCREENS if s in all_labels]
    res["certified_screens_missing"] = [s for s in CERTIFIED_SCREENS if s not in all_labels]
    res["text_renders"] = texts
    res["light_total"] = len(lights)
    res["light_static"] = sum(1 for l in lights if l["mobility"] and "Static" in l["mobility"] and "Stationary" not in l["mobility"])
    res["light_stationary"] = sum(1 for l in lights if l["mobility"] and "Stationary" in l["mobility"])
    res["bad_mesh_actors"] = sorted(set(bad_mesh))
    res["broken_root_actors"] = sorted(set(broken_root))
    res["ok"] = True
else:
    res["ok"] = False
__bridge_result__ = res
"""

# ------------------------------------------------------- CineMRQ isolation
CINEMRQ_CODE = r"""
import unreal
res = {"ok": True}
ar = unreal.AssetRegistryHelpers.get_asset_registry()
seen = set()
for a in ar.get_assets_by_path("/Game/CineMRQ", recursive=True):
    seen.add(str(a.package_name))
res["cinemrq_assets"] = sorted(seen)
# CineMRQ assets must not be referenced by the certified map's actors
w = unreal.EditorLevelLibrary.get_editor_world()
actors = unreal.EditorLevelLibrary.get_all_level_actors()
leaked = []
for a in actors:
    try:
        cls = a.get_class().get_name()
        if cls in ("LevelSequenceActor", "MoviePipelineConfigBase"):
            leaked.append(a.get_actor_label())
    except Exception:
        pass
res["sequence_actors_in_aividohq"] = leaked
res["ok"] = True
__bridge_result__ = res
"""

# ------------------------------------------------------------- dirty state
DIRTY_CODE = r"""
import unreal
res = {}
try:
    names = unreal.EditorLoadingAndSavingUtils.get_dirty_package_names()
    res["dirty"], res["count"] = list(names), len(names)
except Exception as e:
    res["dirty"], res["count"], res["note"] = None, None, "api unavailable: " + str(e)
res["ok"] = True
__bridge_result__ = res
"""


def census() -> dict:
    return py(CENSUS_CODE)


def main() -> int:
    report: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "read_only": True}
    gates: dict = {}

    # 1. identity ---------------------------------------------------------
    ident = py(r"""
import unreal
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
__bridge_result__ = {
    "project_path": project_path,
    "project_name": project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
    "engine": unreal.SystemLibrary.get_engine_version(),
}
""")
    report["identity"] = ident
    gates["bridge_reachable"] = bool(ident.get("ok"))
    gates["project_identity"] = bool(ident.get("ok") and ident.get("project_name") == "ASSET_Showcase2")

    # 2. census -----------------------------------------------------------
    c1 = census()
    report["census_initial"] = c1
    chars = {c["label"] for c in (c1.get("characters") or [])}
    gates["map_loaded"] = bool(c1.get("ok") and "AividoHQ" in str(c1.get("world", "")))
    gates["characters_8of8"] = len(chars) == 8 and all(
        any(e.lower() in lbl.lower() for lbl in chars) for e in EXPECTED_CHARS)
    gates["actor_count_166"] = c1.get("total_actors") == 166
    gates["props_present"] = c1.get("prop_count", 0) >= 23
    gates["screens_present"] = len(c1.get("certified_screens_missing") or []) == 0
    gates["ui_text_present"] = len(c1.get("text_renders") or []) >= 3
    gates["lights_all_movable"] = (c1.get("light_total", 0) >= 41
                                   and c1.get("light_stationary", 0) == 0
                                   and c1.get("light_static", 0) == 0)
    gates["no_broken_roots"] = len(c1.get("broken_root_actors") or []) == 0
    gates["no_missing_materials"] = len(c1.get("bad_mesh_actors") or []) == 0

    # 3. CineMRQ isolation --------------------------------------------------
    cmrq = py(CINEMRQ_CODE)
    report["cinemrq_isolation"] = cmrq
    gates["cinemrq_isolated"] = bool(
        cmrq.get("ok") and len(cmrq.get("cinemrq_assets") or []) > 0
        and len(cmrq.get("sequence_actors_in_aividohq") or []) == 0)

    # 4. dirty-state readback (informational, never saved) ------------------
    dirty = py(DIRTY_CODE)
    report["dirty_state"] = dirty

    report["gates"] = gates
    report["all_pass"] = all(v is True for v in gates.values())
    report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out_path = None
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"all_pass": report["all_pass"], "gates": gates,
                      "written": str(out_path) if out_path else None}, indent=2, default=str))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
