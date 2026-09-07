"""Independent re-certification probe for aivido/polish-90.

Runs every required Phase-0 check against the LIVE Unreal editor bridge:
  - project identity / engine / map
  - full editor-world census (characters, props, screens, UI text, lights,
    materials, broken roots)
  - idle-driver live motion test inside PIE (real transform deltas, bounded
    amplitudes, duplicate-start guard, exact restore, callback teardown)
  - map save + reopen + post-reopen census
Writes a single JSON blob to stdout; exit code 0 iff every gate passed.

Usage:
  <venv-python> scripts/recert/polish90_recert_probe.py [--out PATH] [--skip-pie]
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
if w is not None:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    res["total_actors"] = len(actors)
    chars, props, screens, texts, lights, bad_mesh, broken_root = [], [], [], [], [], [], []
    for a in actors:
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        cls = a.get_class().get_name()
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
                          "loc": [round(loc.x,1), round(loc.y,1), round(loc.z,1)]})
        if label.startswith("W3I_"):
            props.append(label)
        low = label.lower()
        if "screen" in low or "vd_" in low or "grade" in low or "hub" in low or "console" in low:
            screens.append(label)
        if cls == "TextRenderActor":
            texts.append(label)
        if cls in ("PointLight", "SpotLight", "DirectionalLight", "SkyLight", "RectLight"):
            comp = a.get_editor_property("root_component") if hasattr(a, "get_editor_property") else None
            if comp is None:
                try:
                    comp = a.root_component
                except Exception:
                    comp = None
            mob = str(comp.get_editor_property("mobility")) if comp else "none"
            lights.append({"label": label, "class": cls, "mobility": mob})
        if cls == "StaticMeshActor":
            comp = a.static_mesh_component if hasattr(a, "static_mesh_component") else None
            if comp is None or comp.get_editor_property("static_mesh") is None:
                bad_mesh.append(label)
            else:
                n = comp.get_num_materials()
                for i in range(min(n, 3)):
                    if comp.get_material(i) is None:
                        bad_mesh.append(label + "#slot%d" % i)
                        break
        if a.get_class().get_name() not in ("LevelScriptActor", "WorldSettings"):
            root = None
            try:
                root = a.get_root_component()
            except Exception:
                try:
                    root = a.root_component
                except Exception:
                    root = None
            if root is None:
                broken_root.append(label)
    res["characters"] = chars
    res["prop_count"] = len(props)
    res["props"] = props
    res["screens"] = screens
    res["text_renders"] = texts
    res["lights"] = lights
    res["light_total"] = len(lights)
    res["light_movable"] = sum(1 for l in lights if l["mobility"].endswith("Movable"))
    res["light_stationary"] = sum(1 for l in lights if l["mobility"].endswith("Stationary"))
    res["light_static"] = sum(1 for l in lights if l["mobility"].endswith("Static"))
    res["bad_mesh_actors"] = bad_mesh
    res["broken_root_actors"] = broken_root
    res["ok"] = True
else:
    res["ok"] = False
    res["error"] = "no editor world"
__bridge_result__ = res
"""


def census() -> dict:
    return py(CENSUS_CODE)


# ------------------------------------------------------- idle motion (PIE)
PIE_PRE_CODE = r"""
import unreal, json
ed = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
w = ed.get_game_world()
res = {"pie": w is not None}
if w is not None:
    chars = {}
    for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor):
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        if label.startswith("AVIDO_Human") or label.startswith("AVIDO_Agent"):
            l = a.get_actor_location(); r = a.get_actor_rotation()
            chars[label] = {"loc": [round(l.x,4), round(l.y,4), round(l.z,4)],
                            "yaw": round(r.yaw,4)}
    res["chars"] = chars
__bridge_result__ = res
"""


def pie_chars() -> dict:
    return py(PIE_PRE_CODE)


IDLE_CODE = r"""
import json
try:
    import aivido_idle_driver as drv
except ImportError:
    __bridge_result__ = {"ok": False, "error": "aivido_idle_driver not importable"}
else:
    import json as _json
    action = ACTION
    if action == "start":
        r1 = drv.start_idle_driver()
        r2 = drv.start_idle_driver()   # duplicate-start guard probe
        r1.pop("handle", None)
        r2.pop("handle", None)
        r1["second_start"] = r2
        r1["second_start_already_flag"] = r2.get("already", False)
        __bridge_result__ = r1
    elif action == "stop":
        __bridge_result__ = drv.stop_idle_driver()
    elif action == "stats":
        __bridge_result__ = drv.idle_stats()
""".replace("ACTION", "%s")


def idle(action: str) -> dict:
    return py(IDLE_CODE % repr(action))


def transform_delta(a: dict, b: dict) -> dict:
    out = {}
    for label, pre in a.items():
        post = b.get(label)
        if not post:
            out[label] = None
            continue
        dx = post["loc"][0] - pre["loc"][0]
        dy = post["loc"][1] - pre["loc"][1]
        dz = post["loc"][2] - pre["loc"][2]
        out[label] = {
            "dx": round(dx, 3), "dy": round(dy, 3), "dz": round(dz, 3),
            "planar": round((dx * dx + dy * dy) ** 0.5, 3),
            "yaw_d": round(post["yaw"] - pre["yaw"], 3),
        }
    return out


