import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Test the MemorySystem integration
from core.memory_system import MemorySystem

def test_memory_integration():
    """Test that the memory system works correctly"""
    
    # Create a new instance
    memory = MemorySystem()
    
    # Create a project
    project = memory.create_project("Test Project", "A test project for integration")
    print(f"Created project: {project['id']}")
    
    # Set as active project
    memory.set_active_project(project['id'])
    
    # Create a milestone
    milestone = memory.create_milestone(
        "Test Milestone",
        "A test milestone",
        start_date=1690000000,
        end_date=1690000000 + 86400 * 7  # One week later
    )
    print(f"Created milestone: {milestone['id']}")
    
    # Create a task
    task = memory.create_task(
        "Test Task",
        "A test task",
        milestone_id=milestone['id']
    )
    print(f"Created task: {task['id']}")
    
    # Set as active task
    memory.set_active_task(task['id'])
    
    # Get current task
    current_task = memory.get_active_task()
    print(f"Active task: {current_task['name']}")
    
    # Get current milestone
    current_milestone = memory.get_active_milestone()
    print(f"Active milestone: {current_milestone['name']}")
    
    # Get project
    current_project = memory.get_active_project()
    print(f"Active project: {current_project['name']}")
    
    # Test saving and loading a checkpoint
    checkpoint_data = {
        "step": 1,
        "action": "test",
        "result": "success"
    }
    
    checkpoint_saved = memory.save_checkpoint("test_checkpoint", checkpoint_data)
    print(f"Checkpoint saved: {checkpoint_saved}")
    
    # Try to load the checkpoint
    checkpoint_loaded = memory.get_checkpoint("test_checkpoint")
    print(f"Checkpoint loaded: {checkpoint_loaded}")
    
    print("Memory system integration test completed successfully!")

if __name__ == "__main__":
    test_memory_integration()