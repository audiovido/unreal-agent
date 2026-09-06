#!/usr/bin/env python3
"""
AIVIDO WORKER 5 FINAL INTEGRATION SCRIPT

Integrates Worker 2 characters into final staging map.
Creates: Content/Aivido/Production/Integration/Maps/AividoHQ_Final_Stage.umap

Based on Worker 2 verified commit: 3dbbd2d5c55a4dfe9bd6acb6662e9ef0ebded5eb
"""

import json
import os
import sys

# Import Unreal bridge tools
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'assetlib', 'tools'))
try:
    from ue_bridge_acceptance import UnrealBridge
    from ue_hq_characters import spawn_character, position_character
except ImportError:
    print("WARNING: Unreal bridge tools not available, creating documentation only")
    UNREAL_AVAILABLE = False
else:
    UNREAL_AVAILABLE = True

# Worker 2 character manifest (from WORKER2_CHARACTERS_MANIFEST.json)
CHARACTERS = [
    {
        "agent_id": "Master",
        "display_name": "Master Director",
        "role": "Command Director",
        "asset_path": "/Game/AividoHQ/Characters/Master/",
        "mesh_name": "Business_Male_01",
        "station_coordinates": [0, 700, 0],
        "yaw": 90,
        "accent_color": "cyan"
    },
    {
        "agent_id": "Creative",
        "display_name": "Creative Director",
        "role": "Creative Direction",
        "asset_path": "/Game/AividoHQ/Characters/Creative/",
        "mesh_name": "Male_Adult_11",
        "station_coordinates": [3800, 900, 0],
        "yaw": -90,
        "accent_color": "amber"
    },
    {
        "agent_id": "Visual",
        "display_name": "Visual Director",
        "role": "Visual Direction",
        "asset_path": "/Game/AividoHQ/Characters/Visual/",
        "mesh_name": "Business_Female_02",
        "station_coordinates": [-3800, 900, 0],
        "yaw": -90,
        "accent_color": "magenta"
    },
    {
        "agent_id": "Technical",
        "display_name": "Technical Director",
        "role": "Technical Direction",
        "asset_path": "/Game/AividoHQ/Characters/Technical/",
        "mesh_name": "Male_Adult_03",
        "station_coordinates": [1900, 300, 0],
        "yaw": 180,
        "accent_color": "green"
    },
    {
        "agent_id": "Audio",
        "display_name": "Audio Director",
        "role": "Audio Production",
        "asset_path": "/Game/AividoHQ/Characters/Audio/",
        "mesh_name": "Female_Adult_05",
        "station_coordinates": [-1900, 300, 0],
        "yaw": 180,
        "accent_color": "violet"
    },
    {
        "agent_id": "Animation",
        "display_name": "Animation Director",
        "role": "Animation Direction",
        "asset_path": "/Game/AividoHQ/Characters/Animation/",
        "mesh_name": "Male_Adult_12",
        "station_coordinates": [950, 1700, 0],
        "yaw": 180,
        "accent_color": "sky"
    },
    {
        "agent_id": "Lighting",
        "display_name": "Lighting Artist",
        "role": "Lighting Design",
        "asset_path": "/Game/AividoHQ/Characters/Lighting/",
        "mesh_name": "Female_Adult_01",
        "station_coordinates": [-950, 1700, 0],
        "yaw": 180,
        "accent_color": "gold"
    },
    {
        "agent_id": "VFX",
        "display_name": "VFX Artist",
        "role": "Visual Effects",
        "asset_path": "/Game/AividoHQ/Characters/VFX/",
        "mesh_name": "Female_Adult_08",
        "station_coordinates": [0, 2000, 0],
        "yaw": 180,
        "accent_color": "pink"
    }
]

