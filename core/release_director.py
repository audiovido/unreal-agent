"""release_director.py — deterministic decision logic for the autonomous
Visual Director graduation loop.

The loop itself (capture -> measure -> diagnose -> fix -> recapture ->
accept) is the existing AutonomousVisualLoop in core.visual_loop.  This
module owns the *decisions* that loop needs in release mode, kept pure so
they are regression-testable offline with no editor, no network:

  release_accept     terminal release gate  (>= floor, no blocking defects)
  detect_defects     ranked defect list (reuses the loop's exact derivation)
  plan_fixes         ranked visual problems + highest-impact fixes + why
  parse_capture_diag fresh/visible capture verdict from the native diag
  decide_rollback    when to revert the previous change before retrying
  dolly_factor       bounded camera-distance change for framing defects
  light_factor       bounded light-intensity change for exposure defects

These functions deliberately encode NO scorer thresholds of their own: they
read the budgets/bands from the same frozen measurement constants the loop
and scorer use, and they only ever return bounded change factors.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.visual_loop import AutonomousVisualLoop  # reuse exact defect logic

# Release acceptance floor and coverage band used for the terminal gate.
# The band is chosen inside the frozen scorer's framing band [0.25, 0.60]
# AND inside the loop defect band [0.22, 0.52], so an accepted frame cannot
# carry a live SUBJECT_TOO_LARGE/SMALL defect.
RELEASE_FLOOR = 8.5
RELEASE_COVERAGE_BAND = (0.25, 0.50)
ROLL_MAX_DEG = 3.5

# Bounded change factors for the generic fix executor (never random).
DOLLY_FACTOR_RANGE = (0.55, 1.90)
LIGHT_FACTOR_RANGE = (0.30, 3.00)


def release_accept(
    metrics: Any,
    score: Any,
    *,
    floor: float = RELEASE_FLOOR,
    coverage_band: Tuple[float, float] = RELEASE_COVERAGE_BAND,
    require_ui: bool = False,
    environment_required: bool = True,
    environment_verified: bool = False,
) -> bool:
    """Terminal release acceptance: overall score >= floor AND no blocking
    defect (no measured issues, no head clip, no roll, no bands/stale, no
    stale capture) AND subject coverage inside the release band.

    Strictly additive over the production evaluate contract: it never
    weakens the scorer or the acceptance rules — it is only asked about
    frames whose deterministic issues list is already empty.
    """
    if metrics is None or score is None:
        return False
    if not getattr(metrics, "ok", False):
        return False
    if float(getattr(score, "overall", 0.0) or 0.0) < float(floor):
        return False
    issues = list(getattr(metrics, "issues", None) or [])
    # EMPTY_ENVIRONMENT is task-aware: a requested environment is a blocking
    # acceptance defect, while an unrequested contextual backdrop is advisory.
    # All other measured defects retain the canonical blocking behavior.
    if not environment_required or environment_verified:
        issues = [issue for issue in issues if issue != "EMPTY_ENVIRONMENT"]
    if issues:
        return False
    if getattr(metrics, "head_clipped", False):
        return False
    if getattr(metrics, "stale", False) or getattr(metrics, "bands", None):
        return False
    roll = float(getattr(metrics, "roll_deg", 0.0) or 0.0)
    if roll > ROLL_MAX_DEG:
        return False
    cov = float(getattr(metrics, "subject_coverage", -1.0) or -1.0)
    if getattr(metrics, "subject_bbox", None) is not None:
        if not (coverage_band[0] <= cov <= coverage_band[1]):
            return False
    if require_ui and not getattr(metrics, "ui_bbox", None):
        return False
    return True


def _dummy_loop(target: Dict[str, Any]):
    return AutonomousVisualLoop(target or {}, capture=lambda: "",
                                apply=lambda *a, **k: "")


def detect_defects(
    metrics: Any,
    score: Any,
    target: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Ranked blocking/priority defects exactly as the production loop would
    derive them (single source of truth: AutonomousVisualLoop._derive_defects
    and the shared DEFECT_PRIORITY ordering)."""
    loop = _dummy_loop(target or {})
    return list(loop._derive_defects(metrics, score))


