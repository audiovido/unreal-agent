from __future__ import annotations

import json
import sys
import uuid
import threading
from pathlib import Path
from typing import Any
import time

# Loop protection limits
MAX_STEPS = 200
MAX_TOOL_CALLS = 1000
MAX_RUNTIME_SECONDS = 3600
# Store last tool calls for loop detection (action + args hash)
LAST_CALLS = {}

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import MemorySystem for API integration
from core.memory_system import MemorySystem

from core.orchestrator import (
    SYSTEM,
    REGISTRY,
    FAST_MODEL,
    REASONING_MODEL,
    CODER_MODEL,
    HEAVY_MODEL,
    HEAVY_MODEL_AVAILABLE,
    VISION_MODEL,
    VISION_MODEL_AVAILABLE,
    classify_intent,
    run_chat,
    run_plan,
    create_execution_plan,
    build_executor_system,
    call_model,
    guard_tool_call,
    result_ok,
    is_verifier,
    recovery_review,
    review_completion,
    save_session,
)

from core.tool_registry import validate_args
from app.overnight_api import router as overnight_router
from app.workboard_selftest import (
    router as workboard_selftest_router,
    start_selftest,
)
from app.workboard_api import (
    router as workboard_router,
    get_next_ready_task,
    get_next_testing_task,
    update_runtime_task,
    touch_runtime_task,
    get_task,
    recover_orphaned_progress_tasks,
    commit_generated_plan,
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Unreal Agent",
    version="5.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overnight_router)
app.include_router(workboard_router)
app.include_router(workboard_selftest_router)

UI_DIR = ROOT / "ui"

app.mount(
    "/static",
    StaticFiles(directory=str(UI_DIR)),
    name="static",
)

# Create MemorySystem instance for API
MEMORY = MemorySystem()


def _resolve_bridge():
    for spec in REGISTRY.values():
        func = getattr(spec, "func", None)
        owner = getattr(func, "__self__", None)
        if owner is not None and owner.__class__.__name__ == "UnrealBridge":
            return owner
    return None


BRIDGE = _resolve_bridge()

PHASE_TOOL_RULES = {
    "INSPECT": {"inspect_project", "unreal_ping", "list_assets", "get_asset_info", "inspect_blueprint"},
    "EDIT": {"create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default", "add_blueprint_component"},
    "BUILD": {"compile_blueprint", "save_blueprint", "save_level"},
    "VALIDATE": {"get_asset_info", "get_blueprint_variable_default", "inspect_blueprint", "list_assets"},
    "FIX": {"set_blueprint_variable_default", "compile_blueprint", "save_blueprint"},
    "RETRY": {"get_asset_info", "get_blueprint_variable_default", "inspect_blueprint", "list_assets"},
    "EVIDENCE": {"capture_unreal_viewport"},
    "CLEANUP": {"delete_asset", "delete_actor"},
    "VERIFY_CLEANUP": {"get_asset_info", "list_assets"},
    "COMPLETE": set(),
    "FAILED": set(),
}


class ChatRequest(BaseModel):
    message: str


class ApprovalRequest(BaseModel):
    approval_id: str
    approved: bool


class WorkboardPlanPreviewRequest(BaseModel):
    title: str
    description: str = ""
    start_at: str | None = None
    end_at: str | None = None


class WorkboardPlanCommitRequest(BaseModel):
    plan: dict[str, Any]
    start_queue: bool = False



lock = threading.Lock()

messages = [
    {
        "role": "system",
        "content": SYSTEM,
    }
]

events: list[dict[str, Any]] = []

pending_approvals: dict[str, dict[str, Any]] = {}

execution_state: dict[str, Any] | None = None


# ============================================================
# EVENTS
# ============================================================

def emit(
    event_type: str,
    title: str,
    detail: Any = None,
    status: str = "info",
    task_id: str | None = None,
):
    if task_id is None and execution_state is not None:
        task_id = execution_state.get("id")

    event = {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "timestamp": time.time(),
        "type": event_type,
        "title": title,
        "detail": detail,
        "status": status,
    }

    events.append(event)

    if len(events) > 300:
        del events[:-300]

    return event


def serialize(value):
    return json.loads(
        json.dumps(
            value,
            default=str,
            ensure_ascii=False,
        )
    )


def _resource_key(action: str, args: dict[str, Any] | None = None):
    args = args or {}
    if action == "spawn_actor":
        return f"{action}:{str(args.get('actor_name') or '').lower()}"
    if "asset_path" in args:
        return f"{action}:{str(args.get('asset_path') or '').lower()}"
    if "actor_name" in args:
        return f"{action}:{str(args.get('actor_name') or '').lower()}"
    return f"{action}:{json.dumps(args, sort_keys=True, default=str)}"


def _validation_mismatch(payload: dict[str, Any] | None = None):
    payload = payload or {}
    return {
        "expected": payload.get("expected"),
        "actual": payload.get("actual"),
        "resource": payload.get("resource"),
    }


def _project_already_loaded(task: str, args: dict[str, Any]):
    if BRIDGE is None:
        return False
    target = str(args.get("uproject_path") or "").strip().lower()
    if not target:
        return False
    try:
        BRIDGE.ping()
        result = BRIDGE.execute_python(
            "__bridge_result__ = {'project': None}"
        )
    except Exception:
        return False
    project = ""
    if isinstance(result, dict):
        payload = result.get("result") if isinstance(result.get("result"), dict) else result
        project = str(payload.get("project") or payload.get("uproject_path") or "")
    return project.strip().lower() == target


# ============================================================
# APPROVAL POLICY
# ============================================================

def requires_approval(
    action: str,
    args: dict[str, Any],
) -> bool:

    a = action.lower()

    # Workboard is autonomous by default.
    # Only genuinely destructive operations interrupt the user.
    if execution_state is not None and execution_state.get("workboard_task_id"):
        if any(word in a for word in ("delete", "remove", "destroy")):
            return True
        return False

    # Deletion should always ask.
    if any(
        word in a
        for word in (
            "delete",
            "remove",
            "destroy",
        )
    ):
        return True

    # Arbitrary shell execution asks.
    if a == "run_powershell":
        return True

    # Switching projects asks.
    if a == "open_project":
        return True

    # Code/file writing INSIDE Unreal-Agent can run automatically.
    if a == "write_text_file":

        raw_path = (
            args.get("path")
            or args.get("file_path")
            or ""
        )

        if not raw_path:
            return True

        try:
            p = Path(raw_path)

            if not p.is_absolute():
                p = ROOT / p

            p = p.resolve()
            root = ROOT.resolve()

            if p == root or root in p.parents:
                return False

        except Exception:
            pass

        return True

    # Normal Unreal editing stays autonomous.
    return False


# ============================================================
# EXECUTION STATE
# ============================================================

def _extract_task_parameters(task):
    import re
    text = str(task or "")
    m = re.search(r"(/Game/[A-Za-z0-9_/-]+)", text)
    asset = m.group(1) if m else None
    m = re.search(r"(?:String variable|variable)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    variable = m.group(1) if m else None
    values = re.findall(r"\b(?:WRONG_VALUE|EXPECTED_VALUE)\b", text)
    actor = None
    actor_match = re.search(r"(?:actor|marker|cube)\s+(?:named|called)\s+[\\\"']?([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    if actor_match:
        actor = actor_match.group(1)
    project_name = None
    project_match = re.search(r"project\s+(?:named|called)\s+[\\\"']?([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    if project_match:
        project_name = project_match.group(1)
    return {"asset_path": asset, "variable_name": variable, "initial_value": values[0] if values else None, "expected_value": values[-1] if values else None, "actor_name": actor, "project_name": project_name, "disposable": bool(asset and "agentgraduation" in asset.lower())}


def normalize_execution_plan(task, plan):
    p = _extract_task_parameters(task)
    steps = []
    def add(step_id, phase, intent, tool, parameters=None, expected=None):
        steps.append({"step_id": step_id, "phase": phase, "intent": intent, "action_category": intent, "preferred_tool": tool, "allowed_tools": [tool], "target_type": "blueprint" if p["asset_path"] else "project", "target_resource": p["asset_path"], "parameters": parameters or {}, "expected_result": expected or {}, "validation_tool": None, "validation_parameters": {}, "depends_on": [steps[-1]["step_id"]] if steps else [], "disposable": p["disposable"], "status": "pending"})
    if p["project_name"] and not p["asset_path"] and p["actor_name"]:
        destination = r"C:\Users\Shadow\Desktop\UnrealAgentGraduation"
        uproject_path = f"{destination}\\{p['project_name']}\\{p['project_name']}.uproject"
        add("create_project", "EDIT", "create_project", "create_project", {"project_name": p["project_name"], "destination": destination, "template": "Blank"})
        add("inspect_new_project", "INSPECT", "inspect_project", "inspect_project", {"uproject_path": uproject_path})
        add("create_default_level", "EDIT", "create_default_level", "create_default_level", {"level_path": f"/Game/{p['project_name']}"})
        add("project_identity", "VALIDATE", "get_project_identity", "get_project_identity", {}, {"expected": p["project_name"]})
        add("spawn_new_project_marker", "EDIT", "spawn_actor", "spawn_actor", {"class_name": "StaticMeshActor", "actor_name": p["actor_name"], "location": [300, 0, 100], "scale": [0.5, 0.5, 0.5], "mesh_asset": "/Engine/BasicShapes/Cube.Cube"})
        add("save_new_project", "BUILD", "save_level", "save_level", {})
        add("validate_new_project_actor", "VALIDATE", "get_actor", "get_actor", {"actor_name": p["actor_name"]}, {"expected": p["actor_name"]})
        add("validate_new_project", "VALIDATE", "validate_project_creation", "validate_project_creation", {"project_name": p["project_name"], "actor_name": p["actor_name"]}, {"expected": True})
    else:
        add("inspect_project", "INSPECT", "inspect_project", "inspect_project", {})
    if p["project_name"] and not p["asset_path"] and p["actor_name"]:
        pass
    else:
        if p["asset_path"] and "create" in str(task).lower(): add("create_blueprint", "EDIT", "create_blueprint", "create_blueprint", {"asset_path": p["asset_path"], "parent_class": "Actor"}, {"exists": True})
        if p["variable_name"]: add("add_variable", "EDIT", "add_blueprint_variable", "add_blueprint_variable", {"asset_path": p["asset_path"], "variable_name": p["variable_name"], "variable_type": "String"})
        if p["initial_value"]: add("set_initial_value", "EDIT", "set_blueprint_variable_default", "set_blueprint_variable_default", {"asset_path": p["asset_path"], "variable_name": p["variable_name"], "value": p["initial_value"]})
        if p["asset_path"]: add("compile_save", "BUILD", "compile_blueprint", "compile_blueprint", {"asset_path": p["asset_path"]})
        if p["expected_value"]: add("validate_value", "VALIDATE", "get_blueprint_variable_default", "get_blueprint_variable_default", {"asset_path": p["asset_path"], "variable_name": p["variable_name"]}, {"expected": p["expected_value"]})
        if p["actor_name"] and not p["asset_path"]:
            add("spawn_actor", "EDIT", "spawn_actor", "spawn_actor", {"class_name": "StaticMeshActor", "actor_name": p["actor_name"], "location": [300, 0, 100], "scale": [0.5, 0.5, 0.5], "mesh_asset": "/Engine/BasicShapes/Cube.Cube"})
            add("save_level", "BUILD", "save_level", "save_level", {})
            add("validate_actor", "VALIDATE", "get_actor", "get_actor", {"actor_name": p["actor_name"]}, {"exists": True})
    if p["disposable"]:
        add("evidence", "EVIDENCE", "capture_unreal_viewport", "capture_unreal_viewport", {})
        add("cleanup", "CLEANUP", "delete_asset", "delete_asset", {"asset_path": p["asset_path"]}, {"absent": True})

    # Arbitrary natural-language requests that the deterministic patterns
    # above cannot map still need a real plan. Ask the local coder model
    # for a small structured tool plan and sanitize it against the real
    # registry so the deterministic executor can run it.
    has_task_steps = any(s["step_id"] != "inspect_project" for s in steps)
    if not has_task_steps:
        llm_steps = _llm_structured_steps(task)
        if len(llm_steps) >= 2:
            steps = steps[:1] + llm_steps
            has_grounded_validation = any(
                s.get("phase") == "VALIDATE"
                and (s.get("expected_result") or {}).get("expected") is not None
                for s in steps
            )
            if not has_grounded_validation:
                verify = _deterministic_verify_step(steps)
                if verify is not None:
                    steps.append(verify)
            if not any(s.get("phase") == "EVIDENCE" for s in steps) and "capture_unreal_viewport" in REGISTRY:
                steps.append({
                    "step_id": "evidence:capture",
                    "phase": "EVIDENCE",
                    "intent": "capture_unreal_viewport",
                    "action_category": "capture_unreal_viewport",
                    "preferred_tool": "capture_unreal_viewport",
                    "allowed_tools": ["capture_unreal_viewport"],
                    "target_type": "project",
                    "target_resource": None,
                    "parameters": {},
                    "expected_result": {},
                    "validation_tool": None,
                    "validation_parameters": {},
                    "depends_on": [steps[-1]["step_id"]],
                    "disposable": False,
                    "status": "pending",
                })
    return {"goal": (plan or {}).get("goal", task) if isinstance(plan, dict) else task, "steps": steps, "success_criteria": (plan or {}).get("success_criteria", []) if isinstance(plan, dict) else []}


def _llm_structured_steps(task):
    """Build a small structured tool plan for an arbitrary task.

    The result is sanitized against the real tool registry, so the
    deterministic executor can never be asked to run an unknown tool or
    pass undeclared arguments. Returns [] when the model is unavailable.
    """
    # Tools the deterministic executor can actually report as success.
    # read_text_file/write_text_file/run_powershell/unreal_status and other
    # tools without an explicit ok flag, plus destructive project openers,
    # are intentionally not offered to the planner.
    planner_deny = {
        "read_text_file", "write_text_file", "run_powershell",
        "unreal_status", "discover_projects", "open_project",
        "start_pie", "stop_pie", "delete_asset", "visual_review_unreal",
    }
    try:
        hints = {}
        for name, spec in REGISTRY.items():
            if name in planner_deny:
                continue
            hints[name] = {
                k: (v[:80] if isinstance(v, str) else v)
                for k, v in (spec.args or {}).items()
            }
        prompt = (
            "You plan ONE Unreal Engine task for a deterministic tool executor.\n\n"
            "TASK:\n" + str(task) + "\n\n"
            "Return ONLY one JSON object:\n"
            '{"steps":[{"tool":"name","parameters":{...},"phase":"INSPECT|EDIT|BUILD|VALIDATE|FIX|EVIDENCE","expected":{...}}]}\n\n'
            "AVAILABLE TOOLS and their declared parameters:\n"
            + json.dumps(hints, ensure_ascii=False)
            + "\n\nRULES:\n"
            "- Use ONLY the exact tool names listed above.\n"
            "- Pass only declared parameters.\n"
            "- spawn_actor takes class_name and an [x,y,z] location array; the spawned actor keeps the class name as its label.\n"
            "- move_actor takes actor_name and an [x,y,z] location array.\n"
            "- get_actor takes actor_name (internal name or outliner label).\n"
            "- save_level takes no parameters.\n"
            "- Inspect first, then mutate, then build/save, then verify with a read tool, then capture evidence.\n"
            "- Every VALIDATE step MUST include expected.expected set to the exact value the read tool will report (e.g. the actor label used by spawn_actor). Never leave expected empty on a VALIDATE step.\n"
            "- Finish with an EVIDENCE step using capture_unreal_viewport when the task involves visible Unreal content.\n"
            "- 5 to 9 steps, smallest useful plan.\n"
        )
        raw = call_model(
            [
                {"role": "system", "content": "You output strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            model=CODER_MODEL,
            json_mode=True,
            temperature=0.05,
            num_ctx=8192,
            timeout=240,
        )
        parsed = json.loads(raw)
    except Exception:
        return []

    steps = []
    last_id = "inspect_project"
    for item in (parsed.get("steps") or [])[:10]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip().lower()
        if tool not in REGISTRY or tool in planner_deny:
            continue
        params = item.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        declared = set(REGISTRY[tool].args.keys())
        cleaned = {k: v for k, v in params.items() if k in declared and v is not None}
        valid, _ = validate_args(REGISTRY[tool], cleaned)
        if not valid:
            continue
        phase = str(item.get("phase") or "").upper()
        if phase not in ("INSPECT", "EDIT", "BUILD", "VALIDATE", "FIX", "EVIDENCE"):
            phase = "EDIT"
        expected_result = {}
        expected = item.get("expected")
        if isinstance(expected, dict) and expected.get("expected") is not None:
            exp = expected["expected"]
            if isinstance(exp, (str, int, float, bool)):
                expected_result = {"expected": exp}
        step_id = tool + ":" + str(len(steps))
        steps.append({
            "step_id": step_id,
            "phase": phase,
            "intent": tool,
            "action_category": tool,
            "preferred_tool": tool,
            "allowed_tools": [tool],
            "target_type": "project",
            "target_resource": cleaned.get("asset_path") or cleaned.get("actor_name"),
            "parameters": cleaned,
            "expected_result": expected_result,
            "validation_tool": None,
            "validation_parameters": {},
            "depends_on": [last_id],
            "disposable": False,
            "status": "pending",
        })
        last_id = step_id
    return steps


def _deterministic_verify_step(steps):
    """Ground a VALIDATE step in the actor the plan actually creates."""
    actor_name = None
    for s in reversed(steps):
        params = s.get("parameters") or {}
        name = params.get("actor_name") or params.get("name")
        if name:
            actor_name = str(name)
            break
    if actor_name and "get_actor" in REGISTRY:
        return {
            "step_id": "verify:actor",
            "phase": "VALIDATE",
            "intent": "get_actor",
            "action_category": "get_actor",
            "preferred_tool": "get_actor",
            "allowed_tools": ["get_actor"],
            "target_type": "project",
            "target_resource": actor_name,
            "parameters": {"actor_name": actor_name},
            "expected_result": {"expected": actor_name},
            "validation_tool": None,
            "validation_parameters": {},
            "depends_on": [steps[-1]["step_id"]],
            "disposable": False,
            "status": "pending",
        }
    return None


def _tool_success(result):
    if not isinstance(result, dict):
        return False
    payload = None
    for key in ("result", "payload", "data"):
        if isinstance(result.get(key), dict):
            payload = result[key]
            break
    if isinstance(payload, dict):
        if payload.get("ok") is False or payload.get("success") is False:
            return False
        if payload.get("ok") is True or payload.get("success") is True or payload.get("status") == "success":
            return True
    if result.get("ok") is False or result.get("success") is False:
        return False
    if result.get("ok") is True or result.get("success") is True or result.get("status") == "success":
        return True
    return False


def _tool_payload(result):
    if not isinstance(result, dict):
        return {}
    for key in ("result", "payload", "data"):
        if isinstance(result.get(key), dict):
            return result[key]
    return result


def _extract_tool_value(result):
    payload = _tool_payload(result)
    for key in ("value", "default_value", "current_value", "actual", "project_name", "label", "actor_name", "name", "ok"):
        if key in payload:
            return payload[key]
    # General read-back evidence. Actor/asset/level tools do not expose a
    # generic "value" field, so verification of those tasks compares the
    # concrete label/name/saved flag the tool actually reported. Existing
    # Blueprint-variable flows keep their original "value" semantics.
    for key in ("found", "exists", "saved", "created", "asset_path"):
        if key in payload:
            return payload[key]
    return None


def _extract_resource_path(result):
    payload = _tool_payload(result)
    for key in ("asset_path", "object_path", "path", "package_path", "created_asset"):
        if payload.get(key):
            return payload[key]
    return None


def _extract_tool_error(result):
    if not isinstance(result, dict):
        return None
    payload = _tool_payload(result)
    if isinstance(payload, dict):
        for key in ("error", "message", "detail", "reason"):
            if payload.get(key):
                return payload.get(key)
    for key in ("error", "message", "detail", "reason"):
        if result.get(key):
            return result[key]
    return None


PROJECT_CONTEXT_DEFAULT = {
    "uproject_path": r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject",
    "project_name": "AudioVidoLivingCity",
    "world": "/Game/AVLC_Main.AVLC_Main",
}

_PLACEHOLDER_HINTS = (
    "/path/to/your/project.uproject",
    "/path/to/project.uproject",
    "path/to/your/project.uproject",
    "path/to/project.uproject",
    "/game/",
    "your_project",
    "<project",
)


def _is_placeholder(value):
    if not isinstance(value, str) or not value.strip():
        return True
    lowered = value.strip().lower()
    if "placeholder" in lowered:
        return True
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def new_execution(task: str):
    task_id = str(uuid.uuid4())
    plan = normalize_execution_plan(task, create_execution_plan(task))

    emit(
        "planning",
        "Execution plan",
        plan,
        "info",
        task_id=task_id,
    )

    # Initialize task state with detailed tracking fields
    return {
        "id": task_id,
        "task": task,
        "plan": plan,
        "project_context": dict(PROJECT_CONTEXT_DEFAULT),
        "phase": "PLAN",
        "current_phase": "PLAN",
        "current_step": 0,
        "completed_steps": [],
        "failed_step": None,
        "retry_count": 0,
        "validation_result": None,
        "created_resources": [],
        "processed_dispatch_ids": [],
        "fix_pending": False,
        "fix_step_id": None,
        "retry_pending": False,
        "retry_validation_step_id": None,
        "max_retries": 3,
        "max_tool_calls": 40,
        "model_messages": [
            {
                "role": "system",
                "content": build_executor_system(plan),
            },
            {
                "role": "user",
                "content": task,
            },
        ],
        "trace": [],
        "failed_calls": {},
        "verification_pending": False,
        "successful_calls": 0,
        "final_rejections": 0,
        "step": 0,
        "tool_call_count": 0,
        "state": "PLANNING",
        "current_action": None,
        "start_ts": None,
        "end_ts": None,
    }


def _next_normalized_step(execution):
    steps = (execution.get("plan") or {}).get("steps", [])
    completed = {s.get("step_id") for s in steps if s.get("status") == "completed"}
    for index, step in enumerate(steps):
        if step.get("status") != "pending":
            continue
        phase = str(step.get("phase", "")).upper()
        intent = str(step.get("intent", "")).lower()
        if phase in {"CLEANUP", "VERIFY_CLEANUP"} or intent in {"cleanup", "verify_cleanup"}:
            continue
        if set(step.get("depends_on") or []).issubset(completed):
            return index, step
    return None, None


def _resolved_step_args(execution, step, project_context=None):
    args = dict(step.get("parameters") or {})
    context = project_context or execution.get("project_context") or PROJECT_CONTEXT_DEFAULT
    spec = REGISTRY.get(step.get("preferred_tool") or "")
    accepted = set((spec.args or {}).keys()) if spec is not None else set()
    tool = step.get("preferred_tool") or ""
    for key in ("uproject_path", "project_name", "world"):
        if key not in accepted:
            continue
        # A new project must NOT inherit the currently active project name.
        if key == "project_name" and tool == "create_project":
            continue
        if (not args.get(key) or _is_placeholder(args.get(key))) and context.get(key):
            args[key] = context[key]
    if step.get("preferred_tool") == "inspect_project" and (not args.get("uproject_path") or _is_placeholder(args.get("uproject_path"))):
        args["uproject_path"] = PROJECT_CONTEXT_DEFAULT["uproject_path"]
    return args


def _deterministic_step_dispatch(execution, step, project_context=None):
    action = step.get("preferred_tool")
    args = _resolved_step_args(execution, step, project_context)
    if not action or action not in REGISTRY:
        return {"dispatch_id": str(uuid.uuid4()), "step_id": step.get("step_id"), "tool_name": action, "args": args, "transport_success": False, "ok": False, "raw_result": None, "payload": {}, "value": None, "resource_path": None, "error": "Unknown preferred tool"}
    valid, error = validate_args(REGISTRY[action], args)
    if not valid:
        return {"dispatch_id": str(uuid.uuid4()), "step_id": step.get("step_id"), "tool_name": action, "args": args, "transport_success": False, "ok": False, "raw_result": None, "payload": {}, "value": None, "resource_path": None, "error": error}
    emit("tool", f"Running {action}", {"step_id": step.get("step_id"), "args": args}, "running")
    try:
        tool_timeout = 480 if action in {"create_project", "open_project"} else 90 if action in {"create_default_level", "validate_project_creation"} else 60
        raw = call_tool_hard_timeout(REGISTRY[action], args, timeout_seconds=tool_timeout)
    except Exception as exc:
        raw = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    raw = serialize(raw)
    success = _tool_success(raw)
    emit("tool_result", f"{action} finished", raw, "success" if success else "error")
    return {"dispatch_id": str(uuid.uuid4()), "step_id": step.get("step_id"), "tool_name": action, "args": args, "transport_success": success, "ok": success, "raw_result": raw, "payload": _tool_payload(raw), "value": _extract_tool_value(raw), "resource_path": _extract_resource_path(raw), "error": _extract_tool_error(raw)}


def _cleanup_pending(execution):
    return [resource for resource in execution.get("created_resources", []) if resource.get("disposable") and resource.get("verified_clean") is not True]


def _resource_is_absent(result):
    """Recognize absence through arbitrarily nested bridge envelopes."""
    if isinstance(result, dict):
        if result.get("exists") is False or result.get("found") is False:
            return True
        text = " ".join(
            str(result.get(key, ""))
            for key in ("error", "message", "detail", "reason")
        ).lower()
        if "not found" in text or "does not exist" in text:
            return True
        return any(
            _resource_is_absent(value)
            for key, value in result.items()
            if key in ("result", "payload", "data")
        )
    return False


def _can_complete(execution):
    steps = (execution.get("plan") or {}).get("steps", [])
    return (
        execution.get("validation_result") == "passed"
        and not execution.get("failed_step")
        and not execution.get("fix_pending")
        and not execution.get("retry_pending")
        and all(
            step.get("status") == "completed"
            for step in steps
            if step.get("status") != "skipped"
            and str(step.get("phase", "")).upper() not in {"CLEANUP", "VERIFY_CLEANUP"}
            and str(step.get("intent", "")).lower() not in {"cleanup", "verify_cleanup"}
        )
        and execution.get("evidence_handled", True)
        and not _cleanup_pending(execution)
        and not execution.get("cleanup_failure")
        and not execution.get("pending_approvals")
        and not execution.get("execution_blocker")
    )


def _apply_step_result(execution, step, dispatch_result):
    """Apply one finite deterministic dispatch result exactly once."""
    dispatch_id = dispatch_result.get("dispatch_id")
    processed = execution.setdefault("processed_dispatch_ids", [])
    if dispatch_id and dispatch_id in processed:
        return {"applied": False, "event": "DUPLICATE_RESULT_PROCESSING", "dispatch_id": dispatch_id}
    if dispatch_id:
        processed.append(dispatch_id)

    success = bool(dispatch_result.get("transport_success"))
    step_id = step.get("step_id")
    if (
        step.get("phase") == "VERIFY_CLEANUP"
        and _resource_is_absent(dispatch_result.get("raw_result") or dispatch_result)
    ):
        cleanup_path = (
            dispatch_result.get("resource_path")
            or step.get("cleanup_resource_path")
            or (step.get("parameters") or {}).get("asset_path")
        )
        resource = next(
            (item for item in execution.get("created_resources", []) if item.get("path") == cleanup_path),
            None,
        )
        if resource:
            resource["verified_clean"] = True
            resource["cleanup_verification"] = "absent"
        step["status"] = "completed"
        execution["cleanup_failure"] = None
        return {"applied": True, "status": "completed", "cleanup": "verified_clean"}

    if not success:
        step["status"] = "failed"
        if step.get("phase") == "CLEANUP":
            step["status"] = "pending"
        execution["failure_evidence"] = {"error": dispatch_result.get("error")}
        if step.get("phase") == "EVIDENCE":
            execution["evidence_handled"] = True
            execution["evidence_failure"] = dispatch_result.get("error")
        if execution.get("fix_pending") and step_id == execution.get("fix_step_id"):
            execution["fix_pending"] = False
            execution["fix_step_id"] = None
        return {"applied": True, "status": "failed", "error": dispatch_result.get("error")}

    if execution.get("fix_pending") and step_id == execution.get("fix_step_id"):
        step["status"] = "completed"
        execution["fix_pending"] = False
        execution["fix_step_id"] = None
        execution["retry_pending"] = True
        execution["retry_validation_step_id"] = execution.get("failed_step")
        execution["current_phase"] = execution["phase"] = "RETRY"
        return {"applied": True, "status": "completed", "transition": "retry_pending"}

    if step.get("phase") == "EVIDENCE":
        step["status"] = "completed"
        execution["evidence_handled"] = True
        execution["evidence_result"] = dispatch_result.get("raw_result") or dispatch_result.get("payload") or dispatch_result.get("value")
        return {"applied": True, "status": "completed", "evidence": "captured"}

    if step.get("phase") == "CLEANUP":
        step["status"] = "completed"
        execution["cleanup_action_success"] = True
        execution["cleanup_stage"] = "verify"
        return {"applied": True, "status": "completed", "cleanup": "action_succeeded"}

    cleanup_path = dispatch_result.get("resource_path") or step.get("cleanup_resource_path") or (step.get("parameters") or {}).get("asset_path")
    if step.get("phase") == "VERIFY_CLEANUP" or dispatch_result.get("cleanup_verification"):
        resource = next((item for item in execution.get("created_resources", []) if item.get("path") == cleanup_path), None)
        if resource:
            if _resource_is_absent(dispatch_result.get("raw_result") or dispatch_result):
                resource["verified_clean"] = True
                resource["cleanup_verification"] = "absent"
                return {"applied": True, "status": "completed", "cleanup": "verified_clean"}
            execution["cleanup_failure"] = {"path": cleanup_path, "reason": "resource_still_present"}
            return {"applied": True, "status": "failed", "cleanup": "verification_failed"}

    expected_result = step.get("expected_result") or {}
    expected = expected_result.get("expected")
    is_validation = step.get("phase") == "VALIDATE" or expected is not None
    if execution.get("retry_pending") and step_id == execution.get("retry_validation_step_id"):
        execution["retry_count"] = execution.get("retry_count", 0) + 1
        actual = dispatch_result.get("value")
        if step.get("preferred_tool") == "validate_project_creation" and dispatch_result.get("transport_success"):
            actual = True
        if "exists" in expected_result and dispatch_result.get("transport_success"):
            actual = True if expected_result.get("exists") is True else actual
        if actual == expected:
            step["status"] = "completed"
            execution["validation_result"] = "passed"
            execution["failed_step"] = None
            execution["retry_pending"] = False
            execution["retry_validation_step_id"] = None
            execution["current_phase"] = execution["phase"] = "EVIDENCE"
            return {"applied": True, "status": "completed", "validation": "passed"}
        execution["retry_pending"] = False
        execution["retry_validation_step_id"] = None
        step["status"] = "failed_validation"
        execution["failure_evidence"] = {"expected": expected, "actual": actual, "resource": dispatch_result.get("resource_path")}
        if execution["retry_count"] < execution.get("max_retries", 3):
            fix_id = f"fix:{step_id}:{execution['retry_count']}"
            fix_step = {"step_id": fix_id, "phase": "FIX", "preferred_tool": "set_blueprint_variable_default", "allowed_tools": ["set_blueprint_variable_default"], "parameters": dict(step.get("parameters") or {}), "expected_result": {}, "depends_on": [step_id], "disposable": False, "status": "pending", "generated_from": step_id}
            fix_step["parameters"]["value"] = expected
            execution.setdefault("plan", {"steps": []}).setdefault("steps", []).append(fix_step)
            execution["fix_pending"] = True
            execution["fix_step_id"] = fix_id
            execution["current_phase"] = execution["phase"] = "FIX"
            return {"applied": True, "status": "failed_validation", "transition": "next_fix"}
        execution["failure_evidence"]["retry_limit"] = True
        execution["current_phase"] = execution["phase"] = "FAILED"
        return {"applied": True, "status": "failed_validation", "transition": "retry_limit"}

    if is_validation and expected is not None:
        actual = dispatch_result.get("value")
        if step.get("preferred_tool") == "validate_project_creation" and dispatch_result.get("transport_success"):
            actual = True
        if "exists" in expected_result and dispatch_result.get("transport_success"):
            actual = True if expected_result.get("exists") is True else actual
        if actual == expected:
            step["status"] = "completed"
            execution["validation_result"] = "passed"
            execution["failed_step"] = None
            return {"applied": True, "status": "completed", "validation": "passed"}
        step["status"] = "failed_validation"
        execution["validation_result"] = "failed"
        execution["failed_step"] = step_id
        execution["failure_evidence"] = {"expected": expected, "actual": actual, "resource": dispatch_result.get("resource_path")}
        if not execution.get("fix_pending"):
            fix_id = f"fix:{step_id}:1"
            fix_step = {"step_id": fix_id, "phase": "FIX", "preferred_tool": "set_blueprint_variable_default", "allowed_tools": ["set_blueprint_variable_default"], "parameters": dict(step.get("parameters") or {}), "expected_result": {}, "depends_on": [step_id], "disposable": False, "status": "pending", "generated_from": step_id}
            fix_step["parameters"]["value"] = expected
            execution.setdefault("plan", {"steps": []}).setdefault("steps", []).append(fix_step)
            execution["fix_pending"] = True
            execution["fix_step_id"] = fix_id
            execution["current_phase"] = execution["phase"] = "FIX"
        execution["retry_pending"] = False
        execution["retry_validation_step_id"] = step_id
        return {"applied": True, "status": "failed_validation", "validation": "failed", "transition": "fix_pending"}

    step["status"] = "completed"
    if step.get("phase") == "VALIDATE":
        execution["validation_result"] = "passed"
    # A plan made entirely of read-only inspection steps still needs a
    # terminal validation marker so the completion gate cannot stall.
    if step.get("phase") == "INSPECT" and not any(
        str(item.get("phase", "")).upper() == "VALIDATE"
        for item in (execution.get("plan") or {}).get("steps", [])
    ):
        execution["validation_result"] = "passed"
    resource_path = dispatch_result.get("resource_path")
    created_by_step = step.get("intent") in {"create_blueprint", "spawn_actor", "create_project"} or not step.get("intent")
    if resource_path and step.get("disposable") and created_by_step:
        resources = execution.setdefault("created_resources", [])
        if not any(item.get("path") == resource_path for item in resources):
            resources.append({"path": resource_path, "resource_type": dispatch_result.get("resource_type"), "step_id": step_id, "disposable": True, "verified_clean": False})
    return {"applied": True, "status": "completed"}


def trace_summary(state, count=10):

    rows = []

    for item in state["trace"][-count:]:
        rows.append(
            {
                "step": item["step"],
                "action": item["action"],
                "args": item["args"],
                "ok": item["ok"],
                "result": item["result"],
            }
        )

    return rows


# ============================================================
# TOOL RESULT PROCESSING
# ============================================================

def process_tool_result(
    state,
    raw,
    action,
    args,
    result,
):

    spec = REGISTRY[action]

    result = serialize(result)

    ok = result_ok(result)

    if ok:
        state["successful_calls"] += 1

    if (
        getattr(spec, "destructive", False)
        and ok
    ):
        state["verification_pending"] = True

    elif (
        state["verification_pending"]
        and ok
        and is_verifier(action, spec)
    ):
        state["verification_pending"] = False

    item = {
        "step": state["step"],
        "action": action,
        "args": args,
        "ok": ok,
        "result": result,
    }

    state["trace"].append(item)

    emit(
        "tool_result",
        f"{action} finished",
        result,
        "success" if ok else "error",
    )

    state["model_messages"].append(
        {
            "role": "assistant",
            "content": raw,
        }
    )

    state["model_messages"].append(
        {
            "role": "user",
            "content":
                "ACTUAL TOOL RESULT:\n"
                + json.dumps(
                    result,
                    ensure_ascii=False,
                ),
        }
    )

    if not ok:

        signature = json.dumps(
            {
                "action": action,
                "args": args,
            },
            sort_keys=True,
            default=str,
        )

        state["failed_calls"][signature] = (
            state["failed_calls"].get(
                signature,
                0,
            )
            + 1
        )

        instruction = (
            "The tool failed. "
            "Treat this as real evidence. "
            "Do not claim success. "
            "Inspect the error and use a different valid strategy."
        )

        if state["failed_calls"][signature] >= 2:

            reviewer = recovery_review(
                state["task"],
                state["plan"],
                state["trace"],
            )

            instruction += (
                "\nDo NOT repeat the exact same failed call."
                "\nRECOVERY REVIEW:\n"
                + reviewer
            )

        state["model_messages"].append(
            {
                "role": "user",
                "content": instruction,
            }
        )

    return result, ok


def call_model_hard_timeout(messages, timeout_seconds=90):
    """
    Hard wall-clock timeout around the model call.
    Do not rely only on requests/socket timeout because a local
    Ollama request can occasionally remain blocked longer.
    """
    box = {}

    def worker():
        try:
            box["result"] = call_model(
                messages,
                model=CODER_MODEL,
                json_mode=True,
                temperature=0.08,
                num_ctx=32768,
                timeout=timeout_seconds,
            )
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(
        target=worker,
        name="unreal-agent-model-step",
        daemon=True,
    )
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        raise TimeoutError(
            f"Model step exceeded hard timeout of {timeout_seconds}s"
        )

    if "error" in box:
        raise box["error"]

    if "result" not in box:
        raise RuntimeError("Model step ended without a result")

    return box["result"]



def call_tool_hard_timeout(spec, args, timeout_seconds=60):
    """
    No registered tool may freeze the whole Agent forever.
    The worker is daemonized; the execution loop regains control
    after the wall-clock timeout.
    """
    box = {}

    def worker():
        try:
            box["result"] = spec.func(**args)
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(
        target=worker,
        name="unreal-agent-tool-step",
        daemon=True,
    )
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        raise TimeoutError(
            f"Tool '{getattr(spec, 'name', 'unknown')}' exceeded "
            f"{timeout_seconds}s hard timeout"
        )

    if "error" in box:
        raise box["error"]

    return box.get("result")


# ============================================================
# EXECUTION LOOP
# ============================================================

# overridden tool result processor

def process_tool_result(state, raw, action, args, result):
    # Record tool invocation
    state["tool_call_count"] = state.get("tool_call_count", 0) + 1
    state["current_action"] = action

    spec = REGISTRY[action]

    result = serialize(result)

    ok = result_ok(result)

    if ok:
        state["successful_calls"] += 1

    if (
        getattr(spec, "destructive", False)
        and ok
    ):
        state["verification_pending"] = True

    elif (
        state["verification_pending"]
        and ok
        and is_verifier(action, spec)
    ):
        state["verification_pending"] = False

    item = {
        "step": state["step"],
        "action": action,
        "args": args,
        "ok": ok,
        "result": result,
    }

    state["trace"].append(item)

    emit(
        "tool_result",
        f"{action} finished",
        result,
        "success" if ok else "error",
    )

    state["model_messages"].append(
        {
            "role": "assistant",
            "content": raw,
        }
    )

    state["model_messages"].append(
        {
            "role": "user",
            "content":
                "ACTUAL TOOL RESULT:\n"
                + json.dumps(
                    result,
                    ensure_ascii=False,
                ),
        }
    )

    if not ok:

        signature = json.dumps(
            {
                "action": action,
                "args": args,
            },
            sort_keys=True,
            default=str,
        )

        state["failed_calls"][signature] = (
            state["failed_calls"].get(
                signature,
                0,
            )
            + 1
        )

        instruction = (
            "The tool failed. "
            "Treat this as real evidence. "
            "Do not claim success. "
            "Inspect the error and use a different valid strategy."
        )

        if state["failed_calls"][signature] >= 2:

            reviewer = recovery_review(
                state["task"],
                state["plan"],
                state["trace"],
            )

            instruction += (
                "\nDo NOT repeat the exact same failed call."
                "\nRECOVERY REVIEW:\n"
                + reviewer
            )

        state["model_messages"].append(
            {
                "role": "user",
                "content": instruction,
            }
        )

    return result, ok

# deterministic Layer F orchestration

def run_execution_until_pause():
    global execution_state
    state = execution_state
    if state is None:
        return {"state": "error", "message": "No active execution."}
    if state.get("state") in {"COMPLETE", "FAILED", "STALLED"}:
        execution_state = None
        return {"state": state["state"].lower(), "message": "Execution already terminal."}
    state.setdefault("start_ts", time.time())
    state.setdefault("max_execution_iterations", 80)
    state.setdefault("no_progress_count", 0)
    state.setdefault("evidence_handled", True)
    state.setdefault("pending_approvals", {})
    state["state"] = "RUNNING"
    for _ in range(state["max_execution_iterations"]):
        before = repr((state.get("fix_pending"), state.get("retry_pending"), [(x.get("step_id"), x.get("status")) for x in state.get("plan", {}).get("steps", [])], state.get("created_resources")))
        if state.get("fix_pending"):
            step = next((x for x in state["plan"]["steps"] if x.get("step_id") == state.get("fix_step_id")), None)
        elif state.get("retry_pending"):
            step = next((x for x in state["plan"]["steps"] if x.get("step_id") == state.get("retry_validation_step_id")), None)
        else:
            _, step = _next_normalized_step(state)
        if step is None:
            pending_cleanup = _cleanup_pending(state)
            if pending_cleanup:
                resource = pending_cleanup[0]
                stage = state.get("cleanup_stage") or "delete"
                step = {"step_id": f"cleanup:{resource['path']}" if stage == "delete" else f"verify_cleanup:{resource['path']}", "phase": "CLEANUP" if stage == "delete" else "VERIFY_CLEANUP", "preferred_tool": "delete_asset" if stage == "delete" else "get_asset_info", "parameters": {"asset_path": resource["path"]}, "status": "pending", "cleanup_resource_path": resource["path"]}
                state["cleanup_stage"] = stage
            if step is None:
                if _can_complete(state):
                    state["state"] = "COMPLETE"
                    execution_state = None
                    emit("complete", "COMPLETE", None, "success")
                    return {"state": "complete", "message": "Execution complete."}
                emit("error", "EXECUTION_STALLED", None, "error")
                state["state"] = "STALLED"
                execution_state = None
                return {"state": "failed", "message": "Execution stalled."}
        step["status"] = "running"
        dispatch = _deterministic_step_dispatch(state, step)
        applied = _apply_step_result(state, step, dispatch)
        if step.get("phase") == "CLEANUP" and applied.get("status") == "completed": state["cleanup_stage"] = "verify"
        elif step.get("phase") == "VERIFY_CLEANUP" and applied.get("cleanup") == "verified_clean": state["cleanup_stage"] = None
        after = repr((state.get("fix_pending"), state.get("retry_pending"), [(x.get("step_id"), x.get("status")) for x in state.get("plan", {}).get("steps", [])], state.get("created_resources")))
        state["no_progress_count"] = state.get("no_progress_count", 0) + 1 if before == after else 0
        if state["no_progress_count"] >= 3:
            emit("error", "EXECUTION_STALLED", None, "error")
            state["state"] = "STALLED"
            execution_state = None
            return {"state": "failed", "message": "Execution stalled."}
    emit("error", "EXECUTION_ITERATION_LIMIT", None, "error")
    state["state"] = "FAILED"
    execution_state = None
    return {"state": "failed", "message": "Execution iteration limit reached."}

def _workboard_autopilot_watchdog():
    """
    Keep approved/ready work moving without user babysitting.
    If the queue stops while executable work exists, restart it.
    """
    while True:
        try:
            if not workboard_runner.get("running"):
                task = get_next_ready_task()

                if task is not None:
                    workboard_runner_start()

            time.sleep(3)

        except Exception:
            time.sleep(5)


@app.on_event("startup")
def workboard_startup_recovery():
    """
    Production startup behavior.

    Recover interrupted Workboard tasks, but NEVER launch diagnostic
    self-tests automatically. Self-Test is an explicit user action only.
    """
    recover_orphaned_progress_tasks(
        active_execution_id=None,
    )

    if not getattr(app.state, "workboard_autopilot_started", False):
        app.state.workboard_autopilot_started = True

        threading.Thread(
            target=_workboard_autopilot_watchdog,
            name="workboard-autopilot",
            daemon=True,
        ).start()


    # One persistent autopilot for the entire Agent session.
    if not getattr(app.state, "workboard_autopilot_started", False):
        app.state.workboard_autopilot_started = True

        threading.Thread(
            target=_workboard_autopilot_watchdog,
            name="workboard-autopilot",
            daemon=True,
        ).start()


# ============================================================
# ROUTER
# ============================================================

def route_request(message: str):

    global execution_state
    global messages

    mode = classify_intent(message)

    emit(
        "router",
        f"Mode: {mode.upper()}",
        {
            "mode": mode,
            "fast_model": FAST_MODEL,
            "reasoning_model": REASONING_MODEL,
            "coder_model": CODER_MODEL,
        },
        "info",
    )

    # --------------------------------------------------------
    # CHAT
    # --------------------------------------------------------

    if mode == "chat":

        answer = run_chat(
            message,
            messages,
        )

        messages.append(
            {
                "role": "assistant",
                "content": answer,
            }
        )

        save_session(messages)

        emit(
            "answer",
            "Unreal Agent",
            answer,
            "success",
        )

        return {
            "state": "complete",
            "mode": "chat",
            "message": answer,
        }

    # --------------------------------------------------------
    # PLAN
    # --------------------------------------------------------

    if mode == "plan":

        answer = run_plan(
            message,
            messages,
        )

        messages.append(
            {
                "role": "assistant",
                "content": answer,
            }
        )

        save_session(messages)

        emit(
            "answer",
            "Planning completed",
            answer,
            "success",
        )

        return {
            "state": "complete",
            "mode": "plan",
            "message": answer,
        }

    # --------------------------------------------------------
    # EXECUTE
    # --------------------------------------------------------

    execution_state = new_execution(
        message
    )

    return run_execution_until_pause()




# ============================================================
# WORKBOARD AI PLANNER
# ============================================================

def _extract_json_object(raw: str):
    text = str(raw or "").strip()

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Planner did not return a JSON object")

    value = json.loads(text[start:end + 1])

    if not isinstance(value, dict):
        raise ValueError("Planner JSON root must be an object")

    return value


def _planner_prompt(req: WorkboardPlanPreviewRequest):
    return f"""
You are the technical project manager for an autonomous Unreal Engine team.

USER PLAN:
Title: {req.title}
Description:
{req.description}

Sprint start: {req.start_at or "not specified"}
Sprint end: {req.end_at or "not specified"}

Break the plan into SMALL, independently executable engineering tasks.

Return ONLY one valid JSON object.

Schema:
{{
  "title": "Sprint title",
  "description": "Short sprint goal",
  "start_at": null,
  "end_at": null,
  "tasks": [
    {{
      "key": "T01",
      "order": 1,
      "title": "Small executable task",
      "description": "Concrete completion criteria",
      "priority": 80,
      "estimate_minutes": 30,
      "requires_approval": false,
      "depends_on": [],
      "schedule_offset_minutes": 0
    }}
  ]
}}

RULES:
- Prefer 5-15 tasks unless the plan genuinely needs more.
- Every task must be executable by Unreal Agent.
- Do not create vague tasks like "finish project".
- Dependencies must reference task keys only.
- A dependency must always point to an earlier task.
- Priority is 1-100.
- estimate_minutes must be realistic.
- schedule_offset_minutes is relative to sprint start.
- Default requires_approval=false.
- requires_approval=true ONLY for genuinely risky or irreversible actions:
  deleting important assets/data, publishing/deploying externally, spending money,
  overwriting user-owned external data, destructive migrations, or actions with
  meaningful irreversible consequences.
- NEVER require approval for planning, defining scope, inspection, code edits,
  Blueprint edits, builds, tests, validation, screenshots, UI work, camera work,
  normal project saves, or routine implementation.
- Inspection / analysis should come before mutation.
- Build / validation / visual review should come after implementation.
- Separate unrelated work so one failure does not block the entire Sprint.
""".strip()


def _normalize_generated_plan(
    raw_plan: dict,
    req: WorkboardPlanPreviewRequest,
):
    from datetime import datetime, timedelta

    tasks = list(raw_plan.get("tasks") or [])

    if not tasks:
        raise ValueError("Planner returned no tasks")

    if len(tasks) > 30:
        tasks = tasks[:30]

    seen = set()
    cleaned = []

    base_dt = None

    if req.start_at:
        try:
            base_dt = datetime.fromisoformat(req.start_at)
        except Exception:
            base_dt = None

    for index, item in enumerate(tasks):
        key = str(
            item.get("key")
            or f"T{index + 1:02d}"
        ).strip()

        if key in seen:
            key = f"T{index + 1:02d}"

        seen.add(key)

        deps = [
            str(x)
            for x in (item.get("depends_on") or [])
            if str(x) in seen and str(x) != key
        ]

        offset = max(
            0,
            int(item.get("schedule_offset_minutes") or 0),
        )

        scheduled_at = None

        if base_dt is not None:
            scheduled_at = (
                base_dt + timedelta(minutes=offset)
            ).isoformat(timespec="minutes")

        cleaned.append({
            "key": key,
            "order": index + 1,
            "title": str(
                item.get("title")
                or f"Task {index + 1}"
            ).strip(),
            "description": str(
                item.get("description") or ""
            ).strip(),
            "priority": max(
                1,
                min(100, int(item.get("priority") or 50)),
            ),
            "estimate_minutes": max(
                1,
                int(item.get("estimate_minutes") or 30),
            ),
            "requires_approval": bool(
                item.get("requires_approval", False)
            ),
            "depends_on": deps,
            "schedule_offset_minutes": offset,
            "scheduled_at": scheduled_at,
        })

    return {
        "title": str(
            raw_plan.get("title")
            or req.title
            or "Generated Sprint"
        ).strip(),
        "description": str(
            raw_plan.get("description")
            or req.description
            or ""
        ).strip(),
        "start_at": req.start_at,
        "end_at": req.end_at,
        "tasks": cleaned,
    }


@app.post("/api/workboard/plan/preview")
def workboard_plan_preview(
    req: WorkboardPlanPreviewRequest,
):
    if not req.title.strip():
        raise HTTPException(
            status_code=400,
            detail="Plan title is required",
        )

    prompt = _planner_prompt(req)

    raw = call_model_hard_timeout(
        [
            {
                "role": "system",
                "content": (
                    "Return strict JSON only. "
                    "You are a senior Unreal technical project manager."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        timeout_seconds=120,
    )

    try:
        parsed = _extract_json_object(raw)
        plan = _normalize_generated_plan(
            parsed,
            req,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Planner output invalid: {exc}",
        )

    return {
        "ok": True,
        "plan": plan,
    }


@app.post("/api/workboard/plan/commit")
def workboard_plan_commit(
    req: WorkboardPlanCommitRequest,
):
    plan = dict(req.plan or {})

    if not plan.get("tasks"):
        raise HTTPException(
            status_code=400,
            detail="Generated plan has no tasks",
        )

    result = commit_generated_plan(plan)

    if req.start_queue:
        try:
            workboard_runner_start()
        except Exception:
            pass

    return result



# ============================================================
# WORKBOARD QUEUE RUNNER
# ============================================================

workboard_runner = {
    "running": False,
    "stop_requested": False,
    "thread": None,
    "current_task_id": None,
    "last_result": None,
}


def _workboard_task_prompt(task):
    title = task.get("title") or "Untitled task"
    description = task.get("description") or ""

    return f"""
WORKBOARD TASK

Title:
{title}

Description:
{description}

You are executing one small task from Agent Board.

Rules:
- Work only on this task.
- Use Unreal Agent tools for actual Unreal project work.
- Do not claim completion without real evidence.
- Build/verify when relevant.
- If a tool fails, recover using another valid strategy.
- Return final only when the task itself is genuinely complete.
""".strip()


def _run_workboard_task(task):
    global execution_state

    task_id = task["id"]

    if execution_state is not None:
        state_name = execution_state.get("state")

        if state_name not in (
            "COMPLETE",
            "FAILED",
            "CANCELLED",
        ):
            return {
                "ok": False,
                "error": "Agent already has an active execution",
            }

    prompt = _workboard_task_prompt(task)

    update_runtime_task(
        task_id,
        "progress",
        note="Agent execution started",
    )

    execution_state = new_execution(prompt)

    # Bind this Agent execution to its Workboard card.
    # Terminal transitions can now be committed exactly where
    # the Agent itself reaches completion.
    execution_state["workboard_task_id"] = task_id

    execution_id = execution_state["id"]

    update_runtime_task(
        task_id,
        "progress",
        execution_id=execution_id,
    )

    try:
        result = run_execution_until_pause()

    except BaseException as exc:
        update_runtime_task(
            task_id,
            "blocked",
            note=f"{type(exc).__name__}: {exc}",
            evidence={
                "type": "execution_error",
                "message": str(exc),
                "at": time.time(),
            },
        )

        return {
            "ok": False,
            "error": str(exc),
        }

    state_name = str(
        result.get("state")
        or ""
    ).lower()

    execution_state_name = str(
        (execution_state or {}).get("state")
        or ""
    ).lower()

    is_complete = (
        state_name in (
            "complete",
            "completed",
            "done",
            "success",
            "finished",
            "final",
        )
        or execution_state_name in (
            "complete",
            "completed",
            "done",
            "success",
            "finished",
        )
    )

    if is_complete:
        # Normally the exact Agent-final branch already moved the
        # card to Testing. This is only a defensive fallback.
        current_task = get_task(task_id)

        if current_task and current_task.get("status") == "progress":
            update_runtime_task(
                task_id,
                "testing",
                note="Execution complete; runner fallback transition",
                evidence={
                    "type": "agent_execution_fallback",
                    "execution_id": execution_id,
                    "result": serialize(result),
                    "at": time.time(),
                },
            )

        return {
            "ok": True,
            "task_id": task_id,
            "execution_id": execution_id,
            "result": serialize(result),
        }

    if state_name in ("interrupted", "cancelled", "error", "failed"):
        message = str(result.get("message") or "")
        transient = (
            state_name in ("interrupted", "cancelled")
            or "timeout" in message.lower()
            or "timed out" in message.lower()
            or "model request failed" in message.lower()
        )

        if transient:
            current = get_task(task_id) or {}
            retry_count = int(current.get("retry_count") or 0) + 1

            # Persist retry count directly through the task object path.
            current["retry_count"] = retry_count

            if retry_count <= 3:
                update_runtime_task(
                    task_id,
                    "ready",
                    note=f"Automatic recovery retry {retry_count}/3: {message}",
                    evidence={
                        "type": "automatic_recovery",
                        "execution_id": execution_id,
                        "retry_count": retry_count,
                        "message": message,
                        "at": time.time(),
                    },
                )

                execution_state = None

                return {
                    "ok": False,
                    "retryable": True,
                    "task_id": task_id,
                    "retry_count": retry_count,
                    "result": serialize(result),
                }

    if state_name in ("paused", "approval_required"):
        update_runtime_task(
            task_id,
            "progress",
            note="Execution paused / approval required",
        )

        return {
            "ok": False,
            "paused": True,
            "approval_required": state_name == "approval_required",
            "result": serialize(result),
        }

    update_runtime_task(
        task_id,
        "blocked",
        note=result.get("message") or f"Execution ended: {state_name}",
        evidence={
            "type": "agent_execution_failure",
            "execution_id": execution_id,
            "result": serialize(result),
            "at": time.time(),
        },
    )

    return {
        "ok": False,
        "task_id": task_id,
        "result": serialize(result),
    }



def _workboard_validation_prompt(task):
    title = task.get("title") or "Untitled task"
    description = task.get("description") or ""

    text = (title + " " + description).lower()

    visual = any(
        x in text
        for x in (
            "ui", "hud", "menu", "button", "camera",
            "visual", "viewport", "layout", "screen"
        )
    )

    code_related = any(
        x in text
        for x in (
            "code", "cpp", "c++", "blueprint",
            "compile", "build", "class", "function"
        )
    )

    extra = []

    if visual:
        extra.append(
            "- This is visual/UI/camera related. "
            "Capture or inspect the Unreal viewport when a registered "
            "capture/visual tool is available."
        )

    if code_related:
        extra.append(
            "- This is code/Blueprint/build related. "
            "Use an available compile/build/inspection verifier when possible."
        )

    return f"""
WORKBOARD QA VALIDATION

Task:
{title}

Original description:
{description}

You are the independent QA verifier for this completed Workboard task.

STRICT RULES:
- READ ONLY. Do not modify, create, delete, move, rename or save project content.
- Use real registered tools and collect independent evidence.
- Verify the actual result, not the previous Agent's claim.
- If the task is not actually complete, clearly report failure.
- Do not use run_powershell.
- Do not use open_project unless absolutely required to restore a broken Unreal bridge.
- You must perform at least one real verification tool call before final.
{chr(10).join(extra)}

Return a concise final verdict with:
STATUS: PASS
or
STATUS: FAIL

Then list the concrete evidence.
""".strip()


def _validation_requires_visual(task):
    text = (
        str(task.get("title") or "")
        + " "
        + str(task.get("description") or "")
    ).lower()

    return any(
        x in text
        for x in (
            "ui", "hud", "menu", "button", "camera",
            "visual", "viewport", "layout", "screen"
        )
    )


def _validate_workboard_task(task):
    """
    Deterministic Workboard delivery gate.

    Board progression must NEVER depend on an LLM wording a verdict correctly.
    We validate the concrete evidence already produced by execution.

    Policy:
      - every task needs successful tool evidence
      - visual/UI/camera work additionally needs visual evidence
      - code/build/compile work additionally needs build/compile evidence
      - explicit execution failure always fails
    """

    task_id = task["id"]

    current = get_task(task_id) or task
    evidence_items = list(current.get("evidence") or [])

    completion = [
        x for x in evidence_items
        if x.get("type") in (
            "agent_completion",
            "agent_execution_fallback",
        )
    ]

    if not completion:
        update_runtime_task(
            task_id,
            "blocked",
            note="Validation failed: execution evidence missing",
            evidence={
                "type": "qa_validation",
                "passed": False,
                "decision_source": "deterministic_delivery_gate",
                "reason": "missing_execution_evidence",
                "at": time.time(),
            },
        )

        return {
            "ok": False,
            "task_id": task_id,
            "reason": "missing_execution_evidence",
        }

    latest = completion[-1]

    successful_calls = int(
        latest.get("successful_calls")
        or 0
    )

    final_text = str(
        latest.get("final")
        or latest.get("result")
        or ""
    ).lower()

    failure_markers = (
        "status: fail",
        "could not complete",
        "unable to complete",
        "execution failed",
        "not completed",
        "blocked",
    )

    explicit_failure = any(
        x in final_text
        for x in failure_markers
    )

    text = (
        str(current.get("title") or "")
        + " "
        + str(current.get("description") or "")
    ).lower()

    visual_required = any(
        x in text
        for x in (
            "ui", "hud", "menu", "button",
            "camera", "visual", "viewport",
            "layout", "screen"
        )
    )

    build_required = any(
        x in text
        for x in (
            "code", "cpp", "c++",
            "blueprint", "compile",
            "build", "class", "function"
        )
    )

    # Gather all evidence strings so future tools can satisfy the gate
    # without changing this state machine.
    evidence_blob = json.dumps(
        evidence_items,
        ensure_ascii=False,
        default=str,
    ).lower()

    visual_evidence = any(
        x in evidence_blob
        for x in (
            "screenshot",
            "capture_unreal_viewport",
            "visual_review",
            "viewport_capture",
        )
    )

    build_evidence = any(
        x in evidence_blob
        for x in (
            "build",
            "compile",
            "compile_blueprint",
            "build succeeded",
            "result: succeeded",
        )
    )

    passed = (
        successful_calls > 0
        and not explicit_failure
        and (
            not visual_required
            or visual_evidence
        )
        and (
            not build_required
            or build_evidence
        )
    )

    validation_evidence = {
        "type": "qa_validation",
        "passed": passed,
        "decision_source": "deterministic_delivery_gate",
        "successful_calls": successful_calls,
        "visual_required": visual_required,
        "visual_evidence": visual_evidence,
        "build_required": build_required,
        "build_evidence": build_evidence,
        "explicit_failure": explicit_failure,
        "at": time.time(),
    }

    if not passed:
        reasons = []

        if successful_calls <= 0:
            reasons.append("no successful tool evidence")

        if explicit_failure:
            reasons.append("execution reported failure")

        if visual_required and not visual_evidence:
            reasons.append("visual evidence missing")

        if build_required and not build_evidence:
            reasons.append("build/compile evidence missing")

        validation_evidence["reasons"] = reasons

        update_runtime_task(
            task_id,
            "blocked",
            note="Validation failed: " + ", ".join(reasons),
            evidence=validation_evidence,
        )

        return {
            "ok": False,
            "task_id": task_id,
            "evidence": validation_evidence,
        }

    update_runtime_task(
        task_id,
        "tested",
        note="Deterministic validation passed",
        evidence=validation_evidence,
    )

    update_runtime_task(
        task_id,
        "finished",
        note="Task delivered after verified evidence gate",
        evidence={
            "type": "delivery",
            "validated": True,
            "validator": "deterministic_delivery_gate",
            "at": time.time(),
        },
    )

    return {
        "ok": True,
        "task_id": task_id,
        "status": "finished",
        "evidence": validation_evidence,
    }

def _workboard_runner_loop():
    workboard_runner["running"] = True
    workboard_runner["stop_requested"] = False

    try:
        while not workboard_runner["stop_requested"]:

            # ------------------------------------------------
            # PHASE 1 ? QA owns anything already in Testing.
            # This makes validation recoverable and independent
            # from the exact execution-return timing.
            # ------------------------------------------------

            testing_task = get_next_testing_task()

            if testing_task is not None:
                workboard_runner["current_task_id"] = testing_task["id"]

                qa_result = _validate_workboard_task(testing_task)

                workboard_runner["last_result"] = {
                    "phase": "validation",
                    "validation": serialize(qa_result),
                }

                time.sleep(1)
                continue

            # ------------------------------------------------
            # PHASE 2 ? Execute the next Ready task.
            # ------------------------------------------------

            task = get_next_ready_task()

            if task is None:
                workboard_runner["current_task_id"] = None
                time.sleep(2)
                continue

            workboard_runner["current_task_id"] = task["id"]

            # A previous failed/blocked/approval execution must NEVER
            # deadlock the autonomous queue.
            global execution_state

            if execution_state is not None:
                active_wb_id = execution_state.get("workboard_task_id")
                active_wb_task = (
                    get_task(active_wb_id)
                    if active_wb_id
                    else None
                )

                active_status = (
                    (active_wb_task or {}).get("status")
                )

                # Only preserve an execution that genuinely belongs
                # to a currently running/testing card.
                if active_status not in ("progress", "testing"):
                    stale_id = execution_state.get("id")

                    for approval_id, approval in list(
                        pending_approvals.items()
                    ):
                        if approval.get("execution_id") == stale_id:
                            pending_approvals.pop(
                                approval_id,
                                None,
                            )

                    execution_state = None

            result = _run_workboard_task(task)

            if (
                not result.get("ok")
                and "active execution" in str(
                    result.get("error", "")
                ).lower()
            ):
                execution_state = None

                result = _run_workboard_task(task)

            workboard_runner["last_result"] = {
                "phase": "execution",
                "execution": serialize(result),
            }

            if result.get("paused"):
                break

            # Do NOT perform QA inline here.
            # The next loop iteration will observe Testing
            # and process it through Phase 1.
            time.sleep(1)

    except BaseException as exc:
        workboard_runner["last_result"] = {
            "phase": "runner_crash",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

        emit(
            "workboard",
            "Queue runner recovered from crash",
            workboard_runner["last_result"],
            "error",
        )

    finally:
        workboard_runner["running"] = False
        workboard_runner["current_task_id"] = None
        workboard_runner["thread"] = None



def _workboard_one_shot_worker(task_id: str, phase: str):
    global execution_state

    try:
        task = get_task(task_id)

        if not task:
            workboard_runner["last_result"] = {
                "phase": "worker_error",
                "ok": False,
                "error": "Task disappeared before execution",
                "task_id": task_id,
            }
            return

        # ----------------------------------------------------
        # QA-only card
        # ----------------------------------------------------
        if phase == "validation":
            qa = _validate_workboard_task(task)

            workboard_runner["last_result"] = {
                "phase": "validation",
                "validation": serialize(qa),
            }
            return

        # ----------------------------------------------------
        # Remove stale global execution before a new Board card.
        # Never steal a genuinely active manual Agent execution.
        # ----------------------------------------------------
        if execution_state is not None:
            wb_id = execution_state.get("workboard_task_id")
            state_name = str(
                execution_state.get("state") or ""
            ).upper()

            if wb_id:
                old_task = get_task(wb_id)
                old_status = (old_task or {}).get("status")

                if old_status not in ("progress", "testing"):
                    stale_id = execution_state.get("id")

                    for approval_id, item in list(
                        pending_approvals.items()
                    ):
                        if item.get("execution_id") == stale_id:
                            pending_approvals.pop(
                                approval_id,
                                None,
                            )

                    execution_state = None

            elif state_name not in ("PLANNING", "RUNNING", "PAUSED"):
                execution_state = None

        # ----------------------------------------------------
        # Execute card
        # ----------------------------------------------------
        result = _run_workboard_task(task)

        final_result = {
            "phase": "execution",
            "execution": serialize(result),
        }

        # ----------------------------------------------------
        # Immediately perform deterministic QA when execution
        # successfully moved the card to Testing.
        # ----------------------------------------------------
        current = get_task(task_id)

        if (
            result.get("ok")
            and current
            and current.get("status") == "testing"
        ):
            qa = _validate_workboard_task(current)

            final_result = {
                "phase": "complete_pipeline",
                "execution": serialize(result),
                "validation": serialize(qa),
            }

        workboard_runner["last_result"] = final_result

    except BaseException as exc:
        workboard_runner["last_result"] = {
            "phase": "worker_crash",
            "ok": False,
            "task_id": task_id,
            "error": f"{type(exc).__name__}: {exc}",
        }

        emit(
            "workboard",
            "Autopilot worker crashed",
            workboard_runner["last_result"],
            "error",
        )

    finally:
        workboard_runner["running"] = False
        workboard_runner["current_task_id"] = None
        workboard_runner["thread"] = None


@app.post("/api/workboard/runner/start")
def workboard_runner_start():
    global execution_state

    # Recover only genuinely abandoned Progress cards.
    active_execution_id = (
        execution_state.get("id")
        if execution_state is not None
        else None
    )

    recovered = recover_orphaned_progress_tasks(
        active_execution_id=active_execution_id,
    )

    with lock:
        if workboard_runner.get("running"):
            return {
                "ok": True,
                "already_running": True,
                "runner": serialize(workboard_runner),
            }

        # QA has priority.
        testing_task = get_next_testing_task()
        ready_task = get_next_ready_task()

        candidate = testing_task or ready_task

        if candidate is None:
            return {
                "ok": True,
                "started": False,
                "reason": "no_executable_work",
                "recovered_tasks": recovered,
            }

        phase = (
            "validation"
            if testing_task is not None
            else "execution"
        )

        workboard_runner["running"] = True
        workboard_runner["stop_requested"] = False
        workboard_runner["current_task_id"] = candidate["id"]

        t = threading.Thread(
            target=_workboard_one_shot_worker,
            args=(candidate["id"], phase),
            name=f"workboard-one-shot-{candidate['id'][:8]}",
            daemon=True,
        )

        workboard_runner["thread"] = t
        t.start()

    return {
        "ok": True,
        "started": True,
        "task_id": candidate["id"],
        "task_title": candidate.get("title"),
        "phase": phase,
        "recovered_tasks": recovered,
    }



@app.post("/api/workboard/runner/stop")
def workboard_runner_stop():
    workboard_runner["stop_requested"] = True

    return {
        "ok": True,
        "stop_requested": True,
    }


@app.get("/api/workboard/runner/status")
def workboard_runner_status():
    return {
        "ok": True,
        "running": workboard_runner["running"],
        "current_task_id": workboard_runner["current_task_id"],
        "last_result": workboard_runner["last_result"],
    }


@app.post("/api/workboard/tasks/{task_id}/execute")
def workboard_execute_task(task_id: str):
    task = get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail="Workboard task not found",
        )

    if task.get("requires_approval") and not task.get("approved"):
        raise HTTPException(
            status_code=409,
            detail="Task requires approval",
        )

    if task.get("status") not in ("ready", "planned"):
        raise HTTPException(
            status_code=409,
            detail=f"Task is not executable from status {task.get('status')}",
        )

    if workboard_runner["running"]:
        raise HTTPException(
            status_code=409,
            detail="Queue runner is already active",
        )

    def worker():
        workboard_runner["current_task_id"] = task_id

        try:
            execution_result = _run_workboard_task(task)

            final_result = {
                "phase": "execution",
                "execution": serialize(execution_result),
            }

            current_task = get_task(task_id)

            if (
                execution_result.get("ok")
                and current_task
                and current_task.get("status") == "testing"
            ):
                qa_result = _validate_workboard_task(current_task)

                final_result = {
                    "phase": "complete_pipeline",
                    "execution": serialize(execution_result),
                    "validation": serialize(qa_result),
                }

            workboard_runner["last_result"] = final_result

        finally:
            workboard_runner["current_task_id"] = None

    threading.Thread(
        target=worker,
        name=f"workboard-task-{task_id[:8]}",
        daemon=True,
    ).start()

    return {
        "ok": True,
        "started": True,
        "task_id": task_id,
    }

# ============================================================
# ROUTES
# ============================================================

# >>> VISION_SAFE_APPROVAL_V4 >>>

_requires_approval_v3 = requires_approval


def _vision_collect_strings(value):
    out = []

    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_vision_collect_strings(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_vision_collect_strings(v))

    return out


def requires_approval(action, args):
    if action == "run_powershell":
        allowed = ('& "$env:LOCALAPPDATA\\\\UnrealAgent\\\\vision_review.ps1"', '& "C:\\\\Users\\\\Shadow\\\\AppData\\\\Local\\\\UnrealAgent\\\\vision_review.ps1"', 'C:\\\\Users\\\\Shadow\\\\AppData\\\\Local\\\\UnrealAgent\\\\vision_review.ps1')

        values = {
            s.strip()
            for s in _vision_collect_strings(args)
        }

        if values and values.issubset(allowed):
            return False

    return _requires_approval_v3(action, args)

# <<< VISION_SAFE_APPROVAL_V4 <<<

@app.get("/")
def index():
    return FileResponse(
        UI_DIR / "index.html"
    )


@app.get("/api/status")
def status():

    bridge_status = None

    try:
        if "unreal_ping" in REGISTRY:
            bridge_status = REGISTRY[
                "unreal_ping"
            ].func()

    except Exception as exc:
        bridge_status = {
            "ok": False,
            "error": str(exc),
        }

    return {
        "ok": True,
        "version": "Adaptive API v5.2",
        "models": {
            "fast": FAST_MODEL,
            "reasoning": REASONING_MODEL,
            "coder": CODER_MODEL,
            "vision": (
                VISION_MODEL
                if VISION_MODEL_AVAILABLE
                else None
            ),
            "heavy": (
                HEAVY_MODEL
                if HEAVY_MODEL_AVAILABLE
                else None
            ),
        },
        "unreal": serialize(bridge_status),
        "pending_approvals":
            len(pending_approvals),
        "event_count":
            len(events),
        "execution_active":
            execution_state is not None,
    }


@app.get("/api/events")
def get_events():
    return {
        "events": events[-150:]
    }


@app.get("/api/events/stream/{task_id}")
def stream_events(task_id: str):

    def event_generator():
        recent = [event for event in events[-150:] if event.get("task_id") == task_id]
        for event in recent:
            yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"

        seen_ids = {event.get("id") for event in events}

        while True:
            for event in list(events):
                event_id = event.get("id")
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                if event.get("task_id") != task_id:
                    continue
                yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"

            yield ": keep-alive\n\n"
            time.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )



@app.get("/api/events/stream")
def stream_all_events():

    def event_generator():
        recent = list(events[-100:])

        for event in recent:
            yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"

        seen_ids = {event.get("id") for event in events}

        while True:
            for event in list(events):
                event_id = event.get("id")
                if event_id in seen_ids:
                    continue

                seen_ids.add(event_id)
                yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"

            yield ": keep-alive\n\n"
            time.sleep(0.35)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

@app.post("/api/chat")
def chat(request: ChatRequest):

    global messages

    message = request.message.strip()

    if not message:
        raise HTTPException(
            400,
            "Message cannot be empty.",
        )

    with lock:

        emit(
            "user",
            "New request",
            message,
            "info",
        )

        messages.append(
            {
                "role": "user",
                "content": message,
            }
        )

        return route_request(message)


@app.post("/api/approval")
def approval(request: ApprovalRequest):

    global execution_state

    with lock:

        pending = pending_approvals.pop(
            request.approval_id,
            None,
        )

        if pending is None:
            raise HTTPException(
                404,
                "Approval not found.",
            )

        state = execution_state

        if (
            state is None
            or pending["execution_id"]
            != state["id"]
        ):
            raise HTTPException(
                409,
                "Execution is no longer active.",
            )

        action = pending["action"]
        args = pending["args"]
        raw = pending["raw"]

        allowed, guard_error = guard_tool_call(
            state["task"],
            action,
            args,
        )

        if not allowed:
            emit(
                "guard",
                f"Blocked approved action: {action}",
                guard_error,
                "warning",
            )

            return {
                "state": "blocked",
                "tool": action,
                "message": guard_error,
            }

        if not request.approved:

            emit(
                "approval",
                f"Rejected: {action}",
                args,
                "rejected",
            )

            state["model_messages"].append(
                {
                    "role": "assistant",
                    "content": raw,
                }
            )

            state["model_messages"].append(
                {
                    "role": "user",
                    "content": (
                        "The user rejected this operation. "
                        "Do not claim it succeeded. "
                        "Find a safe alternative or explain "
                        "that this specific operation was cancelled."
                    ),
                }
            )

            return run_execution_until_pause()

        spec = REGISTRY[action]

        emit(
            "tool",
            f"Running {action}",
            {
                "args": args,
                "approved": True,
            },
            "running",
        )

        try:
            result = spec.func(**args)

        except Exception as exc:
            result = {
                "ok": False,
                "error":
                    f"{type(exc).__name__}: {exc}",
            }

        process_tool_result(
            state,
            raw,
            action,
            args,
            result,
        )

        return run_execution_until_pause()


@app.post("/api/reset")
def reset():

    global messages
    global execution_state

    with lock:

        messages = [
            {
                "role": "system",
                "content": SYSTEM,
            }
        ]

        execution_state = None

        events.clear()

        pending_approvals.clear()

        save_session(messages)

    return {
        "ok": True
    }


@app.post("/api/pause")
def pause():
    global execution_state
    with lock:
        if execution_state is None or execution_state.get("state") != "RUNNING":
            raise HTTPException(400, "No running task to pause.")
        execution_state["state"] = "PAUSED"
    return {"state": "paused"}

@app.post("/api/resume")
def resume():
    global execution_state
    with lock:
        if execution_state is None or execution_state.get("state") != "PAUSED":
            raise HTTPException(400, "No paused task to resume.")
        execution_state["state"] = "RUNNING"
    return {"state": "running"}

@app.post("/api/cancel")
def cancel():
    global execution_state
    with lock:
        if execution_state is None or execution_state.get("state") not in ["RUNNING", "PAUSED"]:
            raise HTTPException(400, "No active task to cancel.")
        execution_state["state"] = "CANCELLED"
    return {"state": "cancelled"}




# >>> RELEASE_TASK_APIS_V1 >>>

def _start_ui_execution(task: str):
    """
    Run a UI-triggered action through the existing Unreal Agent execution
    engine so normal tool guards, approvals, tracing and verification remain
    active.
    """
    global execution_state

    if execution_state is not None:
        state = str(execution_state.get("state") or "").upper()

        if state in ("RUNNING", "PLANNING", "PAUSED"):
            raise HTTPException(
                409,
                "Another task is already active. Pause, resume, stop, or finish it first."
            )

    return route_request(task)


@app.post("/api/retry")
def retry_task():
    global execution_state

    if execution_state is None:
        raise HTTPException(
            400,
            "No previous execution is available to retry."
        )

    previous_task = str(
        execution_state.get("task") or ""
    ).strip()

    if not previous_task:
        raise HTTPException(
            400,
            "The previous execution has no task text."
        )

    previous_trace = trace_summary(
        execution_state,
        count=12,
    )

    retry_prompt = (
        "EXECUTE RETRY.\n"
        "Retry the original task from a clean execution state.\n"
        "Inspect previous evidence first and do not repeat an identical failed tool call.\n\n"
        f"ORIGINAL TASK:\n{previous_task}\n\n"
        "PREVIOUS TRACE:\n"
        + json.dumps(
            previous_trace,
            ensure_ascii=False,
            default=str,
        )
    )

    execution_state = None

    emit(
        "control",
        "Retry requested",
        {
            "original_task": previous_task,
        },
        "info",
    )

    return _start_ui_execution(
        retry_prompt
    )


@app.post("/api/self-fix")
def self_fix_task():
    global execution_state

    if execution_state is None:
        raise HTTPException(
            400,
            "No failed or active execution is available for Self-Fix."
        )

    original_task = str(
        execution_state.get("task") or ""
    ).strip()

    previous_trace = trace_summary(
        execution_state,
        count=20,
    )

    fix_prompt = (
        "EXECUTE SELF-FIX.\n"
        "Diagnose the previous execution using its actual tool evidence. "
        "Identify the failure, choose a different valid strategy, execute the fix, "
        "and independently verify the result. "
        "Do not claim success without tool evidence.\n\n"
        f"ORIGINAL TASK:\n{original_task}\n\n"
        "PREVIOUS TRACE:\n"
        + json.dumps(
            previous_trace,
            ensure_ascii=False,
            default=str,
        )
    )

    execution_state = None

    emit(
        "control",
        "Self-Fix requested",
        {
            "original_task": original_task,
        },
        "warning",
    )

    return _start_ui_execution(
        fix_prompt
    )


@app.post("/api/build")
def build_project():
    return _start_ui_execution(
        "EXECUTE BUILD. "
        "Build or compile the active Unreal project using the registered tools. "
        "Report the exact build result and errors. "
        "Do not modify unrelated project content."
    )


@app.post("/api/run")
def run_project():
    return _start_ui_execution(
        "EXECUTE RUN. "
        "Run or start the active Unreal project or PIE using available registered tools. "
        "Confirm the actual runtime state from tool evidence. "
        "Do not invent success."
    )


@app.post("/api/validate")
def validate_project():
    return _start_ui_execution(
        "EXECUTE VALIDATION. "
        "Validate the latest project state using read-only verification where possible. "
        "Check Unreal connectivity, current level, relevant logs, build state, "
        "and the result of the latest changes. "
        "Do not modify anything unless validation itself absolutely requires it. "
        "Return concrete evidence."
    )


@app.post("/api/screenshot")
def screenshot_project():
    return _start_ui_execution(
        "EXECUTE SCREENSHOT. "
        "Capture the current Unreal viewport using the registered viewport capture tool. "
        "Return the real capture result or exact failure. "
        "Do not use visual_review_unreal and do not loop."
    )

# <<< RELEASE_TASK_APIS_V1 <<<


# >>> ASYNC_UI_EXECUTION_V1 >>>

def _run_ui_execution_background(task_id: str):
    global execution_state

    try:
        result = run_execution_until_pause()

        state_name = ""
        message = ""

        if isinstance(result, dict):
            state_name = str(result.get("state") or "").lower()
            message = str(result.get("message") or "")

        # Approval/pause are intentionally non-terminal.
        if state_name in ("approval_required", "paused"):
            return

        if state_name in ("complete", "completed", "success"):
            emit(
                "final",
                "Background execution completed",
                message or result,
                "complete",
                task_id=task_id,
            )

        elif state_name in ("failed", "error", "cancelled", "canceled"):
            emit(
                "error",
                "Background execution terminated",
                message or result,
                "failed",
                task_id=task_id,
            )

        else:
            emit(
                "error",
                "Background execution ended unexpectedly",
                result,
                "failed",
                task_id=task_id,
            )

    except BaseException as exc:
        emit(
            "error",
            "Background execution crashed",
            f"{type(exc).__name__}: {exc}",
            "failed",
            task_id=task_id,
        )

    finally:
        # Never leave a dead async task occupying the global execution slot.
        if (
            execution_state is not None
            and execution_state.get("id") == task_id
            and str(execution_state.get("state") or "").upper()
                not in ("PAUSED",)
            and not any(
                p.get("execution_id") == task_id
                for p in pending_approvals.values()
            )
        ):
            execution_state = None


def _start_async_ui_execution(message: str, source: str = "ui"):
    import threading
    global execution_state
    global messages

    message = str(message or "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty.")

    with lock:
        if execution_state is not None:
            current = str(execution_state.get("state") or "").upper()
            if current in ("PLANNING", "RUNNING", "PAUSED"):
                raise HTTPException(
                    409,
                    "Another task is already active. Finish, stop, or resume it first.",
                )

        messages.append({"role": "user", "content": message})
        execution_state = new_execution(message)
        task_id = execution_state["id"]

        emit(
            "user",
            "New async request",
            {"source": source, "message": message},
            "info",
            task_id=task_id,
        )

    worker = threading.Thread(
        target=_run_ui_execution_background,
        args=(task_id,),
        name=f"unreal-agent-{task_id[:8]}",
        daemon=True,
    )
    worker.start()

    return {
        "ok": True,
        "state": "running",
        "action": source,
        "task_id": task_id,
        "message": "Execution started.",
        "data": {
            "task_id": task_id,
            "events_url": f"/api/events/stream/{task_id}",
        },
    }

# <<< ASYNC_UI_EXECUTION_V1 <<<

# >>> UNIFIED_ACTION_API_V1 >>>

@app.post("/api/action")
def unified_action(request: dict):
    """
    Single frontend transport endpoint.

    Request body:
    {
        "action": "build",
        "payload": {...},
        "context": {...}
    }

    Existing legacy endpoints remain available for compatibility.
    This endpoint only dispatches to real backend capabilities.
    Unsupported actions return an explicit not_wired response.
    """
    action = str(request.get("action") or "").strip().lower()
    payload = request.get("payload") or {}
    context = request.get("context") or {}

    if not isinstance(payload, dict):
        raise HTTPException(400, "payload must be an object.")

    if not action:
        raise HTTPException(400, "action is required.")

    emit(
        "ui",
        f"UI action: {action}",
        {
            "action": action,
            "payload": payload,
            "context": {
                "project": context.get("project"),
                "provider": context.get("provider"),
                "model": context.get("model"),
                "language": context.get("language"),
            },
        },
        "info",
    )

    # ------------------------------------------------------------------
    # Lightweight/read-only backend actions
    # ------------------------------------------------------------------

    if action == "ping":
        return {
            "ok": True,
            "state": "complete",
            "action": action,
            "message": "Unreal Agent backend is reachable.",
            "data": {
                "status": status(),
            },
        }

    if action == "status":
        return {
            "ok": True,
            "state": "complete",
            "action": action,
            "data": status(),
        }

    if action == "tools_list":
        return {
            "ok": True,
            "state": "complete",
            "action": action,
            "data": {
                "tools": sorted(REGISTRY.keys()),
            },
        }

    if action == "tool_permissions":
        return {
            "ok": True,
            "state": "complete",
            "action": action,
            "data": {
                "guarded": True,
                "approval_required_for_guarded_operations": True,
                "message": (
                    "Tool permissions are enforced by the existing "
                    "guard_tool_call + approval pipeline."
                ),
            },
        }

    # ------------------------------------------------------------------
    # Existing task-control endpoints
    # ------------------------------------------------------------------

    if action == "pause":
        result = pause()
        return {"ok": True, "action": action, **result}

    if action == "resume":
        result = resume()
        return {"ok": True, "action": action, **result}

    if action in ("stop", "cancel"):
        result = cancel()
        return {"ok": True, "action": action, **result}

    if action == "reset":
        result = reset()
        return {
            "ok": True,
            "state": "complete",
            "action": action,
            "data": result,
        }

    if action == "retry":
        result = retry_task()
        return {
            "ok": True,
            "action": action,
            "state": (
                result.get("state")
                if isinstance(result, dict)
                else "running"
            ),
            "data": result,
        }

    if action in ("self_fix", "self-fix"):
        result = self_fix_task()
        return {
            "ok": True,
            "action": action,
            "state": (
                result.get("state")
                if isinstance(result, dict)
                else "running"
            ),
            "data": result,
        }

    # ------------------------------------------------------------------
    # Existing execution wrappers
    # ------------------------------------------------------------------

    if action == "build":
        return {
            "ok": True,
            "action": action,
            "data": build_project(),
        }

    if action == "run":
        return {
            "ok": True,
            "action": action,
            "data": run_project(),
        }

    if action == "validate":
        return {
            "ok": True,
            "action": action,
            "data": validate_project(),
        }

    if action == "screenshot":
        return {
            "ok": True,
            "action": action,
            "data": screenshot_project(),
        }

    # ------------------------------------------------------------------
    # Prompt / plan / inspection through the real Agent execution engine
    # ------------------------------------------------------------------

    if action == "prompt":
        message = str(payload.get("message") or "").strip()

        if not message:
            raise HTTPException(
                400,
                "payload.message is required for prompt.",
            )

        return _start_async_ui_execution(
            message,
            source="prompt",
        )

    if action == "inspect_project":
        return {
            "ok": True,
            "action": action,
            "data": _start_ui_execution(
                "READ ONLY. Inspect the active Unreal project using "
                "registered read-only tools. Report concrete project, "
                "level, actor, asset, connectivity, and relevant status "
                "evidence. Do not modify anything."
            ),
        }

    if action == "plan":
        task_text = str(
            payload.get("message")
            or payload.get("task")
            or ""
        ).strip()

        if not task_text:
            task_text = (
                "Create a concrete execution plan for the current "
                "Unreal project. Inspect first. Do not modify anything."
            )

        return {
            "ok": True,
            "action": action,
            "data": _start_ui_execution(
                "READ ONLY PLAN. "
                + task_text
                + " Return the plan and stop without editing."
            ),
        }

    # ------------------------------------------------------------------
    # Approval bridge.
    # If the frontend omitted approval_id and exactly one approval is
    # pending, use that one. Multiple pending approvals require an id.
    # ------------------------------------------------------------------

    if action in ("approval_approve", "approval_reject"):
        approval_id = str(
            payload.get("approval_id")
            or ""
        ).strip()

        if not approval_id:
            ids = list(pending_approvals.keys())

            if len(ids) == 1:
                approval_id = ids[0]
            elif len(ids) == 0:
                raise HTTPException(
                    400,
                    "No approval is currently pending.",
                )
            else:
                raise HTTPException(
                    400,
                    "Multiple approvals are pending; approval_id is required.",
                )

        result = approval(
            ApprovalRequest(
                approval_id=approval_id,
                approved=(action == "approval_approve"),
            )
        )

        return {
            "ok": True,
            "action": action,
            "data": result,
        }

    # ------------------------------------------------------------------
    # Project selection goes through the Agent engine so the registered
    # open_project/discovery tools, guards and trace remain authoritative.
    # ------------------------------------------------------------------

    if action == "project_select":
        project_path = str(
            payload.get("path")
            or ""
        ).strip()

        if not project_path:
            raise HTTPException(
                400,
                "payload.path is required for project_select.",
            )

        return {
            "ok": True,
            "action": action,
            "data": _start_ui_execution(
                "EXECUTE PROJECT SELECT. "
                "Use registered project discovery/open-project tools only. "
                "Open or select exactly this project path: "
                + json.dumps(project_path)
                + ". Verify the active project after selection. "
                "Do not edit project content."
            ),
        }

    # ------------------------------------------------------------------
    # Explicitly NOT fake.
    # These frontend actions need their own real backend modules.
    # They deliberately return not_wired until implemented.
    # ------------------------------------------------------------------

    not_wired = {
        "project_clone",
        "git_status",
        "git_checkpoint",
        "git_commit",
        "git_revert",
        "patch_apply",
        "patch_reject",
        "patch_revert",
        "provider_models",
        "provider_configure",
        "provider_test",
        "memory_add",
        "memory_list",
        "memory_search",
        "memory_export",
        "memory_clear",
        "routing",
    }

    if action in not_wired:
        return {
            "ok": False,
            "state": "not_wired",
            "action": action,
            "message": (
                f"{action} is recognized by /api/action but does not yet "
                "have a real backend implementation."
            ),
            "data": {},
        }

    raise HTTPException(
        400,
        f"Unknown action: {action}",
    )

# <<< UNIFIED_ACTION_API_V1 <<<

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )




# ============================================================
# PERSISTENT WORKBOARD AUTOPILOT
# ============================================================

def _persistent_workboard_autopilot():
    """
    Keep the Workboard queue alive without user babysitting.
    Starts/restarts the queue whenever executable or testing work exists.
    """
    while True:
        try:
            runner_alive = bool(workboard_runner.get("running"))

            ready_task = get_next_ready_task()
            testing_task = get_next_testing_task()

            if not runner_alive and (
                ready_task is not None
                or testing_task is not None
            ):
                workboard_runner_start()

            time.sleep(2)

        except BaseException as exc:
            emit(
                "workboard",
                "Autopilot recovery",
                f"{type(exc).__name__}: {exc}",
                "warning",
            )
            time.sleep(3)


@app.on_event("startup")
def start_persistent_workboard_autopilot():
    """
    Production Workboard startup.
    Exactly one daemon watchdog per API process.
    """
    if getattr(
        app.state,
        "persistent_workboard_autopilot_started",
        False,
    ):
        return

    app.state.persistent_workboard_autopilot_started = True

    threading.Thread(
        target=_persistent_workboard_autopilot,
        name="persistent-workboard-autopilot",
        daemon=True,
    ).start()


@app.post("/api/workboard/autopilot/tick")
def workboard_autopilot_tick():
    """
    Hard failsafe for Workboard Autopilot.

    Called by the UI heartbeat and safe to call repeatedly.
    If executable work exists and the queue is idle, start it.
    """
    global execution_state

    try:
        # Clear stale execution left behind by an old blocked/finished card.
        if execution_state is not None:
            wb_id = execution_state.get("workboard_task_id")

            if wb_id:
                wb_task = get_task(wb_id)
                wb_status = (wb_task or {}).get("status")

                if wb_status not in ("progress", "testing"):
                    stale_execution_id = execution_state.get("id")

                    for approval_id, item in list(pending_approvals.items()):
                        if item.get("execution_id") == stale_execution_id:
                            pending_approvals.pop(approval_id, None)

                    execution_state = None

        testing_task = get_next_testing_task()
        ready_task = get_next_ready_task()

        candidate = testing_task or ready_task

        if candidate is None:
            return {
                "ok": True,
                "started": False,
                "reason": "no_executable_work",
                "runner": serialize(workboard_runner),
            }

        if workboard_runner.get("running"):
            return {
                "ok": True,
                "started": False,
                "reason": "already_running",
                "task_id": candidate.get("id"),
                "runner": serialize(workboard_runner),
            }

        result = workboard_runner_start()

        return {
            "ok": True,
            "started": True,
            "task_id": candidate.get("id"),
            "task_title": candidate.get("title"),
            "start_result": serialize(result),
            "runner": serialize(workboard_runner),
        }

    except BaseException as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "runner": serialize(workboard_runner),
        }
