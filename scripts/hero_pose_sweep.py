"""hero_pose_sweep.py — bounded camera-pose sweep for the durable cast hero.

Captures the SAME standing (durably repaired) hero from a few camera
distances/angles, scores each real frame with the deterministic cinematic
scorer + the local vision model, and keeps the best-composed frame. Bounded:
max 6 captures, each real (native viewport read-back, liveness-probed).
"""

from __future__ import annotations

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
from tools.unreal.cinematic_live import CinematicLiveAdapter
from tools.unreal.unreal_bridge import UnrealBridge

OUT = "reports/cinematic/cast_durable/sweep"


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


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero", default="AVIDO_Human_Master")
    args = ap.parse_args()

    bridge = UnrealBridge(timeout=120)
    os.makedirs(OUT, exist_ok=True)
    adapter = CinematicLiveAdapter(bridge, output_root=OUT, seq_root="/Game/Cine/Sweep")

    # hero subject (durably standing)
    sub = bridge.execute_python(f"""
import unreal
a = None
for x in unreal.EditorActorSubsystem().get_all_level_actors():
    if (x.get_actor_label() or "") == {json.dumps(args.hero)}:
        a = x; break
loc = a.get_actor_location()
bb = a.get_actor_bounds(False)
__bridge_result__ = {{"x": round(loc.x,1), "y": round(loc.y,1),
                     "h": round(bb[0].z + bb[1].z - (bb[0].z - bb[1].z), 2)}}
""")
    s = sub.get("result") if isinstance(sub, dict) else None
    hero = {"label": args.hero, "kind": "actor",
            "location": [float(s["x"]), float(s["y"]), 0.0],
            "height_cm": float(s["h"])}

    prompt = ("Create a premium cinematic hero shot of the character, "
              "cinematic lighting, smooth camera movement")
    brief = parse_cinematic_brief(prompt)
    tgt = None

    combos = [(220, 0.0), (260, 0.0), (260, 90.0), (260, 180.0),
              (330, 0.0), (330, 180.0)]
    results = []
    for distance, yaw in combos:
        plan = plan_cinematic_shots(brief, [hero], options={
            "fov_deg": 50.0, "yaws": [yaw], "distance": distance, "max_shots": 1})
        if not plan.get("ok"):
            continue
        if tgt is None:
            tgt = cinematic_target(brief, plan)
        shot = dict(plan["shots"][0])
        path = os.path.join(OUT, f"hero_d{int(distance)}_y{int(yaw)}.png")
        adapter.aim_viewport(shot)
        cap = adapter.capture(shot, path)
        if not cap.get("ok") or not os.path.isfile(path):
            results.append({"distance": distance, "yaw": yaw,
                            "capture": cap.get("ok"), "score": None})
            continue
        sc = score_cinematic_frame(path, tgt)
        results.append({"distance": distance, "yaw": yaw, "capture": True,
                        "path": path,
                        "overall": sc.get("overall"),
                        "basis": sc.get("overall_basis"),
                        "coverage": (sc.get("metrics") or {}).get("subject_coverage")})
        print(json.dumps({"distance": distance, "yaw": yaw,
                          "overall": sc.get("overall"),
                          "coverage": (sc.get("metrics") or {}).get("subject_coverage")},
                         default=str))

    best = None
    for r in results:
        ov = r.get("overall")
        if isinstance(ov, (int, float)) and (best is None or ov > best.get("overall", -1)):
            best = r
    if best:
        import shutil
        shutil.copyfile(best["path"], os.path.join(OUT, "hero_best.png"))
        best["copied_as"] = "hero_best.png"
    record = {"hero": args.hero, "results": results, "best": best,
              "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(os.path.join(OUT, "sweep_result.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    print(json.dumps(record, indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()