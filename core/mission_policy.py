"""mission_policy.py — CANONICAL MISSION EXECUTION POLICY.

A mission is either READ_ONLY or MUTATING. The policy is enforced at two
independent boundaries:

  1. PLAN VALIDATION — before any step executes, every planned step's tool is
     classified. A READ_ONLY mission whose plan contains any non-READ_ONLY
     tool is rejected (terminal BLOCKED / PLAN_REJECTED) and zero steps run.

  2. FINAL EXECUTION BOUNDARY — the dispatch wrapper refuses to invoke any
     non-READ_ONLY tool while the mission is READ_ONLY, regardless of how the
     step got into the plan (planner, recovery, self-fix, resume, injected
     steps). UNKNOWN tools are DENIED BY DEFAULT in READ_ONLY mode.

The mode itself never comes from the LLM alone: an explicit request flag wins,
then conservative prompt markers ("read only", "do not modify anything", ...),
then intent-derived chat/plan/diagnostic classification. A prompt that merely
CONTAINS a mutating verb (e.g. "do NOT spawn") can no longer flip a read-only
request into a mutating mission.

This module is dependency-free on purpose (importable from the mission engine,
the API layer and tests without cycles).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

MODE_READ_ONLY = "READ_ONLY"
MODE_MUTATING = "MUTATING"

CLASS_READ_ONLY = "READ_ONLY"
CLASS_MUTATING = "MUTATING"
CLASS_UNKNOWN = "UNKNOWN"

# ---------------------------------------------------------------------------
# Tool safety classification (curated, auditable).
# Default for any tool not listed here is UNKNOWN -> DENIED in READ_ONLY mode.
# ---------------------------------------------------------------------------

# Read-only tools: safe queries / probes / measurements / proof captures.
# None of them mutate world, asset, project or editor state.
_READ_ONLY_TOOLS = {
    "blender_inspect_asset",
    "blender_job_status",
    "blender_jobs_list",
    "blender_status",
    "blender_verify_export",
    "capture_pie_viewport",      # screenshot of PIE viewport (proof capture)
    "capture_unreal_viewport",   # screenshot of editor viewport (proof capture)
    "discover_character_assets",
    "discover_projects",
    "frame_viewport_from_actor", # transient viewport camera framing only
    "get_actor",
    "get_asset_info",
    "get_blueprint_variable_default",
    "get_current_level",
    "get_pie_status",
    "get_project_identity",
    "get_selected_actors",
    "get_widget_text",
    "graph_list_nodes",
    "inspect_blueprint",
    "inspect_character_asset",
    "inspect_imported_asset",
    "inspect_project",
    "is_level_dirty",
    "list_assets",
    "list_level_actors",
    "list_level_sequences",
    "ollama_chat",
    "read_sequence_structure",
    "read_text_file",            # reads only; never writes
    "runtime_actor_verify",
    "runtime_status",
    "runtime_widget_verify",
    "unreal_coder_doctor",
    "unreal_ping",
    "unreal_status",
    "validate_project_creation",
    "verify_blender_output",
    "verify_character_visible",
    "verify_imported_asset",
    "verify_reopen_state",
    "verify_ui_state",
    "verify_widget_visible",
    "visual_review_unreal",
}

# Mutating tools: any operation that can change world, asset, project, editor
# or external-tool state — including transforms, saves, imports, spawns,
# deletes, material/lighting/graph edits, PIE/UI runtime state and arbitrary
# shell/Python-capable execution.
_MUTATING_TOOLS = {
    "add_actor_binding",
    "add_blueprint_component",
    "add_blueprint_variable",
    "add_button",
    "add_camera_cut",
    "add_editable_text_box",
    "add_scroll_box",
    "add_text_widget",
    "add_widget_to_viewport",
    "assign_animation",
    "avatar_react",
    "bind_button_event",
    "bind_enter_submit",
    "blender_cancel_job",
    "blender_convert_asset",
    "blender_create_asset",
    "blender_prepare_asset",
    "blender_prepare_character",
    "blender_recover",
    "chat_append_bubble",
    "chat_complete_roundtrip",
    "chat_send_message",
    "compile_blueprint",
    "create_asset_folder",
    "create_blueprint",
    "create_default_level",
    "create_level_sequence",
    "create_project",
    "create_umg_widget",
    "create_widget_blueprint",
    "delete_actor",
    "delete_asset",
    "graph_add_call_function",
    "graph_add_event_override",
    "graph_build_beginplay_print",
    "graph_compile_save",
    "graph_connect_pins",
    "graph_delete_node",
    "graph_set_pin_default",
    "import_asset",
    "import_asset_fbx",
    "import_asset_gltf",
    "import_blender_output",
    "install_character_assets",
    "move_actor",
    "open_map",
    "open_project",
    "rotate_actor",
    "run_powershell",            # arbitrary shell execution — always mutating
    "save_blueprint",
    "save_level",
    "save_sequence",
    "scale_actor",
    "scrub_and_play",
    "set_blueprint_variable_default",
    "set_character_transform",
    "set_ui_state",
    "set_widget_text",
    "spawn_actor",
    "spawn_blender_output",
    "spawn_character",
    "spawn_imported_asset",
    "start_pie",
    "stop_pie",
    "write_text_file",
}


def classify_tool(tool_name: Optional[str]) -> str:
    """Classify one tool: READ_ONLY | MUTATING | UNKNOWN (deny by default)."""
    name = str(tool_name or "")
    if name in _READ_ONLY_TOOLS:
        return CLASS_READ_ONLY
    if name in _MUTATING_TOOLS:
        return CLASS_MUTATING
    return CLASS_UNKNOWN


# ---------------------------------------------------------------------------
# Mode resolution — canonical request contract wins, prompt markers next,
# intent classification last. Never trusts the LLM alone.
# ---------------------------------------------------------------------------

# Conservative markers: a request that clearly asks for no mutation. These are
# phrase-level on purpose ("do not modify anything" triggers; a bare "do not
# modify the lighting" does not) so legitimate mixed requests are not trapped.
_STRONG_READ_ONLY_MARKERS = (
    "read only", "read-only", "readonly",
    "read-only mission", "read only mission",
    "inspection only", "report only", "analysis only", "audit only",
    "no changes", "no modifications", "no mutation",
    "do not modify anything", "do not edit anything", "do not change anything",
    "do not create, modify", "do not create, modify, delete",
    "do not spawn, move", "do not spawn, delete",
    "without modifying", "without changing",
    "do not modify the scene", "do not edit the scene",
    "zero mutation",
)


def has_strong_read_only_marker(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(m in text for m in _STRONG_READ_ONLY_MARKERS)


def resolve_mission_mode(
    prompt: str,
    *,
    explicit_read_only: Optional[bool] = None,
    request_mode: Optional[str] = None,
    intent_read_only: bool = False,
    intent_mode: Optional[str] = None,
    diagnostic: bool = False,
) -> str:
    """Resolve the canonical mission mode.

    Precedence:
      1. explicit request flag (request.read_only) — authoritative
      2. request mode chat/plan — never mutates
      3. diagnostic intent — planned as read-only health probes
      4. strong read-only prompt markers — provable user intent
      5. intent-derived read_only for non-execute classifications
      6. default MUTATING (a plain prompt may plan real work)
    """
    if explicit_read_only is not None:
        return MODE_READ_ONLY if explicit_read_only else MODE_MUTATING
    if request_mode in ("chat", "plan"):
        return MODE_READ_ONLY
    if diagnostic:
        return MODE_READ_ONLY
    if has_strong_read_only_marker(prompt):
        return MODE_READ_ONLY
    if intent_read_only and intent_mode not in ("execute",):
        return MODE_READ_ONLY
    return MODE_MUTATING


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------


def plan_violations(read_only: bool, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return every step that violates the policy.

    For MUTATING missions nothing is a violation. For READ_ONLY missions any
    step whose tool is not READ_ONLY (MUTATING or UNKNOWN) is a violation.
    """
    if not read_only:
        return []
    violations: List[Dict[str, Any]] = []
    for step in steps or []:
        tool = str(step.get("preferred_tool") or "")
        safety = classify_tool(tool)
        if safety != CLASS_READ_ONLY:
            violations.append({
                "step_id": str(step.get("step_id") or ""),
                "phase": str(step.get("phase") or ""),
                "tool": tool,
                "safety": safety,
            })
    return violations


