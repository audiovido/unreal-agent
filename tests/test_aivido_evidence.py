"""AIVIDO evidence packager — hermetic regression tests.

Pins the honesty contract of scripts/aivido_evidence.py:
  * stale frame            -> FAIL
  * missing fresh frame    -> FAIL
  * empty SceneDiff        -> FAIL
  * executor success alone -> never PASS
  * vision gate unavailable-> deterministic metrics still decide; no hang, no lie
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.aivido_evidence as ev


def _make_frame(path: Path, color: int = 90) -> None:
    from PIL import Image
    img = Image.new("RGB", (160, 120), (color, color, color))
    img.save(path)


def _write_metadata(path: Path, frame: str, **overrides):
    sha = hashlib.sha256((path / frame).read_bytes()).hexdigest()
    meta = {
        "frame": frame,
        "path": str(path / frame),
        "sha256": sha,
        "size_bytes": (path / frame).stat().st_size,
        "captured_at_epoch": time.time(),
        "map": "/Game/AIVIDO_Showcase",
        "source": "bridge",
    }
    meta.update(overrides)
    (path / "capture_metadata.json").write_text(json.dumps(meta))
    return meta


def _prepare_dir(tmp_path: Path, *, frame: str = "FINAL.png", color: int = 90,
                 with_metadata: bool = True, **meta_overrides) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _make_frame(tmp_path / frame, color)
    if with_metadata:
        _write_metadata(tmp_path, frame, **meta_overrides)
    return tmp_path


# ---------------------------------------------------------------------------
# Freshness / stale-frame detection
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_fresh_bridge_frame_passes(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is True and r["stale"] is False

    def test_missing_frame_is_not_fresh(self, tmp_path):
        ev_dir = tmp_path
        ev_dir.mkdir(exist_ok=True)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is False and r["reason"] == "missing"

    def test_sha_mismatch_is_stale(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path)
        # mutate the frame after metadata was written -> bytes no longer match
        _make_frame(ev_dir / "FINAL.png", color=200)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is False and r["stale"] is True
        assert r["reason"] == "sha_mismatch"

    def test_old_capture_is_stale(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path, captured_at_epoch=time.time() - 10_000)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is False and r["reason"] == "too_old"

    def test_no_metadata_is_stale(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path, with_metadata=False)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is False and r["stale"] is True
        assert r["reason"] == "no_capture_metadata"

    def test_wrong_map_is_stale(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path, map="/Game/SomeOtherMap")
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"),
                                     max_age=900, expected_map="/Game/AIVIDO_Showcase")
        assert r["fresh"] is False and r["reason"] == "map_mismatch"

    def test_future_timestamp_is_stale(self, tmp_path):
        ev_dir = _prepare_dir(tmp_path, captured_at_epoch=time.time() + 10_000)
        r = ev.check_frame_freshness(str(ev_dir), str(ev_dir / "FINAL.png"), max_age=900)
        assert r["fresh"] is False and r["reason"] == "future_timestamp"


# ---------------------------------------------------------------------------
# SceneDiff honesty
# ---------------------------------------------------------------------------

def _scene(actors, materials=None):
    return {"map": "/Game/AIVIDO_Showcase", "actors": actors,
            "classes": {a: "StaticMeshActor" for a in actors},
            "transforms": {}, "mesh_refs": [], "material_refs": materials or [],
            "lights": [], "cameras": []}


class TestScenediff:
    def test_empty_scenediff_rejected(self, tmp_path):
        payload = {"before": _scene(["A"]), "after": _scene(["A"])}
        (tmp_path / "scenediff.json").write_text(json.dumps(payload))
        r = ev.check_scenediff(str(tmp_path / "scenediff.json"))
        assert r["ok"] is False and r["reason"] == "empty_scenediff"

    def test_meaningful_scenediff_accepted(self, tmp_path):
        payload = {"before": _scene(["A"]), "after": _scene(["A", "B"])}
        (tmp_path / "scenediff.json").write_text(json.dumps(payload))
        r = ev.check_scenediff(str(tmp_path / "scenediff.json"))
        assert r["ok"] is True

    def test_material_only_change_is_meaningful(self, tmp_path):
        payload = {"before": _scene(["A"], ["M_Old"]), "after": _scene(["A"], ["M_New"])}
        (tmp_path / "scenediff.json").write_text(json.dumps(payload))
        r = ev.check_scenediff(str(tmp_path / "scenediff.json"))
        assert r["ok"] is True

    def test_missing_scenediff_file_fails(self, tmp_path):
        r = ev.check_scenediff(str(tmp_path / "nope.json"))
        assert r["ok"] is False and r["reason"] == "scenediff_unreadable"


# ---------------------------------------------------------------------------
# Provenance writer contract
# ---------------------------------------------------------------------------

class TestProvenanceWriter:
    def test_write_capture_metadata_pins_bytes(self, tmp_path):
        from tools.visual.evidence_capture import write_capture_metadata
        frame = tmp_path / "FINAL.png"
        _make_frame(frame)
        ts = time.time() - 3
        meta = write_capture_metadata(str(frame), map_name="/Game/AIVIDO_Showcase",
                                      source="bridge", captured_at_epoch=ts)
        assert meta["sha256"] == hashlib.sha256(frame.read_bytes()).hexdigest()
        assert meta["map"] == "/Game/AIVIDO_Showcase"
        on_disk = json.loads((tmp_path / "capture_metadata.json").read_text())
        assert on_disk["sha256"] == meta["sha256"]
        r = ev.check_frame_freshness(str(tmp_path), str(frame), max_age=900)
        assert r["fresh"] is True

    def test_metadata_rejects_missing_frame(self, tmp_path):
        from tools.visual.evidence_capture import write_capture_metadata
        with pytest.raises(FileNotFoundError):
            write_capture_metadata(str(tmp_path / "ghost.png"))


# ---------------------------------------------------------------------------
# End-to-end packaging verdicts (vision gate mocked at the HTTP boundary)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class TestPackagerVerdicts:
    def _run(self, tmp_path, monkeypatch, *, executor_ok=False, vision_ok=False,
             frame_color=90, with_scenediff=True, meaningful=True, with_metadata=True,
             meta_overrides=None):
        ev_dir = _prepare_dir(tmp_path, color=frame_color, with_metadata=with_metadata,
                              **(meta_overrides or {}))
        if with_scenediff:
            after = _scene(["A", "B"]) if meaningful else _scene(["A"])
            payload = {"before": _scene(["A"]), "after": after}
            (ev_dir / "scenediff.json").write_text(json.dumps(payload))
        monkeypatch.setattr(ev, "vision_gate_available",
                            lambda: {"available": vision_ok, "model": ev.VISION_MODEL,
                                     "latency_s": 1.0})
        argv = ["x", str(ev_dir), "--executor-ok"] if executor_ok else ["x", str(ev_dir)]
        monkeypatch.setattr(sys, "argv", argv)
        return ev_dir, ev.main()

    def test_unprovable_frame_fails_even_with_executor_ok(self, tmp_path, monkeypatch):
        # frame bytes exist but no capture metadata -> not provably fresh
        ev_dir, rc = self._run(tmp_path, monkeypatch, executor_ok=True,
                               with_metadata=False)
        assert rc == 1
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "FAIL"
        assert verdict["freshness"]["fresh"] is False
        assert verdict["freshness"]["reason"] == "no_capture_metadata"
        assert any("STALE FRAME" in i for i in verdict["issues"])
        assert verdict["executor_ok"] is True  # recorded, but not sufficient

    def test_stale_frame_fails_even_with_executor_ok(self, tmp_path, monkeypatch):
        ev_dir, rc = self._run(tmp_path, monkeypatch, executor_ok=True,
                               meta_overrides={"captured_at_epoch": time.time() - 50_000})
        assert rc == 1
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "FAIL"
        assert any("STALE FRAME" in i for i in verdict["issues"])

    def test_empty_scenediff_fails(self, tmp_path, monkeypatch):
        ev_dir, rc = self._run(tmp_path, monkeypatch, meaningful=False)
        assert rc == 1
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "FAIL"
        assert any("EMPTY SCENEDIFF" in i for i in verdict["issues"])

    def test_executor_success_alone_never_passes(self, tmp_path, monkeypatch):
        # no scenediff at all, executor claims success -> FAIL
        ev_dir, rc = self._run(tmp_path, monkeypatch, executor_ok=True,
                               with_scenediff=False)
        assert rc == 1
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "FAIL"
        assert any("MISSING SCENEDIFF" in i for i in verdict["issues"])

    def test_full_evidence_passes_pixels_only_when_vision_down(self, tmp_path, monkeypatch):
        ev_dir, rc = self._run(tmp_path, monkeypatch, executor_ok=True, vision_ok=False)
        assert rc == 0
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "PASS_PIXELS_ONLY"
        assert verdict["vision_gate"]["available"] is False
        assert "VISION GATE UNAVAILABLE" in verdict.get("vision_gate_note", "")

    def test_full_evidence_passes_with_vision(self, tmp_path, monkeypatch):
        ev_dir, rc = self._run(tmp_path, monkeypatch, executor_ok=True, vision_ok=True)
        assert rc == 0
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert verdict["verdict"] == "PASS"

    def test_degenerate_black_frame_fails_even_when_fresh(self, tmp_path, monkeypatch):
        ev_dir, rc = self._run(tmp_path, monkeypatch, frame_color=3, vision_ok=True)
        assert rc == 1
        verdict = json.loads((ev_dir / "verdict.json").read_text())
        assert any("degenerate" in i for i in verdict["issues"])
