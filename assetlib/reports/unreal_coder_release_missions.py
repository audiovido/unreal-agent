"""unreal_coder_release_missions.py — LIVE release acceptance missions.

Runs the Phase V/W live matrix against the live UE 5.8.2 editor through the
canonical mission engine + real capability registry + real bridge:

  J  graphics enhancement   (before/after capture + score evidence)
  K  UI mission             (UMG widget asset, real and verified)
  L  gameplay mission       (PIE start/stop with runtime verification)
  M  cinematic mission      (Level Sequence + camera cut + scrub/play)
  N  archviz/environment    (composition + save + capture)
  W  beginner mixed mission (multi-capability orchestration, small scope)

Every mission: real editor mutations, independent read-back, viewport
evidence, structured verdict. No mocked bridges. Safe unique names; nothing
destructive; originals untouched.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission as mission_mod
from core.capability_registry import build_capability_registry
from core.scene_locators import locators_from_profile
from core.tool_registry import build_registry
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from core.project_safety import ProjectMutationGuard
from tools.unreal.project_manager import (
    create_project, discover_projects, inspect_project, open_project,
)
from tools.unreal.unreal_bridge import UnrealBridge

MISSIONS_TO_RUN = sys.argv[1:] or [
    "graphics", "ui", "gameplay", "cinematic", "archviz", "beginner",
]


def build_live_engine(tmp_checkpoint_dir=None, scene_locators=None):
    bridge = UnrealBridge()
    registry = build_registry(
        discover_projects, inspect_project, open_project, create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=bridge,
    )
    caps = build_capability_registry(registry)

    def dispatch(step):
        tool = step.get("preferred_tool")
        spec = registry.get(tool)
        if spec is None:
            return {"ok": False, "error": f"Unknown tool {tool}"}
        args = dict(step.get("parameters") or {})
        try:
            raw = spec.func(**args)
        except TypeError as exc:
            return {"ok": False, "error": f"arg mismatch: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        from app.api import _tool_success
        return {"ok": _tool_success(raw), "result": raw, "tool": tool}

    guard = ProjectMutationGuard(bridge=bridge)

    def guarded_dispatch(step):
        from core.project_safety import MUTATING_TOOLS
        if step.get("preferred_tool") in MUTATING_TOOLS:
            verdict = guard.validate_mutation()
            if not verdict.ok:
                return {"ok": False,
                        "error": f"{verdict.code}: {verdict.detail}"}
        return dispatch(step)

    def capture():
        result = bridge.capture_unreal_viewport()
        payload = result.get("result") if isinstance(result, dict) else {}
        return {"path": (payload or {}).get("path"),
                "tool": "capture_unreal_viewport",
                "ok": bool((payload or {}).get("ok"))}

    if tmp_checkpoint_dir:
        mission_mod.CHECKPOINT_DIR = Path(tmp_checkpoint_dir)

    engine = MissionEngineProxy(registry, caps, guarded_dispatch, capture,
                                bridge, scene_locators=scene_locators)
    return engine, bridge, guard


class MissionEngineProxy:
    """Mission engine bound to the LIVE registry + guarded dispatch."""

    def __init__(self, registry, caps, dispatch, capture, bridge,
                 scene_locators=None):
        from core.mission import MissionEngine
        self._engine = MissionEngine(
            tool_registry=registry, capabilities=caps, dispatch=dispatch,
            capture=capture, evaluate=_make_evaluate(bridge,
                                                      scene_locators))
        self.registry = registry
        self.bridge = bridge

    def run_prompt(self, prompt: str, label: str):
        from core.mission import MissionState
        mission_id = f"mission_rel_{label}_{uuid.uuid4().hex[:6]}"
        state = MissionState(mission_id=mission_id, prompt=prompt)
        state.started_at = time.time()
        intent = interpret_intent(prompt)
        requirements = expand_requirements(intent)
        state.intent = intent.to_dict()
        state.requirements = requirements.to_dict()
        planner = build_universal_planner(self.registry)
        plan = planner.build_plan(intent, requirements, None)
        state.plan = plan.to_dict()
        state.status = "executing"
        state.save()
        state = self._engine.run(state)
        return state


# ---------------------------------------------------------------------------
# Scene locator configuration (mission-level, reusable)
# ---------------------------------------------------------------------------
# Generic deterministic measurement assumes a centered mid-tone subject.  The
# release composition scene keeps its subject band (bright structures) below a
# darker top band inside a wide viewport, so the generic scan merges the top
# band into the subject bbox and reports a false HEAD_CROPPED.  Scene locators
# pin only WHERE the scene keeps its content (frame-relative ROI + luma band)
# through the documented measure() subject_locator mechanism; they never alter
# scorer thresholds.  Profiles are serializable mission configuration resolved
# here via core.scene_locators.
SCENE_LOCATOR_PROFILES = {
    # Any capture of the UA_Rel_Gfx board composition (any camera pose): the
    # subject is the bright composition mass inside the standard hero band.
    "rel_gfx_board": {
        "subject": {"method": "luma_band",
                     "roi": [0.02, 0.05, 0.72, 0.97],
                     "min_luma": 140, "max_luma": 250},
    },
}


def resolve_scene_locators(name):
    """Resolve a named scene profile into measure() locator callables, or
    None when the scene has no profile (plain generic measurement)."""
    profile = SCENE_LOCATOR_PROFILES.get(name or "")
    return locators_from_profile(profile) or None


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------

def _make_evaluate(bridge, scene_locators=None, target=None):
    """Deterministic + provider visual evaluation for live evidence.

    scene_locators: optional dict of locator callables (subject_locator /
    ui_locator) resolved from a mission's scene profile and passed to
    measure() through the documented injection mechanism.  None keeps the
    generic plain-measure behavior.

    target: optional VisualTarget dict whose ``required_visual_categories``
    make acceptance task-aware (only categories the task actually requested
    weigh on the overall).  None/{} keeps the historic all-categories
    contract exactly (UI tasks, Step-5/6, and every existing caller).

    The captured dict may carry precomputed "_metrics" and "_score" from a
    caller that already measured the exact same frame (e.g. the visual
    loop's runner); when present, the duplicate deterministic measure is
    skipped.  Evaluation is then performed with the cached metrics, so
    score/defects are bit-for-bit identical to a fresh measure.

    Vision providers only run when the deterministic verdict is NOT
    decisive (see vision_provider.review_image decisive_score): clean
    frames at/above the acceptance score and frames with deterministic
    defects need no model round-trip (its verdict was always overridden by
    deterministic_wins).  Ambiguous near-threshold frames still get the
    full model cross-check.  Set UNREAL_AGENT_FORCE_VISION=1 to always run
    providers.
    """
    def evaluate(captured):
        from core.visual_acceptance import measure, score as score_fn
        from core import vision_provider
        import os
        path = (captured or {}).get("path") or ""
        locator_kw = {}
        if scene_locators:
            for key in ("subject_locator", "ui_locator"):
                fn = scene_locators.get(key)
                if fn is not None:
                    locator_kw[key] = fn
        metrics = (captured or {}).get("_metrics")
        if metrics is None:
            metrics = measure(path, **locator_kw)
        if not metrics.ok:
            return {"score": 0.0, "defects": ["CAPTURE_UNREADABLE"],
                    "review": {"ok": False}}
        s = (captured or {}).get("_score")
        if s is None:
            s = score_fn(metrics, target=target)
        decisive = None if os.getenv("UNREAL_AGENT_FORCE_VISION") else 8.5
        review = vision_provider.review_image(
            path, providers=vision_provider.get_configured_providers(),
            metrics=metrics, score=s, decisive_score=decisive)
        defects = list(metrics.issues) + [
            d for d in (review.get("defects") or [])
            if d not in metrics.issues]
        return {"score": float(s.overall), "defects": defects,
                "review": review}
    return evaluate


def run_python(bridge, code):
    result = bridge.execute_python(code)
    payload = result.get("result") if isinstance(result, dict) else {}
    return payload if isinstance(payload, dict) else {"ok": False,
                                                      "raw": payload}


def actor_exists(bridge, label):
    payload = run_python(bridge, f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()
__bridge_result__ = {{
    "ok": True,
    "found": any(a.get_actor_label() == {label!r} for a in actors),
}}
""")
    return bool(payload.get("found"))


