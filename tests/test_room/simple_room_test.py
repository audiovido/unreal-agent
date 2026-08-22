#!/usr/bin/env python3
"""
Simple Modern Room Test for Unreal Agent
This script will create a small polished modern room using the Unreal Agent bridge.
"""

import requests
import time
import os

def test_bridge_connection():
    """Test if the Unreal Bridge is working properly."""
    try:
        response = requests.get("http://127.0.0.1:6766/ping")
        print(f"Bridge ping result: {response.json()}")
        return response.json().get('ok', False)
    except Exception as e:
        print(f"Bridge connection failed: {e}")
        return False

def create_modern_room():
    """Create a modern room using the Unreal Agent bridge."""
    
    print("=== STARTING MODERN ROOM CREATION ===")
    
    if not test_bridge_connection():
        print("Bridge not available, cannot proceed with room creation")
        return False
    
    # Clear existing content
    try:
        response = requests.post("http://127.0.0.1:6766/clear_level")
        print(f"Clear level result: {response.json()}")
    except Exception as e:
        print(f"Failed to clear level: {e}")
        return False
    
    # Create floor
    try:
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "Box",
                                   "location": [0, 0, -50],
                                   "scale": [20, 20, 1],
                                   "material": "FloorMaterial"
                               })
        print(f"Create floor result: {response.json()}")
    except Exception as e:
        print(f"Failed to create floor: {e}")
        return False
    
    # Create walls (4 walls)
    try:
        # Front wall
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "Box",
                                   "location": [0, 50, 0],
                                   "scale": [20, 1, 10],
                                   "material": "WallMaterial"
                               })
        print(f"Create wall result: {response.json()}")
        
        # Back wall  
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "Box",
                                   "location": [0, -50, 0],
                                   "scale": [20, 1, 10],
                                   "material": "WallMaterial"
                               })
        print(f"Create back wall result: {response.json()}")
        
        # Left wall
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "Box",
                                   "location": [-50, 0, 0],
                                   "scale": [1, 20, 10],
                                   "material": "WallMaterial"
                               })
        print(f"Create left wall result: {response.json()}")
        
        # Right wall
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "Box",
                                   "location": [50, 0, 0],
                                   "scale": [1, 20, 10],
                                   "material": "WallMaterial"
                               })
        print(f"Create right wall result: {response.json()}")
        
    except Exception as e:
        print(f"Failed to create walls: {e}")
        return False
    
    # Add lighting
    try:
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "DirectionalLight",
                                   "location": [0, 0, 100],
                                   "rotation": [45, 0, 0]
                               })
        print(f"Create light result: {response.json()}")
    except Exception as e:
        print(f"Failed to create lighting: {e}")
        return False
    
    # Set camera position
    try:
        response = requests.post("http://127.0.0.1:6766/set_camera", 
                               json={
                                   "location": [0, -100, 50],
                                   "rotation": [45, 0, 0]
                               })
        print(f"Set camera result: {response.json()}")
    except Exception as e:
        print(f"Failed to set camera: {e}")
        return False
    
    # Save level
    try:
        response = requests.post("http://127.0.0.1:6766/save_level", 
                               json={
                                   "path": "Saved/UnrealAgent/test_room_modern"
                               })
        print(f"Save level result: {response.json()}")
    except Exception as e:
        print(f"Failed to save level: {e}")
        return False
    
    # Capture viewport
    try:
        response = requests.post("http://127.0.0.1:6766/capture_viewport")
        print(f"Capture result: {response.json()}")
    except Exception as e:
        print(f"Failed to capture viewport: {e}")
        return False
    
    print("=== MODERN ROOM CREATION COMPLETE ===")
    return True

if __name__ == "__main__":
    try:
        success = create_modern_room()
        if success:
            print("Room creation successful!")
        else:
            print("Room creation failed!")
    except Exception as e:
        print(f"Error during room creation: {e}")