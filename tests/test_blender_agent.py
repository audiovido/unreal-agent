"""Deterministic tests for the Blender Agent pipeline and its Supervisor
integration into Unreal Agent.

Coverage (all offline / no live Blender or Unreal required):
  - job schema: creation, validation, persistence, recovery
  - runner: success / failure / timeout / retry / cancel / missing binary
  - manifests + validation logic (scale, transform, material, export files)
  - supervisor routing (Blender vs Unreal task plans)
  - Blender -> Unreal handoff tools with a FakeBridge
  - acceptance-contract mapping for Blender deliverables

The fake "blender.exe" is a batch/shell wrapper around a tiny python script,
so the real subprocess runner (timeout, retry, cancel) is exercised end to end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blender_agent import job_schema, validation
from blender_agent.config import workspace_layout
from blender_agent.geometry import cm_to_bu, safe_name
from blender_agent.materials import parse_color
from blender_agent.runner import run_job_sync, run_with_retries
from blender_agent.agent import BlenderAgent
from core import task_goal
from tools.unreal.import_tools import ImportTools
from tools.unreal.unreal_bridge import UnrealBridge

# ===================================================================== helpers


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Point the asset exchange at a temp dir so tests never touch the repo
    workspace or the user's Blender jobs."""
    ws = tmp_path / "ws"
    monkeypatch.setenv("UNREAL_AGENT_WORKSPACE", str(ws))
    from blender_agent.config import ensure_workspace
    ensure_workspace()
    return ws


@pytest.fixture(autouse=True)
def isolated_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")


FAKE_BLENDER_SRC = r'''"""Fake Blender executable for runner tests."""
import json, os, sys, time

def main():
    argv = sys.argv[1:]
    marker = "--"
    if marker not in argv:
        print("fake blender: no -- marker", flush=True)
        return 2
    idx = argv.index(marker)
    job_path, result_path = argv[idx + 1], argv[idx + 2]
    try:
        job = json.loads(open(job_path, encoding="utf-8").read())
    except Exception:
        job = {}
    mode = os.environ.get("UA_FAKE_BLENDER_MODE", "ok")
    if mode == "sleep":
        time.sleep(300)
        return 0
    if mode == "fail_once" and job.get("attempts", 0) == 1:
        open(result_path, "w", encoding="utf-8").write(json.dumps({
            "ok": False, "error": "fake_blender_failed_once",
            "outputs": {}, "validation": {"ok": False}, "manifest": {},
        }))
        print("fake blender failed once", flush=True)
        return 1
    if mode == "never":
        return 1
    open(result_path, "w", encoding="utf-8").write(json.dumps({
        "ok": True,
        "outputs": {
            "object_name": job.get("inputs", {}).get("name", "Fake"),
            "export": {"ok": True, "path": "C:/tmp/fake.fbx", "format": "fbx"},
        },
        "validation": {"ok": True, "dimensions_cm": [200.0, 100.0, 80.0]},
        "manifest": {
            "job_id": job.get("id"),
            "export_format": "fbx",
            "output_path": "C:/tmp/fake.fbx",
            "dimensions_cm": [200.0, 100.0, 80.0],
            "materials": [{"name": "wood"}],
            "textures": [],
            "validation": {"ok": True},
        },
    }))
    print("fake blender ok", flush=True)
    return 0

sys.exit(main())
'''


def install_fake_blender(tmp_path, monkeypatch, mode="ok"):
    """Create a fake blender executable and point the runner at it."""
    script = tmp_path / "fake_blender.py"
    script.write_text(FAKE_BLENDER_SRC, encoding="utf-8")
    exe = tmp_path / ("blender.bat" if os.name == "nt" else "blender.sh")
    python = sys.executable
    if os.name == "nt":
        exe.write_text(f'@echo off\n"{python}" "{script}" %*\n', encoding="utf-8")
    else:
        exe.write_text(f'#!/bin/sh\n"{python}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("UA_FAKE_BLENDER_MODE", mode)
    import blender_agent.runner as runner_mod
    monkeypatch.setattr(runner_mod, "blender_executable", lambda: exe)
    return exe


class FakeBridge:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def execute_python(self, code):
        self.calls.append(code)
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "result": {"ok": True}}