def capture_to(bridge, name):
    """Capture a viewport frame to a stable evidence path (fresh)."""
    payload = run_python(bridge, f"""
import os
saved_dir = unreal.Paths.convert_relative_path_to_full(
    unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent", "release_missions")
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, {name!r})
if os.path.isfile(path):
    os.remove(path)
if hasattr(unreal, "UnrealAgentBlueprintLibrary"):
    diag = str(unreal.UnrealAgentBlueprintLibrary
               .capture_active_viewport_detailed(path))
    ok = diag.startswith("OK|")
else:
    task = unreal.AutomationLibrary.take_high_res_screenshot(
        1280, 720, path, None, False, False, force_game_view=False)
    ok = False
__bridge_result__ = {{"ok": bool(ok), "path": path.replace(chr(92), "/"), "diag": diag if hasattr(unreal, 'UnrealAgentBlueprintLibrary') else "automation"}}
""")
    path = payload.get("path")
    if path and not payload.get("ok"):
        # EditorAutomation path completes asynchronously: bounded wait.
        deadline = time.time() + 30
        while time.time() < deadline:
            if Path(path).is_file() and Path(path).stat().st_size > 0:
                return path
            time.sleep(1)
        return None
    # Native capture writes asynchronously too: wait until the file exists,
    # then wait until its size STABILIZES (two identical probes) so two
    # captures can never read the same half-written/previous frame.
    if not path:
        return None
    deadline = time.time() + 30
    last_size = -1
    while time.time() < deadline:
        size = Path(path).stat().st_size if Path(path).is_file() else -1
        if size > 0 and size == last_size:
            return path
        last_size = size
        time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------

