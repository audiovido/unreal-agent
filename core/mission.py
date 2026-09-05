"""mission.py — UNREAL CODER mission engine.

A Mission is the universal unit of work: one natural-language request ->
interpreted intent -> requirement spec -> capability-selected plan -> executed
through the EXISTING tool registry/executor -> validated (technical + visual)
-> evidence -> terminal verdict.

This module owns the mission-level concerns the step executor does not:
  - checkpoint / resume (long tasks survive interruption)
  - loop/runaway protection (repeated commands, unchanged errors, stagnation)
  - error classification -> targeted recovery policy
  - mission observability states (interpreting/planning/executing/...)
  - the controlled visual acceptance loop wrapper (bounded)

Execution of individual steps is delegated to an injected executor callable
(the existing api executor / dispatcher). This keeps one implementation of
the actual tool-running machinery.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.capability_registry import CapabilityRegistry
from core.mission_policy import (
    MODE_READ_ONLY,
    MODE_MUTATING,
    plan_steps_summary,
    policy_block_payload,
)
from core.universal_intent import UniversalIntent, expand_requirements, interpret_intent
from core.universal_planner import MissionPlan, UniversalPlanner

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DIR = ROOT / "memory" / "checkpoints" / "unreal_coder"

# ---------------------------------------------------------------------------
# Error classification -> targeted recovery policy
# ---------------------------------------------------------------------------

ERROR_CLASSES = [
    # Ordered: most specific markers first ("blueprint compile" must win over
    # generic "compile"; "pie begin play" must win over generic "pie"/"editor").
    ("WRONG_PROJECT", ("wrong project", "expected_project",
                       "project identity mismatch", "different project")),
    ("BLUEPRINT", ("blueprint compile", "blueprint graph", "kismet",
                   "blueprint error", "blueprint failed")),
    ("CODE_COMPILE", ("compile", "error building", "c++ ", "cl.exe",
                      "link error")),
    ("PIE", ("pie", "play in editor", "begin play", "end play")),
    ("EDITOR_STATE", ("editor busy", "transaction", "garbage collect",
                      "editor not ready")),
    ("BRIDGE", ("bridge", "connection", "refused", "empty bridge response",
                "timed out")),
    ("ASSET_IMPORT", ("import", "fbx", "gltf", "asset not found",
                      "failed to load asset")),
    ("MATERIAL_GRAPH", ("material graph", "material expression")),
    ("VISUAL", ("capture", "screenshot", "visual", "score")),
    ("MEDIA", ("media", "playback", "video")),
    ("NETWORK", ("network", "replication", "session")),
    ("PERFORMANCE", ("fps", "frame time", "draw calls")),
    ("EXTERNAL_TOOL", ("blender", "external", "executable")),
    ("MODEL", ("ollama", "model", "llm")),
    ("AUTH", ("permission", "access denied", "unauthorized")),
    ("FILESYSTEM", ("file not found", "no such file",
                    "path does not exist")),
    ("UNREAL_API_VERSION", ("deprecated", "no attribute",
                            "has no attribute", "undefined symbol")),
]


def classify_error(error: str) -> str:
    text = str(error or "").lower()
    for code, markers in ERROR_CLASSES:
        if any(m in text for m in markers):
            return code
    return "UNKNOWN"


# Targeted recovery: what the mission engine tries per class, bounded.
RECOVERY_POLICY = {
    "BRIDGE": ["reconnect_bridge", "resolve_project", "stop"],
    "WRONG_PROJECT": ["resolve_project", "stop"],
    "CODE_COMPILE": ["fix_compile", "stop"],
    "BLUEPRINT": ["recompile", "stop"],
    "ASSET_IMPORT": ["reintake", "blender_route", "stop"],
    "EXTERNAL_TOOL": ["retry_tool", "stop"],
    "FILESYSTEM": ["resolve_project", "stop"],
    "EDITOR_STATE": ["wait_editor_ready", "stop"],
    "VISUAL": ["visual_repair", "stop"],
    "PIE": ["stop_pie_then_retry", "stop"],
    "UNREAL_API_VERSION": ["skip_step", "stop"],
}


@dataclass
class MissionState:
    """Full durable mission state (checkpoint payload)."""

    mission_id: str
    prompt: str
    status: str = "interpreting"   # interpreting|planning|executing|validating|repairing|complete|failed|blocked
    intent: Dict[str, Any] = field(default_factory=dict)
    requirements: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    completed_step_ids: List[str] = field(default_factory=list)
    step_results: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    remaining_issues: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    recovery_attempts: Dict[str, int] = field(default_factory=dict)
    loop_events: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    verdict: Optional[str] = None          # PASS / PARTIAL / FAIL / BLOCKED
    why: str = ""
    read_only: bool = False                # canonical execution mode (policy)
    policy: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "prompt": self.prompt,
            "status": self.status,
            "intent": dict(self.intent),
            "requirements": dict(self.requirements),
            "plan": dict(self.plan),
            "completed_step_ids": list(self.completed_step_ids),
            "step_results": dict(self.step_results),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "remaining_issues": list(self.remaining_issues),
            "blockers": list(self.blockers),
            "recovery_attempts": dict(self.recovery_attempts),
            "loop_events": list(self.loop_events)[-50:],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "verdict": self.verdict,
            "why": self.why,
            "read_only": self.read_only,
            "policy": dict(self.policy),
        }

    # -- persistence --------------------------------------------------------
    def save(self) -> None:
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        path = CHECKPOINT_DIR / f"{self.mission_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False,
                       default=str),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def load(cls, mission_id: str) -> Optional["MissionState"]:
        path = CHECKPOINT_DIR / f"{mission_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        state = cls(mission_id=data.get("mission_id", mission_id),
                    prompt=data.get("prompt", ""))
        for key, value in data.items():
            if hasattr(state, key):
                setattr(state, key, value)
        return state

    @classmethod
    def latest(cls) -> Optional["MissionState"]:
        """Newest checkpoint (for resume), or None."""
        if not CHECKPOINT_DIR.exists():
            return None
        newest = None
        newest_mtime = -1.0
        for path in CHECKPOINT_DIR.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest = path
        if newest is None:
            return None
        try:
            data = json.loads(newest.read_text(encoding="utf-8"))
        except Exception:
            return None
        return cls.load(data.get("mission_id", ""))


# ---------------------------------------------------------------------------
# Loop / runaway protection
# ---------------------------------------------------------------------------

MAX_RECOVERY_PER_CLASS = 3
MAX_VISUAL_ITERATIONS = 3
MAX_IDENTICAL_EVENTS = 2


class LoopProtector:
    """Detects repeated identical work and stagnation; forces strategy change
    or stop. Nothing here retries forever."""

    def __init__(self):
        self.signatures: Dict[str, int] = {}
        self.no_progress = 0

    def observe(self, signature: str) -> str:
        """Returns 'ok' | 'repeat' | 'stop'."""
        count = self.signatures.get(signature, 0) + 1
        self.signatures[signature] = count
        if count > MAX_IDENTICAL_EVENTS:
            return "stop"
        if count > 1:
            return "repeat"
        return "ok"

    def progress(self, moved: bool) -> bool:
        """True while allowed to continue."""
        self.no_progress = 0 if moved else self.no_progress + 1
        return self.no_progress < 3


# ---------------------------------------------------------------------------
# Mission engine
# ---------------------------------------------------------------------------

class MissionEngine:
    """Runs one universal mission end-to-end using injected executors.

    Dependencies are injected to keep this module testable and decoupled:
      tool_registry: live ToolSpec dict (availability source)
      capabilities:  CapabilityRegistry bound to tool_registry
      dispatch:      (step_dict) -> result dict   [existing executor]
      capture:       () -> evidence dict          [visual capture]
      evaluate:      (evidence) -> dict           [visual acceptance]
      repair:        (defects) -> change note     [visual loop action]
    """

    def __init__(
        self,
        tool_registry: Dict[str, Any],
        capabilities: CapabilityRegistry,
        dispatch: Callable[[Dict[str, Any]], Dict[str, Any]],
        capture: Optional[Callable[[], Dict[str, Any]]] = None,
        evaluate: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        repair: Optional[Callable[[Dict[str, Any]], str]] = None,
    ):
        self.tool_registry = tool_registry
        self.capabilities = capabilities
        self.dispatch = dispatch
        self.capture = capture
        self.evaluate = evaluate
        self.repair = repair
        self.planner = UniversalPlanner(capabilities)

    # -- lifecycle -----------------------------------------------------------
    def start_mission(self, prompt: str, mission_id: Optional[str] = None) -> MissionState:
        state = MissionState(
            mission_id=mission_id or f"mission_{uuid.uuid4().hex[:12]}",
            prompt=str(prompt or ""),
        )
        state.started_at = time.time()
        state.status = "interpreting"
        state.save()
        return state

    def interpret(self, state: MissionState) -> MissionState:
        intent = interpret_intent(state.prompt)
        requirements = expand_requirements(intent)
        state.intent = intent.to_dict()
        state.requirements = requirements.to_dict()
        state.status = "planning"
        state.save()
        return state

    def plan(self, state: MissionState) -> MissionState:
        intent = interpret_intent(state.prompt)
        requirements = expand_requirements(intent)
        project_context = self._resolve_project_context()
        mission_plan = self.planner.build_plan(
            intent, requirements, project_context)
        state.plan = mission_plan.to_dict()
        state.warnings = list(mission_plan.warnings)
        state.status = "executing"
        state.save()
        return state

    # -- execution ------------------------------------------------------------
    def run(self, state: MissionState, max_steps: int = 60) -> MissionState:
        """Execute pending plan steps through the existing dispatcher with
        loop protection, recovery and checkpointing."""
        state.status = "executing"
        state.save()
        protector = LoopProtector()
        steps = (state.plan.get("steps") or [])
        # Skip already completed (resume semantics).
        pending = [s for s in steps
                   if s.get("step_id") not in set(state.completed_step_ids)]
        executed = 0
        for step in pending:
            if executed >= max_steps:
                state.remaining_issues.append(
                    "Mission step budget reached; checkpoint saved for "
                    "continuation.")
                state.save()
                return state
            step_id = step.get("step_id")
            signature = f"{step.get('preferred_tool')}:{json.dumps(step.get('parameters') or {}, sort_keys=True, default=str)}"
            verdict_sig = protector.observe(signature)
            if verdict_sig == "stop":
                state.loop_events.append({
                    "step_id": step_id, "event": "loop_protection_stop",
                    "signature": signature,
                })
                state.blockers.append(
                    "LOOP_PROTECTION: identical step repeated beyond "
                    "threshold; strategy change or manual review required.")
                state.status = "blocked"
                state.verdict = "BLOCKED"
                state.why = "Runaway loop detected and stopped."
                state.finished_at = time.time()
                state.save()
                return state

            result = self._dispatch_with_recovery(state, step)
            state.step_results[step_id] = result
            ok = bool(result.get("ok"))
            if ok:
                state.completed_step_ids.append(step_id)
                moved = protector.progress(True)
            else:
                moved = protector.progress(False)
                if not moved:
                    state.remaining_issues.append(
                        f"No progress after failures at {step_id}; "
                        "checkpoint saved.")
                    state.status = "failed"
                    state.verdict = "FAIL"
                    state.why = ("Repeated step failures with no recovery "
                                 "progress; stopped to avoid burning budget.")
                    state.finished_at = time.time()
                    state.save()
                    return state
            executed += 1
            state.updated_at = time.time()
            state.save()

        state.status = "validating"
        state.save()
        return self.validate(state)

    # -- recovery ----------------------------------------------------------
    def _dispatch_with_recovery(
        self, state: MissionState, step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Dispatch once per recovery action from the class policy.

        The existing executor already owns transport-level retries; this loop
        exists to stop runaway classes quickly, not to retry endlessly.
        """
        result: Dict[str, Any] = {}
        for attempt in range(1, MAX_RECOVERY_PER_CLASS + 1):
            result = self.dispatch(step) or {"ok": False, "error": "no result"}
            if bool(result.get("ok")):
                return result
            error_text = str(
                result.get("error") or result.get("message") or "")
            error_class = classify_error(error_text)
            state.recovery_attempts[error_class] = (
                state.recovery_attempts.get(error_class, 0) + 1)
            policy = RECOVERY_POLICY.get(error_class, ["stop"])
            action = policy[min(attempt - 1, len(policy) - 1)]
            state.loop_events.append({
                "step_id": step.get("step_id"), "error_class": error_class,
                "recovery": action, "attempt": attempt,
                "error": error_text[:200],
            })
            if action in {"stop", "skip_step"}:
                return result
            time.sleep(0.05)
        state.remaining_issues.append(
            f"Recovery budget exhausted at {step.get('step_id')}: "
            f"{str(result.get('error') or '')[:200]}")
        return result

    # -- visual validation ---------------------------------------------------
    def validate(self, state: MissionState) -> MissionState:
        """Technical + visual validation with bounded repair loop."""
        technical_ok = self._technical_gate(state)
        visual = self._visual_loop(state)
        state.evidence.extend(visual.get("evidence", []))
        if visual.get("defects"):
            state.remaining_issues.extend(
                f"VISUAL:{d}" for d in visual["defects"])
        floor = (state.plan.get("visual_gate") or {}).get("score_floor", 6.0)
        score = float(visual.get("score", 0.0))
        gate_needed = bool((state.plan.get("visual_gate") or {}).get("enabled"))
        diagnostic = bool((state.intent or {}).get("diagnostic"))
        if diagnostic:
            # Diagnostics only PASS with real probe evidence;
            # get_evidence must never come back empty for them.
            self._emit_diagnostic_evidence(state)

        if state.blockers:
            state.status = "blocked"
            state.verdict = "BLOCKED"
            state.why = "; ".join(state.blockers)
        elif diagnostic:
            diagnosis = self._diagnostic_verdict(state, technical_ok)
            state.status = diagnosis["status"]
            state.verdict = diagnosis["verdict"]
            state.why = diagnosis["why"]
        elif technical_ok and (not gate_needed or score >= floor):
            if not state.completed_step_ids:
                # 0 executed steps + no work can never become verified PASS
                # (e.g. an empty chat-mode plan that reached execution).
                state.status = "failed"
                state.verdict = "FAIL"
                state.why = (
                    "Mission executed 0 steps; PASS requires real verified "
                    "work (0-step empty-plan PASS blocked).")
            else:
                state.status = "complete"
                state.verdict = "PASS"
                state.why = (
                    f"All {len(state.completed_step_ids)} steps verified; visual "
                    f"score {score:.2f} >= floor {floor:.2f}."
                    if gate_needed else
                    f"All {len(state.completed_step_ids)} steps verified.")
        elif technical_ok and gate_needed:
            # A visual rejection is deliberately resumable: technical work is
            # preserved while a later repaired capture can be revalidated.
            state.status = "repairing"
            state.verdict = "PARTIAL"
            state.why = (
                f"Technical work verified but visual score {score:.2f} below "
                f"floor {floor:.2f} after bounded repair; remaining defects: "
                f"{visual.get('defects', [])}.")
        else:
            state.status = "failed"
            state.verdict = "FAIL"
            state.why = "Technical validation failed; see remaining_issues."
        state.finished_at = time.time()
        state.save()
        return state

    def _technical_gate(self, state: MissionState) -> bool:
        steps = state.plan.get("steps") or []
        required = [
            s.get("step_id") for s in steps
            if str(s.get("phase", "")).upper()
            not in {"VISUAL", "ANSWER"}
        ]
        return all(sid in set(state.completed_step_ids) for sid in required)

    def _emit_diagnostic_evidence(self, state: MissionState) -> None:
        """Append one real evidence entry per completed diagnostic probe.

        A status/health mission must never finish with empty evidence: every
        INSPECT probe that actually executed contributes its real result (and
        a real report path when the tool wrote one) to `state.evidence`, so
        the gateway's get_evidence returns non-empty, real evidence.
        """
        steps = state.plan.get("steps") or []
        completed = set(state.completed_step_ids)
        existing = {
            ev.get("step_id")
            for ev in state.evidence
            if ev.get("kind") == "diagnostic_probe"
        }
        for step in steps:
            sid = step.get("step_id")
            if sid in existing or sid not in completed:
                continue
            if str(step.get("phase", "")).upper() != "INSPECT":
                continue
            result = state.step_results.get(sid) or {}
            inner = (result.get("result")
                     if isinstance(result.get("result"), dict) else {})
            entry = {
                "kind": "diagnostic_probe",
                "step_id": sid,
                "probe": step.get("intent"),
                "tool": step.get("preferred_tool"),
                "ok": bool(result.get("ok") or inner.get("ok")),
                "detail": str(result.get("error")
                              or inner.get("error") or "")[:400],
            }
            path = (result.get("path") or result.get("resource_path")
                    or inner.get("path") or inner.get("resource_path"))
            if path:
                entry["path"] = str(path)
            state.evidence.append(entry)

    def _diagnostic_verdict(
        self, state: MissionState, technical_ok: bool,
    ) -> Dict[str, str]:
        """Diagnostic missions PASS only after real probes ran AND passed.

        Enforces the invariant that a status/health mission can never report
        verified PASS from 0 executed steps / no evidence: the backend health
        probe and the Unreal bridge readiness probe must both be planned,
        executed and pass, the technical gate must hold, and evidence must
        exist.
        """
        steps = state.plan.get("steps") or []
        results = state.step_results
        problems: List[str] = []
        probe_steps = [
            s for s in steps
            if s.get("intent") in ("backend_health", "bridge_health")
        ]
        if len(probe_steps) < 2:
            problems.append(
                "required backend/bridge probes were not planned")
        for step in probe_steps:
            res = results.get(step.get("step_id")) or {}
            if not res.get("ok"):
                problems.append(
                    f"{step.get('intent')} probe did not pass: "
                    f"{str(res.get('error') or '')[:160]}")
        if not technical_ok:
            problems.append(
                "not all planned diagnostic steps were verified")
        if not state.evidence:
            problems.append("no diagnostic evidence was emitted")
        if problems:
            return {
                "status": "failed", "verdict": "FAIL",
                "why": "Diagnostic verification incomplete: "
                        + "; ".join(problems),
            }
        return {
            "status": "complete", "verdict": "PASS",
            "why": (
                "Backend and Unreal bridge probes executed and passed "
                f"({len(state.completed_step_ids)} steps) with real "
                f"evidence ({len(state.evidence)} item(s))."),
        }

    def _visual_loop(self, state: MissionState) -> Dict[str, Any]:
        """Bounded EXECUTE->CAPTURE->EVALUATE->REPAIR loop via injected
        callables (the existing visual machinery)."""
        gate = state.plan.get("visual_gate") or {}
        if not gate.get("enabled") or self.capture is None:
            return {"score": 0.0, "defects": [], "evidence": [],
                    "iterations": 0}
        evidence = []
        best_score = 0.0
        best_defects: List[str] = []
        previous_scores: List[float] = []
        for iteration in range(MAX_VISUAL_ITERATIONS):
            captured = self.capture()
            evidence.append(captured)
            review = (self.evaluate or (lambda c: {}))(captured)
            score = float(review.get("score") or 0.0)
            defects = list(review.get("defects") or [])
            if score > best_score:
                best_score, best_defects = score, defects
            if score >= float(gate.get("score_floor", 6.0)):
                return {"score": score, "defects": defects,
                        "evidence": evidence, "iterations": iteration + 1,
                        "verdict": "PASS"}
            if not defects or self.repair is None:
                return {"score": score, "defects": defects,
                        "evidence": evidence, "iterations": iteration + 1,
                        "verdict": "FAIL"}
            previous_scores.append(score)
            # Stagnation: identical scores twice -> stop repairing.
            if (len(previous_scores) >= 2
                    and previous_scores[-1] == previous_scores[-2]):
                return {"score": score, "defects": defects,
                        "evidence": evidence, "iterations": iteration + 1,
                        "verdict": "STAGNANT"}
            repair_result = self.repair(defects)
            # A repair policy name is not a repair.  Production adapters
            # return a structured, read-back-verified result; legacy tests
            # may continue to return a descriptive string.
            if isinstance(repair_result, dict) and not repair_result.get("ok"):
                return {"score": score, "defects": defects,
                        "evidence": evidence, "iterations": iteration + 1,
                        "verdict": "REPAIR_UNAVAILABLE",
                        "repair_error": str(repair_result.get("error") or "")}
        return {"score": best_score, "defects": best_defects,
                "evidence": evidence, "iterations": MAX_VISUAL_ITERATIONS,
                "verdict": "BUDGET"}

    def _resolve_project_context(self) -> Dict[str, Any]:
        try:
            from tools.unreal.project_context import load_active_context
            ctx = load_active_context() or {}
            return {k: v for k, v in ctx.items() if not k.startswith("_")}
        except Exception:
            return {}

    _reproject = None