def plan_steps_summary(state: Any) -> List[Dict[str, Any]]:
    """Per-step canonical summary (tool, phase, status, safety, blocked).

    Never includes step parameters (no chain-of-thought leakage)."""
    read_only = bool(getattr(state, "read_only", False))
    out: List[Dict[str, Any]] = []
    for step in (state.plan or {}).get("steps") or []:
        tool = str(step.get("preferred_tool") or "")
        safety = classify_tool(tool)
        out.append({
            "step_id": str(step.get("step_id") or ""),
            "phase": str(step.get("phase") or ""),
            "tool": tool,
            "status": step.get("status"),
            "safety": safety,
            "blocked": bool(read_only and safety != CLASS_READ_ONLY),
        })
    return out


def policy_snapshot(state: Any) -> Dict[str, Any]:
    """Canonical policy block for the mission response / checkpoint."""
    read_only = bool(getattr(state, "read_only", False))
    mode = MODE_READ_ONLY if read_only else MODE_MUTATING
    if not read_only:
        return {"mode": mode, "verdict": "ALLOWED", "blocked_tools": [],
                "reason": ""}
    violations = plan_violations(read_only, (state.plan or {}).get("steps"))
    if violations:
        blocked = sorted({v["tool"] for v in violations})
        return {
            "mode": mode,
            "verdict": "PLAN_REJECTED",
            "blocked_tools": blocked,
            "reason": ("read-only mission planned non-read-only tools: "
                       + ", ".join(blocked)),
        }
    return {"mode": mode, "verdict": "OK", "blocked_tools": [],
            "reason": ""}


def policy_block_payload(state: Any, *, terminal: bool = False) -> Dict[str, Any]:
    """Response-safe policy block (never raises on missing fields)."""
    base = dict(getattr(state, "policy", None) or {})
    mode = MODE_READ_ONLY if bool(getattr(state, "read_only", False)) else MODE_MUTATING
    base.setdefault("mode", mode)
    base.setdefault("verdict", "PLAN_REJECTED" if terminal else "PLANNED")
    base.setdefault("blocked_tools", [])
    base.setdefault("reason", "")
    return base