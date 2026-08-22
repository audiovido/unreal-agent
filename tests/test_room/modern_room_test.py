#!/usr/bin/env python3
"""
Modern Room Test for Unreal Agent
This script will create a small polished modern room using the Unreal Agent.
"""

import os
import sys
import time
from pathlib import Path

# Add the app directory to the Python path to access the API
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from api import UnrealAgentAPI

def create_modern_room():
    """Create a modern room with floor, walls, props, lighting and camera view."""
    
    print("=== STARTING MODERN ROOM CREATION ===")
    
    # Initialize the Unreal Agent API
    agent = UnrealAgentAPI()
    
    # Start by clearing any existing content
    print("Clearing existing content...")
    agent.clear_level()
    
    # Create floor
    print("Creating floor...")
    agent.create_actor(
        actor_type="Floor",
        location=(0, 0, -50),
        scale=(10, 10, 1)
    )
    
    # Create walls (4 walls around the room)
    print("Creating walls...")
    # Front wall
    agent.create_actor(
        actor_type="Wall",
        location=(0, 50, 0),
        scale=(20, 1, 10)
    )
    # Back wall  
    agent.create_actor(
        actor_type="Wall",
        location=(0, -50, 0),
        scale=(20, 1, 10)
    )
    # Left wall
    agent.create_actor(
        actor_type="Wall", 
        location=(-50, 0, 0),
        scale=(1, 20, 10)
    )
    # Right wall
    agent.create_actor(
        actor_type="Wall",
        location=(50, 0, 0),
        scale=(1, 20, 10)
    )
    
    # Add basic props (if available)
    print("Adding props...")
    # Add a simple table
    agent.create_actor(
        actor_type="Table",
        location=(0, 0, -25)
    )
    
    # Add a chair
    agent.create_actor(
        actor_type="Chair",
        location=(20, 0, -25)
    )
    
    # Add lighting
    print("Adding lighting...")
    agent.create_actor(
        actor_type="DirectionalLight",
        location=(0, 0, 100),
        rotation=(45, 0, 0)
    )
    
    # Add a point light for ambient lighting
    agent.create_actor(
        actor_type="PointLight",
        location=(0, 0, 0),
        intensity=2000
    )
    
    # Set camera position for good view
    print("Setting up camera...")
    agent.set_camera_location((0, -100, 50))
    agent.set_camera_rotation((45, 0, 0))
    
    # Save the level
    print("Saving level...")
    save_path = "Saved/UnrealAgent/test_room_modern"
    agent.save_level(save_path)
    
    # Capture viewport for visual review
    print("Capturing viewport...")
    capture_result = agent.capture_viewport()
    
    print("=== MODERN ROOM CREATION COMPLETE ===")
    return capture_result

if __name__ == "__main__":
    try:
        result = create_modern_room()
        print(f"Room creation successful! Capture saved at: {result}")
    except Exception as e:
        print(f"Error during room creation: {e}")
        sys.exit(1)