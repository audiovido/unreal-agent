"""cinematic_mission.py — live cinematic mission entry point.

Wires the hermetic cinematic director to the live Unreal adapter and
persists real evidence. Safe to import anywhere (no live side effects);
the live bridge is only touched inside run_live_cinematic().

Mission lifecycle (V2 contract):
    prompt -> run_cinematic() -> real proof frames -> JSON result path.
Never fakes: BLOCKED reasons and engine-closed gaps are recorded verbatim.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from core.cinematic_director import (
    run_cinematic,
    write_cinematic_result,
)
from core.cinematic_assets import decide_asset_strategy


def default_cinematic_out_dir() -> str:
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "reports", "cinematic")
    os.makedirs(root, exist_ok=True)
    return root


def _build_live_adapter(bridge, out_root: str):
    from tools.unreal.cinematic_live import CinematicLiveAdapter
    return CinematicLiveAdapter(bridge, output_root=out_root)


def run_live_cinematic(
    prompt: str,
    *,
    bridge=None,
    out_dir: Optional[str] = None,
    resolution: Any = "1920x1080",
    max_visual_passes: int = 3,
    vision=None,
    engine: str = "unreal",
) -> Dict[str, Any]:
    """Full live cinematic mission on the configured Unreal bridge.

    ``bridge`` may be injected (tests) or defaults to the canonical live
    UnrealBridge (127.0.0.1:6766). Returns the CinematicResult + artifact
    paths; caller decides what to surface.
    """
    from tools.unreal.movie_render_queue import MovieRenderQueueDriver
    from tools.unreal.unreal_bridge import UnrealBridge

    bridge = bridge or UnrealBridge()
    out_dir = out_dir or default_cinematic_out_dir()
    w, h = MovieRenderQueueDriver.resolution_for(resolution)
    adapter = _build_live_adapter(bridge, out_root=out_dir)
    adapter.set_resolution(w, h)

    result = run_cinematic(
        prompt, adapter, out_dir=out_dir,
        vision=vision, max_visual_passes=max_visual_passes)
    result["resolution"] = [w, h]
    result["rendered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    result["engine"] = engine
    path = write_cinematic_result(result, out_dir)
    result["result_path"] = path
    return result


__all__ = ["run_live_cinematic", "default_cinematic_out_dir",
           "decide_asset_strategy"]
