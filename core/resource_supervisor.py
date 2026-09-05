"""resource_supervisor.py — Shadow-host resource supervision (Phase 6).

Tracks CPU / RAM / GPU memory / active Unreal processes and classifies work
into two policies:

    SAFE_PARALLEL  — project inspection, file/code work, read-only queries,
                     lightweight editor operations. Allowed to run
                     concurrently across sessions.
    GPU_HEAVY      — rendering, Visual Director capture loops, shader
                     compilation, heavy asset import, cinematic rendering.
                     Gated: queued or throttled when VRAM headroom is low or
                     another heavy task is already running.

The gate exposes RUNNING / QUEUED_RESOURCE / THROTTLED decisions per task.
No session is ever blocked by another project's SAFE_PARALLEL work; only the
shared GPU resources serialize heavy work.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

RUNNING = "RUNNING"
QUEUED_RESOURCE = "QUEUED_RESOURCE"
THROTTLED = "THROTTLED"

# ---------------------------------------------------------------------------
# Classification vocabulary (deterministic; independent of any LLM).
# ---------------------------------------------------------------------------

_GPU_HEAVY_TERMS = (
    "render", "rendering", "cinematic", "movie", "movie render queue",
    "path tracer", "lumen", "nanite bake", "shader", "shader compile",
    "capture loop", "viewport capture", "screenshot burst", "heavy import",
    "import fbx", "import gltf", "bake", "lightmass", "volumetric",
    "niagara sim", "particle sim", "metahuman", "hair", "groom",
    "ray traced", "raytracing", "rtx", "cinematics", "animation render",
    "video render", "4k", "8k", "export video", "render out",
)

_GPU_HEAVY_TOOLS = {
    "capture_pie_viewport",
    "capture_unreal_viewport",
    "visual_review_unreal",
    "import_asset",
    "import_asset_fbx",
    "import_asset_gltf",
    "import_blender_output",
    "spawn_blender_output",
    "blender_create_asset",
    "blender_convert_asset",
    "blender_prepare_asset",
    "scrub_and_play",
    "start_pie",
}


def classify_prompt(prompt: str) -> str:
    """SAFE_PARALLEL | GPU_HEAVY from prompt vocabulary."""
    text = str(prompt or "").lower()
    if any(term in text for term in _GPU_HEAVY_TERMS):
        return "GPU_HEAVY"
    return "SAFE_PARALLEL"


def classify_tools(tools: List[str]) -> str:
    """GPU_HEAVY when any planned tool is GPU-bound, else SAFE_PARALLEL."""
    for tool in tools or []:
        if str(tool or "") in _GPU_HEAVY_TOOLS:
            return "GPU_HEAVY"
    return "SAFE_PARALLEL"


def classify(step_or_prompt: Any) -> str:
    """Accept a prompt string or a step dict / tool name."""
    if isinstance(step_or_prompt, str):
        return classify_prompt(step_or_prompt)
    if isinstance(step_or_prompt, dict):
        tools = [step_or_prompt.get("preferred_tool")]
        return classify_tools(tools)
    return "SAFE_PARALLEL"


# ---------------------------------------------------------------------------
# Process / GPU sampling (Windows tasklist + nvidia-smi; psutil if present).
# ---------------------------------------------------------------------------

def _run_capture(args: List[str], timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "") + (result.stderr or "")
    except Exception:
        return ""


def _unreal_editor_pids() -> List[int]:
    out = _run_capture(
        ["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe",
         "/FO", "CSV", "/NH"])
    pids: List[int] = []
    for line in out.splitlines():
        parts = line.strip("\"").split("\",\"")
        if len(parts) >= 2 and parts[0].lower() == "unrealeditor.exe" \
                and parts[1].strip().isdigit():
            pids.append(int(parts[1].strip()))
    return sorted(set(pids))


def _gpu_memory_mb() -> Optional[Dict[str, Any]]:
    """nvidia-smi query (Windows/most Shadow hosts). Returns None when the
    GPU cannot be queried; callers treat None as 'unknown, be conservative'
    for GPU_HEAVY gating only when a heavy task is already active."""
    text = _run_capture([
        "nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits"])
    try:
        used, total, util = [float(x) for x in text.strip().split(",")]
        return {"used_mb": used, "total_mb": total,
                "utilization_pct": util}
    except Exception:
        return None


class ResourceSupervisor:
    """Background sampler + gating policy. Owns no execution state — it only
    measures the host and advises the session runner."""

    def __init__(self, sample_interval: float = 5.0,
                 max_heavy_tasks: int = 1,
                 vram_headroom_frac: float = 0.20,
                 active_heavy_provider: Optional[Callable[[], int]] = None):
        self.sample_interval = float(sample_interval)
        self.max_heavy_tasks = max(1, int(os.getenv(
            "UA_MAX_GPU_HEAVY_TASKS", str(max_heavy_tasks))))
        self.vram_headroom_frac = float(vram_headroom_frac)
        self._active_heavy_provider = active_heavy_provider or (lambda: 0)
        self._lock = threading.RLock()
        self._snapshot: Dict[str, Any] = self._empty_snapshot()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _empty_snapshot(self) -> Dict[str, Any]:
        return {
            "sampled_at": 0.0,
            "cpu_percent": None,
            "ram_total_mb": None,
            "ram_used_mb": None,
            "ram_used_percent": None,
            "gpu": None,
            "unreal_processes": [],
            "active_heavy_tasks": 0,
        }

    # -- sampling -------------------------------------------------------------
    def _sample_once(self) -> Dict[str, Any]:
        snap: Dict[str, Any] = {
            "sampled_at": time.time(),
            "cpu_percent": None,
            "ram_total_mb": None,
            "ram_used_mb": None,
            "ram_used_percent": None,
            "gpu": None,
            "unreal_processes": _unreal_editor_pids(),
            "active_heavy_tasks": self._active_heavy_provider(),
        }
        try:
            import psutil  # optional dependency
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            snap["cpu_percent"] = round(cpu, 1)
            snap["ram_total_mb"] = round(mem.total / (1024 * 1024), 1)
            snap["ram_used_mb"] = round(mem.used / (1024 * 1024), 1)
            snap["ram_used_percent"] = round(mem.percent, 1)
        except Exception:
            pass
        snap["gpu"] = _gpu_memory_mb()
        return snap

    def start(self) -> "ResourceSupervisor":
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="aivido-resource-supervisor",
                daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    self._snapshot = self._sample_once()
            except Exception:
                pass
            self._stop.wait(self.sample_interval)

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    # -- gating -----------------------------------------------------------------
    def gate(self, kind: str) -> str:
        """Policy decision for a classified task.

        SAFE_PARALLEL always runs (projects never block each other on safe
        work). GPU_HEAVY runs while fewer than max_heavy_tasks are active and
        VRAM headroom is above the floor (or GPU is unknown and nothing is
        running yet). Returns RUNNING | QUEUED_RESOURCE | THROTTLED.
        """
        if kind != "GPU_HEAVY":
            return RUNNING
        snap = self.snapshot()
        active = int(snap.get("active_heavy_tasks") or 0)
        # The live provider is authoritative (the sampler only refreshes it
        # every interval); a fresh supervisor gates correctly immediately.
        try:
            active = max(active, int(self._active_heavy_provider() or 0))
        except Exception:
            pass
        if active >= self.max_heavy_tasks:
            return QUEUED_RESOURCE
        gpu = snap.get("gpu")
        if gpu:
            total = float(gpu.get("total_mb") or 0)
            used = float(gpu.get("used_mb") or 0)
            if total > 0:
                headroom = 1.0 - (used / total)
                if headroom < self.vram_headroom_frac:
                    return THROTTLED
        return RUNNING


_default_supervisor: Optional[ResourceSupervisor] = None
_supervisor_lock = threading.Lock()


def get_default_supervisor() -> ResourceSupervisor:
    global _default_supervisor
    with _supervisor_lock:
        if _default_supervisor is None:
            _default_supervisor = ResourceSupervisor()
        return _default_supervisor


def snapshot() -> Dict[str, Any]:
    return get_default_supervisor().snapshot()