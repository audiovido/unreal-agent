"""Durable parent-goal and acceptance-contract state for long executions."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_GOAL_FILE = ROOT / "memory" / "task_goal.json"


def _text(value):
    return str(value or "").strip()


def _has(text, *terms):
    lowered = text.lower()
    return any(term in lowered for term in terms)


_ENVIRONMENT_REQUEST_TERMS = (
    "environment", "background", "architecture", "surrounding scene",
    "contextual setting", "room", "interior", "studio", "garage",
    "backdrop", "set dressing",
)


def environment_required_for_request(request):
    """Return whether the user explicitly made environment/context part of acceptance."""
    text = _text(request).lower()
    if any(marker in text for marker in (
        "without environment", "without a background", "no environment",
        "no background", "do not add an environment", "don't add an environment",
    )):
        return False
    if any(term in text for term in _ENVIRONMENT_REQUEST_TERMS):
        return True
    # Do not equate a generic "scene" mention with an environment
    # requirement: a vehicle may be showcased in the existing level without
    # asking the agent to create surrounding context. Require the explicit
    # environment/context vocabulary above (or an explicit "surrounding
    # scene" phrase) so the contract stays task-aware rather than vehicle-aware.
    return "surrounding scene" in text


def _read_only_inspection(text):
    """True for explicit read-only inspection/query requests (no mutation).

    Such goals are satisfied by the inspection evidence itself, so they get a
    satisfiable inspection:result criterion instead of the synthetic
    task:original_goal_complete catch-all that intentionally never completes
    on health checks alone. Vague no-criteria requests and any request with
    mutation intent keep the catch-all, so write-task completion gates are
    never weakened.
    """
    lowered = _text(text).lower()
    # Hard read-only markers (mirrors core/orchestrator's guard allow-list).
    if any(
        marker in lowered
        for marker in (
            "read-only",
            "read only",
            "readonly",
            "no modification",
            "no modifications",
            "do not modify",
            "don't modify",
            "do not change",
            "do not edit",
            "do not alter",
            "inspection only",
            "visual inspection only",
        )
    ):
        return True
    query = any(
        term in lowered
        for term in (
            "inspect",
            "inspection",
            "tell me",
            "what is",
            "what's",
            "whats",
            "list the",
            "list actors",
            "report",
            "describe",
            "summarize",
            "summarise",
            "status of",
            "what is open",
            "what's open",
            "which actors",
            "is pie",
            "pie status",
            "how many",
            "show me",
            "check the current",
            "check if",
            "is the bridge",
            "is the level",
        )
    )
    mutation = any(
        term in lowered
        for term in (
            "create",
            "spawn",
            "build",
            "make ",
            "make a",
            "make an",
            "add ",
            "add a",
            "add an",
            "set ",
            "delete",
            "remove",
            "save",
            "compile",
            "place",
            "edit",
            "modify",
            "fix",
            "write",
            "generate",
            "import",
            "open project",
            "open the project",
            "load project",
            "switch project",
            "change",
            "update",
            "configure",
            "install",
            "prepare",
            "rename",
            "replace",
            "convert",
            "cleanup",
            "polish",
            "optimize",
        )
    )
    return query and not mutation


# Tools whose successful, non-empty result constitutes read-only inspection
# evidence. Mirrors the guard's read-only allow-list in core/orchestrator;
# PIE start/stop toggles are excluded because they produce no inspection data.
INSPECTION_EVIDENCE_TOOLS = {
    "discover_projects",
    "inspect_project",
    "get_current_level",
    "get_selected_actors",
    "get_actor",
    "get_asset_info",
    "inspect_blueprint",
    "graph_list_nodes",
    "is_level_dirty",
    "list_assets",
    "list_level_actors",
    "read_text_file",
    "unreal_ping",
    "unreal_status",
    "capture_unreal_viewport",
    "capture_pie_viewport",
    "get_pie_status",
    "visual_review_unreal",
}


def _blender_request(text):
    """True when the request routes through the Blender Agent (kept in sync
    with app.api._needs_blender so acceptance criteria match the plan)."""
    lowered = text.lower()
    strong = (
        "blender", "3d asset", "3d model", "3d assets", "3d models",
        "custom 3d", "fbx", "glb", "gltf", "obj file",
    )
    if any(term in lowered for term in strong):
        return True
    if "mesh" in lowered and any(
        term in lowered for term in ("cleanup", "convert", "prepare", "fix", "uv", "decimat", "lod", "scale", "optimize")
    ):
        return True
    if "character" in lowered and any(
        term in lowered for term in ("prepare", "prep", "better", "retarget", "improve", "source", "cleanup")
    ):
        return True
    return False


def build_acceptance_contract(request, project_context=None):
    """Create a deterministic contract; preserve the complete original request."""
    text = _text(request)
    criteria = []
    deliverables = []
    environment_required = environment_required_for_request(text)

    def add(label, deliverable=None):
        if label not in criteria:
            criteria.append(label)
        if deliverable and deliverable not in deliverables:
            deliverables.append(deliverable)

    # Explicit synthetic/actor tasks.
    actor = None
    match = re.search(r"(?:cube|actor|marker)\s+(?:named|called)\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    if match:
        actor = match.group(1)
        add(f"actor:{actor}:exists", actor)
    if _has(text, "light"):
        add("light:exists", "light")
    if _has(text, "save"):
        add("level:saved", "saved level")
    if _has(text, "verify", "read-back") and actor:
        add(f"actor:{actor}:verified", f"verified {actor}")
    if re.search(r"\b(?:screenshot|capture|proof)\b", text, re.I):
        add("viewport:captured", "viewport proof")

    # Long AvaLive-style build criteria. These remain mandatory when requested,
    # while optional presentation refinements do not block completion.
    long_terms = {
        "avatar": "avatar",
        "environment": "environment",
        "lighting": "lighting",
        "camera": "camera",
        "chat ui": "chat UI",
        "text input": "text input",
        "send": "Send control",
        "enter-to-send": "Enter-to-send",
        "ollama": "local Ollama response",
        "thinking": "Thinking state",
        "online": "Online state",
        "animation": "avatar animation/reaction",
        "runtime": "runtime validation",
        "reopen": "reopen verification",
    }
    for term, label in long_terms.items():
        if term in text.lower():
            add(f"deliverable:{term.replace(' ', '_')}", label)
    if environment_required:
        add("deliverable:environment", "verified environment/context")
    # Blender Agent deliverables. These criteria are only emitted when the
    # request actually routes through the Blender Agent, so plain Unreal tasks
    # are never burdened with unsatisfiable 3D-pipeline criteria.
    if _blender_request(text):
        add("deliverable:blender_asset", "Blender asset")
        if _has(text, "export"):
            add("deliverable:blender_export", "Blender export")
        if _has(text, "import into unreal", "unreal import", "import it into"):
            add("deliverable:unreal_import", "Unreal import")
        if _has(text, "spawn", "place it", "place the asset"):
            add("deliverable:asset_spawned", "spawned asset")
    if _has(text, "character") and any(
        t in text for t in ("prepare", "prep", "better", "retarget", "improve", "source", "cleanup")
    ):
        add("deliverable:character", "prepared character")

    # Concrete criteria are sufficient; an aggregate "build complete" flag
    # would be impossible to independently verify and could deadlock completion.

    # A task with no parsed mutation still has a mandatory parent goal. This is
    # intentionally not satisfied by health checks. Explicit read-only
    # inspection/query requests are the exception: their goal IS the
    # inspection, so they complete from real inspection evidence instead of
    # inheriting the unsatisfiable catch-all.
    if not criteria:
        if _read_only_inspection(text):
            add("inspection:result", "inspection result")
        else:
            add("task:original_goal_complete", text[:240])

    optional = []
    if _has(text, "optional", "nice to have"):
        optional.append("explicit optional requirements")

    milestones = []
    if len(criteria) >= 3:
        milestone_labels = [
            ("project_scene", ("project", "scene", "actor", "light")),
            ("avatar", ("avatar",)),
            ("presentation", ("environment", "lighting", "camera")),
            ("chat_ui", ("chat", "text_input", "send")),
            ("ollama", ("ollama", "thinking", "online")),
            ("animation", ("animation",)),
            ("validation", ("runtime", "reopen", "saved")),
            ("evidence", ("screenshot", "viewport")),
        ]
        for name, terms in milestone_labels:
            owned = [c for c in criteria if any(term in c.lower() for term in terms)]
            if owned:
                milestones.append({"id": name, "criteria": owned, "status": "pending"})

    return {
        "id": str(uuid.uuid4()),
        "original_user_request": text,
        "primary_goal": text,
        "required_deliverables": deliverables,
        "acceptance_criteria": criteria,
        "environment_required": environment_required,
        "environment_criterion": "deliverable:environment" if environment_required else None,
        "environment_requirement": {
            "required": environment_required,
            "criterion": "deliverable:environment" if environment_required else None,
            "status": "required/unevaluated" if environment_required else "advisory",
        },
        "completed_criteria": [],
        "pending_criteria": list(criteria),
        "optional_criteria": optional,
        "project_context": dict(project_context or {}),
        "continuation_state": {
            "status": "pending",
            "current_milestone": 0,
            "next_milestone": 1,
            "sub_execution_ids": [],
            "milestones": milestones,
        },
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def load_task_goal():
    if not TASK_GOAL_FILE.exists():
        return None
    try:
        value = json.loads(TASK_GOAL_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def save_task_goal(goal):
    TASK_GOAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    goal = dict(goal or {})
    goal["updated_at"] = time.time()
    tmp = TASK_GOAL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(goal, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(TASK_GOAL_FILE)
    return goal


def update_task_goal(goal, *, completed=None, milestone=None, project_context=None, status=None, sub_execution_id=None):
    goal = dict(goal or {})
    if completed:
        done = list(dict.fromkeys(list(goal.get("completed_criteria", [])) + list(completed)))
        goal["completed_criteria"] = done
        goal["pending_criteria"] = [x for x in goal.get("acceptance_criteria", []) if x not in done]
        cont = dict(goal.get("continuation_state") or {})
        milestones = []
        for milestone_item in cont.get("milestones", []):
            item = dict(milestone_item)
            owned = set(item.get("criteria") or [])
            if owned and owned.issubset(set(done)):
                item["status"] = "completed"
            elif owned & set(done):
                item["status"] = "active"
            milestones.append(item)
        cont["milestones"] = milestones
        next_pending = next((i for i, item in enumerate(milestones) if item.get("status") != "completed"), len(milestones))
        cont["current_milestone"] = max(0, next_pending - 1)
        cont["next_milestone"] = next_pending
        goal["continuation_state"] = cont
    if milestone is not None:
        cont = dict(goal.get("continuation_state") or {})
        cont["current_milestone"] = milestone
        cont["next_milestone"] = milestone + 1
        goal["continuation_state"] = cont
    if project_context:
        goal["project_context"] = dict(project_context)
    if status:
        cont = dict(goal.get("continuation_state") or {})
        cont["status"] = status
        goal["continuation_state"] = cont
    if sub_execution_id:
        cont = dict(goal.get("continuation_state") or {})
        ids = list(cont.get("sub_execution_ids") or [])
        if sub_execution_id not in ids:
            ids.append(sub_execution_id)
        cont["sub_execution_ids"] = ids
        goal["continuation_state"] = cont
    return save_task_goal(goal)


def reconcile_step(goal, step, result):
    """Map verified tool evidence to contract criteria."""
    if not isinstance(goal, dict) or not isinstance(step, dict):
        return goal
    tool = str(step.get("preferred_tool") or "")
    payload = result if isinstance(result, dict) else {}
    nested = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    # A step only reaches reconciliation after the executor already verified
    # transport success. Accept the outer envelope's ok flag OR the inner
    # bridge payload's ok flag so criteria clearing is consistent with the
    # loop's _tool_success semantics regardless of envelope shape. Requiring
    # the ok to be nested inside "result" left fully successful tasks with
    # permanently pending criteria (e.g. viewport:captured) and a STALL/FAILED
    # terminal despite every step completing.
    step_ok = bool(payload.get("ok") is True or nested.get("ok") is True)
    completed = []
    if not step_ok:
        return goal
    actor_name = (step.get("parameters") or {}).get("actor_name") or nested.get("label") or nested.get("actor_name")
    spawn_class = str((step.get("parameters") or {}).get("class_name") or "")
    required = set(goal.get("acceptance_criteria") or [])

    def environment_actor_evidence(value):
        """Accept only structured environment read-back, never the proof PNG."""
        if isinstance(value, dict):
            label = str(value.get("label") or value.get("actor_name") or value.get("name") or "").lower()
            klass = str(value.get("class") or value.get("class_name") or "").lower()
            semantic = ("environment", "env_", "floor", "building", "architecture",
                        "room", "studio", "garage", "backdrop", "set")
            if any(term in label for term in semantic):
                return True
            if any(term in klass for term in ("landscape", "environment", "foliage")):
                return True
            return any(environment_actor_evidence(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return any(environment_actor_evidence(v) for v in value)
        return False

    def environment_readback_verified(value):
        payload_value = value.get("result") if isinstance(value, dict) else value
        return environment_actor_evidence(payload_value)
    if tool == "spawn_actor" and step_ok and actor_name:
        completed.append(f"actor:{actor_name}:exists")
        # Scene-content deliverables map to the concrete actor classes that
        # actually prove them; without this mapping long builds stall forever
        # on unsatisfiable deliverable:environment/lighting/camera criteria.
        if spawn_class == "PointLight":
            if "deliverable:lighting" in required:
                completed.append("deliverable:lighting")
        elif spawn_class == "CameraActor":
            if "deliverable:camera" in required:
                completed.append("deliverable:camera")
        elif spawn_class == "StaticMeshActor":
            # Only semantically labelled environment geometry proves the
            # environment deliverable; a vehicle body alone does not.
            if "deliverable:environment" in required and environment_actor_evidence({
                "label": actor_name, "class": spawn_class,
            }):
                completed.append("deliverable:environment")
    if tool == "get_actor" and step_ok and actor_name:
        completed.extend([f"actor:{actor_name}:exists", f"actor:{actor_name}:verified"])
    if tool == "save_level" and step_ok:
        completed.append("level:saved")
    # ------------------------------------------------------------ product
    # capabilities: acceptance criteria are satisfiable ONLY from real verified
    # tool evidence. A criterion is never cleared by planner intent alone.
    product = {
        "deliverable:avatar": [
            ("spawn_character", lambda p: p.get("verified") is True and p.get("mesh") is not None),
            ("verify_character_visible", lambda p: p.get("verified") is True and p.get("mesh") is not None and p.get("visible") is True),
        ],
        "deliverable:animation": [
            ("assign_animation", lambda p: p.get("verified") is True and p.get("animation") is not None),
            ("avatar_react", lambda p: p.get("verified") is True and p.get("moved") is True),
        ],
        "deliverable:chat_ui": [
            ("create_widget_blueprint", lambda p: p.get("verified") is True or p.get("is_widget") is True),
            ("add_widget_to_viewport", lambda p: p.get("verified") is True and p.get("in_viewport") is True),
            ("verify_widget_visible", lambda p: p.get("verified") is True and p.get("visible") is True and p.get("found") is True),
        ],
        "deliverable:text_input": [
            ("add_editable_text_box", lambda p: p.get("verified") is True),
        ],
        "deliverable:send": [
            ("bind_button_event", lambda p: p.get("verified") is True and p.get("bound") is True),
            ("chat_send_message", lambda p: p.get("verified") is True and p.get("input_verified") is True),
        ],
        "deliverable:enter-to-send": [
            ("bind_enter_submit", lambda p: p.get("verified") is True and p.get("bound") is True),
        ],
        "deliverable:ollama": [
            ("ollama_chat", lambda p: p.get("verified") is True and bool(str(p.get("response") or "").strip()) and p.get("local_only") is True),
        ],
        "deliverable:thinking": [
            ("set_ui_state", lambda p: p.get("verified") is True and p.get("state") == "thinking"),
            ("verify_ui_state", lambda p: p.get("verified") is True and p.get("state") == "thinking" and p.get("match") is True),
        ],
        "deliverable:online": [
            ("set_ui_state", lambda p: p.get("verified") is True and p.get("state") == "online"),
            ("verify_ui_state", lambda p: p.get("verified") is True and p.get("state") == "online" and p.get("match") is True),
        ],
        "deliverable:runtime": [
            ("runtime_status", lambda p: p.get("ok") is True and p.get("is_playing") is True),
            ("runtime_widget_verify", lambda p: p.get("verified") is True and p.get("is_playing") is True),
            ("runtime_actor_verify", lambda p: p.get("verified") is True and p.get("is_playing") is True and p.get("found") is True),
        ],
        "deliverable:reopen": [
            ("verify_reopen_state", lambda p: p.get("verified") is True),
        ],
    }
    for criterion, rules in product.items():
        if criterion not in required or criterion in completed:
            continue
        for tool_name, predicate in rules:
            if tool != tool_name:
                continue
            if predicate(nested):
                completed.append(criterion)
                break
    # ------------------------------------------------------------ blender
    # Blender Agent deliverables clear only from verified pipeline evidence:
    # a validated Blender export, a verified Unreal import, or a spawned
    # actor. blender_prepare_character with code REALISTIC_CHARACTER_SOURCE_
    # REQUIRED clears nothing — the Unreal mannequin fallback (spawn/install)
    # is what honestly satisfies deliverable:character without faking a human.
    blender = {
        "deliverable:blender_asset": [
            ("blender_create_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_convert_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_prepare_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_prepare_character", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
        ],
        "deliverable:blender_export": [
            ("blender_create_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_convert_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_prepare_asset", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
            ("blender_prepare_character", lambda p: p.get("verified") is True and bool(p.get("export_path"))),
        ],
        "deliverable:character": [
            ("blender_prepare_character", lambda p: p.get("verified") is True and bool(p.get("export_path")) and p.get("code") != "REALISTIC_CHARACTER_SOURCE_REQUIRED"),
            ("spawn_character", lambda p: p.get("verified") is True and p.get("mesh") is not None),
            ("install_character_assets", lambda p: p.get("verified") is True and p.get("mesh") is not None),
            ("verify_character_visible", lambda p: p.get("verified") is True and p.get("mesh") is not None and p.get("visible") is True),
        ],
        "deliverable:unreal_import": [
            ("import_blender_output", lambda p: p.get("verified") is True and bool(p.get("asset_path"))),
            ("import_asset", lambda p: p.get("verified") is True and bool(p.get("asset_path"))),
            ("import_asset_fbx", lambda p: p.get("verified") is True and bool(p.get("asset_path"))),
            ("import_asset_gltf", lambda p: p.get("verified") is True and bool(p.get("asset_path"))),
        ],
        "deliverable:asset_spawned": [
            ("spawn_blender_output", lambda p: p.get("verified") is True and bool(p.get("actor_name"))),
            ("spawn_imported_asset", lambda p: p.get("verified") is True and bool(p.get("actor_name"))),
            ("spawn_actor", lambda p: bool(p.get("label")) or bool(p.get("actor_name"))),
        ],
    }
    for criterion, rules in blender.items():
        if criterion not in required or criterion in completed:
            continue
        for tool_name, predicate in rules:
            if tool != tool_name:
                continue
            if predicate(nested):
                completed.append(criterion)
                break
    # A Blender-created static-mesh actor proves the environment deliverable.
    if (
        "deliverable:environment" in required
        and "deliverable:environment" not in completed
        and tool == "spawn_blender_output"
        and step_ok
    ):
        completed.append("deliverable:environment")
    if tool == "list_level_actors" and "deliverable:environment" in required:
        if environment_readback_verified(payload):
            completed.append("deliverable:environment")
        # The read-back itself is the evaluation event. A valid structured
        # actor-list response with no environment-semantic actor is negative
        # evidence, never an implicit pass from the screenshot.
        else:
            completed.append("environment:evaluated")
    if tool == "open_map" and step_ok:
        level = (step.get("parameters") or {}).get("level_path") or nested.get("level_path") or nested.get("world_path")
        if str(level or "").startswith("/Game/"):
            completed.append("deliverable:reopen")
    if tool == "capture_unreal_viewport" and step_ok:
        completed.append("viewport:captured")
    if tool in {"spawn_actor", "get_actor"} and str((step.get("parameters") or {}).get("class_name")) == "PointLight":
        if step_ok:
            completed.append("light:exists")
    # Read-only inspection/query goals complete from real inspection evidence:
    # a successful inspection tool with a non-empty result. This is the only
    # path that satisfies inspection:result, so vague no-criteria requests
    # (which keep the task:original_goal_complete catch-all) still cannot
    # complete from health checks alone.
    if "inspection:result" in required and "inspection:result" not in completed:
        if step_ok and tool in INSPECTION_EVIDENCE_TOOLS and (payload or nested):
            completed.append("inspection:result")

    # The synthetic catch-all criterion (auto added when a request parsed no
    # concrete criteria) only clears once every real criterion is complete AND
    # evidence has actually been captured. Planner intent alone never clears it.
    if "task:original_goal_complete" in required and "task:original_goal_complete" not in completed:
        others = [c for c in required if c != "task:original_goal_complete"]
        others_done = (not others) or set(others).issubset(set(completed))
        if others_done and ("viewport:captured" in completed or (tool == "capture_unreal_viewport" and step_ok)):
            completed.append("task:original_goal_complete")
    return update_task_goal(goal, completed=completed)


def contract_complete(goal):
    if not goal:
        return True
    required = set(goal.get("acceptance_criteria") or [])
    completed = set(goal.get("completed_criteria") or [])
    return bool(required) and required.issubset(completed)
