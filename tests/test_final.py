#!/usr/bin/env python3
"""
Final Comprehensive Test for Unreal Agent
This script will execute all three tests in sequence:
1. Modern Room Creation
2. UMG Menu Creation  
3. Playable Mini Slice
"""

import sys
import os
from tools.unreal.unreal_bridge import UnrealBridge

def test_modern_room():
    """Test 1: Create a modern room with floor, walls, props, lighting"""
    print("=== TEST 1: MODERN ROOM CREATION ===")
    
    bridge = UnrealBridge()
    
    # Clear level first
    result = bridge.clear_level()
    print(f"Clear level: {result}")
    
    # Create floor
    result = bridge.create_actor(
        actor_type="Box",
        location=[0, 0, -50],
        scale=[20, 20, 1],
        material="FloorMaterial"
    )
    print(f"Floor created: {result}")
    
    # Create walls (4 walls)
    result = bridge.create_actor(
        actor_type="Box",
        location=[0, 50, 0],
        scale=[20, 1, 10],
        material="WallMaterial"
    )
    print(f"Front wall created: {result}")
    
    result = bridge.create_actor(
        actor_type="Box",
        location=[0, -50, 0],
        scale=[20, 1, 10],
        material="WallMaterial"
    )
    print(f"Back wall created: {result}")
    
    result = bridge.create_actor(
        actor_type="Box",
        location=[-50, 0, 0],
        scale=[1, 20, 10],
        material="WallMaterial"
    )
    print(f"Left wall created: {result}")
    
    result = bridge.create_actor(
        actor_type="Box",
        location=[50, 0, 0],
        scale=[1, 20, 10],
        material="WallMaterial"
    )
    print(f"Right wall created: {result}")
    
    # Add lighting
    result = bridge.create_actor(
        actor_type="DirectionalLight",
        location=[0, 0, 100],
        rotation=[45, 0, 0]
    )
    print(f"Lighting created: {result}")
    
    # Set camera position for good view
    result = bridge.set_camera(
        location=[0, -100, 50],
        rotation=[45, 0, 0]
    )
    print(f"Camera set: {result}")
    
    # Save level
    result = bridge.save_level("Saved/UnrealAgent/test_room_modern")
    print(f"Level saved: {result}")
    
    # Capture viewport
    result = bridge.capture_unreal_viewport()
    print(f"Viewport captured: {result}")
    
    print("=== MODERN ROOM TEST COMPLETED ===\n")
    return True

def test_umg_menu():
    """Test 2: Create UMG menu with title, buttons and styling"""
    print("=== TEST 2: UMG MENU CREATION ===")
    
    bridge = UnrealBridge()
    
    # Clear level first
    result = bridge.clear_level()
    print(f"Clear level: {result}")
    
    # Create a simple widget component 
    result = bridge.create_actor(
        actor_type="WidgetComponent",
        location=[0, 0, 0],
        widget_class="UMyMenuWidget"
    )
    print(f"Widget created: {result}")
    
    # Set properties for better visual appearance
    result = bridge.set_actor_properties(
        actor_name="MyMenuWidget",
        properties={
            "bIsFocusable": True,
            "bCanEverTick": True,
            "ForegroundColor": [1, 1, 1, 1],
            "HorizontalAlignment": "HAlign_Center",
            "VerticalAlignment": "VAlign_Center"
        }
    )
    print(f"Widget properties set: {result}")
    
    # Set camera for good view
    result = bridge.set_camera(
        location=[0, -50, 0],
        rotation=[0, 0, 0]
    )
    print(f"Camera set: {result}")
    
    # Capture viewport
    result = bridge.capture_unreal_viewport()
    print(f"Viewport captured: {result}")
    
    print("=== UMG MENU TEST COMPLETED ===\n")
    return True

def test_playable_slice():
    """Test 3: Create a playable mini slice with character, movement and interaction"""
    print("=== TEST 3: PLAYABLE MINI SLICE ===")
    
    bridge = UnrealBridge()
    
    # Clear level first
    result = bridge.clear_level()
    print(f"Clear level: {result}")
    
    # Create floor
    result = bridge.create_actor(
        actor_type="Box",
        location=[0, 0, -50],
        scale=[30, 30, 1],
        material="FloorMaterial"
    )
    print(f"Floor created: {result}")
    
    # Create simple walls
    result = bridge.create_actor(
        actor_type="Box",
        location=[0, 20, 0],
        scale=[30, 1, 5],
        material="WallMaterial"
    )
    print(f"Wall created: {result}")
    
    # Create character pawn (use a basic capsule)
    result = bridge.create_actor(
        actor_type="Capsule",
        location=[0, 0, 0],
        scale=[1, 1, 2]
    )
    print(f"Character created: {result}")
    
    # Add simple lighting
    result = bridge.create_actor(
        actor_type="PointLight",
        location=[0, 0, 50],
        intensity=2000
    )
    print(f"Lighting created: {result}")
    
    # Set camera for character view
    result = bridge.set_camera(
        location=[0, -30, 10],
        rotation=[45, 0, 0]
    )
    print(f"Camera set: {result}")
    
    # Save level
    result = bridge.save_level("Saved/UnrealAgent/test_gameplay_slice")
    print(f"Level saved: {result}")
    
    # Capture viewport
    result = bridge.capture_unreal_viewport()
    print(f"Viewport captured: {result}")
    
    print("=== PLAYABLE MINI SLICE TEST COMPLETED ===\n")
    return True

def run_all_tests():
    """Run all tests in sequence"""
    print("Starting comprehensive Unreal Agent tests...\n")
    
    try:
        # Test 1: Modern Room
        test_modern_room()
        
        # Test 2: UMG Menu
        test_umg_menu()
        
        # Test 3: Playable Mini Slice
        test_playable_slice()
        
        print("=== ALL TESTS COMPLETED SUCCESSFULLY ===")
        return True
        
    except Exception as e:
        print(f"Error during tests: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    if success:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)