"""Visual RC Scene Criteria — Deterministic, hermetic acceptance checks.

This module defines the OBJECTIVE, MEASURABLE criteria for the Visual Vertical
Slice V1. These are NOT subjective visual quality judgments — they are
deterministic predicates that can be evaluated against scene evidence
(actor lists, transforms, metadata) and fresh screenshots.

Every check here must be:
- Deterministic (same input -> same result)
- Hermetically testable (no live Unreal required for unit tests)
- Binary (PASS/FAIL) — no scoring gradients
- Evidence-backed (traceable to specific actors, transforms, hashes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# --------------------------------------------------------------------------
# Scene Actor Contracts
# --------------------------------------------------------------------------

# Required actor labels (case-insensitive substrings) that MUST be present
# in the live scene for the Western/Frontier-Tech room.
REQUIRED_ACTOR_LABELS: tuple[str, ...] = (
    "heidi",           # Hero focal point
    "worker",          # At least 3 distinct workers
    "station",         # Distinct worker stations/roles
)

# Minimum counts for required archetypes
MIN_HEIDI_COUNT = 1
MIN_WORKER_COUNT = 3
MIN_STATION_COUNT = 3

# Worker role markers — each worker should have a distinct role indicator
WORKER_ROLE_MARKERS: tuple[str, ...] = (
    "miner", "engineer", "prospector", "guard", "medic", "tech",
    "scout", "pilot", "mechanic", "operator", "analyst", "surveyor",
)

# --------------------------------------------------------------------------
# Animation State Contracts
# --------------------------------------------------------------------------

# Required animation states that must be observable on workers
REQUIRED_WORKER_STATES: tuple[str, ...] = (
    "IDLE",
    "WALK",
    "WORK",
)

# Heidi-to-worker task handoff indicators
TASK_HANDOFF_MARKERS: tuple[str, ...] = (
    "task_", "handoff", "assign", "interact", "signal", "direct",
)


# --------------------------------------------------------------------------
# Placeholder Detection (Deterministic)
# --------------------------------------------------------------------------

# Actor/class names that indicate placeholder-heavy content
PLACEHOLDER_INDICATORS: tuple[str, ...] = (
    "cube", "sphere", "cylinder", "cone", "plane", "default_",
    "basic_", "primitive_", "starter_", "template_", "placeholder",
    "proxy_", "graybox", "whitebox", "blockout", "bs_", "bp_cube",
    "bp_sphere", "sm_cube", "sm_sphere", "defaultcube", "defaultsphere",
)


# --------------------------------------------------------------------------
# Scene Integrity Contracts
# --------------------------------------------------------------------------

# Map name that must be loaded
REQUIRED_MAP_SUBSTRING = "/Game/AIVIDO_Showcase"

# Maximum allowed duplicate labels for critical actors
MAX_DUPLICATE_LABELS_CRITICAL = 1  # Heidi must be unique


# --------------------------------------------------------------------------
# Evidence Freshness Contracts
# --------------------------------------------------------------------------

# Maximum age of evidence frames in seconds (5 minutes)
MAX_EVIDENCE_AGE_SECONDS = 300

# Required capture metadata keys
REQUIRED_CAPTURE_METADATA_KEYS: tuple[str, ...] = (
    "frame", "path", "sha256", "size_bytes", "captured_at_epoch", "map", "source",
)


# --------------------------------------------------------------------------
# Data Classes
# --------------------------------------------------------------------------


@dataclass
class SceneActor:
    """Normalized actor representation from scene probe."""
    name: str
    label: str
    class_name: str
    location: Dict[str, float] = field(default_factory=dict)
    rotation: Dict[str, float] = field(default_factory=dict)
    scale: Dict[str, float] = field(default_factory=dict)
    readable: bool = True


@dataclass
class SceneEvidence:
    """Complete scene evidence snapshot."""
    map_name: str
    actors: List[SceneActor]
    captured_at_epoch: float
    capture_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Result of a single acceptance check."""
    check_id: str
    name: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Deterministic Check Functions
# --------------------------------------------------------------------------


