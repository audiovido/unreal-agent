"""Blueprint Graph gap-closure batch 1 (UE 5.8 bridge).

Fills the highest-value gaps around the existing UnrealAgentBlueprintLibrary
surface WITHOUT reimplementing capabilities that already pass:

  EXISTS (not duplicated here):
    create_blueprint / add_blueprint_variable(+default) / add_blueprint_component
    / compile_blueprint / save_blueprint (blueprint_tools.py)
    add_call_function_node / connect_pins / set_pin_default
    / list_graph_nodes / delete_node / compile_save
    (blueprint_graph_tools.py, native UnrealAgentBlueprintLibrary)

  NEW in this batch (verified live against UE 5.8 in batch 1 acceptance):
    1. list_graphs               - open/read all graphs (name + type + node count)
    2. read_graph                - per-node detail via the NATIVE node/pin readers
                                   (EdGraph.Nodes is protected in Python; the
                                   proven surface is ListGraphNodes + ListNodePins)
    3. create_function_graph     - add a brand-new UFunction graph
    4. add_function_override     - 5.8 signature: (bp, function_name) -> graph
    5. set_variable_metadata     - instance-editable / expose-on-spawn / category
    6. list_member_variables     - read-back variable names + types
    7. list_events_and_functions - read-back event + function graph inventory
    8. compile_and_inspect       - compile via the proven BS_UP_TO_DATE contract
    9. verify_blueprint_structure- checklist assertion via read-back + CDO
    10. rename_graph             - 5.8 signature: (graph_obj, new_name)

Known engine gaps (documented, not faked):
  - pin DISCONNECT requires C++ (K2Pin removal API not exposed to Python);
    workaround: delete the consuming node and re-add it.
  - get_basic_type_by_name("Double"/"Float") returns an int-typed
    EdGraphPinType in this 5.8 build (verified live); the caller records the
    actual CDO property type instead of trusting the request string.
  - per-node compile error text is unreachable from Python (EdGraph.Nodes is
    protected); compile_and_inspect reports the engine compile status instead.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class BlueprintGraphGapTools:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # ---- 1. open/read Blueprint graphs ------------------------------------
    def list_graphs(self, asset_path: str) -> Dict[str, Any]:
        """Return every graph of the Blueprint with name and type tag."""
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    out = []
    for g in unreal.BlueprintEditorLibrary.list_graphs(bp):
        out.append({{
            "name": str(unreal.BlueprintEditorLibrary.get_name(g)),
            "type": str(g.get_class().get_name()),
        }})
    __bridge_result__ = {{"ok": True, "graphs": out, "count": len(out)}}
''')

    # ---- 2. read a graph's nodes/pins via the native readers ---------------
    def read_graph(self, asset_path: str, graph_name: str = "EventGraph") -> Dict[str, Any]:
        """Read node-level structure: node titles + raw pin names per node.

        Uses the proven native surface (ListGraphNodes + ListNodePins) because
        EdGraph.Nodes is protected in the Python editor API.
        """
        return self.bridge.execute_python(f'''
a = {self._q(asset_path)}
g = {self._q(graph_name)}
bp = unreal.EditorAssetLibrary.load_asset(a)
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
elif unreal.BlueprintEditorLibrary.find_graph(bp, g) is None:
    __bridge_result__ = {{"ok": False, "error": "graph not found: " + g}}
else:
    titles = [str(x) for x in unreal.UnrealAgentBlueprintLibrary.list_graph_nodes(a, g)]
    nodes = []
    for t in titles:
        pins = [str(p) for p in unreal.UnrealAgentBlueprintLibrary.list_node_pins(a, g, t)]
        nodes.append({{"title": t, "pins": pins}})
    __bridge_result__ = {{"ok": True, "graph": g, "node_count": len(nodes), "nodes": nodes}}
''')

    # ---- 3. create a brand-new function graph -----------------------------
    def create_function_graph(self, asset_path: str, function_name: str) -> Dict[str, Any]:
        """Create a new UFunction graph on the Blueprint and read it back."""
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    try:
        g = unreal.BlueprintEditorLibrary.add_function_graph(bp, {self._q(function_name)})
        exists = unreal.BlueprintEditorLibrary.find_graph(bp, {self._q(function_name)}) is not None
        __bridge_result__ = {{
            "ok": g is not None and exists,
            "function": {self._q(function_name)},
            "graph_class": g.get_class().get_name() if g else None,
            "verified_on_read_back": bool(exists),
        }}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc), "function": {self._q(function_name)}}}
''')

    # ---- 4. override a parent-class function ------------------------------
    def add_function_override(self, asset_path: str, function_name: str) -> Dict[str, Any]:
        """Override a parent-class function. 5.8 signature verified live:
        add_function_override(bp, function_name) returns the override graph."""
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    try:
        graph = unreal.BlueprintEditorLibrary.add_function_override(
            bp, {self._q(function_name)})
        verified = unreal.BlueprintEditorLibrary.find_graph(
            bp, {self._q(function_name)}) is not None
        __bridge_result__ = {{
            "ok": graph is not None and verified,
            "function": {self._q(function_name)},
            "graph_class": graph.get_class().get_name() if graph else None,
            "verified_on_read_back": bool(verified),
        }}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc), "function": {self._q(function_name)}}}
''')

    # ---- 5. variable metadata ---------------------------------------------
    def set_variable_metadata(self, asset_path: str, variable_name: str,
                              instance_editable: bool | None = None,
                              expose_on_spawn: bool | None = None,
                              expose_to_cinematics: bool | None = None,
                              category: str | None = None) -> Dict[str, Any]:
        # Each requested setter becomes its own indented, try-guarded call that
        # records success per metadata key (a setter missing in a given engine
        # release degrades to that key being skipped, never a hard failure).
        # NOTE: bools are emitted with repr() (Python True/False), never
        # json.dumps (JSON true/false is not valid Python).
        requested = []
        setters = []
        if instance_editable is not None:
            requested.append("instance_editable")
            setters.append(
                "unreal.BlueprintEditorLibrary.set_blueprint_variable_instance_editable"
                f"(bp, var, {repr(bool(instance_editable))})"
            )
        if expose_on_spawn is not None:
            requested.append("expose_on_spawn")
            setters.append(
                "unreal.BlueprintEditorLibrary.set_blueprint_variable_expose_on_spawn"
                f"(bp, var, {repr(bool(expose_on_spawn))})"
            )
        if expose_to_cinematics is not None:
            requested.append("expose_to_cinematics")
            setters.append(
                "unreal.BlueprintEditorLibrary.set_blueprint_variable_expose_to_cinematics"
                f"(bp, var, {repr(bool(expose_to_cinematics))})"
            )
        if category is not None:
            requested.append("category")
            setters.append(
                "unreal.BlueprintEditorLibrary.set_blueprint_variable_category"
                f"(bp, var, {self._q(category)})"
            )
        lines: list[str] = ["        applied_keys = []"]
        for key, call in zip(requested, setters):
            lines.append("        try:")
            lines.append(f"            {call}")
            lines.append(f"            applied_keys.append({self._q(key)})")
            lines.append("        except Exception as exc:")
            lines.append(f"            applied_keys.append({self._q(key)} + ':failed:' + str(exc))")
        body = "\n".join(lines)
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    try:
        var = {self._q(variable_name)}
{body}
        failed = [k for k in applied_keys if ":failed:" in k]
        __bridge_result__ = {{
            "ok": len(failed) == 0,
            "variable": {self._q(variable_name)},
            "applied": [k for k in applied_keys if ":failed:" not in k],
            "failed_setters": failed,
        }}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')

    # ---- 6. read-back variables -------------------------------------------
    def list_member_variables(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    names = unreal.BlueprintEditorLibrary.list_member_variable_names(bp)
    out = []
    for n in names:
        vtype = "unknown"
        try:
            vtype = str(unreal.BlueprintEditorLibrary.get_member_variable_type(bp, n))
        except Exception:
            pass
        out.append({{"name": str(n), "type": vtype}})
    __bridge_result__ = {{"ok": True, "variables": out}}
''')

    # ---- 7. read-back events/functions ------------------------------------
    def list_events_and_functions(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    events = [str(x) for x in unreal.BlueprintEditorLibrary.list_events(bp)]
    funcs = [str(x) for x in unreal.BlueprintEditorLibrary.list_functions(bp)]
    __bridge_result__ = {{"ok": True, "events": events, "functions": funcs}}
''')

    # ---- 8. compile + error inspection ------------------------------------
    def compile_and_inspect(self, asset_path: str) -> Dict[str, Any]:
        """Compile and read back the engine compile status.

        Uses the proven contract from blueprint_tools.compile_blueprint
        (BlueprintEditorLibrary.compile_blueprint + saved BS_UP_TO_DATE status
        re-check after reload). Per-node error text is not reachable from
        Python (EdGraph.Nodes protected) so any failing status is reported
        verbatim instead of faked per-node details.
        """
        return self.bridge.execute_python(f'''
a = {self._q(asset_path)}
bp = unreal.EditorAssetLibrary.load_asset(a)
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    status_before = str(bp.get_editor_property("status"))
    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": "compile threw: " + str(exc), "status_before": status_before}}
    else:
        reloaded = unreal.EditorAssetLibrary.load_asset(a)
        status_after = str(reloaded.get_editor_property("status")) if reloaded is not None else "ASSET_MISSING_AFTER_COMPILE"
        up_to_date = "BS_UP_TO_DATE" in status_after
        __bridge_result__ = {{
            "ok": bool(up_to_date),
            "status_before": status_before,
            "status_after": status_after,
            "errors": [] if up_to_date else [status_after],
            "note": "per-node error text unavailable from Python (EdGraph.Nodes protected); engine status is authoritative",
        }}
''')

    # ---- 9. structure verification (used by the live harness) -------------
    def verify_blueprint_structure(self, asset_path: str, expected: Dict[str, Any]) -> Dict[str, Any]:
        """    expected: {"variables": [...], "components": [...],
    "graphs": {name: {"nodes": [substr...]}}} -> verified True + diffs.

    Variables are checked via member-variable read-back; components via the
    SubobjectDataSubsystem gather (the same proven pattern add_blueprint_component
    uses - SCS components are NOT properties on the CDO, they are sub-object
    handles); graph nodes via the native ListGraphNodes titles.
    """
        exp = json.dumps(expected)
        return self.bridge.execute_python(f'''
import json as _json
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
else:
    expected = _json.loads({json.dumps(exp)})
    diffs = []
    member_names = [str(x) for x in unreal.BlueprintEditorLibrary.list_member_variable_names(bp)]
    for v in expected.get("variables", []):
        if v not in member_names:
            diffs.append("missing variable: " + v)
    component_names = []
    try:
        subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        for handle in subsystem.k2_gather_subobject_data_for_blueprint(bp):
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
            if data is not None:
                obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)
                if obj is not None and str(obj.get_class().get_name()).endswith("Component"):
                    component_names.append(str(obj.get_name()))
    except Exception as exc:
        diffs.append("component read failed: " + str(exc))
    for c in expected.get("components", []):
        if c not in component_names:
            diffs.append("missing component: " + c)
    for gname, gspec in expected.get("graphs", {{}}).items():
        g = unreal.BlueprintEditorLibrary.find_graph(bp, gname)
        if g is None:
            diffs.append("missing graph: " + gname)
            continue
        titles = [str(x) for x in unreal.UnrealAgentBlueprintLibrary.list_graph_nodes({self._q(asset_path)}, gname)]
        for want in gspec.get("nodes", []):
            if not any(want in t for t in titles):
                diffs.append(f"graph {{gname}} missing node containing: {{want}}")
    __bridge_result__ = {{
        "ok": len(diffs) == 0,
        "diffs": diffs,
        "verified": len(diffs) == 0,
    }}
''')

    # ---- 10. rename a graph -----------------------------------------------
    def rename_graph(self, asset_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """5.8 signature verified live: rename_graph(graph_object, new_name)."""
        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
g = unreal.BlueprintEditorLibrary.find_graph(bp, {self._q(old_name)})
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint not found"}}
elif g is None:
    __bridge_result__ = {{"ok": False, "error": "graph not found: " + {self._q(old_name)}}}
else:
    try:
        unreal.BlueprintEditorLibrary.rename_graph(g, {self._q(new_name)})
        found = unreal.BlueprintEditorLibrary.find_graph(bp, {self._q(new_name)}) is not None
        gone = unreal.BlueprintEditorLibrary.find_graph(bp, {self._q(old_name)}) is None
        __bridge_result__ = {{
            "ok": bool(found and gone),
            "renamed": bool(found and gone),
            "old_name": {self._q(old_name)},
            "new_name": {self._q(new_name)},
            "verified_on_read_back": bool(found),
        }}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')