# ---------------------------------------------------------------------------
# Public response shaping (API contract)
# ---------------------------------------------------------------------------

def mission_response(state: MissionState) -> Dict[str, Any]:
    """Canonical external response: concise, no internal chain-of-thought."""
    steps = (state.plan.get("steps") or [])
    return {
        "mission_id": state.mission_id,
        "status": state.status,
        "verdict": state.verdict,
        "why": state.why,
        "interpretation": {
            "domains": (state.intent or {}).get("domains"),
            "primary_domain": (state.intent or {}).get("primary_domain"),
            "quality": (state.intent or {}).get("quality"),
            "deliverables": (state.intent or {}).get("deliverables"),
        },
        "plan": {
            "phases": (state.plan or {}).get("phases"),
            "selected_capabilities": (state.plan or {}).get(
                "selected_capabilities"),
            "visual_gate": (state.plan or {}).get("visual_gate"),
            "steps": plan_steps_summary(state),
        },
        "policy": policy_block_payload(state, terminal=(
            state.status in {"complete", "failed", "blocked"}
            and bool(state.policy)
            and (state.policy or {}).get("verdict") == "PLAN_REJECTED")),
        "completed_work": {
            "steps_total": len(steps),
            "steps_completed": len(state.completed_step_ids),
            "step_ids": list(state.completed_step_ids),
        },
        "evidence": list(state.evidence),
        "warnings": list(state.warnings),
        "remaining_issues": list(state.remaining_issues),
        "artifacts": [
            r for r in (
                state.step_results.get(sid, {}) for sid in state.completed_step_ids
            ) if isinstance(r, dict) and (r.get("resource_path") or r.get("path"))
        ],
        "resumable": state.status in {"executing", "validating", "repairing",
                                      "blocked", "failed"}
                     and (state.policy or {}).get("verdict") != "PLAN_REJECTED",
    }


def resume_latest_mission() -> Optional[MissionState]:
    return MissionState.latest()
