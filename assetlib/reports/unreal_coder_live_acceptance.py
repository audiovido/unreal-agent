"""Live acceptance: canonical Unreal Coder API against live UE 5.8.2.

Runs ONE real mission through the composition root (mission engine ->
capability-selected plan -> live bridge dispatch -> technical gate), then
verifies resulting editor state by read-back and records evidence.

Safety: spawns a uniquely-named PointLight + StaticMeshActor in the open
project's map, saves, captures viewport evidence. Nothing destructive.
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
from core.mission import mission_response
from tools.unreal.unreal_bridge import UnrealBridge


def main() -> int:
    report = {
        "runner": "unreal_coder_live_acceptance",
        "started_at": time.time(),
        "engine_version": None,
        "project": None,
        "mission_id": None,
        "request": None,
        "plan_summary": None,
        "dispatched_tools": [],
        "live_verifications": [],
        "evidence": [],
        "verdict": None,
        "why": None,
    }

    bridge = UnrealBridge()

    # 1) Live editor identity BEFORE any mutation.
    identity = bridge.get_identity()
    if not identity.get("ok"):
        report["verdict"] = "FAIL"
        report["why"] = f"bridge identity failed: {identity}"
        print(json.dumps(report, indent=2))
        return 1
    report["engine_version"] = identity.get("engine")
    report["project"] = identity.get("project_name")
    report["live_verifications"].append({
        "check": "editor_identity",
        "ok": True,
        "engine": identity.get("engine"),
        "project": identity.get("project_name"),
        "world": identity.get("world"),
    })

    mission_id = f"mission_live_{uuid.uuid4().hex[:8]}"
    prompt = ("Add a warm accent light and a small marker prop to the "
              "current scene, then capture proof of the result.")
    report["request"] = prompt

    # 2) Mission engine on the REAL capability registry; dispatch wired to
    #    the LIVE bridge for concrete tools (spawn/save/capture).
    from core.capability_registry import build_capability_registry
    from core.tool_registry import build_registry
    from tools.unreal.project_manager import (
        create_project, discover_projects, inspect_project, open_project,
    )

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
        # Mirror the api executor's nested-envelope success semantics
        # (bridge tools report ok in the inner payload).
        from app.api import _tool_success
        return {"ok": _tool_success(raw), "result": raw, "tool": tool}

    def capture():
        result = bridge.capture_unreal_viewport()
        payload = result.get("result") if isinstance(result, dict) else {}
        return {"path": (payload or {}).get("path"), "tool":
                "capture_unreal_viewport", "ok": bool((payload or {}).get("ok"))}

    def evaluate(captured):
        # Deterministic evidence check: capture verified by the native
        # diagnostic (source=GameViewport / OK| header) upstream in the
        # bridge; acceptance requires the file path to exist.
        path = (captured or {}).get("path")
        ok = bool(path) and Path(path).exists()
        return {"score": 7.6 if ok else 0.0,
                "defects": [] if ok else ["CAPTURE_FAILED"]}

    from core.mission import MissionEngine, MissionState
    mission_mod.CHECKPOINT_DIR = (
        ROOT / "memory" / "checkpoints" / "unreal_coder")
    engine = MissionEngine(
        tool_registry=registry, capabilities=caps, dispatch=dispatch,
        capture=capture, evaluate=evaluate,
    )

    light_label = f"UA_UC_Live_{uuid.uuid4().hex[:6]}"
    prop_label = f"UA_UC_Prop_{uuid.uuid4().hex[:6]}"
    state = engine.start_mission(prompt, mission_id=mission_id)
    engine.interpret(state)
    engine.plan(state)
    # Inject concrete live labels for verification (deterministic naming).
    for step in state.plan.get("steps", []):
        params = step.get("parameters") or {}
        if params.get("class_name") == "PointLight" and not params.get(
                "actor_name", "").startswith("UA_UC_"):
            params["actor_name"] = light_label
        elif params.get("class_name") == "StaticMeshActor" and not params.get(
                "actor_name", "").startswith("UA_UC_"):
            params["actor_name"] = prop_label
    report["mission_id"] = mission_id
    report["plan_summary"] = {
        "selected_capabilities": state.plan.get("selected_capabilities"),
        "visual_gate": state.plan.get("visual_gate"),
        "steps": [
            {"step_id": s.get("step_id"), "tool": s.get("preferred_tool"),
             "phase": s.get("phase")}
            for s in state.plan.get("steps", [])
        ],
    }

    state = engine.run(state)
    report["dispatched_tools"] = [
        {"tool": s.get("preferred_tool"), "step": s.get("step_id")}
        for s in state.plan.get("steps", [])
    ]
    report["evidence"].extend(state.evidence)

    # 3) Independent live read-back: the actors MUST exist in the editor.
    def actor_exists(name: str) -> bool:
        code = f"""
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
__bridge_result__ = {{
    "ok": True,
    "found": any(a.get_actor_label() == {name!r} for a in actors),
}}
"""
        result = bridge.execute_python(code)
        payload = result.get("result") if isinstance(result, dict) else {}
        return bool(payload.get("found"))

    read_back = {}
    for label in (light_label, prop_label):
        found = actor_exists(label)
        read_back[label] = found
        report["live_verifications"].append({
            "check": f"actor_exists:{label}", "ok": found})
    report["live_verifications"].append({
        "check": "evidence_capture_path_exists",
        "ok": all(e.get("path") and Path(e["path"]).exists()
                  for e in state.evidence) if state.evidence else False,
        "paths": [e.get("path") for e in state.evidence],
    })

    # 4) Verdict: mission engine says PASS *and* independent read-back green.
    engine_pass = state.verdict == "PASS"
    actors_ok = all(read_back.values())
    capture_ok = all(
        e.get("path") and Path(e["path"]).exists() for e in state.evidence
    ) if state.evidence else False
    report["verdict"] = (
        "PASS" if (engine_pass and actors_ok and capture_ok)
        else ("PARTIAL" if engine_pass or actors_ok else "FAIL"))
    report["why"] = (
        f"mission={state.verdict} ({state.why}); live read-back "
        f"{read_back}; capture_ok={capture_ok}")
    report["finished_at"] = time.time()
    report["duration_s"] = round(
        report["finished_at"] - report["started_at"], 1)

    out = Path(__file__).with_suffix(".json")
    out.write_text(json.dumps(report, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "verdict", "why", "engine_version", "project", "mission_id",
        "duration_s")}, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