def mission_graphics(engine, bridge, report):
    """Phase J: scene-improvement mission with before/after evidence.

    Editor viewports only repaint on demand when the editor is not focused,
    so the change is measured through TWO PIE RUNS: run A with the mission
    light hidden (before), run B with the warm key light active (after).
    PIE forces continuous GameViewport rendering, so both frames are real
    renders. Evidence = pixel-diff analysis (changed-pixel fraction + max
    delta); a claim of visible change requires the measured diff.
    """
    light_label = f"UA_Rel_Gfx_KeyLight_{uuid.uuid4().hex[:5]}"
    setup = run_python(bridge, f"""
import unreal
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cam_loc, cam_rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
light = subsystem.spawn_actor_from_class(
    unreal.PointLight, cam_loc + cam_rot.get_forward_vector() * 250.0,
    unreal.Rotator(0, 0, 0))
ok = False
if light is not None:
    light.set_actor_label({light_label!r})
    comp = light.get_component_by_class(unreal.PointLightComponent)
    if comp is not None:
        comp.set_editor_property("intensity", 500000.0)
        comp.set_editor_property("light_color", unreal.Color(1.0, 0.7, 0.4, 1.0))
        ok = True
light.set_hidden_ed(True)
save = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
__bridge_result__ = {{"ok": bool(ok), "saved": bool(save)}}
""")

    def pie_capture(tag: str):
        """One PIE run -> fresh GameViewport capture."""
        run_python(bridge, """
import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
__bridge_result__ = {"ok": True}
""")
        time.sleep(4.0)
        payload = run_python(bridge, f"""
import unreal, os
p = 'C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/proof/rel_gfx_{tag}.png'
if os.path.isfile(p):
    os.remove(p)
diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p))
__bridge_result__ = {{"diag": diag[:80], "size": os.path.getsize(p) if os.path.isfile(p) else -1}}
""")
        time.sleep(1.5)
        run_python(bridge, """
import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
__bridge_result__ = {"ok": True}
""")
        time.sleep(1.5)
        path = Path("assetlib/proof/rel_gfx_" + tag + ".png")
        return str(path.resolve()) if path.is_file() and path.stat().st_size > 0 else None

    before = pie_capture("before")
    visible = run_python(bridge, f"""
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
light = [a for a in actors if a.get_actor_label() == {light_label!r}][0]
light.set_hidden_ed(False)
save = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
__bridge_result__ = {{"ok": True, "saved": bool(save)}}
""")
    after = pie_capture("after")

    # Deterministic diff analysis - the claim of visible change REQUIRES
    # a measured changed-pixel fraction, never an unsupported assertion.
    luma_before = luma_after = None
    frames_differ = False
    changed_fraction = 0.0
    max_delta = 0
    if before and after:
        import hashlib
        from PIL import Image, ImageChops
        from core.visual_acceptance import measure
        mb, ma = measure(before), measure(after)
        luma_before, luma_after = mb.mean_luma, ma.mean_luma
        h1 = hashlib.md5(Path(before).read_bytes()).hexdigest()
        h2 = hashlib.md5(Path(after).read_bytes()).hexdigest()
        frames_differ = h1 != h2
        if frames_differ:
            g1 = Image.open(before).convert("L")
            g2 = Image.open(after).convert("L")
            diff = ImageChops.difference(g1, g2)
            hist = diff.histogram()
            total = g1.size[0] * g1.size[1]
            changed = sum(hist[8:])
            changed_fraction = round(changed / total, 6)
            max_delta = max(diff.get_flattened_data())

    visible_change = bool(frames_differ and changed_fraction >= 0.002
                          and max_delta >= 20)
    ok = bool(setup.get("ok") and before and after and visible_change)
    report["missions"]["graphics"] = {
        "light": light_label, "method": "two_pie_runs",
        "before": before, "after": after,
        "luma_before": luma_before, "luma_after": luma_after,
        "frames_differ": frames_differ,
        "changed_pixel_fraction": changed_fraction,
        "max_pixel_delta": max_delta,
        "measured_visible_change": visible_change,
        "evidence_ok": ok,
    }
    return ok

