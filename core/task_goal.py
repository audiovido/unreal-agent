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


def build_acceptance_contract(request, project_context=None):
    """Create a deterministic contract; preserve the complete original request."""
    text = _text(request)
    criteria = []
    deliverables = []

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
    # Concrete criteria are sufficient; an aggregate "build complete" flag
    # would be impossible to independently verify and could deadlock completion.

    # A task with no parsed mutation still has a mandatory parent goal. This is
    # intentionally not satisfied by health checks.
    if not criteria:
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
            # Only visible static geometry proves the environment deliverable.
            if "deliverable:environment" in required:
                completed.append("deliverable:environment")
    if tool == "get_actor" and step_ok and actor_name:
        completed.extend([f"actor:{actor_name}:exists", f"actor:{actor_name}:verified"])
    if tool == "save_level" and step_ok:
        completed.append("level:saved")
    if tool == "open_map" and step_ok:
        level = (step.get("parameters") or {}).get("level_path") or nested.get("level_path") or nested.get("world_path")
        if str(level or "").startswith("/Game/"):
            completed.append("deliverable:reopen")
    if tool == "capture_unreal_viewport" and step_ok:
        completed.append("viewport:captured")
    if tool in {"spawn_actor", "get_actor"} and str((step.get("parameters") or {}).get("class_name")) == "PointLight":
        if step_ok:
            completed.append("light:exists")
    return update_task_goal(goal, completed=completed)


def contract_complete(goal):
    if not goal:
        return True
    required = set(goal.get("acceptance_criteria") or [])
    completed = set(goal.get("completed_criteria") or [])
    return bool(required) and required.issubset(completed)
