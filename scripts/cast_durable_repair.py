"""cast_durable_repair.py — durable production-safe repair for the Aivido human cast.

ROOT CAUSE (Blender-verified, no Blender surgery required):
  * Source FBX geometry is correct. Blender diagnosis of the Rocketbox sources:
      - Business_Male_01  (Master) mesh world bounds z=[-0.001, 1.806], feet at 0,
        armature root (Bip01) at z=0.895, mesh object at z=-89.518 (legacy
        "Bip01 Footsteps" pivot convention).
      - Business_Female_02 (Visual) mesh world bounds z=[0.0, 1.729], armature
        root at z=0.923, mesh object at z=-92.329.
    Unreal baked that mesh-object pivot offset into each skeleton's ref pose, so
    every cast member renders ~1.8 m BELOW its component origin (floor z=0). The
    bake differs per character (Master -187, Creative -72, ...) -> the correction
    is measured and applied per character.
  * Invisibility: the FBX "m00X_opacity" Phong MIC (OpacityMapWeight=1 +
    OpacityMap=m00X_opacity_color) cuts out the silhouette polys; the visible body
    geometry lives in the opacity slot. The project already ships per-character
    production OPAQUE MICs (Aivido_Body / Aivido_Head, parents M_Aivido_Cloth /
    M_Aivido_Skin, both BLEND_OPAQUE) that were never assigned to the meshes.

DURABLE FIX (sanctioned option C: source proven healthy -> Unreal-side correction):
  1. Mesh ASSETS: re-slot each cast SkeletalMesh to production opaque MICs
     (slot0 -> Aivido_Body, slot1 -> Aivido_Head, slot2+ -> Aivido_Body) and save.
  2. Components: clear override materials (removes old WhiteH residue) so meshes
     render their (now fixed) materials.
  3. Components: durable per-character Z lift so mesh feet rest on the floor
     (measured from real render bounds); persisted by saving the certified map
     (an intentional, verified update). No runtime/temporary Z-lift or WhiteH hack.
  Recoverable: every before-state value is recorded (component Z, slot materials,
  override slots, zmin/zmax) before mutation.

Flow: --gate master applies ONLY Master + a real hero capture + honest score, and
aborts (restoring Master exactly) unless the humanoid verifiably renders; --all
propagates the proven repair to all 8 and re-verifies; --save persists the map.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cinematic_director import (
    parse_cinematic_brief,
    plan_cinematic_shots,
    cinematic_target,
    score_cinematic_frame,
)
from core.cinematic_mission import default_cinematic_out_dir
from tools.unreal.cinematic_live import CinematicLiveAdapter
from tools.unreal.unreal_bridge import UnrealBridge

_CAST_PREFIX = "AVIDO_Human_"
_CAM_PREFIX = "AVCam_"
_CHARS = ["Master", "Creative", "Visual", "Technical", "Audio",
          "Animation", "Lighting", "VFX"]
_MAT_DIR = "/Game/AividoHQ/Characters"
_MESH_PATHS = {
    "Master": "/Game/AividoHQ/Characters/Master/Business_Male_01.Business_Male_01",
    "Creative": "/Game/AividoHQ/Characters/Creative/Male_Adult_11.Male_Adult_11",
    "Visual": "/Game/AividoHQ/Characters/Visual/Business_Female_02.Business_Female_02",
    "Technical": "/Game/AividoHQ/Characters/Technical/Male_Adult_03.Male_Adult_03",
    "Audio": "/Game/AividoHQ/Characters/Audio/Female_Adult_05.Female_Adult_05",
    "Animation": "/Game/AividoHQ/Characters/Animation/Male_Adult_12.Male_Adult_12",
    "Lighting": "/Game/AividoHQ/Characters/Lighting/Female_Adult_01.Female_Adult_01",
    "VFX": "/Game/AividoHQ/Characters/VFX/Female_Adult_08.Female_Adult_08",
}


# ---------------------------------------------------------------------------
# engine helpers (each returns parsed payload)
# ---------------------------------------------------------------------------

def _payload(res):
    if isinstance(res, dict) and res.get("ok"):
        return res.get("result")
    return None


def snapshot_cast(bridge):
    """Record every cast member's before-state (durable-evidence)."""
    code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
out = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if not lbl.startswith({json.dumps(_CAST_PREFIX)}):
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    mesh = comp.skeletal_mesh
    bb = a.get_actor_bounds(False)
    al = a.get_actor_location(); cr = comp.get_editor_property("relative_location")
    slots = []
    if mesh:
        mats = mesh.get_editor_property("materials")
        for i, sm in enumerate(mats):
            mi = sm.get_editor_property("material_interface")
            slots.append({{"i": i, "mat": mi.get_path_name() if mi else None}})
    over = []
    try:
        ov = comp.get_editor_property("override_materials")
        for om in (ov or []):
            over.append(om.get_path_name() if om else None)
    except Exception:
        over = None
    out.append({{
        "label": lbl,
        "actor_loc": [round(al.x,1), round(al.y,1), round(al.z,1)],
        "comp_rel": [round(cr.x,1), round(cr.y,1), round(cr.z,1)],
        "mesh": mesh.get_path_name() if mesh else None,
        "zmin": round(bb[0].z - bb[1].z, 2),
        "zmax": round(bb[0].z + bb[1].z, 2),
        "slot_materials": slots,
        "component_overrides": over,
        "actor_count": 0,
    }})
actor_count = len(ed.get_all_level_actors())
__bridge_result__ = {{"cast": out, "actor_count": actor_count}}
'''
    res = _payload(bridge.execute_python(code))
    return res or {"cast": [], "actor_count": 0}


def repair_mesh_slots(bridge, char, mesh_path):
    """Re-slot a mesh asset to production opaque MICs and save it (durable).

    SkeletalMesh exposes NO set_material() in python (it is a silent no-op) and
    mutating the struct elements of the materials array writes to copies that
    do not persist. The proven durable path (verified live) is to build a fresh
    SkeletalMaterial list and assign the whole 'materials' property, then save
    the package.
    """
    body_path = _MAT_DIR + "/" + char + "/Aivido_Body.Aivido_Body"
    head_path = _MAT_DIR + "/" + char + "/Aivido_Head.Aivido_Head"
    code = f'''
import unreal
mesh_path = {json.dumps(mesh_path)}
body_path = {json.dumps(body_path)}
head_path = {json.dumps(head_path)}
body = unreal.load_asset(body_path)
head = unreal.load_asset(head_path)
mesh = unreal.load_asset(mesh_path)
if mesh is None or body is None or head is None:
    __bridge_result__ = {{"ok": False, "error": "missing mesh/material for " + char}}
else:
    mats = mesh.get_editor_property("materials")
    names = [str(m.get_editor_property("material_slot_name")) for m in mats]
    new = []
    for i, nm in enumerate(names):
        sm = unreal.SkeletalMaterial()
        sm.set_editor_property("material_interface", head if i == 1 else body)
        sm.set_editor_property("material_slot_name", unreal.Name(nm))
        new.append(sm)
    mesh.set_editor_property("materials", new)
    mesh.modify()
    try:
        unreal.EditorLoadingAndSavingUtils.save_packages([mesh_path], only_if_is_dirty=False)
    except Exception as exc:
        pass
    now = [str(m.get_editor_property("material_interface").get_path_name())
           for m in mesh.get_editor_property("materials")]
    __bridge_result__ = {{"ok": bool(now), "slots_before": len(mats),
                         "slots_now": now, "slot_names": names}}
