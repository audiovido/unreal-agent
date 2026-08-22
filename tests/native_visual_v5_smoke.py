import json
import os
import sys

from core.orchestrator import REGISTRY

required = {
    "capture_unreal_viewport",
    "visual_review_unreal",
}

missing = sorted(required.difference(REGISTRY.keys()))

if missing:
    print(json.dumps({
        "ok": False,
        "error": "Missing tools",
        "missing": missing
    }, indent=2))
    raise SystemExit(2)

capture = REGISTRY["capture_unreal_viewport"].func()

print("=== NATIVE CAPTURE ===")
print(json.dumps(capture, ensure_ascii=False, indent=2))

if not isinstance(capture, dict) or not capture.get("ok"):
    raise SystemExit(3)

info = capture.get("result") or {}

if not info.get("ok"):
    raise SystemExit(4)

path = info.get("path")

if not path or not os.path.isfile(path):
    raise SystemExit(5)

if os.path.getsize(path) < 1000:
    raise SystemExit(6)

review = REGISTRY["visual_review_unreal"].func()

print()
print("=== NATIVE VISION REVIEW ===")
print(json.dumps(review, ensure_ascii=False, indent=2))

if not isinstance(review, dict) or not review.get("ok"):
    raise SystemExit(7)

print()
print("NATIVE_VISUAL_SMOKE_PASS")
print(path)