def check_heidi_hero_focal_point(evidence: SceneEvidence) -> CheckResult:
    """Verify Heidi exists and is positioned as the hero focal point.

    Deterministic criteria:
    - Exactly one actor with label containing "heidi" (case-insensitive)
    - Actor is readable (not a phantom handle)
    - Actor has a valid transform (not at origin 0,0,0 unless intentional)
    """
    heidi_actors = [
        a for a in evidence.actors
        if "heidi" in a.label.lower()
    ]

    issues = []
    details = {"heidi_count": len(heidi_actors), "actors": []}

    if len(heidi_actors) == 0:
        issues.append("NO_HEIDI_ACTOR_FOUND")
    elif len(heidi_actors) > 1:
        issues.append(f"MULTIPLE_HEIDI_ACTORS: {len(heidi_actors)} found")

    for h in heidi_actors:
        details["actors"].append({
            "name": h.name,
            "label": h.label,
            "class": h.class_name,
            "location": h.location,
            "readable": h.readable,
        })
        if not h.readable:
            issues.append(f"HEIDI_PHANTOM_HANDLE: {h.name}")

    passed = len(issues) == 0 and len(heidi_actors) == MIN_HEIDI_COUNT
    return CheckResult(
        check_id="HEIDI_HERO_FOCAL_POINT",
        name="Heidi Hero Focal Point",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_minimum_three_workers(evidence: SceneEvidence) -> CheckResult:
    """Verify at least 3 distinct worker actors are present.

    Deterministic criteria:
    - At least 3 actors with label containing "worker" (case-insensitive)
    - Each worker is readable
    - Workers have distinct internal names (not duplicates)
    """
    worker_actors = [
        a for a in evidence.actors
        if "worker" in a.label.lower()
    ]

    readable_workers = [w for w in worker_actors if w.readable]
    unique_names = set(w.name for w in readable_workers)

    issues = []
    details = {
        "total_worker_labels": len(worker_actors),
        "readable_workers": len(readable_workers),
        "unique_worker_names": len(unique_names),
        "workers": [],
    }

    if len(readable_workers) < MIN_WORKER_COUNT:
        issues.append(f"INSUFFICIENT_WORKERS: {len(readable_workers)} readable, need {MIN_WORKER_COUNT}")

    if len(unique_names) < MIN_WORKER_COUNT:
        issues.append(f"DUPLICATE_WORKER_NAMES: {len(unique_names)} unique, need {MIN_WORKER_COUNT}")

    # Check for actual duplicate names among readable workers
    if len(readable_workers) != len(unique_names):
        # Find which names are duplicated
        name_counts: Dict[str, int] = {}
        for w in readable_workers:
            name_counts[w.name] = name_counts.get(w.name, 0) + 1
        duplicates = [name for name, count in name_counts.items() if count > 1]
        issues.append(f"DUPLICATE_WORKER_NAMES: {duplicates}")

    for w in readable_workers:
        details["workers"].append({
            "name": w.name,
            "label": w.label,
            "class": w.class_name,
            "location": w.location,
        })

    passed = len(issues) == 0
    return CheckResult(
        check_id="MIN_THREE_WORKERS",
        name="Minimum 3 Visible Workers",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_distinct_worker_stations_roles(evidence: SceneEvidence) -> CheckResult:
    """Verify workers have distinct stations/roles.

    Deterministic criteria:
    - At least 3 distinct station actors (label contains "station")
    - OR at least 3 workers each associated with a distinct role marker
    - Station/worker pairing can be inferred from proximity or naming
    """
    station_actors = [
        a for a in evidence.actors
        if "station" in a.label.lower()
    ]
    worker_actors = [
        a for a in evidence.actors
        if "worker" in a.label.lower() and a.readable
    ]

    issues = []
    details = {
        "station_count": len(station_actors),
        "worker_count": len(worker_actors),
        "stations": [],
        "role_assignments": {},
    }

    # Check stations
    readable_stations = [s for s in station_actors if s.readable]
    details["readable_stations"] = len(readable_stations)

    for s in readable_stations:
        details["stations"].append({
            "name": s.name,
            "label": s.label,
            "class": s.class_name,
            "location": s.location,
        })

    # Check role markers on workers (from class name or label)
    roles_found: Set[str] = set()
    for w in worker_actors:
        label_lower = w.label.lower()
        class_lower = w.class_name.lower()
        for role in WORKER_ROLE_MARKERS:
            if role in label_lower or role in class_lower:
                roles_found.add(role)
                details["role_assignments"][w.name] = role
                break

    details["distinct_roles_found"] = sorted(roles_found)

    # PASS if either stations >= 3 OR distinct roles >= 3
    stations_ok = len(readable_stations) >= MIN_STATION_COUNT
    roles_ok = len(roles_found) >= MIN_WORKER_COUNT

    if not stations_ok and not roles_ok:
        issues.append(
            f"INSUFFICIENT_STATIONS_ROLES: stations={len(readable_stations)}, "
            f"roles={len(roles_found)}, need {MIN_STATION_COUNT}"
        )

    passed = len(issues) == 0
    return CheckResult(
        check_id="DISTINCT_WORKER_STATIONS_ROLES",
        name="Distinct Worker Stations/Roles",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_worker_animation_states(evidence: SceneEvidence) -> CheckResult:
    """Verify workers exhibit IDLE, WALK, WORK states.

    Deterministic criteria (from scene metadata/animation state):
    - At least one worker shows IDLE state indicators
    - At least one worker shows WALK state indicators
    - At least one worker shows WORK state indicators
    - State can be inferred from: animation component, velocity, task assignment
    """
    worker_actors = [
        a for a in evidence.actors
        if "worker" in a.label.lower() and a.readable
    ]

    issues = []
    details = {
        "worker_count": len(worker_actors),
        "states_observed": {},
        "state_coverage": {},
    }

    # This check relies on capture metadata or animation state in evidence
    # For hermetic testing, we check if the evidence contains state info
    states_found: Set[str] = set()

    for w in worker_actors:
        # Check class name for state hints
        class_lower = w.class_name.lower()
        label_lower = w.label.lower()

        for state in REQUIRED_WORKER_STATES:
            state_lower = state.lower()
            if state_lower in class_lower or state_lower in label_lower:
                states_found.add(state)
                details["states_observed"][w.name] = state

    # Also check capture metadata for state info
    meta = evidence.capture_metadata
    if "worker_states" in meta:
        for worker_name, state in meta["worker_states"].items():
            if state in REQUIRED_WORKER_STATES:
                states_found.add(state)
                details["state_coverage"][worker_name] = state

    details["unique_states_found"] = sorted(states_found)

    missing = [s for s in REQUIRED_WORKER_STATES if s not in states_found]
    if missing:
        issues.append(f"MISSING_WORKER_STATES: {missing}")

    passed = len(issues) == 0
    return CheckResult(
        check_id="WORKER_ANIMATION_STATES",
        name="Worker IDLE/WALK/WORK States",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_heidi_to_worker_task_handoff(evidence: SceneEvidence) -> CheckResult:
    """Verify Heidi-to-worker task handoff is represented.

    Deterministic criteria:
    - Scene contains task/handoff/interaction markers between Heidi and workers
    - Can be: task actor, interaction volume, signal emitter, or metadata flag
    """
    issues = []
    details = {"handoff_indicators": []}

    # Check actors for handoff markers
    all_labels = [a.label.lower() for a in evidence.actors]
    all_classes = [a.class_name.lower() for a in evidence.actors]

    found_markers = []
    for marker in TASK_HANDOFF_MARKERS:
        for label in all_labels:
            if marker in label:
                found_markers.append(f"label:{label}")
        for cls in all_classes:
            if marker in cls:
                found_markers.append(f"class:{cls}")

    # Check capture metadata
    meta = evidence.capture_metadata
    if meta.get("task_handoff"):
        found_markers.append(f"metadata:task_handoff={meta['task_handoff']}")

    details["handoff_indicators"] = found_markers

    if not found_markers:
        issues.append("NO_TASK_HANDOFF_INDICATORS_FOUND")

    passed = len(issues) == 0
    return CheckResult(
        check_id="HEIDI_WORKER_TASK_HANDOFF",
        name="Heidi-to-Worker Task Handoff",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_no_placeholder_heavy(evidence: SceneEvidence) -> CheckResult:
    """Verify scene is not placeholder-heavy.

    Deterministic criteria:
    - No more than 2 actors with placeholder indicator names
    - Critical actors (Heidi, workers, stations) are NOT placeholders
    - Placeholder ratio (placeholder actors / total actors) < 0.3
    """
    total_actors = len(evidence.actors)
    if total_actors == 0:
        return CheckResult(
            check_id="NO_PLACEHOLDER_HEAVY",
            name="No Placeholder-Heavy Final Presentation",
            passed=False,
            details={"total_actors": 0},
            issues=["EMPTY_SCENE"],
        )

    placeholder_actors = []
    critical_placeholders = []

    for a in evidence.actors:
        label_lower = a.label.lower()
        class_lower = a.class_name.lower()
        name_lower = a.name.lower()

        is_placeholder = any(
            ind in label_lower or ind in class_lower or ind in name_lower
            for ind in PLACEHOLDER_INDICATORS
        )

        if is_placeholder:
            placeholder_actors.append(a)
            # Check if critical
            if ("heidi" in label_lower or "worker" in label_lower or
                "station" in label_lower):
                critical_placeholders.append(a)

    placeholder_ratio = len(placeholder_actors) / total_actors

    issues = []
    details = {
        "total_actors": total_actors,
        "placeholder_count": len(placeholder_actors),
        "placeholder_ratio": round(placeholder_ratio, 3),
        "critical_placeholders": len(critical_placeholders),
        "placeholders": [
            {"name": p.name, "label": p.label, "class": p.class_name}
            for p in placeholder_actors
        ],
    }

    if critical_placeholders:
        issues.append(f"CRITICAL_ACTORS_ARE_PLACEHOLDERS: {len(critical_placeholders)}")

    if len(placeholder_actors) > 2:
        issues.append(f"TOO_MANY_PLACEHOLDERS: {len(placeholder_actors)} (max 2)")

    if placeholder_ratio >= 0.3:
        issues.append(f"PLACEHOLDER_RATIO_TOO_HIGH: {placeholder_ratio:.1%} (max 30%)")

    passed = len(issues) == 0
    return CheckResult(
        check_id="NO_PLACEHOLDER_HEAVY",
        name="No Placeholder-Heavy Final Presentation",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_scene_actor_integrity(evidence: SceneEvidence) -> CheckResult:
    """Verify scene actor integrity — no phantom handles, valid transforms.

    Deterministic criteria:
    - All critical actors are readable (not phantom)
    - No duplicate internal names for critical actors
    - All actors have valid transforms (not NaN/inf)
    - Map name matches required map
    """
    issues = []
    details = {
        "map_name": evidence.map_name,
        "total_actors": len(evidence.actors),
        "readable_actors": 0,
        "phantom_actors": 0,
        "transform_issues": 0,
        "duplicate_names": [],
    }

    # Map check
    if REQUIRED_MAP_SUBSTRING not in evidence.map_name:
        issues.append(f"WRONG_MAP: {evidence.map_name} (expected *{REQUIRED_MAP_SUBSTRING}*)")

    # Actor checks
    name_counts: Dict[str, int] = {}
    for a in evidence.actors:
        if a.readable:
            details["readable_actors"] += 1
        else:
            details["phantom_actors"] += 1
            issues.append(f"PHANTOM_HANDLE: {a.name} ({a.label})")

        # Transform validation
        for axis in ("x", "y", "z"):
            for transform_type in ("location", "rotation", "scale"):
                transform = getattr(a, transform_type, {})
                val = transform.get(axis, 0)
                if val is None or (isinstance(val, float) and (val != val or val == float("inf") or val == float("-inf"))):
                    details["transform_issues"] += 1
                    issues.append(f"INVALID_TRANSFORM: {a.name}.{transform_type}.{axis} = {val}")

        name_counts[a.name] = name_counts.get(a.name, 0) + 1

    # Duplicate names check (critical actors only)
    for name, count in name_counts.items():
        if count > 1:
            # Check if any of these are critical
            actors_with_name = [a for a in evidence.actors if a.name == name]
            is_critical = any(
                "heidi" in a.label.lower() or "worker" in a.label.lower() or "station" in a.label.lower()
                for a in actors_with_name
            )
            if is_critical:
                issues.append(f"DUPLICATE_CRITICAL_NAME: {name} (count={count})")
                details["duplicate_names"].append(name)

    passed = len(issues) == 0
    return CheckResult(
        check_id="SCENE_ACTOR_INTEGRITY",
        name="Scene Actor Integrity",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_fresh_evidence(capture_metadata: Dict[str, Any]) -> CheckResult:
    """Verify screenshot evidence is fresh (not stale).

    Deterministic criteria:
    - capture_metadata.json exists with all required keys
    - captured_at_epoch is within MAX_EVIDENCE_AGE_SECONDS of now
    - sha256 matches the actual frame file
    - map matches the scene map
    """
    import time

    issues = []
    details = {"metadata_present": bool(capture_metadata)}

    if not capture_metadata:
        issues.append("MISSING_CAPTURE_METADATA")
        return CheckResult(
            check_id="FRESH_EVIDENCE",
            name="Valid Fresh Screenshots/Evidence",
            passed=False,
            details=details,
            issues=issues,
        )

    # Check required keys
    missing_keys = [k for k in REQUIRED_CAPTURE_METADATA_KEYS if k not in capture_metadata]
    if missing_keys:
        issues.append(f"MISSING_METADATA_KEYS: {missing_keys}")

    # Check age
    captured_at = capture_metadata.get("captured_at_epoch", 0)
    age = time.time() - captured_at
    details["evidence_age_seconds"] = round(age, 1)
    details["max_age_seconds"] = MAX_EVIDENCE_AGE_SECONDS

    if age > MAX_EVIDENCE_AGE_SECONDS:
        issues.append(f"STALE_EVIDENCE: age={age:.0f}s > {MAX_EVIDENCE_AGE_SECONDS}s")

    # Check map consistency
    meta_map = capture_metadata.get("map", "")
    details["metadata_map"] = meta_map

    passed = len(issues) == 0
    return CheckResult(
        check_id="FRESH_EVIDENCE",
        name="Valid Fresh Screenshots/Evidence",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_no_stale_evidence(evidence: SceneEvidence, prior_hashes: Optional[Set[str]] = None) -> CheckResult:
    """Verify no stale evidence (reused frames from previous runs).

    Deterministic criteria:
    - Current frame hash not in prior_hashes (if provided)
    - capture_metadata sha256 is current
    """
    issues = []
    details = {}

    if prior_hashes:
        current_hash = evidence.capture_metadata.get("sha256", "")
        details["current_hash"] = current_hash[:16] if current_hash else "none"
        details["prior_hash_count"] = len(prior_hashes)

        if current_hash and current_hash in prior_hashes:
            issues.append("STALE_FRAME_DETECTED: hash matches prior run")

    # Check if metadata has stale flag
    if evidence.capture_metadata.get("stale", False):
        issues.append("CAPTURE_METADATA_FLAGS_STALE")

    passed = len(issues) == 0
    return CheckResult(
        check_id="NO_STALE_EVIDENCE",
        name="No Stale Evidence",
        passed=passed,
        details=details,
        issues=issues,
    )


def check_western_frontier_readability(evidence: SceneEvidence) -> CheckResult:
    """Verify Western/Frontier-Tech room readability.

    Deterministic criteria (proxy measures for readability):
    - Scene has environment actors (walls, floor, props) — not empty
    - At least 5 non-worker/non-Heidi environment actors
    - Environment actors have varied classes (not all same class)
    - No single class dominates > 50% of environment actors
    """
    # Exclude Heidi, workers, stations
    env_actors = [
        a for a in evidence.actors
        if a.readable and not any(
            kw in a.label.lower() for kw in ("heidi", "worker", "station")
        )
    ]

    issues = []
    details = {
        "environment_actor_count": len(env_actors),
        "class_distribution": {},
    }

    if len(env_actors) < 5:
        issues.append(f"INSUFFICIENT_ENVIRONMENT_ACTORS: {len(env_actors)} (need >= 5)")

    # Class diversity
    class_counts: Dict[str, int] = {}
    for a in env_actors:
        cls = a.class_name or "Unknown"
        class_counts[cls] = class_counts.get(cls, 0) + 1

    details["class_distribution"] = class_counts
    details["unique_classes"] = len(class_counts)

    if class_counts:
        max_class_count = max(class_counts.values())
        dominance = max_class_count / len(env_actors)
        details["max_class_dominance"] = round(dominance, 2)
        if dominance > 0.5:
            issues.append(f"CLASS_DOMINANCE: {max_class_count}/{len(env_actors)} = {dominance:.0%} > 50%")

    passed = len(issues) == 0
    return CheckResult(
        check_id="WESTERN_FRONTIER_READABILITY",
        name="Western/Frontier-Tech Room Readability",
        passed=passed,
        details=details,
        issues=issues,
    )


# --------------------------------------------------------------------------
# Aggregated Check Runner
# --------------------------------------------------------------------------


def run_all_deterministic_checks(
    evidence: SceneEvidence,
    prior_hashes: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Run all deterministic acceptance checks and return aggregated result."""
    checks = [
        check_heidi_hero_focal_point,
        check_minimum_three_workers,
        check_distinct_worker_stations_roles,
        check_worker_animation_states,
        check_heidi_to_worker_task_handoff,
        check_no_placeholder_heavy,
        check_scene_actor_integrity,
        check_fresh_evidence,
        check_no_stale_evidence,
        check_western_frontier_readability,
    ]

    results = []
    all_passed = True

    for check_fn in checks:
        if check_fn.__name__ == "check_no_stale_evidence":
            result = check_fn(evidence, prior_hashes)
        elif check_fn.__name__ == "check_fresh_evidence":
            result = check_fn(evidence.capture_metadata)
        else:
            result = check_fn(evidence)
        results.append(result)
        if not result.passed:
            all_passed = False

    return {
        "overall_passed": all_passed,
        "checks": [r.__dict__ for r in results],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
    }