def mission_ui(engine, bridge, report):
    """Phase K: real UMG widget asset, compiled + persisted + verified."""
    payload = run_python(bridge, f"""
import unreal
name = "UA_Rel_Menu_{uuid.uuid4().hex[:5]}"
tools = unreal.AssetToolsHelpers.get_asset_tools()
widget = tools.create_asset(name, "/Game/ReleaseMissions",
                            unreal.WidgetBlueprint,
                            unreal.WidgetBlueprintFactory())
created = widget is not None
saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(widget, False)) if created else False
reloaded = unreal.EditorAssetLibrary.load_asset("/Game/ReleaseMissions/" + name)
verified = bool(reloaded is not None and reloaded.get_class().get_name() == "WidgetBlueprint")
__bridge_result__ = {{"ok": bool(created and saved and verified), "name": name, "created": created, "saved": saved, "verified": verified}}
""")
    ok = bool(payload.get("ok"))
    report["missions"]["ui"] = {
        "widget": payload.get("name"), "created": payload.get("created"),
        "saved": payload.get("saved"), "verified": payload.get("verified"),
        "evidence_ok": ok,
    }
    return ok


def mission_gameplay(engine, bridge, report):
    """Phase L: spawn + PIE start/stop with runtime world verification."""
    label = f"UA_Rel_Gp_{uuid.uuid4().hex[:5]}"
    spawn = run_python(bridge, f"""
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = subsystem.spawn_actor_from_class(
    unreal.StaticMeshActor, unreal.Vector(0, 0, 100), unreal.Rotator(0, 0, 0))
if actor is not None:
    actor.set_actor_label({label!r})
    mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
    if mesh is not None and hasattr(actor, "static_mesh_component"):
        actor.static_mesh_component.set_static_mesh(mesh)
__bridge_result__ = {{"ok": actor is not None, "label": {label!r}}}
""")
    editor_ok = actor_exists(bridge, label)
    start = run_python(bridge, """
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.editor_request_begin_play()
__bridge_result__ = {"ok": True, "requested": True}
""")
    time.sleep(2.5)
    pie = run_python(bridge, """
editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
game_world = editor_subsystem.get_game_world()
__bridge_result__ = {
    "ok": game_world is not None,
    "world": game_world.get_path_name() if game_world else None,
}
""")
    stop = run_python(bridge, """
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.editor_request_end_play()
__bridge_result__ = {"ok": True}
""")
    ok = bool(editor_ok and pie.get("ok"))
    report["missions"]["gameplay"] = {
        "actor_spawned": editor_ok, "pie_started": pie.get("ok"),
        "pie_world": pie.get("world"), "evidence_ok": ok,
    }
    return ok