# ===================================================================== schema
class TestJobSchema:
    def test_new_job_defaults_and_persist(self, isolated_workspace):
        job = job_schema.new_job("create_primitive", {"name": "X"})
        assert job.status == "QUEUED"
        assert job.attempts == 0
        assert job.max_attempts == 3
        loaded = job_schema.load_job(job.id)
        assert loaded is not None
        assert loaded.operation == "create_primitive"
        assert loaded.inputs["name"] == "X"

    def test_unknown_operation_rejected(self):
        with pytest.raises(ValueError):
            job_schema.new_job("explode_everything", {})

    def test_validate_job(self):
        job = job_schema.new_job("convert_asset", {"source": "a.fbx"})
        ok, err = job_schema.validate_job(job)
        assert ok and not err
        job.operation = "nope"
        ok, err = job_schema.validate_job(job)
        assert not ok and "unsupported" in err

    def test_list_jobs_ordered(self, isolated_workspace):
        a = job_schema.new_job("create_primitive", {"name": "A"})
        b = job_schema.new_job("convert_asset", {"source": "x.fbx"})
        ids = [s["id"] for s in job_schema.list_jobs()]
        assert a.id in ids and b.id in ids

    def test_recover_incomplete_only_touches_interrupted(self, isolated_workspace):
        running = job_schema.new_job("create_primitive", {"name": "R"})
        running.status = "RUNNING"
        running.attempts = 1
        job_schema.save_job(running)
        complete = job_schema.new_job("create_primitive", {"name": "C"})
        complete.status = "COMPLETE"
        complete.manifest = {"output_path": "x.fbx"}
        job_schema.save_job(complete)
        relaunched = []
        recovered = job_schema.recover_incomplete_jobs(relaunch_callback=lambda j: relaunched.append(j.id))
        ids = [r["id"] for r in recovered]
        assert running.id in ids
        assert complete.id not in ids  # completed outputs are never duplicated
        reloaded = job_schema.load_job(complete.id)
        assert reloaded.status == "COMPLETE"
        assert relaunched == [running.id]

    def test_recover_exhausted_marks_failed(self, isolated_workspace):
        job = job_schema.new_job("create_primitive", {"name": "E"}, max_attempts=1)
        job.status = "RUNNING"
        job.attempts = 1
        job_schema.save_job(job)
        job_schema.recover_incomplete_jobs()
        assert job_schema.load_job(job.id).status == "FAILED"


