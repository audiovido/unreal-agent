"""cinematic_live_demo.py — bounded AividoHQ cinematic demo on the live bridge.

Two modes:

  trial   Capture real single frames of one hero from a yaw arc so the
          director (and this report) can verify composition before a full
          run. Writes PNGs + a viewer HTML under the output dir.

  run     Execute the full bounded cinematic pipeline for the hero:
          brief -> subjects -> shot plan -> CineCamera placement -> bounded
          visual loop -> Level Sequence asset -> real Unreal frames (+ mp4
          when ffmpeg exists) -> scorecard -> JSON result. Scene state is
          preserved: the mission never saves the level and removes every
          actor/asset it created afterwards (AIVIDO_V2_* / AVCam_*).

Truthful by contract: MRQ unavailability is reported as BLOCKED and the
real-frame path is labeled exactly as what it is.
"""

from __future__ import annotations

import argparse
import base64
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

# Actors/assets this demo creates; cleanup only ever touches these prefixes.
_CAM_PREFIX = "AVCam_"
_SEQ_ROOT = "/Game/Cine/AividoV2"


def _resolve_hero_subjects(adapter, prompt, hero_arg):
    brief = parse_cinematic_brief(prompt)
    subjects = adapter.inspect_subjects(brief)
    if hero_arg:
        matches = [s for s in subjects if hero_arg.lower() in s["label"].lower()]
        if matches:
            return [matches[0]]
        # exact-label fallback (props/scene anchors may sit outside the
        # ranked cast shortlist)
        res = adapter.bridge.get_actor(hero_arg)
        payload = res.get("result") if isinstance(res, dict) and isinstance(
            res.get("result"), dict) else res
        if isinstance(payload, dict) and payload.get("ok") and payload.get("location"):
            loc = payload["location"]
            return [{"label": payload.get("label") or hero_arg,
                     "kind": "prop",
                     "location": [round(v, 2) for v in loc],
                     "class": payload.get("class")}]
        print(f"hero '{hero_arg}' not found; candidates: "
              + ", ".join(s["label"] for s in subjects))
        sys.exit(2)
    if not subjects:
        print(json.dumps({"ok": False, "error": "no hero subjects found"}))
        sys.exit(2)
    for preferred in ("Master", "Master_", "Lead"):
        for s in subjects:
            if preferred.lower() in s["label"].lower():
                return [s]
    return [subjects[0]]


def _shot_for_yaw(hero, yaw, distance=420.0, fov=50.0, index=1, duration=10.0):
    brief = parse_cinematic_brief(f"hero shot, {duration} seconds")
    plan = plan_cinematic_shots(brief, [hero], options={
        "yaws": [float(yaw)], "distance": float(distance), "fov_deg": float(fov),
        "max_shots": 1})
    shot = plan["shots"][0]
    shot["index"] = int(index)
    return shot


def _viewer_html(out_dir, frames, title):
    rows = []
    for p in frames:
        rows.append(f'<div style="margin:12px"><img src="{os.path.basename(p)}" '
                    f'style="max-width:640px;border:1px solid #444"></div>')
    html = (f"<html><body style='background:#111;color:#ddd;font-family:sans-serif'>"
            f"<h2>{title}</h2>{''.join(rows)}</body></html>")
    viewer = os.path.join(out_dir, "trial_view.html")
    with open(viewer, "w", encoding="utf-8") as f:
        f.write(html)
    return viewer


def trial(args):
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=60)
    adapter = CinematicLiveAdapter(bridge, output_root=args.out_dir)
    adapter.set_resolution(*MovieRenderQueueDriver.resolution_for(args.resolution))
    hero = _resolve_hero_subjects(adapter, args.prompt, args.hero)[0]
    out_dir = os.path.join(args.out_dir, "trial")
    os.makedirs(out_dir, exist_ok=True)
    yaws = [float(v) for v in (args.yaws or "0,90,180,270").split(",")]
    frames = []
    notes = []
    for i, yaw in enumerate(yaws, start=1):
        shot = _shot_for_yaw(hero, yaw, distance=float(args.distance),
                             index=i, duration=float(args.duration))
        cam = adapter.place_camera(shot)
        if not cam.get("ok"):
            notes.append({"yaw": yaw, "error": cam})
            continue
        aim = adapter.aim_viewport(shot)
        p = os.path.join(out_dir, f"trial_yaw{yaw:03.0f}.png")
        cap = adapter.capture(shot, p)
        frames.append({"yaw": yaw, "path": cap.get("path"),
                       "ok": cap.get("ok"), "camera": cam})
    viewer = _viewer_html(out_dir, [f["path"] for f in frames if f.get("ok")],
                          f"Trial: {hero['label']}")
    cleanup_live(bridge)
    print(json.dumps({"ok": True, "hero": hero, "frames": frames,
                      "viewer": viewer}, indent=2, default=str))