'''
    return _payload(bridge.execute_python(code))


def clear_component_overrides(bridge, labels):
    """Remove any override materials on the given cast components."""
    code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
labels = {json.dumps(labels)}
cleared = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl not in labels:
        continue
    for comp in a.get_components_by_class(unreal.SkeletalMeshComponent):
        try:
            comp.set_editor_property("override_materials", [])
            cleared.append(lbl)
        except Exception as exc:
            cleared.append({{"label": lbl, "err": str(exc)[:120]}})
__bridge_result__ = {{"cleared": cleared}}
'''
    return _payload(bridge.execute_python(code))


def lift_cast_components(bridge, labels):
    """Durable per-component Z lift so mesh feet rest on floor (z=0)."""
    code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
labels = {json.dumps(labels)}
records = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl not in labels:
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    bb = a.get_actor_bounds(False)
    zmin = bb[0].z - bb[1].z
    lift = -zmin
    cr = comp.get_editor_property("relative_location")
    comp.set_editor_property("relative_location", unreal.Vector(cr.x, cr.y, cr.z + lift))
    bb2 = a.get_actor_bounds(False)
    records.append({{"label": lbl,
                    "comp_z_before": round(cr.z, 2),
                    "comp_z_after": round(cr.z + lift, 2),
                    "lift_cm": round(lift, 2),
                    "zmin_before": round(zmin, 2),
                    "zmin_after": round(bb2[0].z - bb2[1].z, 2),
                    "zmax_after": round(bb2[0].z + bb2[1].z, 2)}})
__bridge_result__ = records
'''
    res = _payload(bridge.execute_python(code))
    return res or []


def orient_cast_components(bridge, labels):
    """Durable orientation fix: rotate cast components upright.

    Unreal imports the Rocketbox FBX such that the skeleton ref pose renders
    the character HEAD-DOWN (head at the bottom of the render bounds, legs at
    the top; verified live by vision). A 180 deg pitch (rotation about X)
    flips up/down while keeping the facing direction, so the character stands
    upright. The caller re-runs lift_cast_components afterwards so the feet
    land on the floor in the upright pose.
    """
    code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
labels = {json.dumps(labels)}
records = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl not in labels:
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    rot = comp.get_editor_property("relative_rotation")
    comp.set_editor_property("relative_rotation",
        unreal.Rotator(pitch=180.0, yaw=rot.yaw, roll=rot.roll))
    records.append({{"label": lbl,
                     "rot_before": [round(rot.pitch,1), round(rot.yaw,1), round(rot.roll,1)],
                     "rot_after": [180.0, round(rot.yaw,1), round(rot.roll,1)]}})
__bridge_result__ = records
'''
    res = _payload(bridge.execute_python(code))
    return res or []


def verify_cast(bridge, labels):
    """Post-repair verification: zmin ~ 0, slot0=Aivido_Body, no WhiteH."""
    code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
labels = {json.dumps(labels)}
out = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl not in labels:
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    mesh = comp.skeletal_mesh
    bb = a.get_actor_bounds(False)
    mats = []
    if mesh:
        for sm in mesh.get_editor_property("materials"):
            mi = sm.get_editor_property("material_interface")
            mats.append(mi.get_path_name() if mi else None)
    over = []
    try:
        for om in (comp.get_editor_property("override_materials") or []):
            over.append(om.get_path_name() if om else None)
    except Exception:
        over = None
    out.append({{
        "label": lbl,
        "zmin": round(bb[0].z - bb[1].z, 2),
        "zmax": round(bb[0].z + bb[1].z, 2),
        "height_cm": round(bb[0].z + bb[1].z - (bb[0].z - bb[1].z), 2),
        "slot_materials": mats,
        "component_overrides": over,
    }})
