"""asset_intake.py — Layer 7: universal asset intake analysis.

Deterministic pre-import inspection of asset files. For meshes supported by
trivial parsing (OBJ) we parse real geometry; for formats requiring a DCC
(FBX/GLTF) we report the file header facts we can verify from disk and route
repair through the Blender Agent (headless) when the user asked for repair.

Pipeline responsibilities:
- classify file type/size, detect missing/corrupt files
- OBJ: parse vertices/faces/normals/UV presence, bounding box -> scale/orient
- decide folder placement + naming per /Game conventions
- provenance record (never mutate the original file)
- repair routing: Unreal-native (import settings) vs Blender vs none

This module never imports Unreal; the import itself goes through the
existing registered tools (import_asset_fbx / import_asset_gltf).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SUPPORTED_MESH = {".obj", ".fbx", ".gltf", ".glb"}
SUPPORTED_TEXTURE = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".exr", ".hdr",
                     ".tif", ".tiff"}
SUPPORTED_AUDIO = {".wav", ".mp3", ".ogg", ".flac"}
SUPPORTED_VIDEO = {".mp4", ".avi", ".mov", ".mkv"}

# Reasonable Unreal content bounds (Unreal units = cm).
# A single imported mesh larger than 1 km is almost always a unit error
# (world/landscape work uses tiled levels, not one OBJ).
MIN_DIMENSION_CM = 0.1
MAX_DIMENSION_CM = 100_000.0

NAMING_BAD_CHARS = re.compile(r"[^A-Za-z0-9_]")


class AssetIntakeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class IntakeReport:
    source_path: str
    exists: bool = False
    kind: str = "unknown"               # mesh | texture | audio | video | unknown
    format: str = ""
    size_bytes: int = 0
    sha256_16: str = ""
    # mesh facts (OBJ parsed; FBX/GLTF header facts)
    vertices: Optional[int] = None
    faces: Optional[int] = None
    has_uvs: Optional[bool] = None
    has_normals: Optional[bool] = None
    bbox_min: Optional[List[float]] = None
    bbox_max: Optional[List[float]] = None
    dimensions_cm: Optional[List[float]] = None
    largest_dimension_cm: Optional[float] = None
    orientation_axis: Optional[str] = None
    scale_suspect: bool = False
    # derived decisions
    suggested_name: str = ""
    suggested_folder: str = "/Game/Imported"
    repair_needed: List[str] = field(default_factory=list)
    repair_route: str = "none"          # none | unreal_settings | blender
    provenance: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    ok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "exists": self.exists,
            "kind": self.kind,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "sha256_16": self.sha256_16,
            "vertices": self.vertices,
            "faces": self.faces,
            "has_uvs": self.has_uvs,
            "has_normals": self.has_normals,
            "bbox_min": self.bbox_min,
            "bbox_max": self.bbox_max,
            "dimensions_cm": self.dimensions_cm,
            "largest_dimension_cm": self.largest_dimension_cm,
            "orientation_axis": self.orientation_axis,
            "scale_suspect": self.scale_suspect,
            "suggested_name": self.suggested_name,
            "suggested_folder": self.suggested_folder,
            "repair_needed": list(self.repair_needed),
            "repair_route": self.repair_route,
            "provenance": dict(self.provenance),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


def classify_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_MESH:
        return "mesh"
    if suffix in SUPPORTED_TEXTURE:
        return "texture"
    if suffix in SUPPORTED_AUDIO:
        return "audio"
    if suffix in SUPPORTED_VIDEO:
        return "video"
    return "unknown"


def _sha16(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def suggest_name(path: Path) -> str:
    stem = NAMING_BAD_CHARS.sub("_", path.stem).strip("_") or "ImportedAsset"
    if stem[0].isdigit():
        stem = "A_" + stem
    return stem


def analyze_obj(path: Path, report: IntakeReport) -> None:
    """Parse an ASCII OBJ for geometry facts (deterministic, bounded)."""
    minx = miny = minz = math.inf
    maxx = maxy = maxz = -math.inf
    vertices = 0
    faces = 0
    has_uvs = False
    has_normals = False
    with path.open("r", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        x, y, z = (float(parts[1]), float(parts[2]),
                                   float(parts[3]))
                    except ValueError:
                        continue
                    vertices += 1
                    minx, maxx = min(minx, x), max(maxx, x)
                    miny, maxy = min(miny, y), max(maxy, y)
                    minz, maxz = min(minz, z), max(maxz, z)
            elif line.startswith("f "):
                faces += 1
            elif line.startswith("vt "):
                has_uvs = True
            elif line.startswith("vn "):
                has_normals = True
    if vertices == 0:
        report.repair_needed.append("no_geometry")
        report.repair_route = "blender"
        report.warnings.append("OBJ contains no parseable vertices.")
        return
    report.vertices = vertices
    report.faces = faces
    report.has_uvs = has_uvs
    report.has_normals = has_normals
    report.bbox_min = [round(minx, 4), round(miny, 4), round(minz, 4)]
    report.bbox_max = [round(maxx, 4), round(maxy, 4), round(maxz, 4)]
    dims = [maxx - minx, maxy - miny, maxz - minz]
    report.dimensions_cm = [round(d, 4) for d in dims]
    report.largest_dimension_cm = round(max(dims), 4)
    axis = "z"
    if dims[0] >= dims[1] and dims[0] >= dims[2]:
        axis = "x"
    elif dims[1] >= dims[0] and dims[1] >= dims[2]:
        axis = "y"
    report.orientation_axis = axis
    # OBJ units are unitless; if largest axis is wildly outside plausible cm
    # content, flag scale suspicion (repair via Blender normalize).
    largest = max(dims)
    if largest > MAX_DIMENSION_CM or largest < MIN_DIMENSION_CM:
        report.scale_suspect = True
        report.repair_needed.append("scale_normalization")
        report.repair_route = "blender"
    if not has_uvs:
        report.repair_needed.append("missing_uvs")
        if report.repair_route != "blender":
            report.repair_route = "blender"


def analyze_header_mesh(path: Path, report: IntakeReport) -> None:
    """Header-level facts for DCC formats (FBX/GLTF/GLB)."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".glb":
        # GLB container: magic 'glTF', version, length.
        if len(data) >= 12 and data[:4] == b"glTF":
            version = struct.unpack("<I", data[4:8])[0]
            report.warnings.append(f"GLB container version {version}.")
            report.repair_needed.append("verify_import")
        else:
            raise AssetIntakeError("ASSET_CORRUPT", "GLB magic missing")
    elif suffix == ".fbx":
        # Binary FBX starts with 'Kaydara FBX Binary'; else assume ASCII FBX.
        if data[:18] == b"Kaydara FBX Binary":
            report.warnings.append("Binary FBX detected.")
        else:
            report.warnings.append("ASCII FBX detected.")
        report.repair_needed.append("verify_import")
    elif suffix == ".gltf":
        stripped = data.lstrip()
        if not stripped.startswith(b"{"):
            raise AssetIntakeError("ASSET_CORRUPT", "glTF is not JSON")
        try:
            doc = json.loads(stripped.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise AssetIntakeError("ASSET_CORRUPT", f"glTF JSON invalid: {exc}")
        meshes = doc.get("meshes") or []
        report.vertices = sum(
            len(m.get("primitives") or []) for m in meshes) or None
        report.warnings.append(
            f"glTF document with {len(meshes)} mesh(es); geometry stats "
            "verified after import.")


def analyze_asset(source: str, folder: Optional[str] = None) -> IntakeReport:
    """Inspect one asset file before import. Never mutates the source."""
    path = Path(source)
    report = IntakeReport(source_path=str(path))
    report.provenance = {
        "original_path": str(path.resolve()),
        "original_name": path.name,
        "analyzed_at_epoch": int(__import__("time").time()),
        "operations": [],
    }
    if not path.exists() or not path.is_file():
        report.warnings.append("File does not exist.")
        return report
    report.exists = True
    report.kind = classify_kind(path)
    report.format = path.suffix.lower().lstrip(".")
    report.size_bytes = path.stat().st_size
    report.sha256_16 = _sha16(path)
    report.suggested_name = suggest_name(path)
    if folder:
        report.suggested_folder = folder
    elif report.kind == "texture":
        report.suggested_folder = "/Game/Imported/Textures"
    elif report.kind == "audio":
        report.suggested_folder = "/Game/Imported/Audio"
    elif report.kind == "video":
        report.suggested_folder = "/Game/Imported/Media"

    if report.kind == "mesh":
        try:
            if report.format == "obj":
                analyze_obj(path, report)
            else:
                analyze_header_mesh(path, report)
        except AssetIntakeError as exc:
            report.warnings.append(f"{exc.code}: {exc}")
            report.repair_needed.append("corrupt_header")
            report.repair_route = "blender"
            return report
        if report.repair_route == "none" and report.repair_needed:
            report.repair_route = "unreal_settings"
    elif report.kind in {"texture", "audio", "video"}:
        if report.size_bytes == 0:
            report.warnings.append("Empty file.")
            report.repair_needed.append("empty_file")
            report.ok = False
            return report
        report.ok = True
        return report
    else:
        report.warnings.append(
            f"Unsupported format '{report.format}' for automatic intake.")
        return report

    report.ok = report.exists and report.kind != "unknown"
    if report.ok and not report.repair_needed:
        report.repair_route = "none"
    return report


def provenance_record(
    report: IntakeReport,
    operations: List[str],
    output_path: Optional[str] = None,
    import_destination: Optional[str] = None,
) -> Dict[str, Any]:
    """Immutable provenance chain: original -> operations -> output -> dest."""
    record = dict(report.provenance)
    record["operations"] = list(operations)
    record["output_path"] = output_path
    record["import_destination"] = import_destination
    record["original_untouched"] = True
    return record
