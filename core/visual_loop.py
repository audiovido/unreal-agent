"""visual_loop.py — the autonomous visual iteration loop.

The loop is the runtime engine of the product contract:

    BUILD -> RUNTIME -> CAPTURE -> ANALYZE -> SCORE -> FIX -> CAPTURE

It drives deterministic, changed-strategy iteration: every fix is derived
from a measured defect, logged as problem/hypothesis/change/before/after/
result, and applied with bounded deltas — never random value shuffling.
A task may only report COMPLETE when BOTH the technical acceptance and the
visual acceptance pass (see completion_gate in visual_acceptance).

This module is Unreal-agnostic. The caller injects:

- capture:        () -> path to a fresh screenshot
- apply:          (action, metrics, score, target, pass_index) -> change note
- vision:         (path) -> optional vision-model review dict
- technical_ok:   () -> (bool, evidence_dict)
- external blocker: Optional[str] (e.g. PHOTOREAL_CHARACTER_SOURCE_REQUIRED)
                  — waives only the categories an external asset makes
                  impossible, never the technical gate.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.visual_acceptance import (
    accepts,
    combine_with_vision,
    completion_gate,
    measure,
    score,
)
from core.visual_director import (
    DEFECT_ACTIONS,
    defect_to_action,
    self_critique,
)

# Changed-strategy chains: if the first strategy for a defect does not clear
# it, advance to the next strategy instead of repeating the same change.
STRATEGY_CHAINS: Dict[str, List[str]] = {
    "HEAD_CROPPED": ["camera_framing_recompute", "camera_pull_back",
                     "camera_move_closer"],
    "SUBJECT_TOO_LARGE": ["camera_pull_back", "camera_framing_recompute",
                          "camera_move_closer"],
    "SUBJECT_TOO_SMALL": ["camera_move_closer", "camera_framing_recompute"],
    "WHITE_CLIPPING": ["exposure_reduce_highlights",
                       "lighting_reduce_background",
                       "environment_reduce_emissives"],
    "BACKGROUND_OVEREXPOSED": ["lighting_reduce_background",
                               "exposure_reduce_highlights"],
    "BLACK_CLIPPING": ["exposure_raise_blacks", "lighting_raise_key"],
    "SUBJECT_TOO_DARK": ["lighting_raise_key", "exposure_raise_blacks",
                         "camera_move_closer"],
    "UI_TOO_SMALL": ["ui_scale_up", "ui_relayout_runtime"],
    "UI_LOW_CONTRAST": ["ui_raise_contrast", "ui_scale_up"],
    "UI_OFF_SCREEN": ["ui_relayout_runtime", "ui_scale_up"],
    "BLACK_BAND": ["viewport_aspect_fix", "capture_force_fresh"],
    "STALE_CAPTURE": ["capture_force_fresh"],
    "CAMERA_ROLL": ["camera_roll_reset", "camera_framing_recompute"],
    "EMPTY_ENVIRONMENT": ["environment_add_depth", "lighting_reduce_background",
                          "camera_pull_back"],
}

DEFECT_PRIORITY: List[str] = [
    "STALE_CAPTURE", "BLACK_BAND", "HEAD_CROPPED", "SUBJECT_TOO_LARGE",
    "SUBJECT_TOO_SMALL", "WHITE_CLIPPING", "BACKGROUND_OVEREXPOSED",
    "BLACK_CLIPPING", "SUBJECT_TOO_DARK", "UI_OFF_SCREEN", "UI_TOO_SMALL",
    "UI_LOW_CONTRAST", "CAMERA_ROLL", "EMPTY_ENVIRONMENT",
]


@dataclass
class LoopPass:
    index: int
    path: str
    hash_md5_12: str
    defects: List[str]
    actions: List[str]
    verdict: str                       # PASS / REVISE
    score: Dict[str, float] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    vision: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "path": self.path,
            "hash": self.hash_md5_12,
            "defects": self.defects,
            "actions": self.actions,
            "verdict": self.verdict,
            "score": self.score,
            "metrics": self.metrics,
            "vision": self.vision,
        }


class AutonomousVisualLoop:
    """Deterministic capture -> measure -> score -> fix -> recapture loop.

    Parameters
    ----------
    target:           VisualTarget dict from visual_director.parse_intent
    capture:          callable() -> path of a fresh screenshot
    apply:            callable(action, metrics, score, target, pass_index)
                      -> change description str (or dict with "note")
    vision:           optional callable(path) -> vision review dict
    technical_ok:     optional callable() -> (bool, evidence dict)
    external_blocker: optional str, e.g. PHOTOREAL_CHARACTER_SOURCE_REQUIRED
    max_passes:       default 8; loop stops early when the target passes
    """

    def __init__(
        self,
        target: Dict[str, Any],
        capture: Callable[[], str],
        apply: Callable[[str, Any, Any, Dict[str, Any], int], Any],
        vision: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        technical_ok: Optional[Callable[[], tuple]] = None,
        external_blocker: Optional[str] = None,
        max_passes: int = 8,
        out_dir: Optional[str] = None,
        subject_locator: Optional[Callable] = None,
        ui_locator: Optional[Callable] = None,
    ) -> None:
        self.target = target
        self.subject_locator = subject_locator
        self.ui_locator = ui_locator
        self.capture = capture
        self.apply = apply
        self.vision = vision
        self.technical_ok = technical_ok
        self.external_blocker = external_blocker
        self.max_passes = int(max_passes)
        self.out_dir = out_dir
        self.passes: List[LoopPass] = []
        self.action_logs: List[Dict[str, Any]] = []
        self._tried: Dict[str, List[str]] = {}
        self._pending_log: Optional[Dict[str, Any]] = None

    def _post_measure(self, metrics: Any) -> None:
        """Hook for scene-specific ground truth. Runs immediately after a
        capture is measured and BEFORE defects are derived/scored, so an
        adapter can correct a proxy that its runtime disagrees with (e.g.
        zero an image-derived camera-roll when the actual camera rotation is
        read back as level). Default: no-op."""
        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _derive_defects(self, metrics: Any, s: Any) -> List[str]:
        d: List[str] = []
        if metrics.stale:
            d.append("STALE_CAPTURE")
        if metrics.bands:
            d.append("BLACK_BAND")
        subj = self.target.get("subject") or {}
        want = subj.get("target_screen_coverage") or [0.22, 0.50]
        light = self.target.get("lighting") or {}
        ui_t = self.target.get("ui") or {}

        if metrics.head_clipped:
            d.append("HEAD_CROPPED")
        if metrics.subject_bbox:
            if metrics.subject_coverage > want[1] + 0.02:
                d.append("SUBJECT_TOO_LARGE")
            elif metrics.subject_coverage < max(0.0, want[0] - 0.02) \
                    and str(subj.get("type")) != "scene":
                d.append("SUBJECT_TOO_SMALL")
        if metrics.pct_white > light.get("highlight_clipping_max", 0.08) + 0.02:
            d.append("WHITE_CLIPPING")
        if metrics.pct_black > light.get("shadow_crush_max", 0.12) + 0.03:
            d.append("BLACK_CLIPPING")
        if s.lighting < 6.0 and 0 < metrics.mean_luma < 70:
            d.append("SUBJECT_TOO_DARK")
        if ui_t.get("present"):
            ui_want = ui_t.get("screen_coverage") or [0.20, 0.45]
            if not metrics.ui_bbox:
                d.append("UI_OFF_SCREEN")
            elif metrics.ui_screen_coverage < max(0.0, ui_want[0] - 0.03):
                d.append("UI_TOO_SMALL")
        if metrics.roll_deg > 3.5:
            d.append("CAMERA_ROLL")
        if (subj.get("head_fully_visible") and not metrics.head_clipped
                and metrics.entropy > 0 and metrics.entropy < 5.2
                and metrics.std_luma < 13):
            d.append("EMPTY_ENVIRONMENT")
        seen = set()
        ordered = [x for x in DEFECT_PRIORITY if x in d and not (
            x in seen or seen.add(x))]
        return ordered

    def _choose_action(self, defects: List[str]) -> Optional[str]:
        if not defects:
            return None
        defect = defects[0]
        tried = self._tried.setdefault(defect, [])
        chain = STRATEGY_CHAINS.get(defect,
                                    [DEFECT_ACTIONS.get(defect, defect)])
        for candidate in chain:
            if candidate not in tried:
                tried.append(candidate)
                return candidate
        return None  # every strategy exhausted for the top defect

    def _metrics_dict(self, m: Any) -> Dict[str, Any]:
        return {
            "width": m.width, "height": m.height, "mean_luma": m.mean_luma,
            "std_luma": m.std_luma, "entropy": m.entropy,
            "pct_white": m.pct_white, "pct_black": m.pct_black,
            "subject_coverage": m.subject_coverage,
            "ui_coverage": m.ui_screen_coverage, "head_clipped": m.head_clipped,
            "bands": m.bands, "stale": m.stale, "roll_deg": m.roll_deg,
        }

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        if not os.path.isdir(self.out_dir or ".") and self.out_dir:
            os.makedirs(self.out_dir, exist_ok=True)
        last_hash: Optional[str] = None
        final_path = ""
        final_score = None
        final_metrics = None
        final_vision = None

        for i in range(1, self.max_passes + 1):
            try:
                path = self.capture()
            except Exception as exc:
                return self._result("BLOCKED", error=f"capture failed: {exc}",
                                    last_hash=last_hash)
            final_path = path
            m = measure(path, self.target, reference_hash=last_hash,
                        subject_locator=self.subject_locator,
                        ui_locator=self.ui_locator)
            last_hash = m.hash_md5_12 or last_hash
            self._post_measure(m)
            s = score(m, self.target)
            vision = None
            if self.vision is not None and m.ok:
                try:
                    vision = self.vision(path)
                except Exception:  # pragma: no cover - vision is advisory
                    vision = None
            s = combine_with_vision(s, vision)
            final_score, final_metrics, final_vision = s, m, vision

            defects = self._derive_defects(m, s)
            gate = accepts(
                s, self.target,
                allow_external_blocker=bool(self.external_blocker))
            verdict = "PASS" if gate else "REVISE"
            action = self._choose_action(defects) if not gate else None
            lp = LoopPass(
                index=i, path=path, hash_md5_12=m.hash_md5_12,
                defects=defects, actions=[action] if action else [],
                verdict=verdict, score=s.to_dict(), metrics=self._metrics_dict(m),
                vision=vision,
            )
            self.passes.append(lp)

            # close out the previous iteration's before/after log
            if self._pending_log is not None:
                pend = self._pending_log
                pend["after"] = {k: self._metrics_dict(m)[k] for k in
                                 ("mean_luma", "pct_white", "pct_black",
                                  "subject_coverage", "ui_coverage",
                                  "head_clipped")}
                pend["result"] = "RESOLVED" if not defects else (
                    "CHANGED" if pend["after"] != pend["before"] else "NO_CHANGE")
                self.action_logs.append(pend)
                self._pending_log = None

            if gate:
                break

            if action is None:
                self._pending_log = None
                break

            try:
                out = self.apply(action, m, s, self.target, i)
            except Exception as exc:
                return self._result("BLOCKED", error=f"apply failed: {exc}",
                                    last_hash=last_hash)
            note = out if isinstance(out, str) else str(
                (out or {}).get("note", action))
            self._pending_log = {
                "index": i, "problem": defects[0],
                "hypothesis": self._hypothesis(defects[0], m),
                "change": note,
                "before": {k: self._metrics_dict(m)[k] for k in
                           ("mean_luma", "pct_white", "pct_black",
                            "subject_coverage", "ui_coverage",
                            "head_clipped")},
            }

        # flush a pending action log that never got a follow-up capture
        if self._pending_log is not None and final_metrics is not None:
            pend = self._pending_log
            pend["after"] = self._metrics_dict(final_metrics)
            pend["result"] = "NO_FOLLOWUP_CAPTURE"
            self.action_logs.append(pend)
            self._pending_log = None

        return self._result("COMPLETE", last_hash=last_hash,
                            final_path=final_path, final_score=final_score,
                            final_metrics=final_metrics,
                            final_vision=final_vision)

    def _hypothesis(self, defect: str, m: Any) -> str:
        hyps = {
            "HEAD_CROPPED": "subject reaches the top margin; camera framing "
                            "or distance must change",
            "SUBJECT_TOO_LARGE": f"subject coverage {m.subject_coverage} exceeds "
                                 "the target band; camera distance too close",
            "SUBJECT_TOO_SMALL": "subject coverage below the target band; "
                                 "camera too far",
            "WHITE_CLIPPING": f"{m.pct_white:.1%} of pixels are blown; "
                              "highlight/background sources too hot",
            "BLACK_CLIPPING": "shadows crushed; lift exposure/blacks",
            "SUBJECT_TOO_DARK": "subject is underexposed; raise key/fill",
            "UI_OFF_SCREEN": "required UI has no detected panel in frame",
            "UI_TOO_SMALL": "UI panel below target coverage; scale up",
            "UI_LOW_CONTRAST": "UI blends into the background; raise contrast",
            "BLACK_BAND": "resolution/aspect mismatch produces letterbox",
            "STALE_CAPTURE": "capture hash unchanged between passes; "
                             "presentation is frozen",
            "CAMERA_ROLL": "detected roll exceeds threshold; reset roll",
            "EMPTY_ENVIRONMENT": "low entropy/contrast; environment lacks depth",
            "BACKGROUND_OVEREXPOSED": "background dominates the highlights",
        }
        return hyps.get(defect, f"{defect} detected; applying bounded fix")

    def _result(
        self,
        status: str,
        last_hash: Optional[str] = None,
        final_path: str = "",
        final_score: Any = None,
        final_metrics: Any = None,
        final_vision: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> Dict[str, Any]:
        # technical acceptance (evidence-based)
        tech_ok, tech_evidence = True, {}
        if self.technical_ok is not None:
            try:
                tech_ok, tech_evidence = self.technical_ok()
            except Exception:  # pragma: no cover
                tech_ok, tech_evidence = False, {"error": "technical check raised"}

        visual_ok = False
        critique: Dict[str, Any] = {"verdict": "REVISE"}
        if final_score is not None and final_metrics is not None:
            visual_ok = accepts(final_score, self.target,
                                allow_external_blocker=bool(
                                    self.external_blocker))
            critique = self_critique(final_path, final_metrics, final_score,
                                     vision_review=final_vision)

        gate = completion_gate(tech_ok, visual_ok)
        if error:
            status = "BLOCKED"
        elif not gate["product_complete"]:
            status = "PARTIAL" if status == "COMPLETE" else status

        return {
            "status": status,
            "error": error,
            "target": self.target,
            "passes": [p.to_dict() for p in self.passes],
            "action_logs": self.action_logs,
            "final": {
                "path": final_path,
                "hash": last_hash or (final_metrics.hash_md5_12
                                      if final_metrics else ""),
                "score": final_score.to_dict() if final_score else {},
                "metrics": self._metrics_dict(final_metrics)
                if final_metrics else {},
                "vision": final_vision,
            },
            "self_critique": critique,
            "completion_gate": gate,
            "technical_evidence": tech_evidence,
            "external_blocker": self.external_blocker,
            "iterations": len(self.passes),
        }


def dump_result(result: Dict[str, Any], path: str) -> str:
    """Persist a loop result as JSON for reports/audit trails."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    return path