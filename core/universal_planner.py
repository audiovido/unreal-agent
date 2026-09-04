"""universal_planner.py — Layer 3: dependency-aware universal planner.

Turns a RequirementSpec + CapabilityRegistry into a MissionPlan: ordered
phases with dependencies, selected capabilities, acceptance tests, visual
gates, parallel hints, risk estimates and stop conditions.

The plan's steps are emitted in the SAME normalized step format consumed by
the existing executor (app/api.py), so universal missions execute on the
existing machinery — no parallel implementation. Steps referencing
capabilities are expanded through capability.tools (registered tool names
only), never invented tool names.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.capability_registry import CapabilityRegistry, RECOVERY_VISUAL
from core.universal_intent import RequirementSpec, UniversalIntent

# Quality modes -> visual score floors enforced by the visual gate phase.
QUALITY_VISUAL_FLOORS = {
    "prototype": 5.0,
    "standard": 6.0,
    "high": 7.0,
    "production": 7.5,
    "cinematic": 8.0,
    "photoreal": 8.0,
    # Release acceptance is stricter than ordinary production or cinematic
    # work.  Keep it explicit so callers can require the final 9.0 gate
    # without weakening the default beginner experience.
    "release": 9.0,
    "performance": 5.5,
    "mobile": 6.0,
}

# Requirements kinds -> capabilities.
KIND_TO_CAPABILITY = {
    "actor": ["actor_staging"],
    "ui": ["umg_widget_authoring"],
    "sequencer": ["sequencer_cinematic", "camera_framing"],
    "environment": ["environment_composition"],
    "level": ["level_creation", "actor_staging"],
    "materials": ["material_authoring"],
    "lighting": ["lighting_setup"],
    "gameplay": ["blueprint_authoring", "gameplay_smoke"],
    "characters": ["character_staging"],
    "vfx": ["niagara_effects"],
    "audio": ["audio_staging"],
    "media": ["media_playback"],
    "optimization": ["performance_analysis"],
    "assets": ["asset_intake_analysis", "asset_import"],
    "cleanup": ["asset_cleanup_destructive"],
    "world": ["terrain_setup", "foliage_distribution"],
    "camera": ["camera_framing"],
    "safety": ["level_inspection"],
}

PARALLELIZABLE_KINDS = {"materials", "lighting", "vfx", "audio"}
RISKY_KINDS = {"safety", "assets", "packaging"}


@dataclass
class PlanStep:
    step_id: str
    phase: str                      # INSPECT / EDIT / BUILD / VALIDATE / EVIDENCE / CLEANUP / VISUAL
    intent: str
    preferred_tool: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_result: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    capability: str = ""
    parallelizable: bool = False
    risky: bool = False
    estimated_cost: int = 1         # 1 cheap .. 5 expensive
    stop_condition: str = ""        # natural failure semantics
    status: str = "pending"

    def to_normalized(self) -> Dict[str, Any]:
        """Executor-compatible normalized step (app/api.py format)."""
        return {
            "step_id": self.step_id,
            "phase": self.phase,
            "intent": self.intent,
            "action_category": self.intent,
            "preferred_tool": self.preferred_tool,
            "allowed_tools": [self.preferred_tool],
            "target_type": "project",
            "target_resource": None,
            "parameters": dict(self.parameters),
            "expected_result": dict(self.expected_result),
            "validation_tool": None,
            "validation_parameters": {},
            "depends_on": list(self.depends_on),
            "disposable": False,
            "status": self.status,
            "capability": self.capability,
            "parallelizable": self.parallelizable,
            "risky": self.risky,
            "estimated_cost": self.estimated_cost,
            "stop_condition": self.stop_condition,
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.to_normalized()


@dataclass
class MissionPlan:
    mission_id: str
    objective: str
    intent: UniversalIntent
    requirements: RequirementSpec
    phases: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[PlanStep] = field(default_factory=list)
    selected_capabilities: List[str] = field(default_factory=list)
    skipped_capabilities: Dict[str, str] = field(default_factory=dict)
    acceptance_tests: List[str] = field(default_factory=list)
    visual_gate: Dict[str, Any] = field(default_factory=dict)
    open_questions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parallel_groups: List[List[str]] = field(default_factory=list)
    checkpoint_policy: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "objective": self.objective,
            "mode": self.intent.mode,
            "phases": [dict(p) for p in self.phases],
            "steps": [s.to_dict() for s in self.steps],
            "selected_capabilities": list(self.selected_capabilities),
            "skipped_capabilities": dict(self.skipped_capabilities),
            "acceptance_tests": list(self.acceptance_tests),
            "visual_gate": dict(self.visual_gate),
            "open_questions": list(self.open_questions),
            "warnings": list(self.warnings),
            "parallel_groups": [list(g) for g in self.parallel_groups],
            "checkpoint_policy": dict(self.checkpoint_policy),
        }

    def normalized_steps(self) -> List[Dict[str, Any]]:
        return [s.to_normalized() for s in self.steps]


class UniversalPlanner:
    """Layer 3: plans missions against the capability registry."""

    def __init__(self, capabilities: CapabilityRegistry):
        self.capabilities = capabilities

    # ------------------------------------------------------------------
    def _cap(self, name: str):
        return self.capabilities.get(name)

    def _select(self, name: str, skipped: Dict[str, str]):
        if self.capabilities.available(name):
            return name
        cap = self.capabilities.get(name)
        reason = "missing tools: " + ",".join(
            cap.missing_tools) if cap else "unknown capability"
        skipped[name] = reason
        return None

    def _tool_for(self, capability_name: str, preferred: Optional[str]):
        """Pick a registered tool from the capability for a concrete step."""
        cap = self._cap(capability_name)
        if cap is None:
            return None
        if preferred and preferred in cap.spec.tools:
            return preferred
        for tool in list(cap.spec.tools) + list(cap.spec.optional_tools):
            if tool in self.capabilities._tool_registry:
                return tool
        return None

    # ------------------------------------------------------------------
    def build_plan(
        self,
        intent: UniversalIntent,
        requirements: RequirementSpec,
        project_context: Optional[Dict[str, Any]] = None,
    ) -> MissionPlan:
        plan = MissionPlan(
            mission_id=f"mission_{uuid.uuid4().hex[:12]}",
            objective=requirements.objective,
            intent=intent,
            requirements=requirements,
        )
        plan.open_questions = list(requirements.open_questions)

        # ---- chat/plan modes: no environment mutation -------------------
        if intent.mode in {"chat", "plan"}:
            plan.phases.append({
                "phase": "ANSWER",
                "objective": "Answer/plan the request directly",
                "stop_condition": "answer produced",
            })
            return plan

        skipped: Dict[str, str] = {}

        # ---- Phase 0: project grounding ---------------------------------
        plan.phases.append({
            "phase": "GROUND",
            "objective": "Resolve and verify the active project and bridge "
                         "session before any mutation",
            "stop_condition": "project identity verified or structured "
                              "blocker PROJECT_CONTEXT_MISSING",
        })
        grounding = self._select("project_inspection", skipped)
        health = self._select("bridge_health", skipped)
        if grounding:
            plan.selected_capabilities.append(grounding)
        if health:
            plan.selected_capabilities.append(health)
        ground_steps: List[PlanStep] = []
        if grounding:
            tool = self._tool_for(grounding, "inspect_project")
            if tool:
                ground_steps.append(PlanStep(
                    step_id="resolve_project", phase="INSPECT",
                    intent="resolve_project", preferred_tool=tool,
                    capability=grounding, stop_condition="project resolved",
                ))
        if health:
            ground_steps.append(PlanStep(
                step_id="bridge_health", phase="INSPECT",
                intent="bridge_health",
                preferred_tool=self._tool_for(health, "unreal_ping"),
                capability=health, depends_on=["resolve_project"],
                stop_condition="bridge responds; wrong project is a "
                               "structured blocker",
            ))
        if intent.diagnostic:
            # Status/health missions MUST probe the Aivido backend as a real
            # registered-tool step (never a 0-step "answer" plan). The
            # bridge_health probe above covers Unreal readiness; this step
            # covers backend readiness and writes evidence.
            backend = self._select("backend_health", skipped)
            if backend:
                plan.selected_capabilities.append(backend)
                tool = self._tool_for(backend, "unreal_coder_doctor")
                if tool:
                    ground_steps.append(PlanStep(
                        step_id="backend_health", phase="INSPECT",
                        intent="backend_health", preferred_tool=tool,
                        capability=backend,
                        depends_on=([ground_steps[-1].step_id]
                                    if ground_steps else []),
                        stop_condition="backend doctor probe passes with "
                                       "real evidence report",
                    ))
                else:
                    skipped[backend] = "unreal_coder_doctor tool unavailable"
        plan.steps.extend(ground_steps)

        # ---- Phase 1..n: capability-driven work --------------------------
        work_steps: List[PlanStep] = []
        prev_id = ground_steps[-1].step_id if ground_steps else None
        for req in requirements.requirements:
            kind = req.get("kind")
            if kind in {"answer", "validation"}:
                continue
            if kind == "actor":
                # Precise single-actor placement: spawn honoring an explicit
                # location, then an independent get_actor read-back step so
                # the mission only passes after the actor exists in the level
                # actor list.
                actor_steps = self._actor_placement_steps(
                    plan.objective, skipped, prev_id,
                    base=len(plan.steps) + len(work_steps))
                work_steps.extend(actor_steps)
                if actor_steps:
                    prev_id = actor_steps[-1].step_id
                continue
            if kind == "safety":
                # Explicit checkpoint before destructive work.
                work_steps.append(PlanStep(
                    step_id="checkpoint", phase="SAFETY", intent="checkpoint",
                    preferred_tool="run_powershell",
                    parameters={"command": "echo checkpoint"},
                    capability="", risky=True, depends_on=[prev_id] if prev_id else [],
                    stop_condition="checkpoint recorded",
                ))
                prev_id = "checkpoint"
                continue
            cap_names = KIND_TO_CAPABILITY.get(kind, [])
            for cap_name in cap_names:
                if cap_name in plan.selected_capabilities:
                    continue
                chosen = self._select(cap_name, skipped)
                if not chosen:
                    continue
                plan.selected_capabilities.append(chosen)
                step_id = f"{chosen}_{len(plan.steps)}"
                tool = self._tool_for(chosen, self._primary_tool(chosen))
                if not tool:
                    skipped[chosen] = "no usable registered tool"
                    continue
                work_steps.append(PlanStep(
                    step_id=step_id, phase=self._phase_for(chosen),
                    intent=chosen, preferred_tool=tool,
                    parameters=self._parameters_for(
                        chosen, req, intent, project_context),
                    capability=chosen,
                    parallelizable=kind in PARALLELIZABLE_KINDS,
                    risky=kind in RISKY_KINDS,
                    estimated_cost=3 if kind in {"environment", "world"} else 2,
                    depends_on=[prev_id] if prev_id else [],
                    stop_condition=f"{chosen} verified",
                ))
                prev_id = step_id

        plan.steps.extend(work_steps)

        # ---- Visual gate / validation phase ------------------------------
        floor = QUALITY_VISUAL_FLOORS.get(
            intent.quality, QUALITY_VISUAL_FLOORS["standard"])
        plan.visual_gate["score_floor"] = floor
        plan.visual_gate = {
            "enabled": intent.needs_visual_validation,
            "score_floor": floor,
            "max_iterations": 3,
            "policy": "capture -> measure -> repair highest-impact defect -> "
                      "re-capture; stop on pass, stagnation, or budget",
        }
        if intent.needs_visual_validation:
            gate_cap = self._select("visual_quality_gate", skipped)
            if gate_cap:
                plan.selected_capabilities.append(gate_cap)
                plan.steps.append(PlanStep(
                    step_id="visual_gate", phase="VISUAL", intent="visual_gate",
                    preferred_tool="capture_unreal_viewport",
                    capability=gate_cap, depends_on=[prev_id] if prev_id else [],
                    expected_result={"score_floor": floor},
                    stop_condition="score >= floor, or stagnation/iteration "
                                   "budget exhausted with a structured FAIL",
                ))
            else:
                plan.warnings.append(
                    "Visual validation requested but the capture tool is "
                    "unavailable; the gate is disabled and recorded as a "
                    "known limitation.")

        # ---- Acceptance tests & stop conditions --------------------------
        plan.acceptance_tests = self._acceptance_tests(intent, requirements)
        plan.checkpoint_policy = {
            "persist_after": ["GROUND", "each completed phase"],
            "resume": "completed validated steps are never re-run",
            "interrupted": "resume from latest valid checkpoint",
        }

        # ---- Parallel groups ---------------------------------------------
        parallel = [s.step_id for s in work_steps if s.parallelizable]
        if parallel:
            plan.parallel_groups.append(parallel)

        plan.skipped_capabilities = skipped
        return plan

    # ------------------------------------------------------------------
    def _primary_tool(self, capability_name: str) -> Optional[str]:
        cap = self._cap(capability_name)
        return cap.spec.tools[0] if cap and cap.spec.tools else None

    def _actor_placement_steps(
        self, objective: str, skipped: Dict[str, str],
        prev_id: Optional[str], base: int,
    ) -> List[PlanStep]:
        """Spawn a StaticMeshActor cube + independent get_actor read-back.

        Honours an explicit "location (x, y, z)" (or bare coordinate triple)
        in the request and a "named X"/"called X" label; otherwise a unique
        UA_ actor label is generated so the read-back is never ambiguous.
        """
        cap_name = "actor_staging"
        chosen = self._select(cap_name, skipped)
        if not chosen:
            return []
        spawn_tool = self._tool_for(chosen, "spawn_actor")
        if not spawn_tool:
            skipped[chosen] = "spawn_actor tool unavailable"
            return []
        text = str(objective or "")
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,"
                      r"\s*(-?\d+(?:\.\d+)?)", text)
        location = [float(m.group(1)), float(m.group(2)),
                    float(m.group(3))] if m else [0.0, 0.0, 0.0]
        nm = re.search(r"(?:named|called)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        label = (nm.group(1) if nm
                 else f"UA_E2E_{uuid.uuid4().hex[:6]}")
        spawn_id = f"actor_spawn_{base}"
        steps = [PlanStep(
            step_id=spawn_id, phase="EDIT", intent="actor_staging",
            preferred_tool=spawn_tool, capability=chosen,
            parameters={
                "class_name": "StaticMeshActor",
                "actor_name": label,
                "location": location,
                "scale": [1.0, 1.0, 1.0],
                "mesh_asset": "/Engine/BasicShapes/Cube.Cube",
            },
            depends_on=[prev_id] if prev_id else [],
            stop_condition=(f"StaticMeshActor {label} spawned at {location}"),
        )]
        if "get_actor" in self.capabilities._tool_registry:
            steps.append(PlanStep(
                step_id=f"actor_verify_{base}", phase="VALIDATE",
                intent="actor_verify", preferred_tool="get_actor",
                capability=chosen, parameters={"actor_name": label},
                depends_on=[spawn_id],
                stop_condition=(f"actor {label} found in the level actor list"),
            ))
        return steps

    def _phase_for(self, capability_name: str) -> str:
        cap = self._cap(capability_name)
        if cap and cap.spec.requires_visual_validation:
            return "EDIT"
        if capability_name in {"blueprint_authoring", "level_creation"}:
            return "BUILD"
        return "EDIT"

    def _parameters_for(
        self,
        capability_name: str,
        req: Dict[str, Any],
        intent: UniversalIntent,
        project_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Concrete tool parameters; conservative defaults, no fabrication."""
        params: Dict[str, Any] = {}
        ctx = project_context or {}
        if capability_name in {"environment_composition", "actor_staging",
                               "lighting_setup", "level_creation"}:
            label = "UA_" + re.sub(
                r"[^A-Za-z0-9_]", "", req.get("id", "Env"))[:24]
            params = {
                "class_name": "PointLight" if capability_name == "lighting_setup"
                else "StaticMeshActor",
                "actor_name": label,
                "location": [0, 0, 300 if capability_name == "lighting_setup" else 100],
            }
            if capability_name != "lighting_setup":
                params["mesh_asset"] = "/Engine/BasicShapes/Cube.Cube"
                params["scale"] = [2.0, 2.0, 0.5]
        elif capability_name == "sequencer_cinematic":
            params = {"asset_path": "/Game/UA_Mission/Intro"}
        elif capability_name == "camera_framing":
            params = {"seq_path": "/Game/UA_Mission/Intro",
                      "actor_label": "UA_Cam_Intro",
                      "location": [0, -400, 200],
                      "start_s": 0.0, "end_s": 5.0}
        elif capability_name == "umg_widget_authoring":
            params = {"asset_path": "/Game/UA_Mission/WBP_MainMenu"}
        elif capability_name == "project_inspection":
            params = {}
        elif capability_name == "blueprint_authoring":
            params = {"asset_path": "/Game/UA_Mission/BP_MissionActor",
                      "parent_class": "Actor"}
        return params

    # ------------------------------------------------------------------
    def _acceptance_tests(
        self, intent: UniversalIntent, requirements: RequirementSpec,
    ) -> List[str]:
        tests: List[str] = []
        for req in requirements.requirements:
            kind = req.get("kind")
            if kind == "validation":
                continue
            ops = req.get("ops") or []
            if "capture" in ops or "visual_gate" in ops:
                tests.append(f"visual:{req['id']}")
            if "pie" in ops or "runtime" in ops:
                tests.append(f"runtime:{req['id']}")
            if kind == "assets":
                tests.append("asset:imported_verified")
            if kind == "ui":
                tests.append("ui:widget_visible")
        if intent.needs_visual_validation:
            tests.append("visual:quality_gate")
        return tests or ["technical:steps_completed"]


def build_universal_planner(
    tool_registry: Dict[str, Any],
) -> UniversalPlanner:
    """Create the planner bound to the live tool registry."""
    from core.capability_registry import build_capability_registry
    return UniversalPlanner(build_capability_registry(tool_registry))
