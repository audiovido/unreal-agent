"""BlenderAgent — the out-of-Blender orchestration facade.

Accepts structured jobs, runs them headlessly with bounded timeout/retry,
persists every state change, and exposes restart/recovery so a crashed
Supervisor can resume work without duplicating completed outputs.
"""
from __future__ import annotations

from typing import Any, Callable

from blender_agent import job_schema, validation
from blender_agent.config import blender_executable, blender_version, discover_blender
from blender_agent.job_schema import BlenderJob, load_job, new_job, to_dict
from blender_agent.runner import cancel_job, run_with_retries


class BlenderAgent:
    """Headless Blender job orchestrator."""

    def __init__(self, on_log: Callable[[str], None] | None = None):
        self.on_log = on_log

    # ------------------------------------------------------ discovery
    def status(self) -> dict[str, Any]:
        """Blender presence + version. Never fabricates success."""
        exe = discover_blender()
        if exe is None:
            return {
                "ok": False,
                "code": "BLENDER_NOT_FOUND",
                "blender": None,
                "message": "Blender executable not found on this machine.",
                "hint": "Set UNREAL_AGENT_BLENDER_EXE or install Blender, or use the vendored portable install.",
            }
        version = blender_version(exe)
        return {
            "ok": bool(version.get("ok")),
            "blender": {
                "exe": str(exe).replace("\\", "/"),
                "version": version.get("version"),
            },
            "bpy_verified": None,  # verified by the live headless probe
            "message": f"Blender {version.get('version')} at {exe}" if version.get("ok") else version.get("error"),
        }

    # ------------------------------------------------------ jobs
    def submit(self, operation: str, inputs: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        job = new_job(operation, inputs, **kwargs)
        return to_dict(job)

    def run(self, job_id: str) -> dict[str, Any]:
        job = load_job(job_id)
        if job is None:
            return {"ok": False, "code": "JOB_NOT_FOUND", "error": f"job not found: {job_id}", "job_id": job_id}
        run_with_retries(job, on_log=self.on_log)
        return to_dict(job)

    def run_job(self, job: BlenderJob | dict[str, Any]) -> dict[str, Any]:
        """Run an already-created job (by object or dict) synchronously."""
        if isinstance(job, dict):
            job = load_job(job.get("id", ""))
            if job is None:
                return {"ok": False, "code": "JOB_NOT_FOUND", "error": "job not found"}
        run_with_retries(job, on_log=self.on_log)
        return to_dict(job)

    def run_sync(self, operation: str, inputs: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        """Create + run a job synchronously; returns its full record."""
        job = self.submit(operation, inputs, **kwargs)
        return self.run(job["id"])

    def status_of(self, job_id: str) -> dict[str, Any] | None:
        return job_schema.job_status(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return cancel_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        return job_schema.list_jobs()

    def recover(self, relaunch: bool = True) -> dict[str, Any]:
        """Restart/recovery: detect interrupted RUNNING jobs and retry them.

        COMPLETE jobs (manifest present) are never re-run, so completed
        outputs are never duplicated. Returns a summary of what was recovered.
        """
        recovered = job_schema.recover_incomplete_jobs(
            relaunch_callback=(self.run if relaunch else None)
        )
        return {
            "ok": True,
            "recovered_count": len(recovered),
            "recovered": recovered,
        }

    # ------------------------------------------------------ evaluation
    def evaluate(self, job_id: str) -> dict[str, Any]:
        """Verdict for a job (pass/fail + evidence) for the parent goal."""
        job = self.status_of(job_id)
        if job is None:
            return {"pass": False, "code": "JOB_NOT_FOUND", "error": f"job not found: {job_id}"}
        return validation.evaluate_job_result(job)
