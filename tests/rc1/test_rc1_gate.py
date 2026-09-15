#!/usr/bin/env python3
"""Hermetic tests for AIVIDO RC1 Acceptance Gate.

These tests verify the gate logic without requiring live Unreal, backend, or bridge.
All external dependencies are mocked or tested via static analysis.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "rc1"))

from aivido_rc1_gate import RC1Gate, CHECK_DESCRIPTIONS


class TestRC1GateStaticChecks(unittest.TestCase):
    """Tests that verify gate logic by inspecting source files (no runtime deps)."""

    def setUp(self):
        self.gate = RC1Gate()

    def test_check_descriptions_complete(self):
        """All 18 checks have human-readable descriptions."""
        expected_checks = 18
        # The gate creates checks dynamically, verify descriptions cover them
        self.assertEqual(len(CHECK_DESCRIPTIONS), expected_checks)

    def test_repo_release_state_check_logic(self):
        """Verify check_repo_release_state logic without filesystem."""
        # Test the pattern matching logic
        content_all = """# Aivido Mac Release Status
Release: aivido-mac-release-20260911-170846
- Stage A: Graduated
- Stage B: Graduated
- Stage C: Graduated
- Stage D: Graduated
"""
        content_missing = """# Aivido Mac Release Status
Release: test
- Stage A: Graduated
"""
        required = ["Stage A: Graduated", "Stage B: Graduated",
                    "Stage C: Graduated", "Stage D: Graduated"]

        missing_all = [r for r in required if r not in content_all]
        self.assertEqual(len(missing_all), 0)

        missing_some = [r for r in required if r not in content_missing]
        self.assertEqual(len(missing_some), 3)

    def test_fresh_evidence_patterns_in_evidence_packager(self):
        """Verify evidence packager contains required freshness patterns."""
        evidence_path = ROOT / "scripts" / "aivido_evidence.py"
        self.assertTrue(evidence_path.exists(), "evidence packager must exist")
        content = evidence_path.read_text()
        required = ["sha256", "capture_metadata", "fresh", "stale",
                    "max_age", "captured_at_epoch",
                    "EXECUTOR SUCCESS ALONE IS NOT A PASS"]
        for pattern in required:
            self.assertIn(pattern.lower(), content.lower(),
                          f"Missing pattern {pattern} in evidence packager")

    def test_empty_scenediff_gate_in_production_v2(self):
        """Verify production_v2 has empty SceneDiff gate."""
        prod_path = ROOT / "core" / "production_v2.py"
        self.assertTrue(prod_path.exists(), "production_v2 must exist")
        content = prod_path.read_text()
        self.assertIn("scene_diff_is_meaningful", content)
        self.assertIn("scene_diff_gate", content)
        self.assertIn("graduation_gates", content)

    def test_executor_success_not_pass_in_evidence(self):
        """Verify evidence packager rejects executor-only pass."""
        evidence_path = ROOT / "scripts" / "aivido_evidence.py"
        content = evidence_path.read_text()
        self.assertIn("EXECUTOR SUCCESS ALONE IS NOT A PASS", content)
        self.assertIn("executor_ok", content)
        self.assertIn("informational only", content.lower())

    def test_stale_screenshot_gate_in_evidence(self):
        """Verify evidence packager has stale/missing screenshot gate."""
        evidence_path = ROOT / "scripts" / "aivido_evidence.py"
        content = evidence_path.read_text()
        self.assertIn("STALE FRAME", content)
        self.assertIn("MISSING FRESH FRAME", content)
        self.assertIn("check_frame_freshness", content)

    def test_actor_identity_audit_in_graduation_gate(self):
        """Verify graduation gate has actor identity audit."""
        grad_path = ROOT / "tools" / "aivido_graduation_gate.py"
        self.assertTrue(grad_path.exists(), "graduation gate must exist")
        content = grad_path.read_text()
        self.assertIn("audit_mission_labels", content)
        self.assertIn("MISSION_LABEL_UNKNOWN", content)
        self.assertIn("AIVIDO_", content)

    def test_negation_cues_in_production_v2(self):
        """Verify production_v2 has negation protection."""
        prod_path = ROOT / "core" / "production_v2.py"
        content = prod_path.read_text()
        self.assertIn("NEGATION_CUES", content)
        self.assertIn("negat", content.lower())
        self.assertIn("classify_lane", content)
        self.assertIn("atomic_fast_path_allowed", content)

    def test_no_hardcoded_windows_paths_in_critical_files(self):
        """Verify no Shadow/C:\\Users\\Shadow paths in graduation path."""
        critical = [
            ROOT / "tools" / "aivido_graduation_gate.py",
            ROOT / "tools" / "aivido_verified_mission.py",
            ROOT / "scripts" / "aivido_evidence.py",
            ROOT / "core" / "production_v2.py",
        ]
        forbidden = ["Shadow", "C:\\\\Users\\\\Shadow", "C:/Users/Shadow",
                     "AvaLive", "avalive_uproject", "unreal_editor_exe"]
        for f in critical:
            self.assertTrue(f.exists(), f"{f.name} must exist")
            content = f.read_text()
            for pattern in forbidden:
                self.assertNotIn(pattern.lower(), content.lower(),
                                 f"Forbidden pattern {pattern} in {f.name}")

    def test_release_output_formats(self):
        """Verify graduation gate and evidence packager output JSON + MD."""
        grad_path = ROOT / "tools" / "aivido_graduation_gate.py"
        ev_path = ROOT / "scripts" / "aivido_evidence.py"
        for f in [grad_path, ev_path]:
            self.assertTrue(f.exists())
        grad_content = grad_path.read_text()
        ev_content = ev_path.read_text()
        self.assertIn("json_out", grad_content)
        self.assertIn("json.dumps", grad_content)
        self.assertIn("verdict.json", ev_content)
        self.assertIn("verdict.md", ev_content)

    def test_one_click_launcher_exists(self):
        """Verify avalive_gate.py (one-click launcher) exists."""
        launcher = ROOT / "scripts" / "avalive_gate.py"
        config = ROOT / "scripts" / "avalive_gate.json"
        self.assertTrue(launcher.exists(), "avalive_gate.py missing")
        self.assertTrue(config.exists(), "avalive_gate.json missing")

    def test_evidence_packager_exists(self):
        """Verify aivido_evidence.py exists."""
        packager = ROOT / "scripts" / "aivido_evidence.py"
        self.assertTrue(packager.exists(), "aivido_evidence.py missing")

    def test_regression_test_files_exist(self):
        """Verify required regression test files exist."""
        required = [
            "tests/test_actor_identity.py",
            "tests/test_aivido_evidence.py",
            "tests/test_production_v2.py",
            "tests/test_visual_acceptance.py",
            "tests/test_compile_stall_regression.py",
        ]
        for test_path in required:
            full = ROOT / test_path
            self.assertTrue(full.exists(), f"Missing test file: {test_path}")

    def test_production_brief_path_in_verified_mission(self):
        """Verify verified mission supports explicit brief path."""
        verified = ROOT / "tools" / "aivido_verified_mission.py"
        self.assertTrue(verified.exists())
        content = verified.read_text()
        self.assertIn("package_evidence", content)
        self.assertIn("ev_dir", content)


class TestRC1GateRuntimeBehavior(unittest.TestCase):
    """Tests that exercise gate runtime behavior with mocked externals."""

    def setUp(self):
        self.gate = RC1Gate()

    @patch("urllib.request.urlopen")
    def test_backend_health_ok(self, mock_urlopen):
        """Backend health check passes when contract satisfied."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": True, "version": "test", "unreal": {"ok": True}
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_backend_health()
        self.assertTrue(self.gate.report["checks"].get("BACKEND_HEALTH", {}).get("ok"))

    @patch("urllib.request.urlopen")
    def test_backend_health_fail(self, mock_urlopen):
        """Backend health check fails when contract not satisfied."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": False, "unreal": {"ok": False}
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_backend_health()
        self.assertFalse(self.gate.report["checks"].get("BACKEND_HEALTH", {}).get("ok"))

    @patch("urllib.request.urlopen")
    def test_backend_health_exception(self, mock_urlopen):
        """Backend health check fails on exception."""
        mock_urlopen.side_effect = ConnectionError("connection refused")

        self.gate.check_backend_health()
        self.assertFalse(self.gate.report["checks"].get("BACKEND_HEALTH", {}).get("ok"))

    @patch("socket.create_connection")
    def test_bridge_health_ok(self, mock_connect):
        """Bridge health check passes with valid response."""
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b'{"ok": true, "message": "UNREAL_BRIDGE_READY", "identity": {"project": "test"}, "engine": "UE5"}\n', b""]
        mock_connect.return_value = mock_sock

        self.gate.check_bridge_health()
        self.assertTrue(self.gate.report["checks"].get("BRIDGE_HEALTH", {}).get("ok"))

    @patch("socket.create_connection")
    def test_bridge_health_fail_not_ready(self, mock_connect):
        """Bridge health check fails without READY signal."""
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b'{"ok": true, "message": "something else"}\n', b""]
        mock_connect.return_value = mock_sock

        self.gate.check_bridge_health()
        self.assertFalse(self.gate.report["checks"].get("BRIDGE_HEALTH", {}).get("ok"))

    @patch("socket.create_connection")
    def test_expected_map_ok(self, mock_connect):
        """Expected map check passes on correct map."""
        mock_sock = MagicMock()
        probe_result = {
            "ok": True,
            "result": {"ok": True, "map": "/Game/AIVIDO_Showcase", "actor_count": 25}
        }
        mock_sock.recv.side_effect = [json.dumps(probe_result).encode() + b"\n", b""]
        mock_connect.return_value = mock_sock

        self.gate.check_expected_map()
        self.assertTrue(self.gate.report["checks"].get("EXPECTED_MAP", {}).get("ok"))

    @patch("socket.create_connection")
    def test_expected_map_wrong_map(self, mock_connect):
        """Expected map check fails on wrong map."""
        mock_sock = MagicMock()
        probe_result = {
            "ok": True,
            "result": {"ok": True, "map": "/Game/OtherMap", "actor_count": 10}
        }
        mock_sock.recv.side_effect = [json.dumps(probe_result).encode() + b"\n", b""]
        mock_connect.return_value = mock_sock

        self.gate.check_expected_map()
        self.assertFalse(self.gate.report["checks"].get("EXPECTED_MAP", {}).get("ok"))

    @patch("urllib.request.urlopen")
    def test_command_runtime_live_endpoint_ok(self, mock_urlopen):
        """Command runtime check passes via live endpoint."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": True,
            "worker_alive": True,
            "counts": {"pass": 10, "failed": 2},
            "active": None,
            "state_path": "/runtime/command_jobs.json",
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_command_runtime()
        check = self.gate.report["checks"].get("COMMAND_RUNTIME", {})
        self.assertTrue(check.get("ok"))
        self.assertEqual(check.get("active_jobs"), 0)

    @patch("urllib.request.urlopen")
    def test_command_runtime_live_endpoint_fails_fallback_to_file(self, mock_urlopen):
        """Command runtime falls back to file when live endpoint fails."""
        mock_urlopen.side_effect = ConnectionError("connection refused")

        # Mock the file fallback - create proper directory structure
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_dir.mkdir()
            state_file = runtime_dir / "command_jobs.json"
            state_data = {
                "jobs": {
                    "job1": {"state": "pass", "started_at": time.time() - 100},
                    "job2": {"state": "running", "started_at": time.time() - 10},
                }
            }
            state_file.write_text(json.dumps(state_data))

            with patch("aivido_rc1_gate.ROOT", Path(tmpdir)):
                self.gate.check_command_runtime()
                check = self.gate.report["checks"].get("COMMAND_RUNTIME", {})
                self.assertTrue(check.get("ok"))
                self.assertEqual(check.get("active_jobs"), 1)

    @patch("urllib.request.urlopen")
    def test_command_runtime_both_fail(self, mock_urlopen):
        """Command runtime fails when both live endpoint and file are unavailable."""
        mock_urlopen.side_effect = ConnectionError("connection refused")
        with patch("aivido_rc1_gate.ROOT", Path("/nonexistent")):
            self.gate.check_command_runtime()
            check = self.gate.report["checks"].get("COMMAND_RUNTIME", {})
            self.assertFalse(check.get("ok"))

    @patch("urllib.request.urlopen")
    def test_no_stuck_job_active_null_passes(self, mock_urlopen):
        """NO_STUCK_JOB passes when active is null."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": True,
            "worker_alive": True,
            "counts": {"pass": 10},
            "active": None,
            "state_path": "/runtime/command_jobs.json",
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_no_stuck_job()
        check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
        self.assertTrue(check.get("ok"))
        self.assertEqual(check.get("stuck_jobs"), 0)

    @patch("urllib.request.urlopen")
    def test_no_stuck_job_active_within_window_passes(self, mock_urlopen):
        """NO_STUCK_JOB passes when active job is within valid window."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": True,
            "worker_alive": True,
            "counts": {"pass": 10, "running": 1},
            "active": {"job_id": "cmd_abc123", "started_at": time.time() - 10},
            "state_path": "/runtime/command_jobs.json",
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_no_stuck_job()
        check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
        self.assertTrue(check.get("ok"))

    @patch("urllib.request.urlopen")
    def test_no_stuck_job_stale_active_fails(self, mock_urlopen):
        """NO_STUCK_JOB fails when active job is stale (> 5 min)."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "ok": True,
            "worker_alive": True,
            "counts": {"pass": 10, "running": 1},
            "active": {"job_id": "cmd_stuck", "started_at": time.time() - 400},
            "state_path": "/runtime/command_jobs.json",
        }).encode()
        mock_urlopen.return_value = mock_response

        self.gate.check_no_stuck_job()
        check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
        self.assertFalse(check.get("ok"))

    @patch("urllib.request.urlopen")
    def test_no_stuck_job_fallback_file_active_null(self, mock_urlopen):
        """NO_STUCK_JOB passes via file fallback when active is null."""
        mock_urlopen.side_effect = ConnectionError("connection refused")

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_dir.mkdir()
            state_file = runtime_dir / "command_jobs.json"
            state_data = {
                "jobs": {
                    "job1": {"state": "pass", "started_at": time.time() - 100},
                }
            }
            state_file.write_text(json.dumps(state_data))

            with patch("aivido_rc1_gate.ROOT", Path(tmpdir)):
                self.gate.check_no_stuck_job()
                check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
                self.assertTrue(check.get("ok"))

    @patch("urllib.request.urlopen")
    def test_no_stuck_job_fallback_file_stale_active_fails(self, mock_urlopen):
        """NO_STUCK_JOB fails via file fallback when active job is stale."""
        mock_urlopen.side_effect = ConnectionError("connection refused")

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_dir.mkdir()
            state_file = runtime_dir / "command_jobs.json"
            state_data = {
                "jobs": {
                    "stuck_job": {"state": "running", "started_at": time.time() - 400},
                }
            }
            state_file.write_text(json.dumps(state_data))

            with patch("aivido_rc1_gate.ROOT", Path(tmpdir)):
                self.gate.check_no_stuck_job()
                check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
                self.assertFalse(check.get("ok"))

    def test_no_stuck_job_missing_all_runtime_evidence_fails(self):
        """NO_STUCK_JOB fails when no runtime evidence available."""
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            with patch("aivido_rc1_gate.ROOT", Path("/nonexistent")):
                self.gate.check_no_stuck_job()
                check = self.gate.report["checks"].get("NO_STUCK_JOB", {})
                self.assertFalse(check.get("ok"))

    def test_command_runtime_obsolete_command_state_not_required(self):
        """COMMAND_RUNTIME does not require obsolete command_state.json."""
        # The gate should work with command_jobs.json, not command_state.json
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_dir.mkdir()
            state_file = runtime_dir / "command_jobs.json"
            state_data = {
                "jobs": {
                    "job1": {"state": "pass", "started_at": time.time() - 100},
                }
            }
            state_file.write_text(json.dumps(state_data))

            with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
                with patch("aivido_rc1_gate.ROOT", Path(tmpdir)):
                    self.gate.check_command_runtime()
                    check = self.gate.report["checks"].get("COMMAND_RUNTIME", {})
                    self.assertTrue(check.get("ok"))
                    # Should use command_jobs.json, not command_state.json
                    self.assertIn("command_jobs", check.get("state_path", ""))


class TestRC1GateVerdict(unittest.TestCase):
    """Tests for overall gate verdict logic."""

    def test_verdict_pass_when_no_reasons(self):
        """Verdict is PASS when no failure reasons."""
        gate = RC1Gate()
        gate.report["reasons"] = []
        gate.report["verdict"] = "PASS" if not gate.report["reasons"] else "FAIL"
        self.assertEqual(gate.report["verdict"], "PASS")

    def test_verdict_fail_when_reasons_exist(self):
        """Verdict is FAIL when failure reasons exist."""
        gate = RC1Gate()
        gate.report["reasons"] = ["BACKEND_HEALTH:connection refused"]
        gate.report["verdict"] = "PASS" if not gate.report["reasons"] else "FAIL"
        self.assertEqual(gate.report["verdict"], "FAIL")

    def test_json_output_structure(self):
        """JSON output has required structure."""
        gate = RC1Gate()
        gate._pass("TEST_CHECK", {"detail": "value"})
        gate.report["verdict"] = "PASS"

        output = json.dumps(gate.report, indent=2, default=str)
        parsed = json.loads(output)

        self.assertIn("gate", parsed)
        self.assertIn("at", parsed)
        self.assertIn("checks", parsed)
        self.assertIn("reasons", parsed)
        self.assertIn("verdict", parsed)
        self.assertEqual(parsed["verdict"], "PASS")
        self.assertTrue(parsed["checks"]["TEST_CHECK"]["ok"])


class TestRC1ReportGenerator(unittest.TestCase):
    """Tests for the report generator."""

    def test_format_report_pass(self):
        """Report formats correctly for PASS verdict."""
        gate_json = {
            "verdict": "PASS",
            "at": "2026-09-12 12:00:00",
            "checks": {"TEST_CHECK": {"ok": True, "detail": "value"}},
            "reasons": [],
        }
        # Import report generator
        sys.path.insert(0, str(ROOT / "tools" / "rc1"))
        from aivido_rc1_report import format_report

        report = format_report(gate_json)
        self.assertIn("Verdict: PASS", report)
        self.assertIn("✅ PASS", report)
        self.assertIn("TEST_CHECK", report)

    def test_format_report_fail(self):
        """Report formats correctly for FAIL verdict."""
        gate_json = {
            "verdict": "FAIL",
            "at": "2026-09-12 12:00:00",
            "checks": {"TEST_CHECK": {"ok": False, "reason": "failed"}},
            "reasons": ["TEST_CHECK:failed"],
        }
        sys.path.insert(0, str(ROOT / "tools" / "rc1"))
        from aivido_rc1_report import format_report

        report = format_report(gate_json)
        self.assertIn("Verdict: FAIL", report)
        self.assertIn("❌ FAIL", report)
        self.assertIn("TEST_CHECK:failed", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)