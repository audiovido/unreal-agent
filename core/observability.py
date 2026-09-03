"""observability.py — UNREAL CODER structured mission logging (Phase S/T).

Mission logs expose: mission id, project identity, phase, step, tool/
capability, duration, result, warning/error class. They NEVER expose
internal chain-of-thought and NEVER contain raw secrets (redacted through
core.config.redact_text).

One mission produces ONE summary artifact:
    memory/mission_logs/<mission_id>.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import redact, redact_text

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "memory" / "mission_logs"

# Event kinds that are safe for user-facing summaries (no internal reasoning).
PUBLIC_EVENT_KINDS = {
    "mission_started", "interpretation", "plan_built", "step_started",
    "step_completed", "step_failed", "recovery", "visual_iteration",
    "guard_blocked", "mission_finished", "warning",
}


class MissionLogger:
    """Structured, bounded, secret-safe mission event log."""

    def __init__(self, mission_id: str,
                 project: Optional[Dict[str, Any]] = None):
        self.mission_id = str(mission_id)
        self.project = dict(project or {})
        self.events: List[Dict[str, Any]] = []
        self.created_at = time.time()

    # -- event recording -------------------------------------------------------
    def event(self, kind: str, phase: str = "", step: str = "",
              tool: str = "", duration_s: float = 0.0,
              result: str = "", detail: Optional[Dict[str, Any]] = None,
              error_class: str = "") -> Dict[str, Any]:
        entry = {
            "at": round(time.time(), 3),
            "kind": kind,
            "phase": phase,
            "step": step,
            "tool": tool,
            "duration_s": round(float(duration_s or 0.0), 3),
            "result": redact_text(result)[:200],
            "error_class": error_class,
        }
        if detail:
            entry["detail"] = redact(detail)
        self.events.append(entry)
        # Bounded in-memory history (artifact keeps everything).
        if len(self.events) > 2000:
            self.events = self.events[-1500:]
        return entry

    def warning(self, message: str, detail: Optional[Dict[str, Any]] = None):
        return self.event("warning", result=message, detail=detail)

    # -- persistence -----------------------------------------------------------
    def save(self) -> Path:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{self.mission_id}.json"
        artifact = self.summary_artifact()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        tmp.replace(path)
        return path

    # -- user-facing contract (Phase T) ---------------------------------------
    def summary_artifact(self) -> Dict[str, Any]:
        """The ONE mission summary artifact: STATUS / UNDERSTOOD / DID /
        RESULT / EVIDENCE / WARNINGS / REMAINING — no raw internal logs."""
        steps = [e for e in self.events
                 if e["kind"] in ("step_completed", "step_failed")]
        completed = [e for e in steps if e["kind"] == "step_completed"]
        failed = [e for e in steps if e["kind"] == "step_failed"]
        tools = sorted({e["tool"] for e in steps if e.get("tool")})
        duration = round(time.time() - self.created_at, 1)
        warnings = [e["result"] for e in self.events if e["kind"] == "warning"]
        guard_blocks = [
            e for e in self.events if e["kind"] == "guard_blocked"]
        return {
            "mission_id": self.mission_id,
            "project": dict(self.project),
            "duration_s": duration,
            "steps_total": len(steps),
            "steps_completed": len(completed),
            "steps_failed": len(failed),
            "tools_used": tools,
            "warnings": warnings[:20],
            "guard_blocks": [e["result"] for e in guard_blocks][:10],
            # Public event stream only — internal reasoning never enters.
            "events": [e for e in self.events
                       if e["kind"] in PUBLIC_EVENT_KINDS][-100:],
        }


def user_result_contract(
    state: Any,
    log: Optional[MissionLogger] = None,
) -> Dict[str, Any]:
    """Phase T: the simple user-facing result.

    STATUS / WHAT I UNDERSTOOD / WHAT I DID / RESULT / EVIDENCE / WARNINGS /
    REMAINING ISSUES. No raw internal logs, no chain-of-thought.
    """
    plan = getattr(state, "plan", None) or {}
    intent = getattr(state, "intent", None) or {}
    steps = plan.get("steps") or []
    completed = list(getattr(state, "completed_step_ids", []) or [])
    tools = sorted({s.get("preferred_tool") for s in steps
                    if s.get("preferred_tool") and s.get("step_id") in set(completed)})
    deliverables = intent.get("deliverables") or []
    domains = intent.get("domains") or []

    understood = f"You asked to {(_norm_prompt(getattr(state, 'prompt', '')) or 'work on your Unreal project')}."
    if domains:
        understood += f" I read this as {', '.join(domains)} work"
        if deliverables:
            understood += f" delivering: {', '.join(str(d) for d in deliverables[:4])}"
        understood += "."

    did = (f"Executed {len(completed)} of {len(steps)} planned steps"
           + (f" using {', '.join(str(t) for t in tools[:6])}" if tools else "")
           + ".")
    warnings = list(getattr(state, "warnings", []) or [])
    remaining = list(getattr(state, "remaining_issues", []) or [])
    blockers = list(getattr(state, "blockers", []) or [])

    return {
        "status": getattr(state, "verdict", None) or "PENDING",
        "what_i_understood": understood,
        "what_i_did": did,
        "result": getattr(state, "why", ""),
        "evidence": list(getattr(state, "evidence", []) or [])[:10],
        "warnings": warnings[:10],
        "remaining_issues": (remaining + blockers)[:10],
        "mission_id": getattr(state, "mission_id", ""),
    }


def _norm_prompt(prompt: str) -> str:
    text = str(prompt or "").strip().rstrip(".")
    return text[:1].lower() + text[1:] if text else ""
