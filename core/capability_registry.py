"""capability_registry.py — Layer 4: discoverable capability registry.

Capabilities are meaningful abilities (configure material instance, create
level sequence, import asset) built ON TOP of low-level tools. The registry is
the single place the planner queries; no task routing is hard-coded elsewhere.

Each CapabilitySpec describes what the planner needs to know:
  name, domain, description, required tools (must exist in the tool registry),
  whether it mutates project state, needs editor/live bridge, needs PIE,
  needs build, requires visual validation, and a recovery strategy.

A capability is REGISTERED only when its required tools exist in the live tool
registry, so a disabled subsystem cannot be planned by mistake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Recovery strategies supported by the mission engine.
RECOVERY_TOOL_ERROR = "tool_error_retry"        # transient: retry with cap
RECOVERY_BRIDGE = "reconnect_bridge"            # bridge down: reconnect once
RECOVERY_PROJECT = "resolve_project"            # wrong/missing project
RECOVERY_IMPORT = "asset_reimport"              # re-run intake/import
RECOVERY_COMPILE = "recompile_blueprint"        # BP compile failure
RECOVERY_VISUAL = "visual_repair_loop"          # hand to visual loop
RECOVERY_NONE = "none"


@dataclass
class CapabilitySpec:
    name: str
    domain: str
    description: str
    tools: List[str]                                # required tool names
    optional_tools: List[str] = field(default_factory=list)
    mutates_project: bool = True
    requires_editor: bool = True
    requires_pie: bool = False
    requires_build: bool = False
    requires_visual_validation: bool = False
    requires_blender: bool = False
    supported_ue_versions: tuple = ("5.3", "5.4", "5.5", "5.6", "5.7", "5.8")
    recovery: str = RECOVERY_TOOL_ERROR
    quality_floor: float = 0.0                      # visual score floor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "tools": list(self.tools),
            "optional_tools": list(self.optional_tools),
            "mutates_project": self.mutates_project,
            "requires_editor": self.requires_editor,
            "requires_pie": self.requires_pie,
            "requires_build": self.requires_build,
            "requires_visual_validation": self.requires_visual_validation,
            "requires_blender": self.requires_blender,
            "supported_ue_versions": list(self.supported_ue_versions),
            "recovery": self.recovery,
            "quality_floor": self.quality_floor,
        }


@dataclass
class RegisteredCapability:
    spec: CapabilitySpec
    available: bool
    missing_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.spec.to_dict(),
            "available": self.available,
            "missing_tools": list(self.missing_tools),
        }


# --------------------------------------------------------------------------
# The catalog. Tool names must match core/tool_registry.build_registry.
# --------------------------------------------------------------------------

CAPABILITY_CATALOG: List[CapabilitySpec] = [
    # ---- inspection / safety ------------------------------------------------
    CapabilitySpec(
        name="project_inspection", domain="general_unreal",
        description="Resolve and verify the active Unreal project identity, "
                    "engine version and live editor session.",
        tools=["inspect_project"], optional_tools=["unreal_ping", "get_project_identity"],
        mutates_project=False, requires_editor=False,
        recovery=RECOVERY_PROJECT,
    ),
    CapabilitySpec(
        name="bridge_health", domain="general_unreal",
        description="Verify the live editor bridge responds and belongs to "
                    "the expected project.",
        tools=["unreal_ping"], optional_tools=["get_project_identity"],
        mutates_project=False, recovery=RECOVERY_BRIDGE,
    ),
    CapabilitySpec(
        name="backend_health", domain="general_unreal",
        description="Probe the Aivido backend health (python env, config, "
                    "API boot, writable dirs) read-only via the canonical "
                    "doctor and emit a real evidence report.",
        tools=["unreal_coder_doctor"], mutates_project=False,
        requires_editor=False, recovery=RECOVERY_NONE,
    ),
    CapabilitySpec(
        name="level_inspection", domain="level_design",
        description="Inspect the open level's actors and state.",
        tools=["list_level_actors"], optional_tools=["get_current_level"],
        mutates_project=False, recovery=RECOVERY_BRIDGE,
    ),
    # ---- level / environment ------------------------------------------------
    CapabilitySpec(
        name="level_creation", domain="level_design",
        description="Create and persist a real /Game level.",
        tools=["create_default_level", "save_level"], requires_editor=True,
        recovery=RECOVERY_TOOL_ERROR,
    ),
    CapabilitySpec(
        name="actor_staging", domain="environment_art",
        description="Spawn and place actors with scale/mesh to compose a "
                    "scene or blockout.",
        tools=["spawn_actor"], optional_tools=["get_actor", "delete_actor"],
        requires_visual_validation=True, recovery=RECOVERY_TOOL_ERROR,
    ),
    CapabilitySpec(
        name="environment_composition", domain="environment_art",
        description="Compose an environment: floor/props/lighting basics "
                    "with composition-aware placement.",
        tools=["spawn_actor", "save_level"],
        optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, quality_floor=7.0,
        recovery=RECOVERY_VISUAL,
    ),
    # ---- lighting / materials ----------------------------------------------
    CapabilitySpec(
        name="lighting_setup", domain="lighting",
        description="Establish or repair lighting: key/fill, exposure, "
                    "mood-appropriate intensity.",
        tools=["spawn_actor"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, quality_floor=7.0,
        recovery=RECOVERY_VISUAL,
    ),
    CapabilitySpec(
        name="material_authoring", domain="materials",
        description="Author/verify materials and instances with physically "
                    "plausible values.",
        tools=["spawn_actor"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, quality_floor=7.0,
        recovery=RECOVERY_VISUAL,
    ),
    # ---- UI ------------------------------------------------------------------
    CapabilitySpec(
        name="umg_widget_authoring", domain="ui",
        description="Create UMG widgets, text/buttons/input bindings and "
                    "viewport placement.",
        tools=["create_widget_blueprint", "add_text_widget"],
        optional_tools=["add_button", "bind_button_event",
                        "add_widget_to_viewport", "set_widget_text",
                        "verify_widget_visible"],
        requires_visual_validation=True, quality_floor=7.0,
        recovery=RECOVERY_COMPILE,
    ),
    CapabilitySpec(
        name="ui_runtime_validation", domain="ui",
        description="Verify UI state and widget visibility in the running "
                    "game world.",
        tools=["set_ui_state", "verify_ui_state"], requires_pie=True,
        recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- gameplay ------------------------------------------------------------
    CapabilitySpec(
        name="blueprint_authoring", domain="gameplay",
        description="Create Blueprint assets, variables, defaults; compile "
                    "and verify read-back.",
        tools=["create_blueprint", "compile_blueprint"],
        optional_tools=["add_blueprint_variable",
                        "set_blueprint_variable_default",
                        "get_blueprint_variable_default", "save_blueprint"],
        requires_build=True, recovery=RECOVERY_COMPILE,
    ),
    CapabilitySpec(
        name="gameplay_smoke", domain="gameplay",
        description="Start PIE, verify the game world, stop PIE.",
        tools=["start_pie", "stop_pie"], requires_pie=True,
        recovery=RECOVERY_TOOL_ERROR,
    ),
    CapabilitySpec(
        name="character_staging", domain="characters",
        description="Spawn/stage characters, transforms and animation "
                    "assignment.",
        tools=["spawn_character"], optional_tools=["assign_animation",
                                                   "verify_character_visible"],
        requires_visual_validation=True, recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- cinematics ------------------------------------------------------------
    CapabilitySpec(
        name="sequencer_cinematic", domain="cinematics",
        description="Create Level Sequences with camera actors, bindings "
                    "and camera cuts.",
        tools=["create_level_sequence"], optional_tools=["add_camera_cut", "capture_unreal_viewport"],
        requires_visual_validation=True, quality_floor=7.5,
        recovery=RECOVERY_VISUAL,
    ),
    CapabilitySpec(
        name="camera_framing", domain="camera",
        description="Compute and apply composition-aware camera framing "
                    "(coverage, headroom, angle).",
        tools=["add_camera_cut"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, recovery=RECOVERY_VISUAL,
    ),
    # ---- assets ------------------------------------------------------------------
    CapabilitySpec(
        name="asset_intake_analysis", domain="asset_pipeline",
        description="Pre-import inspection of asset files: scale, "
                    "orientation, UVs, materials, repair routing.",
        tools=[], optional_tools=[], requires_editor=False,
        mutates_project=False, recovery=RECOVERY_NONE,
    ),
    CapabilitySpec(
        name="asset_import", domain="asset_pipeline",
        description="Import FBX/GLTF assets into /Game folders and verify "
                    "imported state.",
        tools=["import_asset_fbx"], optional_tools=["import_asset_gltf",
                                                    "spawn_imported_asset",
                                                    "verify_imported_asset"],
        requires_visual_validation=True, recovery=RECOVERY_IMPORT,
    ),
    CapabilitySpec(
        name="asset_cleanup_destructive", domain="asset_pipeline",
        description="Delete assets/actors with verification of absence.",
        tools=["delete_asset", "delete_actor"], requires_editor=True,
        recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- Blender / DCC ------------------------------------------------------------
    CapabilitySpec(
        name="blender_asset_repair", domain="blender",
        description="Route assets through headless Blender for scale/axis/"
                    "pivot/UV repair, then re-export for Unreal.",
        tools=["blender_prepare_asset"], optional_tools=["blender_status",
                                                         "blender_inspect_asset",
                                                         "blender_convert_asset"],
        requires_editor=False, requires_blender=True,
        recovery=RECOVERY_IMPORT,
    ),
    CapabilitySpec(
        name="blender_asset_creation", domain="blender",
        description="Create 3D assets procedurally in headless Blender and "
                    "export for Unreal import.",
        tools=["blender_create_asset"], optional_tools=["blender_status"],
        requires_editor=False, requires_blender=True,
        recovery=RECOVERY_IMPORT,
    ),
    # ---- world / terrain -----------------------------------------------------------
    CapabilitySpec(
        name="terrain_setup", domain="world_building",
        description="Landscape/terrain groundwork at real-world scale.",
        tools=["spawn_actor"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, recovery=RECOVERY_TOOL_ERROR,
    ),
    CapabilitySpec(
        name="foliage_distribution", domain="world_building",
        description="Performance-aware content distribution for large "
                    "worlds.",
        tools=["spawn_actor"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- vfx / audio / media ---------------------------------------------------------
    CapabilitySpec(
        name="niagara_effects", domain="vfx",
        description="Create/attach Niagara effects; validate visually.",
        tools=["spawn_actor"], optional_tools=["capture_unreal_viewport"],
        requires_visual_validation=True, recovery=RECOVERY_VISUAL,
    ),
    CapabilitySpec(
        name="audio_staging", domain="audio",
        description="Stage sound assets and ambient/triggers; playback "
                    "state is validated, not visuals.",
        tools=["spawn_actor"], optional_tools=["start_pie", "stop_pie"],
        requires_pie=False, recovery=RECOVERY_TOOL_ERROR,
    ),
    CapabilitySpec(
        name="media_playback", domain="media",
        description="Set up media playback surfaces; verify playback state "
                    "separately from backend integration.",
        tools=["spawn_actor"], requires_editor=True,
        recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- optimization ------------------------------------------------------------------
    CapabilitySpec(
        name="performance_analysis", domain="optimization",
        description="Measure baseline performance signals before/after "
                    "optimization changes.",
        tools=["list_level_actors"], optional_tools=["runtime_status",
                                                     "capture_unreal_viewport"],
        mutates_project=False, recovery=RECOVERY_TOOL_ERROR,
    ),
    # ---- quality --------------------------------------------------------------------------
    CapabilitySpec(
        name="visual_quality_gate", domain="visual_quality",
        description="Capture representative views, measure, score, and gate "
                    "acceptance on evidence.",
        tools=["capture_unreal_viewport"], requires_editor=True,
        mutates_project=False, recovery=RECOVERY_VISUAL,
    ),
]

_CATALOG_BY_NAME = {c.name: c for c in CAPABILITY_CATALOG}


class CapabilityRegistry:
    """Discoverable capability layer over the live tool registry."""

    def __init__(self, tool_registry: Optional[Dict[str, Any]] = None):
        self._tool_registry = tool_registry or {}
        self._cache: Dict[str, RegisteredCapability] = {}
        self.refresh()

    # -- public API --------------------------------------------------------
    def refresh(self) -> None:
        """Re-resolve availability of every capability against tools."""
        self._cache.clear()
        for spec in CAPABILITY_CATALOG:
            missing = [t for t in spec.tools if t not in self._tool_registry]
            self._cache[spec.name] = RegisteredCapability(
                spec=spec, available=not missing, missing_tools=missing,
            )

    def get(self, name: str) -> Optional[RegisteredCapability]:
        return self._cache.get(name)

    def get_spec(self, name: str) -> Optional[CapabilitySpec]:
        cap = self._cache.get(name)
        return cap.spec if cap else _CATALOG_BY_NAME.get(name)

    def available(self, name: str) -> bool:
        cap = self._cache.get(name)
        return bool(cap and cap.available)

    def by_domain(self, domain: str) -> List[RegisteredCapability]:
        return [c for c in self._cache.values() if c.spec.domain == domain]

    def available_by_domain(self, domain: str) -> List[RegisteredCapability]:
        return [c for c in self.by_domain(domain) if c.available]

    def all_capabilities(self) -> Dict[str, RegisteredCapability]:
        return dict(self._cache)

    def available_catalog(self) -> Dict[str, bool]:
        return {name: cap.available for name, cap in self._cache.items()}

    def discover(self) -> Dict[str, Any]:
        """Planner-facing discovery summary."""
        available = [c for c in self._cache.values() if c.available]
        return {
            "total": len(self._cache),
            "available": len(available),
            "domains": sorted({c.spec.domain for c in available}),
            "capabilities": {
                name: {
                    "domain": cap.spec.domain,
                    "description": cap.spec.description,
                    "recovery": cap.spec.recovery,
                    "requires_visual_validation":
                        cap.spec.requires_visual_validation,
                }
                for name, cap in sorted(self._cache.items())
            },
        }


def build_capability_registry(tool_registry: Dict[str, Any]) -> CapabilityRegistry:
    """Create a registry bound to the live tool registry (no hard-coding)."""
    return CapabilityRegistry(tool_registry)
