import requests
from rich.console import Console

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5-coder:14b"

console = Console()

SYSTEM_PROMPT = """
You are UnrealAgent, a local autonomous AI specialized exclusively in Unreal Engine.

Your responsibilities:
- Unreal Engine C++ development
- Blueprint architecture and debugging
- UMG/UI systems
- Gameplay systems
- Editor automation
- Asset and project inspection
- Build diagnostics
- Test planning
- Safe code changes
- Step-by-step execution planning

Rules:
- Never pretend a command succeeded unless you have evidence.
- Prefer reversible changes.
- Explain destructive actions before execution.
- Keep Unreal-specific answers precise and production-oriented.
- When writing code, target Unreal Engine 5.8 unless told otherwise.
"""

def ask_agent(user_message: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 16384
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()

    data = response.json()
    return data["message"]["content"]

def main():
    console.print("[bold]UnrealAgent Local[/bold]")
    console.print("Model: qwen2.5-coder:14b")
    console.print("Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You > ").strip()

            if user_input.lower() in {"exit", "quit"}:
                break

            if not user_input:
                continue

            console.print("\n[bold cyan]Agent >[/bold cyan]")
            answer = ask_agent(user_input)
            console.print(answer)
            console.print()

        except KeyboardInterrupt:
            console.print("\nExiting...")
            break

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

if __name__ == "__main__":
    main()
