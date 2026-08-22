#!/usr/bin/env python3
"""
Simple Test for Unreal Agent - Modern Room Creation
Direct test script to verify Unreal Agent functionality.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from tools.unreal.unreal_bridge import UnrealBridge
    
    def test_modern_room():
        """Test 1: Create a modern room with floor, walls, lighting"""
        print("=== TEST 1: MODERN ROOM CREATION ===")
        
        bridge = UnrealBridge()
        
        # Test bridge connection
        ping_result = bridge.ping()
        print(f"Bridge ping: {ping_result}")
        
        if not ping_result.get('ok'):
            print("Bridge is not ready!")
            return False
        
        # Create floor
        result = bridge.spawn_actor(
            actor_type="Box",
            location=[0, 0, -50],
            scale=[20, 20, 1]
        )
        print(f"Floor created: {result}")
        
        # Create walls (4 walls)
        result = bridge.spawn_actor(
            actor_type="Box",
            location=[0, 50, 0],
            scale=[20, 1, 10]
        )
        print(f"Front wall created: {result}")
        
        # Add lighting
        result = bridge.spawn_actor(
            actor_type="DirectionalLight",
            location=[0, 0, 100],
            rotation=[45, 0, 0]
        )
        print(f"Lighting created: {result}")
        
        # Save level
        result = bridge.save_level()
        print(f"Level saved: {result}")
        
        # Capture viewport
        result = bridge.capture_unreal_viewport()
        print(f"Viewport captured: {result}")
        
        print("=== MODERN ROOM TEST COMPLETED ===\n")
        return True

    if __name__ == "__main__":
        try:
            success = test_modern_room()
            if success:
                print("\n✅ Modern room creation successful!")
                sys.exit(0)
            else:
                print("\n❌ Modern room creation failed!")
                sys.exit(1)
        except Exception as e:
            print(f"Error during modern room creation: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
except ImportError as e:
    print(f"Failed to import UnrealBridge: {e}")
    print("Make sure Unreal Editor is running with the bridge plugin enabled")
    sys.exit(1)