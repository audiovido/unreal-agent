"""Headless Blender process runner.

The runner is the ONLY place Blender is launched. It never opens the Blender
UI: every job runs as ``blender --background --factory-startup --python ...``.

Guarantees:
  - bounded timeout (process killed when exceeded)
  - bounded retries (driven by job.attempts / max_attempts)
  - cancellation (kill + mark CANCELLED)
  - logs (stdout/stderr captured into the job log)
  - output manifest + validation evidence survive in the job record

The in-Blender entry script is generated on demand and imports the same
``blender_agent`` package from the project root, so there is no code copy.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from blender_agent.config import blender_executable, ensure_workspace
from blender_agent.job_schema import (
    BlenderJob,
    append_log,
    load_job,
    new_job,
    save_job,
    to_dict,
    validate_job,
)

ROOT = Path(__file__).resolve().parents[1]

_ENTRY_TEMPLATE = r'''"""Auto-generated headless Blender entry (Blender Agent)."""
import sys, os, json, traceback

PROJECT_ROOT = {project_root!r}
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "blender_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

job_path = sys.argv[sys.argv.index("--") + 1]
result_path = sys.argv[sys.argv.index("--") + 2]

from blender_agent.asset_pipeline import execute_job_file

sys.exit(execute_job_file(job_path, result_path))
'''


class BlenderRunnerError(Exception):
    pass


class BlenderTimeout(BlenderRunnerError):
    pass


class BlenderCancelled(BlenderRunnerError):
    pass


class BlenderMissing(BlenderRunnerError):
    pass


def _entry_script() -> Path:
    layout = ensure_workspace()
    script_dir = layout["blender_work"] / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    script = script_dir / "entry.py"
    script.write_text(_ENTRY_TEMPLATE.format(project_root=str(ROOT)), encoding="utf-8")
    return script


def _cancel_marker(job_id: str) -> Path:
    return ensure_workspace()["jobs"] / f"{job_id}.cancel"


def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation. A running process is killed at the next poll."""
    marker = _cancel_marker(job_id)
    marker.write_text(json.dumps({"at": time.time()}), encoding="utf-8")
    job = load_job(job_id)
    if job is not None:
        append_log(job, "cancel requested")
        save_job(job)
    return {"ok": True, "job_id": job_id, "cancel_requested": True}


def _is_cancelled(job_id: str) -> bool:
    return _cancel_marker(job_id).exists()


def _clear_cancel_marker(job_id: str):
    try:
        _cancel_marker(job_id).unlink(missing_ok=True)
    except OSError:
        pass


