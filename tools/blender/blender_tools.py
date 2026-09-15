"""Registry-facing Blender Agent tools.

Each tool returns the standard envelope used across the Unreal Agent registry:
``{"ok": bool, "result": {...}}`` where the payload itself carries ``ok`` /
``verified`` / ``code`` fields, so the deterministic executor, acceptance
contract and UI treat Blender work exactly like Unreal work. Blender always
runs headless — no tool opens the Blender UI.

The tools are deliberately high-level: a planner expresses WHAT (create a
table, convert an FBX, prepare a character) and the tool owns the job lifecycle
(create -> run -> validate -> manifest).
"""
from __future__ import annotations

from typing import Any, Optional

from blender_agent.agent import BlenderAgent
from blender_agent.job_schema import list_jobs, job_status
from blender_agent.runner import cancel_job
from blender_agent import validation

DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 3


def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
    ok = bool(payload.get("ok"))
    out = {"ok": ok, "result": payload}
    if payload.get("code"):
        out["code"] = payload["code"]
    if payload.get("error"):
        out.setdefault("error", payload["error"])
    return out


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Convert a job record into a tool payload with verified semantics."""
    status = job.get("status")
    evaluation = validation.evaluate_job_result(job)
    return {
        "ok": status == "COMPLETE" and evaluation.get("pass") is True,
        "verified": status == "COMPLETE" and evaluation.get("pass") is True,
        "status": status,
        "job_id": job.get("id"),
        "operation": job.get("operation"),
        "attempts": job.get("attempts"),
        "max_attempts": job.get("max_attempts"),
        "error": job.get("error"),
        "code": "COMPLETE" if status == "COMPLETE" else status,
        "outputs": job.get("outputs"),
        "validation": job.get("validation"),
        "manifest": job.get("manifest"),
        "export_path": (job.get("manifest") or {}).get("output_path"),
        "dimensions_cm": (job.get("validation") or {}).get("dimensions_cm"),
        "materials": (job.get("validation") or {}).get("materials"),
        "proof": (job.get("outputs") or {}).get("proof"),
        "blend_file": (job.get("outputs") or {}).get("blend_file"),
    }


class BlenderTools:
    """High-level Blender Agent tools wired into the tool registry."""

    def __init__(self, on_log=None):
        self.agent = BlenderAgent(on_log=on_log)

    # ------------------------------------------------------ discovery
    def blender_status(self) -> dict[str, Any]:
        """Verify Blender executable + version. Never fabricates success."""
        status = self.agent.status()
        ok = bool(status.get("ok"))
        payload = {
            "ok": ok,
            "verified": ok,
            "code": None if ok else "BLENDER_NOT_FOUND",
            "blender": status.get("blender"),
            "message": status.get("message"),
            "error": None if ok else status.get("message"),
        }
        return _wrap(payload)

    # ------------------------------------------------------ jobs
    def _run(self, operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
        job = self.agent.run_sync(
            operation,
            inputs,
            timeout_seconds=int(inputs.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
            max_attempts=int(inputs.get("max_attempts") or DEFAULT_MAX_ATTEMPTS),
        )
        return _wrap(_job_payload(job))

    def blender_create_asset(
        self,
        name: str,
        shape: str = "cube",
        dimensions_cm: Optional[list] = None,
        materials: Optional[Any] = None,
        export_format: str = "fbx",
        export_dir: Optional[str] = None,
        screenshot: bool = True,
        expected_dimensions_cm: Optional[list] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """Create a 3D asset procedurally in headless Blender and export it."""
        inputs = {
            "name": name,
            "shape": shape,
            "dimensions_cm": dimensions_cm,
            "expected_dimensions_cm": expected_dimensions_cm or dimensions_cm,
            "materials": materials or ["white"],
            "export_format": export_format,
            "export_dir": export_dir,
            "screenshot": screenshot,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._run("create_primitive", inputs)

    def blender_convert_asset(
        self,
        source: str,
        export_format: str = "fbx",
        name: Optional[str] = None,
        export_dir: Optional[str] = None,
        cleanup: bool = True,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """Convert an existing asset file (FBX/GLB/GLTF/OBJ) to another format."""
        inputs = {
            "source": source,
            "export_format": export_format,
            "name": name,
            "export_dir": export_dir,
            "cleanup": cleanup,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._run("convert_asset", inputs)

    def blender_prepare_asset(
        self,
        source: Optional[str] = None,
        name: Optional[str] = None,
        export_format: str = "fbx",
        materials: Optional[Any] = None,
        target_dimension_cm: Optional[float] = None,
        decimate_ratio: Optional[float] = None,
        uv_unwrap: bool = True,
        export_dir: Optional[str] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """Clean up, transform, scale, UV-unwrap and export a mesh for Unreal."""
        inputs = {
            "source": source,
            "name": name,
            "export_format": export_format,
            "materials": materials,
            "target_dimension_cm": target_dimension_cm,
            "decimate_ratio": decimate_ratio,
            "uv_unwrap": uv_unwrap,
            "export_dir": export_dir,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._run("prepare_asset", inputs)

    def blender_prepare_character(
        self,
        source: Optional[str] = None,
        name: Optional[str] = None,
        export_format: str = "fbx",
        target_height_cm: Optional[float] = None,
        export_dir: Optional[str] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """Prepare a real character asset (mesh + skeleton + animations) for
        Unreal. Returns REALISTIC_CHARACTER_SOURCE_REQUIRED when no realistic
        source character exists — never fabricates one."""
        inputs = {
            "source": source,
            "name": name,
            "export_format": export_format,
            "target_height_cm": target_height_cm,
            "export_dir": export_dir,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._run("prepare_character", inputs)

    def blender_inspect_asset(
        self,
        source: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """Inspect a source asset: meshes, armature, materials, textures, animations."""
        inputs = {
            "source": source,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._run("inspect_asset", inputs)

    # ------------------------------------------------------ job control
    def blender_job_status(self, job_id: str) -> dict[str, Any]:
        """Return the persisted record of one Blender job."""
        job = job_status(job_id)
        if job is None:
            return {"ok": False, "result": {"ok": False, "code": "JOB_NOT_FOUND", "error": f"job not found: {job_id}", "job_id": job_id}}
        return _wrap(_job_payload(job))

    def blender_jobs_list(self, limit: int = 20) -> dict[str, Any]:
        """List recent Blender jobs (id, operation, status)."""
        jobs = list_jobs()[: int(limit)]
        return {
            "ok": True,
            "result": {"ok": True, "jobs": jobs, "count": len(jobs)},
        }

    def blender_cancel_job(self, job_id: str) -> dict[str, Any]:
        """Request cancellation of a running Blender job."""
        return {"ok": True, "result": cancel_job(job_id)}

    def blender_recover(self) -> dict[str, Any]:
        """Detect interrupted Blender jobs and resume/retry them (restart recovery)."""
        return {"ok": True, "result": self.agent.recover(relaunch=True)}

    def blender_verify_export(self, job_id: str) -> dict[str, Any]:
        """Re-validate the exported file + manifest of a completed job."""
        job = job_status(job_id)
        if job is None:
            return {"ok": False, "result": {"ok": False, "code": "JOB_NOT_FOUND", "error": f"job not found: {job_id}"}}
        file_check = validation.validate_export_file((job.get("manifest") or {}).get("output_path"))
        manifest_check = validation.validate_manifest(job.get("manifest"))
        ok = bool(file_check.get("ok") and manifest_check.get("ok"))
        return _wrap({
            "ok": ok,
            "verified": ok,
            "code": None if ok else "EXPORT_VERIFY_FAILED",
            "job_id": job_id,
            "file": file_check,
            "manifest": manifest_check,
            "error": None if ok else (file_check.get("error") or manifest_check.get("error")),
        })
