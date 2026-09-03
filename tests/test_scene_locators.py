"""Regression tests for core.scene_locators — the configurable production
locator layer that lets missions supply the documented measure()
subject_locator / ui_locator injection from a serializable scene profile.

Fully offline: Pillow synthetic frames only, no editor, no network.  The
frames mirror the documented use case (tests/img_helpers) where the generic
mid-tone heuristic is ambiguous and a scene profile pins WHERE the scene
keeps its subject.
"""
from __future__ import annotations

from core.scene_locators import (
    dark_panel_ui_locator,
    locators_from_profile,
    luma_band_subject_locator,
)
from core.visual_acceptance import measure
from tests.img_helpers import hero_locator, make_scene


def test_no_profile_keeps_generic_measurement():
    assert locators_from_profile(None) == {}
    assert locators_from_profile({}) == {}
    assert locators_from_profile({"ui": {"method": "nope"}}) == {}


def test_profile_resolves_documented_locator_kwargs():
    profile = {
        "subject": {"method": "luma_band",
                    "roi": [0.02, 0.05, 0.72, 0.97],
                    "min_luma": 140, "max_luma": 250},
        "ui": {"method": "dark_panel",
               "ui_roi": [0.55, 0.05, 0.99, 0.97],
               "dark_threshold": 60},
    }
    locs = locators_from_profile(profile)
    assert set(locs) == {"subject_locator", "ui_locator"}
    assert callable(locs["subject_locator"])
    assert callable(locs["ui_locator"])
    assert locs["subject_locator"].__name__ == "luma_band_subject_locator"
    assert locs["ui_locator"].__name__ == "dark_panel_ui_locator"


def test_profile_subject_locator_matches_documented_helper():
    """A config profile must produce exactly the measurement the documented
    scene locator produced directly (same algorithm, same band/ROI)."""
    path = _tmp_scene("profile.png")
    profile = {
        "subject": {"method": "luma_band",
                    "roi": [0.02, 0.05, 0.72, 0.97],
                    "min_luma": 140, "max_luma": 250},
    }
    locs = locators_from_profile(profile)
    from PIL import Image
    image = Image.open(path)
    direct = hero_locator(image)  # documented helper from the test corpus
    via_profile = locs["subject_locator"](image)
    assert via_profile == direct
    # and measuring with the resolved locator uses the documented mechanism
    m = measure(path, subject_locator=locs["subject_locator"])
    assert m.subject_bbox == direct
    assert m.ok and not m.issues


def test_profile_without_ui_keeps_default_ui_detection():
    path = _tmp_scene("panel_only.png")
    locs = locators_from_profile({"subject": {"method": "luma_band",
                                              "min_luma": 140}})
    m = measure(path, subject_locator=locs["subject_locator"])
    # dark glass panel on the right is still found by the generic UI scan
    assert m.ui_bbox is not None
    assert m.ui_bbox[0] >= m.width * 0.5


def test_ui_locator_pins_the_dark_panel_region():
    path = _tmp_scene("panel_ui.png")
    loc = dark_panel_ui_locator(dark_threshold=70)
    from PIL import Image
    bbox = loc(Image.open(path))
    assert bbox is not None
    w, h = Image.open(path).size
    # panel occupies the right band of the synthetic scene
    assert bbox[0] >= int(w * 0.55)
    assert bbox[2] <= w
    assert bbox[1] >= int(h * 0.05)


def _tmp_scene(name: str) -> str:
    """Render the corpus synthetic scene (bright hero + dark glass panel on
    the right) to a temp file and return its path."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="scene_locators_"))
    path = tmp / name
    make_scene().save(path, format="PNG")
    return str(path)
