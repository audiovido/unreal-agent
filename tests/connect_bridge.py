from pathlib import Path

path = Path(r".\core\orchestrator.py")
text = path.read_text(encoding="utf-8-sig")

start = text.index("import json")
system_pos = text.index("SYSTEM = f")

prefix = '''import json
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

'''

text = prefix + text[system_pos:]
path.write_text(text, encoding="utf-8")

print("orchestrator bridge connected")
