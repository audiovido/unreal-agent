"""mrq_frame_manifest.py — verifiable frame manifest for the headless MRQ render.

Independently verifies the committed MRQ PNG frame set and the MP4 encoding,
then writes reports/cinematic/headless_mrq/frame_manifest.json with:

  - exact frame sequence (frame_0000.png .. frame_NNNN.png), no gaps
  - sha256 + byte size per frame (independent re-hash, not stored state)
  - resolution / mode via PIL
  - distinct-hash count (frames are not duplicates)
  - luma stats (no black/empty render)
  - MP4 identity + ffprobe metrics
  - frame-by-frame MP4-vs-PNG parity (mean absolute difference, 0-255 scale)
  - provenance: UE render session log evidence (movie-pipeline lines)

Usage: <venv-python> scripts/mrq_frame_manifest.py [--frames DIR] [--mp4 PATH]
                   [--out PATH] [--engine-log PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FRAMES_DIR = ROOT / "reports" / "cinematic" / "headless_mrq" / "frames"
MP4_PATH = ROOT / "reports" / "cinematic" / "headless_mrq" / "mrq_render_1920x1080_30fps.mp4"
OUT_PATH = ROOT / "reports" / "cinematic" / "headless_mrq" / "frame_manifest.json"
ENGINE_LOG = Path("C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/ASSET_Showcase2/Saved/Logs/ASSET_Showcase2_2.log")

EXPECTED_FRAMES = 240
EXPECTED_W, EXPECTED_H = 1920, 1080
EXPECTED_FPS = "30/1"
EXPECTED_DURATION = 8.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(mp4: Path) -> dict:
    ffprobe = _ffprobe_bin()
    p = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames",
         "-show_entries", "format=duration", "-of", "json", str(mp4)],
        capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[:400]}")
    import json as _json
    d = _json.loads(p.stdout)
    st = d["streams"][0]
    return {"codec": st["codec_name"], "width": st["width"], "height": st["height"],
            "r_frame_rate": st["r_frame_rate"], "nb_frames": int(st["nb_frames"]),
            "duration": float(d["format"]["duration"])}


def _ffprobe_bin() -> str:
    for name in ("ffprobe",):
        try:
            p = subprocess.run(["where", name], capture_output=True, text=True)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip().splitlines()[0]
        except Exception:
            pass
    raise RuntimeError("ffprobe not found on PATH")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=str(FRAMES_DIR))
    ap.add_argument("--mp4", default=str(MP4_PATH))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--engine-log", default=str(ENGINE_LOG))
    args = ap.parse_args()

    frames_dir, mp4_path = Path(args.frames), Path(args.mp4)
    files = sorted(frames_dir.glob("frame_*.png"))
    expected_names = [f"frame_{i:04d}.png" for i in range(EXPECTED_FRAMES)]
    names_ok = [f.name for f in files] == expected_names

    from PIL import Image
    import numpy as np

    per_frame = []
    hashes = set()
    lumas = []
    dims_ok = True
    for f in files:
        b = f.read_bytes()
        h = hashlib.sha256(b).hexdigest()
        hashes.add(h)
        with Image.open(f) as im:
            w, hgt, mode = im.size[0], im.size[1], im.mode
            gray = np.asarray(im.convert("L"), dtype=np.float64)
        if (w, hgt) != (EXPECTED_W, EXPECTED_H):
            dims_ok = False
        lumas.append(float(gray.mean()))
        per_frame.append({"file": f.name, "bytes": f.stat().st_size, "sha256": h})

    # MP4 metrics + per-frame parity (decode to raw rgb24, compare to PNGs)
    mp4_metrics = ffprobe(mp4_path)
    ffmpeg = _ffprobe_bin().replace("ffprobe", "ffmpeg")
    dec = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(mp4_path), "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=300)
    raw = dec.stdout
    n_mp4 = len(raw) // (EXPECTED_W * EXPECTED_H * 3)
    mad = None
    if n_mp4 == len(files) and files:
        m = np.frombuffer(raw[: n_mp4 * EXPECTED_W * EXPECTED_H * 3],
                          dtype=np.uint8).reshape(n_mp4, EXPECTED_H, EXPECTED_W, 3).astype(np.int16)
        pngs = np.stack([np.asarray(Image.open(f).convert("RGB")) for f in files]).astype(np.int16)
        mad = float(np.abs(m - pngs).mean())

    # engine-log provenance
    prov = {"log": str(args.engine_log), "lines": {}}
    log = Path(args.engine_log)
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")
        for key, needle in [
            ("movie_args_detected", "Successfully detected and loaded required movie arguments"),
            ("render_last_shot_done", "Finished rendering last shot"),
            ("executor_finished", "MoviePipelineLinearExecutorBase finished 1 jobs"),
        ]:
            prov["lines"][key] = True if needle in text else False

    manifest = {
        "schema": "aivido.v2.mrq-frame-manifest.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "scripts/mrq_frame_manifest.py",
        "frames_dir": str(frames_dir.relative_to(ROOT)).replace("\\", "/"),
        "frame_count": len(files),
        "expected_frame_count": EXPECTED_FRAMES,
        "sequence_complete_no_gaps": names_ok,
        "resolution": f"{EXPECTED_W}x{EXPECTED_H}",
        "dimensions_all_match": dims_ok,
        "pixel_mode": files[0] and Image.open(files[0]).mode,
        "distinct_sha256_count": len(hashes),
        "all_frames_distinct": len(hashes) == len(files),
        "luma_mean_min": round(min(lumas), 2) if lumas else None,
        "luma_mean_max": round(max(lumas), 2) if lumas else None,
        "near_black_frames": sum(1 for l in lumas if l < 5.0),
        "mp4": {"path": str(mp4_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(mp4_path), **mp4_metrics},
        "mp4_vs_png_mad": round(mad, 3) if mad is not None else None,
        "mp4_frame_count_matches_png": n_mp4 == len(files),
        "engine_log_provenance": prov,
        "per_frame": per_frame,
    }

    checks = {
        "sequence": names_ok,
        "count": len(files) == EXPECTED_FRAMES,
        "dimensions": dims_ok,
        "distinct": len(hashes) == len(files),
        "no_black": manifest["near_black_frames"] == 0,
        "mp4_metrics": (mp4_metrics["codec"] == "h264"
                        and (mp4_metrics["width"], mp4_metrics["height"]) == (EXPECTED_W, EXPECTED_H)
                        and mp4_metrics["r_frame_rate"] == EXPECTED_FPS
                        and abs(mp4_metrics["duration"] - EXPECTED_DURATION) < 0.05
                        and mp4_metrics["nb_frames"] == EXPECTED_FRAMES),
        "mp4_parity": mad is not None and mad <= 3.0,
        "provenance": all(prov["lines"].values()),
    }
    manifest["checks"] = checks
    manifest["all_pass"] = all(checks.values())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"all_pass": manifest["all_pass"], "checks": checks,
                      "frame_count": manifest["frame_count"],
                      "mp4_vs_png_mad": manifest["mp4_vs_png_mad"],
                      "written": str(out)}, indent=2))
    return 0 if manifest["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
