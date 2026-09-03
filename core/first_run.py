"""first_run.py — first-run backend/state foundation (Lane B, Part 8).

Produces and persists the structured WELCOME → ENVIRONMENT CHECK →
UNREAL DETECTED → CHOOSE PROJECT → READY progression as DATA only.
Worker A owns any UI; this module only offers the state/stage API plus a
JSON snapshot under config/first_run.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import app_config, env_doctor

STAGES = ["welcome", "environment_check", "unreal_detected",
          "choose_project", "ready"]

STAGE_LABELS = {
    "welcome": "Welcome to Unreal Agent",
    "environment_check": "Checking your environment…",
    "unreal_detected": "Unreal Editor detected",
    "choose_project": "Choose a project",
    "ready": "Ready to work",
}


def _stage(name: str, status: str, detail: str) -> Dict[str, Any]:
    return {"stage": name, "status": status, "detail": detail,
            "at": round(time.time(), 3)}


def build_progression(doctor: Optional[Dict[str, Any]] = None,
                      recent_project: Optional[str] = None,
                      unreal_build: Optional[Dict[str, Any]] = None,
                      file_path: Optional[Path] = None) -> Dict[str, Any]:
    """Compute the five-stage first-run snapshot from real inputs.

    doctor          -> env_doctor.run() result (or None to skip live checks)
    recent_project  -> configured/selected .uproject path
    unreal_build    -> detected build dict {label, path, editor_exe} or None
    """
    doctor = doctor or {"overall": "PASS", "user_error": "no doctor run",
                        "failures": [], "warnings": []}
    stages: List[Dict[str, Any]] = []
    stages.append(_stage("welcome", "ok", "Unreal Agent is starting"))
    env_status = "ok" if doctor.get("overall") != "FAIL" else "blocked"
    stages.append(_stage("environment_check", env_status,
                         doctor.get("user_error") or doctor.get("summary", "")))
    if unreal_build and unreal_build.get("editor_exe"):
        stages.append(_stage("unreal_detected", "ok",
                             f"{unreal_build.get('label')} at "
                             f"{unreal_build.get('editor_exe')}"))
    else:
        stages.append(_stage("unreal_detected", "warn",
                             "no installed build found — connect to an "
                             "already-open editor instead"))
    proj_ok = bool(recent_project and Path(str(recent_project)).exists())
    stages.append(_stage("choose_project", "ok" if proj_ok else "warn",
                         recent_project or "no project selected yet"))
    ready = env_status == "ok" and proj_ok
    stages.append(_stage("ready", "ok" if ready else "pending",
                         "Ready" if ready else "waiting for a project"))

    snapshot = {
        "schema": "ua.first_run.v1",
        "progression": stages,
        "ready": ready,
        "doctor": {"overall": doctor.get("overall"),
                   "summary": doctor.get("summary")},
        "project": recent_project,
        "unreal_build": unreal_build,
        "created_at": round(time.time(), 3),
    }
    if file_path is not None:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(json.dumps(snapshot, indent=2,
                                            default=str), encoding="utf-8")
        except Exception:
            pass
    return snapshot


def load_snapshot(file_path: Optional[Path] = None) -> Dict[str, Any]:
    path = file_path or Path(app_config.FIRST_RUN_FILE)
    if not path.exists():
        return {"schema": "ua.first_run.v1", "progression": [],
                "ready": False, "doctor": {}, "project": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": "ua.first_run.v1", "progression": [],
                "ready": False, "doctor": {}, "project": None}


def stage_result(snapshot: Dict[str, Any], stage: str) -> Optional[Dict[str, Any]]:
    for s in snapshot.get("progression", []):
        if s.get("stage") == stage:
            return s
    return None
