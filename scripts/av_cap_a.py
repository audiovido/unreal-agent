"""Single viewport capture. TAG is baked per variant (A/B/C)."""
import os

import unreal

TAG = "A"

saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
os.makedirs(out_dir, exist_ok=True)
p = os.path.join(out_dir, f"live2_{TAG}.png")
if os.path.isfile(p):
    os.remove(p)
d = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p))
__bridge_result__ = {"path": p, "size": os.path.getsize(p) if os.path.isfile(p) else 0, "diag": d}