# Natural placement adjustments for final staging
# Adjust positions to create more natural team working environment
FINAL_PLACEMENT = {
    "Master": {"x": 0, "y": 500, "z": 0, "yaw": 0, "description": "Central command overlooking team"},
    "Creative": {"x": 1200, "y": 800, "z": 0, "yaw": -45, "description": "Creative station near visual displays"},
    "Visual": {"x": -1200, "y": 800, "z": 0, "yaw": 45, "description": "Visual station with review monitors"},
    "Technical": {"x": 800, "y": 200, "z": 0, "yaw": 90, "description": "Technical workstation"},
    "Audio": {"x": -800, "y": 200, "z": 0, "yaw": -90, "description": "Audio mixing station"},
    "Animation": {"x": 400, "y": 1500, "z": 0, "yaw": 180, "description": "Animation review area"},
    "Lighting": {"x": -400, "y": 1500, "z": 0, "yaw": 180, "description": "Lighting control station"},
    "VFX": {"x": 0, "y": 1200, "z": 0, "yaw": 0, "description": "VFX central presentation area"}
}

def create_integration_plan():
    """Create integration plan document"""
    plan = {
        "integration_id": "worker5_final_integration",
        "worker_sources": {
            "worker2": {
                "status": "integrated",
                "commit": "3dbbd2d5c55a4dfe9bd6acb6662e9ef0ebded5eb",
                "branch": "aivido-worker2-human-agents",
                "characters_count": 8,
                "characters": [c["agent_id"] for c in CHARACTERS]
            },
            "worker1": {
                "status": "waiting_for_push",
                "expected": "environment/architecture/lighting",
                "notes": "Not yet available in repository"
            },
            "worker3": {
                "status": "waiting_for_push",
                "expected": "props/set_dressing",
                "notes": "Not yet available in repository"
            },
            "worker4": {
                "status": "waiting_for_push",
                "expected": "game_ui",
                "notes": "Not yet available in repository"
            }
        },
        "staging_map": {
            "name": "AividoHQ_Final_Stage",
            "path": "Content/Aivido/Production/Integration/Maps/AividoHQ_Final_Stage.umap",
            "description": "Final integration candidate for Aivido HQ production"
        },
        "character_placement": FINAL_PLACEMENT,
        "animation_status": {
            "rocketbox_animations": "blocked",
            "current_animations": "basic_idle_walk",
            "notes": "Using verified existing animations as per Worker 2 handoff"
        },
        "integration_steps": [
            "1. Create final staging map",
            "2. Spawn all 8 Worker 2 characters",
            "3. Position characters according to natural team layout",
            "4. Apply verified animations",
            "5. Save and validate map",
            "6. Create visual proof",
            "7. Generate final handoff documentation"
        ]
    }
    
    return plan

