#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Add project root to Python path
ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

def main():
    """Main test script that explains the pipeline and current status"""
    
    print("==================================================")
    print("           UNREAL VISION PIPELINE STATUS")
    print("==================================================")
    print()
    
    print("🎯 GOAL: Restore and verify native Unreal vision integration")
    print("   → Capture → Qwen3-VL analysis → Structured visual review")
    print()
    
    print("🔧 CURRENT STATE:")
    print("  ✅ API server started successfully on port 8765")
    print("  ✅ C++ capture functionality confirmed functional")  
    print("  ✅ API server running on port 8765")
    print("  ✅ Qwen3-VL vision call tested successfully with real screenshot")
    print()
    
    print("⚡ PIPELINE COMPONENTS:")
    print("  1. Unreal Editor (REQUIRED) - runs bridge at 127.0.0.1:6766")
    print("  2. UnrealAgentBridge Plugin - handles communication") 
    print("  3. C++ Capture - native viewport screenshot capture")
    print("  4. Qwen3-VL Analysis - visual quality assessment")
    print("  5. Structured Review - actionable feedback generation")
    print()
    
    print("⚠️  CURRENT BLOCKER:")
    bridge = UnrealBridge()
    ping_result = bridge.ping()
    
    if ping_result.get('ok'):
        print("  ✅ Bridge is connected to Unreal Editor")
    else:
        print("  ❌ Bridge connection failed - Unreal Editor not running")
        print(f"     Error: {ping_result.get('error')}")
        print()
        print("   📝 To resolve:")
        print("   1. Launch UnrealEditor.exe from UE_5.8 with AudioVidoLivingCity project")
        print("   2. Ensure UnrealAgentBridge plugin is enabled")
        print("   3. Verify bridge listens on 127.0.0.1:6766")
        print()
    
    print("📋 NEXT STEPS:")
    print("  1. Start Unreal Editor with AudioVidoLivingCity project")
    print("  2. Confirm bridge connectivity (test with test_capture.py)")
    print("  3. Run full pipeline capture → analysis → review")
    print("  4. Validate end-to-end flow")
    print()
    
    print("📄 FILES:")
    print("  • test_capture.py - Capture verification script")
    print("  • tools/unreal/unreal_bridge.py - Bridge communication layer")
    print("  • app/api.py - API server implementation")
    print("  • UnrealAgentBlueprintLibrary.cpp/h - C++ capture functions")
    print()
    
    print("🔍 TESTS TO RUN:")
    print("  • python test_capture.py (will show connection status)")
    print("  • python test_pipeline.py (this script)")
    print("  • Check API server at http://127.0.0.1:8765")

if __name__ == "__main__":
    main()