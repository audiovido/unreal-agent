#!/usr/bin/env python3
"""AIVIDO Visual RC Acceptance Gate — Read-only verification of Visual Vertical Slice V1.

This gate is READ-ONLY. It never mutates Unreal or runtime state during validation.
All checks are deterministic and hermetically testable.

Verifies 10 objective acceptance criteria for the Western/Frontier-Tech room:
  1. HEIDI_HERO_FOCAL_POINT       — Heidi exists, unique, readable, positioned as hero
  2. MIN_THREE_WORKERS            — At least 3 distinct, readable worker actors
  3. DISTINCT_WORKER_STATIONS_ROLES — 3+ stations OR 3+ distinct worker roles
  4. WORKER_ANIMATION_STATES      — IDLE, WALK, WORK states all observable
  5. HEIDI_WORKER_TASK_HANDOFF    — Task/handoff/interaction markers present
  6. NO_PLACEHOLDER_HEAVY         — Scene not dominated by placeholder assets
  7. SCENE_ACTOR_INTEGRITY        — No phantoms, valid transforms, correct map
  8. FRESH_EVIDENCE               — Screenshot metadata fresh, complete, matching
  9. NO_STALE_EVIDENCE            — Frame hash not reused from prior runs
  10. WESTERN_FRONTIER_READABILITY — Environment actors present, diverse, readable

Output: Machine-readable JSON + concise human report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766

# READ-ONLY live scene probe
SCENE_PROBE_CODE = '''
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    __bridge_result__ = {"ok": False, "error": "editor_world_unavailable"}
else:
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    result_actors = []
    read_errors = []
    for a in actors:
        try:
            name = str(a.get_name() or "")
            label = str(a.get_actor_label() or "")
            cls = str(a.get_class().get_name() if a.get_class() else "")
            transform = a.get_actor_transform()
            loc = transform.translation
            rot = transform.rotation
            scale = transform.scale3d
            result_actors.append({
                "name": name,
                "label": label,
                "class": cls,
                "location": {"x": float(loc.x), "y": float(loc.y), "z": float(loc.z)},
                "rotation": {"x": float(rot.x), "y": float(rot.y), "z": float(rot.z), "w": float(rot.w)},
                "scale": {"x": float(scale.x), "y": float(scale.y), "z": float(scale.z)},
                "readable": True,
            })
        except Exception as exc:
            read_errors.append({"name": str(a.get_name() or "unknown"), "error": type(exc).__name__})
    __bridge_result__ = {
        "ok": True,
        "map": str(world.get_path_name() or ""),
        "actor_count": len(result_actors),
        "read_errors": read_errors,
        "actors": result_actors,
    }
'''

CHECK_NAMES = {
    "HEIDI_HERO_FOCAL_POINT": "Heidi Hero Focal Point",
    "MIN_THREE_WORKERS": "Minimum 3 Visible Workers",
    "DISTINCT_WORKER_STATIONS_ROLES": "Distinct Worker Stations/Roles",
    "WORKER_ANIMATION_STATES": "Worker IDLE/WALK/WORK States",
    "HEIDI_WORKER_TASK_HANDOFF": "Heidi-to-Worker Task Handoff",
    "NO_PLACEHOLDER_HEAVY": "No Placeholder-Heavy Final Presentation",
    "SCENE_ACTOR_INTEGRITY": "Scene Actor Integrity",
    "FRESH_EVIDENCE": "Valid Fresh Screenshots/Evidence",
    "NO_STALE_EVIDENCE": "No Stale Evidence",
    "WESTERN_FRONTIER_READABILITY": "Western/Frontier-Tech Room Readability",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VisualRCGate:
    def __init__(
        self,
        json_out: str | None = None,
        evidence_dir: str | None = None,
        prior_hashes_path: str | None = None,
    ):
        self.json_out = json_out
        self.evidence_dir = Path(evidence_dir) if evidence_dir else ROOT / "evidence"
        self.prior_hashes_path = Path(prior_hashes_path) if prior_hashes_path else None
        self.report: Dict[str, Any] = {
            "gate": "aivido_visual_rc_gate",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": {},
            "reasons": [],
            "verdict": "PASS",
        }
        self._scene_evidence = None
        self._prior_hashes: Set[str] = set()

    def _fail(self, check_id: str, reason: str):
        self.report["reasons"].append(f"{check_id}:{reason}")
        self.report["checks"][check_id] = {"ok": False, "reason": reason}

    def _pass(self, check_id: str, detail: Dict | None = None):
        self.report["checks"][check_id] = {"ok": True, **(detail or {})}

    def _load_prior_hashes(self) -> None:
        """Load prior frame hashes from evidence directory or explicit file."""
        if self.prior_hashes_path and self.prior_hashes_path.exists():
            try:
                data = json.loads(self.prior_hashes_path.read_text())
                self._prior_hashes = set(data.get("hashes", []))
            except Exception:
                self._prior_hashes = set()
        elif self.evidence_dir.exists():
            # Scan for verdict.json files with frame hashes
            for verdict_file in self.evidence_dir.glob("**/verdict.json"):
                try:
                    data = json.loads(verdict_file.read_text())
                    frame = data.get("final", {}).get("frame") or data.get("frame")
                    if frame and "sha256" in frame:
                        self._prior_hashes.add(frame["sha256"])
                except Exception:
                    pass

    def _probe_live_scene(self) -> Dict[str, Any] | None:
        """Execute read-only scene probe via Unreal bridge."""
        try:
            s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=10)
            s.sendall(json.dumps({"type": "python", "code": SCENE_PROBE_CODE}).encode() + b"\n")
            s.settimeout(30)
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
            data = json.loads(buf.decode().strip())
            return data.get("result") if isinstance(data.get("result"), dict) else {}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _load_latest_capture_metadata(self) -> Dict[str, Any]:
        """Find and load the most recent capture_metadata.json."""
        if not self.evidence_dir.exists():
            return {}
        metadata_files = list(self.evidence_dir.glob("**/capture_metadata.json"))
        if not metadata_files:
            return {}
        # Get most recent by mtime
        latest = max(metadata_files, key=lambda f: f.stat().st_mtime)
        try:
            return json.loads(latest.read_text())
        except Exception:
            return {}

    def _build_scene_evidence(self, probe_result: Dict[str, Any], capture_meta: Dict[str, Any]) -> Any:
        """Convert probe result to SceneEvidence dataclass."""
        from tools.visual_rc.scene_criteria import SceneEvidence, SceneActor

        actors = []
        for a in probe_result.get("actors", []):
            actors.append(SceneActor(
                name=a.get("name", ""),
                label=a.get("label", ""),
                class_name=a.get("class", ""),
                location=a.get("location", {}),
                rotation=a.get("rotation", {}),
                scale=a.get("scale", {}),
                readable=a.get("readable", True),
            ))

        return SceneEvidence(
            map_name=probe_result.get("map", ""),
            actors=actors,
            captured_at_epoch=capture_meta.get("captured_at_epoch", time.time()),
            capture_metadata=capture_meta,
        )

    # ------------------------------------------------------------------
    # Individual Checks (thin wrappers around deterministic criteria)
    # ------------------------------------------------------------------

    def check_heidi_hero_focal_point(self) -> None:
        from tools.visual_rc.scene_criteria import check_heidi_hero_focal_point
        result = check_heidi_hero_focal_point(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_min_three_workers(self) -> None:
        from tools.visual_rc.scene_criteria import check_minimum_three_workers
        result = check_minimum_three_workers(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_distinct_worker_stations_roles(self) -> None:
        from tools.visual_rc.scene_criteria import check_distinct_worker_stations_roles
        result = check_distinct_worker_stations_roles(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_worker_animation_states(self) -> None:
        from tools.visual_rc.scene_criteria import check_worker_animation_states
        result = check_worker_animation_states(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_heidi_worker_task_handoff(self) -> None:
        from tools.visual_rc.scene_criteria import check_heidi_to_worker_task_handoff
        result = check_heidi_to_worker_task_handoff(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_no_placeholder_heavy(self) -> None:
        from tools.visual_rc.scene_criteria import check_no_placeholder_heavy
        result = check_no_placeholder_heavy(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_scene_actor_integrity(self) -> None:
        from tools.visual_rc.scene_criteria import check_scene_actor_integrity
        result = check_scene_actor_integrity(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_fresh_evidence(self) -> None:
        from tools.visual_rc.scene_criteria import check_fresh_evidence
        result = check_fresh_evidence(self._scene_evidence.capture_metadata)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_no_stale_evidence(self) -> None:
        from tools.visual_rc.scene_criteria import check_no_stale_evidence
        result = check_no_stale_evidence(self._scene_evidence, self._prior_hashes)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def check_western_frontier_readability(self) -> None:
        from tools.visual_rc.scene_criteria import check_western_frontier_readability
        result = check_western_frontier_readability(self._scene_evidence)
        if result.passed:
            self._pass(result.check_id, result.details)
        else:
            self._fail(result.check_id, "; ".join(result.issues))

    def run_all(self) -> int:
        """Run all 10 checks."""
        # Load prior hashes for stale detection
        self._load_prior_hashes()

        # Probe live scene
        probe_result = self._probe_live_scene()
        if not probe_result or not probe_result.get("ok"):
            self._fail("SCENE_PROBE", f"Scene probe failed: {probe_result.get('error') if probe_result else 'no response'}")
            self.report["verdict"] = "FAIL"
            self._output()
            return 42

        # Load capture metadata
        capture_meta = self._load_latest_capture_metadata()

        # Build scene evidence
        self._scene_evidence = self._build_scene_evidence(probe_result, capture_meta)

        # Run checks
        checks = [
            ("1", self.check_heidi_hero_focal_point),
            ("2", self.check_min_three_workers),
            ("3", self.check_distinct_worker_stations_roles),
            ("4", self.check_worker_animation_states),
            ("5", self.check_heidi_worker_task_handoff),
            ("6", self.check_no_placeholder_heavy),
            ("7", self.check_scene_actor_integrity),
            ("8", self.check_fresh_evidence),
            ("9", self.check_no_stale_evidence),
            ("10", self.check_western_frontier_readability),
        ]

        for num, check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(f"CHECK_{num}", f"unexpected error: {type(exc).__name__}: {exc}")

        self.report["verdict"] = "PASS" if not self.report["reasons"] else "FAIL"
        self._output()
        return 0 if self.report["verdict"] == "PASS" else 42

    def _output(self) -> None:
        text = json.dumps(self.report, indent=2, default=str)
        print(text)
        if self.json_out:
            out = Path(self.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="AIVIDO Visual RC Acceptance Gate")
    ap.add_argument("--json-out", default="", help="Write JSON report to file")
    ap.add_argument("--evidence-dir", default="", help="Evidence directory to scan")
    ap.add_argument("--prior-hashes", default="", help="JSON file with prior frame hashes")
    ap.add_argument("--check", default="", help="Run only specific check number (1-10)")
    args = ap.parse_args()

    gate = VisualRCGate(
        json_out=args.json_out if args.json_out else None,
        evidence_dir=args.evidence_dir if args.evidence_dir else None,
        prior_hashes_path=args.prior_hashes if args.prior_hashes else None,
    )

    if args.check:
        check_map = {
            "1": gate.check_heidi_hero_focal_point,
            "2": gate.check_min_three_workers,
            "3": gate.check_distinct_worker_stations_roles,
            "4": gate.check_worker_animation_states,
            "5": gate.check_heidi_worker_task_handoff,
            "6": gate.check_no_placeholder_heavy,
            "7": gate.check_scene_actor_integrity,
            "8": gate.check_fresh_evidence,
            "9": gate.check_no_stale_evidence,
            "10": gate.check_western_frontier_readability,
        }
        if args.check in check_map:
            # Still need scene evidence for single check
            probe_result = gate._probe_live_scene()
            capture_meta = gate._load_latest_capture_metadata()
            gate._load_prior_hashes()
            if probe_result and probe_result.get("ok"):
                gate._scene_evidence = gate._build_scene_evidence(probe_result, capture_meta)
                check_map[args.check]()
            gate.report["verdict"] = "PASS" if not gate.report["reasons"] else "FAIL"
            text = json.dumps(gate.report, indent=2, default=str)
            print(text)
            return 0 if gate.report["verdict"] == "PASS" else 42
        else:
            print(f"Unknown check: {args.check}", file=sys.stderr)
            return 2

    return gate.run_all()


if __name__ == "__main__":
    raise SystemExit(main())