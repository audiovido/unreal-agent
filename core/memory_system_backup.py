"""
Memory system for persistent project execution state management.
Handles projects, tasks, milestones, checkpoints, failure memory, and visual QA.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

ROOT = Path(__file__).resolve().parents[1]

# Memory storage paths
MEMORY_DIR = ROOT / "memory"
PROJECTS_DIR = MEMORY_DIR / "projects"
CHECKPOINTS_DIR = MEMORY_DIR / "checkpoints"
FAILURE_MEMORY_FILE = MEMORY_DIR / "failure_memory.jsonl"
VISUAL_QA_MEMORY_FILE = MEMORY_DIR / "visual_qa_memory.jsonl"
DECISIONS_FILE = MEMORY_DIR / "decisions.json"

# Ensure directories exist
MEMORY_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
CHECKPOINTS_DIR.mkdir(exist_ok=True)

# Task states
TASK_STATES = [
    "pending",
    "active", 
    "blocked",
    "failed",
    "verified",
    "completed",
    "cancelled"
]

# Valid milestone statuses
MILESTONE_STATUSES = ["not_started", "in_progress", "completed", "cancelled"]

class MemorySystem:
    def __init__(self):
        self.active_project_id = None
        self.active_milestone_id = None
        self.active_task_id = None

    def get_active_project(self) -> Optional[Dict[str, Any]]:
        """Get the currently active project"""
        if not self.active_project_id:
            return None
            
        project_path = PROJECTS_DIR / f"{self.active_project_id}.json"
        if not project_path.exists():
            return None
            
        with open(project_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def set_active_project(self, project_id: str):
        """Set the active project"""
        self.active_project_id = project_id
        self.active_milestone_id = None
        self.active_task_id = None
        
    def get_active_milestone(self) -> Optional[Dict[str, Any]]:
        """Get the currently active milestone"""
        if not self.active_project_id or not self.active_milestone_id:
            return None
            
        project = self.get_active_project()
        if not project:
            return None
            
        for milestone in project.get('milestones', []):
            if milestone['id'] == self.active_milestone_id:
                return milestone
                
        return None
    
    def set_active_milestone(self, milestone_id: str):
        """Set the active milestone"""
        self.active_milestone_id = milestone_id
        
    def get_active_task(self) -> Optional[Dict[str, Any]]:
        """Get the currently active task"""
        if not self.active_project_id or not self.active_task_id:
            return None
            
        project = self.get_active_project()
        if not project:
            return None
            
        # Check in milestones for active task
        for milestone in project.get('milestones', []):
            for task_id in milestone.get('task_ids', []):
                if task_id == self.active_task_id:
                    return self.get_task(task_id)
                    
        # If not found in milestones, check tasks directly
        for task in project.get('tasks', []):
            if task['id'] == self.active_task_id:
                return task
                
        return None
    
    def set_active_task(self, task_id: str):
        """Set the active task"""
        self.active_task_id = task_id
