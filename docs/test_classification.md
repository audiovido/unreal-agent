# Test Classification (Phase 17)

Classified by import/usage heuristics + name conventions. The pytest suite
collects only `test_*.py` files; probe/scan/patch scripts are development
tools that are intentionally not collected.

Total test files: 74

| file | kind |
|---|---|
| add_subobject_signature.py | PROBE |
| blueprint_api_scan.py | PROBE |
| blueprint_beginplay_smoke.py | LIVE UE |
| blueprint_event_pin_scan.py | PROBE |
| blueprint_graph_signature_scan.py | PROBE |
| blueprint_lowlevel_node_scan.py | PROBE |
| blueprint_node_api_scan.py | PROBE |
| blueprint_node_factory_scan.py | PROBE |
| blueprint_printstring_probe.py | PROBE |
| blueprint_signature_scan.py | PROBE |
| callfunction_binding_scan.py | PROBE |
| callfunction_native_probe.py | PROBE |
| check_bridge_methods.py | PROBE |
| cleanup_blueprint_smoke.py | PROBE |
| component_signature.py | PROBE |
| connect_bridge.py | PROBE |
| final_blueprint_smoke.py | PROBE |
| final_graph_bridge_smoke.py | PROBE |
| final_smoke_test.py | PROBE |
| fix_vision_http_v5_2.py | LEGACY SCRIPT |
| graph_outer_probe.py | PROBE |
| inspect_save_api.py | PROBE |
| install_heavy_specialist_v3.py | PATCH/INSTALL SCRIPT |
| install_heavy_wrapper_v3.py | PATCH/INSTALL SCRIPT |
| install_native_visual_v5.py | PATCH/INSTALL SCRIPT |
| install_native_visual_v5_1.py | PATCH/INSTALL SCRIPT |
| install_visual_loop_v4.py | PATCH/INSTALL SCRIPT |
| kismet_library_scan.py | PROBE |
| native_capture_test.py | LIVE UE |
| native_capture_test_v2.py | LIVE UE |
| native_capture_v5_1_smoke.py | LIVE UE |
| native_visual_v5_smoke.py | LEGACY SCRIPT |
| new_object_node_probe.py | PROBE |
| patch_add_component.py | PATCH/INSTALL SCRIPT |
| patch_blueprint_registry.py | PATCH/INSTALL SCRIPT |
| patch_blueprint_registry_v2.py | PATCH/INSTALL SCRIPT |
| patch_blueprint_registry_v3.py | PATCH/INSTALL SCRIPT |
| patch_component_rename.py | PATCH/INSTALL SCRIPT |
| patch_graph_registry.py | PATCH/INSTALL SCRIPT |
| printstring_binding_scan_v2.py | PROBE |
| probe_add_call_node.py | PROBE |
| probe_compile_native.py | PROBE |
| probe_connect_native.py | PROBE |
| probe_graph_nodes.py | PROBE |
| probe_node_pins.py | PROBE |
| probe_node_pins_native.py | PROBE |
| probe_save_native.py | PROBE |
| probe_set_pin.py | PROBE |
| probe_set_pin_native.py | PROBE |
| rename_subobject_signature.py | PROBE |
| save_level.py | LIVE UE |
| scene_capture_test.py | LEGACY SCRIPT |
| spawn_cube.py | LIVE UE |
| subobject_parent_signature.py | PROBE |
| test_backend_lifecycle.py | INTEGRATION (mocked bridge) |
| test_blueprint_compile.py | INTEGRATION (mocked bridge) |
| test_deterministic_dispatch.py | INTEGRATION (mocked bridge) |
| test_execution_contract.py | INTEGRATION (mocked bridge) |
| test_fake_closed_loop.py | INTEGRATION (mocked bridge) |
| test_final.py | LIVE UE |
| test_main_loop_closed_loop.py | INTEGRATION (mocked bridge) |
| test_plan_normalization.py | UNIT/INTEGRATION |
| test_project_context.py | UNIT/INTEGRATION |
| test_project_creation.py | INTEGRATION (mocked bridge) |
| test_runtime_tail.py | UNIT/INTEGRATION |
| test_save_level.py | UNIT/INTEGRATION |
| test_simple_room.py | LIVE UE |
| test_spawn_cube.py | LIVE UE |
| test_startup_map.py | UNIT/INTEGRATION |
| test_task_goal.py | UNIT/INTEGRATION |
| test_terminal_state.py | INTEGRATION (mocked bridge) |
| test_tool_registry_validation.py | UNIT/INTEGRATION |
| test_umg_menu.py | LIVE UE |
| viewport_capture_test_v3.py | LIVE UE |

## Summary

| kind | count |
|---|---|
| INTEGRATION (mocked bridge) | 8 |
| LEGACY SCRIPT | 14 |
| LIVE UE | 11 |
| PATCH/INSTALL SCRIPT | 11 |
| PROBE | 34 |
| UNIT/INTEGRATION | 8 |

## Repo-root legacy one-shot scripts (superseded; excluded via pytest.ini `--ignore`)

| file | kind |
|---|---|
| final_test.py | LEGACY SCRIPT |
| final_corrected_test.py | LEGACY SCRIPT |
| final_verification_simple.py | LEGACY SCRIPT |
| phase2_verification.py | LEGACY SCRIPT |
| simple_test.py | LEGACY SCRIPT |
| test_capture.py | LEGACY SCRIPT |
| test_memory_integration.py | LEGACY SCRIPT |
| test_persistence_simple.py | LEGACY SCRIPT |
| test_pipeline.py | LEGACY SCRIPT |
| status_check.py | LEGACY SCRIPT |
| debug_actor_classes.py | LEGACY SCRIPT |

## Notes

- UNIT/INTEGRATION files under `tests/test_*.py` are the regression suite (686 tests collected as of 2026-09-03).
- test_umg_menu.py performs real editor work (creates a WidgetComponent via the live bridge on 6766, writes to Saved/UnrealAgent) without assertions; it is a LIVE UE probe and is excluded from the automated suite via pytest.ini `--ignore` like the other LIVE UE probes, rather than passing vacuously when the bridge is down.
- LIVE UE probes (spawn_cube.py, save_level.py, viewport_capture_test_v3.py, etc.) connect to the real editor; they are kept as manual live probes, not part of the automated suite.
- PATCH/INSTALL scripts are one-shot dev tools, superseded by the current toolchain.
- New live graduation probes live in `scripts/live_*.py` (excluded from pytest via norecursedirs).
- No blanket skips were used; collection fixes were done in pytest.ini (exclude backup/ legacy probes).