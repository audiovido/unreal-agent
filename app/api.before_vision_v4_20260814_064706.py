from __future__ import annotations

import json
import sys
import uuid
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.orchestrator import (
    SYSTEM,
    REGISTRY,
    FAST_MODEL,
    REASONING_MODEL,
    CODER_MODEL,
    HEAVY_MODEL,
    HEAVY_MODEL_AVAILABLE,
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
    version="3.0.0",
)

UI_DIR = ROOT / "ui"

app.mount(
    "/static",
    StaticFiles(directory=str(UI_DIR)),
    name="static",
)


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
):
    event = {
        "id": str(uuid.uuid4()),
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

    plan = create_execution_plan(task)

    emit(
        "planning",
        "Execution plan",
        plan,
        "info",
    )

    return {
        "id": str(uuid.uuid4()),
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


# ============================================================
# EXECUTION LOOP
# ============================================================

def run_execution_until_pause():

    global execution_state
    global messages

    state = execution_state

    if state is None:
        return {
            "state": "error",
            "message": "No active execution.",
        }

    for _ in range(80):

        state["step"] += 1

        try:
            raw = call_model(
                state["model_messages"],
                model=CODER_MODEL,
                json_mode=True,
                temperature=0.08,
                num_ctx=32768,
                timeout=600,
            )

        except Exception as exc:

            msg = (
                f"Model request failed: "
                f"{type(exc).__name__}: {exc}"
            )

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

            emit(
                "guard",
                f"Blocked invalid action: {action}",
                guard_error,
                "warning",
            )

            process_tool_result(
                state,
                raw,
                action,
                args,
                result,
            )

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
        "version": "Adaptive API v3",
        "models": {
            "fast": FAST_MODEL,
            "reasoning": REASONING_MODEL,
            "coder": CODER_MODEL,
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


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app.api:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )