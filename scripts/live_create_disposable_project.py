#!/usr/bin/env python3
"""Create a disposable Unreal project for graduation E2E and dump a machine-
readable result JSON. Project name is unique per run to avoid collisions."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAME = "UA_GradAudit_" + time.strftime("%Y%m%d_%H%M%S")
DEST = r"C:\Users\Shadow\Desktop\UnrealAgentGraduation"
OUT = ROOT / "memory" / "grad_disposable_project.json"

from tools.unreal.project_manager import create_project

start = time.time()
result = create_project(project_name=NAME, destination=DEST, template="Blank")
result["elapsed_seconds"] = round(time.time() - start, 1)
result["project_name"] = NAME
OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
print(json.dumps({"project_name": NAME, "ok": result.get("ok"), "uproject_path": result.get("uproject_path"), "elapsed_seconds": result["elapsed_seconds"]}, default=str), flush=True)
sys.exit(0 if result.get("ok") else 1)