"""visual_acceptance.py — objective screenshot measurement and acceptance.

The Visual Acceptance Engine evaluates a captured screenshot against a
VisualTarget using deterministic, measurable checks FIRST (subject bbox and
screen coverage, head clipping, white/black clipping, contrast, entropy,
black bands, stale-hash, resolution, UI presence) and only then combines a
vision-model review into the final score. It never trusts a vision model's
opinion alone.

This module is generic: it has no Unreal, AvaLive, or camera knowledge. It
operates on an image path plus a VisualTarget dict.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PIL import Image, ImageStat

from tools.visual.shot_quality import analyze_frame

# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class VisualMetrics:
    ok: bool = False
    width: int = 0
    height: int = 0
    mean_luma: float = -1.0
    std_luma: float = -1.0
    entropy: float = -1.0
    pct_white: float = -1.0
    pct_black: float = -1.0
    bands: List[str] = field(default_factory=list)
    subject_bbox: Optional[List[int]] = None          # [x0, y0, x1, y1] px
    subject_coverage: float = -1.0                    # screen fraction 0..1
    head_clipped: bool = False
    ui_bbox: Optional[List[int]] = None
    ui_screen_coverage: float = -1.0
    empty_space_ratio: float = -1.0
    hash_md5_12: str = ""
    stale: bool = False
    roll_deg: float = 0.0
    issues: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualScore:
    composition: float = 0.0
    subject_framing: float = 0.0
    lighting: float = 0.0
    environment: float = 0.0
    ui: float = 0.0
    readability: float = 0.0
    target_match: float = 0.0
    technical_integrity: float = 0.0
    overall: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "composition": round(self.composition, 2),
            "subject_framing": round(self.subject_framing, 2),
            "lighting": round(self.lighting, 2),
            "environment": round(self.environment, 2),
            "ui": round(self.ui, 2),
            "readability": round(self.readability, 2),
            "target_match": round(self.target_match, 2),
            "technical_integrity": round(self.technical_integrity, 2),
            "overall": round(self.overall, 2),
        }


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------

def _entropy(image: Image.Image) -> float:
    gray = image.convert("L")
    hist = gray.histogram()
    total = float(sum(hist))
    if total <= 0:
        return 0.0
    e = 0.0
    for c in hist:
        if c:
            p = c / total
            e -= p * math.log2(p)
    return round(e, 3)


def find_subject_bbox(
    image: Image.Image,
    roi: Optional[List[float]] = None,
    min_luma: int = 45,
    max_luma: int = 250,
) -> Optional[List[int]]:
    """Bounding box of the dominant foreground subject inside a region of
    interest (fractions of the frame).

    Segmentation is component-based instead of marginal row/column density:
    the ROI is coarse-gridded and a cell counts as foreground only when it is
    a mid-tone cell with real local structure (contrast). That excludes
    smooth sky gradients, flat walls and flat floors, which is what made the
    old marginal scan union the whole ROI on any busy/mid-tone frame and
    falsely report HEAD_CROPPED and oversized coverage. Connected foreground
    cells form components and the dominant one (largest area, preferring a
    centroid in the central band) becomes the subject. Falls back to the flat-
    field density scan only when no structured component exists. Returns pixel
    coords [x0, y0, x1, y1] or None when the frame is empty/flat."""
    w, h = image.size
    if roi is None:
        roi = [0.02, 0.05, 0.72, 0.97]   # left-center band where heroes sit
    rx0, ry0 = int(w * roi[0]), int(h * roi[1])
    rx1, ry1 = int(w * roi[2]), int(h * roi[3])
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    gray = image.convert("L")
    px = gray.load()
    step = 6
    contrast_min = 12          # a cell must carry structure, not smooth fill
    cell_w = (rx1 - rx0 + step - 1) // step
    cell_h = (ry1 - ry0 + step - 1) // step
    grid = [[False] * cell_w for _ in range(cell_h)]
    for cy in range(cell_h):
        y0 = ry0 + cy * step
        y1 = min(ry0 + (cy + 1) * step, ry1)
        for cx in range(cell_w):
            x0 = rx0 + cx * step
            x1 = min(rx0 + (cx + 1) * step, rx1)
            total = 0
            lo, hi = 255, 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    p = px[x, y]
                    total += p
                    if p < lo:
                        lo = p
                    if p > hi:
                        hi = p
            mean = total / max((x1 - x0) * (y1 - y0), 1)
            if min_luma < mean < max_luma and hi - lo >= contrast_min:
                grid[cy][cx] = True
    # connected components over the coarse grid (4-connectivity)
    seen = [[False] * cell_w for _ in range(cell_h)]
    comps: List[tuple] = []    # (area, min_x, min_y, max_x, max_y, centroid_y)
    for cy in range(cell_h):
        for cx in range(cell_w):
            if not grid[cy][cx] or seen[cy][cx]:
                continue
            stack = [(cx, cy)]
            seen[cy][cx] = True
            area = 0
            mnx = mny = 1 << 30
            mxx = mxy = -1
            sy = 0
            while stack:
                gx, gy = stack.pop()
                area += 1
                sy += gy
                if gx < mnx:
                    mnx = gx
                if gx > mxx:
                    mxx = gx
                if gy < mny:
                    mny = gy
                if gy > mxy:
                    mxy = gy
                for ngx, ngy in ((gx - 1, gy), (gx + 1, gy),
                                 (gx, gy - 1), (gx, gy + 1)):
                    if 0 <= ngx < cell_w and 0 <= ngy < cell_h \
                            and grid[ngy][ngx] and not seen[ngy][ngx]:
                        seen[ngy][ngx] = True
                        stack.append((ngx, ngy))
            comps.append((area, mnx, mny, mxx, mxy, sy / max(area, 1)))

    def _marginal_bbox():
        # flat-field / hollow-subject scan: luma-band density over rows/cols.
        # Used only when no structured component exists or the best component
        # is a hollow outline (flat-filled subjects leave no interior
        # structure), where band density still frames the subject correctly.
        xs, ys = [], []
        for y in range(ry0, ry1, 2):
            cnt = 0
            for x in range(rx0, rx1, 2):
                p = px[x, y]
                if min_luma < p < max_luma:
                    cnt += 1
            if cnt > (rx1 - rx0) / 2 * 0.18:
                ys.append(y)
        for x in range(rx0, rx1, 2):
            cnt = 0
            for y in range(ry0, ry1, 2):
                p = px[x, y]
                if min_luma < p < max_luma:
                    cnt += 1
            if cnt > (ry1 - ry0) / 2 * 0.18:
                xs.append(x)
        if not xs or not ys:
            return None
        pad = 6
        return [max(rx0, min(xs) - pad), max(ry0, min(ys) - pad),
                min(rx1, max(xs) + pad), min(ry1, max(ys) + pad)]

    if not comps:
        return _marginal_bbox()
    # marginal bbox = the luma-band mass (the classic density scan)
    marginal = _marginal_bbox()
    roi_area = (rx1 - rx0) * (ry1 - ry0)
    # Two views of the scene, each right in different situations:
    #  * marginal = the luma-band mass. Correct when it covers only a small
    #    slice of the ROI (a well-defined band subject, e.g. a flat-filled
    #    hero on an out-of-band background). On busy or sky-heavy frames the
    #    marginal scan unions nearly the whole ROI and reports a false
    #    HEAD_CROPPED.
    #  * component = the dominant STRUCTURED mass. Correct when the marginal
    #    mass swallows the ROI, but flat-filled subjects leave only thin
    #    boundary strips (no interior structure), so a small fragmentary
    #    component must not override a clean marginal subject.
    if marginal is None:
        # no in-band mass: the largest structured component is the subject
        _, mnx, mny, mxx, mxy, _ = max(comps, key=lambda c: c[0])
        return [max(rx0, rx0 + mnx * step - 6),
                max(ry0, ry0 + mny * step - 6),
                min(rx1, rx0 + (mxx + 1) * step + 6),
                min(ry1, ry0 + (mxy + 1) * step + 6)]
    m_area = (marginal[2] - marginal[0]) * (marginal[3] - marginal[1])
    if m_area < roi_area * 0.45:
        return marginal
    # Busy/sky-heavy frame: prefer the dominant structured component, but
    # only when it is a real mass (>= 6% of the ROI cells), not an outline
    # strip left by a flat-filled subject.
    total_cells = cell_w * cell_h
    best = None
    for c in comps:
        if c[0] < total_cells * 0.06:
            continue
        if 0.15 * cell_h <= c[5] <= 0.85 * cell_h:
            if best is None or c[0] > best[0]:
                best = c
    if best is None:
        best = max(comps, key=lambda c: c[0])
    area, mnx, mny, mxx, mxy, _ = best
    pad = 6
    if area < total_cells * 0.06:
        return marginal
    # hollow check: an outline with an empty interior has a meaningless bbox
    bbox_cells = (mxx - mnx + 1) * (mxy - mny + 1)
    if area < bbox_cells * 0.25:
        return marginal
    return [max(rx0, rx0 + mnx * step - pad),
            max(ry0, ry0 + mny * step - pad),
            min(rx1, rx0 + (mxx + 1) * step + pad),
            min(ry1, ry0 + (mxy + 1) * step + pad)]


def find_ui_bbox(
    image: Image.Image,
    ui_roi: Optional[List[float]] = None,
    dark_threshold: int = 70,
) -> Optional[List[int]]:
    """Detect a dark UI panel on the right side (fractions). Uses the region
    that is consistently darker than the scene average."""
    w, h = image.size
    if ui_roi is None:
        ui_roi = [0.55, 0.05, 0.99, 0.97]
    x0, y0 = int(w * ui_roi[0]), int(h * ui_roi[1])
    x1, y1 = int(w * ui_roi[2]), int(h * ui_roi[3])
    gray = image.convert("L")
    px = gray.load()
    # scene baseline brightness from the left side
    base_sum = base_n = 0
    for y in range(0, h, 3):
        for x in range(int(w * 0.02), int(w * 0.4), 3):
            base_sum += px[x, y]
            base_n += 1
    baseline = base_sum / max(base_n, 1)
    xs, ys = [], []
    for y in range(y0, y1, 2):
        row_sum = 0
        row_n = 0
        for x in range(x0, x1, 2):
            row_sum += px[x, y]
            row_n += 1
        row_mean = row_sum / max(row_n, 1)
        if row_mean < min(baseline - 18, dark_threshold):
            ys.append(y)
    for x in range(x0, x1, 2):
        col_sum = 0
        col_n = 0
        for y in range(y0, y1, 2):
            col_sum += px[x, y]
            col_n += 1
        col_mean = col_sum / max(col_n, 1)
        if col_mean < min(baseline - 18, dark_threshold):
            xs.append(x)
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def detect_camera_roll(image: Image.Image, threshold_deg: float = 4.0) -> float:
    """Raw median edge-orientation estimate of camera roll.

    Strong edges near the frame border are sampled and their orientation is
    folded to [0, 45] degrees (vertical and horizontal edges both fold toward
    zero for a level camera; a rolled camera shifts them together). The
    folded median is returned. This raw value is a SENSITIVE signal, not a
    verdict: perspective keystone and texture noise bias it even for a level
    camera, so measure() gates it with roll_support() — a roll is only
    recorded when most strong edges genuinely agree on the angle. Genuine
    gross rolls (a rotated horizon/skyline with few competing structures)
    agree strongly; busy or keystoned content does not."""
    gray = image.convert("L")
    w, h = gray.size
    px = gray.load()
    angles: List[float] = []
    band = 28
    for y in range(band, h - band, 12):
        for x in range(band, w - band, 12):
            gx = px[min(x + 4, w - 1), y] - px[max(x - 4, 0), y]
            gy = px[x, min(y + 4, h - 1)] - px[max(y - 4, 0), y]
            if abs(gx) < 12 or abs(gy) < 12:
                continue     # require a genuinely tilted edge: pure axis
            mag = math.hypot(gx, gy)     # edges fold to 0 and drown roll
            if mag < 30:
                continue
            angle = math.degrees(math.atan2(gy, gx)) % 90.0
            if angle > 45.0:
                angle = 90.0 - angle
            if 42.5 <= angle <= 47.5:
                continue            # ambiguous rectangle-corner sample
            angles.append(angle)
    if len(angles) < 12:
        return 0.0
    angles.sort()
    return round(angles[len(angles) // 2], 2)


def roll_support(image: Image.Image, roll_deg: float, window: float = 5.0) -> float:
    """Fraction of strong edge samples agreeing with a candidate roll.

    A camera roll is physically a rotation of the whole frame: if it is real,
    the dominant edge family follows it and a large share of strong edges
    agree within `window` degrees. Keystone perspective and texture noise
    bias the raw median without broad agreement, so support near 1 means
    'the whole frame really is tilted', support near 0 means the median is an
    artifact of a mixed-orientation scene. Returns 0.0 when there is nothing
    to agree on."""
    if roll_deg <= 0.0:
        return 0.0
    gray = image.convert("L")
    w, h = gray.size
    px = gray.load()
    agree = total = 0
    band = 28
    for y in range(band, h - band, 12):
        for x in range(band, w - band, 12):
            gx = px[min(x + 4, w - 1), y] - px[max(x - 4, 0), y]
            gy = px[x, min(y + 4, h - 1)] - px[max(y - 4, 0), y]
            if abs(gx) < 12 or abs(gy) < 12:
                continue     # same tilted-edge requirement as the detector
            if math.hypot(gx, gy) < 30:
                continue
            angle = math.degrees(math.atan2(gy, gx)) % 90.0
            if angle > 45.0:
                angle = 90.0 - angle
            if 42.5 <= angle <= 47.5:
                continue
            total += 1
            if abs(angle - roll_deg) <= window:
                agree += 1
    if total < 12:
        return 0.0
    return round(agree / float(total), 2)


def _coverage(bbox, w, h) -> float:
    if not bbox:
        return 0.0
    return round((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / float(w * h), 4)


def measure(
    path: str,
    target: Optional[Dict[str, Any]] = None,
    reference_hash: Optional[str] = None,
    subject_locator: Optional[Callable[[Image.Image], Optional[List[int]]]] = None,
    ui_locator: Optional[Callable[[Image.Image], Optional[List[int]]]] = None,
) -> VisualMetrics:
    """Measure a screenshot against a VisualTarget. Locators are injectable so
    scenes with unusual subjects can supply scene-specific blob detection."""
    target = target or {}
    m = VisualMetrics()
    if not os.path.isfile(path):
        m.issues.append("missing file")
        return m
    raw = analyze_frame(path)
    if not raw.get("ok"):
        m.issues.append("unreadable")
        return m
    try:
        image = Image.open(path).convert("RGB")
    except Exception as exc:  # pragma: no cover
        m.issues.append(f"decode: {exc}")
        return m
    with open(path, "rb") as f:
        m.hash_md5_12 = hashlib.md5(f.read()).hexdigest()[:12]
    m.stale = bool(reference_hash and reference_hash == m.hash_md5_12)
    m.width, m.height = raw["width"], raw["height"]
    m.mean_luma = round(raw.get("mean_luma", -1), 1)
    m.std_luma = round(raw.get("std_luma", -1), 1)
    m.pct_white = round(raw.get("pct_white", 0), 4)
    m.pct_black = round(raw.get("pct_black", 0), 4)
    m.bands = raw.get("bands_blank", [])
    m.entropy = _entropy(image)
    m.ok = True

    if subject_locator is not None:
        m.subject_bbox = subject_locator(image)
    else:
        m.subject_bbox = find_subject_bbox(image)
    if m.subject_bbox:
        m.subject_coverage = _coverage(m.subject_bbox, m.width, m.height)
        # head clipping: subject reaches the top margin of the frame
        target_top_frac = (target.get("subject") or {}).get("max_head_top_frac", 0.06)
        if m.subject_bbox[1] < int(m.height * target_top_frac):
            m.head_clipped = True
            m.issues.append("HEAD_CROPPED")

    if ui_locator is not None:
        m.ui_bbox = ui_locator(image)
    else:
        m.ui_bbox = find_ui_bbox(image)
    if m.ui_bbox:
        m.ui_screen_coverage = _coverage(m.ui_bbox, m.width, m.height)

    # empty-space proxy: fraction of the frame that is near-baseline flat
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    m.empty_space_ratio = round(
        max(0.0, 1.0 - (stat.stddev[0] / max(m.mean_luma + 1e-6, 1.0)) / 3.0), 4
    )
    # Roll is recorded only when the frame broadly agrees on one tilt angle.
    # The raw edge-orientation median is a sensitive but noisy signal (keystone
    # perspective and texture bias it even for a level camera), so a low-
    # support reading is treated as level. This is intentionally strict:
    # image-only heuristics never override runtime ground truth (frozen
    # camera transforms / the documented _post_measure hook), they only
    # prevent false CAMERA_ROLL defects on level frames.
    raw_roll = detect_camera_roll(image)
    support = roll_support(image, raw_roll) if raw_roll > 3.5 else 1.0
    m.roll_deg = round(raw_roll, 2) if support >= 0.6 else 0.0
    if m.bands:
        m.issues.append("BLACK_BAND:" + ",".join(m.bands))
    # clipping flags use the TARGET-owned budget (mk. + a small tolerance) so
    # measurement issues, the loop defect and the acceptance gate all agree
    light_t = target.get("lighting") or {}
    hm = float(light_t.get("highlight_clipping_max", 0.08))
    sm = float(light_t.get("shadow_crush_max", 0.12))
    if m.pct_white > hm + 0.02:
        m.issues.append("WHITE_CLIPPING")
    if m.pct_black > sm + 0.03:
        m.issues.append("BLACK_CLIPPING")
    if m.stale:
        m.issues.append("STALE_CAPTURE")
    m.raw = raw
    m.raw["roll_raw"] = raw_roll
    m.raw["roll_support"] = support
    return m


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def score(metrics: VisualMetrics, target: Optional[Dict[str, Any]] = None) -> VisualScore:
    """Map measured metrics to a structured 0-10 score."""
    target = target or {}
    s = VisualScore()
    if not metrics.ok:
        for name in ("composition", "subject_framing", "lighting", "environment",
                     "ui", "readability", "target_match", "technical_integrity"):
            setattr(s, name, 0.0)
        s.overall = 0.0
        return s

    mean = metrics.mean_luma
    std = metrics.std_luma

    # --- lighting: mid-brightness, contrast, clipping
    # Clipping penalties are EXCESS-based: the VisualTarget owns the clipping
    # budget (highlight_clipping_max / shadow_crush_max), so a frame that sits
    # within the requested budget is not punished. A premium target (0.05 max)
    # therefore demands fewer blown pixels than a lenient target (0.08), and
    # the loop's WHITE_CLIPPING trigger (budget + 0.02) stays consistent with
    # the acceptance gate.
    light_t = target.get("lighting") or {}
    hm = float(light_t.get("highlight_clipping_max", 0.08))
    sm = float(light_t.get("shadow_crush_max", 0.12))
    lighting = 10.0
    if mean < 40 or mean > 235:
        lighting -= 4.0
    elif mean < 80 or mean > 205:
        lighting -= 1.5
    if std < 12:
        lighting -= 3.0
    lighting -= min(8.0, max(0.0, metrics.pct_white - hm) * 60.0)
    lighting -= min(8.0, max(0.0, metrics.pct_black - sm) * 40.0)
    s.lighting = _clamp(lighting)

    # --- technical integrity
    tech = 10.0
    if metrics.bands:
        tech -= len(metrics.bands) * 3.0
    if metrics.stale:
        tech -= 6.0
    if metrics.width < 800:
        tech -= 3.0
    if metrics.roll_deg and metrics.roll_deg > 3.5:
        tech -= 2.0
        metrics.issues.append("CAMERA_ROLL")
    s.technical_integrity = _clamp(tech)

    # --- subject framing against target coverage
    subj = target.get("subject") or {}
    want = subj.get("target_screen_coverage") or [0.25, 0.60]
    cov = metrics.subject_coverage
    framing = 6.0
    if cov > 0:
        if want[0] <= cov <= want[1]:
            framing = 10.0
        elif cov < want[0]:
            framing = _clamp(7.0 + (cov - want[0]) * 60.0)
        else:
            framing = _clamp(7.0 - (cov - want[1]) * 40.0)
    if metrics.head_clipped:
        framing = min(framing, 3.0)
    if subj.get("head_fully_visible") and metrics.subject_bbox is None:
        framing = min(framing, 4.0)
    s.subject_framing = _clamp(framing)

    # --- composition: hierarchy, emptiness, balance
    comp = 7.0
    if 0.15 <= cov <= 0.65:
        comp += 1.5
    if 0.05 <= metrics.empty_space_ratio <= 0.55:
        comp += 1.0
    else:
        comp -= 1.0
    if not metrics.head_clipped:
        comp += 0.5
    s.composition = _clamp(comp)

    # --- environment: variance/entropy proxy
    env = _clamp(5.0 + metrics.entropy / 1.6 + min(2.0, std / 40.0))
    s.environment = env

    # --- UI present + coverage vs target
    ui_t = target.get("ui") or {}
    ui_want = ui_t.get("screen_coverage") or [0.18, 0.50]
    ui = 5.0 if metrics.ui_bbox else 2.0
    if metrics.ui_bbox:
        ui = 8.0
        if ui_want[0] <= metrics.ui_screen_coverage <= ui_want[1]:
            ui += 1.5
        if ui_t.get("required_elements"):
            ui += 0.5
        if metrics.ui_bbox[0] < metrics.width * 0.3:
            ui -= 1.5          # panel overlapping the subject zone
    s.ui = _clamp(ui)
    if metrics.ui_bbox and not metrics.head_clipped and metrics.subject_bbox \
            and metrics.ui_bbox[0] > metrics.subject_bbox[2]:
        s.readability = _clamp(7.5 + min(2.5, std / 30.0))
    else:
        s.readability = _clamp(5.0 if metrics.ui_bbox else 2.0)

    # --- target match: distance vector between target intent and measurements
    match = 7.0
    if metrics.ui_bbox and ui_t.get("placement") == "right":
        match += 1.0
    if metrics.subject_bbox and subj.get("screen_position") == "left_center":
        w = metrics.width
        cx = (metrics.subject_bbox[0] + metrics.subject_bbox[2]) / 2.0
        if 0.25 <= cx / w <= 0.5:
            match += 1.0
    if (subj.get("head_fully_visible") and metrics.head_clipped) or \
            (metrics.bands or metrics.stale):
        match -= 2.0
    s.target_match = _clamp(match)

    overall = (
        s.composition * 0.15 + s.subject_framing * 0.20 + s.lighting * 0.15 +
        s.environment * 0.12 + s.ui * 0.12 + s.readability * 0.10 +
        s.target_match * 0.10 + s.technical_integrity * 0.06
    )
    s.overall = _clamp(overall)
    return s


_VISION_CACHE: Dict[str, List[float]] = {}


def combine_with_vision(
    s: VisualScore,
    vision_review: Optional[Dict[str, Any]] = None,
    vision_weight: float = 0.35,
) -> VisualScore:
    """Blend deterministic scores with a vision-model review dict
    ({"score": 0-10, "pass": bool, "ui_visible": [...], "issues": [...]})."""
    if not vision_review:
        return s
    v = float(vision_review.get("score", s.overall))
    blended = s.overall * (1.0 - vision_weight) + _clamp(v) * vision_weight
    s.overall = round(blended, 2)
    # vision-informed penalties for specific categories
    issues = [str(i) for i in (vision_review.get("issues") or [])]
    for name, penalty in (("subject_framing", "head"), ("ui", "ui"),
                          ("lighting", "lighting"), ("readability", "contrast")):
        if any(name[:3].lower() in i.lower() or name.lower() in i.lower() for i in issues):
            cur = getattr(s, name)
            setattr(s, name, round(_clamp(cur - 1.0), 2))
    if vision_review.get("pass") is False and s.overall >= 8.0:
        s.overall = round(s.overall - 0.5, 2)
    return s


def accepts(
    s: VisualScore,
    target: Optional[Dict[str, Any]] = None,
    mandatory_categories: Optional[List[str]] = None,
    allow_external_blocker: bool = False,
) -> bool:
    """Product contract gates: overall >= 8.0 AND every mandatory category
    >= 7.0. External-asset blockers can waive a category only when
    allow_external_blocker is set by the caller with evidence."""
    if s.overall < 8.0:
        return False
    mandatory = mandatory_categories or [
        "composition", "subject_framing", "lighting", "environment",
        "ui", "readability", "target_match", "technical_integrity",
    ]
    if allow_external_blocker:
        mandatory = [c for c in mandatory if c != "subject_framing"]
    for cat in mandatory:
        if getattr(s, cat) < 7.0:
            return False
    return True


def completion_gate(technical_ok: bool, visual_ok: bool) -> Dict[str, Any]:
    """A product task completes only when BOTH technical and visual pass."""
    return {
        "technical_pass": bool(technical_ok),
        "visual_pass": bool(visual_ok),
        "product_complete": bool(technical_ok and visual_ok),
    }