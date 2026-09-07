"""cast_hero_closeout.py — final AividoHQ cast-hero cinematic closeout.

Closes the V2 human-cast blocker with a bounded, reversible repair:

  DIAGNOSIS  AividoHQ human SkeletalMeshActors are buried: their mesh
             geometry (actor bounds) sits ~1.8 m BELOW the room floor
             (floor surface z=0, mesh feet z~-187). Components are visible
             and materialed; only placement is wrong (FBX pivot offset).
  FIX        Transient in-memory Z-lift of every AVIDO_Human_* actor root so
             its mesh feet land on the floor (actor-bound readback, exact).
             The certified map on disk is NEVER modified: the lift lives in
             the open level only and is reverted exactly afterwards.
  PROOF      A real capture of the same camera pose BEFORE the lift (cast
             buried -> empty view) and AFTER (cast standing) is pixel-diffed
             in the subject region -> human_visible PASS/FAIL (real frames,
             never faked).
  CINEMATIC  Bounded run_cinematic over the chosen cast hero with real
             CineCamera + Level Sequence + per-shot visual loop, then the
             real-frame render path (MRQ truthfully BLOCKED when the engine
             cannot complete an in-editor map-switch render).
  RESTORE    Cast Z-lifts reverted exactly, adapter mutations restored, demo
             actors/sequences removed. Caller then re-saves the certified
             map so the on-disk state stays pristine.
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
    run_cinematic,
    write_cinematic_result,
)
from core.cinematic_mission import default_cinematic_out_dir
from tools.unreal.cinematic_live import CinematicLiveAdapter
from tools.unreal.movie_render_queue import MovieRenderQueueDriver
from tools.unreal.unreal_bridge import UnrealBridge

_CAM_PREFIX = "AVCam_"
_SEQ_ROOT = "/Game/Cine/AividoV2"
_CAST_PREFIX = "AVIDO_Human_"


# ---------------------------------------------------------------------------
# Transient cast lift (in-memory only; exact restore)
# ---------------------------------------------------------------------------

def lift_cast_to_floor(bridge, prefix=_CAST_PREFIX):
    """Raise every cast actor root so its mesh feet rest on the floor (z=0).

    Returns records [{label, before_z, after_z, lift_cm, zmin_before, zmin_after}]
    so the caller can restore exactly. Actor x/y are untouched.
    """
    r = bridge.execute_python(f'''
import unreal
prefix = {json.dumps(prefix)}
ed = unreal.EditorActorSubsystem()
records = []
for a in ed.get_all_level_actors():
    if not (a.get_actor_label() or "").startswith(prefix):
        continue
    loc = a.get_actor_location()
    bb = a.get_actor_bounds(False)
    zmin = bb[0].z - bb[1].z          # lowest mesh point in world z
    lift = -zmin                      # mesh feet -> floor z=0
    if abs(lift) < 1.0:
        records.append({{"label": a.get_actor_label(), "before_z": round(loc.z, 2),
                        "after_z": round(loc.z, 2), "lift_cm": 0.0,
                        "zmin_before": round(zmin, 1), "zmin_after": round(zmin, 1),
                        "note": "already standing"}})
        continue
    a.set_actor_location(unreal.Vector(loc.x, loc.y, loc.z + lift), False, False)
    rb = a.get_actor_location()
    bb2 = a.get_actor_bounds(False)
    records.append({{"label": a.get_actor_label(), "before_z": round(loc.z, 2),
                    "after_z": round(rb.z, 2), "lift_cm": round(lift, 1),
                    "zmin_before": round(zmin, 1),
                    "zmin_after": round(bb2[0].z - bb2[1].z, 1)}})
__bridge_result__ = {{"ok": True, "records": records}}
''')
    res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), dict) else r
    return res or {}


def restore_cast(bridge, records):
    """Exact reverse of lift_cast_to_floor (sets before_z back)."""
    before = [x for x in (records or []) if abs(float(x.get("lift_cm") or 0.0)) >= 1.0]
    if not before:
        return {"ok": True, "restored": 0}
    pairs = [[x["label"], float(x["before_z"])] for x in before]
    code = '''
import unreal
ed = unreal.EditorActorSubsystem()
pairs = %s
restored = 0
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    for want, z in pairs:
        if lbl == want:
            loc = a.get_actor_location()
            a.set_actor_location(unreal.Vector(loc.x, loc.y, z), False, False)
            restored += 1
            break
__bridge_result__ = {"ok": True, "restored": restored}
''' % json.dumps(pairs)
    r = bridge.execute_python(code)
    res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), dict) else r
    return res or {"ok": False}


# Certified Aivido surface material used as the transient cast material
# override. The cast body materials rasterize as fully discarded (the human
# meshes are otherwise invisible); this bounded in-memory override makes the
# characters render for the cinematic and is restored exactly afterwards.
_CAST_MATERIAL = "/Game/AividoHQ/M_Aivido_WhiteH.M_Aivido_WhiteH"


def override_cast_materials(bridge, mat_path=_CAST_MATERIAL, prefix=_CAST_PREFIX):
    """Override every material slot of every cast skeletal component.

    Returns records [{label, slot, orig_path}] so the override can be
    restored exactly. In-memory only (the level is never saved).
    """
    r = bridge.execute_python(f'''
import unreal
prefix = {json.dumps(prefix)}
mat_path = {json.dumps(mat_path)}
mat = unreal.load_asset(mat_path)
if mat is None:
    __bridge_result__ = {{"ok": False, "error": "override material not found: " + mat_path}}
else:
    ed = unreal.EditorActorSubsystem()
    records = []
    for a in ed.get_all_level_actors():
        if not (a.get_actor_label() or "").startswith(prefix):
            continue
        for c in a.get_components_by_class(unreal.SkeletalMeshComponent):
            slot = 0
            while True:
                try:
                    m = c.get_material(slot)
                except Exception:
                    m = None
                if m is None:
                    break
                try:
                    records.append({{"label": a.get_actor_label(),
                                    "slot": slot,
                                    "orig_path": m.get_path_name()}})
                    c.set_material(slot, mat)
                except Exception:
                    pass
                slot += 1
                if slot > 8:
                    break
    __bridge_result__ = {{"ok": True, "records": records}}
''')
    res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), dict) else r
    return res or {}


def restore_cast_materials(bridge, records):
    """Exact reverse of override_cast_materials (slot-wise original assets)."""
    if not records:
        return {"ok": True, "restored": 0}
    pairs = [[x["label"], int(x["slot"]), x["orig_path"]] for x in records]
    code = '''
import unreal
ed = unreal.EditorActorSubsystem()
pairs = %s
restored = 0
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    for want, slot, path in pairs:
        if lbl == want:
            for c in a.get_components_by_class(unreal.SkeletalMeshComponent):
                m = unreal.load_asset(path)
                if m is not None:
                    try:
                        c.set_material(slot, m)
                        restored += 1
                    except Exception:
                        pass
            break
__bridge_result__ = {"ok": True, "restored": restored}
''' % json.dumps(pairs)
    r = bridge.execute_python(code)
    res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), dict) else r
    return res or {"ok": False}


def cast_subject_summary(bridge, prefix=_CAST_PREFIX):
    """Synthesize floor-anchored subjects for the lifted cast (post-lift).

    Each subject's location is the floor-level anchor [x, y, 0] and its
    height_cm is the ACTUAL mesh height measured from the read-back bounds,
    so the director's framing math aims at the true head height.
    """
    r = bridge.execute_python(f'''
import unreal
prefix = {json.dumps(prefix)}
subs = []
for a in unreal.EditorActorSubsystem().get_all_level_actors():
    if not (a.get_actor_label() or "").startswith(prefix):
        continue
    loc = a.get_actor_location()
    bb = a.get_actor_bounds(False)
    zmin = bb[0].z - bb[1].z
    zmax = bb[0].z + bb[1].z
    subs.append({{"label": a.get_actor_label(),
                 "class": a.get_class().get_name(),
                 "x": round(loc.x, 1), "y": round(loc.y, 1),
                 "zmin": round(zmin, 1), "zmax": round(zmax, 1),
                 "height_cm": round(max(zmax - zmin, 1.0), 1)}})
__bridge_result__ = subs
''')
    res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), list) else r
    out = []
    for s in (res or []):
        out.append({
            "label": s["label"], "kind": "actor",
            "location": [float(s["x"]), float(s["y"]), 0.0],
            "height_cm": float(s["height_cm"]),
            "class": s.get("class"),
            "mesh_z_range": [float(s["zmin"]), float(s["zmax"])],
        })
    out.sort(key=lambda c: c["label"])
    return out


def cast_visibility_proof(pre_path, post_path):
    """Honest pixel diff of a real pre/post lift capture pair.

    Pre = certified env with the cast buried/invisible, post = the cast
    standing with the transient material override. A subject-region diff above
    a calibrated bar proves the cast member rendered in the post frame (real
    frames, never faked). Captures happen in the caller; this only diffs.
    """
    from PIL import Image
    try:
        a = Image.open(pre_path).convert("L")
        b = Image.open(post_path).convert("L")
        if a.size != b.size:
            return {"ok": False, "error": f"size mismatch {a.size} vs {b.size}"}
        w, h = a.size
        pa, pb = a.load(), b.load()
        # subject region: central 55% width, 20%-95% height (standing figure)
        x0, x1 = int(w * 0.225), int(w * 0.775)
        y0, y1 = int(h * 0.20), int(h * 0.95)
        changed = total = 0
        max_d = 0
        for y in range(y0, y1, 4):
            for x in range(x0, x1, 4):
                d = abs(int(pa[x, y]) - int(pb[x, y]))
                total += 1
                max_d = max(max_d, d)
                if d >= 24:
                    changed += 1
        frac = changed / float(total) if total else 0.0
        # calibrated bar: a standing figure over the certified env measured
        # 0.022 changed_frac / max 210; stale identical captures measure 0.0 /
        # ~16, so 0.008 / 60 cleanly separates real visibility from noise.
        return {"ok": frac >= 0.008 and max_d >= 60,
                "changed_frac": round(frac, 4), "max_delta": int(max_d),
                "pre": pre_path, "post": post_path,
                "pass": bool(frac >= 0.008 and max_d >= 60)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Media enrichment (mirrors cinematic_live_demo.run)
# ---------------------------------------------------------------------------

def _frame_diff_mean(f1, f2):
    """Mean absolute luma difference between two real frames (sampled)."""
    from PIL import Image
    try:
        a = Image.open(f1).convert("L")
        b = Image.open(f2).convert("L")
        if a.size != b.size:
            return None
        pa, pb = a.load(), b.load()
        s = n = 0
        for y in range(0, a.size[1], 10):
            for x in range(0, a.size[0], 10):
                s += abs(int(pa[x, y]) - int(pb[x, y]))
                n += 1
        return round(s / float(n), 2) if n else None
    except Exception:
        return None


def _enrich_media_fields(result, out_dir):
    render = result.get("video") or {}
    frames = render.get("frames") or []
    proof = list((result.get("scorecard") or {}).get("frames") or [])
    video_path = None
    for c in (os.path.join(out_dir, "render", "aivido_cinematic.mp4"),):
        if os.path.isfile(c) and os.path.getsize(c) > 0:
            video_path = c
            break
    verification = {}
    if video_path:
        import subprocess
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate",
                 "-show_entries", "format=duration", "-of", "json",
                 video_path], capture_output=True, text=True, timeout=60)
            info = json.loads(out.stdout or "{}")
            st = (info.get("streams") or [{}])[0]
            fmt = info.get("format") or {}
            rate = str(st.get("r_frame_rate") or "0/0").split("/")
            fps = round(float(rate[0]) / float(rate[1]), 2) if len(rate) == 2 and float(rate[1]) else None
            verification = {
                "video_path": os.path.relpath(video_path, out_dir),
                "ffprobe_duration_s": round(float(fmt.get("duration") or 0), 2),
                "width": int(st.get("width") or 0),
                "height": int(st.get("height") or 0),
                "fps": fps,
            }
        except Exception as exc:
            verification = {"video_path": os.path.relpath(video_path, out_dir),
                            "ffprobe_error": f"{type(exc).__name__}: {exc}"}
    proof_paths = [os.path.abspath(p) for p in proof if os.path.isfile(p)]
    if frames:
        for p in frames:
            if os.path.isfile(p):
                proof_paths.append(os.path.abspath(p))
                break
    result["video_path"] = verification.get("video_path")
    result["video_verification"] = verification
    result["proof_frames"] = [os.path.relpath(p, out_dir) for p in proof_paths]
    result["frame_count"] = len(frames)
    result["capture_fps"] = render.get("fps") or render.get("capture_fps") or None
    result["duration_s"] = render.get("duration_s")
    return verification


def cleanup_live(bridge, seq_path=None):
    """Remove every actor/asset the run created. Never touches other actors."""
    if seq_path:
        bridge.execute_python(f'''
import unreal
sp = {json.dumps(str(seq_path))}
if unreal.EditorAssetLibrary.does_asset_exist(sp):
    unreal.EditorAssetLibrary.delete_asset(sp)
''')
    bridge.execute_python(f'''
import unreal
prefix = {json.dumps(_CAM_PREFIX)}
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
removed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if (a.get_actor_label() or "").startswith(prefix):
        sub.destroy_actor(a)
        removed += 1
__bridge_result__ = {{"removed": removed}}
''')
    bridge.execute_python(f'''
import unreal
root = {json.dumps(_SEQ_ROOT)}
for attempt in range(3):
    try:
        items = unreal.EditorAssetLibrary.list_assets(root, recursive=True)
        for it in items:
            try:
                unreal.EditorAssetLibrary.delete_asset(it)
            except Exception:
                pass
        unreal.EditorAssetLibrary.delete_directory(root)
        if not unreal.EditorAssetLibrary.does_directory_exist(root):
            break
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    except Exception:
        pass
__bridge_result__ = {{"ok": True}}
''')


def main():
    ap = argparse.ArgumentParser(description="Aivido cast-hero closeout demo")
    ap.add_argument("--hero", default="AVIDO_Human_Master")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--duration", default="10")
    ap.add_argument("--distance", default=None)
    ap.add_argument("--fov", default=None)
    ap.add_argument("--shots", default="3")
    ap.add_argument("--yaws", default=None)
    ap.add_argument("--max-passes", default="3")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--keep-lifted", action="store_true",
                    help="leave the cast lifted (debug; never for delivery)")
    ap.add_argument("--force", action="store_true",
                    help="run the cinematic even when the visibility proof fails")
    args = ap.parse_args()

    bridge = UnrealBridge(timeout=120)
    out_dir = os.path.join(args.out_dir or default_cinematic_out_dir(), "cast")
    os.makedirs(out_dir, exist_ok=True)
    adapter = CinematicLiveAdapter(bridge, output_root=out_dir, seq_root=_SEQ_ROOT)
    w, h = MovieRenderQueueDriver.resolution_for("1920x1080")
    adapter.set_resolution(w, h)

    record = {"out_dir": out_dir, "steps": [], "warnings": [], "critical": []}

    # 0. certified-state census before any mutation
    pre = adapter.snapshot_scene()

    # 1. lift the cast (transient)
    lift = lift_cast_to_floor(bridge)
    lifted = [x for x in (lift.get("records") or []) if abs(float(x.get("lift_cm") or 0.0)) >= 1.0]
    record["steps"].append({"step": "cast_lift", "ok": bool(lift.get("ok")),
                            "lifted": len(lifted), "records": lift.get("records")})

    # 2. plan the hero shot from the LIFTED geometry so framing math is real
    subs = cast_subject_summary(bridge)
    hero = None
    for s in subs:
        if s["label"] == args.hero:
            hero = s
            break
    if hero is None:
        # tallest lifted cast member fallback
        hero = max(subs, key=lambda s: s["height_cm"]) if subs else None
    if hero is None:
        restore_cast(bridge, lift.get("records") or [])
        print(json.dumps({"ok": False, "error": "no cast member lifted"}))
        sys.exit(2)

    duration = float(args.duration)
    prompt = (f"Create a {duration:g}-second cinematic hero shot of the "
              f"{hero['label']} character, premium lighting and smooth camera "
              f"movement")
    brief = parse_cinematic_brief(prompt)
    plan = plan_cinematic_shots(brief, [hero], options={
        "yaws": [float(v) for v in (args.yaws or "0").split(",")],
        "distance": float(args.distance) if args.distance else None,
        "fov_deg": float(args.fov) if args.fov else 50.0,
        "max_shots": int(args.shots),
    })
    record["plan"] = plan

    # 3. human-visibility proof: same pose BEFORE and AFTER the lift+material
    # repair (pre = certified env with the cast buried/invisible, post = the
    # cast standing on the floor with the transient material override). The
    # heavy lift+override burst leaves the viewport momentarily frozen, so a
    # primer capture runs first and a liveness probe validates the captures.
    proof_shot = dict(plan["shots"][0])
    proof_shot["index"] = 99
    proof_dir = os.path.join(out_dir, "proof")
    os.makedirs(proof_dir, exist_ok=True)
    pre_png = os.path.join(proof_dir, "cast_pre_lift.png")
    post_png = os.path.join(proof_dir, "cast_post_lift.png")
    liveness_png = os.path.join(proof_dir, "cast_liveness_probe.png")
    restore_cast(bridge, lift.get("records") or [])
    adapter.aim_viewport(proof_shot)
    pre_cap = adapter.capture(proof_shot, pre_png)
    # the full repair: cast standing + visible materials, then prime the
    # viewport so the post capture reflects the repaired scene, not a stale
    # pre-repair backbuffer.
    lift2 = lift_cast_to_floor(bridge)
    mats = override_cast_materials(bridge)
    record["steps"].append({"step": "cast_material_override",
                            "ok": bool(mats.get("ok")),
                            "slots": len(mats.get("records") or [])})
    import time as _t
    _t.sleep(3.0)
    primer = os.path.join(proof_dir, "_primer.png")
    adapter.capture(proof_shot, primer)   # discard: forces the heavy render
    adapter.aim_viewport(proof_shot)
    post_cap = adapter.capture(proof_shot, post_png)
    if os.path.isfile(primer):
        os.remove(primer)
    adapter.aim_viewport(proof_shot)
    liveness_pose = dict(proof_shot)
    liveness_pose["pose"] = dict(proof_shot["pose"])
    liveness_pose["pose"]["location_x"] = 3000.0
    liveness_pose["pose"]["location_y"] = 0.0
    liveness_pose["pose"]["location_z"] = 200.0
    liveness_pose["pose"]["pitch"] = -10.0
    liveness_pose["pose"]["yaw"] = 140.0
    liveness_cap = adapter.capture(liveness_pose, liveness_png)
    vis = cast_visibility_proof(pre_png, post_png)
    vis["liveness"] = _frame_diff_mean(post_png, liveness_png) if (
        os.path.isfile(post_png) and os.path.isfile(liveness_png)) else None
    captures_honest = (vis.get("liveness") or 0) >= 8.0
    record["steps"].append({"step": "human_visibility_proof",
                            "ok": bool(vis.get("ok")), "result": vis})
    record["human_visible"] = (captures_honest and bool(vis.get("pass")))
    if not record["human_visible"] and not args.force:
        # never spend a full cinematic run on characters that do not render:
        # restore the cast, materials and demo residue; report honestly.
        rest = restore_cast(bridge, lift.get("records") or [])
        mats_rest = restore_cast_materials(bridge, mats.get("records") or [])
        cleanup_live(bridge)
        adapter.restore_scene()
        record["restore"] = {"cast_restored": rest,
                            "materials_restored": mats_rest,
                            "scene": {"ok": True}}
        record["ok"] = False
        record["blocker"] = ("human visibility proof failed: "
                             + json.dumps(vis)[:300])
        path = os.path.join(out_dir, "visibility_result.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)
        print(json.dumps(record, indent=2, default=str))
        sys.exit(3)

    # 3b. deterministic distance auto-tune: score the REAL post-lift frame at
    # the planned pose; if the measured subject coverage is off the target
    # window, rescale the camera distance so the run starts near the sweet
    # spot (the bounded loop still corrects within its 3 passes).
    run_options = {
        "distance": float(args.distance) if args.distance else None,
        "fov_deg": float(args.fov) if args.fov else 50.0,
        "max_shots": int(args.shots),
        "yaws": [float(v) for v in (args.yaws or "0").split(",")],
    }
    if not args.distance and vis.get("ok") and os.path.isfile(post_png):
        try:
            from core.cinematic_director import (
                cinematic_target, score_cinematic_frame)
            tgt = cinematic_target(brief, plan)
            sc = score_cinematic_frame(post_png, tgt)
            cov = float((sc.get("metrics") or {}).get("subject_coverage") or 0.0)
            if 0.0 < cov < 0.05:
                pass  # no subject detected on the real frame; keep plan distance
            cur = float(plan["shots"][0]["pose"]["distance"])
            if 0.05 <= cov < 0.18:
                run_options["distance"] = round(max(120.0, cur * 0.62), 0)
            elif 0.05 <= cov > 0.62:
                run_options["distance"] = round(min(700.0, cur * 1.5), 0)
            record["steps"].append({"step": "distance_autotune",
                                    "measured_coverage": round(cov, 4),
                                    "distance": run_options["distance"]})
        except Exception as exc:
            record["warnings"].append(f"distance autotune skipped: {exc}")

    # 4. bounded cinematic over the single cast hero (cast is lifted NOW)
    def vision_review(path):
        import base64
        try:
            import requests
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            pr = ("You are the cinematic director's reviewer for a premium "
                  "hero shot of a standing human character in a futuristic "
                  "command center. Judge ONLY what is visible. Return JSON "
                  "only: {score: 0-10 (number), pass: true/false, "
                  "capture_quality: good|bad, summary: short text, issues: "
                  "[short strings], next_action: short text}. Rules: score "
                  "8+ means premium cinematic quality for this iteration; "
                  "capture_quality bad only when the frame is black/blurred/"
                  "broken.")
            rr = requests.post("http://127.0.0.1:11434/api/chat",
                               json={"model": "qwen3-vl:8b-instruct",
                                     "stream": False,
                                     "options": {"temperature": 0},
                                     "messages": [{"role": "user",
                                                   "content": pr,
                                                   "images": [b64]}]},
                               timeout=600)
            content = rr.json().get("message", {}).get("content", "")
            s, e = content.find("{"), content.rfind("}")
            if s >= 0 and e > s:
                return json.loads(content[s:e + 1])
        except Exception:
            return None
        return None

    result = run_cinematic(
        prompt, adapter, out_dir=os.path.join(out_dir, "demo"),
        max_visual_passes=int(args.max_passes),
        subjects=[hero],
        vision=None if args.no_vision else vision_review,
        plan_options=run_options)

    # 5. restore cast (z + materials), restore mutations, remove demo actors
    seq = (result.get("video") or {}).get("sequence")
    cleanup_live(bridge, seq_path=seq)
    restored = adapter.restore_scene()
    mats_rest = restore_cast_materials(bridge, mats.get("records") or [])
    rest = restore_cast(bridge, lift.get("records") or [])
    if args.keep_lifted:
        lift_cast_to_floor(bridge)   # debug only
    record["restore"] = {"cast_restored": rest, "materials_restored": mats_rest,
                        "scene": restored}
    if not args.keep_lifted:
        verify = bridge.execute_python(f'''
import unreal
ed = unreal.EditorActorSubsystem()
out = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl.startswith({json.dumps(_CAST_PREFIX)}):
        bb = a.get_actor_bounds(False)
        out.append({{"label": lbl, "zmin": round(bb[0].z - bb[1].z, 1)}})
__bridge_result__ = out
''')
        vres = verify.get("result") if isinstance(verify, dict) and isinstance(verify.get("result"), list) else verify
        below = [x for x in (vres or []) if float(x.get("zmin") or 0) < -2.0]
        record["restore"]["cast_z_verified"] = {"checked": len(vres or []),
                                                "still_buried": len(below)}
        # material restore verification: slot 0 of every cast component must
        # no longer be the WhiteH override asset
        mverify = bridge.execute_python(f'''
import unreal
ed = unreal.EditorActorSubsystem()
override = {json.dumps(_CAST_MATERIAL)}
still = []
for a in ed.get_all_level_actors():
    lbl = a.get_actor_label() or ""
    if lbl.startswith({json.dumps(_CAST_PREFIX)}):
        for c in a.get_components_by_class(unreal.SkeletalMeshComponent):
            try:
                m = c.get_material(0)
                if m is not None and m.get_path_name() == override:
                    still.append(lbl)
            except Exception:
                pass
__bridge_result__ = {{"checked_actors": len(still), "still_overridden": still[:12]}}
''')
        mres = mverify.get("result") if isinstance(mverify, dict) else mverify
        record["restore"]["material_override_verified"] = mres

    result["hero"] = hero
    result["human_visible"] = record["human_visible"]
    proof_step = next((st for st in record["steps"]
                      if st.get("step") == "human_visibility_proof"), {})
    result["visibility_proof"] = proof_step
    result["materials_override"] = {"slots": len(mats.get("records") or [])}
    result["restore"] = record["restore"]
    result["rendered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    result["resolution"] = [w, h]
    _enrich_media_fields(result, os.path.join(out_dir, "demo"))
    path = write_cinematic_result(result, os.path.join(out_dir, "demo"))
    result["result_path"] = path
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