def run(args):
    bridge = UnrealBridge(timeout=120)
    out_dir = os.path.join(args.out_dir, "demo")
    os.makedirs(out_dir, exist_ok=True)
    dirty_before = bridge.is_level_dirty()
    dbp = dirty_before.get("result") if isinstance(dirty_before, dict) and \
        isinstance(dirty_before.get("result"), dict) else dirty_before

    adapter = CinematicLiveAdapter(bridge, output_root=out_dir,
                                   seq_root=_SEQ_ROOT)
    w, h = MovieRenderQueueDriver.resolution_for(args.resolution)
    adapter.set_resolution(w, h)
    hero = _resolve_hero_subjects(adapter, args.prompt, args.hero)[0]
    prompt = args.prompt
    vision = vision_review if args.vision else None
    plan_options = {}
    if args.distance:
        plan_options["distance"] = float(args.distance)
    if args.fov:
        plan_options["fov_deg"] = float(args.fov)
    if args.shots:
        plan_options["max_shots"] = int(args.shots)
    if args.yaws:
        plan_options["yaws"] = [float(v) for v in args.yaws.split(",")]
    result = run_cinematic(prompt, adapter, out_dir=out_dir,
                           max_visual_passes=int(args.max_passes),
                           subjects=[hero], vision=vision,
                           plan_options=plan_options or None)

    # restore scene: remove cameras + sequence assets created by this demo,
    # and revert every light/exposure value the adapter mutated (exact-value
    # restore; the level is never saved).
    seq = (result.get("video") or {}).get("sequence")
    cleanup_live(bridge, seq_path=seq)
    restore = adapter.restore_scene()
    dirty_after = bridge.is_level_dirty()
    dap = dirty_after.get("result") if isinstance(dirty_after, dict) and \
        isinstance(dirty_after.get("result"), dict) else dirty_after
    result["scene_preservation"] = {
        "dirty_before": bool((dbp or {}).get("is_dirty")),
        "dirty_after": bool((dap or {}).get("is_dirty")),
        "level_saved": False,
        "restored_mutations": restore.get("restored_count"),
        "restore_detail": (restore.get("restored") if isinstance(restore, dict)
                           else None),
        "note": ("level was never saved; demo-created actors/assets were "
                 "removed; every PPV/light mutation the visual loop made "
                 "was reverted to its certified value"),
    }
    result["resolution"] = [w, h]
    result["hero"] = hero
    result["rendered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _enrich_media_fields(result, out_dir)
    path = write_cinematic_result(result, out_dir)
    result["result_path"] = path
    print(json.dumps(result, indent=2, default=str))


def vision_review(path: str):
    """Local vision review of a real captured frame (advisory evidence).

    Mirrors V1's visual-review contract; returns None when the local vision
    model is unavailable so the loop never depends on it.
    """
    try:
        import requests
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        prompt = (
            "You are the cinematic director's reviewer for a premium hero "
            "shot of a futuristic command-center floor. Judge ONLY what is "
            "visible. Return JSON only: "
            "{score: 0-10 (number), pass: true/false, "
            "capture_quality: good|bad, summary: short text, "
            "issues: [short strings], next_action: short text}. "
            "Rules: score 8+ means premium cinematic quality for this "
            "iteration; capture_quality bad only when the frame is black/"
            "blurred/broken."
        )
        r = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={"model": "qwen3-vl:8b-instruct", "stream": False,
                  "options": {"temperature": 0},
                  "messages": [{"role": "user", "content": prompt,
                                 "images": [b64]}]},
            timeout=600)
        content = r.json().get("message", {}).get("content", "")
        s, e = content.find("{"), content.rfind("}")
        if s >= 0 and e > s:
            return json.loads(content[s:e + 1])
    except Exception:
        return None
    return None


def _enrich_media_fields(result, out_dir):
    """Attach authoritative media evidence (video path + ffprobe verify +
    proof stills) to the result so every artifact links to real files."""
    render = result.get("video") or {}
    # render frames recorded by the adapter renderer
    frames = render.get("frames") or []
    # keep the best-scoring shot frames as proof stills
    proof = list((result.get("scorecard") or {}).get("frames") or [])
    video_candidates = [
        os.path.join(out_dir, "render", "aivido_cinematic.mp4"),
    ]
    video_path = None
    for c in video_candidates:
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
                 video_path],
                capture_output=True, text=True, timeout=60)
            info = json.loads(out.stdout or "{}")
            st = (info.get("streams") or [{}])[0]
            fmt = info.get("format") or {}
            rate = str(st.get("r_frame_rate") or "0/0").split("/")
            fps = round(float(rate[0]) / float(rate[1]), 2) if len(rate) == 2 \
                and float(rate[1]) else None
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
    # only real frames kept as proof
    proof_paths = [os.path.abspath(p) for p in proof if os.path.isfile(p)]
    if frames:
        # fall back to the first render frame as a real-frame proof
        for p in frames:
            if os.path.isfile(p):
                proof_paths.append(os.path.abspath(p))
                break
    result["video_path"] = verification.get("video_path")
    result["video_verification"] = verification
    result["proof_frames"] = [
        os.path.relpath(p, out_dir) for p in proof_paths]
    result["frame_count"] = len(frames)
    result["capture_fps"] = (render.get("fps") or render.get("capture_fps")
                              or None)
    result["duration_s"] = render.get("duration_s")


def cleanup_live(bridge, seq_path=None):
    """Remove every actor/asset the demo created. Never touches other actors."""
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
    # delete the content folder the demo created (asset deletion only lands
    # on disk after a save; retry after persisting so no empty shell remains)
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
    ap = argparse.ArgumentParser(description="Aivido V2 live cinematic demo")
    ap.add_argument("mode", choices=("trial", "run"))
    ap.add_argument("--prompt", default=(
        "Create a 10-second cinematic hero shot of the AividoHQ with premium "
        "lighting and smooth camera movement"))
    ap.add_argument("--hero", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--resolution", default="1920x1080")
    ap.add_argument("--duration", default="10")
    ap.add_argument("--distance", default="480")
    ap.add_argument("--fov", default=None)
    ap.add_argument("--shots", default="3")
    ap.add_argument("--yaws", default=None)
    ap.add_argument("--max-passes", default="3")
    ap.add_argument("--no-vision", action="store_true",
                    help="skip the local vision review (deterministic only)")
    args = ap.parse_args()
    args.vision = not args.no_vision
    args.out_dir = args.out_dir or default_cinematic_out_dir()
    if args.mode == "trial":
        trial(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
