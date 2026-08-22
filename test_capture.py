#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Add project root to Python path
ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

def test_capture():
    """Test the viewport capture functionality"""
    
    print("Testing Unreal Bridge capture...")
    
    bridge = UnrealBridge()
    
    # Test ping first
    ping_result = bridge.ping()
    print(f"Ping result: {ping_result}")
    
    # Test capture
    capture_result = bridge.capture_unreal_viewport()
    print(f"Capture result: {capture_result}")
    
    if isinstance(capture_result, dict) and 'result' in capture_result:
        info = capture_result['result']
        print(f"Capture info: {info}")
        
        if isinstance(info, dict) and 'ok' in info and info['ok']:
            path = info.get('path')
            size = info.get('size')
            print(f"Captured file: {path}")
            print(f"File size: {size} bytes")
            
            if os.path.isfile(path):
                print("✓ File exists")
                if size > 1000:
                    print("✓ File size is reasonable (>1000 bytes)")
                else:
                    print("✗ File size is suspiciously small")
            else:
                print("✗ File does not exist")
        else:
            print(f"Capture failed: {info}")
    else:
        print(f"Unexpected result format: {capture_result}")

if __name__ == "__main__":
    test_capture()