def _read_result(result_path: Path) -> dict[str, Any] | None:
    if not result_path.exists():
        return None
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_once(job: BlenderJob, *, on_log: Callable[[str], None] | None = None) -> BlenderJob:
    """Execute one attempt of a job inside headless Blender.

    Mutates the job in place (status/attempts/log/outputs/validation/error) and
    persists it. Does NOT implement retry loops — the caller decides retries.
    """
    valid, err = validate_job(job)
    if not valid:
        job.status = "FAILED"
        job.error = err
        append_log(job, f"job failed validation: {err}", "error")
        save_job(job)
        return job

    try:
        exe = blender_executable()
    except FileNotFoundError as exc:
        job.status = "FAILED"
        job.error = f"BLENDER_NOT_FOUND: {exc}"
        append_log(job, str(exc), "error")
        save_job(job)
        return job

    job.attempts += 1
    job.status = "RUNNING"
    job.error = None
    append_log(job, f"attempt {job.attempts}/{job.max_attempts} starting (headless)")
    save_job(job)
    if on_log:
        on_log(f"[blender] job {job.id} attempt {job.attempts} running")

    _clear_cancel_marker(job.id)

    layout = ensure_workspace()
    result_path = layout["jobs"] / f"{job.id}.result.json"
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass

    script = _entry_script()
    cmd = [
        str(exe),
        "--background",
        "--factory-startup",
        "--python",
        str(script),
        "--",
        str(layout["jobs"] / f"{job.id}.json"),
        str(result_path),
    ]

    env = dict(os.environ)
    env["UA_BLENDER_PROJECT_ROOT"] = str(ROOT)
    env["UA_BLENDER_JOB_ID"] = job.id

    proc = None
    drain = {"lines": [], "done": False}
    started = time.time()

    def _kill_tree():
        """Kill the process AND its children (a .bat wrapper leaves an orphaned
        python alive on Windows; the orphan would hold stdout open forever)."""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(ROOT),
        )

        # Drain stdout on a daemon thread so a killed-but-orphaned child can
        # never block the runner on a read.
        def _drain_stdout():
            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        drain["lines"].append(line)
            except Exception:
                pass
            drain["done"] = True

        threading.Thread(target=_drain_stdout, daemon=True).start()

        deadline = started + max(int(job.timeout_seconds), 2)
        while True:
            if _is_cancelled(job.id):
                _kill_tree()
                proc.wait(timeout=10)
                job.status = "CANCELLED"
                job.error = "cancelled by user"
                append_log(job, "cancelled", "warning")
                save_job(job)
                return job

            # Poll without blocking past the deadline.
            try:
                proc.wait(timeout=0.5)
                done = True
            except subprocess.TimeoutExpired:
                done = False

            if time.time() > deadline and not done:
                _kill_tree()
                proc.wait(timeout=10)
                job.status = "FAILED"
                job.error = f"TIMEOUT after {int(job.timeout_seconds)}s"
                append_log(job, f"timed out after {int(job.timeout_seconds)}s; process tree killed", "error")
                save_job(job)
                return job

            if done:
                break

        # Give the drain thread a moment to finish consuming the pipe.
        drain_deadline = time.time() + 5
        while not drain["done"] and time.time() < drain_deadline:
            time.sleep(0.05)

        output = "".join(drain["lines"])
        if output.strip():
            append_log(job, "--- blender stdout ---")
            for chunk in output.splitlines()[-400:]:
                append_log(job, chunk)
        if on_log and output.strip():
            on_log(output[-1200:])

        result = _read_result(result_path)

        if proc.returncode != 0 and result is None:
            job.status = "FAILED"
            job.error = f"blender exited with code {proc.returncode} and wrote no result"
            append_log(job, f"exit code {proc.returncode}, no result file", "error")
            save_job(job)
            return job

        if result is None:
            job.status = "FAILED"
            job.error = "blender finished but wrote no structured result"
            append_log(job, "no structured result", "error")
            save_job(job)
            return job

        ok = bool(result.get("ok"))
        job.outputs = dict(result.get("outputs") or {})
        job.validation = dict(result.get("validation") or {})
        job.manifest = dict(result.get("manifest") or {})
        job.error = result.get("error")
        if ok:
            job.status = "COMPLETE"
            append_log(job, "job COMPLETE")
        else:
            job.status = "FAILED"
            append_log(job, f"job failed inside Blender: {result.get('error')}", "error")
        save_job(job)
        return job

    except (BlenderTimeout, BlenderCancelled) as exc:
        # Timeout/cancel already persisted the terminal state above; propagate
        # nothing — the caller reads the job record.
        return job
    except Exception as exc:  # pragma: no cover - defensive
        job.status = "FAILED"
        job.error = f"{type(exc).__name__}: {exc}"
        append_log(job, job.error, "error")
        save_job(job)
        return job


def run_with_retries(job: BlenderJob, *, on_log: Callable[[str], None] | None = None) -> BlenderJob:
    """Run a job with bounded retries.

    Retries happen only while attempts < max_attempts and the failure is
    classified as retryable (timeout, missing result, process crash). A job
    that reached COMPLETE is returned untouched (no duplicate execution).
    Failures that never started an attempt (attempts == 0: structural
    validation errors, missing Blender) are terminal — retrying cannot fix
    them, and looping on them would spin forever.
    """
    if job.status == "COMPLETE":
        return job

    while job.attempts < job.max_attempts:
        job = run_once(job, on_log=on_log)
        if job.status in ("COMPLETE", "CANCELLED"):
            return job
        if job.status == "FAILED" and (job.attempts >= job.max_attempts or job.attempts == 0):
            return job
        # Retryable failure.
        job.status = "RETRYING"
        append_log(job, "retrying job", "warning")
        save_job(job)
        if on_log:
            on_log(f"[blender] job {job.id} retrying ({job.attempts}/{job.max_attempts})")

    return job


def run_job_sync(
    operation: str,
    inputs: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
    max_attempts: int | None = None,
    timeout_seconds: int | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create + run a job synchronously and return its structured record."""
    job = new_job(
        operation,
        inputs,
        job_id=job_id,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    run_with_retries(job, on_log=on_log)
    return to_dict(job)


def run_job_file(job_path: str | Path, result_path: str | Path) -> int:
    """Execute a job already persisted to disk (used by the retry/resume path).

    Reads the job, runs with retries, writes the final record back. Returns a
    process exit code (0 = COMPLETE/CANCELLED, 1 = FAILED).
    """
    job = load_job(Path(job_path).stem)
    if job is None:
        return 1
    run_with_retries(job)
    save_job(job)
    return 0 if job.status in ("COMPLETE", "CANCELLED") else 1