# ===================================================================== runner
class TestRunner:
    def test_success_job(self, tmp_path, monkeypatch, isolated_workspace):
        install_fake_blender(tmp_path, monkeypatch, mode="ok")
        job = run_job_sync("create_primitive", {"name": "Table"}, max_attempts=1)
        assert job["status"] == "COMPLETE"
        assert job["attempts"] == 1
        assert job["manifest"]["output_path"] == "C:/tmp/fake.fbx"
        assert job["validation"]["ok"] is True

    def test_failure_job(self, tmp_path, monkeypatch, isolated_workspace):
        install_fake_blender(tmp_path, monkeypatch, mode="never")
        job = run_job_sync("create_primitive", {"name": "X"}, max_attempts=1)
        assert job["status"] == "FAILED"
        assert job["error"] is not None

    def test_retry_then_success(self, tmp_path, monkeypatch, isolated_workspace):
        install_fake_blender(tmp_path, monkeypatch, mode="fail_once")
        job = run_job_sync("create_primitive", {"name": "R"}, max_attempts=2)
        assert job["status"] == "COMPLETE"
        assert job["attempts"] == 2
        # bounded: the retry budget was honored, not exceeded
        assert job["attempts"] <= job["max_attempts"]

    def test_timeout_bounded(self, tmp_path, monkeypatch, isolated_workspace):
        install_fake_blender(tmp_path, monkeypatch, mode="sleep")
        job = run_job_sync("create_primitive", {"name": "T"}, max_attempts=1, timeout_seconds=3)
        assert job["status"] == "FAILED"
        assert "TIMEOUT" in str(job["error"])
        assert "fake_blender_failed_once" not in str(job["error"])

    def test_cancel(self, tmp_path, monkeypatch, isolated_workspace):
        install_fake_blender(tmp_path, monkeypatch, mode="sleep")
        from blender_agent.agent import BlenderAgent
        agent = BlenderAgent()
        record = agent.submit("create_primitive", {"name": "C"}, timeout_seconds=120)
        result = {}
        def worker():
            result["job"] = agent.run(record["id"])
        t = threading.Thread(target=worker)
        t.start()
        time.sleep(2.5)  # let the fake blender start sleeping
        agent.cancel(record["id"])
        t.join(timeout=30)
        assert result["job"]["status"] == "CANCELLED"

    def test_missing_blender_structured(self, tmp_path, monkeypatch, isolated_workspace):
        import blender_agent.runner as runner_mod
        def missing():
            raise FileNotFoundError("blender executable not found (test)")
        monkeypatch.setattr(runner_mod, "blender_executable", missing)
        job = run_job_sync("create_primitive", {"name": "M"}, max_attempts=1)
        assert job["status"] == "FAILED"
        assert "BLENDER_NOT_FOUND" in str(job["error"])

    def test_validation_rejects_bad_job_before_launch(self, tmp_path, monkeypatch, isolated_workspace):
        import blender_agent.runner as runner_mod
        monkeypatch.setattr(runner_mod, "blender_executable", lambda: Path("unused"))
        from blender_agent.job_schema import BlenderJob, save_job
        job = BlenderJob(operation="convert_asset", inputs={}, timeout_seconds=1)
        job.id = "bad-job"
        save_job(job)
        out = run_with_retries(job)
        assert out.status == "FAILED"
        assert "timeout_seconds" in str(out.error)  # structural validation error
        # structural failures are terminal: attempts never incremented, no retry spin
        assert out.attempts == 0


# ===================================================================== manifest/validation
class TestValidation:
    def test_scale_conversion(self):
        assert cm_to_bu(100.0) == pytest.approx(1.0)
        assert cm_to_bu(200.0) == pytest.approx(2.0)

    def test_parse_color_forms(self):
        assert parse_color("wood")[0] == pytest.approx(0.45)
        assert parse_color("#ff0000") == (1.0, 0.0, 0.0, 1.0)
        assert parse_color("0.1, 0.2, 0.3")[:3] == pytest.approx((0.1, 0.2, 0.3))
        assert parse_color([0.5, 0.6, 0.7])[:3] == pytest.approx((0.5, 0.6, 0.7))

    def test_safe_name(self):
        assert safe_name("UA Table 1") == "UA_Table_1"
        assert safe_name("___") == "Object"

    def test_validate_dimensions(self):
        ok = validation.validate_dimensions([200, 100, 80], [200, 100, 80])
        assert ok["ok"] is True
        bad = validation.validate_dimensions([1400, 1500, 80], [200, 100, 80])
        assert bad["ok"] is False

    def test_validate_export_file(self, tmp_path):
        missing = validation.validate_export_file(str(tmp_path / "nope.fbx"))
        assert missing["ok"] is False
        empty = tmp_path / "empty.fbx"
        empty.write_bytes(b"")
        assert validation.validate_export_file(str(empty))["ok"] is False
        good = tmp_path / "ok.fbx"
        good.write_bytes(b"x" * 100)
        result = validation.validate_export_file(str(good))
        assert result["ok"] is True
        assert result["checks"]["suffix_supported"] is True

    def test_validate_source_format(self, tmp_path):
        missing = validation.validate_source_format(str(tmp_path / "x.fbx"))
        assert missing["code"] == "SOURCE_NOT_FOUND"
        bad = tmp_path / "x.dae"
        bad.write_bytes(b"x")
        assert validation.validate_source_format(str(bad))["code"] == "UNSUPPORTED_FORMAT"
        good = tmp_path / "x.fbx"
        good.write_bytes(b"x")
        assert validation.validate_source_format(str(good))["ok"] is True

    def test_validate_manifest_contract(self):
        manifest = {
            "job_id": "1", "export_format": "fbx", "output_path": "x.fbx",
            "dimensions_cm": [1, 2, 3], "materials": [], "textures": [],
            "validation": {"ok": True},
        }
        assert validation.validate_manifest(manifest)["ok"] is True
        assert validation.validate_manifest({})["ok"] is False
        bad = dict(manifest)
        bad["validation"] = {"ok": False}
        assert validation.validate_manifest(bad)["ok"] is False

    def test_agent_status_no_blender(self, isolated_workspace, monkeypatch):
        # discover_blender is imported by name into blender_agent.agent, so it
        # must be patched there (patching config is not enough).
        import blender_agent.agent as agent_mod
        monkeypatch.setattr(agent_mod, "discover_blender", lambda: None)
        status = BlenderAgent().status()
        assert status["ok"] is False
        assert status["code"] == "BLENDER_NOT_FOUND"


