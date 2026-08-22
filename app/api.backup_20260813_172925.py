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
    call_model,
)
from core.tool_registry import validate_args


app = FastAPI(
    title="Unreal Agent",
    version="0.1.0",
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

    if len(events) > 200:
        del events[:-200]

    return event


def serialize(value):
    return json.loads(
        json.dumps(
            value,
            default=str,
        )
    )


def run_agent_until_pause():
    global messages

    for _ in range(30):
        raw = call_model(messages)

        try:
            decision = json.loads(raw)
        except Exception:
            emit(
                "error",
                "Model JSON error",
                raw,
                "error",
            )

            return {
                "state": "error",
                "message": "Model returned invalid JSON.",
            }

        action = decision.get("action")
        args = decision.get("args") or {}
        reason = decision.get("reason", "")

        if action == "final":
            messages.append({
                "role": "assistant",
                "content": raw,
            })

            answer = decision.get("final", "")

            emit(
                "answer",
                "Agent completed",
                answer,
                "success",
            )

            return {
                "state": "complete",
                "message": answer,
            }

        if action not in REGISTRY:
            messages.append({
                "role": "assistant",
                "content": raw,
            })

            messages.append({
                "role": "user",
                "content":
                    f"ERROR: Unknown tool '{action}'. "
                    "Use an exact available tool name.",
            })

            emit(
                "error",
                f"Unknown tool: {action}",
                reason,
                "error",
            )

            continue

        spec = REGISTRY[action]

        valid, validation_error = validate_args(
            spec,
            args,
        )

        if not valid:
            messages.append({
                "role": "assistant",
                "content": raw,
            })

            messages.append({
                "role": "user",
                "content":
                    f"TOOL SCHEMA ERROR for {action}: "
                    f"{validation_error}. "
                    f"Required schema: {spec.args}",
            })

            emit(
                "error",
                f"Schema rejected: {action}",
                validation_error,
                "error",
            )

            continue

        if spec.destructive:
            approval_id = str(uuid.uuid4())

            pending_approvals[approval_id] = {
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

        emit(
            "tool",
            f"Running {action}",
            {
                "args": args,
                "reason": reason,
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

        result = serialize(result)

        emit(
            "tool_result",
            f"{action} finished",
            result,
            "success"
            if result.get("ok", True)
            else "error",
        )

        messages.append({
            "role": "assistant",
            "content": raw,
        })

        messages.append({
            "role": "user",
            "content":
                "ACTUAL TOOL RESULT:\n"
                + json.dumps(
                    result,
                    ensure_ascii=False,
                ),
        })

    return {
        "state": "error",
        "message":
            "Agent reached maximum step count.",
    }


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
        "unreal": serialize(bridge_status),
        "pending_approvals":
            len(pending_approvals),
        "event_count": len(events),
    }


@app.get("/api/events")
def get_events():
    return {
        "events": events[-100:]
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            400,
            "Message cannot be empty.",
        )

    with lock:
        emit(
            "user",
            "New task",
            message,
            "info",
        )

        messages.append({
            "role": "user",
            "content": message,
        })

        return run_agent_until_pause()


@app.post("/api/approval")
def approval(request: ApprovalRequest):
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

        action = pending["action"]
        args = pending["args"]
        raw = pending["raw"]

        messages.append({
            "role": "assistant",
            "content": raw,
        })

        if not request.approved:
            emit(
                "approval",
                f"Rejected: {action}",
                args,
                "rejected",
            )

            messages.append({
                "role": "user",
                "content":
                    "The user rejected this tool "
                    "execution. Do not claim the "
                    "action succeeded. Find a safe "
                    "alternative or report that the "
                    "operation was cancelled.",
            })

            return run_agent_until_pause()

        spec = REGISTRY[action]

        emit(
            "tool",
            f"Running {action}",
            args,
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

        result = serialize(result)

        emit(
            "tool_result",
            f"{action} finished",
            result,
            "success"
            if result.get("ok", True)
            else "error",
        )

        messages.append({
            "role": "user",
            "content":
                "ACTUAL TOOL RESULT:\n"
                + json.dumps(
                    result,
                    ensure_ascii=False,
                ),
        })

        return run_agent_until_pause()


@app.post("/api/reset")
def reset():
    global messages

    with lock:
        messages = [{
            "role": "system",
            "content": SYSTEM,
        }]

        events.clear()
        pending_approvals.clear()

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )
