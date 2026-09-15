"""Capture provenance for AIVIDO evidence frames.

Every screenshot that is used as evidence must be accompanied by a
``capture_metadata.json`` describing exactly which bytes were captured, when,
from which map, and by which pipeline stage. The evidence packager
(scripts/aivido_evidence.py) uses this to reject stale or hand-placed frames.

Without this metadata a frame is NOT evidence: it is decoration.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_capture_metadata(
    frame_path: str,
    *,
    map_name: str = "",
    source: str = "bridge",
    captured_at_epoch: Optional[float] = None,
    out_dir: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write capture_metadata.json next to a freshly captured frame.

    Must be called immediately after the capture lands on disk, before any
    other process can modify the file (sha256 pins the exact bytes).
    """
    frame_path = os.path.abspath(frame_path)
    if not os.path.isfile(frame_path):
        raise FileNotFoundError(f"frame not found: {frame_path}")

    meta: Dict[str, Any] = {
        "frame": os.path.basename(frame_path),
        "path": frame_path,
        "sha256": sha256_file(frame_path),
        "size_bytes": os.path.getsize(frame_path),
        "captured_at_epoch": float(captured_at_epoch if captured_at_epoch is not None else time.time()),
        "map": str(map_name or ""),
        "source": str(source or "bridge"),
    }
    if extra:
        for k, v in extra.items():
            meta.setdefault(k, v)

    target_dir = out_dir or os.path.dirname(frame_path)
    os.makedirs(target_dir, exist_ok=True)
    meta_path = os.path.join(target_dir, "capture_metadata.json")
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    return meta