def plan_fixes(
    metrics: Any,
    score: Any,
    target: Optional[Dict[str, Any]] = None,
    max_fixes: int = 3,
) -> Dict[str, Any]:
    """Structured diagnosis -> highest-impact fixes with a rationale.

    Returns:
      problems: ranked visual problems (defect, severity, evidence)
      fixes:    top `max_fixes` candidate fix actions with expected impact
      strategy: the action the deterministic loop will try first
    """
    from core.visual_director import DEFECT_ACTIONS
    from core.visual_loop import STRATEGY_CHAINS

    defects = detect_defects(metrics, score, target)
    problems = []
    for d in defects:
        evidence = _defect_evidence(d, metrics)
        problems.append({"defect": d, "severity": _severity(d),
                         "evidence": evidence})
    fixes = []
    for d in defects[:max_fixes]:
        chain = STRATEGY_CHAINS.get(d, [DEFECT_ACTIONS.get(d, d)])
        for action in chain[:max_fixes]:
            fixes.append({
                "defect": d,
                "action": action,
                "expected_impact": _impact(action),
                "why": _why(action, d, metrics),
            })
    return {
        "problems": problems,
        "fixes": fixes,
        "strategy": fixes[0]["action"] if fixes else None,
        "defects": defects,
        "score": round(float(getattr(score, "overall", 0.0) or 0.0), 2),
        "coverage": getattr(metrics, "subject_coverage", None),
        "head_clipped": getattr(metrics, "head_clipped", False),
        "roll_deg": getattr(metrics, "roll_deg", 0.0),
        "ui_coverage": getattr(metrics, "ui_screen_coverage", None),
        "pct_white": getattr(metrics, "pct_white", None),
        "pct_black": getattr(metrics, "pct_black", None),
    }


def _severity(defect: str) -> str:
    return {"HEAD_CROPPED": "high", "CAMERA_ROLL": "medium",
            "WHITE_CLIPPING": "high", "BLACK_CLIPPING": "high",
            "SUBJECT_TOO_LARGE": "medium", "SUBJECT_TOO_SMALL": "medium",
            "STALE_CAPTURE": "blocker", "BLACK_BAND": "blocker",
            "SUBJECT_TOO_DARK": "medium"}.get(defect, "medium")


def _defect_evidence(defect: str, metrics: Any) -> str:
    row = {
        "HEAD_CROPPED": f"subject bbox {getattr(metrics, 'subject_bbox', None)}"
                        f" reaches the top margin",
        "SUBJECT_TOO_LARGE":
            f"subject coverage {getattr(metrics, 'subject_coverage', None)}"
            f" above the target band",
        "SUBJECT_TOO_SMALL":
            f"subject coverage {getattr(metrics, 'subject_coverage', None)}"
            f" below the target band",
        "WHITE_CLIPPING":
            f"{getattr(metrics, 'pct_white', None)} pixels blown",
        "BLACK_CLIPPING":
            f"{getattr(metrics, 'pct_black', None)} pixels crushed",
        "SUBJECT_TOO_DARK":
            f"mean luma {getattr(metrics, 'mean_luma', None)} underexposed",
        "CAMERA_ROLL": f"measured roll {getattr(metrics, 'roll_deg', 0.0)}",
        "STALE_CAPTURE": "capture hash unchanged between passes",
        "BLACK_BAND": f"bands {getattr(metrics, 'bands', None)}",
    }
    return row.get(defect, defect)


def _why(action: str, defect: str, metrics: Any) -> str:
    if action.startswith("camera_") or action == "camera_framing_recompute":
        return (f"the highest measured framing problem is {defect} "
                f"(coverage {getattr(metrics, 'subject_coverage', None)}); "
                "reframing the viewport camera changes subject screen size "
                "directly and is fully read-back verifiable")
    if "light" in action or "exposure" in action or "key" in action:
        return (f"the highest measured exposure problem is {defect} "
                f"(luma {getattr(metrics, 'mean_luma', None)}, "
                f"white {getattr(metrics, 'pct_white', None)}, "
                f"black {getattr(metrics, 'pct_black', None)}); a bounded "
                "dominant-light intensity change has the largest per-op "
                "effect on clipping and is read-back verifiable")
    return f"targets {defect} directly"


