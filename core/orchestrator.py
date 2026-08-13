import json
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from tools.unreal.project_manager import discover_projects, inspect_project, open_project
from tools.system.tool_runner import read_text_file, write_text_file, run_powershell, unreal_status

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5-coder:14b"

TOOLS = {
    "discover_projects": discover_projects,
    "inspect_project": inspect_project,
    "open_project": open_project,
    "read_text_file": read_text_file,
    "write_text_file": write_text_file,
    "run_powershell": run_powershell,
    "unreal_status": unreal_status,
}

SYSTEM = """
You are an autonomous Unreal Engine 5.8 agent.

You can inspect projects, read/write files, run PowerShell commands,
and launch Unreal projects using tools.

Always think in this loop:
1. Understand the task.
2. Inspect before modifying.
3. Choose the minimum required tool.
4. Execute.
5. Verify result.
6. Continue until task is complete.

Never claim success without evidence.

Respond ONLY as JSON in this format:

{
  "thought": "short reasoning",
  "action": "tool_name or final",
  "args": {},
  "final": ""
}

Available tools:`discover_projects(args: none)`ninspect_project(uproject_path: string)
open_project
read_text_file
write_text_file
run_powershell
unreal_status
"""

def call_model(messages):
    r = requests.post(
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
    r.raise_for_status()
    return r.json()["message"]["content"]

def run_agent(task):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task}
    ]

    for step in range(20):
        raw = call_model(messages)

        try:
            decision = json.loads(raw)
        except Exception:
            print("MODEL JSON ERROR:")
            print(raw)
            return

        action = decision.get("action")

        if action == "final":
            print("\nAGENT RESULT:\n")
            print(decision.get("final", ""))
            return

        if action not in TOOLS:
            print("UNKNOWN TOOL:", action)
            return

        args = decision.get("args", {})

        print(f"\nSTEP {step + 1}")
        print("TOOL:", action)
        print("ARGS:", args)

        try:
            result = TOOLS[action](**args)
        except TypeError:
            result = TOOLS[action]()

        print("RESULT:")
        print(result)

        messages.append({
            "role": "assistant",
            "content": raw
        })

        messages.append({
            "role": "user",
            "content": f"Tool result:\n{json.dumps(result, default=str)}"
        })

    print("Stopped after maximum steps.")

if __name__ == "__main__":
    print("=== Unreal Autonomous Agent ===")
    task = input("Task > ")
    run_agent(task)