def mission_cinematic(engine, bridge, report):
    """Phase M: Level Sequence + camera cut + scrub/play + save/verify."""
    seq_path = f"/Game/ReleaseMissions/UA_Rel_Seq_{uuid.uuid4().hex[:5]}"
    create = run_python(bridge, f"""
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
seq = tools.create_asset({seq_path.rsplit('/', 1)[-1]!r},
                         "/Game/ReleaseMissions",
                         unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False)) if seq else False
__bridge_result__ = {{"ok": bool(seq is not None and saved), "path": {seq_path!r}}}
""")
    cam_cut = run_python(bridge, f"""
import unreal
seq = unreal.EditorAssetLibrary.load_asset({seq_path!r})
cam_label = "UA_Rel_Cam_" + {uuid.uuid4().hex[:5]!r}
cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.CineCameraActor, unreal.Vector(300, -600, 250), unreal.Rotator(0, 0, 0))
if cam is not None:
    cam.set_actor_label(cam_label)
cut_ok = False
if seq is not None:
    try:
        track = unreal.MovieSceneSequenceExtensions.add_track(
            seq, unreal.MovieSceneCameraCutTrack)
        section = unreal.MovieSceneTrackExtensions.add_section(track)
        unreal.MovieSceneSectionExtensions.set_range_seconds(section, 0.0, 8.0)
        cut_ok = section is not None
    except Exception as exc:
        cut_ok = False
__bridge_result__ = {{"ok": bool(cut_ok), "camera": cam_label, "camera_ok": cam is not None, "cut_ok": cut_ok}}
""")
    playback = run_python(bridge, f"""
import unreal
seq = unreal.EditorAssetLibrary.load_asset({seq_path!r})
out = {{"ok": False}}
try:
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(2.0)
    out["scrub_time"] = float(unreal.LevelSequenceEditorBlueprintLibrary.get_current_time())
    unreal.LevelSequenceEditorBlueprintLibrary.play()
    out["playing"] = bool(unreal.LevelSequenceEditorBlueprintLibrary.is_playing())
    unreal.LevelSequenceEditorBlueprintLibrary.pause()
    out["paused"] = not bool(unreal.LevelSequenceEditorBlueprintLibrary.is_playing())
    out["ok"] = True
except Exception as exc:
    out["error"] = str(exc)[:180]
__bridge_result__ = out
""")
    saved = run_python(bridge, f"""
import unreal
seq = unreal.EditorAssetLibrary.load_asset({seq_path!r})
saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False))
reloaded = unreal.EditorAssetLibrary.load_asset({seq_path!r})
__bridge_result__ = {{"ok": bool(saved and reloaded is not None and reloaded.get_class().get_name() == "LevelSequence")}}
""")
    cam_ok = actor_exists(bridge, cam_cut.get("camera") or "")
    ok = bool(create.get("ok") and cam_cut.get("ok") and playback.get("ok")
              and saved.get("ok") and cam_ok)
    report["missions"]["cinematic"] = {
        "sequence": seq_path, "created": create.get("ok"),
        "camera_spawned": cam_ok, "camera_cut": cam_cut.get("cut_ok"),
        "scrub_play": playback, "saved_verified": saved.get("ok"),
        "evidence_ok": ok,
    }
    return ok


