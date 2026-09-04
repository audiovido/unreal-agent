"""UNREAL CODER — asset intake + mission engine tests (L7 + engine)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission as mission_mod
from core.mission import (
    LoopProtector,
    MissionEngine,
    MissionState,
    classify_error,
    mission_response,
)
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from tools.unreal.asset_intake import analyze_asset, provenance_record


# ============================================================================
# Asset intake (L7)
# ============================================================================

@pytest.fixture()
def obj_file(tmp_path):
    """A 200cm-cube OBJ (cm units), with UVs and normals."""
    lines = ["# test cube"]
    # 8 vertices of a 200cm cube centered on origin
    coords = [(-100, -100, 0), (100, -100, 0), (100, 100, 0), (-100, 100, 0),
              (-100, -100, 200), (100, -100, 200), (100, 100, 200),
              (-100, 100, 200)]
    for c in coords:
        lines.append(f"v {c[0]} {c[1]} {c[2]}")
    for i in range(1, 9):
        lines.append(f"vt 0.{i} 0.5")
        lines.append(f"vn 0 0 1")
    for f in range(1, 13):
        lines.append(f"f {f} {((f) % 8) + 1} {((f + 1) % 8) + 1}")
    path = tmp_path / "SciFiCrate.obj"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestAssetIntake:
    def test_missing_file_reports(self, tmp_path):
        report = analyze_asset(str(tmp_path / "nope.obj"))
        assert not report.exists
        assert not report.ok
        assert "does not exist" in " ".join(report.warnings)

    def test_obj_geometry_parsed(self, obj_file):
        report = analyze_asset(str(obj_file))
        assert report.ok
        assert report.kind == "mesh"
        assert report.vertices == 8
        assert report.faces == 12
        assert report.has_uvs is True
        assert report.has_normals is True
        assert report.dimensions_cm == [200.0, 200.0, 200.0]
        assert report.largest_dimension_cm == 200.0
        assert report.repair_route in {"none", "unreal_settings"}

    def test_scale_suspect_routes_blender(self, tmp_path):
        path = tmp_path / "Tiny.obj"
        path.write_text("v 0 0 0\nv 0.001 0 0\nv 0 0.001 0\n"
                        "v 0 0 0.001\nf 1 2 3\nf 1 2 4\n",
                        encoding="utf-8")
        report = analyze_asset(str(path))
        assert report.scale_suspect
        assert "scale_normalization" in report.repair_needed
        assert report.repair_route == "blender"

    def test_missing_uvs_routes_blender(self, tmp_path):
        path = tmp_path / "NoUV.obj"
        path.write_text(
            "v 0 0 0\nv 100 0 0\nv 0 100 0\nv 0 0 100\nf 1 2 3\nf 1 2 4\n",
            encoding="utf-8")
        report = analyze_asset(str(path))
        assert report.has_uvs is False
        assert "missing_uvs" in report.repair_needed
        assert report.repair_route == "blender"

    def test_fbx_header_verified(self, tmp_path):
        path = tmp_path / "Model.fbx"
        path.write_bytes(b"Kaydara FBX Binary\x00" + b"\x00" * 64)
        report = analyze_asset(str(path))
        assert report.kind == "mesh"
        assert "Binary FBX detected." in " ".join(report.warnings)

    def test_corrupt_glb_flagged(self, tmp_path):
        path = tmp_path / "broken.glb"
        path.write_bytes(b"NOTGLB" + b"\x00" * 32)
        report = analyze_asset(str(path))
        assert not report.ok or report.repair_route == "blender"
        assert any("ASSET_CORRUPT" in w or "corrupt" in w.lower()
                   for w in report.warnings)

    def test_texture_classified(self, tmp_path):
        path = tmp_path / "wall_diff.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
        report = analyze_asset(str(path))
        assert report.kind == "texture"
        assert report.ok
        assert report.suggested_folder == "/Game/Imported/Textures"

    def test_naming_and_folder(self, obj_file):
        report = analyze_asset(str(obj_file))
        assert report.suggested_name == "SciFiCrate"
        assert report.suggested_folder == "/Game/Imported"

    def test_provenance_chain(self, obj_file):
        report = analyze_asset(str(obj_file))
        record = provenance_record(
            report, operations=["scale_normalize", "uv_repair"],
            output_path="/tmp/fixed.obj",
            import_destination="/Game/Imported/SciFiCrate",
        )
        assert record["original_untouched"] is True
        assert record["operations"] == ["scale_normalize", "uv_repair"]
        assert record["import_destination"].startswith("/Game/")
        assert record["original_path"].endswith("SciFiCrate.obj")

    def test_original_file_untouched(self, obj_file):
        before = obj_file.read_bytes()
        analyze_asset(str(obj_file))
        assert obj_file.read_bytes() == before


# ============================================================================
# Error classification
# ============================================================================

class TestErrorClassification:
    @pytest.mark.parametrize("error,expected", [
        ("Bridge connection refused", "BRIDGE"),
        ("expected_project mismatch", "WRONG_PROJECT"),
        ("Blueprint compile failed", "BLUEPRINT"),
        ("compile error C2039", "CODE_COMPILE"),
        ("failed to import FBX", "ASSET_IMPORT"),
        ("PIE begin play failed", "PIE"),
        ("capture_unreal_viewport timed out", "BRIDGE"),
        ("blender executable not found", "EXTERNAL_TOOL"),
        ("file not found: C:/x.uproject", "FILESYSTEM"),
        ("totally novel failure", "UNKNOWN"),
    ])
    def test_classification(self, error, expected):
        assert classify_error(error) == expected


# ============================================================================
# Loop protection
# ============================================================================

class TestLoopProtector:
    def test_repeat_then_stop(self):
        protector = LoopProtector()
        assert protector.observe("spawn:x") == "ok"
        assert protector.observe("spawn:x") == "repeat"
        assert protector.observe("spawn:x") == "stop"

    def test_different_work_allowed(self):
        protector = LoopProtector()
        assert protector.observe("spawn:a") == "ok"
        assert protector.observe("spawn:b") == "ok"
        assert protector.observe("spawn:a") == "repeat"

    def test_progress_budget(self):
        protector = LoopProtector()
        assert protector.progress(False)
        assert protector.progress(False)
        assert not protector.progress(False)

    def test_progress_reset(self):
        protector = LoopProtector()
        protector.progress(False)
        assert protector.progress(True)
        assert protector.progress(True)


# ============================================================================
# Mission engine
# ============================================================================

def _fake_dispatch_ok(step):
    return {"ok": True, "result": {"verified": True, "tool": step.get(
        "preferred_tool")}, "resource_path": "/Game/Test"}


def _fake_dispatch_fail(step):
    return {"ok": False, "error": "bridge connection refused"}


def _engine(dispatch=None, capture=None, evaluate=None, repair=None):
    from core.capability_registry import build_capability_registry
    tools = {"inspect_project": object(), "unreal_ping": object(),
             "capture_unreal_viewport": object(), "spawn_actor": object(),
             "save_level": object(), "create_widget_blueprint": object(),
             "add_text_widget": object()}
    caps = build_capability_registry(tools)
    if capture is None:
        _caps = {"n": 0}

        def capture():
            _caps["n"] += 1
            return {"path": f"/tmp/default_cap{_caps['n']}.png"}

    if evaluate is None:
        def evaluate(captured):
            # Default: production wires the real visual stack; the fake
            # models a passing review (score above every floor).
            return {"score": 9.0, "defects": []}

    return MissionEngine(
        tool_registry=tools, capabilities=caps,
        dispatch=dispatch or _fake_dispatch_ok,
        capture=capture, evaluate=evaluate, repair=repair,
    )


class TestDiagnosticMission:
    """Regression: status/health diagnostic missions must execute real
    read-only probes and emit evidence; they can never finish as a verified
    PASS from 0 executed steps / no evidence (the ClickUp blocker)."""

    PROMPT = (
        "Check the Aivido backend health and the Unreal bridge readiness "
        "as a status-only diagnostic. Run real probes and only PASS when "
        "both explicitly report READY."
    )

    @staticmethod
    def _diag_engine(dispatch=None):
        from core.capability_registry import build_capability_registry
        tools = {"inspect_project": object(), "unreal_ping": object(),
                 "unreal_coder_doctor": object(),
                 "capture_unreal_viewport": object(), "spawn_actor": object(),
                 "save_level": object(), "create_widget_blueprint": object(),
                 "add_text_widget": object()}
        caps = build_capability_registry(tools)
        return MissionEngine(
            tool_registry=tools, capabilities=caps,
            dispatch=dispatch or _fake_dispatch_ok,
            capture=lambda: {"path": "x.png"},
            evaluate=lambda _: {"score": 9.0, "defects": []},
        )

    def test_status_mission_executes_probes_and_passes_with_evidence(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        engine = self._diag_engine()
        state = engine.start_mission(self.PROMPT)
        state = engine.interpret(state)
        state = engine.plan(state)
        result = engine.run(state)
        assert result.completed_step_ids            # > 0 executed steps
        tools = {s["preferred_tool"] for s in result.plan["steps"]}
        assert "unreal_ping" in tools
        assert "unreal_coder_doctor" in tools
        assert result.verdict == "PASS"
        assert result.status == "complete"
        assert result.evidence                       # non-empty real evidence

    def test_status_mission_fails_when_probe_does_not_pass(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        engine = self._diag_engine(dispatch=_fake_dispatch_fail)
        state = engine.start_mission(self.PROMPT)
        state = engine.interpret(state)
        state = engine.plan(state)
        result = engine.run(state)
        # A down bridge must yield an honest FAIL, never a fabricated PASS.
        assert result.verdict == "FAIL"

    def test_zero_step_diagnostic_mission_never_passes(
        self, tmp_path, monkeypatch
    ): 
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        engine = self._diag_engine()
        state = engine.start_mission(self.PROMPT)
        state = engine.interpret(state)
        state = engine.plan(state)
        # Simulate the historical 0-step chat collapse reaching execution.
        state.plan["steps"] = []
        result = engine.run(state)
        assert result.verdict != "PASS"


class TestMissionEngine:
    def test_full_mission_pass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR",
                            tmp_path / "cp")
        engine = _engine()
        state = engine.start_mission("Create a polished main menu")
        state = engine.interpret(state)
        state = engine.plan(state)
        state = engine.run(state)
        assert state.verdict == "PASS"
        assert state.status == "complete"
        assert state.completed_step_ids

    def test_checkpoint_persisted_and_loadable(self, tmp_path, monkeypatch):
        cp = tmp_path / "cp"
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", cp)
        engine = _engine()
        state = engine.start_mission("Create a polished main menu")
        state = engine.interpret(state)
        state = engine.plan(state)
        state.save()
        assert (cp / f"{state.mission_id}.json").exists()
        loaded = MissionState.load(state.mission_id)
        assert loaded.prompt == state.prompt
        assert loaded.plan.get("mission_id") == state.plan.get("mission_id")

    def test_resume_skips_completed_steps(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        engine = _engine()
        state = engine.start_mission("Create a polished main menu")
        state = engine.interpret(state)
        state = engine.plan(state)
        first = engine.run(state)
        total = len(first.plan.get("steps", []))
        done = len(first.completed_step_ids)
        # Simulate interruption mid-mission: clear remaining, re-run.
        first.completed_step_ids = first.completed_step_ids[: done // 2]
        resumed = engine.run(first)
        assert resumed.verdict == "PASS"
        assert len(resumed.completed_step_ids) == total

    def test_loop_protection_blocks_runaway(self, tmp_path, monkeypatch):
        """Two plan steps with identical signature -> third must stop."""
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        calls = {"n": 0}

        def flaky(step):
            # Always fail with the same error so recovery policy can't fix it.
            return {"ok": False, "error": "mysterious unrecoverable error"}

        engine = _engine(dispatch=flaky)
        state = engine.start_mission("Create a polished main menu")
        state = engine.interpret(state)
        state = engine.plan(state)
        # Reduce plan to identical steps to force the same-signature loop.
        state.plan["steps"] = [
            {"step_id": "s1", "phase": "EDIT", "intent": "work",
             "preferred_tool": "spawn_actor", "parameters": {"x": 1},
             "depends_on": [], "status": "pending"},
            {"step_id": "s2", "phase": "EDIT", "intent": "work",
             "preferred_tool": "spawn_actor", "parameters": {"x": 1},
             "depends_on": [], "status": "pending"},
            {"step_id": "s3", "phase": "EDIT", "intent": "work",
             "preferred_tool": "spawn_actor", "parameters": {"x": 1},
             "depends_on": [], "status": "pending"},
            {"step_id": "s4", "phase": "EDIT", "intent": "work",
             "preferred_tool": "spawn_actor", "parameters": {"x": 1},
             "depends_on": [], "status": "pending"},
        ]
        result = engine.run(state)
        assert result.status == "blocked"
        assert result.verdict == "BLOCKED"
        assert any("LOOP_PROTECTION" in b for b in result.blockers)

    def test_visual_loop_pass_at_floor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        captures = {"n": 0}

        def capture():
            captures["n"] += 1
            return {"path": f"/tmp/cap{captures['n']}.png"}

        def evaluate(captured):
            return {"score": 7.5, "defects": []}

        engine = _engine(capture=capture, evaluate=evaluate, repair=None)
        state = engine.start_mission("make a beautiful room")
        state = engine.interpret(state)
        state = engine.plan(state)
        result = engine.run(state)
        # Visual gate enabled -> PASS requires score >= floor.
        assert result.verdict == "PASS"
        assert captures["n"] >= 1
        assert result.evidence

    def test_visual_loop_repairs_then_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        state = _engine().start_mission("make a beautiful room")
        reviews = [{"score": 5.0, "defects": ["DARK"]},
                   {"score": 7.5, "defects": []}]
        captures = {"n": 0}
        repairs = []

        def capture():
            captures["n"] += 1
            return {"path": f"/tmp/cap{captures['n']}.png"}

        def evaluate(captured):
            return reviews[min(captures["n"] - 1, len(reviews) - 1)]

        def repair(defects):
            repairs.append(defects)
            return "exposure_raise"

        engine = _engine(capture=capture, evaluate=evaluate, repair=repair)
        engine.interpret(state)
        engine.plan(state)
        result = engine.run(state)
        assert len(repairs) == 1
        assert result.verdict == "PASS"

    def test_visual_loop_stagnation_stops(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        state = _engine().start_mission("make a beautiful room")
        captures = {"n": 0}
        repairs = []

        def capture():
            captures["n"] += 1
            return {"path": f"/tmp/cap{captures['n']}.png"}

        def evaluate(captured):
            # Same score forever, defect never cleared.
            return {"score": 5.5, "defects": ["DARK"]}

        def repair(defects):
            repairs.append(defects)
            return "attempt"

        engine = _engine(capture=capture, evaluate=evaluate, repair=repair)
        engine.interpret(state)
        engine.plan(state)
        result = engine.run(state)
        assert result.verdict in {"PARTIAL", "FAIL", "STAGNANT", "BUDGET"}
        assert len(repairs) <= 3  # bounded, never infinite

    def test_visual_rejection_is_resumable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        state = _engine().start_mission("make a beautiful room")
        engine = _engine(capture=lambda: {"path": "x.png"},
                         evaluate=lambda _: {"score": 1.0,
                                             "defects": ["CHEAP_PRIMITIVE_LOOK"]},
                         repair=lambda _: {"ok": False,
                                           "error": "scene-specific repair required"})
        engine.interpret(state)
        engine.plan(state)
        result = engine.run(state)
        assert result.verdict == "PARTIAL"
        assert result.status == "repairing"
        assert mission_response(result)["resumable"] is True

    def test_response_shape(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        engine = _engine()
        state = engine.start_mission("Create a main menu")
        engine.interpret(state)
        engine.plan(state)
        engine.run(state)
        response = mission_response(state)
        for key in ("mission_id", "status", "verdict", "interpretation",
                    "plan", "completed_work", "evidence", "warnings",
                    "remaining_issues", "artifacts", "resumable"):
            assert key in response, key

    def test_chat_mission_never_dispatches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        calls = []

        def dispatch(step):
            calls.append(step)
            return {"ok": True}

        engine = _engine(dispatch=dispatch)
        state = engine.start_mission("What is a GameMode?")
        engine.interpret(state)
        engine.plan(state)
        engine.run(state)
        assert calls == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