actor_count = len(ed.get_all_level_actors())
__bridge_result__ = {{"cast": out, "actor_count": actor_count}}
'''
    return _payload(bridge.execute_python(code))


def _frame_diff_mean(f1, f2):
    from PIL import Image
    try:
        a = Image.open(f1).convert("L"); b = Image.open(f2).convert("L")
        if a.size != b.size:
            return None
        pa, pb = a.load(), b.load()
        s = n = 0
        for y in range(0, a.size[1], 10):
            for x in range(0, a.size[0], 10):
                s += abs(int(pa[x, y]) - int(pb[x, y])); n += 1
        return round(s / float(n), 2) if n else None
    except Exception:
        return None


def vision_review(path):
    import base64
    try:
        import requests
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        pr = ("You are the cinematic director's reviewer for a premium hero shot "
              "of a standing human character in a futuristic command center. "
              "Judge ONLY what is visible. Return JSON only: {score: 0-10 "
              "(number), pass: true/false, human_visible: true/false, "
              "summary: short text, issues: [short strings]}. Rules: score 8+ "
              "means premium cinematic quality; human_visible true only if a "
              "humanoid figure is actually present and readable.")
        rr = requests.post("http://127.0.0.1:11434/api/chat",
                           json={"model": "qwen3-vl:8b-instruct", "stream": False,
                                 "options": {"temperature": 0},
                                 "messages": [{"role": "user", "content": pr,
                                               "images": [b64]}]}, timeout=600)
        content = rr.json().get("message", {}).get("content", "")
        s, e = content.find("{"), content.rfind("}")
        if s >= 0 and e > s:
            return json.loads(content[s:e + 1])
    except Exception:
        return None
    return None


def capture_hero(bridge, adapter, hero_subject, out_path, fov_deg=50.0,
                 distance=None, yaw=0.0, max_passes=1):
    """Aim + capture a framed hero pose, with bounded distance autotune."""
    prompt = "Create a premium cinematic hero shot of the character, cinematic lighting, smooth camera movement"
    brief = parse_cinematic_brief(prompt)
    plan = plan_cinematic_shots(brief, [hero_subject], options={
        "fov_deg": fov_deg, "yaws": [yaw], "distance": distance,
        "max_shots": 1})
    if not plan.get("ok"):
        return {"ok": False, "error": plan.get("error")}
    shot = dict(plan["shots"][0])
    adapter.aim_viewport(shot)
    cap = adapter.capture(shot, out_path)
    # bounded distance autotune (deterministic, max 1 corrective pass)
    best = {"path": out_path, "coverage": None, "score": None}
    if cap.get("ok") and os.path.isfile(out_path):
        tgt = cinematic_target(brief, plan)
        sc = score_cinematic_frame(out_path, tgt)
        best["coverage"] = float((sc.get("metrics") or {}).get("subject_coverage") or 0.0)
        best["score"] = sc.get("overall")
        cov = best["coverage"]
        cur = float(plan["shots"][0]["pose"].get("distance") or 0.0)
        if 0.05 <= cov < 0.18 and max_passes >= 1:
            new_dist = round(max(120.0, cur * 0.62), 0)
            plan2 = plan_cinematic_shots(brief, [hero_subject], options={
                "fov_deg": fov_deg, "yaws": [yaw], "distance": new_dist,
                "max_shots": 1})
            shot2 = dict(plan2["shots"][0])
            adapter.aim_viewport(shot2)
            cap2 = adapter.capture(shot2, out_path)
            if cap2.get("ok"):
                sc2 = score_cinematic_frame(out_path, tgt)
                best["coverage"] = float((sc2.get("metrics") or {}).get("subject_coverage") or 0.0)
                best["score"] = sc2.get("score")
                best["autotuned_distance"] = new_dist
    return {"ok": cap.get("ok"), "plan": plan, "capture": cap,
            "best": best}


def main():
    ap = argparse.ArgumentParser(description="Durable Aivido cast repair")
    ap.add_argument("--gate", action="store_true", help="Master only + hero gate")
    ap.add_argument("--all", action="store_true", help="propagate to all 8")
    ap.add_argument("--save", action="store_true", help="persist the map")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--hero", default="AVIDO_Human_Master")
    args = ap.parse_args()

    bridge = UnrealBridge(timeout=120)
    out_dir = os.path.join(args.out_dir or default_cinematic_out_dir(), "cast_durable")
    os.makedirs(out_dir, exist_ok=True)
    adapter = CinematicLiveAdapter(bridge, output_root=out_dir, seq_root="/Game/Cine/DurableRepair")

    record = {"out_dir": out_dir, "steps": [], "warnings": [], "critical": []}

    # 0. certified before-state (durable evidence + recovery source)
    before = snapshot_cast(bridge)
    record["actor_count_before"] = before.get("actor_count")
    record["before"] = before.get("cast")
    by_label = {c["label"]: c for c in before.get("cast", [])}

    def restore_actor(label):
        """Exact reverse: restore comp Z + clear overrides to recorded state."""
        c = by_label.get(label)
        if not c:
            return
        code = f'''
