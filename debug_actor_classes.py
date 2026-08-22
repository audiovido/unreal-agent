#!/usr/bin/env python3
"""
Debug what actor classes are available in Unreal
"""

import sys
sys.path.insert(0, '.')

try:
    from tools.unreal.unreal_bridge import UnrealBridge
    
    def debug_actor_creation():
        """Test different actor classes to see which work"""
        print("=== DEBUGGING ACTOR CLASSES ===")
        
        bridge = UnrealBridge()
        
        # Test ping first
        ping_result = bridge.ping()
        print(f"Bridge ping: {ping_result}")
        
        if not ping_result.get('ok'):
            print("Bridge is not ready!")
            return False
        
        # Try to spawn some basic actor classes that are likely to work
        test_classes = [
            "DirectionalLight", 
            "PointLight",
            "Box",
            "Capsule"
        ]
        
        for class_name in test_classes:
            try:
                print(f"\nTrying to spawn: {class_name}")
                result = bridge.spawn_actor(
                    class_name=class_name,
                    location=[0, 0, 0],
                    rotation=[0, 0, 0]
                )
                print(f"Result for {class_name}: {result}")
            except Exception as e:
                print(f"Error spawning {class_name}: {e}")
        
        return True

    if __name__ == "__main__":
        debug_actor_creation()
        
except ImportError as e:
    print(f"Failed to import UnrealBridge: {e}")
    sys.exit(1)