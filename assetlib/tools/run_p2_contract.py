"""FREEBUFF ASSET P2: host contract runner + milestone report.

The scenarios table below is the executable contract: each entry shells into
headless Blender 4.2 (blender_ops.convert), then asserts its expectations.
pytest imports the same table + run_job_host, so the tests and the milestone
report cannot drift apart.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ASSETLIB = TOOLS.parent
if str(ASSETLIB.parent) not in sys.path:
    sys.path.insert(0, str(ASSETLIB.parent))
from assetlib.tools.env import discover_blender, ensure_layout  # noqa: E402

LAYOUT = ensure_layout()
SAMPLES = Path(LAYOUT["tests_blender"]) / "samples"
OUT_ROOT = Path(LAYOUT["tests_blender"]) / "p2_out"
BLEND_DIR = Path(LAYOUT["tests_blender"]) / "p2_work"
PROOF_DIR = Path(LAYOUT["proof"])


def sample(name: str) -> Path:
    return SAMPLES / name


def _job(scn: dict, work_root: Path | None = None) -> dict:
    """Build a P2 job, optionally routing generated artifacts off-repo."""
    work_root = Path(work_root) if work_root is not None else OUT_ROOT
    scenario_root = work_root / scn["id"]
    inputs = {
        "source": str(sample(scn["source"])),
        "name": scn.get("name"),
        "export_formats": scn.get("export_formats", ["fbx"]),
        "export_dir": str(scenario_root / "exports"),
        "blend_dir": str(work_root / "blend"),
        "origin_center": scn.get("origin_center", "BOUNDS"),
        "decimate_ratio": scn.get("decimate_ratio"),
        "lods": scn.get("lods", False),
        "collision": scn.get("collision", False),
    }
    return {"id": f"p2_{scn['id']}", "inputs": inputs}


CONTRACT_SCENARIOS = [
    {
        "id": "fbx_roundtrip",
        "source": "sample_table.fbx",
        "name": "P2_Table",
        "export_formats": ["fbx"],
        "expect": {
            "ok": True, "source_format": "fbx", "exports": ["fbx"],
            "mesh_count": 5, "dim_x": (100.0, 135.0), "dim_y": (60.0, 80.0),
            "dim_z": (90.0, 110.0), "materials": {"P2_TableTop", "P2_Leg"},
        },
    },
    {
        "id": "glb_roundtrip",
        "source": "sample_monkey.glb",
        "export_formats": ["glb"],
        "expect": {"ok": True, "source_format": "glb", "exports": ["glb"],
                   "mesh_count": 1},
    },
    {
        "id": "obj_to_both",
        "source": "sample_cone.obj",
        "name": "P2_Cone",
        "export_formats": ["fbx", "glb"],
        "expect": {"ok": True, "source_format": "obj", "exports": ["fbx", "glb"],
                   "mesh_count": 1},
    },
    {
        "id": "decimate_optional",
        "source": "sample_cone.obj",
        "name": "P2_Cone_Lo",
        "export_formats": ["fbx"],
        "decimate_ratio": 0.25,
        "expect": {"ok": True, "decimate_requested": True,
                   "polygons_decreased": True, "mesh_count": 1},
    },
    {
        "id": "origin_bottom_and_name",
        "source": "sample_table.fbx",
        "name": "P2_Org_Table",
        "origin_center": "BOTTOM",
        "export_formats": ["glb"],
        "expect": {"ok": True, "organization_name": "P2_Org_Table",
                   "origin_center": "BOTTOM", "mesh_count": 5},
    },
    {
        "id": "error_missing_source",
        "source": "does_not_exist.fbx",
        "expect": {"ok": False},
    },
    {
        "id": "error_unsupported_format",
        "source": "bad_format.dae",
        "expect": {"ok": False, "code": "UNSUPPORTED_FORMAT"},
    },
]


def _ensure_samples() -> None:
    needed = ["sample_table.fbx", "sample_monkey.glb", "sample_cone.obj",
              "sample_cone.mtl"]
    if all(sample(n).exists() for n in needed):
        return
    print("generating samples ...", flush=True)
    blender = discover_blender()
    proc = subprocess.run([str(blender), "--background", "--factory-startup",
                           "--python", str(TOOLS / "make_p2_samples.py")],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("sample generation failed:\n" + proc.stdout[-800:] +
                           proc.stderr[-800:])
    for n in needed:
        if not sample(n).exists():
            raise RuntimeError(f"sample missing after generation: {n}")


def run_job_host(job: dict, blender=None, timeout: int = 240,
                 work_root: Path | None = None) -> dict:
    """Run one convert job through headless Blender; return structured result."""
    blender = blender or discover_blender()
    work_root = Path(work_root) if work_root is not None else OUT_ROOT
    out_dir = work_root / str(job["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    job_path = out_dir / "job.json"
    result_path = out_dir / "result.json"
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    proc = subprocess.run(
        [str(blender), "--background", "--factory-startup",
         "--python", str(TOOLS / "blender_ops.py"),
         "--", str(job_path), str(result_path)],
        capture_output=True, text=True, timeout=timeout)
    result = {"exit_code": proc.returncode}
    if result_path.exists():
        try:
            result.update(json.loads(result_path.read_text(encoding="utf-8")))
        except Exception as exc:
            result["parse_error"] = str(exc)
    result["log_tail"] = (proc.stdout or "")[-600:] + (proc.stderr or "")[-300:]
    return result


def check_scenario(scn: dict, result: dict) -> tuple[bool, list[str]]:
    exp = scn["expect"]
    fails: list[str] = []
    ok = bool(result.get("ok"))
    if ok != exp.get("ok", True):
        fails.append(f"ok expected {exp.get('ok')} got {ok}")
    if exp.get("code") and result.get("code") != exp.get("code"):
        fails.append(f"code expected {exp.get('code')} got {result.get('code')}")
    rep = result.get("report") or {}
    val = result.get("validation") or {}
    if exp.get("source_format") and rep.get("source_format") != exp["source_format"]:
        fails.append(f"source_format expected {exp['source_format']} "
                     f"got {rep.get('source_format')}")
    got_exports = sorted(val.get("exports") or [])
    if exp.get("exports") and got_exports != sorted(exp["exports"]):
        fails.append(f"exports expected {sorted(exp['exports'])} got {got_exports}")
    if exp.get("mesh_count") is not None:
        got = val.get("meshes")
        if got != exp["mesh_count"]:
            fails.append(f"mesh_count expected {exp['mesh_count']} got {got}")
    if exp.get("dim_x"):
        d = val.get("dimensions_cm") or [0, 0, 0]
        for label, idx, (lo, hi) in (("dim_x", 0, exp["dim_x"]),
                                     ("dim_y", 1, exp["dim_y"]),
                                     ("dim_z", 2, exp["dim_z"])):
            if not (lo <= d[idx] <= hi):
                fails.append(f"{label} {d[idx]} outside [{lo}, {hi}]")
    if exp.get("materials"):
        got = set(val.get("materials") or [])
        if not exp["materials"].issubset(got):
            fails.append(f"materials missing {exp['materials'] - got} in {got}")
    if exp.get("organization_name") is not None:
        org = rep.get("organization") or {}
        if org.get("requested_name") != exp["organization_name"]:
            fails.append(f"organization name expected {exp['organization_name']} "
                         f"got {org.get('requested_name')}")
    if exp.get("origin_center"):
        norm = rep.get("normalization") or {}
        if norm.get("origin_center") != exp["origin_center"]:
            fails.append(f"origin_center expected {exp['origin_center']} "
                         f"got {norm.get('origin_center')}")
    if exp.get("decimate_requested"):
        dec = rep.get("geometry", {}).get("decimate") or {}
        if not dec.get("requested"):
            fails.append("decimate not requested")
        elif exp.get("polygons_decreased"):
            before = sum(v["polygons"] for v in (dec.get("before") or {}).values())
            after = sum(v["polygons"] for v in (dec.get("after") or {}).values())
            if after >= before:
                fails.append(f"decimate polygons not decreased {before} -> {after}")
    if not exp.get("ok"):
        return (not fails, fails)  # error cases need no further field checks
    # outputs files physically present
    files = (result.get("outputs") or {}).get("exports") or []
    if files and any(not Path(f.get("path", "")).exists() for f in files):
        fails.append("an exported file is missing on disk")
    val_file = (result.get("outputs") or {}).get("validation_file")
    if val_file and not Path(val_file).exists():
        fails.append("per-asset validation json missing")
    return (not fails, fails)


def main() -> int:
    started = time.time()
    _ensure_samples()
    blender = discover_blender()
    if not (SAMPLES / "bad_format.dae").exists():
        (SAMPLES / "bad_format.dae").write_text("not a real dae", encoding="utf-8")

    rows = []
    for scn in CONTRACT_SCENARIOS:
        job = _job(scn)
        result = run_job_host(job, blender=blender)
        passed, fails = check_scenario(scn, result)
        rows.append({"id": scn["id"], "source": scn["source"],
                     "passed": passed, "fails": fails,
                     "ok": result.get("ok"), "code": result.get("code"),
                     "validation": result.get("validation"),
                     "elapsed_seconds": result.get("report", {}).get("elapsed_seconds")})
        print(f"[p2] {scn['id']:<28} {'PASS' if passed else 'FAIL'} "
              f"ok={result.get('ok')} code={result.get('code')} "
              f"fails={fails}", flush=True)

    ok_all = all(r["passed"] for r in rows)
    milestone = {
        "milestone": "P2 reusable headless Blender automation",
        "finished_at": time.time(),
        "elapsed_seconds": round(time.time() - started, 1),
        "ok": ok_all,
        "blender_ops": "assetlib/tools/blender_ops.py (reuses blender_agent "
                       "importers/geometry/exporters params read-only)",
        "scale_contract": "metric meters in Blender -> cm (100/unit) via "
                          "FBX apply_unit_scale + GLB meter conversion",
        "deferred": {"lods": "flag accepted, structural seam only",
                     "collision": "flag accepted, structural seam only"},
        "scenarios": rows,
        "samples": sorted(p.name for p in SAMPLES.iterdir() if p.suffix in
                          (".fbx", ".glb", ".obj", ".mtl")),
        "validation_files": [str((OUT_ROOT / s["id"] / "result.json")).replace("\\", "/")
                             for s in CONTRACT_SCENARIOS],
    }
    (Path(LAYOUT["reports"]) / "milestone_P2.json").write_text(
        json.dumps(milestone, indent=2, default=str), encoding="utf-8")
    print("=" * 70)
    print(f"P2 CONTRACT {'PASS' if ok_all else 'FAIL'} "
          f"({sum(r['passed'] for r in rows)}/{len(rows)} scenarios, "
          f"{milestone['elapsed_seconds']}s)")
    print(f"report: {Path(LAYOUT['reports']) / 'milestone_P2.json'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