# ===================================================================== registry/tools
def test_blender_tools_registered():
    from core.tool_registry import build_registry
    import tools.unreal.project_manager as pm
    registry = build_registry(
        pm.discover_projects, pm.inspect_project, pm.open_project, pm.create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=UnrealBridge(),
    )
    for name in (
        "blender_status", "blender_create_asset", "blender_convert_asset",
        "blender_prepare_asset", "blender_prepare_character", "blender_inspect_asset",
        "blender_job_status", "blender_jobs_list", "blender_cancel_job",
        "blender_recover", "blender_verify_export",
        "create_asset_folder", "import_asset", "import_asset_fbx", "import_asset_gltf",
        "import_blender_output", "verify_blender_output", "verify_imported_asset",
        "spawn_blender_output", "spawn_imported_asset", "inspect_imported_asset",
    ):
        assert name in registry, name


# ===================================================================== routing
class TestSupervisorRouting:
    @pytest.fixture(autouse=True)
    def _registry(self, monkeypatch):
        from app import api
        fake = {name: object() for name in (
            "inspect_project", "unreal_ping", "blender_status", "blender_create_asset",
            "blender_convert_asset", "blender_prepare_asset", "blender_prepare_character",
            "create_asset_folder", "import_blender_output", "verify_blender_output",
            "spawn_blender_output", "get_actor", "save_level", "capture_unreal_viewport",
            "install_character_assets", "spawn_character", "verify_character_visible",
            "create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default",
            "compile_blueprint", "get_blueprint_variable_default",
        )}
        monkeypatch.setattr(api, "REGISTRY", fake)
        return api

    def test_table_task_routes_blender_then_unreal(self, _registry):
        task = (
            "Create a simple high-quality test prop: UA_Blender_Test_Table with "
            "sensible dimensions, a basic material, transforms applied, exported "
            "to FBX, then import it into Unreal, spawn it, save, verify and capture proof."
        )
        plan = _registry.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        ids = [s["step_id"] for s in plan["steps"]]
        assert "blender_status" in tools
        assert "blender_create_asset" in tools
        create = next(s for s in plan["steps"] if s["preferred_tool"] == "blender_create_asset")
        assert create["parameters"]["name"] == "UA_Blender_Test_Table"
        assert create["parameters"]["shape"] == "table"
        # handoff chain ordering: blender -> import -> verify -> spawn -> save -> proof
        assert tools.index("blender_create_asset") < tools.index("import_blender_output")
        assert tools.index("import_blender_output") < tools.index("verify_blender_output")
        assert tools.index("verify_blender_output") < tools.index("spawn_blender_output")
        assert ids.index("spawn_blender_output") < ids.index("save_blender_scene")
        assert ids.index("save_blender_scene") < ids.index("blender_evidence")
        assert "spawn_character" not in tools

    def test_character_without_source_has_mannequin_fallback(self, _registry):
        task = (
            "Prepare a better character/environment asset for AvaLive using Blender, "
            "export it, import it into Unreal, place it correctly, validate it, and capture proof."
        )
        plan = _registry.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        assert "blender_prepare_character" in tools
        assert "import_blender_output" in tools
        assert "install_character_assets" in tools  # honest Unreal fallback
        assert "spawn_character" in tools

    def test_convert_task_routes_convert(self, _registry):
        plan = _registry.normalize_execution_plan(
            "Convert the FBX at C:/tmp/model.fbx to GLB using Blender, then import into Unreal.", None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        assert "blender_convert_asset" in tools
        step = next(s for s in plan["steps"] if s["preferred_tool"] == "blender_convert_asset")
        assert step["parameters"]["source"] == "C:/tmp/model.fbx"
        assert step["parameters"]["export_format"] == "glb"

    def test_pure_unreal_task_unaffected(self, _registry):
        task = (
            "Create a blueprint at /Game/Probe with String variable Greeting set "
            "initially to hello and expected value is hello."
        )
        plan = _registry.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        assert not any(t.startswith("blender_") for t in tools)
        assert "create_blueprint" in tools

    def test_needs_blender_negative_cases(self, _registry):
        from app import api
        assert api._needs_blender("Explain Unreal lighting best practices") is False
        assert api._needs_blender("Inspect the active project") is False


# ===================================================================== handoff
class TestBlenderUnrealHandoff:
    def _completed_job(self, isolated_workspace, name="Table", export_path=None):
        job = job_schema.new_job("create_primitive", {"name": name})
        job.status = "COMPLETE"
        job.manifest = {
            "job_id": job.id, "output_path": export_path or "C:/tmp/fake.fbx",
            "export_format": "fbx", "dimensions_cm": [200, 100, 80],
            "materials": [], "textures": [], "validation": {"ok": True},
        }
        job.validation = {"ok": True}
        job_schema.save_job(job)
        return job

    def test_import_blender_output_picks_latest_complete(self, isolated_workspace):
        job = self._completed_job(isolated_workspace)
        bridge = FakeBridge([
            # create_asset_folder -> not used here; import flow:
            {"ok": True, "result": {
                "ok": True, "imported_paths": [
                    "/Game/Imported/wood.wood",
                    "/Game/Imported/Table.Table",
                ], "count": 2, "error": None}},
            # verify wood material -> not a mesh
            {"ok": True, "result": {"ok": False, "code": "ASSET_NOT_FOUND", "asset_path": "/Game/Imported/wood.wood", "class": None, "verified": False}},
            # verify table mesh
            {"ok": True, "result": {"ok": True, "asset_path": "/Game/Imported/Table.Table", "class": "StaticMesh", "verified": True, "bounds": {"size_cm": [200, 100, 80]}, "bounds_ok": True}},
        ])
        it = ImportTools(bridge)
        out = it.import_blender_output(destination_path="/Game/Imported")
        payload = out["result"]
        assert payload["verified"] is True
        assert payload["asset_path"] == "/Game/Imported/Table.Table"
        assert payload["asset_class"] == "StaticMesh"
        handoff = payload["handoff"]
        assert handoff["job_id"] == job.id
        assert handoff["asset_path"] == "/Game/Imported/Table.Table"

    def test_verify_blender_output_uses_handoff(self, isolated_workspace):
        self._completed_job(isolated_workspace)
        bridge = FakeBridge([
            {"ok": True, "result": {"ok": True, "asset_path": "/Game/Imported/Table.Table", "class": "StaticMesh", "verified": True, "bounds": {"size_cm": [200, 100, 80]}, "bounds_ok": True}},
        ])
        it = ImportTools(bridge)
        # Seed the handoff directly.
        it._write_handoff({"job_id": "x", "asset_path": "/Game/Imported/Table.Table"})
        out = it.verify_blender_output()
        assert out["result"]["verified"] is True
        assert out["result"]["class"] == "StaticMesh"

    def test_verify_without_handoff_structured(self, isolated_workspace):
        it = ImportTools(FakeBridge())
        out = it.verify_blender_output()
        assert out["result"]["code"] == "NO_HANDOFF"

    def test_spawn_blender_output_uses_handoff(self, isolated_workspace):
        self._completed_job(isolated_workspace)
        bridge = FakeBridge([
            {"ok": True, "result": {
                "ok": True, "asset_path": "/Game/Imported/Table.Table",
                "asset_class": "StaticMesh", "actor_name": "UA_Blender_Test_Table",
                "actor": {"label": "UA_Blender_Test_Table", "class": "StaticMeshActor"},
                "verified": True}},
        ])
        it = ImportTools(bridge)
        it._write_handoff({"job_id": "x", "asset_path": "/Game/Imported/Table.Table"})
        out = it.spawn_blender_output(actor_name="UA_Blender_Test_Table")
        assert out["result"]["verified"] is True
        assert out["result"]["actor_name"] == "UA_Blender_Test_Table"

    def test_create_asset_folder_resilient(self, isolated_workspace):
        bridge = FakeBridge([{"ok": True, "result": {
            "ok": True, "folder": "/Game/Imported", "created": False,
            "exists": False, "physical_path": "C:/x/Content/Imported",
            "physical_exists": True, "verified": True}}])
        out = ImportTools(bridge).create_asset_folder("/Game/Imported")
        assert out["result"]["verified"] is True


# ===================================================================== contract
class TestBlenderAcceptanceContract:
    def test_blender_criteria_only_for_blender_requests(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Prepare a better character/environment asset for AvaLive using Blender, "
            "export it, import it into Unreal, place it correctly, validate it, and capture proof.")
        criteria = goal["acceptance_criteria"]
        assert "deliverable:blender_asset" in criteria
        assert "deliverable:blender_export" in criteria
        assert "deliverable:unreal_import" in criteria
        assert "deliverable:asset_spawned" in criteria
        assert "deliverable:character" in criteria

    def test_pure_unreal_request_gets_no_blender_criteria(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Create a blueprint at /Game/Probe with String variable Greeting set "
            "initially to hello and expected value is hello.")
        assert not any("blender" in c or "unreal_import" in c for c in goal["acceptance_criteria"])

    def test_reconcile_blender_asset_clears_only_verified_export(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Create a 3D asset using Blender, export it to FBX, import it into Unreal and spawn it.")
        # unverified export must not clear
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "blender_create_asset"},
            {"ok": True, "result": {"ok": True, "verified": False, "status": "FAILED", "export_path": None}})
        assert "deliverable:blender_asset" in goal["pending_criteria"]
        # verified export clears it
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "blender_create_asset"},
            {"ok": True, "result": {"ok": True, "verified": True, "status": "COMPLETE", "export_path": "x.fbx"}})
        assert "deliverable:blender_asset" in goal["completed_criteria"]

    def test_reconcile_character_source_required_does_not_clear(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Prepare a better character using Blender.")
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "blender_prepare_character"},
            {"ok": True, "result": {"ok": True, "verified": False, "status": "COMPLETE",
                                    "code": "REALISTIC_CHARACTER_SOURCE_REQUIRED",
                                    "export_path": None}})
        assert "deliverable:character" in goal["pending_criteria"]
        # the honest Unreal mannequin fallback clears it
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "spawn_character", "parameters": {"actor_name": "UA_Avatar"}},
            {"ok": True, "result": {"ok": True, "verified": True, "mesh": "/Game/Mannequin/SK", "visible": True}})
        assert "deliverable:character" in goal["completed_criteria"]

    def test_reconcile_unreal_import(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Create a 3D asset using Blender, export it to FBX, import it into Unreal and spawn it.")
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "import_blender_output"},
            {"ok": True, "result": {"ok": True, "verified": True, "asset_path": "/Game/Imported/T"}})
        assert "deliverable:unreal_import" in goal["completed_criteria"]

    def test_reconcile_asset_spawned(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(
            "Create a 3D asset using Blender, export it to FBX, import it into Unreal and spawn it.")
        goal = task_goal.reconcile_step(
            goal, {"preferred_tool": "spawn_blender_output", "parameters": {"actor_name": "T"}},
            {"ok": True, "result": {"ok": True, "verified": True, "actor_name": "T"}})
        assert "deliverable:asset_spawned" in goal["completed_criteria"]