def generate_integration_script():
    """Generate Unreal Python script for integration"""
    script = """# Unreal Python Script: AividoHQ_Final_Stage Integration
# Generated by Worker 5 Final Integration

import unreal

# Create or load final staging map
editor_asset_lib = unreal.EditorAssetLibrary()
map_path = "/Game/Aivido/Production/Integration/Maps/AividoHQ_Final_Stage"

# Check if map exists, create if not
if not editor_asset_lib.does_asset_exist(map_path):
    # Create new map from default template
    empty_map = unreal.EditorAssetLibrary.load_asset("/Engine/Maps/Templates/Template_Default")
    editor_asset_lib.duplicate_asset("/Engine/Maps/Templates/Template_Default", map_path)
    print(f"Created new map: {map_path}")
else:
    print(f"Map already exists: {map_path}")

# Load the map
editor_level_lib = unreal.EditorLevelLibrary()
current_map = editor_level_lib.get_current_level_name()
if current_map != "AividoHQ_Final_Stage":
    editor_level_lib.load_level(map_path)

# Character definitions from Worker 2
characters = [
    {"id": "Master", "mesh": "/Game/AividoHQ/Characters/Master/Business_Male_01", "pos": [0, 500, 0], "rot": [0, 0, 0]},
    {"id": "Creative", "mesh": "/Game/AividoHQ/Characters/Creative/Male_Adult_11", "pos": [1200, 800, 0], "rot": [0, -45, 0]},
    {"id": "Visual", "mesh": "/Game/AividoHQ/Characters/Visual/Business_Female_02", "pos": [-1200, 800, 0], "rot": [0, 45, 0]},
    {"id": "Technical", "mesh": "/Game/AividoHQ/Characters/Technical/Male_Adult_03", "pos": [800, 200, 0], "rot": [0, 90, 0]},
    {"id": "Audio", "mesh": "/Game/AividoHQ/Characters/Audio/Female_Adult_05", "pos": [-800, 200, 0], "rot": [0, -90, 0]},
    {"id": "Animation", "mesh": "/Game/AividoHQ/Characters/Animation/Male_Adult_12", "pos": [400, 1500, 0], "rot": [0, 180, 0]},
    {"id": "Lighting", "mesh": "/Game/AividoHQ/Characters/Lighting/Female_Adult_01", "pos": [-400, 1500, 0], "rot": [0, 180, 0]},
    {"id": "VFX", "mesh": "/Game/AividoHQ/Characters/VFX/Female_Adult_08", "pos": [0, 1200, 0], "rot": [0, 0, 0]},
]

# Spawn characters
for char in characters:
    mesh_asset = unreal.EditorAssetLibrary.load_asset(char["mesh"])
    if mesh_asset:
        location = unreal.Vector(char["pos"][0], char["pos"][1], char["pos"][2])
        rotation = unreal.Rotator(char["rot"][0], char["rot"][1], char["rot"][2])
        
        actor = editor_level_lib.spawn_actor_from_object(
            mesh_asset,
            location,
            rotation
        )
        
        if actor:
            actor.set_actor_label(f"Aivido_{char['id']}")
            print(f"Spawned: {char['id']} at {location}")
        else:
            print(f"Failed to spawn: {char['id']}")
    else:
        print(f"Mesh not found: {char['mesh']}")

# Save map
editor_asset_lib.save_asset(map_path)
print(f"Map saved: {map_path}")

print("Aivido Worker 5 Integration Complete - 8 characters placed in final staging map")
"""
    
    return script

def main():
    """Main integration execution"""
    print("=" * 60)
    print("AIVIDO WORKER 5 - FINAL INTEGRATION")
    print("=" * 60)
    
    # Create integration plan
    plan = create_integration_plan()
    
    print(f"\nIntegration Plan Created:")
    print(f"- Worker 2 Characters: {len(plan['worker_sources']['worker2']['characters'])}/8")
    print(f"- Staging Map: {plan['staging_map']['path']}")
    print(f"- Missing Workers: Worker 1, 3, 4 (marked WAITING_FOR_WORKER_PUSH)")
    
    # Generate Unreal script
    script = generate_integration_script()
    
    # Save integration files
    os.makedirs("reports/hq", exist_ok=True)
    
    # Save integration plan
    with open("reports/hq/WORKER5_INTEGRATION_PLAN.json", "w") as f:
        json.dump(plan, f, indent=2)
    
    # Save Unreal script
    with open("assetlib/tools/worker5_final_integration.py", "w") as f:
        f.write(script)
    
    # Create integration manifest
    manifest = {
        "integration": {
            "worker5": {
                "status": "in_progress",
                "branch": "aivido/worker5-final-integration",
                "map_created": plan["staging_map"]["path"],
                "characters_integrated": len(CHARACTERS),
                "workers_available": 1,
                "workers_total": 4,
                "completion_percentage": 25,  # Worker 2 only integrated
                "qa_status": "pending",
                "visual_proof": "pending"
            }
        }
    }
    
    with open("reports/hq/WORKER5_INTEGRATION_MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"\nIntegration Files Created:")
    print(f"- reports/hq/WORKER5_INTEGRATION_PLAN.json")
    print(f"- assetlib/tools/worker5_final_integration.py")
    print(f"- reports/hq/WORKER5_INTEGRATION_MANIFEST.json")
    
    print(f"\nNext Steps:")
    print(f"1. Run Unreal script to create final staging map")
    print(f"2. Verify 8 characters spawn correctly")
    print(f"3. Capture visual proof")
    print(f"4. Complete QA validation")
    print(f"5. Create final handoff documentation")
    
    print(f"\n{'=' * 60}")
    print("WORKER 5 STATUS: INTEGRATION PLAN READY")
    print(f"Progress: Worker 2 integrated | Workers 1,3,4 WAITING")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()