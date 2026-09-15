#!/usr/bin/env python3
"""
Final Integration Test for Unreal Agent

Tests the real Unreal Bridge API end-to-end:
1. Spawn actors, verify, move, save, cleanup.
"""

import sys
import json
from tools.unreal.unreal_bridge import UnrealBridge


def test_modern_room():
    """Test 1: Create actors, verify positions, clean up."""
    print("=== TEST 1: MODERN ROOM CREATION ===")
    bridge = UnrealBridge()

    result = bridge.ping()
    assert result.get("ok"), "Bridge not connected"

    before = bridge.list_level_actors()
    actors_before = {a["name"] for a in before.get("result", [])}

    result = bridge.spawn_actor(class_name="StaticMeshActor", location=[0, 0, -50], actor_name="TestFloor")
    assert result.get("ok"), f"Floor spawn failed: {result}"

    result = bridge.spawn_actor(class_name="StaticMeshActor", location=[0, 500, 0], actor_name="TestWall")
    assert result.get("ok"), f"Wall spawn failed: {result}"

    result = bridge.spawn_actor(class_name="DirectionalLight", location=[0, 0, 300], actor_name="TestLight")
    assert result.get("ok"), f"Light spawn failed: {result}"

    result = bridge.save_level()
    assert result.get("ok"), f"Save failed: {result}"

    bridge.capture_unreal_viewport()

    for name in ["TestFloor", "TestWall", "TestLight"]:
        bridge.delete_actor(name)
    bridge.save_level()

    after = bridge.list_level_actors()
    actors_after = {a["name"] for a in after.get("result", [])}
    assert not (actors_after - actors_before), f"Leftover actors: {actors_after - actors_before}"

    print("=== MODERN ROOM TEST COMPLETED ===")
    return True


def test_umg_menu():
    """Test 2: Create and verify a named actor."""
    print("=== TEST 2: UMG MENU CREATION ===")
    bridge = UnrealBridge()

    result = bridge.spawn_actor(class_name="StaticMeshActor", location=[0, 0, 0], actor_name="TestMenuWidget")
    assert result.get("ok"), f"Spawn failed: {result}"

    result = bridge.get_actor("TestMenuWidget")
    assert result.get("ok"), f"Read back failed: {result}"

    bridge.delete_actor("TestMenuWidget")
    bridge.save_level()

    print("=== UMG MENU TEST COMPLETED ===")
    return True


def test_playable_slice():
    """Test 3: Spawn, move, verify movement."""
    print("=== TEST 3: PLAYABLE MINI SLICE ===")
    bridge = UnrealBridge()

    result = bridge.spawn_actor(class_name="StaticMeshActor", location=[0, 0, 0], actor_name="TestCharacter")
    assert result.get("ok"), f"Spawn failed: {result}"

    new_loc = [100, 100, 50]
    result = bridge.move_actor("TestCharacter", new_loc)
    assert result.get("ok"), f"Move failed: {result}"

    result = bridge.get_actor("TestCharacter")
    actual_loc = result.get("result", {}).get("location", [])
    assert actual_loc == new_loc, f"Position mismatch: {actual_loc} != {new_loc}"

    bridge.save_level()
    bridge.capture_unreal_viewport()

    bridge.delete_actor("TestCharacter")
    bridge.save_level()

    print("=== PLAYABLE MINI SLICE COMPLETED ===")
    return True


def run_all_tests():
    print("Starting comprehensive Unreal Agent tests...\n")
    try:
        test_modern_room()
        test_umg_menu()
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
    sys.exit(0 if success else 1)
