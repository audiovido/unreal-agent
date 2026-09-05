"""Configurable, production-safe scene locators.

Locators are mission configuration, not acceptance-rule overrides.  They select
which measurable image region represents a scene subject or UI panel; the
shared visual acceptance scorer still owns all thresholds and scoring.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.visual_acceptance import find_subject_bbox, find_ui_bbox

# image -> [x0, y0, x1, y1] pixel bbox or None
Locator = Callable[[Any], Optional[List[int]]]

VEHICLE_SHOWCASE_PROFILE = {
    "subject": {
        "method": "vehicle_showcase",
        "roi": [0.28, 0.10, 0.76, 0.95],
        "min_luma": 0,
        "max_luma": 120,
    },
    "strategy": {
        "order": [
            "subject_bbox_validity", "camera_framing", "empty_space",
            "exposure_clipping", "background_separation",
        ],
        "max_passes": 3,
        "allow_geometry_edits": False,
        "allow_scale_edits": False,
    },
}


def is_vehicle_showcase_task(text: Any) -> bool:
    """Return whether text explicitly requests a vehicle showcase scene."""
    lowered = str(text or "").lower()
    vehicle = ("vehicle", "truck", "car", "suv", "automobile", "van")
    context = ("showcase", "show case", "display", "exhibit", "garage", "scene")
    return bool(any(word in lowered for word in vehicle)
                and any(word in lowered for word in context))


SUBJECT_METHODS = ("luma_band", "bright_band", "vehicle_showcase")
UI_METHODS = ("dark_panel", "dark_band")


def luma_band_subject_locator(
    roi: Optional[List[float]] = None,
    min_luma: int = 45,
    max_luma: int = 250,
) -> Locator:
    """Locate the dominant subject inside a frame-relative luma-band ROI."""
    def locate(image: Any) -> Optional[List[int]]:
        return find_subject_bbox(
            image,
            roi=list(roi) if roi else None,
            min_luma=int(min_luma),
            max_luma=int(max_luma),
        )

    locate.__name__ = "luma_band_subject_locator"
    return locate


def vehicle_showcase_subject_locator(
    roi: Optional[List[float]] = None,
    min_luma: int = 0,
    max_luma: int = 120,
) -> Locator:
    """Locate a dark assembled vehicle without measuring the map/floor mass.

    The ROI is expressed as frame fractions so the detector generalizes across
    capture sizes.  Dark cells are grouped into connected components and
    nearby body/wheel groups are merged.  A candidate must have vehicle-like
    dimensions and central support; no candidate returns ``None`` so the
    acceptance loop fails closed instead of inventing a subject bbox.
    """
    def locate(image: Any) -> Optional[List[int]]:
        from PIL import Image
        import numpy as np

        if not isinstance(image, Image.Image):
            return None
        w, h = image.size
        fr = list(roi or [0.28, 0.10, 0.76, 0.95])
        if len(fr) != 4:
            return None
        x0, y0 = int(w * fr[0]), int(h * fr[1])
        x1, y1 = int(w * fr[2]), int(h * fr[3])
        if x1 <= x0 or y1 <= y0:
            return None

        gray = np.asarray(image.convert("L"), dtype=np.uint8)
        crop = gray[y0:y1, x0:x1]
        step = 4
        gh, gw = crop.shape[0] // step, crop.shape[1] // step
        if gh < 4 or gw < 4:
            return None
        crop = crop[:gh * step, :gw * step]
        cells = crop.reshape(gh, step, gw, step)
        mean = cells.mean(axis=(1, 3))
        local_range = (cells.max(axis=(1, 3)).astype(int)
                       - cells.min(axis=(1, 3)).astype(int))
        # Smooth dark pixels are valid black paint; brighter low-contrast
        # cells are retained only when they have silhouette structure.
        dark = ((mean >= int(min_luma)) & (mean <= int(max_luma))
                & ((mean < 62) | (local_range >= 8)))
        # A showcase floor/map can be a large dark horizontal slab. Suppress
        # rows that occupy most of the lower crop before connected-component
        # assembly; otherwise the slab merges with the wheels and becomes the
        # false "vehicle" bbox. This remains frame-relative, not screenshot
        # coordinates.
        lower_start = int(gh * 0.70)
        for row in range(lower_start, gh):
            if float(dark[row].mean()) >= 0.55:
                dark[row, :] = False

        # One-cell morphological close joins body and wheels, but does not
        # expand the region enough to turn the entire environment into a blob.
        connected = dark.copy()
        connected[1:, :] |= dark[:-1, :]
        connected[:-1, :] |= dark[1:, :]
        connected[:, 1:] |= dark[:, :-1]
        connected[:, :-1] |= dark[:, 1:]

        seen = np.zeros_like(connected, dtype=bool)
        components: List[Dict[str, int]] = []
        for gy, gx in zip(*np.where(connected)):
            if seen[gy, gx]:
                continue
            stack = [(int(gy), int(gx))]
            seen[gy, gx] = True
            points = []
            while stack:
                cy, cx = stack.pop()
                points.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx),
                               (cy, cx - 1), (cy, cx + 1)):
                    if (0 <= ny < gh and 0 <= nx < gw
                            and connected[ny, nx] and not seen[ny, nx]):
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(points) >= 12:
                ys = [p[0] for p in points]
                xs = [p[1] for p in points]
                components.append({
                    "area": len(points), "x0": min(xs), "y0": min(ys),
                    "x1": max(xs) + 1, "y1": max(ys) + 1,
                })
        if not components:
            return None

        # Merge nearby silhouette pieces (body, wheels, mirrors) into an
        # assembled-vehicle group before scoring candidates.
        groups: List[Dict[str, Any]] = []
        for comp in sorted(components, key=lambda c: c["area"], reverse=True):
            group = next((g for g in groups
                          if comp["x0"] <= g["x1"] + 18
                          and comp["x1"] >= g["x0"] - 18
                          and comp["y0"] <= g["y1"] + 28
                          and comp["y1"] >= g["y0"] - 28), None)
            if group is None:
                groups.append({**comp})
            else:
                group["x0"] = min(group["x0"], comp["x0"])
                group["y0"] = min(group["y0"], comp["y0"])
                group["x1"] = max(group["x1"], comp["x1"])
                group["y1"] = max(group["y1"], comp["y1"])
                group["area"] += comp["area"]

        candidates = []
        for group in groups:
            bx0, by0 = x0 + group["x0"] * step, y0 + group["y0"] * step
            bx1, by1 = x0 + group["x1"] * step, y0 + group["y1"] * step
            bw, bh = bx1 - bx0, by1 - by0
            coverage = (bw * bh) / float(w * h)
            if bw < w * 0.04 or bh < h * 0.06 or coverage > 0.42:
                continue
            cx = ((bx0 + bx1) / 2.0) / w
            cy = ((by0 + by1) / 2.0) / h
            # Prefer a centered, lower-supported silhouette over a small dark
            # prop or upper background patch.
            centrality = max(0.05, 1.0 - abs(cx - 0.5) - 0.35 * abs(cy - 0.58))
            lower_support = 1.0 if by1 >= h * 0.55 else 0.45
            aspect = min(1.0, bw / max(float(bh) * 2.0, 1.0))
            score_value = group["area"] * centrality * lower_support * (0.7 + 0.3 * aspect)
            candidates.append((score_value, [
                max(x0, bx0 - 8), max(y0, by0 - 8),
                min(x1, bx1 + 8), min(y1, by1 + 8),
            ]))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    locate.__name__ = "vehicle_showcase_subject_locator"
    return locate


def dark_panel_ui_locator(
    ui_roi: Optional[List[float]] = None,
    dark_threshold: int = 70,
) -> Locator:
    """Locate a dark UI panel inside a frame-relative ROI."""
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
    """Map a serializable scene profile to measure() locator kwargs."""
    out: Dict[str, Locator] = {}
    if not profile:
        return out
    subject = profile.get("subject") or {}
    if subject:
        method = subject.get("method")
        if method == "vehicle_showcase":
            out["subject_locator"] = vehicle_showcase_subject_locator(
                roi=subject.get("roi"),
                min_luma=subject.get("min_luma", 0),
                max_luma=subject.get("max_luma", 120),
            )
        elif method in (None, "luma_band", "bright_band"):
            out["subject_locator"] = luma_band_subject_locator(
                roi=subject.get("roi"),
                min_luma=subject.get("min_luma", 45),
                max_luma=subject.get("max_luma", 250),
            )
    ui = profile.get("ui") or {}
    if ui and ui.get("method") in (None, *UI_METHODS):
        out["ui_locator"] = dark_panel_ui_locator(
            ui_roi=ui.get("ui_roi"),
            dark_threshold=ui.get("dark_threshold", 70),
        )
    return out
