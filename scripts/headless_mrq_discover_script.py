"""headless_mrq_discover_script.py - ENGINE-SIDE discovery of concrete MRQ pass/output classes.

Writes reports/cinematic/headless_mrq/discover_result.json.
"""
import json
import os

import unreal

RESULTS = {"classes": []}

# Get the base render pass class by C++ path (robust to Python name differences).
base_pass = None
for path in (
    "/Script/MovieRenderPipelineRenderPasses.MoviePipelineRenderPass",
    "/Script/MovieRenderPipelineCore.MoviePipelineRenderPass",
):
    try:
        base_pass = unreal.load_class(None, path)
        if base_pass is not None:
            break
    except Exception:
        base_pass = None
RESULTS["base_pass_resolved"] = str(base_pass) if base_pass else None

out_base = None
for path in (
    "/Script/MovieRenderPipelineCore.MoviePipelineImageSequenceOutputBase",
    "/Script/MovieRenderPipelineCore.MoviePipelineOutputBase",
):
    try:
        out_base = unreal.load_class(None, path)
        if out_base is not None:
            break
    except Exception:
        out_base = None
RESULTS["out_base_resolved"] = str(out_base) if out_base else None

for name in dir(unreal):
    if not name.startswith("MoviePipeline"):
        continue
    try:
        cls = getattr(unreal, name)
    except Exception:
        continue
    if not isinstance(cls, type):
        continue
    rec = {"name": name}
    try:
        rec["abstract"] = bool(cls.is_abstract())
    except Exception:
        rec["abstract"] = None
    try:
        rec["is_pass"] = bool(base_pass is not None and cls.is_subclass_of(base_pass))
    except Exception:
        rec["is_pass"] = None
    try:
        rec["is_output"] = bool(out_base is not None and cls.is_subclass_of(out_base))
    except Exception:
        rec["is_output"] = None
    RESULTS["classes"].append(rec)

# Sort: concrete passes first, then outputs.
RESULTS["classes"].sort(
    key=lambda r: (0 if r["is_pass"] and not r["abstract"] else
                   1 if r["is_pass"] else
                   2 if r["is_output"] and not r["abstract"] else 3)
)

out_path = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "reports", "cinematic", "headless_mrq",
    "discover_result.json"))
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(RESULTS, fh, indent=2, default=str)
print("[MRQ_DISCOVER] wrote " + out_path)