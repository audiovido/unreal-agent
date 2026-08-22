import json
import sys
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.project_manager import (
    discover_projects,
    inspect_project,
    open_project,
)

from tools.system.tool_runner import (
    read_text_file,
    write_text_file,
    run_powershell,
    unreal_status,
)

from core.tool_registry import build_registry, tool_prompt, validate_args
from tools.unreal.unreal_bridge import UnrealBridge

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5-coder:14b"

BRIDGE = UnrealBridge()

SESSION_FILE = ROOT / "memory" / "conversation.json"


def load_session():
    if not SESSION_FILE.exists():
        return [{"role": "system", "content": SYSTEM}]

    try:
        messages = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(messages, list):
            raise ValueError("session is not a list")

        # Always use the current system prompt.
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = SYSTEM
        else:
            messages.insert(0, {"role": "system", "content": SYSTEM})

        return messages
    except Exception as exc:
        print(f"WARNING: Could not load session: {exc}")
        return [{"role": "system", "content": SYSTEM}]


def save_session(messages):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(
        json.dumps(messages, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


REGISTRY = build_registry(
    discover_projects,
    inspect_project,
    open_project,
    read_text_file,
    write_text_file,
    run_powershell,
    unreal_status,
    bridge=BRIDGE,
)

SYSTEM = f"""
You are UnrealAgent, an autonomous local engineering agent specialized
exclusively in Unreal Engine 5.8.

You have real tools. Use them instead of pretending to perform actions.

OPERATING LOOP:
1. Understand the user's goal.
2. Inspect the environment/project first.
3. Plan the smallest safe action.
4. Call exactly one tool.
5. Examine actual tool output.
6. Verify the result.
7. Continue until the task is complete.

CRITICAL RULES:
- Never claim an action happened unless tool output proves it.
- Never invent tool names.
- Never invent argument names.
- Use ONLY the exact schemas below.
- Do not modify anything when the user requested inspection only.
- Prefer reading/inspection before writing.
- Prefer reversible changes.
- Never delete projects, assets, source files, or directories automatically.
- Never format disks, modify boot configuration, registry security settings,
  credentials, firewall rules, or unrelated system configuration.
- Never execute downloaded scripts blindly.
- If an operation could cause irreversible project loss, stop and explain.
- A failed tool call is evidence of failure, not success.
- If a tool reports "Ambiguous actor label", STOP the current operation immediately.
- Do not call any mutation tool for that ambiguous actor reference.
- Report every internal actor name provided in the tool result's "matches" field.
- Ask the user to choose one of those exact internal actor names before continuing.
- Never choose among ambiguous actor matches automatically.
- After any write or mutation tool, you MUST perform an independent read-only verification before claiming success.
- For actor changes such as spawn, move, rotate, scale, or delete, use get_actor or list_level_actors to verify the actual Unreal state.
- Never use the write tool's own return value as the only verification evidence.
- If verification fails or disagrees with the requested result, do not claim success.

AVAILABLE TOOLS:

{tool_prompt(REGISTRY)}

OUTPUT:
Return ONLY one JSON object.

For a tool call:

{{
  "action": "exact_tool_name",
  "args": {{
    "exact_argument_name": "value"
  }},
  "reason": "short explanation"
}}

When completely finished:

{{
  "action": "final",
  "args": {{}},
  "reason": "short explanation",
  "final": "concise result including what was actually verified"
}}
"""


def call_model(messages):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 16384
            }
        },
        timeout=600
    )

    response.raise_for_status()
    return response.json()["message"]["content"]


def run_agent(task, messages=None):
    if messages is None:
        messages = [
            {"role": "system", "content": SYSTEM}
        ]

    messages.append({"role": "user", "content": task})

    for step in range(30):

        raw = call_model(messages)

        try:
            decision = json.loads(raw)
        except Exception as exc:
            print("\nMODEL JSON ERROR")
            print(exc)
            print(raw)
            return

        action = decision.get("action")
        args = decision.get("args") or {}

        if action == "final":
            messages.append({
                "role": "assistant",
                "content": raw
            })
            print("\n=== AGENT RESULT ===\n")
            print(decision.get("final", ""))
            return messages

        if action not in REGISTRY:
            messages.append({
                "role": "user",
                "content":
                    f"ERROR: Unknown tool '{action}'. "
                    "Choose only an exact tool from AVAILABLE TOOLS."
            })
            continue

        spec = REGISTRY[action]

        valid, error = validate_args(spec, args)

        if not valid:
            print(f"\nSCHEMA REJECTED: {action}")
            print(error)

            messages.append({
                "role": "assistant",
                "content": raw
            })

            messages.append({
                "role": "user",
                "content":
                    f"TOOL SCHEMA ERROR for {action}: {error}. "
                    f"Required schema: {spec.args}"
            })
            continue

        if spec.destructive:
            print("\n----------------------------------------")
            print("WRITE/EXECUTION TOOL REQUEST")
            print("----------------------------------------")
            print("Tool:", action)
            print("Reason:", decision.get("reason", ""))
            print("Args:", json.dumps(args, indent=2))

            approval = input("\nApprove? [y/N] ").strip().lower()

            if approval not in {"y", "yes"}:
                messages.append({
                    "role": "assistant",
                    "content": raw
                })

                messages.append({
                    "role": "user",
                    "content":
                        "Tool execution was rejected by the safety layer. "
                        "Find a safe alternative or report that approval is required."
                })
                continue

        print(f"\n=== STEP {step + 1} ===")
        print("TOOL:", action)
        print("REASON:", decision.get("reason", ""))
        print("ARGS:", args)

        try:
            result = spec.func(**args)

        except Exception as exc:
            result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"
            }

        print("RESULT:")
        print(result)

        messages.append({
            "role": "assistant",
            "content": raw
        })

        messages.append({
            "role": "user",
            "content":
                "ACTUAL TOOL RESULT:\n" +
                json.dumps(result, default=str)
        })

    print("\nAgent stopped: maximum step count reached.")


if __name__ == "__main__":
    print("================================")
    print(" UnrealAgent Autonomous Runtime ")
    print("================================")
    print("Model:", MODEL)
    print()

    messages = load_session()

    while True:
        task = input("Task > ").strip()

        if task.lower() in {"exit", "quit"}:
            break

        if task:
            run_agent(task, messages)
            save_session(messages)
            save_session(messages)

