"""Blender Agent — headless Blender automation for the Unreal Agent pipeline.

This package is stdlib-only so the same code runs in two places:

1. OUTSIDE Blender (the Agent / runner side):
   - discovers the Blender executable
   - manages a persisted, structured job store
   - spawns headless Blender with bounded timeout / retry / cancellation

2. INSIDE Blender (bpy side):
   - geometry / materials / import / export / rigging / validation ops
   - executes a job dict and writes a structured result file

A job never depends on a human touching the Blender UI. All state is JSON.
"""

from blender_agent.job_schema import (
    BlenderJob,
    JOB_STATES,
    new_job,
    validate_job,
    load_job,
    save_job,
    list_jobs,
    to_dict,
    job_status,
)
from blender_agent.config import (
    blender_executable,
    blender_version,
    discover_blender,
    workspace_layout,
    ensure_workspace,
)

__all__ = [
    "BlenderJob",
    "JOB_STATES",
    "new_job",
    "validate_job",
    "load_job",
    "save_job",
    "list_jobs",
    "to_dict",
    "job_status",
    "blender_executable",
    "blender_version",
    "discover_blender",
    "workspace_layout",
    "ensure_workspace",
]
