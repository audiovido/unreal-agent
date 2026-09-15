"""Structured Blender job contract + durable JSON job store.

Generic job states (per the integration spec):

    QUEUED -> RUNNING -> VALIDATING -> COMPLETE
                          |                |
                          v                v
                       FAILED          (retry) RETRYING -> RUNNING

Job shape (all keys always present):

    {
      "id": "...",
      "operation": "create_primitive | convert_asset | prepare_asset | "
                   "prepare_character | inspect_asset | render_screenshot",
      "inputs": {...},
      "outputs": {...},
      "status": "QUEUED|RUNNING|VALIDATING|FAILED|RETRYING|COMPLETE|CANCELLED",
      "validation": {...},
      "manifest": {...},
      "error": null,
      "attempts": 0,
      "max_attempts": 3,
      "timeout_seconds": 600,
      "created_at": ...,
      "updated_at": ...,
      "log": [...]
    }

Persistence supports restart/recovery: every status change is written
atomically (tmp + replace), so a crashed Supervisor/Agent can reload RUNNING
jobs, detect the dead Blender process, and resume or retry them without
duplicating completed outputs (a COMPLETE job is never re-executed).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from blender_agent.config import ensure_workspace

JOB_STATES = ("QUEUED", "RUNNING", "VALIDATING", "FAILED", "RETRYING", "COMPLETE", "CANCELLED")

OPERATIONS = (
    "create_primitive",
    "convert_asset",
    "prepare_asset",
    "prepare_character",
    "inspect_asset",
    "render_screenshot",
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 600


@dataclass
class BlenderJob:
    """A single structured, persisted Blender task."""

    operation: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "QUEUED"
    validation: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    error: Any = None
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.operation not in OPERATIONS:
            raise ValueError(f"Unknown Blender operation: {self.operation!r}")


def _job_dir() -> Path:
    return ensure_workspace()["jobs"]


def to_dict(job: BlenderJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "operation": job.operation,
        "inputs": job.inputs,
        "outputs": job.outputs,
        "status": job.status,
        "validation": job.validation,
        "manifest": job.manifest,
        "error": job.error,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "timeout_seconds": job.timeout_seconds,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "log": job.log,
    }


def new_job(
    operation: str,
    inputs: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
    max_attempts: int | None = None,
    timeout_seconds: int | None = None,
) -> BlenderJob:
    """Create a job from a validated operation + inputs."""
    job = BlenderJob(
        operation=operation,
        inputs=dict(inputs or {}),
        id=job_id or str(uuid.uuid4()),
    )
    if max_attempts is not None:
        job.max_attempts = int(max_attempts)
    if timeout_seconds is not None:
        job.timeout_seconds = int(timeout_seconds)
    job.log.append({"at": time.time(), "level": "info", "message": "job created"})
    save_job(job)
    return job


def validate_job(job: BlenderJob) -> tuple[bool, str]:
    """Structural validation of a job before execution."""
    if not job.id:
        return False, "job.id is required"
    if job.operation not in OPERATIONS:
        return False, f"unsupported operation: {job.operation}"
    if not isinstance(job.inputs, dict):
        return False, "job.inputs must be an object"
    if job.max_attempts < 1:
        return False, "max_attempts must be >= 1"
    if job.timeout_seconds < 2:
        return False, "timeout_seconds must be >= 2"
    return True, ""


def _atomic_write(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def save_job(job: BlenderJob) -> BlenderJob:
    job.updated_at = time.time()
    _atomic_write(_job_dir() / f"{job.id}.json", to_dict(job))
    return job


def load_job(job_id: str) -> BlenderJob | None:
    path = _job_dir() / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BlenderJob(
            operation=data.get("operation", ""),
            inputs=data.get("inputs", {}),
            outputs=data.get("outputs", {}),
            id=data.get("id", job_id),
            status=data.get("status", "QUEUED"),
            validation=data.get("validation", {}),
            manifest=data.get("manifest", {}),
            error=data.get("error"),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            timeout_seconds=int(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            log=data.get("log", []),
        )
    except Exception as exc:
        return None


def list_jobs() -> list[dict[str, Any]]:
    job_dir = _job_dir()
    if not job_dir.exists():
        return []
    out = []
    paths = [p for p in job_dir.glob("*.json") if not p.name.endswith(".result.json")]
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "id": data.get("id"),
            "operation": data.get("operation"),
            "status": data.get("status"),
            "attempts": data.get("attempts"),
            "max_attempts": data.get("max_attempts"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "error": data.get("error"),
            "has_manifest": bool(data.get("manifest")),
        })
    return out


def job_status(job_id: str) -> dict[str, Any] | None:
    job = load_job(job_id)
    if job is None:
        return None
    return to_dict(job)


def append_log(job: BlenderJob, message: str, level: str = "info") -> BlenderJob:
    job.log.append({"at": time.time(), "level": level, "message": str(message)})
    return job


def recover_incomplete_jobs(relaunch_callback=None) -> list[dict[str, Any]]:
    """Restart/recovery: find RUNNING/VALIDATING jobs left by a crashed owner.

    A COMPLETE job (manifest written) is never touched — completed outputs are
    not duplicated. A QUEUED/RETRYING job is left alone. RUNNING/VALIDATING
    jobs are marked RETRYING (attempts < max) or FAILED (attempts exhausted);
    ``relaunch_callback`` may re-dispatch them immediately.
    """
    recovered = []
    for summary in list_jobs():
        if summary["status"] not in ("RUNNING", "VALIDATING"):
            continue
        job = load_job(summary["id"])
        if job is None:
            continue
        if job.attempts >= job.max_attempts:
            job.status = "FAILED"
            job.error = job.error or "process died and retries exhausted"
            append_log(job, "recovered as FAILED (retries exhausted)", "warning")
        else:
            job.status = "RETRYING"
            append_log(job, "recovered from interrupted execution; will retry", "warning")
        save_job(job)
        recovered.append(to_dict(job))
        if relaunch_callback is not None and job.status == "RETRYING":
            relaunch_callback(job)
    return recovered