def _impact(action: str) -> str:
    impacts = {
        "camera_framing_recompute": "repositions subject framing to the "
                                    "target coverage band in one bounded move",
        "camera_pull_back": "reduces subject screen coverage (bounded)",
        "camera_move_closer": "increases subject screen coverage (bounded)",
        "camera_roll_reset": "zeroes camera roll (exact, verifiable)",
        "exposure_reduce_highlights": "lowers highlight clipping the most",
        "lighting_reduce_background": "secondary highlight reduction",
        "environment_reduce_emissives": "reduces emissive contribution",
        "exposure_raise_blacks": "lifts crushed shadows the most",
        "lighting_raise_key": "brightens the scene key light",
        "capture_force_fresh": "forces a genuinely new frame",
    }
    return impacts.get(action, "bounded change targeting " + action)


def parse_capture_diag(diag: str) -> Dict[str, Any]:
    """Parse the native capture diagnostic into a structured verdict.

    The release capture contract requires a REAL visible viewport frame:
    source=LevelViewport[...], visible=1.  visible=0 means the editor
    window is minimized/occluded and the returned PNG is a stale buffer —
    such a capture is rejected, never used as evidence.
    """
    diag = str(diag or "")
    fields = {}
    for match in re.finditer(r"(\w+)=([^|]+)", diag):
        fields[match.group(1)] = match.group(2).strip()
    visible = fields.get("visible")
    ok_flag = diag.startswith("OK|") or diag.startswith("OK |")
    visible_ok = visible == "1"
    return {
        "ok": bool(ok_flag and visible_ok),
        "raw": diag[:160],
        "visible": visible_ok,
        "source": fields.get("source", ""),
        "width": int(fields["width"]) if fields.get("width", "").isdigit() else 0,
        "height": int(fields["height"]) if fields.get("height", "").isdigit() else 0,
        "bytes": int(fields["bytes"]) if fields.get("bytes", "").isdigit() else 0,
    }


def decide_rollback(
    previous_score: Optional[float],
    current_score: Optional[float],
    previous_defects: List[str],
    current_defects: List[str],
    applied_actions: List[str],
) -> bool:
    """Revert the last change when the new frame is strictly worse or made
    no progress: score dropped >= 0.05 OR the same blocking defect persists
    after an applied change while score did not improve."""
    if not applied_actions:
        return False
    if previous_score is None or current_score is None:
        return False
    if current_score <= previous_score - 0.05:
        return True
    if current_score <= previous_score + 0.01 and current_defects and \
            current_defects == previous_defects:
        return True
    return False


def dolly_factor(
    direction: str,
    coverage: Optional[float],
    target_coverage: float = 0.40,
) -> float:
    """Bounded camera-distance change factor for a framing defect.

    Screen coverage scales with the square of the inverse distance, so the
    one-step factor to move coverage to `target_coverage` is
    sqrt(coverage/target) — clamped to the bounded range and never a
    reversal of the requested direction.
    """
    if coverage is None or coverage <= 0:
        return 1.0
    if direction in ("camera_pull_back",) and coverage > target_coverage:
        factor = (coverage / max(target_coverage, 1e-6)) ** 0.5
        return round(min(max(factor, 1.05), DOLLY_FACTOR_RANGE[1]), 3)
    if direction in ("camera_move_closer",) and coverage < target_coverage:
        factor = (coverage / max(target_coverage, 1e-6)) ** 0.5
        return round(min(max(factor, DOLLY_FACTOR_RANGE[0]), 0.95), 3)
    return 1.0


def light_factor(action: str, metrics: Any) -> float:
    """Bounded dominant-light intensity change factor for exposure defects,
    sized from the measured excess over the frozen clipping budgets."""
    hm = 0.08 + 0.02          # frozen highlight budget + issue tolerance
    sm = 0.12 + 0.03          # frozen shadow budget + issue tolerance
    if action in ("exposure_reduce_highlights", "lighting_reduce_background",
                  "environment_reduce_emissives"):
        white = float(getattr(metrics, "pct_white", 0.0) or 0.0)
        if white <= hm:
            return 0.85
        return round(min(max(hm / white, LIGHT_FACTOR_RANGE[0]), 0.85), 3)
    if action in ("exposure_raise_blacks", "lighting_raise_key"):
        black = float(getattr(metrics, "pct_black", 0.0) or 0.0)
        luma = float(getattr(metrics, "mean_luma", 130.0) or 130.0)
        if black >= sm:
            return round(min(max(1.5, (black / sm) * 1.6),
                             LIGHT_FACTOR_RANGE[1]), 3)
        if luma < 90.0:
            return round(min(max(1.3, 120.0 / max(luma, 1.0)),
                             LIGHT_FACTOR_RANGE[1]), 3)
        return 1.2
    return 1.0
