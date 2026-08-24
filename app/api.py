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


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Unreal Agent",
    version="5.2.0",
)

UI_DIR = ROOT / "ui"

app.mount(
    "/static",
    StaticFiles(directory=str(UI_DIR)),
    name="static",
)

# Create MemorySystem instance for API
MEMORY = MemorySystem()


class ChatRequest(BaseModel):
    message: str


class ApprovalRequest(BaseModel):
    approval_id: str
    approved: bool


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


# ============================================================
# APPROVAL POLICY
# ============================================================

def requires_approval(
    action: str,
    args: dict[str, Any],
) -> bool:

    a = action.lower()

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

def new_execution(task: str):

    task_id = str(uuid.uuid4())
    plan = create_execution_plan(task)

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

# redefinition of run_execution_until_pause follows unchanged

def run_execution_until_pause():

    global execution_state
    global messages

    state = execution_state

    if state is None:
        return {
            "state": "error",
            "message": "No active execution.",
        }

    if state.get("state") == "PLANNING":
        state["state"] = "RUNNING"
        state["start_ts"] = time.time()

        if state.get("start_ts") and (time.time() - state["start_ts"]) >= MAX_RUNTIME_SECONDS:
            state["state"] = "FAILED"
            state["end_ts"] = time.time()
            return {
                "state": "failed",
                "message": "Execution stopped: maximum runtime reached.",
            }

    for _ in range(80):

        if state.get("start_ts") and (time.time() - state["start_ts"]) >= MAX_RUNTIME_SECONDS:
            state["state"] = "FAILED"
            state["end_ts"] = time.time()
            return {
                "state": "failed",
                "message": "Execution stopped: maximum runtime reached.",
            }

        if state.get("state") == "PAUSED":
            return {"state":"paused","message":"Execution paused."}

        if state.get("state") == "CANCELLED":
            state["end_ts"] = time.time()
            return {"state":"cancelled","message":"Execution cancelled."}

        state["step"] += 1

        emit(
            "thinking",
            "Agent deciding next step",
            {
                "step": state["step"],
                "after_tool": state.get("current_action"),
            },
            "running",
        )

        try:
            raw = call_model_hard_timeout(
                state["model_messages"],
                timeout_seconds=90,
            )

        except Exception as exc:

            msg = (
                f"Model request failed: "
                f"{type(exc).__name__}: {exc}"
            )

            state["state"] = "FAILED"
            state["end_ts"] = time.time()

            emit(
                "error",
                "Model request failed",
                msg,
                "error",
            )

            return {
                "state": "error",
                "message": msg,
            }

        try:
            decision = json.loads(raw)

        except Exception as exc:

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
                        "INVALID JSON RESPONSE. "
                        "Return exactly one valid JSON object. "
                        f"Error: {exc}"
                    ),
                }
            )

            emit(
                "error",
                "Model JSON repair",
                raw,
                "warning",
            )

            continue

        action = str(
            decision.get("action")
            or ""
        ).strip()

        args = decision.get("args") or {}

        reason = str(
            decision.get("reason")
            or ""
        )

        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        if action == "final":

            proposed = str(
                decision.get("final")
                or ""
            )

            if state["verification_pending"]:

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
                            "FINAL REJECTED. "
                            "A mutation still requires "
                            "independent read-only verification."
                        ),
                    }
                )

                emit(
                    "review",
                    "Verification still required",
                    None,
                    "warning",
                )

                continue

            if state["successful_calls"] == 0:

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
                            "FINAL REJECTED. "
                            "EXECUTE mode requires real tool evidence."
                        ),
                    }
                )

                continue

            review = review_completion(
                state["task"],
                state["plan"],
                state["trace"],
                proposed,
            )

            if (
                not review.get("complete", False)
                and state["final_rejections"] < 3
            ):

                state["final_rejections"] += 1

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
                            "QA REVIEW REJECTED COMPLETION.\n"
                            "Missing:\n"
                            + json.dumps(
                                review.get(
                                    "missing",
                                    [],
                                ),
                                ensure_ascii=False,
                            )
                            + "\nInstruction:\n"
                            + str(
                                review.get(
                                    "instruction",
                                    "",
                                )
                            )
                            + "\nContinue execution."
                        ),
                    }
                )

                emit(
                    "review",
                    "QA requested more work",
                    review,
                    "warning",
                )

                continue

            messages.append(
                {
                    "role": "assistant",
                    "content": proposed,
                }
            )

            save_session(messages)

            emit(
                "answer",
                "Agent completed",
                proposed,
                "success",
            )

            execution_state = None

            return {
                "state": "complete",
                "message": proposed,
            }

        # ----------------------------------------------------
        # TOOL NAME
        # ----------------------------------------------------

        if not action or action not in REGISTRY:

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
                        f"ERROR: Unknown tool '{action}'. "
                        "Use ONLY an exact tool from AVAILABLE TOOLS."
                    ),
                }
            )

            emit(
                "error",
                f"Unknown tool: {action or '<empty>'}",
                reason,
                "error",
            )

            continue

        spec = REGISTRY[action]

        # ----------------------------------------------------
        # SCHEMA
        # ----------------------------------------------------

        valid, validation_error = validate_args(
            spec,
            args,
        )

        if not valid:

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
                        f"TOOL SCHEMA ERROR for {action}: "
                        f"{validation_error}. "
                        f"Required schema: {spec.args}"
                    ),
                }
            )

            emit(
                "error",
                f"Schema rejected: {action}",
                validation_error,
                "error",
            )

            continue

        # ----------------------------------------------------
        # HARD GUARDS
        # ----------------------------------------------------

        allowed, guard_error = guard_tool_call(
            state["task"],
            action,
            args,
        )

        if not allowed:

            result = {
                "ok": False,
                "error": guard_error,
                "blocked_by_guard": True,
            }

            # Count blocked attempts too, otherwise a model can loop forever
            # on a tool that the task explicitly forbids.
            state["tool_call_count"] = state.get("tool_call_count", 0) + 1

            signature = json.dumps(
                {
                    "guard_blocked": True,
                    "action": action,
                    "args": args,
                },
                sort_keys=True,
                default=str,
            )

            state["failed_calls"][signature] = (
                state["failed_calls"].get(signature, 0) + 1
            )

            emit(
                "guard",
                f"Blocked invalid action: {action}",
                guard_error,
                "warning",
            )

            # Feed the guard result back to the model so it can change strategy.
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
                        "TOOL CALL BLOCKED BY HARD GUARD.\n"
                        f"Tool: {action}\n"
                        f"Reason: {guard_error}\n"
                        "This tool is unavailable for this task. "
                        "Do NOT call it again. "
                        "Immediately choose a different registered tool "
                        "that complies with the task."
                    ),
                }
            )

            # Stop a pathological identical blocked loop quickly.
            if state["failed_calls"][signature] >= 3:
                state["state"] = "FAILED"
                state["end_ts"] = time.time()

                return {
                    "state": "failed",
                    "message": (
                        f"Execution stopped: model repeated guard-blocked "
                        f"tool '{action}' three times."
                    ),
                }

            if state.get("tool_call_count", 0) >= MAX_TOOL_CALLS:
                state["state"] = "FAILED"
                state["end_ts"] = time.time()
                return {
                    "state": "failed",
                    "message": "Execution stopped: maximum tool call limit reached."
                }

            continue

        # ----------------------------------------------------
        # APPROVAL
        # ----------------------------------------------------

        if requires_approval(action, args):

            approval_id = str(uuid.uuid4())

            pending_approvals[approval_id] = {
                "execution_id": state["id"],
                "raw": raw,
                "action": action,
                "args": args,
                "reason": reason,
            }

            emit(
                "approval",
                f"Approval required: {action}",
                {
                    "approval_id": approval_id,
                    "tool": action,
                    "args": args,
                    "reason": reason,
                },
                "warning",
            )

            return {
                "state": "approval_required",
                "approval_id": approval_id,
                "tool": action,
                "args": args,
                "reason": reason,
            }

        # ----------------------------------------------------
        # EXECUTE
        # ----------------------------------------------------

        emit(
            "tool",
            f"Running {action}",
            {
                "args": args,
                "reason": reason,
                "step": state["step"],
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
        tool_signature = action + ":" + json.dumps(args, sort_keys=True, default=str)
        if state.get("last_tool_signature") == tool_signature:
            state["repeated_tool_count"] = state.get("repeated_tool_count", 1) + 1
        else:
            state["last_tool_signature"] = tool_signature
            state["repeated_tool_count"] = 1

        if state.get("repeated_tool_count", 0) >= 3:
            state["state"] = "FAILED"
            state["end_ts"] = time.time()
            return {
                "state": "failed",
                "message": "Execution stopped: probable tool loop detected.",
            }

        if state.get("tool_call_count", 0) >= MAX_TOOL_CALLS:
            state["state"] = "FAILED"
            state["end_ts"] = time.time()
            return {
                "state": "failed",
                "message": "Execution stopped: maximum tool call limit reached.",
            }


    emit(
        "error",
        "Execution safety limit reached",
        trace_summary(state, 15),
        "error",
    )

    return {
        "state": "error",
        "message":
            "Execution reached the 80-step safety limit.",
    }


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
    try:
        run_execution_until_pause()
    except Exception as exc:
        emit(
            "error",
            "Background execution failed",
            f"{type(exc).__name__}: {exc}",
            "failed",
            task_id=task_id,
        )


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


