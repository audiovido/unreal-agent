#!/usr/bin/env python
"""Fresh AIVIDO bridge capture -> evidence dir with provenance + pixel metrics.

Stdlib-only by design: native bridge capture (proven path), then deterministic
pixel metrics computed from a `sips`-downsampled copy (zlib PNG decode in
pure Python) so a broken/hanging PIL environment cannot block evidence.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib

STAMP = time.strftime("%Y%m%d-%H%M%S")
OUT_DIR = f"/Users/admin/Desktop/AIVIDO_MAC_LOGS/overnight_evidence_{STAMP}"
MAP = "/Game/AIVIDO_Showcase"
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 6766

CAPTURE_CODE = r'''
import os
saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, "overnight_latest.png")
try:
    if os.path.isfile(path):
        os.remove(path)
except Exception:
    pass
diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(path))
size = os.path.getsize(path) if os.path.isfile(path) else 0
__bridge_result__ = {"ok": diag.startswith("OK|"), "path": path, "size": size, "diag": diag,
                     "map": unreal.EditorLevelLibrary.get_editor_world().get_path_name()}
'''


def sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def png_pixels(path: str):
    """Decode a small RGBA/RGB PNG into flat pixel tuples (stdlib only)."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8, f"depth {depth}"
        elif typ == b"IDAT":
            idat += chunk
        pos += 12 + ln
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * channels
    out, prev = [], bytearray(stride)
    i = 0
    for _ in range(0, len(raw), stride + 1):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += stride + 1
        if f == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out.append(bytes(line))
        prev = line
    return w, len(out), channels, out


def metrics(path: str) -> dict:
    small = "/tmp/av_metric_small.png"
    subprocess.run(["sips", "-Z", "160", path, "--out", small],
                   capture_output=True, timeout=60)
    w, h, ch, rows = png_pixels(small)
    total = w * h
    luma_sum = black = white = 0
    flat = {}
    for row in rows:
        for x in range(0, len(row), ch):
            r, g, b = row[x], row[x + 1], row[x + 2]
            l = (r * 299 + g * 587 + b * 114) // 1000
            luma_sum += l
            if l < 8:
                black += 1
            elif l > 247:
                white += 1
            flat[l // 32] = flat.get(l // 32, 0) + 1
    mean = luma_sum / total
    bands = sorted(flat.items())
    return {
        "mean_luma": round(mean, 1),
        "pct_black": round(black / total * 100, 3),
        "pct_white": round(white / total * 100, 3),
        "luma_bands_0to7": [c for _, c in bands],
        "width_small": w, "height_small": h,
    }


def bridge_python(code: str) -> dict:
    payload = {"type": "python", "code": code}
    import socket
    s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=240)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf.decode("utf-8").strip())


def main() -> int:
    print("[capture] native viewport capture via bridge ...", flush=True)
    t0 = time.time()
    resp = bridge_python(CAPTURE_CODE)
    info = resp.get("result") or {}
    print(json.dumps(info, indent=2))
    if not info.get("ok") or not info.get("size"):
        print("CAPTURE_FAILED")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    dst = os.path.join(OUT_DIR, "FINAL.png")
    shutil.copy2(info["path"], dst)
    sha = sha256_file(dst)
    meta = {
        "frame": "FINAL.png", "path": dst, "sha256": sha,
        "size_bytes": os.path.getsize(dst),
        "captured_at_epoch": time.time(), "map": MAP, "source": "bridge",
        "diag": info.get("diag", ""),
    }
    with open(os.path.join(OUT_DIR, "capture_metadata.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    m = metrics(dst)
    ok = (m["mean_luma"] > 8 and m["pct_black"] < 60.0
          and str(info.get("map", "")).startswith(MAP))
    result = {"evidence_dir": OUT_DIR, "sha12": sha[:12], "metrics": m,
              "capture_ok": ok, "elapsed_s": round(time.time() - t0, 1)}
    print(json.dumps(result, indent=2))
    with open(os.path.join(OUT_DIR, "capture_ok.json"), "w") as fh:
        json.dump(result, fh, indent=2)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
