#!/usr/bin/env python3

import sys
import os
import json
import time
from pathlib import Path

# Add the project root to path for imports
sys.path.insert(0, os.path.dirname(__file__))

print("=== PERSISTENCE TEST ===")
print()

# Test 1: Create test project structure
print("1. Creating test project structure...")

try:
    # Create necessary directories
    memory_dir = Path("memory")
    projects_dir = memory_dir / "projects"
    projects_dir.mkdir(exist_ok=True)
    
    print("  ✓ Memory directories created")
    
    # Create a test project file directly
    test_project_data = {
        "id": "TEST_MEMORY",
        "name": "TEST_MEMORY", 
        "milestones": [
            {
                "id": "M1",
                "name": "M1",
                "status": "not_started",
                "created_at": time.time(),
                "updated_at": time.time()
            }
        ],
        "tasks": [
            {
                "id": "T1",
                "name": "Task 1",
                "description": "Task 1 description", 
                "state": "pending",
                "created_at": time.time(),
                "updated_at": time.time(),
                "execution_steps": [
                    {
                        "id": "S1",
                        "description": "Step 1 of T1",
                        "verified": True,
                        "created_at": time.time()
                    },
                    {
                        "id": "S2", 
                        "description": "Step 2 of T1",
                        "verified": False,
                        "created_at": time.time()
                    }
                ]
            }
        ],
        "created_at": time.time(),
        "updated_at": time.time()
    }
    
    # Save the project
    test_project_file = projects_dir / "TEST_MEMORY.json"
    with open(test_project_file, 'w', encoding='utf-8') as f:
        json.dump(test_project_data, f, ensure_ascii=False, indent=2)
        
    print("  ✓ Test project created successfully")
    
except Exception as e:
    print(f"  ✗ Failed to create test project: {e}")

print()

# Test 2: Verify persistence works
print("2. Testing persistence verification...")
try:
    from core.memory_system import MemorySystem
    
    # Create memory system instance
    ms = MemorySystem()
    
    # Set the active project
    ms.set_active_project("TEST_MEMORY")
    
    # Get the project back
    project = ms.get_active_project()
    
    if project and project["id"] == "TEST_MEMORY":
        print("  ✓ Project persistence verified")
        
        # Check milestone
        milestones = project.get("milestones", [])
        if len(milestones) > 0 and milestones[0]["id"] == "M1":
            print("  ✓ Milestone persistence verified")
            
        # Check tasks  
        tasks = project.get("tasks", [])
        if len(tasks) >= 1:
            print("  ✓ Task persistence verified")
            
            # Check execution steps
            t1 = next((t for t in tasks if t["id"] == "T1"), None)
            if t1 and "execution_steps" in t1 and len(t1["execution_steps"]) >= 2:
                print("  ✓ Execution step persistence verified")
                
                # Verify step 1 is marked as verified
                if t1["execution_steps"][0]["verified"] == True:
                    print("  ✓ Step verification status preserved")
                else:
                    print("  ! Step 1 verification status not preserved")
            else:
                print("  ? Execution steps not found or incorrect count")
        else:
            print("  ? Tasks not found or incorrect count")
            
    else:
        print("  ? Project not retrieved correctly")
        
except Exception as e:
    print(f"  ✗ Persistence test failed: {e}")

print()

# Test 3: Test memory state reloading
print("3. Testing memory state reloading...")
try:
    # Simulate what would happen when restarting system
    # Create a new MemorySystem instance and reload the project
    
    ms2 = MemorySystem()
    ms2.set_active_project("TEST_MEMORY")
    
    project2 = ms2.get_active_project()
    
    if project2 and project2["id"] == "TEST_MEMORY":
        print("  ✓ Memory state reloaded successfully")
        
        # Verify that we can access the same data
        tasks = project2.get("tasks", [])
        t1 = next((t for t in tasks if t["id"] == "T1"), None)
        
        if t1 and len(t1.get("execution_steps", [])) > 0:
            print("  ✓ Reloaded execution steps accessible")
        else:
            print("  ? Reloaded execution steps not accessible")
    else:
        print("  ? Could not reload project correctly")
        
except Exception as e:
    print(f"  ✗ Memory reloading test failed: {e}")

print()
print("=== PERSISTENCE TEST COMPLETE ===")