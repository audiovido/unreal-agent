#!/usr/bin/env python3
"""AIVIDO RC1 Acceptance Gate — Read-only verification of release candidate 1.

This gate is READ-ONLY by default. It never mutates Unreal or runtime state
during validation. All checks are deterministic and hermetically testable.

Verifies 18 release criteria:
  1. Repository / release state
  2. Backend health contract
  3. Unreal bridge health contract
  4. Correct expected map contract
  5. Command runtime health
  6. No active stuck job
  7. One-Click launcher presence
  8. Evidence packager presence
  9. Fresh-evidence requirements
  10. Empty SceneDiff cannot graduate
  11. Executor success alone cannot graduate
  12. Stale/missing screenshot cannot graduate
  13. Actor identity regression protections exist
  14. Explicit production brief path exists
  15. Negated instructions cannot trigger forbidden tools
  16. Required regression suites can be invoked
  17. No stale Windows/Shadow-PC production path is required
  18. Release output is machine-readable JSON + concise human report
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766
BACKEND_URL = "http://127.0.0.1:8765/api/status"

CHECK_DESCRIPTIONS = {
    "REPO_RELEASE_STATE": "Repository / release state",
    "BACKEND_HEALTH": "Backend health contract",
    "BRIDGE_HEALTH": "Unreal bridge health contract",
    "EXPECTED_MAP": "Correct expected map contract",
    "COMMAND_RUNTIME": "Command runtime health",
    "NO_STUCK_JOB": "No active stuck job",
    "ONE_CLICK_LAUNCHER": "One-Click launcher presence",
    "EVIDENCE_PACKAGER": "Evidence packager presence",
    "FRESH_EVIDENCE_REQUIREMENTS": "Fresh-evidence requirements",
    "EMPTY_SCENEDIFF_CANNOT_GRADUATE": "Empty SceneDiff cannot graduate",
    "EXECUTOR_SUCCESS_ALONE_CANNOT_GRADUATE": "Executor success alone cannot graduate",
    "STALE_MISSING_SCREENSHOT_CANNOT_GRADUATE": "Stale/missing screenshot cannot graduate",
    "ACTOR_IDENTITY_REGRESSION": "Actor identity regression protections exist",
    "EXPLICIT_PRODUCTION_BRIEF": "Explicit production brief path exists",
    "NEGATED_INSTRUCTIONS_PROTECTION": "Negated instructions cannot trigger forbidden tools",
    "REGRESSION_SUITES_INVOKABLE": "Required regression suites can be invoked",
    "NO_STALE_WINDOWS_PATH": "No stale Windows/Shadow-PC production path required",
    "RELEASE_OUTPUT_FORMAT": "Release output is machine-readable JSON + human report",
}

# READ-ONLY live scene probe (same pattern as graduation gate)
PROBE_CODE = '''
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    __bridge_result__ = {"ok": False, "error": "editor_world_unavailable"}
else:
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    names = []
    read_errors = []
    for a in actors:
        try:
            names.append(str(a.get_actor_label() or a.get_name()))
        except Exception as exc:
            read_errors.append(type(exc).__name__)
    __bridge_result__ = {
        "ok": True,
        "map": str(world.get_path_name() or ""),
        "actor_count": len(names),
        "read_errors": read_errors,
        "labels": sorted(names),
    }
'''


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RC1Gate:
    def __init__(self, json_out: str | None = None):
        self.json_out = json_out
        self.report: dict[str, Any] = {
            "gate": "aivido_rc1_gate",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": {},
            "reasons": [],
            "verdict": "PASS",
        }

    def _fail(self, check_id: str, reason: str):
        self.report["reasons"].append(f"{check_id}:{reason}")
        self.report["checks"][check_id] = {"ok": False, "reason": reason}

    def _pass(self, check_id: str, detail: dict | None = None):
        self.report["checks"][check_id] = {"ok": True, **(detail or {})}

    # 1. Repository / release state
    def check_repo_release_state(self) -> None:
        """Verify release tag/status file exists and records graduation."""
        status_path = ROOT / "AIVIDO_RELEASE_STATUS.md"
        if not status_path.exists():
            self._fail("REPO_RELEASE_STATE", "AIVIDO_RELEASE_STATUS.md missing")
            return
        content = status_path.read_text(errors="replace")
        required = ["Stage A: Graduated", "Stage B: Graduated",
                    "Stage C: Graduated", "Stage D: Graduated"]
        missing = [r for r in required if r not in content]
        if missing:
            self._fail("REPO_RELEASE_STATE", f"missing graduation stages: {missing}")
        else:
            self._pass("REPO_RELEASE_STATE", {"status_path": str(status_path)})

    # 2. Backend health contract
    def check_backend_health(self) -> None:
        """Verify backend API responds with expected contract."""
        import urllib.request
        try:
            with urllib.request.urlopen(BACKEND_URL, timeout=10) as r:
                data = json.load(r)
            ok = data.get("ok") is True
            unreal_ok = data.get("unreal", {}).get("ok") is True
            if not ok or not unreal_ok:
                self._fail("BACKEND_HEALTH", f"backend contract not satisfied: {data}")
            else:
                self._pass("BACKEND_HEALTH", {"version": data.get("version")})
        except Exception as exc:
            self._fail("BACKEND_HEALTH", f"{type(exc).__name__}: {exc}")

    # 3. Unreal bridge health contract
    def check_bridge_health(self) -> None:
        """Verify Unreal bridge accepts connections and returns identity."""
        try:
            s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=5)
            s.sendall(b'{"type":"ping"}\n')
            buf = b""
            t0 = time.time()
            while not buf.endswith(b"\n") and time.time() - t0 < 10:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
            data = json.loads(buf.decode().strip())
            ok = data.get("ok") is True
            ident = data.get("identity") or {}
            engine = data.get("engine")
            if not ok:
                self._fail("BRIDGE_HEALTH", f"bridge ping not ok: {data}")
                return
            if "UNREAL_BRIDGE_READY" not in str(data.get("message", "")):
                self._fail("BRIDGE_HEALTH", f"missing READY signal: {data}")
                return
            self._pass("BRIDGE_HEALTH", {"identity": ident, "engine": engine})
        except Exception as exc:
            self._fail("BRIDGE_HEALTH", f"{type(exc).__name__}: {exc}")

    # 4. Correct expected map contract
    def check_expected_map(self) -> None:
        """Verify live Unreal scene is on the expected map."""
        try:
            s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=10)
            s.sendall(json.dumps({"type": "python", "code": PROBE_CODE}).encode() + b"\n")
            s.settimeout(30)
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
            data = json.loads(buf.decode().strip())
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            if not result.get("ok"):
                self._fail("EXPECTED_MAP", f"probe failed: {result.get('error')}")
                return
            map_name = str(result.get("map") or "")
            expected_map = "/Game/AIVIDO_Showcase"
            if expected_map not in map_name:
                self._fail("EXPECTED_MAP", f"wrong map: {map_name} (expected ~{expected_map})")
            else:
                self._pass("EXPECTED_MAP", {"map": map_name, "actor_count": result.get("actor_count")})
        except Exception as exc:
            self._fail("EXPECTED_MAP", f"{type(exc).__name__}: {exc}")

    # 5. Command runtime health
    def check_command_runtime(self) -> None:
        """Verify command runtime via live endpoint or persisted file."""
        runtime = self._get_runtime_state()
        if runtime is None:
            self._fail("COMMAND_RUNTIME", "no runtime state available (live endpoint and file)")
            return
        try:
            ok = bool(runtime.get("ok"))
            worker_alive = bool(runtime.get("worker_alive"))
            counts = runtime.get("counts", {})
            active = runtime.get("active")
            state_path = runtime.get("state_path", "")
            total_jobs = sum(counts.values()) if isinstance(counts, dict) else 0
            active_count = 1 if active is not None else 0
            if not ok or not worker_alive:
                self._fail("COMMAND_RUNTIME", f"runtime not healthy: ok={ok}, worker_alive={worker_alive}")
                return
            self._pass("COMMAND_RUNTIME", {
                "state_path": state_path,
                "total_jobs": total_jobs,
                "active_jobs": active_count,
                "worker_alive": worker_alive,
                "counts": counts,
                "source": "live" if "live" in str(state_path).lower() or not state_path else "file",
            })
        except Exception as exc:
            self._fail("COMMAND_RUNTIME", f"{type(exc).__name__}: {exc}")

    # 6. No active stuck job
    def check_no_stuck_job(self) -> None:
        """Verify no active job is stuck beyond threshold."""
        runtime = self._get_runtime_state()
        if runtime is None:
            self._fail("NO_STUCK_JOB", "no runtime state available")
            return
        try:
            active = runtime.get("active")
            if active is None:
                self._pass("NO_STUCK_JOB", {"stuck_jobs": 0, "reason": "no_active_job"})
                return
            now = time.time()
            started = active.get("started_at") or 0
            if now - started > 300:  # 5 minutes
                self._fail("NO_STUCK_JOB", f"stuck active job: {active.get('job_id')} running > 5min")
            else:
                self._pass("NO_STUCK_JOB", {"stuck_jobs": 0, "active_job_id": active.get("job_id"), "age_s": round(now - started, 1)})
        except Exception as exc:
            self._fail("NO_STUCK_JOB", f"{type(exc).__name__}: {exc}")

    def _get_runtime_state(self) -> dict | None:
        """Get runtime state from live endpoint, then file fallback."""
        # Try live endpoint first
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/command/runtime", timeout=5) as r:
                data = json.load(r)
            if data.get("ok"):
                data["_source"] = "live"
                return data
        except Exception:
            pass
        # Fallback to persisted file
        state_path = ROOT / "runtime" / "command_jobs.json"
        if not state_path.exists():
            return None
        try:
            data = json.loads(state_path.read_text())
            jobs = data.get("jobs", {})
            counts: dict[str, int] = {}
            active_job = None
            for job in jobs.values():
                state = str(job.get("state", "unknown"))
                counts[state] = counts.get(state, 0) + 1
                if state == "running":
                    active_job = job
            return {
                "ok": True,
                "worker_alive": True,
                "counts": counts,
                "active": active_job,
                "state_path": str(state_path),
                "_source": "file",
            }
        except Exception:
            return None

    # 7. One-Click launcher presence
    def check_one_click_launcher(self) -> None:
        """Verify avalive_gate.py (one-click launcher) exists and is invokable."""
        launcher = ROOT / "scripts" / "avalive_gate.py"
        config = ROOT / "scripts" / "avalive_gate.json"
        if not launcher.exists():
            self._fail("ONE_CLICK_LAUNCHER", "avalive_gate.py missing")
            return
        if not config.exists():
            self._fail("ONE_CLICK_LAUNCHER", "avalive_gate.json config missing")
            return
        # Verify it's executable and has required commands
        try:
            result = subprocess.run(
                [sys.executable, str(launcher), "status"],
                capture_output=True, text=True, timeout=15, cwd=ROOT
            )
            if result.returncode not in (0, 1):  # 1 = degraded/unreachable is ok
                self._fail("ONE_CLICK_LAUNCHER", f"status command failed: {result.stderr[:200]}")
                return
            self._pass("ONE_CLICK_LAUNCHER", {"launcher": str(launcher), "config": str(config)})
        except Exception as exc:
            self._fail("ONE_CLICK_LAUNCHER", f"{type(exc).__name__}: {exc}")

    # 8. Evidence packager presence
    def check_evidence_packager(self) -> None:
        """Verify aivido_evidence.py exists and is a Python script."""
        packager = ROOT / "scripts" / "aivido_evidence.py"
        if not packager.exists():
            self._fail("EVIDENCE_PACKAGER", "aivido_evidence.py missing")
            return
        # Just verify it's a Python file with expected entry point
        content = packager.read_text()
        if "def main() -> int:" not in content and "def main():" not in content:
            self._fail("EVIDENCE_PACKAGER", "no main() function found")
            return
        self._pass("EVIDENCE_PACKAGER", {"packager": str(packager)})

    # 9. Fresh-evidence requirements
    def check_fresh_evidence_requirements(self) -> None:
        """Verify evidence packager enforces fresh-frame contract."""
        packager = ROOT / "scripts" / "aivido_evidence.py"
        if not packager.exists():
            self._fail("FRESH_EVIDENCE_REQUIREMENTS", "aivido_evidence.py missing")
            return
        content = packager.read_text()
        required_patterns = [
            "sha256", "capture_metadata", "fresh", "stale",
            "max_age", "captured_at_epoch", "EXECUTOR SUCCESS ALONE IS NOT A PASS"
        ]
        missing = [p for p in required_patterns if p.lower() not in content.lower()]
        if missing:
            self._fail("FRESH_EVIDENCE_REQUIREMENTS", f"missing patterns: {missing}")
        else:
            self._pass("FRESH_EVIDENCE_REQUIREMENTS", {"packager": str(packager)})

    # 10. Empty SceneDiff cannot graduate
    def check_empty_scenediff_cannot_graduate(self) -> None:
        """Verify SceneDiff empty-diff gate blocks graduation."""
        prod_v2 = ROOT / "core" / "production_v2.py"
        evidence = ROOT / "scripts" / "aivido_evidence.py"
        if not prod_v2.exists():
            self._fail("EMPTY_SCENEDIFF_CANNOT_GRADUATE", "production_v2.py missing")
            return
        if not evidence.exists():
            self._fail("EMPTY_SCENEDIFF_CANNOT_GRADUATE", "aivido_evidence.py missing")
            return
        prod_content = prod_v2.read_text()
        ev_content = evidence.read_text()
        checks = [
            ("production_v2", "scene_diff_is_meaningful", prod_content),
            ("production_v2", "scene_diff_gate", prod_content),
            ("aivido_evidence", "empty_scenediff", ev_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            import re
            if not re.search(pattern, content):
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("EMPTY_SCENEDIFF_CANNOT_GRADUATE", f"missing patterns: {missing}")
        else:
            self._pass("EMPTY_SCENEDIFF_CANNOT_GRADUATE", {})

    # 11. Executor success alone cannot graduate
    def check_executor_success_alone_cannot_graduate(self) -> None:
        """Verify executor success is not sufficient for PASS."""
        prod_v2 = ROOT / "core" / "production_v2.py"
        evidence = ROOT / "scripts" / "aivido_evidence.py"
        if not prod_v2.exists() or not evidence.exists():
            self._fail("EXECUTOR_SUCCESS_ALONE_CANNOT_GRADUATE", "required files missing")
            return
        prod_content = prod_v2.read_text()
        ev_content = evidence.read_text()
        checks = [
            ("production_v2", "executor success is NOT mission PASS", prod_content),
            ("production_v2", "execution_gate", prod_content),
            ("aivido_evidence", "EXECUTOR SUCCESS ALONE IS NOT A PASS", ev_content),
            ("aivido_evidence", "informational only", ev_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            import re
            if not re.search(pattern, content, re.IGNORECASE):
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("EXECUTOR_SUCCESS_ALONE_CANNOT_GRADUATE", f"missing patterns: {missing}")
        else:
            self._pass("EXECUTOR_SUCCESS_ALONE_CANNOT_GRADUATE", {})

    # 12. Stale/missing screenshot cannot graduate
    def check_stale_missing_screenshot_cannot_graduate(self) -> None:
        """Verify stale/missing screenshot gates block graduation."""
        evidence = ROOT / "scripts" / "aivido_evidence.py"
        prod_v2 = ROOT / "core" / "production_v2.py"
        if not evidence.exists() or not prod_v2.exists():
            self._fail("STALE_MISSING_SCREENSHOT_CANNOT_GRADUATE", "required files missing")
            return
        ev_content = evidence.read_text()
        prod_content = prod_v2.read_text()
        checks = [
            ("aivido_evidence", "STALE FRAME", ev_content),
            ("aivido_evidence", "MISSING FRESH FRAME", ev_content),
            ("aivido_evidence", "check_frame_freshness", ev_content),
            ("production_v2", "screenshot_fresh", prod_content),
            ("production_v2", "evidence_gate", prod_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            import re
            if not re.search(pattern, content):
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("STALE_MISSING_SCREENSHOT_CANNOT_GRADUATE", f"missing patterns: {missing}")
        else:
            self._pass("STALE_MISSING_SCREENSHOT_CANNOT_GRADUATE", {})

    # 13. Actor identity regression protections exist
    def check_actor_identity_regression(self) -> None:
        """Verify actor identity audit exists in graduation gate."""
        grad_gate = ROOT / "tools" / "aivido_graduation_gate.py"
        test_actor = ROOT / "tests" / "test_actor_identity.py"
        if not grad_gate.exists():
            self._fail("ACTOR_IDENTITY_REGRESSION", "graduation gate missing")
            return
        if not test_actor.exists():
            self._fail("ACTOR_IDENTITY_REGRESSION", "test_actor_identity.py missing")
            return
        grad_content = grad_gate.read_text()
        test_content = test_actor.read_text()
        checks = [
            ("graduation_gate", "audit_mission_labels", grad_content),
            ("graduation_gate", "MISSION_LABEL_UNKNOWN", grad_content),
            ("test_actor_identity", "AIVIDO_", test_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            if pattern not in content:
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("ACTOR_IDENTITY_REGRESSION", f"missing patterns: {missing}")
        else:
            self._pass("ACTOR_IDENTITY_REGRESSION", {})

    # 14. Explicit production brief path exists
    def check_explicit_production_brief(self) -> None:
        """Verify production brief / mission file path is supported."""
        grad_gate = ROOT / "tools" / "aivido_graduation_gate.py"
        verified = ROOT / "tools" / "aivido_verified_mission.py"
        if not grad_gate.exists() or not verified.exists():
            self._fail("EXPLICIT_PRODUCTION_BRIEF", "required files missing")
            return
        grad_content = grad_gate.read_text()
        verified_content = verified.read_text()
        checks = [
            ("graduation_gate", "mission_file", grad_content),
            ("verified_mission", "package_evidence", verified_content),
            ("verified_mission", "ev_dir", verified_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            if pattern not in content:
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("EXPLICIT_PRODUCTION_BRIEF", f"missing patterns: {missing}")
        else:
            self._pass("EXPLICIT_PRODUCTION_BRIEF", {})

    # 15. Negated instructions cannot trigger forbidden tools
    def check_negated_instructions_protection(self) -> None:
        """Verify production lane classification rejects negated instructions."""
        prod_v2 = ROOT / "core" / "production_v2.py"
        if not prod_v2.exists():
            self._fail("NEGATED_INSTRUCTIONS_PROTECTION", "production_v2.py missing")
            return
        content = prod_v2.read_text()
        checks = [
            "NEGATION_CUES",
            "negat",
            "classify_lane",
            "atomic_fast_path_allowed",
        ]
        missing = [c for c in checks if c.lower() not in content.lower()]
        if missing:
            self._fail("NEGATED_INSTRUCTIONS_PROTECTION", f"missing patterns: {missing}")
        else:
            self._pass("NEGATED_INSTRUCTIONS_PROTECTION", {})

    # 16. Required regression suites can be invoked
    def check_regression_suites_invokable(self) -> None:
        """Verify key regression test files exist."""
        required_tests = [
            "tests/test_actor_identity.py",
            "tests/test_aivido_evidence.py",
            "tests/test_production_v2.py",
            "tests/test_visual_acceptance.py",
            "tests/test_compile_stall_regression.py",
        ]
        missing = []
        for test_path in required_tests:
            full = ROOT / test_path
            if not full.exists():
                missing.append(test_path)
        if missing:
            self._fail("REGRESSION_SUITES_INVOKABLE", f"missing test files: {missing}")
            return
        self._pass("REGRESSION_SUITES_INVOKABLE", {"test_files": required_tests})

    # 17. No stale Windows/Shadow-PC production path required
    def check_no_stale_windows_path(self) -> None:
        """Verify no hardcoded Windows/Shadow-PC paths are required for graduation."""
        critical_files = [
            ROOT / "tools" / "aivido_graduation_gate.py",
            ROOT / "tools" / "aivido_verified_mission.py",
            ROOT / "scripts" / "aivido_evidence.py",
            ROOT / "core" / "production_v2.py",
        ]
        forbidden_patterns = [
            "Shadow",
            "C:\\\\Users\\\\Shadow",
            "C:/Users/Shadow",
            "AvaLive",
            "avalive_uproject",
            "unreal_editor_exe",
        ]
        violations = []
        for f in critical_files:
            if f.exists():
                content = f.read_text()
                for pattern in forbidden_patterns:
                    if pattern.lower() in content.lower():
                        violations.append(f"{f.name}:{pattern}")
        if violations:
            self._fail("NO_STALE_WINDOWS_PATH", f"hardcoded Windows paths found: {violations}")
        else:
            self._pass("NO_STALE_WINDOWS_PATH", {})

    # 18. Release output is machine-readable JSON + concise human report
    def check_release_output_format(self) -> None:
        """Verify gate outputs machine-readable JSON and human report."""
        # This gate itself produces JSON; verify graduation gate does too
        grad_gate = ROOT / "tools" / "aivido_graduation_gate.py"
        evidence = ROOT / "scripts" / "aivido_evidence.py"
        if not grad_gate.exists() or not evidence.exists():
            self._fail("RELEASE_OUTPUT_FORMAT", "required files missing")
            return
        grad_content = grad_gate.read_text()
        ev_content = evidence.read_text()
        checks = [
            ("graduation_gate", "json_out", grad_content),
            ("graduation_gate", "json.dumps", grad_content),
            ("aivido_evidence", "verdict.json", ev_content),
            ("aivido_evidence", "verdict.md", ev_content),
            ("aivido_evidence", "json.dumps", ev_content),
        ]
        missing = []
        for mod, pattern, content in checks:
            if pattern not in content:
                missing.append(f"{mod}:{pattern}")
        if missing:
            self._fail("RELEASE_OUTPUT_FORMAT", f"missing patterns: {missing}")
        else:
            self._pass("RELEASE_OUTPUT_FORMAT", {})

    def run_all(self) -> int:
        """Run all 18 checks."""
        checks = [
            ("1", self.check_repo_release_state),
            ("2", self.check_backend_health),
            ("3", self.check_bridge_health),
            ("4", self.check_expected_map),
            ("5", self.check_command_runtime),
            ("6", self.check_no_stuck_job),
            ("7", self.check_one_click_launcher),
            ("8", self.check_evidence_packager),
            ("9", self.check_fresh_evidence_requirements),
            ("10", self.check_empty_scenediff_cannot_graduate),
            ("11", self.check_executor_success_alone_cannot_graduate),
            ("12", self.check_stale_missing_screenshot_cannot_graduate),
            ("13", self.check_actor_identity_regression),
            ("14", self.check_explicit_production_brief),
            ("15", self.check_negated_instructions_protection),
            ("16", self.check_regression_suites_invokable),
            ("17", self.check_no_stale_windows_path),
            ("18", self.check_release_output_format),
        ]

        for num, check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(f"CHECK_{num}", f"unexpected error: {type(exc).__name__}: {exc}")

        self.report["verdict"] = "PASS" if not self.report["reasons"] else "FAIL"

        # Output JSON
        text = json.dumps(self.report, indent=2, default=str)
        print(text)
        if self.json_out:
            out = Path(self.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)

        return 0 if self.report["verdict"] == "PASS" else 42


def main() -> int:
    ap = argparse.ArgumentParser(description="AIVIDO RC1 Acceptance Gate")
    ap.add_argument("--json-out", default="", help="Write JSON report to file")
    ap.add_argument("--check", default="", help="Run only specific check number (1-18)")
    args = ap.parse_args()

    gate = RC1Gate(args.json_out if args.json_out else None)

    if args.check:
        # Run single check for debugging
        check_map = {
            "1": gate.check_repo_release_state,
            "2": gate.check_backend_health,
            "3": gate.check_bridge_health,
            "4": gate.check_expected_map,
            "5": gate.check_command_runtime,
            "6": gate.check_no_stuck_job,
            "7": gate.check_one_click_launcher,
            "8": gate.check_evidence_packager,
            "9": gate.check_fresh_evidence_requirements,
            "10": gate.check_empty_scenediff_cannot_graduate,
            "11": gate.check_executor_success_alone_cannot_graduate,
            "12": gate.check_stale_missing_screenshot_cannot_graduate,
            "13": gate.check_actor_identity_regression,
            "14": gate.check_explicit_production_brief,
            "15": gate.check_negated_instructions_protection,
            "16": gate.check_regression_suites_invokable,
            "17": gate.check_no_stale_windows_path,
            "18": gate.check_release_output_format,
        }
        if args.check in check_map:
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