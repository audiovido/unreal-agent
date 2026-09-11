"""Auto-generated headless Blender entry (Blender Agent)."""
import sys, os, json, traceback

PROJECT_ROOT = 'C:\\Users\\Shadow\\Desktop\\Unreal-Agent'
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "blender_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

job_path = sys.argv[sys.argv.index("--") + 1]
result_path = sys.argv[sys.argv.index("--") + 2]

from blender_agent.asset_pipeline import execute_job_file

sys.exit(execute_job_file(job_path, result_path))