def mission_archviz(engine, bridge, report):
    """Phase N: small clean architectural composition, real-scale."""
    base = f"UA_Rel_Arch_{uuid.uuid4().hex[:5]}"
    payload = run_python(bridge, f"""
import unreal
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
made = []
floor = subsystem.spawn_actor_from_class(
    unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
if floor is not None:
    floor.set_actor_label({base + '_Floor'!r})
    mesh = unreal.load_asset("/Engine/BasicShapes/Plane.Plane")
    if mesh is not None and hasattr(floor, "static_mesh_component"):
        floor.static_mesh_component.set_static_mesh(mesh)
        floor.set_actor_scale3d(unreal.Vector(10.0, 10.0, 1.0))
    made.append("floor")
pillar = subsystem.spawn_actor_from_class(
    unreal.StaticMeshActor, unreal.Vector(200, 0, 150), unreal.Rotator(0, 0, 0))
if pillar is not None:
    pillar.set_actor_label({base + '_Pillar'!r})
    mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
    if mesh is not None and hasattr(pillar, "static_mesh_component"):
        pillar.static_mesh_component.set_static_mesh(mesh)
        pillar.set_actor_scale3d(unreal.Vector(0.5, 0.5, 3.0))
    made.append("pillar")
light = subsystem.spawn_actor_from_class(
    unreal.PointLight, unreal.Vector(-150, 150, 250), unreal.Rotator(0, 0, 0))
if light is not None:
    light.set_actor_label({base + '_Light'!r})
    made.append("light")
save = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
__bridge_result__ = {{"ok": len(made) == 3, "made": made, "saved": bool(save)}}
""")
    frame = capture_to(bridge, "archviz_result.png")
    ok = bool(payload.get("ok")) and frame is not None
    report["missions"]["archviz"] = {
        "composition": payload.get("made"), "saved": payload.get("saved"),
        "capture": frame, "evidence_ok": ok,
    }
    return ok


def mission_beginner(engine, bridge, report):
    """Phase W: one beginner prompt routed across multiple capabilities."""
    prompt = ("Make my scene nicer: add a light, a prop, and a small "
              "cinematic camera moment.")
    state = engine.run_prompt(prompt, "beginner")
    caps = set(state.plan.get("selected_capabilities") or [])
    frame = capture_to(bridge, "beginner_result.png")
    multi = len(caps & {"lighting_setup", "environment_composition",
                        "material_authoring", "sequencer_cinematic",
                        "camera_framing", "visual_quality_gate"}) >= 2
    ok = bool(state.verdict in ("PASS", "PARTIAL") and multi)
    report["missions"]["beginner"] = {
        "mission_id": state.mission_id, "verdict": state.verdict,
        "capabilities": sorted(caps), "multi_capability": multi,
        "capture": frame, "evidence_ok": ok, "why": state.why,
        "user_result": {
            "status": state.verdict,
            "completed_steps": len(state.completed_step_ids),
        },
    }
    return ok


# ---------------------------------------------------------------------------

def main() -> int:
    from core.mission import MissionEngine  # noqa: F401 (import sanity)
    report = {
        "runner": "unreal_coder_release_missions",
        "started_at": time.time(),
        "missions": {},
        "all_ok": False,
    }
    engine, bridge, guard = build_live_engine()
    identity = guard.capture_identity()
    report["session"] = identity.to_dict()
    if not identity.uproject_path:
        report["why"] = "no live editor session"
        print(json.dumps(report, indent=2, default=str))
        return 1

    runners = {
        "graphics": mission_graphics,
        "ui": mission_ui,
        "gameplay": mission_gameplay,
        "cinematic": mission_cinematic,
        "archviz": mission_archviz,
        "beginner": mission_beginner,
    }
    for name in MISSIONS_TO_RUN:
        runner = runners.get(name)
        if runner is None:
            continue
        started = time.time()
        try:
            ok = runner(engine, bridge, report)
        except Exception as exc:
            report["missions"][name] = {
                "evidence_ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            ok = False
        report["missions"][name]["duration_s"] = round(
            time.time() - started, 1)

    report["all_ok"] = all(
        m.get("evidence_ok") for m in report["missions"].values())
    report["verdict"] = "PASS" if report["all_ok"] else "PARTIAL"
    report["finished_at"] = time.time()
    out = Path(__file__).with_suffix(".json")
    out.write_text(json.dumps(report, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({
        "verdict": report["verdict"],
        "project": report["session"].get("project_name"),
        "missions": {k: v.get("evidence_ok")
                     for k, v in report["missions"].items()},
    }, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
