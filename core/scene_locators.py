"""scene_locators.py — configurable, production-safe scene locators.

The deterministic measurement in core.visual_acceptance is generic: its
subject scan assumes a centered mid-tone subject.  Scenes whose visual
contract does not match that assumption (for example a wide composition whose
darker top band merges into the generic subject scan and produces a false
HEAD_CROPPED) use the documented injection mechanism — ``subject_locator`` /
``ui_locator`` callables passed to ``measure()`` (and carried by
``AutonomousVisualLoop``) — to supply scene-specific blob detection.

This module provides *parameterized factories* for those locators so a
mission can declare them from a small serializable profile (mission
configuration) instead of importing test helpers or hard-coding one
screenshot's pixel box.

Profiles describe only where a scene keeps its content — a frame-relative ROI
and a brightness band — never pixel coordinates of one capture.  They feed
the same find_subject_bbox / find_ui_bbox algorithms the deterministic
measurement already uses, so no scorer threshold or scoring logic is touched:
a locator only replaces *which region is measured*, exactly as the documented
mechanism intends.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.visual_acceptance import find_subject_bbox, find_ui_bbox

# image -> [x0, y0, x1, y1] pixel bbox or None
Locator = Callable[[Any], Optional[List[int]]]

# Supported profile "method" values (both default to the generic algorithm
# with the profile's band/ROI restrictions).
SUBJECT_METHODS = ("luma_band", "bright_band")
UI_METHODS = ("dark_panel", "dark_band")


def luma_band_subject_locator(
    roi: Optional[List[float]] = None,
    min_luma: int = 45,
    max_luma: int = 250,
) -> Locator:
    """Subject = the dominant structured mass inside a frame-relative ROI
    restricted to a luma band.

    ``roi`` is [x0, y0, x1, y1] in frame fractions.  ``min_luma``/``max_luma``
    select the brightness band whose content is the scene's subject (e.g. the
    bright composition mass below a darker sky band).  Uses the same
    component-based segmentation as the generic detector, so a band-restricted
    locator and the plain scan agree whenever the generic scan is unambiguous.
    """
    def locate(image: Any) -> Optional[List[int]]:
        return find_subject_bbox(
            image,
            roi=list(roi) if roi else None,
            min_luma=int(min_luma),
            max_luma=int(max_luma),
        )

    locate.__name__ = "luma_band_subject_locator"
    return locate


def dark_panel_ui_locator(
    ui_roi: Optional[List[float]] = None,
    dark_threshold: int = 70,
) -> Locator:
    """UI panel = the consistently dark region inside a frame-relative ROI
    (fractions; default the right-hand band) below the scene baseline.

    Same scan as the generic UI detector; supplying it explicitly pins the UI
    contract of a scene (e.g. a dark glass panel on the right) instead of
    letting an unrelated dark object elsewhere claim the credit.
    """
    def locate(image: Any) -> Optional[List[int]]:
        return find_ui_bbox(
            image,
            ui_roi=list(ui_roi) if ui_roi else None,
            dark_threshold=int(dark_threshold),
        )

    locate.__name__ = "dark_panel_ui_locator"
    return locate


def locators_from_profile(
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Locator]:
    """Map a serializable scene-locator profile to measure()-compatible
    locator kwargs (``subject_locator`` / ``ui_locator``).

    Profile shape (all entries optional)::

        {"subject": {"method": "luma_band",        # or omitted
                     "roi": [0.02, 0.05, 0.72, 0.97],
                     "min_luma": 140, "max_luma": 250},
         "ui":      {"method": "dark_panel",        # or omitted
                     "ui_roi": [0.55, 0.05, 0.99, 0.97],
                     "dark_threshold": 70}}

    Returns {} when ``profile`` is None or empty, which keeps the caller on
    plain generic measurement.  Unknown methods are ignored (fail safe):
    a mission never silently changes semantics because of a typo.
    """
    out: Dict[str, Locator] = {}
    if not profile:
        return out
    subject = profile.get("subject") or {}
    if subject:  # a subject entry present (even method-less) pins it
        method = subject.get("method")
        if method in (None, *SUBJECT_METHODS):
            out["subject_locator"] = luma_band_subject_locator(
                roi=subject.get("roi"),
                min_luma=subject.get("min_luma", 45),
                max_luma=subject.get("max_luma", 250),
            )
    ui = profile.get("ui") or {}
    if ui:  # a ui entry present (even method-less) pins it
        method = ui.get("method")
        if method in (None, *UI_METHODS):
            out["ui_locator"] = dark_panel_ui_locator(
                ui_roi=ui.get("ui_roi"),
                dark_threshold=ui.get("dark_threshold", 70),
            )
    return out