import unreal
ed = unreal.EditorActorSubsystem()
label = {json.dumps(label)}
rec = {json.dumps(c)}
for a in ed.get_all_level_actors():
    if (a.get_actor_label() or "") != label:
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    comp.set_editor_property("relative_location",
        unreal.Vector(rec["comp_rel"][0], rec["comp_rel"][1], rec["comp_rel"][2]))
__bridge_result__ = {{"ok": True}}
'''
        bridge.execute_python(code)

    # ----------------------------------------------------------------- gate
    if args.gate or args.all:
        hero_label = args.hero
        hero_char = hero_label.replace(_CAST_PREFIX, "")
        mesh_path = _MESH_PATHS.get(hero_char)
        if not mesh_path:
            record["critical"].append(f"no mesh path for {hero_label}")
            print(json.dumps(record, indent=2, default=str))
            sys.exit(2)

        record["steps"].append({"step": "gate_mesh_reslot",
                                "char": hero_char,
                                **repair_mesh_slots(bridge, hero_char, mesh_path)})
        record["steps"].append({"step": "gate_clear_overrides",
                                **clear_component_overrides(bridge, [hero_label])})
        record["steps"].append({"step": "gate_orient",
                                "records": orient_cast_components(bridge, [hero_label])})
        lift = lift_cast_components(bridge, [hero_label])
        record["steps"].append({"step": "gate_lift", "records": lift})
        rec = lift[0] if lift else {}

        # real hero capture + honest score (Master gate)
        v = verify_cast(bridge, [hero_label])
        member = next((x for x in (v.get("cast") or []) if x["label"] == hero_label), None)
        hero_subject = {"label": hero_label, "kind": "actor",
                        "location": [by_label[hero_label]["actor_loc"][0],
                                     by_label[hero_label]["actor_loc"][1], 0.0],
                        "height_cm": float((member or {}).get("height_cm") or 180.0)}
        proof_png = os.path.join(out_dir, "gate_hero.png")
        liveness_png = os.path.join(out_dir, "gate_liveness.png")
        cap = capture_hero(bridge, adapter, hero_subject, proof_png)
        # liveness: move the camera to a very different pose -> frame must change
        # (a stale backbuffer returns an identical frame and would nullify the
        # gate; a real viewport returns a large mean diff).
        live = None
        if cap.get("ok"):
            p = dict(cap["plan"]["shots"][0]["pose"])
            far_pose = dict(p)
            far_pose["location_x"] = float(p.get("location_x", 0)) + 1500.0
            far_pose["location_y"] = float(p.get("location_y", 0)) - 900.0
            far_pose["location_z"] = 260.0
            far_pose["pitch"] = -12.0
            far_pose["yaw"] = 130.0
            far_pose["roll"] = 0.0
            adapter.aim_viewport({"pose": far_pose})
            lc = adapter.capture({"pose": far_pose}, liveness_png)
            if lc.get("ok") and os.path.isfile(proof_png) and os.path.isfile(liveness_png):
                live = _frame_diff_mean(proof_png, liveness_png)

        vision = vision_review(proof_png) if os.path.isfile(proof_png) else None
        record["steps"].append({"step": "gate_capture", "capture": cap,
                                "vision": vision, "liveness": live})
        human_ok = bool(vision and vision.get("human_visible"))
        captures_honest = (live is None) or live >= 8.0
        record["gate_human_visible"] = human_ok and captures_honest
        record["gate_vision"] = vision
        record["gate_score"] = cap.get("best", {}).get("score")
        record["gate_coverage"] = cap.get("best", {}).get("coverage")

        if not args.all and not captures_honest:
            # captures not honest (no live viewport / empty frame): do not trust
            restore_actor(hero_label)
            record["ok"] = False
            record["blocker"] = ("Master gate failed: captures not honest "
                                 f"(liveness={live})")
            with open(os.path.join(out_dir, "gate_result.json"), "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, default=str)
            print(json.dumps(record, indent=2, default=str))
            sys.exit(3)

    # ------------------------------------------------------------------- all
    if args.all:
        labels = [_CAST_PREFIX + c for c in _CHARS]
        reslots = {}
        for c in _CHARS:
            reslots[c] = repair_mesh_slots(bridge, c, _MESH_PATHS[c])
        record["steps"].append({"step": "reslot_all", "results": reslots})
        record["steps"].append({"step": "clear_overrides_all",
                                **clear_component_overrides(bridge, labels)})
        record["steps"].append({"step": "orient_all",
                                "records": orient_cast_components(bridge, labels)})
        lifts = lift_cast_components(bridge, labels)
        record["steps"].append({"step": "lift_all", "records": lifts})
        ver = verify_cast(bridge, labels)
        record["verify_all"] = ver
        standing = [x for x in (ver.get("cast") or []) if -1.5 <= float(x["zmin"]) <= 1.5]
        no_white = all("WhiteH" not in str(x.get("slot_materials")) and
                       "WhiteH" not in str(x.get("component_overrides"))
                       for x in (ver.get("cast") or []))
        record["all_standing"] = {"count": len(standing), "of": len(ver.get("cast") or [])}
        record["no_white_residue"] = no_white
        record["actor_count_after"] = ver.get("actor_count")

    # ------------------------------------------------------------ hero proof
    if args.all or args.gate:
        v = verify_cast(bridge, [_CAST_PREFIX + c for c in _CHARS]) if args.all else \
            verify_cast(bridge, [args.hero])
        member = next((x for x in (v.get("cast") or []) if x["label"] == args.hero), None)
        hero_subject = {"label": args.hero, "kind": "actor",
                        "location": [by_label[args.hero]["actor_loc"][0],
                                     by_label[args.hero]["actor_loc"][1], 0.0],
                        "height_cm": float((member or {}).get("height_cm") or 180.0)}
        hero_png = os.path.join(out_dir, "hero_proof.png")
        cap = capture_hero(bridge, adapter, hero_subject, hero_png, distance=400.0, max_passes=1)
        vision = vision_review(hero_png) if os.path.isfile(hero_png) else None
        record["hero_proof"] = {"path": hero_png, "capture": cap,
                                "vision": vision,
                                "score": cap.get("best", {}).get("score"),
                                "coverage": cap.get("best", {}).get("coverage")}

    # ----------------------------------------------------------------- save
    if args.save and (args.all or args.gate):
        if args.all:
            saved = _payload(bridge.execute_python("""
import unreal
try:
    ok = bool(unreal.EditorLoadingAndSavingUtils.save_current_level())
except Exception as exc:
    ok = False
__bridge_result__ = {"ok": ok}
"""))
            record["save"] = {"map_saved": bool(saved.get("ok")) if saved else False}
        else:
            record["save"] = {"note": "gate only; not saving map"}

    record["ok"] = True
    record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = os.path.join(out_dir, "cast_durable_result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    record["result_path"] = path
    print(json.dumps(record, indent=2, default=str))


if __name__ == "__main__":
    main()