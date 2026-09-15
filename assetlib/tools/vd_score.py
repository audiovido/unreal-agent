"""Pure-stdlib PNG frame scorer (no PIL/numpy dependency).

Decodes a PNG (zlib + filters) and returns capture-derived metrics used by the
visual-director rubric: exposure/contrast, sky/mid/ground band statistics,
left/right balance, colorfulness, dark/bright fractions, and a coarse
horizontal detail proxy (adjacent-sample luminance deltas).
Usage: python assetlib/tools/vd_score.py <png>
"""
import json
import struct
import sys
import zlib


def load_png_lum(path: str, step: int = 3):
    """Return (w, h, [rows of subsampled luminance 0..1 floats])."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    pos = 8
    width = height = bitd = colort = None
    raw = b""
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            width, height, bitd, colort = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            raw += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert colort in (0, 2, 6), f"unsupported color type {colort}"
    assert bitd == 8, f"unsupported bit depth {bitd}"
    ch = 1 if colort == 0 else (4 if colort == 6 else 3)
    if colort == 6 and False:
        pass
    dec = zlib.decompress(raw)
    stride = width * ch
    prev = bytearray(stride)
    out = []
    for y in range(height):
        f = dec[y * (stride + 1)]
        line = bytearray(dec[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b_ = prev[i]
                c_ = prev[i - ch] if i >= ch else 0
                p = a + b_ - c_
                pa, pb, pc = abs(p - a), abs(p - b_), abs(p - c_)
                pr = a if (pa <= pb and pa <= pc) else (b_ if pb <= pc else c_)
                line[i] = (line[i] + pr) & 255
        elif f == 0:
            pass
        else:
            raise ValueError(f"filter {f}")
        prev = line
        if y % step == 0:
            if colort == 0:
                out.append([v / 255.0 for v in line[:: ch * step]])
            else:
                row = []
                for i in range(0, stride, ch * step):
                    r_, g_, b_ = line[i], line[i + 1], line[i + 2]
                    row.append((0.2126 * r_ + 0.7152 * g_ + 0.0722 * b_) / 255.0)
                out.append(row)
    return width, height, out


def load_png_rgb_bands(path: str, step: int = 6):
    """Return per-third mean RGB for coarse color/material scoring."""
    with open(path, "rb") as fh:
        data = fh.read()
    pos = 8
    width = height = bitd = colort = None
    raw = b""
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            width, height, bitd, colort = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            raw += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert colort in (2, 6), f"unsupported color type {colort}"
    ch = 4 if colort == 6 else 3
    dec = zlib.decompress(raw)
    stride = width * ch
    prev = bytearray(stride)
    bands = [{"r": 0, "g": 0, "b": 0, "n": 0} for _ in range(3)]
    for y in range(height):
        f = dec[y * (stride + 1)]
        line = bytearray(dec[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b_ = prev[i]
                c_ = prev[i - ch] if i >= ch else 0
                p = a + b_ - c_
                pa, pb, pc = abs(p - a), abs(p - b_), abs(p - c_)
                pr = a if (pa <= pb and pa <= pc) else (b_ if pb <= pc else c_)
                line[i] = (line[i] + pr) & 255
        prev = line
        if y % step:
            continue
        band = min(2, int(y * 3 / height))
        bd = bands[band]
        for i in range(0, stride, ch * step):
            bd["r"] += line[i]
            bd["g"] += line[i + 1]
            bd["b"] += line[i + 2]
            bd["n"] += 1
    return [
        [round(bd["r"] / bd["n"] / 255.0, 3),
         round(bd["g"] / bd["n"] / 255.0, 3),
         round(bd["b"] / bd["n"] / 255.0, 3)]
        for bd in bands
    ]


def main() -> int:
    path = sys.argv[1]
    w, h, rows = load_png_lum(path, step=2)
    ny = len(rows)
    nx = len(rows[0])
    flat = [v for r in rows for v in r]
    n = len(flat)
    mean = sum(flat) / n
    var = sum((v - mean) ** 2 for v in flat) / n
    std = var ** 0.5
    # thirds by row
    third = {}
    for i, r in enumerate(rows):
        band = min(2, int(i * 3 / ny))
        third.setdefault(band, []).extend(r)
    tm = {k: sum(v) / len(v) for k, v in third.items()}
    # left/right halves
    hl, hr = [], []
    for r in rows:
        mid = len(r) // 2
        hl.extend(r[:mid]); hr.extend(r[mid:])
    # colorfulness needs rgb - skip here (grayscale lum only); report lum metrics
    dark = sum(1 for v in flat if v < 40 / 255.0) / n
    bright = sum(1 for v in flat if v > 215 / 255.0) / n
    # detail proxy: mean abs delta along x within rows, and between-row delta
    ddx = 0.0
    cnt = 0
    for r in rows:
        for i in range(1, len(r)):
            ddx += abs(r[i] - r[i - 1])
            cnt += 1
    ddx /= max(cnt, 1)
    ddy = 0.0
    cnt = 0
    for i in range(1, len(rows)):
        for j in range(min(len(rows[i]), len(rows[i - 1]))):
            ddy += abs(rows[i][j] - rows[i - 1][j])
            cnt += 1
    ddy /= max(cnt, 1)
    print(json.dumps({
        "size": [w, h],
        "mean_lum": round(mean, 3),
        "std_lum": round(std, 3),
        "thirds_mean": {str(k): round(v, 3) for k, v in sorted(tm.items())},
        "half_lum": [round(sum(hl) / len(hl), 3), round(sum(hr) / len(hr), 3)],
        "dark_frac": round(dark, 3),
        "bright_frac": round(bright, 3),
        "detail_x": round(ddx, 4),
        "detail_y": round(ddy, 4),
        "rgb_bands": load_png_rgb_bands(path),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
