"""unreal_coder_api.py — THE canonical UNREAL CODER public API.

ONE endpoint, ONE natural-language request:

    POST /api/unreal-coder
    {
      "prompt": "make me a beautiful sci-fi main menu",
      ...optional advanced fields (project, assets, constraints, quality,
         platform, preferences)...
    }

Composition (all behind the API):
    L1 interpret_intent        (core/universal_intent)
    L2 expand_requirements     (core/universal_intent)
    L3 UniversalPlanner        (core/universal_planner)  [capability-selected]
    L4 CapabilityRegistry      (core/capability_registry)
    L7 asset intake            (tools/unreal/asset_intake)
    execution                  -> existing api executor (run_execution_until_pause
                                  via new_execution) for real Unreal work
    validation                 -> existing visual machinery + task_goal
    checkpoint/resume          -> core/mission.MissionState

The endpoint composes deterministic layers with the EXISTING executor: the
plan normalization/execution/acceptance machinery of app/api.py remains the
single implementation of "run steps against Unreal". No parallel engine.

Chat/plan modes answer directly (no environment mutation).
Execute mode: mission state is persisted (checkpoint/resume) and the request
returns the canonical response envelope from core/mission.mission_response.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from core.capability_registry import build_capability_registry
from core.config import redact
from core.mission import (
    MissionEngine,
    MissionState,
    mission_response,
    resume_latest_mission,
)
from core.observability import MissionLogger, user_result_contract
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from tools.unreal.asset_intake import analyze_asset

# --------------------------------------------------------------------------
# Async mission registry (lifecycle metadata only; real state lives in the
# durable MissionState checkpoints under memory/checkpoints/unreal_coder/)
# --------------------------------------------------------------------------

_ASYNC_RUNS: Dict[str, Dict[str, Any]] = {}


# --------------------------------------------------------------------------
# Request / response models
# --------------------------------------------------------------------------


class UnrealCoderRequest(BaseModel):
    """One-sentence mode needs only `prompt`. Advanced fields optional."""

    prompt: str
    project: Optional[str] = None            # uproject path or project name
    assets: Optional[List[str]] = None       # local paths to ingest
    quality: Optional[str] = None            # quality override
    platform: Optional[str] = None           # platform override
    constraints: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    mode: Optional[str] = None               # force chat|plan|execute
    mission_id: Optional[str] = None         # resume an existing mission
    dry_run: bool = False                    # plan only, no execution


class UnrealCoderAccepted(BaseModel):
    mission_id: str
    status: str
    message: str


# --------------------------------------------------------------------------
# Composition root for the universal layers
# --------------------------------------------------------------------------

def _capability_summary(tool_registry: Dict[str, Any]) -> Dict[str, Any]:
    registry = build_capability_registry(tool_registry)
    return registry.discover()


def build_mission_engine(
    tool_registry: Dict[str, Any],
    dispatch: Any = None,
    capture: Any = None,
    evaluate: Any = None,
    repair: Any = None,
) -> MissionEngine:
    """Create the mission engine bound to the live tool registry.

    When `dispatch` is None the engine plans/checkpoints without executing
    (used by dry_run and by tests); production passes the api dispatcher.
    """
    capabilities = build_capability_registry(tool_registry)
    return MissionEngine(
        tool_registry=tool_registry,
        capabilities=capabilities,
        dispatch=dispatch or (lambda step: {
            "ok": False, "error": "dispatch not configured (dry run)"}),
        capture=capture,
        evaluate=evaluate,
        repair=repair,
    )


def interpret_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """L1+L2(+L3 when dry_run) for one request. Deterministic, no I/O."""
    prompt = str(payload.get("prompt") or "")
    intent = interpret_intent(prompt)
    requirements = expand_requirements(intent)

    # Advanced overrides (optional; never required).
    if payload.get("quality"):
        intent.quality = str(payload["quality"]).lower()
        intent.quality_source = "user"
        requirements.quality = intent.quality
    if payload.get("platform"):
        intent.platforms = [str(payload["platform"]).lower()]
        requirements.platforms = list(intent.platforms)
    if isinstance(payload.get("constraints"), dict):
        for key, value in payload["constraints"].items():
            requirements.requirements.append({
                "id": f"constraint_{key}", "kind": "constraint",
                "desc": f"User constraint: {key}={value}", "ops": [],
            })

    # Asset intake for provided attachments (analysis only; never mutates).
    asset_reports = []
    for asset_path in (payload.get("assets") or []):
        try:
            asset_reports.append(analyze_asset(asset_path).to_dict())
        except Exception as exc:
            asset_reports.append({
                "source_path": str(asset_path), "ok": False,
                "warnings": [f"intake analysis failed: {exc}"],
            })

    return {
        "intent": intent.to_dict(),
        "requirements": requirements.to_dict(),
        "asset_reports": asset_reports,
    }


# --------------------------------------------------------------------------
# Router registration (called from app/served.py composition root)
# --------------------------------------------------------------------------

def _default_visual_adapters(tool_registry, scene_locators=None):
    """Build visual-loop adapters from the LIVE registry and the existing
    deterministic visual acceptance machinery (core/visual_acceptance.py).

    capture:  the registered capture tool (real editor viewport screenshot)
    evaluate: deterministic measurement + scoring -> {score, defects}
    repair:   defect->action via the existing Visual Director mapping
    """
    registry = _tool_registry_value(tool_registry)
    capture_spec = registry.get("capture_unreal_viewport")

    def capture():
        if capture_spec is None:
            return {"ok": False, "error": "capture tool unavailable"}
        raw = capture_spec.func()
        from app.api import _tool_payload
        payload = _tool_payload(raw) if isinstance(raw, dict) else {}
        inner = payload.get("result") if isinstance(
            payload.get("result"), dict) else payload
        diagnostic = str((inner or {}).get("diagnostic") or "")
        # Native capture can return a file while the editor viewport is
        # hidden.  That file is diagnostic-only, never valid release proof.
        native_invisible = (
            "source=LevelViewport" in diagnostic
            and "visible=0" in diagnostic
        )
        return {
            "ok": bool((inner or {}).get("ok")) and not native_invisible,
            "path": (inner or {}).get("path"),
            "tool": "capture_unreal_viewport",
            "error": ("editor viewport was not visible" if native_invisible
                      else None),
            "diagnostic": diagnostic,
        }

    def evaluate(captured):
        """Production visual review (Phase B): deterministic measurement plus
        configured vision providers, with disagreement handling. Never raises;
        provider failure degrades to deterministic-only."""
        from core.visual_acceptance import measure, score
        from core import vision_provider
        path = (captured or {}).get("path")
        locator_kw = {}
        if scene_locators:
            for key in ("subject_locator", "ui_locator"):
                fn = scene_locators.get(key)
                if fn is not None:
                    locator_kw[key] = fn
        metrics = measure(path or "", **locator_kw)
        if not metrics.ok:
            return {"score": 0.0, "defects": ["CAPTURE_UNREADABLE"],
                    "metrics": {"ok": False}, "review": {"ok": False}}
        s = score(metrics)
        defects: list = list(metrics.issues)
        # Deterministic defect mapping from the measured values.
        if metrics.pct_white > 0.10:
            defects.append("WHITE_CLIPPING")
        if metrics.pct_black > 0.30:
            defects.append("BLACK_CLIPPING")
        if metrics.mean_luma < 40:
            defects.append("SUBJECT_TOO_DARK")
        review = vision_provider.review_image(
            path or "", providers=vision_provider.get_configured_providers(),
            metrics=metrics, score=s)
        # When a vision model contributed (and agreed), its defect vocabulary
        # enriches the deterministic defect list; deterministic always wins
        # on strong conflict (handled inside review_image).
        for d in (review.get("defects") or []):
            if d not in defects:
                defects.append(d)
        return {"score": float(s.overall), "defects": defects,
                "metrics": {"mean_luma": metrics.mean_luma,
                            "entropy": metrics.entropy,
                            "technical_integrity": s.technical_integrity},
                "review": review}

    def repair(defects):
        """Apply a bounded, read-back-verified camera repair when safe.

        The generic Visual Director is still the policy source, but policy
        text is not evidence of a repair.  Only the camera label created by
        the universal mission is touched here; other defects explicitly stop
        for a different scene strategy rather than mutating unknown content.
        """
        from core.visual_director import defect_to_action
        defect = str(defects[0] if defects else "").split(":", 1)[0].upper()
        action = defect_to_action(defect)
        bridge = _resolve_live_bridge(registry)
        if bridge is None:
            return {"ok": False, "action": action,
                    "error": "live Unreal bridge unavailable for repair"}
        camera_label = "UA_Cam_Intro"
        if defect == "CAMERA_ROLL":
            camera = bridge.get_actor(camera_label)
            payload = camera.get("result", camera) if isinstance(camera, dict) else {}
            rotation = payload.get("rotation") if isinstance(payload, dict) else None
            if not (isinstance(rotation, list) and len(rotation) == 3):
                return {"ok": False, "action": action,
                        "error": "mission camera read-back unavailable"}
            changed = bridge.rotate_actor(camera_label,
                                          [rotation[0], rotation[1], 0.0])
            framed = bridge.frame_viewport_from_actor(camera_label)
            return {"ok": bool(_bridge_ok(changed) and _bridge_ok(framed)),
                    "action": action, "camera": camera_label,
                    "change": changed, "readback": framed}
        if defect in {"HEAD_CROPPED", "SUBJECT_TOO_LARGE"}:
            framed = bridge.frame_viewport_from_actor(camera_label, 180.0)
            return {"ok": bool(_bridge_ok(framed)), "action": action,
                    "camera": camera_label, "readback": framed}
        return {"ok": False, "action": action,
                "error": "defect requires scene-specific repair; no unknown actors modified"}

    return capture, evaluate, repair


# ---------------------------------------------------------------------------
# Shared execute-mode tail (ONE execution path for sync + async entry points)
# ---------------------------------------------------------------------------

def _execute_mission_state(
    state: MissionState,
    request: "UnrealCoderRequest",
    tool_registry,
    dispatch_bridge=None,
    capture=None,
    evaluate=None,
    repair=None,
    scene_locators=None,
    cancel_provider: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Run an interpreted/planned mission through the EXISTING machinery.

    Exactly one execution path exists: project safety guard -> engine.run
    (real registered-tool dispatch with hard timeouts) -> technical +
    visual validation -> canonical mission_response envelope. Both the
    synchronous POST /api/unreal-coder and the asynchronous variant call
    this function, so there is no parallel execution engine.

    cancel_provider: optional zero-arg callable returning True when the
    mission must stop at the next step boundary (used by async cancel).
    """
    run_capture, run_evaluate, run_repair = (
        (capture, evaluate, repair) if capture is not None
        else _default_visual_adapters(tool_registry,
                                       scene_locators=scene_locators))

    def production_dispatch(step, _registry=_tool_registry_value(
            tool_registry)):
        tool = step.get("preferred_tool")
        spec = _registry.get(tool)
        if spec is None:
            return {"ok": False, "error": f"Unknown tool {tool}"}
        args = dict(step.get("parameters") or {})
        from app.api import call_tool_hard_timeout, _tool_success
        try:
            raw = call_tool_hard_timeout(spec, args)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": _tool_success(raw), "result": raw, "tool": tool}

    dispatch_target = dispatch_bridge or production_dispatch

    if cancel_provider is not None:
        def cancellable_dispatch(step, _inner=dispatch_target):
            if cancel_provider():
                raise RuntimeError("MISSION_CANCELLED_BY_USER")
            return _inner(step)
        dispatch_target = cancellable_dispatch

    # -- project safety guard (Phase C) ---------------------------------
    # Every MUTATING step re-validates the live editor session: project
    # identity, editor PID, active map, PIE state. Cross-project mutation
    # is blocked with a structured WRONG_PROJECT error, never executed.
    mission_log = MissionLogger(state.mission_id)
    try:
        from core.project_safety import ProjectMutationGuard, guard_dispatch
        bridge = _resolve_live_bridge(_tool_registry_value(tool_registry))
        guard = ProjectMutationGuard(bridge=bridge)
        identity = guard.capture_identity()
        if identity.uproject_path:
            mission_log.project = identity.to_dict()
            dispatch_base = guard_dispatch(dispatch_target, guard)
        else:
            # No live editor: dry-run/planning style missions still work;
            # mutating steps will fail at dispatch with a bridge error.
            dispatch_base = dispatch_target
            mission_log.warning(
                "no live editor session; project guard passive")
    except Exception as guard_exc:
        dispatch_base = dispatch_target
        mission_log.warning(
            f"project guard unavailable: {type(guard_exc).__name__}")

    engine = build_mission_engine(
        _tool_registry_value(tool_registry),
        dispatch=dispatch_base,
        capture=run_capture,
        evaluate=run_evaluate,
        repair=run_repair,
    )
    state = engine.run(state)
    mission_log.event(
        "mission_finished", phase="validate", result=state.verdict or "",
        detail={"completed": len(state.completed_step_ids)})
    mission_log.save()
    response = mission_response(state)
    # Phase T: simple user contract alongside the machine envelope.
    response["user_result"] = user_result_contract(state, mission_log)
    response["mission_log"] = str(
        (Path(__file__).resolve().parents[1] / "memory" / "mission_logs"
         / f"{state.mission_id}.json"))
    return response


