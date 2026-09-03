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
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.capability_registry import build_capability_registry
from core.mission import (
    MissionEngine,
    MissionState,
    mission_response,
    resume_latest_mission,
)
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from tools.unreal.asset_intake import analyze_asset

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

def register_unreal_coder_api(app, tool_registry, dispatch_bridge=None):
    """Register POST /api/unreal-coder (+ status/resume) on the FastAPI app.

    dispatch_bridge: optional callable(step)->result wired to the existing
    executor. In production app/api.py passes its deterministic dispatcher so
    universal missions run on the same machinery as /api/chat execute mode.
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
        planner = build_universal_planner(
            _tool_registry_value(tool_registry))
        intent_obj = interpret_intent(prompt)
        requirements_obj = expand_requirements(intent_obj)
        mission_plan = planner.build_plan(
            intent_obj, requirements_obj, None)
        state.plan = mission_plan.to_dict()
        state.status = "executing" if not request.dry_run else "planning"
        state.save()

        if request.dry_run:
            return mission_response(state)

        # -- execute (existing dispatcher) ---------------------------------
        state = engine.run(state)
        return mission_response(state)

    @app.get("/api/unreal-coder/capabilities")
    def unreal_coder_capabilities():
        return _capability_summary(_tool_registry_value(tool_registry))

    @app.get("/api/unreal-coder/mission/{mission_id}")
    def unreal_coder_mission(mission_id: str):
        state = MissionState.load(mission_id)
        if state is None:
            from fastapi import HTTPException
            raise HTTPException(404, f"Unknown mission {mission_id}")
        return mission_response(state)

    @app.post("/api/unreal-coder/resume")
    def unreal_coder_resume():
        latest = resume_latest_mission()
        if latest is None:
            return {"ok": False, "message": "No resumable mission checkpoint."}
        engine = build_mission_engine(
            _tool_registry_value(tool_registry), dispatch=dispatch_bridge)
        latest = engine.run(latest)
        return mission_response(latest)


def _tool_registry_value(tool_registry):
    """Support both plain dict registries and zero-arg providers."""
    if callable(tool_registry) and not isinstance(tool_registry, dict):
        return tool_registry()
    return tool_registry
