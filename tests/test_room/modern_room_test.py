#!/usr/bin/env python3
"""
Modern Room Test for Unreal Agent

Creates a modern room using the real Unreal Bridge API.
"""

import sys
import json
from tools.unreal.unreal_bridge import UnrealBridge


def create_modern_room():
    """Create a modern room with floor, walls, props, lighting."""
    print("=== STARTING MODERN ROOM CREATION ===")

    bridge = UnrealBridge()
    assert bridge.ping().get("ok"), "Bridge not connected"

    # Record before
    before = bridge.list_level_actors()
    actors_before = {a["name"] for a in before.get("result", [])}

    # Create floor
    bridge.spawn_actor(class_name="StaticMeshActor", location=[0, 0, -50], actor_name="RoomFloor")
    print("Floor created")

    # Create walls
    for name, loc in [("WallFront", [0, 500, 0]), ("WallBack", [0, -500, 0]),
                       ("WallLeft", [-500, 0, 0]), ("WallRight", [500, 0, 0])]:
        bridge.spawn_actor(class_name="StaticMeshActor", location=loc, actor_name=name)
    print("Walls created")

    # Add lighting
    bridge.spawn_actor(class_name="DirectionalLight", location=[0, 0, 300], actor_name="RoomLight")
    print("Lighting added")

    # Save
    bridge.save_level()
    bridge.capture_unreal_viewport()

    # Cleanup
    for name in ["RoomFloor", "WallFront", "WallBack", "WallLeft", "WallRight", "RoomLight"]:
        bridge.delete_actor(name)
    bridge.save_level()

    # Verify cleanup
    after = bridge.list_level_actors()
    actors_after = {a["name"] for a in after.get("result", [])}
    leftover = actors_after - actors_before
    assert not leftover, f"Leftover actors: {leftover}"

    print("=== MODERN ROOM CREATION COMPLETE ===")
    return True


if __name__ == "__main__":
    try:
        create_modern_room()
        print("\n✅ Modern room test passed!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
