#!/usr/bin/env python3

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to Python path
ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

def test_full_pipeline():
    """Test the full pipeline: capture -> Qwen3-VL analysis -> structured review"""
    
    print("=== Testing Full Unreal Vision Pipeline ===")
    print()
    
    # Test 1: Bridge connectivity (will fail without Unreal Editor running)
    print("1. Testing bridge connectivity...")
    bridge = UnrealBridge()
    
    ping_result = bridge.ping()
    print(f"   Ping result: {ping_result}")
    if not ping_result.get("ok"):
        raise RuntimeError(
            "Bridge connection failed: " + str(ping_result.get("error"))
        )
    print("   PASS: Bridge is connected")
    
    # Test 2: Perform a real native viewport capture.
    print()
    print("2. Testing capture functionality...")
    capture = bridge.capture_unreal_viewport()
    capture_result = capture.get("result") or {}
    capture_path = Path(capture_result.get("path", ""))
    if (
        not capture.get("ok")
        or not capture_result.get("ok")
        or not capture_path.is_file()
        or capture_path.stat().st_size <= 0
    ):
        raise RuntimeError(f"Viewport capture failed: {capture}")
    print(f"   PASS: Captured {capture_path.stat().st_size} bytes")
    
    # Test 3: Perform a real Qwen3-VL analysis.
    print()
    print("3. Testing Qwen3-VL analysis...")
    review = bridge.visual_review_unreal()
    if not review.get("ok"):
        raise RuntimeError(f"Vision review failed: {review}")
    print("   PASS: Vision review returned successfully")
    
    # Test 4: Validate the structured review.
    print()
    print("4. Validating structured review...")
    review_data = review.get("review") or review.get("result") or review
    if not isinstance(review_data, dict):
        raise RuntimeError("Vision review did not return structured data")
    print("   PASS: Structured visual review is available")
    
    print()
    print("=== Pipeline Summary ===")
    print("PASS: Capture and visual-review pipeline completed end to end")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(test_full_pipeline())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