def register_unreal_coder_api(
    app,
    tool_registry,
    dispatch_bridge=None,
    capture=None,
    evaluate=None,
    repair=None,
    scene_locators=None,
):
    """Register POST /api/unreal-coder (+ status/resume) on the FastAPI app.

    dispatch_bridge: optional callable(step)->result wired to the existing
    executor. In production app/api.py passes its deterministic dispatcher so
    universal missions run on the same machinery as /api/chat execute mode.

    capture/evaluate/repair: optional visual-loop adapters. When omitted,
    sensible defaults are built from the live bridge capture tool and the
    deterministic visual acceptance measurement, so execute-mode missions
    produce real visual evidence without caller wiring.
    """

    @app.post("/api/unreal-coder")
    def unreal_coder(request: UnrealCoderRequest):
        prompt = request.prompt.strip()
        if not prompt:
            from fastapi import HTTPException
            raise HTTPException(400, "prompt cannot be empty")

        # -- resume path ------------------------------------------------
        if request.mission_id:
            state = MissionState.load(request.mission_id)
            if state is None:
                from fastapi import HTTPException
                raise HTTPException(404, f"Unknown mission {request.mission_id}")
        else:
            state = MissionState(
                mission_id=f"mission_{uuid.uuid4().hex[:12]}",
                prompt=prompt,
            )
            state.started_at = time.time()

        interpretation = interpret_request(request.model_dump())

        # Chat/plan modes: direct answer, no environment mutation.
        mode = request.mode or interpretation["intent"]["mode"]
        if mode == "chat" and not request.dry_run:
            from core.orchestrator import run_chat
            answer = run_chat(prompt, [])
            return {
                "mission_id": state.mission_id,
                "status": "complete",
                "verdict": "PASS",
                "mode": "chat",
                "message": answer,
                "interpretation": interpretation["intent"],
            }

        state.intent = interpretation["intent"]
        state.requirements = interpretation["requirements"]
        state.status = "planning"
        state.save()

        # -- plan ---------------------------------------------------------
        engine = build_mission_engine(
            _tool_registry_value(tool_registry),
            dispatch=dispatch_bridge,
        )
        planner = build_universal_planner(_tool_registry_value(tool_registry))
        intent_obj = interpret_intent(prompt)
        # Keep the planner in sync with the public advanced quality override.
        # Without this, the response intent can say "release" while the
        # execution plan silently falls back to the prompt-derived tier.
        if request.quality:
            intent_obj.quality = str(request.quality).lower()
            intent_obj.quality_source = "user"
        requirements_obj = expand_requirements(intent_obj)
        mission_plan = planner.build_plan(
            intent_obj, requirements_obj, None)
        state.plan = mission_plan.to_dict()
        state.status = "executing" if not request.dry_run else "planning"
        state.save()

        if request.dry_run:
            return mission_response(state)

        # -- execute (existing dispatcher) ---------------------------------
        # Runs through the single shared execution path (project guard +
        # real tool dispatch + validation); see _execute_mission_state.
        return _execute_mission_state(
            state, request, tool_registry,
            dispatch_bridge=dispatch_bridge,
            capture=capture, evaluate=evaluate, repair=repair,
            scene_locators=scene_locators,
        )

    # ------------------------------------------------------------------
    # ASYNC / VALIDATE / RETRY / CANCEL — the ClickUp MCP gateway surface.
    # No second execution engine: every handler reuses the mission pipeline
    # above (interpret -> plan -> _execute_mission_state -> validation), and
    # the Unreal bridge stays the only execution layer.
    # ------------------------------------------------------------------

    @app.post("/api/unreal-coder/async")
    def unreal_coder_async(request: UnrealCoderRequest):
        """Start a mission in the background and return its id immediately.

        The worker thread runs the exact same pipeline as POST /api/unreal-coder
        (same dispatcher, guard and validation). Real progress is readable at
        any time from GET /api/unreal-coder/mission/{mission_id} because every
        state transition is checkpointed by MissionState.save().
        """
        prompt = request.prompt.strip()
        if not prompt:
            from fastapi import HTTPException
            raise HTTPException(400, "prompt cannot be empty")

        state = MissionState(
            mission_id=f"mission_{uuid.uuid4().hex[:12]}",
            prompt=prompt,
        )
        state.started_at = time.time()

        interpretation = interpret_request(request.model_dump())
        state.intent = interpretation["intent"]
        state.requirements = interpretation["requirements"]
        state.status = "planning"
        state.save()

        # -- plan (same as the synchronous endpoint) ----------------------
        planner = build_universal_planner(_tool_registry_value(tool_registry))
        intent_obj = interpret_intent(prompt)
        if request.quality:
            intent_obj.quality = str(request.quality).lower()
            intent_obj.quality_source = "user"
        requirements_obj = expand_requirements(intent_obj)
        mission_plan = planner.build_plan(
            intent_obj, requirements_obj, None)
        state.plan = mission_plan.to_dict()
        state.status = "executing"
        state.save()

        _ASYNC_RUNS[state.mission_id] = {
            "running": True,
            "cancel_flag": False,
            "error": None,
        }

        def worker():
            try:
                _execute_mission_state(
                    state, request, tool_registry,
                    dispatch_bridge=dispatch_bridge,
                    capture=capture, evaluate=evaluate, repair=repair,
                    scene_locators=scene_locators,
                    cancel_provider=lambda: bool(
                        _ASYNC_RUNS.get(state.mission_id, {}).get(
                            "cancel_flag")),
                )
            except Exception as exc:
                entry = _ASYNC_RUNS.get(state.mission_id)
                current = MissionState.load(state.mission_id) or state
                if entry and entry.get("cancel_flag"):
                    current.status = "blocked"
                    current.verdict = "CANCELLED"
                    current.why = (
                        "Mission cancelled by user request "
                        "(ClickUp MCP gateway).")
                    current.finished_at = time.time()
                    current.save()
                else:
                    if entry is not None:
                        entry["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                entry = _ASYNC_RUNS.get(state.mission_id)
                if entry is not None:
                    entry["running"] = False

        threading.Thread(
            target=worker,
            name=f"unreal-coder-async-{state.mission_id}",
            daemon=True,
        ).start()

        return {
            "ok": True,
            "mission_id": state.mission_id,
            "status": "accepted",
            "message": (
                "Mission accepted; poll "
                f"GET /api/unreal-coder/mission/{state.mission_id} "
                "for real state."
            ),
        }

    @app.post("/api/unreal-coder/mission/{mission_id}/validate")
    def unreal_coder_validate(mission_id: str):
        """Re-run REAL validation (technical gate + fresh visual acceptance
        capture/score through the existing visual machinery) on a mission."""
        from fastapi import HTTPException
        state = MissionState.load(mission_id)
        if state is None:
            raise HTTPException(404, f"Unknown mission {mission_id}")
        if (
            state.status in ("interpreting", "planning", "executing")
            or not (state.plan or {}).get("steps")
        ):
            raise HTTPException(
                409,
                "Mission has no completed steps to validate yet; "
                "poll get_task_status until execution finishes.",
            )
        run_capture, run_evaluate, run_repair = (
            (capture, evaluate, repair) if capture is not None
            else _default_visual_adapters(tool_registry,
                                           scene_locators=scene_locators))
        engine = build_mission_engine(
            _tool_registry_value(tool_registry),
            dispatch=dispatch_bridge or (
                lambda step: {"ok": False, "error": "validation-only mode"}),
            capture=run_capture,
            evaluate=run_evaluate,
            repair=run_repair,
        )
        state = engine.validate(state)
        return mission_response(state)

    @app.post("/api/unreal-coder/mission/{mission_id}/resume")
    def unreal_coder_resume_by_id(mission_id: str):
        """Retry/resume ONE mission by id through the real engine.

        Completed steps are skipped from the checkpoint; failed/pending
        steps re-dispatch through the existing executor, then validation
        runs again. A previously CANCELLED mission is retried too.
        """
        from fastapi import HTTPException
        state = MissionState.load(mission_id)
        if state is None:
            raise HTTPException(404, f"Unknown mission {mission_id}")
        entry = _ASYNC_RUNS.get(mission_id)
        if entry is not None and entry.get("running"):
            raise HTTPException(
                409,
                "Mission is still executing in this process; wait for it to "
                "stop (cancel it first) before retrying.",
            )
        if entry is not None and entry.get("cancel_flag"):
            entry["cancel_flag"] = False
        run_capture, run_evaluate, run_repair = (
            (capture, evaluate, repair) if capture is not None
            else _default_visual_adapters(tool_registry,
                                           scene_locators=scene_locators))
        registry = _tool_registry_value(tool_registry)

        def production_dispatch(step):
            tool = step.get("preferred_tool")
            spec = registry.get(tool)
            if spec is None:
                return {"ok": False, "error": f"Unknown tool {tool}"}
            from app.api import call_tool_hard_timeout, _tool_success
            try:
                raw = call_tool_hard_timeout(
                    spec, dict(step.get("parameters") or {}))
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": _tool_success(raw), "result": raw, "tool": tool}

        engine = build_mission_engine(
            registry, dispatch=dispatch_bridge or production_dispatch,
            capture=run_capture, evaluate=run_evaluate, repair=run_repair)
        state = engine.run(state)
        return mission_response(state)

    @app.post("/api/unreal-coder/mission/{mission_id}/cancel")
    def unreal_coder_cancel(mission_id: str):
        """Cancel a running mission. The async worker stops at the next step
        boundary and the checkpoint is finalized as CANCELLED (never a fake
        SUCCESS). Missions not running in this process are marked directly.
        """
        from fastapi import HTTPException
        state = MissionState.load(mission_id)
        if state is None:
            raise HTTPException(404, f"Unknown mission {mission_id}")
        entry = _ASYNC_RUNS.get(mission_id)
        if entry is not None:
            entry["cancel_flag"] = True
            # Wait (bounded) for the worker to stop at the next step
            # boundary and finalize the checkpoint, so the caller sees the
            # real terminal state instead of a mid-flight snapshot.
            deadline = time.time() + 30.0
            while time.time() < deadline:
                current = MissionState.load(mission_id)
                running = bool(entry.get("running"))
                if not running or current is None \
                        or current.status != "executing":
                    break
                time.sleep(0.5)
        else:
            state.status = "blocked"
            state.verdict = "CANCELLED"
            state.why = "Mission cancelled by user request (ClickUp MCP gateway)."
            state.finished_at = time.time()
            state.save()
        return mission_response(MissionState.load(mission_id) or state)

    @app.get("/api/unreal-coder/capabilities")
    def unreal_coder_capabilities():
        return _capability_summary(_tool_registry_value(tool_registry))

    @app.get("/api/unreal-coder/mission/{mission_id}")
    def unreal_coder_mission(mission_id: str):
        state = MissionState.load(mission_id)
        if state is None:
            from fastapi import HTTPException
            raise HTTPException(404, f"Unknown mission {mission_id}")
        response = mission_response(state)
        # Same evidence-locator fields the execution response carries, so
        # external consumers (e.g. the ClickUp MCP gateway) can find the
        # real mission log for evidence retrieval.
        response["mission_log"] = str(
            Path(__file__).resolve().parents[1] / "memory" / "mission_logs"
            / f"{mission_id}.json")
        return response

    @app.get("/api/unreal-coder/doctor")
    def unreal_coder_doctor():
        """Structured PASS/WARN/FAIL setup report (Phase D)."""
        from core import doctor as doctor_mod
        report = doctor_mod.run_doctor()
        return report

    @app.get("/api/unreal-coder/session")
    def unreal_coder_session():
        """Live editor session identity (Phase C transparency)."""
        from core.project_safety import active_session_identity
        identity = active_session_identity(
            _resolve_live_bridge(_tool_registry_value(tool_registry)))
        if identity is None:
            return {"ok": False, "message": "No live editor session."}
        return {"ok": True, "session": identity.to_dict()}

    @app.post("/api/unreal-coder/resume")
    def unreal_coder_resume():
        latest = resume_latest_mission()
        if latest is None:
            return {"ok": False, "message": "No resumable mission checkpoint."}
        run_capture, run_evaluate, run_repair = (
            (capture, evaluate, repair) if capture is not None
            else _default_visual_adapters(tool_registry,
                                           scene_locators=scene_locators))
        registry = _tool_registry_value(tool_registry)

        def production_dispatch(step):
            tool = step.get("preferred_tool")
            spec = registry.get(tool)
            if spec is None:
                return {"ok": False, "error": f"Unknown tool {tool}"}
            from app.api import call_tool_hard_timeout, _tool_success
            try:
                raw = call_tool_hard_timeout(spec, dict(step.get("parameters") or {}))
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": _tool_success(raw), "result": raw, "tool": tool}

        engine = build_mission_engine(
            registry, dispatch=dispatch_bridge or production_dispatch,
            capture=run_capture, evaluate=run_evaluate, repair=run_repair)
        latest = engine.run(latest)
        return mission_response(latest)


def _tool_registry_value(tool_registry):
    """Support both plain dict registries and zero-arg providers."""
    if callable(tool_registry) and not isinstance(tool_registry, dict):
        return tool_registry()
    return tool_registry


def _resolve_live_bridge(registry: Dict[str, Any]):
    """Find the live UnrealBridge instance behind the tool registry."""
    for spec in (registry or {}).values():
        owner = getattr(getattr(spec, "func", None), "__self__", None)
        if owner is not None and owner.__class__.__name__ == "UnrealBridge":
            return owner
    return None


def _bridge_ok(result: Any) -> bool:
    """Normalize the bridge envelope without treating transport success as work."""
    if not isinstance(result, dict):
        return False
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    return bool(isinstance(payload, dict) and payload.get("ok"))
