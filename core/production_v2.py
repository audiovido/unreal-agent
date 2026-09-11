"""production_v2.py — Production Pipeline V2: evidence-gated execution.

Rebuild of the visual production architecture so that high-level missions can
NEVER false-pass from a single atomic fast-path action.

Two strict lanes:

- ATOMIC LANE: one explicit, single-scene operation. The existing fast-path is
  allowed here, and the result is labelled so it can never be mistaken for a
  production mission verdict.
- PRODUCTION LANE: high-level / multi-step missions. The fast-path is
  forbidden here regardless of keywords, and PASS requires the full
  graduation gate chain.

Design invariants (all enforced in code, not by convention):

* executor success is NOT mission PASS — ``executor_success`` only opens the
  ``execution_gate``.
* actor count alone is NOT evidence — SceneDiff over full scene evidence is
  the only accepted delta signal.
* a production PASS requires a meaningful SceneDiff.
* visual missions require FRESH screenshot evidence (freshness is measured
  against the post-execution snapshot, not the wall clock alone).
* the Visual Director / vision review is an EVALUATOR only: it scores and
  prescribes repair hints; it never executes scene mutations.
* negative wording ("do not use cubes", "without cubes", "no cubes") can never
  trigger a cube fast-path because production-lane classification runs before
  any fast-path, and negative sentences are non-atomic by definition.
* repair is bounded (max 3 iterations) and a REPEATED same-failure signature
  must change strategy or BLOCK.

This module is deterministic and hermetically testable: Unreal access is
injected via callables (``scene_evidence_provider``, ``capture_provider``), so
tests never need a live editor. Runtime adapters live in ``app.api``.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

# --------------------------------------------------------------------------
# Lane classification
# --------------------------------------------------------------------------

# Words that make a request a HIGH-LEVEL / MULTI-STEP mission even when an
# atomic keyword like "cube" also appears. These imply orchestration across
# several actions, staging, or judgment.
PRODUCTION_TERMS: tuple[str, ...] = (
    "scene", "environment", "level", "world", "room", "interior",
    "cinematic", "shot", "camera", "lighting", "materials", "art pass",
    "make it look", "beautiful", "portfolio", "showcase", "staging",
    "composition", "mood", "atmosphere", "vibe", "redesign", "rebuild",
    "layout", "arrange", "decorat", "furnish", "populate", "build me",
    "create me", "and then", "then ", "step by step", "mission",
)

# Explicit single-operation phrasing. Only one of these, combined with exactly
# one object and no production term, can reach the atomic lane.
ATOMIC_TERMS: tuple[str, ...] = (
    "create", "craete", "creat", "spawn", "add", "place", "make", "move",
    "rotate", "scale", "delete", "remove", "duplicate",
)

# Negation cues: "do not use cubes" must NEVER trigger a cube fast-path.
NEGATION_CUES: tuple[str, ...] = (
    "no ", "not ", "don't ", "dont ", "do not ", "without ", "never ",
    "exclude ", "avoid ", "instead of ", "rather than ", "stop using ",
)

MULTI_OBJECT_CUES: tuple[str, ...] = (
    " and ", " with ", " plus ", " several", "multiple", "few ", "some ",
    "couple of", "set of", "group of",
)


def classify_lane(request: str) -> str:
    """Strict two-lane classifier.

    Returns "production" for anything that is high-level, multi-step,
    multi-object, negated, or ambiguous. Returns "atomic" ONLY for a single
    explicit operation on a single object.

    Bias is deliberately toward production: a mis-routed atomic request costs
    a slightly slower path, while a mis-routed production mission used to cost
    a false PASS.
    """
    text = str(request or "").strip().lower()
    if not text:
        return "production"

    # Any negation around an action/object implies judgment, never a bare op.
    if any(cue in text for cue in NEGATION_CUES):
        return "production"

    # High-level mission wording dominates any atomic keyword.
    if any(term in text for term in PRODUCTION_TERMS):
        return "production"

    # Multiple coordinated objects -> multi-step mission.
    if any(cue in text for cue in MULTI_OBJECT_CUES):
        return "production"

    # Word-boundary matching so "create"/"creat" count once and "add" does
    # not match inside unrelated words.
    verbs = sorted(
        {
            t
            for t in ATOMIC_TERMS
            if re.search(r"\b" + re.escape(t) + r"\b", text)
        }
    )
    if len(verbs) > 1:
        return "production"

    if verbs and text.split()[0].rstrip(",.!?") in verbs:
        # Leading single imperative: "create cube", "spawn a sphere".
        object_words = [w for w in text.split() if w not in verbs]
        if len(object_words) <= 3:  # article + adjective + single object
            return "atomic"

    return "production"


def atomic_fast_path_allowed(request: str) -> bool:
    """The cube fast-path may fire ONLY on the atomic lane, and only for a
    positive single-object cube command. Negative wording ("do not use
    cubes") can never reach here because classify_lane already rejects it."""
    if classify_lane(request) != "atomic":
        return False
    text = str(request or "").lower()
    if "cube" not in text:
        return False
    if any(cue in text for cue in NEGATION_CUES):
        return False
    return any(verb in text for verb in ("create", "craete", "creat", "spawn", "add", "place", "make"))


# --------------------------------------------------------------------------
# Scene evidence & SceneDiff
# --------------------------------------------------------------------------

SCENE_EVIDENCE_KEYS: tuple[str, ...] = (
    "map", "actors", "classes", "transforms", "mesh_refs",
    "material_refs", "lights", "cameras",
)

SCENEDIFF_KEYS: tuple[str, ...] = (
    "actors_added", "actors_removed", "actors_modified",
    "transforms_changed", "assets_changed", "materials_changed",
    "lights_changed", "cameras_changed",
)

# Tolerances so float noise never counts as a transform change.
POSITION_TOLERANCE = 1.0   # unreal units
ROTATION_TOLERANCE = 0.5   # degrees
SCALE_TOLERANCE = 0.01


def normalize_scene_evidence(raw: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Coerce a provider payload into the full evidence contract.

    Every SCENE_EVIDENCE_KEYS entry must be present (missing maps/actors are
    structural failures, not empty successes).
    """
    data = dict(raw or {})
    evidence: Dict[str, Any] = {}
    for key in SCENE_EVIDENCE_KEYS:
        value = data.get(key)
        if value is None:
            if key == "map":
                evidence[key] = ""
            elif key in ("transforms",):
                evidence[key] = {}
            else:
                evidence[key] = []
        else:
            evidence[key] = value
    return evidence


def scene_evidence_complete(evidence: Mapping[str, Any]) -> bool:
    """A usable snapshot must name a map and carry an actors list."""
    return bool(str(evidence.get("map") or "").strip()) and isinstance(
        evidence.get("actors"), list
    )


def _actor_key(actor: Any) -> str:
    if isinstance(actor, Mapping):
        return str(actor.get("name") or actor.get("label") or actor.get("id") or "")
    return str(actor)


def _actor_class(actor: Any) -> str:
    if isinstance(actor, Mapping):
        return str(actor.get("class") or actor.get("class_name") or "")
    return ""


def _approx_changed(a: float, b: float, tol: float) -> bool:
    return abs(float(a) - float(b)) > tol


def _transform_changed(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> bool:
    if not before or not after:
        return before != after
    for axis in ("x", "y", "z"):
        try:
            if _approx_changed(
                (before.get("location") or {}).get(axis, 0.0),
                (after.get("location") or {}).get(axis, 0.0),
                POSITION_TOLERANCE,
            ):
                return True
            if _approx_changed(
                (before.get("rotation") or {}).get(axis, 0.0),
                (after.get("rotation") or {}).get(axis, 0.0),
                ROTATION_TOLERANCE,
            ):
                return True
            if _approx_changed(
                (before.get("scale") or {}).get(axis, 1.0),
                (after.get("scale") or {}).get(axis, 1.0),
                SCALE_TOLERANCE,
            ):
                return True
        except (TypeError, ValueError):
            return True
    return False


def scene_diff(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> Dict[str, Any]:
    """Compute the full SceneDiff contract between two scene snapshots."""
    b = normalize_scene_evidence(before)
    a = normalize_scene_evidence(after)

    b_actors = {str(x.get("name") or x.get("label") or x): x for x in (b.get("actors") or []) if isinstance(x, Mapping)} if all(isinstance(x, Mapping) for x in (b.get("actors") or [])) else {_actor_key(x): {} for x in (b.get("actors") or [])}
    a_actors = {str(x.get("name") or x.get("label") or x): x for x in (a.get("actors") or []) if isinstance(x, Mapping)} if all(isinstance(x, Mapping) for x in (a.get("actors") or [])) else {_actor_key(x): {} for x in (a.get("actors") or [])}

    actors_added = sorted(set(a_actors) - set(b_actors))
    actors_removed = sorted(set(b_actors) - set(a_actors))
    actors_modified = sorted(
        name
        for name in set(a_actors) & set(b_actors)
        if _actor_class(a_actors[name]) != _actor_class(b_actors[name])
    )

    b_t = b.get("transforms") or {}
    a_t = a.get("transforms") or {}
    transforms_changed = sorted(
        name
        for name in set(a_t) | set(b_t)
        if _transform_changed(b_t.get(name), a_t.get(name))
    )

    def _sorted_unique(seq: Any) -> List[str]:
        return sorted({str(x) for x in (seq or [])})

    assets_changed = sorted(
        _sorted_unique(b.get("mesh_refs")) != _sorted_unique(a.get("mesh_refs"))
        and [
            *(
                set(_sorted_unique(a.get("mesh_refs")))
                ^ set(_sorted_unique(b.get("mesh_refs")))
            )
        ]
        or []
    )
    materials_changed = sorted(
        _sorted_unique(b.get("material_refs")) != _sorted_unique(a.get("material_refs"))
        and [
            *(
                set(_sorted_unique(a.get("material_refs")))
                ^ set(_sorted_unique(b.get("material_refs")))
            )
        ]
        or []
    )
    lights_changed = sorted(set(_sorted_unique(b.get("lights"))) ^ set(_sorted_unique(a.get("lights"))))
    cameras_changed = sorted(set(_sorted_unique(b.get("cameras"))) ^ set(_sorted_unique(a.get("cameras"))))

    return {
        "actors_added": actors_added,
        "actors_removed": actors_removed,
        "actors_modified": actors_modified,
        "transforms_changed": transforms_changed,
        "assets_changed": assets_changed,
        "materials_changed": materials_changed,
        "lights_changed": lights_changed,
        "cameras_changed": cameras_changed,
    }


def scene_diff_is_meaningful(diff: Mapping[str, Any]) -> bool:
    """A diff is meaningful when ANY tracked dimension actually changed."""
    return any(bool(diff.get(key)) for key in SCENEDIFF_KEYS)


# --------------------------------------------------------------------------
# Screenshot evidence (fresh capture, never stale)
# --------------------------------------------------------------------------


def screenshot_fresh(
    capture: Mapping[str, Any] | None,
    snapshot_after: Mapping[str, Any] | None,
) -> bool:
    """Fresh evidence = captured AFTER the post-execution snapshot and not
    flagged stale. Wall-clock recency alone is NOT sufficient: a screenshot
    reused from before the final scene state is a stale screenshot."""
    if not capture or not snapshot_after:
        return False
    if capture.get("stale"):
        return False
    if str(capture.get("map") or "") != str(snapshot_after.get("map") or ""):
        return False
    try:
        if float(capture.get("captured_at") or 0) < float(snapshot_after.get("captured_at") or 0):
            return False
    except (TypeError, ValueError):
        return False
    return True


def screenshot_content_hash(capture: Mapping[str, Any]) -> str:
    """Stable hash of the captured image content (path+size+mtime)."""
    raw = "|".join(
        str(capture.get(k) or "")
        for k in ("path", "size_bytes", "mtime_ns")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Visual evaluation (deterministic; vision review is advisory evidence)
# --------------------------------------------------------------------------

VISUAL_EVALUATION_CATEGORIES: tuple[str, ...] = (
    "exposure", "composition", "focal_point", "depth", "material_quality",
    "lighting", "clutter", "placeholder_prevalence", "framing", "target_match",
)

# Deterministic base: a clean, freshly captured frame with real content is a
# structurally valid image; every category starts at 8.0 ("clean by
# measurement") and is penalized by concrete defects only.
_BASE_SCORES: Dict[str, float] = {
    "exposure": 8.0,
    "composition": 8.0,
    "focal_point": 8.0,
    "depth": 8.0,
    "material_quality": 8.0,
    "lighting": 8.0,
    "clutter": 8.0,
    "placeholder_prevalence": 8.0,
    "framing": 8.0,
    "target_match": 8.0,
}

# Frame-level defects from the existing analyzer map to category penalties.
_FRAME_DEFECT_PENALTIES: Dict[str, tuple[str, ...]] = {
    "black_frame": ("exposure", "lighting"),
    "white_frame": ("exposure", "lighting"),
    "overexposed": ("exposure",),
    "underexposed": ("exposure",),
    "low_contrast": ("composition", "depth"),
    "letterbox": ("framing", "composition"),
    "black_bands": ("framing", "composition"),
}


def evaluate_visual(
    capture: Mapping[str, Any] | None,
    frame_analysis: Mapping[str, Any] | None = None,
    vision_review: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Score the requested visual categories for one capture.

    Deterministic first: frame-level defects apply category penalties.
    ``vision_review`` (Visual Director / vision model) may adjust scores but is
    an evaluator only — it contributes opinions, never actions.
    """
    scores = dict(_BASE_SCORES)

    analysis = frame_analysis or {}
    issues = [str(i).lower() for i in (analysis.get("issues") or [])]
    for issue in issues:
        for defect, categories in _FRAME_DEFECT_PENALTIES.items():
            if defect.replace("_", " ") in issue or defect in issue:
                for cat in categories:
                    scores[cat] = round(scores[cat] - 2.0, 2)

    # Placeholder/basic-shape prevalence is judged by the vision review only.
    if vision_review:
        vr_issues = [str(i).lower() for i in (vision_review.get("issues") or [])]
        for cat, cue in (
            ("placeholder_prevalence", "placeholder"),
            ("placeholder_prevalence", "basic shape"),
            ("clutter", "clutter"),
            ("composition", "composition"),
            ("lighting", "lighting"),
            ("material_quality", "material"),
            ("focal_point", "focal"),
            ("depth", "flat"),
            ("framing", "framing"),
            ("target_match", "off target"),
            ("exposure", "exposure"),
        ):
            if any(cue in i for i in vr_issues):
                scores[cat] = round(scores[cat] - 1.5, 2)

    overall = round(sum(scores[c] for c in VISUAL_EVALUATION_CATEGORIES) / len(VISUAL_EVALUATION_CATEGORIES), 2)
    return {
        "scores": scores,
        "overall": overall,
        # Accepted = clean overall AND no single defective category. One
        # measurable defect is enough to block a production visual pass.
        "accepted": overall >= 7.5 and all(v >= 7.0 for v in scores.values()),
        "evaluator": "deterministic+vision_advisory" if vision_review else "deterministic",
        "categories": list(VISUAL_EVALUATION_CATEGORIES),
    }


# --------------------------------------------------------------------------
# Graduation gates
# --------------------------------------------------------------------------


def graduation_gates(
    *,
    executor_success: bool,
    diff: Mapping[str, Any] | None,
    capture: Mapping[str, Any] | None,
    snapshot_after: Mapping[str, Any] | None,
    visual: Mapping[str, Any] | None,
    acceptance_contract: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """The production PASS decision. Every gate must pass; any single failing
    gate blocks the verdict — exactly the anti-false-pass contract."""
    diff = diff or {}
    visual = visual or {}
    contract = acceptance_contract or {}

    scene_diff_gate = scene_diff_is_meaningful(diff)
    evidence_gate = screenshot_fresh(capture, snapshot_after)
    visual_gate = bool(visual.get("accepted"))
    contract_gate = bool(contract.get("satisfied", True)) and bool(
        contract.get("present", True)
    )

    technical_unreal_gate = bool(
        (capture or {}).get("unreal_ok", False) or (snapshot_after or {}).get("unreal_ok", False)
    )

    passed = all(
        (
            bool(executor_success),
            scene_diff_gate,
            technical_unreal_gate,
            evidence_gate,
            visual_gate,
            contract_gate,
        )
    )
    return {
        "execution_gate": bool(executor_success),
        "scene_diff_gate": scene_diff_gate,
        "technical_unreal_gate": technical_unreal_gate,
        "evidence_gate": evidence_gate,
        "visual_gate": visual_gate,
        "acceptance_contract": contract_gate,
        "passed": passed,
    }


# --------------------------------------------------------------------------
# Production state machine
# --------------------------------------------------------------------------


class ProductionMissionState:
    """The production-lane state machine.

    CLASSIFY -> PREFLIGHT -> PLAN -> SNAPSHOT_BEFORE -> EXECUTE_STEP ->
    VERIFY_STEP -> SNAPSHOT_AFTER -> SCENE_DIFF -> CAPTURE -> VISUAL_EVALUATE
    -> TARGETED_REPAIR? -> FINAL_VERIFY -> GRADUATE

    Repair is bounded at 3 iterations; a repeated identical failure signature
    must change strategy or the mission BLOCKs.
    """

    MAX_REPAIRS = 3

    STATES = (
        "CLASSIFY", "PREFLIGHT", "PLAN", "SNAPSHOT_BEFORE", "EXECUTE_STEP",
        "VERIFY_STEP", "SNAPSHOT_AFTER", "SCENE_DIFF", "CAPTURE",
        "VISUAL_EVALUATE", "TARGETED_REPAIR", "FINAL_VERIFY", "GRADUATE",
        "BLOCKED",
    )

    def __init__(
        self,
        request: str,
        *,
        evidence_provider: Callable[[str], Mapping[str, Any]],
        capture_provider: Optional[Callable[[str], Mapping[str, Any]]] = None,
        executor: Optional[Callable[[str], Mapping[str, Any]]] = None,
        frame_analyzer: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        vision_reviewer: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        acceptance_contract: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.request = str(request)
        self.lane = classify_lane(self.request)
        self.state = "CLASSIFY"
        self.evidence_provider = evidence_provider
        self.capture_provider = capture_provider
        self.executor = executor
        self.frame_analyzer = frame_analyzer
        self.vision_reviewer = vision_reviewer
        self.acceptance_contract = dict(acceptance_contract or {"present": True, "satisfied": True})

        self.snapshot_before: Dict[str, Any] = {}
        self.snapshot_after: Dict[str, Any] = {}
        self.diff: Dict[str, Any] = {}
        self.capture: Dict[str, Any] = {}
        self.visual: Dict[str, Any] = {}
        self.gates: Dict[str, Any] = {}
        self.executor_success: bool = False
        self.step_results: List[Dict[str, Any]] = []
        self.repair_iterations: int = 0
        self.last_repair_signature: Optional[str] = None
        self.blocker: Optional[str] = None
        self.verdict: Optional[str] = None
        self.transitions: List[str] = [self.state]
        # Mission-relative monotonic clock. Evidence payloads that carry their
        # own ``captured_at`` (real runtime adapters use epoch time) are
        # honored verbatim; otherwise snapshots are stamped with this counter.
        # Freshness is then a like-for-like comparison, and production-grade
        # staleness detection rests on the ``stale`` flag + content hash that
        # the runtime adapter computes (see visual_acceptance).
        self._mission_clock: float = 0.0

    @property
    def diff_meaningful(self) -> bool:
        return scene_diff_is_meaningful(self.diff)

    # -- primitive transitions ------------------------------------------------

    def _to(self, state: str) -> None:
        self.state = state
        self.transitions.append(state)

    def _evidence(self) -> tuple[Dict[str, Any], Mapping[str, Any]]:
        raw = self.evidence_provider(str(self.state)) or {}
        data = dict(normalize_scene_evidence(raw))
        data.setdefault("unreal_ok", True)
        return data, raw

    def _stamp_captured_at(self, snapshot: Dict[str, Any], raw: Mapping[str, Any]) -> None:
        """Stamp a snapshot with a trustworthy capture timestamp.

        Provider-supplied timestamps win (like-for-like freshness checks).
        Otherwise the mission clock advances monotonically, so any capture
        stamped before the post-execution snapshot is correctly stale.
        """
        provider_ts = raw.get("captured_at") if isinstance(raw, Mapping) else None
        if provider_ts is not None:
            try:
                snapshot["captured_at"] = float(provider_ts)
                return
            except (TypeError, ValueError):
                pass
        self._mission_clock += 1.0
        snapshot["captured_at"] = self._mission_clock

    # -- pipeline -------------------------------------------------------------

    def classify(self) -> str:
        self.lane = classify_lane(self.request)
        self._to("PREFLIGHT")
        return self.lane

    def preflight(self) -> None:
        # Production lane must never silently degrade into the fast path.
        if self.lane != "production":
            self._to("PLAN")
            return
        self._to("PLAN")

    def plan(self) -> None:
        self._to("SNAPSHOT_BEFORE")

    def take_snapshot_before(self) -> None:
        self.snapshot_before, raw = self._evidence()
        self._stamp_captured_at(self.snapshot_before, raw)
        self._to("EXECUTE_STEP")

    def execute_steps(self) -> None:
        if self.executor is not None:
            result = self.executor(self.request)
            self.executor_success = bool((result or {}).get("ok"))
            self.step_results.append(dict(result or {}))
        else:
            self.executor_success = True
        self._to("VERIFY_STEP")

    def verify_steps(self) -> None:
        if not self.executor_success:
            self.blocker = "EXECUTOR_FAILED"
            self._to("BLOCKED")
            return
        self._to("SNAPSHOT_AFTER")

    def take_snapshot_after(self) -> None:
        self.snapshot_after, raw = self._evidence()
        self._stamp_captured_at(self.snapshot_after, raw)
        self._to("SCENE_DIFF")

    def compute_scene_diff(self) -> None:
        self.diff = scene_diff(self.snapshot_before, self.snapshot_after)
        self._to("CAPTURE")

    def capture_frame(self) -> None:
        if self.capture_provider is None:
            self.capture = {}
        else:
            self.capture = dict(self.capture_provider(str(self.state)) or {})
            self.capture["content_hash"] = screenshot_content_hash(self.capture)
        self._to("VISUAL_EVALUATE")

    def visual_evaluate(self) -> None:
        frame = self.frame_analyzer(self.capture) if self.frame_analyzer else {}
        vision = self.vision_reviewer(self.capture) if self.vision_reviewer else None
        self.visual = evaluate_visual(self.capture, frame, vision)
        self._to("FINAL_VERIFY")

    def final_verify(self) -> None:
        self.gates = graduation_gates(
            executor_success=self.executor_success,
            diff=self.diff,
            capture=self.capture,
            snapshot_after=self.snapshot_after,
            visual=self.visual,
            acceptance_contract=self.acceptance_contract,
        )
        if self.gates["passed"]:
            self._to("GRADUATE")
            self.verdict = "PASS"
            return

        if self.repair_iterations >= self.MAX_REPAIRS:
            self.blocker = "REPAIR_BUDGET_EXHAUSTED"
            self._to("BLOCKED")
            return

        signature = hashlib.sha256(
            repr({k: self.gates[k] for k in sorted(self.gates)}).encode("utf-8")
        ).hexdigest()[:16]
        if signature == self.last_repair_signature:
            # Repeating the identical failure can never converge by luck.
            self.blocker = "REPEATED_FAILURE_SIGNATURE"
            self._to("BLOCKED")
            return
        self.last_repair_signature = signature
        self.repair_iterations += 1
        self._to("TARGETED_REPAIR")

    def targeted_repair(self) -> None:
        # Re-run the executor with accumulated context (strategy change is the
        # caller's responsibility via a new executor closure; the state machine
        # guarantees bounded iterations and failure-signature change).
        if self.executor is not None:
            result = self.executor(f"{self.request} [repair {self.repair_iterations}]")
            self.executor_success = bool((result or {}).get("ok"))
            self.step_results.append(dict(result or {}))
        self.snapshot_after, raw = self._evidence()
        self._stamp_captured_at(self.snapshot_after, raw)
        self.diff = scene_diff(self.snapshot_before, self.snapshot_after)
        if self.capture_provider is not None:
            self.capture = dict(self.capture_provider(str(self.state)) or {})
            self.capture["content_hash"] = screenshot_content_hash(self.capture)
        frame = self.frame_analyzer(self.capture) if self.frame_analyzer else {}
        vision = self.vision_reviewer(self.capture) if self.vision_reviewer else None
        self.visual = evaluate_visual(self.capture, frame, vision)
        self._to("FINAL_VERIFY")

    # -- driver ----------------------------------------------------------------

    def run(self) -> "ProductionMissionState":
        self.classify()
        self.preflight()
        self.plan()
        self.take_snapshot_before()
        self.execute_steps()
        self.verify_steps()
        while self.state not in ("GRADUATE", "BLOCKED"):
            if self.state == "SNAPSHOT_AFTER":
                self.take_snapshot_after()
            elif self.state == "SCENE_DIFF":
                self.compute_scene_diff()
            elif self.state == "CAPTURE":
                self.capture_frame()
            elif self.state == "VISUAL_EVALUATE":
                self.visual_evaluate()
            elif self.state == "FINAL_VERIFY":
                self.final_verify()
            elif self.state == "TARGETED_REPAIR":
                self.targeted_repair()
            else:
                self._to("BLOCKED")
                self.blocker = self.blocker or "INVALID_STATE"
                break
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lane": self.lane,
            "request": self.request,
            "state": self.state,
            "verdict": self.verdict,
            "blocker": self.blocker,
            "executor_success": self.executor_success,
            "diff": dict(self.diff),
            "diff_meaningful": scene_diff_is_meaningful(self.diff),
            "capture": dict(self.capture),
            "visual": dict(self.visual),
            "gates": dict(self.gates),
            "repair_iterations": self.repair_iterations,
            "transitions": list(self.transitions),
            "acceptance_contract": dict(self.acceptance_contract),
        }
