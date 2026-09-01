"""Generic screenshot quality analysis for the Unreal Agent.

Pure-Python, dependency-light (Pillow only). Detects the failure modes the
autonomous visual loop cares about most:

- all-black frames (PIE world not rendering / camera inside geometry)
- all-white / blown-out frames (exposure runaway, no content)
- blank-but-not-black frames (missing geometry, fog-only)
- extreme underexposure / overexposure
- letterboxed captures (black bars) that waste the frame

Every function here is deterministic and unit-testable offline with synthetic
images, so the visual loop does not need the LLM to notice a dead frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from PIL import Image

# Luma thresholds (0-255).
BLACK_LUMA = 8
WHITE_LUMA = 245
DARK_LUMA = 32
BRIGHT_LUMA = 224
MOSTLY_BLACK_RATIO = 0.85       # frame considered "black" if this fraction is < BLACK_LUMA
MOSTLY_WHITE_RATIO = 0.85       # frame considered "white" if this fraction is > WHITE_LUMA
BLANK_EDGE_RATIO = 0.03          # letterbox/border bands have near-zero content
LETTERBOX_BAND = 0.10            # fraction of the frame height/width for band scan


@dataclass
class QualityVerdict:
    ok: bool
    label: str                       # e.g. normal, black, white, underexposed, overexposed
    mean_luma: float = -1.0
    pct_black: float = -1.0
    pct_white: float = -1.0
    std_luma: float = -1.0
    width: int = 0
    height: int = 0
    issues: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "label": self.label,
            "mean_luma": round(self.mean_luma, 2),
            "pct_black": round(self.pct_black, 4),
            "pct_white": round(self.pct_white, 4),
            "std_luma": round(self.std_luma, 2),
            "width": self.width,
            "height": self.height,
            "issues": self.issues,
        }


def _luma_stats(image: Image.Image) -> Dict[str, float]:
    gray = image.convert("L")
    pixels = list(gray.get_flattened_data())
    n = float(len(pixels))
    mean = sum(pixels) / n
    variance = sum((p - mean) ** 2 for p in pixels) / n
    pct_black = sum(1 for p in pixels if p < BLACK_LUMA) / n
    pct_white = sum(1 for p in pixels if p > WHITE_LUMA) / n
    return {
        "mean_luma": mean,
        "std_luma": variance ** 0.5,
        "pct_black": pct_black,
        "pct_white": pct_white,
    }


def _bands_blank(image: Image.Image) -> List[str]:
    """Detect solid black bands on the frame edges (letterbox / pillarbox)."""
    w, h = image.size
    gray = image.convert("L")
    issues = []
    band_h = max(1, int(h * LETTERBOX_BAND))
    band_w = max(1, int(w * LETTERBOX_BAND))

    top = gray.crop((0, 0, w, band_h))
    bottom = gray.crop((0, h - band_h, w, h))
    left = gray.crop((0, 0, band_w, h))
    right = gray.crop((w - band_w, 0, w, h))

    def mean_black(im):
        flattened = im.get_flattened_data()
        n = float(len(flattened))
        return sum(1 for p in flattened if p < BLACK_LUMA) / n

    if mean_black(top) > 0.95:
        issues.append("top letterbox band")
    if mean_black(bottom) > 0.95:
        issues.append("bottom letterbox band")
    if mean_black(left) > 0.95:
        issues.append("left letterbox band")
    if mean_black(right) > 0.95:
        issues.append("right letterbox band")
    return issues


def analyze_frame(path: str) -> Dict[str, Any]:
    """Analyze a screenshot file; returns raw metrics (never raises on bad files)."""
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:  # pragma: no cover - file-level failure
        return {"ok": False, "error": f"cannot read image: {exc}", "label": "unreadable"}
    stats = _luma_stats(image)
    stats["width"], stats["height"] = image.size
    stats["bands_blank"] = _bands_blank(image)
    stats["ok"] = True
    return stats


def classify_frame(path: str) -> QualityVerdict:
    """Classify a screenshot into a quality verdict with a clear label."""
    raw = analyze_frame(path)
    if not raw.get("ok"):
        return QualityVerdict(ok=False, label="unreadable", raw=raw)

    mean = raw["mean_luma"]
    pct_black = raw["pct_black"]
    pct_white = raw["pct_white"]
    std = raw["std_luma"]
    issues = list(raw.get("bands_blank", []))

    label = "normal"
    if pct_black > MOSTLY_BLACK_RATIO or mean < 6.0:
        label = "black"
        issues.append("frame is essentially black (no render or camera inside void)")
    elif pct_white > MOSTLY_WHITE_RATIO or mean > 245.0:
        label = "white"
        issues.append("frame is blown out (exposure runaway)")
    elif std < 6.0 and 8.0 < mean < 24.0:
        label = "blank_dark"
        issues.append("frame is uniformly dark with almost no contrast")
    elif std < 6.0 and mean > 230.0:
        label = "blank_white"
        issues.append("frame is uniformly bright with almost no contrast")
    elif mean < 28.0:
        label = "underexposed"
        issues.append("frame is too dark overall; raise exposure/lights")
    elif mean > 218.0:
        label = "overexposed"
        issues.append("frame is too bright overall; reduce exposure/lights")
    elif std < 10.0:
        label = "low_contrast"
        issues.append("frame has very low contrast; scene may be flat")

    ok = label == "normal"
    return QualityVerdict(
        ok=ok,
        label=label,
        mean_luma=mean,
        pct_black=pct_black,
        pct_white=pct_white,
        std_luma=std,
        width=raw["width"],
        height=raw["height"],
        issues=issues,
        raw=raw,
    )


def assert_renderable(path: str) -> QualityVerdict:
    """Convenience: fail fast verdict used by the visual retry loop."""
    return classify_frame(path)