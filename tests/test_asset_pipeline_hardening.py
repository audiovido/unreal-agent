"""UNREAL CODER — Phase I: asset pipeline hardening (offline part).

Exercises the intake path end-to-end with SAFE synthetic fixtures:
inspection, scale/orientation/UV detection, naming, folder destination,
repair routing, provenance (original untouched). Live import round-trips
run separately against the live editor.
"""
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.asset_intake import (
    analyze_asset,
    classify_kind,
    provenance_record,
    suggest_name,
)


GOOD_OBJ = """# synthetic crate
v -50.0 -50.0 0.0
v 50.0 -50.0 0.0
v 50.0 50.0 0.0
v -50.0 50.0 0.0
v -50.0 -50.0 100.0
v 50.0 -50.0 100.0
v 50.0 50.0 100.0
v -50.0 50.0 100.0
vt 0.0 0.0
vt 1.0 0.0
vt 1.0 1.0
vn 0.0 0.0 1.0
f 1/1/1 2/2/1 3/3/1
f 5/1/1 8/2/1 7/3/1
"""

HUGE_OBJ = "".join(
    f"v {x * 100000.0} 0 0\n" for x in (-1, 1)
) + "f 1 2 1\n"

NO_UV_OBJ = ("v 0 0 0\nv 10 0 0\nv 0 10 0\n"
             "f 1 2 3\n")


@pytest.fixture
def good_obj(tmp_path):
    p = tmp_path / "Sci-Fi Crate-01.obj"
    p.write_text(GOOD_OBJ, encoding="utf-8")
    return p


class TestInspection:
    def test_kind_classification(self, good_obj, tmp_path):
        assert classify_kind(good_obj) == "mesh"
        assert classify_kind(tmp_path / "t.png") == "texture"
        assert classify_kind(tmp_path / "s.wav") == "audio"
        assert classify_kind(tmp_path / "v.mp4") == "video"
        assert classify_kind(tmp_path / "x.zip") == "unknown"

    def test_obj_geometry_facts(self, good_obj):
        report = analyze_asset(str(good_obj))
        assert report.ok is True
        assert report.vertices == 8
        assert report.faces == 2
        assert report.has_uvs is True
        assert report.has_normals is True
        assert report.dimensions_cm == [100.0, 100.0, 100.0]
        assert report.largest_dimension_cm == 100.0
        assert report.scale_suspect is False

    def test_scale_suspect_routes_to_blender(self, tmp_path):
        p = tmp_path / "huge.obj"
        p.write_text(HUGE_OBJ, encoding="utf-8")
        report = analyze_asset(str(p))
        assert report.scale_suspect is True
        assert "scale_normalization" in report.repair_needed
        assert report.repair_route == "blender"

    def test_missing_uvs_route_to_blender(self, tmp_path):
        p = tmp_path / "flat.obj"
        p.write_text(NO_UV_OBJ, encoding="utf-8")
        report = analyze_asset(str(p))
        assert report.has_uvs is False
        assert "missing_uvs" in report.repair_needed
        assert report.repair_route == "blender"

    def test_clean_obj_routes_none(self, good_obj):
        report = analyze_asset(str(good_obj))
        assert report.repair_route == "none"

    def test_missing_file_reported(self, tmp_path):
        report = analyze_asset(str(tmp_path / "ghost.obj"))
        assert report.ok is False
        assert report.exists is False
        assert any("does not exist" in w for w in report.warnings)

    def test_empty_texture_flagged(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        report = analyze_asset(str(p))
        assert report.ok is False
        assert "empty_file" in report.repair_needed

    def test_unsupported_format(self, tmp_path):
        p = tmp_path / "doc.xyz"
        p.write_text("data")
        report = analyze_asset(str(p))
        assert report.ok is False
        assert any("Unsupported format" in w for w in report.warnings)


class TestNamingAndDestination:
    def test_bad_chars_sanitized(self, tmp_path):
        assert suggest_name(tmp_path / "Sci-Fi Crate-01.obj") == \
            "Sci_Fi_Crate_01"
        assert suggest_name(tmp_path / "1234 model.obj") == "A_1234_model"

    def test_folder_destination_by_kind(self, tmp_path):
        tex = tmp_path / "albedo.png"
        tex.write_bytes(b"\x89PNG fake")
        report = analyze_asset(str(tex))
        assert report.suggested_folder == "/Game/Imported/Textures"
        mesh = tmp_path / "crate.obj"
        mesh.write_text(GOOD_OBJ)
        report = analyze_asset(str(mesh))
        assert report.suggested_folder == "/Game/Imported"

    def test_explicit_folder_override(self, good_obj):
        report = analyze_asset(str(good_obj), folder="/Game/Props")
        assert report.suggested_folder == "/Game/Props"


class TestProvenance:
    def test_original_untouched(self, good_obj):
        before = good_obj.read_bytes()
        before_hash = hashlib.sha256(before).hexdigest()[:16]
        report = analyze_asset(str(good_obj))
        record = provenance_record(
            report, operations=["analyze"],
            output_path=str(good_obj) + ".fixed.fbx",
            import_destination="/Game/Imported")
        assert record["original_untouched"] is True
        assert good_obj.read_bytes() == before
        assert record["operations"] == ["analyze"]
        assert record["import_destination"] == "/Game/Imported"
        assert report.sha256_16 == before_hash

    def test_provenance_chain_complete(self, good_obj):
        report = analyze_asset(str(good_obj))
        record = provenance_record(
            report, operations=["normalize_scale", "export_fbx"],
            output_path="/tmp/out.fbx", import_destination="/Game/Imported")
        for key in ("original_path", "original_name", "operations",
                    "output_path", "import_destination", "original_untouched"):
            assert key in record


class TestBlenderAvailability:
    def test_blender_discoverable(self):
        """Blender is optional; when present the repair route is real."""
        from blender_agent.config import discover_blender
        exe = discover_blender()
        if exe is None:
            pytest.skip("Blender not installed (optional dependency)")
        assert Path(exe).is_file()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