def main() -> int:
    report: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
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

    # 2. census -----------------------------------------------------------
    c1 = census()
    report["census_initial"] = c1
    chars = {c["label"] for c in (c1.get("characters") or [])}
    gates["map_loaded"] = bool(c1.get("ok") and str(c1.get("world", "")).endswith("AividoHQ'") or "AividoHQ" in str(c1.get("world", "")))
    gates["characters_8of8"] = len(chars) == 8 and all(
        any(e.lower() in lbl.lower() for lbl in chars) for e in EXPECTED_CHARS)
    gates["props_present"] = c1.get("prop_count", 0) >= 23
    gates["screens_present"] = len(c1.get("screens") or []) >= 8
    gates["ui_text_present"] = len(c1.get("text_renders") or []) >= 3
    gates["lights_all_movable"] = (c1.get("light_total", 0) >= 41
                                   and c1.get("light_stationary", 0) == 0
                                   and c1.get("light_static", 0) == 0)
    gates["no_broken_roots"] = len(c1.get("broken_root_actors") or []) == 0
    gates["no_missing_materials"] = len(c1.get("bad_mesh_actors") or []) == 0

    # 3. idle driver live motion test --------------------------------------
    if "--skip-pie" in sys.argv:
        gates["idle_motion"] = None
    else:
        st = BR.get_pie_status()
        if (st.get("result") or {}).get("is_playing"):
            BR.stop_pie(); time.sleep(6)
        BR.start_pie()
        time.sleep(14)
        pre = pie_chars()
        if not pre.get("pie"):
            # one bounded retry: PIE begin-play is asynchronous in UE 5.8
            BR.start_pie(); time.sleep(12)
            pre = pie_chars()
        report["pie_pre"] = {"pie": pre.get("pie"), "n": len(pre.get("chars") or {}),
                             "err": pre.get("error")}
        r = idle("start")
        report["idle_start"] = r
        time.sleep(4.5)
        mid = pie_chars()
        time.sleep(4.5)
        post = pie_chars()
        deltas_mid = transform_delta(pre.get("chars") or {}, mid.get("chars") or {})
        deltas_post = transform_delta(pre.get("chars") or {}, post.get("chars") or {})
        stats_running = idle("stats")
        stop = idle("stop")
        time.sleep(0.6)
        after = pie_chars()
        restore_delta = transform_delta(pre.get("chars") or {}, after.get("chars") or {})
        stats_after = idle("stats")
        report["idle_deltas_mid"] = deltas_mid
        report["idle_deltas_post"] = deltas_post
        report["idle_stats_running"] = stats_running
        report["idle_stop"] = stop
        report["idle_restore_delta"] = restore_delta
        report["idle_stats_after"] = stats_after

        moved = [l for l, d in deltas_post.items() if d and (d["planar"] > 0.05 or abs(d["dz"]) > 0.05)]
        bounded = all(
            d and d["planar"] <= 3.0 and abs(d["dz"]) <= 6.0
            for d in deltas_post.values() if d)
        max_restore = max(
            [max(abs(d["dx"]), abs(d["dy"]), abs(d["dz"]), abs(d["yaw_d"]))
             for d in restore_delta.values() if d] or [0.0])
        gates["idle_motion"] = bool(
            r.get("ok") and len(moved) == 8 and bounded and stats_running.get("calls", 0) > 0)
        gates["idle_duplicate_guard"] = bool(r.get("second_start_already_flag"))
        gates["idle_exact_restore"] = bool(stop.get("restored") == 8 and max_restore <= 0.05)
        gates["idle_callback_stopped"] = bool(
            not stats_after.get("running") and stats_after.get("chars", 1) == 0)
        BR.stop_pie(); time.sleep(6)

    # 4. save + reopen ------------------------------------------------------
    save = BR.save_level("/Game/Maps/AividoHQ")
    sres = save.get("result") if isinstance(save.get("result"), dict) else {}
    report["save"] = {k: sres.get(k) for k in ("ok", "saved_map", "dirty_after", "package_exists", "verified")}
    reopen = BR.open_map("/Game/Maps/AividoHQ")
    rres = reopen.get("result") if isinstance(reopen.get("result"), dict) else {}
    report["reopen"] = {k: rres.get(k) for k in ("ok", "loaded", "world_path", "identity_ok")}
    c2 = census()
    report["census_after_reopen"] = c2
    gates["save_reopen"] = bool(sres.get("ok") and rres.get("ok") and c2.get("ok"))
    if c2.get("ok"):
        gates["post_reopen_actors"] = bool(
            len(c2.get("characters") or []) == 8
            and c2.get("prop_count", 0) >= 23
            and c2.get("light_stationary", 0) == 0
            and len(c2.get("text_renders") or []) >= 3)
    else:
        gates["post_reopen_actors"] = False

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
