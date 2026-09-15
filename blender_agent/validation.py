"""Structured validation for Blender jobs and exported assets.

Pure logic (testable outside Blender): manifest completeness, export file
checks, dimension expectations, material presence, unsupported formats.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SUPPORTED_EXPORT_FORMATS = {"fbx", "glb", "gltf"}
SUPPORTED_IMPORT_FORMATS = {"fbx", "glb", "gltf", "obj"}


def validate_export_file(path: Any, *, min_bytes: int = 0) -> dict[str, Any]:
    """Check an exported file exists, is non-empty, and has the right suffix."""
    checks: dict[str, Any] = {"ok": False}
    if not path:
        return {"ok": False, "error": "no export path provided", "checks": checks}
    p = Path(str(path))
    checks["exists"] = p.exists()
    checks["is_file"] = p.is_file() if p.exists() else False
    checks["size_bytes"] = p.stat().st_size if p.exists() and p.is_file() else 0
    checks["size_ok"] = checks["size_bytes"] > min_bytes
    checks["suffix"] = p.suffix.lower() if p.exists() else None
    checks["suffix_supported"] = bool(
        checks["suffix"] and checks["suffix"].lstrip(".") in SUPPORTED_EXPORT_FORMATS
    )
    checks["ok"] = all((checks["exists"], checks["is_file"], checks["size_ok"], checks["suffix_supported"]))
    return {
        "ok": checks["ok"],
        "path": str(p).replace("\\", "/"),
        "checks": checks,
        "error": None if checks["ok"] else "export file validation failed",
    }


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate a job's metadata manifest covers the Phase 5 contract."""
    if not isinstance(manifest, dict):
        return {"ok": False, "error": "manifest missing", "checks": {"manifest": False}}
    required_keys = (
        "job_id", "export_format", "output_path", "dimensions_cm",
        "materials", "textures", "validation",
    )
    missing = [k for k in required_keys if k not in manifest]
    checks: dict[str, Any] = {
        "required_keys_present": not missing,
        "missing_keys": missing,
        "output_path_present": bool(manifest.get("output_path")),
        "export_format_supported": bool(
            manifest.get("export_format") in SUPPORTED_EXPORT_FORMATS
        ),
        "validation_ok": bool(
            isinstance(manifest.get("validation"), dict)
            and manifest["validation"].get("ok") is True
        ),
    }
    # NOTE: missing_keys is a list (falsy when empty), so it must not be fed
    # into all() — only the boolean checks participate.
    bool_checks = (v for k, v in checks.items() if isinstance(v, bool))
    checks["ok"] = all(bool_checks)
    return {
        "ok": checks["ok"],
        "checks": checks,
        "error": None if checks["ok"] else f"manifest validation failed: {missing}",
    }


def validate_dimensions(dimensions: Any, expected_cm: Any, tolerance: float = 0.05) -> dict[str, Any]:
    """Compare measured dimensions (cm) against expected dimensions (cm)."""
    measured = [float(v) for v in (dimensions or [])]
    expected = [float(v) for v in (expected_cm or [])]
    if len(measured) != 3 or len(expected) != 3:
        return {"ok": False, "error": "expected 3D dimensions", "measured": measured, "expected": expected}
    ratios = []
    for m, e in zip(measured, expected):
        if not e:
            ratios.append(1.0)
        else:
            ratios.append(m / e)
    ok = all(abs(r - 1.0) <= tolerance for r in ratios)
    return {
        "ok": ok,
        "measured_cm": [round(v, 3) for v in measured],
        "expected_cm": [round(v, 3) for v in expected],
        "ratios": [round(r, 3) for r in ratios],
        "tolerance": tolerance,
        "error": None if ok else f"dimensions off by >{tolerance * 100:.0f}%",
    }


def validate_materials(materials: Any, expected_names: Any = None) -> dict[str, Any]:
    names = [str(m.get("name") or m) if isinstance(m, dict) else str(m) for m in (materials or [])]
    checks = {
        "material_count": len(names),
        "materials": names,
    }
    if expected_names:
        missing = [e for e in expected_names if e not in names]
        checks["all_expected_present"] = not missing
        checks["missing"] = missing
    checks["ok"] = bool(names) and checks.get("all_expected_present", True)
    return {"ok": checks["ok"], "checks": checks, "error": None if checks["ok"] else "material validation failed"}


def validate_source_format(source: Any) -> dict[str, Any]:
    """Reject unsupported source files before launching Blender."""
    p = Path(str(source))
    ext = p.suffix.lower()
    if not p.exists():
        return {"ok": False, "code": "SOURCE_NOT_FOUND", "error": f"source file not found: {p}", "ext": ext}
    if ext.lstrip(".") not in SUPPORTED_IMPORT_FORMATS:
        return {
            "ok": False,
            "code": "UNSUPPORTED_FORMAT",
            "error": f"unsupported source format: {ext or 'none'} (supported: {sorted(SUPPORTED_IMPORT_FORMATS)})",
            "ext": ext,
        }
    return {"ok": True, "path": str(p).replace("\\", "/"), "ext": ext}


def validate_missing_blender(discovery: Any) -> dict[str, Any]:
    """Structured failure for a missing Blender executable."""
    return {
        "ok": False,
        "code": "BLENDER_NOT_FOUND",
        "error": "Blender executable not found; install Blender or set UNREAL_AGENT_BLENDER_EXE",
        "discovery": discovery,
    }


def evaluate_job_result(job: dict[str, Any]) -> dict[str, Any]:
    """Combine a job record's outputs/validation/manifest into a verdict."""
    if job.get("status") != "COMPLETE":
        return {
            "pass": False,
            "status": job.get("status"),
            "error": job.get("error"),
        }
    validation = job.get("validation") or {}
    manifest_ok = bool(job.get("manifest"))
    export_ok = bool(validation.get("ok"))
    return {
        "pass": bool(export_ok and manifest_ok),
        "status": job.get("status"),
        "validation": validation,
        "manifest_present": manifest_ok,
        "error": None if export_ok and manifest_ok else "validation did not fully pass",
    }
