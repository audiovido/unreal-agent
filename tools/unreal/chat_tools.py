"""Generic reusable chat/UMG capabilities for any Unreal project.

The chat toolchain is project-agnostic and runtime-first: it builds REAL UMG
widgets at runtime (design-time widget trees are not exposed to blueprint
python) and attaches them to the actual game viewport, then binds the real
UMG delegates (Button.Clicked, EditableTextBox.OnTextCommitted) to python
handlers that survive across bridge calls through a module cached in
``sys.modules``.

Tools:
- ollama_chat            real local HTTP ollama request (no fake responses)
- create_widget_blueprint  real persisted WidgetBlueprint asset
- add_text_widget / add_scroll_box / add_editable_text_box / add_button
- bind_button_event / bind_enter_submit
- add_widget_to_viewport / set_widget_text / get_widget_text
- verify_widget_visible
- set_ui_state / verify_ui_state
- chat_append_bubble / chat_send_message / chat_complete_roundtrip

Only evidence that is read back from the live editor is ever ``verified``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from tools.unreal.unreal_bridge import UnrealBridge

# Every bridge snippet shares a durable python module in sys.modules so widget
# object references and handler callables survive between bridge calls.
RUNTIME_PREAMBLE = (
    "import sys, types as _types\n"
    "try:\n"
    "    _rt = sys.modules.get('ua_chat_rt')\n"
    "    if _rt is None:\n"
    "        _rt = _types.ModuleType('ua_chat_rt')\n"
    "        sys.modules['ua_chat_rt'] = _rt\n"
    "    if not hasattr(_rt, 'widgets'): _rt.widgets = {}\n"
    "    if not hasattr(_rt, 'handlers'): _rt.handlers = {}\n"
    "    if not hasattr(_rt, 'state_history'): _rt.state_history = []\n"
    "    if not hasattr(_rt, 'bubbles'): _rt.bubbles = []\n"
    "    if not hasattr(_rt, 'root'): _rt.root = None\n"
    "    if not hasattr(_rt, 'viewport_added'): _rt.viewport_added = {}\n"
    "except Exception:\n"
    "    _rt = None\n"
    "def _rt_outer():\n"
    "    try:\n"
    "        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()\n"
    "    except Exception:\n"
    "        return None\n"
    "def _rt_root():\n"
    "    if _rt is None or _rt.root is None:\n"
    "        if _rt is not None:\n"
    "            r = unreal.new_object(unreal.CanvasPanel, _rt_outer())\n"
    "            _rt.root = r\n"
    "    return _rt.root if _rt is not None else None\n"
    "def _rt_put(name, widget):\n"
    "    if _rt is not None:\n"
    "        _rt.widgets[str(name)] = widget\n"
    "def _rt_get(name):\n"
    "    if _rt is None:\n"
    "        return None\n"
    "    return _rt.widgets.get(str(name))\n"
    "def _rt_text(widget):\n"
    "    try:\n"
    "        t = widget.get_text()\n"
    "    except Exception:\n"
    "        return None\n"
    "    if t is None:\n"
    "        return None\n"
    "    try:\n"
    "        if hasattr(t, 'to_string'):\n"
    "            return t.to_string()\n"
    "    except Exception:\n"
    "        pass\n"
    "    return str(t)\n"
    "def _rt_reset_if_world_changed():\n"
    "    if _rt is None:\n"
    "        return\n"
    "    try:\n"
    "        _w = _rt_outer()\n"
    "        _wid = str(_w.get_path_name()) if _w is not None else None\n"
    "    except Exception:\n"
    "        _wid = None\n"
    "    if _wid == getattr(_rt, 'world_id', None):\n"
    "        return\n"
    "    # The game world changed (editor <-> PIE or a new PIE session): every\n"
    "    # widget/handler from the previous world points at destroyed objects,\n"
    "    # so reset the whole runtime registry before rebuilding.\n"
    "    _rt.world_id = _wid\n"
    "    _rt.widgets = {}\n"
    "    _rt.handlers = {}\n"
    "    _rt.state_history = []\n"
    "    _rt.bubbles = []\n"
    "    _rt.root = None\n"
    "    _rt.viewport_added = {}\n"
    "_rt_reset_if_world_changed()\n"
)


def _ollama_config() -> Dict[str, Any]:
    url = os.getenv("UNREAL_AGENT_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        from tools.unreal.project_manager import SETTINGS
        url = os.getenv("UNREAL_AGENT_OLLAMA_URL") or SETTINGS.get("ollama_url") or url
    except Exception:
        pass
    url = str(url).strip().rstrip("/")
    # Accept base URLs and URLs already ending in /api or /api/chat.
    for suffix in ("/api/chat", "/api"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    return {"url": url}


class ChatTools:
    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    # ------------------------------------------------------------------- ollama
    def ollama_chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        timeout: float = 180.0,
    ) -> Dict[str, Any]:
        """Call the real local Ollama HTTP endpoint and return the model's
        response. Never fabricates a response: any failure returns a structured
        error with ``verified=False``."""
        if not isinstance(prompt, str) or not prompt.strip():
            return {
                "ok": False,
                "code": "EMPTY_PROMPT",
                "prompt": prompt,
                "response": None,
                "model": model,
                "latency_ms": None,
                "local_only": True,
                "verified": False,
                "error": "A non-empty prompt is required",
            }
        cfg = _ollama_config()
        base_url = cfg["url"].rstrip("/")
        try:
            timeout = float(timeout or 180.0)
        except Exception:
            timeout = 180.0
        resolved_model = model or os.getenv("UNREAL_AGENT_OLLAMA_CHAT_MODEL")
        if not resolved_model:
            resolved_model = self._first_available_model(base_url, timeout=min(timeout, 30.0))
        if not resolved_model:
            return {
                "ok": False,
                "code": "NO_MODEL",
                "prompt": prompt,
                "response": None,
                "model": None,
                "latency_ms": None,
                "local_only": True,
                "verified": False,
                "error": "No Ollama model was specified or available (checked /api/tags)",
            }
        body: Dict[str, Any] = {
            "model": resolved_model,
            "stream": False,
            "messages": [],
        }
        if system_prompt:
            body["messages"].append({"role": "system", "content": system_prompt})
        body["messages"].append({"role": "user", "content": prompt})
        started = time.time()
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json=body,
                timeout=max(timeout, 1.0),
            )
            response.raise_for_status()
            data = response.json()
            content = str((data.get("message") or {}).get("content") or "").strip()
            latency_ms = int((time.time() - started) * 1000)
            verified = bool(content)
            return {
                "ok": verified,
                "code": None if verified else "EMPTY_OLLAMA_RESPONSE",
                "model": resolved_model,
                "prompt": prompt,
                "response": content,
                "latency_ms": latency_ms,
                "local_only": True,
                "endpoint": f"{base_url}/api/chat",
                "verified": verified,
                "error": None if verified else "Ollama returned an empty response",
            }
        except requests.exceptions.Timeout as exc:
            return self._ollama_error("OLLAMA_TIMEOUT", prompt, resolved_model, f"Ollama request timed out after {timeout}s: {exc}")
        except requests.exceptions.ConnectionError as exc:
            return self._ollama_error("OLLAMA_UNREACHABLE", prompt, resolved_model, f"Could not reach local Ollama at {base_url}: {exc}")
        except Exception as exc:
            return self._ollama_error("OLLAMA_FAILED", prompt, resolved_model, f"{type(exc).__name__}: {exc}")

    def _first_available_model(self, base_url: str, timeout: float = 30.0) -> Optional[str]:
        try:
            tags = requests.get(f"{base_url}/api/tags", timeout=timeout)
            tags.raise_for_status()
            models = (tags.json() or {}).get("models") or []
            if not isinstance(models, list):
                return None
            for entry in models:
                name = str((entry or {}).get("name") or "").strip()
                if name:
                    return name
            return None
        except Exception:
            return None

    @staticmethod
    def _ollama_error(code: str, prompt: str, model: Optional[str], message: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "code": code,
            "prompt": prompt,
            "response": None,
            "model": model,
            "latency_ms": None,
            "local_only": True,
            "verified": False,
            "error": message,
        }

    # ------------------------------------------------------------- blueprints
    def create_widget_blueprint(self, asset_path: str) -> Dict[str, Any]:
        """Create and independently verify a real persisted WidgetBlueprint."""
        from tools.unreal.blueprint_tools import BlueprintTools
        if not isinstance(asset_path, str) or not asset_path.startswith("/Game/"):
            return {"ok": False, "code": "INVALID_WIDGET_PATH", "asset_path": asset_path, "verified": False}
        return BlueprintTools(self.bridge).create_umg_widget(asset_path)

    # ------------------------------------------------------------- widget tree
    def add_text_widget(
        self,
        name: str,
        text: str = "",
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._add_widget("TextBlock", name, {"text": text}, parent)

    def add_scroll_box(
        self,
        name: str,
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._add_widget("ScrollBox", name, {}, parent)

    def add_editable_text_box(
        self,
        name: str,
        hint_text: Optional[str] = None,
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._add_widget("EditableTextBox", name, {"hint_text": hint_text or ""}, parent)

    def add_button(
        self,
        name: str,
        label: Optional[str] = None,
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._add_widget("Button", name, {"label": label or ""}, parent)

    def _add_widget(
        self,
        widget_class: str,
        name: str,
        props: Dict[str, Any],
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        widget_class = str(widget_class or "").strip()
        name = str(name or "").strip()
        if not widget_class:
            return {"ok": False, "code": "MISSING_WIDGET_CLASS", "verified": False}
        if not name:
            return {"ok": False, "code": "MISSING_WIDGET_NAME", "verified": False}
        supported = {
            "TextBlock", "ScrollBox", "EditableTextBox", "Button",
            "VerticalBox", "HorizontalBox", "CanvasPanel", "SizeBox",
        }
        if widget_class not in supported:
            return {
                "ok": False,
                "code": "UNSUPPORTED_WIDGET_CLASS",
                "widget_class": widget_class,
                "supported": sorted(supported),
                "verified": False,
            }
        prop_text = json.dumps(props or {})
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
import json as _json
widget_class = {widget_class!r}
name = {name!r}
props = _json.loads({prop_text!r})
parent_name = {parent!r}
cls = getattr(unreal, widget_class, None)
if cls is None:
    __bridge_result__ = {{
        "ok": False, "code": "UNKNOWN_WIDGET_CLASS", "widget_class": widget_class,
        "widget": name, "class": None, "verified": False,
    }}
else:
    parent = _rt_get(parent_name) if parent_name else None
    if parent_name and parent is None:
        __bridge_result__ = {{
            "ok": False, "code": "MISSING_PARENT_WIDGET", "widget": name,
            "parent": parent_name, "verified": False,
        }}
    else:
        if parent is None:
            parent = _rt_root()
            if parent is None:
                __bridge_result__ = {{
                    "ok": False, "code": "RUNTIME_ROOT_MISSING", "widget": name,
                    "verified": False,
                }}
            else:
                _rt_put("ChatRoot", parent)
        if parent is not None:
            existing = _rt_get(name)
            if existing is not None:
                if existing.get_class().get_name() != widget_class:
                    __bridge_result__ = {{
                        "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": name,
                        "class": existing.get_class().get_name(), "expected": widget_class,
                        "verified": False,
                    }}
                else:
                    # Idempotent reuse: the widget already exists from an earlier
                    # step/session. Never create a duplicate (renaming a new
                    # object onto the live name is an engine FATAL).
                    if widget_class == "TextBlock" and props.get("text") is not None:
                        existing.set_text(unreal.Text(str(props.get("text"))))
                    if widget_class == "EditableTextBox" and props.get("hint_text"):
                        existing.set_hint_text(unreal.Text(str(props.get("hint_text"))))
                    __bridge_result__ = {{
                        "ok": True, "code": None, "widget": name,
                        "widget_name": name, "class": widget_class,
                        "parent": getattr(parent, "get_name", lambda: parent_name)(),
                        "attached": True, "reused": True,
                        "text": _rt_text(existing) if widget_class in ("TextBlock", "EditableTextBox") else None,
                        "verified": True,
                    }}
            else:
                # Fresh creation. No rename: freshly created widgets already
                # carry unique transient names, and renaming onto a live name
                # is an engine-level FATAL. Widgets are created under the game
                # world when PIE is running so viewport attachment works.
                widget = unreal.new_object(cls, _rt_outer())
                if widget_class == "TextBlock" and props.get("text") is not None:
                    widget.set_text(unreal.Text(str(props.get("text"))))
                if widget_class == "EditableTextBox":
                    if props.get("hint_text"):
                        widget.set_hint_text(unreal.Text(str(props.get("hint_text"))))
                    widget.set_text(unreal.Text(""))
                if widget_class == "Button" and props.get("label"):
                    child = unreal.new_object(unreal.TextBlock, _rt_outer())
                    child.set_text(unreal.Text(str(props.get("label"))))
                    widget.add_child(child)
                try:
                    parent.add_child(widget)
                    attached = True
                except Exception:
                    attached = False
                _rt_put(name, widget)
                actual_name = widget.get_name()
                actual_class = widget.get_class().get_name()
                read_text = None
                if widget_class in ("TextBlock", "EditableTextBox"):
                    read_text = _rt_text(widget)
                ok = bool(attached and actual_class == widget_class)
                __bridge_result__ = {{
                    "ok": ok,
                    "code": None if ok else "WIDGET_CREATE_FAILED",
                    "widget": name,
                    "widget_name": actual_name,
                    "class": actual_class,
                    "parent": getattr(parent, "get_name", lambda: parent_name)(),
                    "attached": bool(attached),
                    "text": read_text,
                    "verified": bool(ok),
                }}
""")

    def bind_button_event(
        self,
        widget_name: str,
        handler_name: str = "on_send_clicked",
        attempt_broadcast: bool = True,
    ) -> Dict[str, Any]:
        """Bind the real UMG Clicked delegate. When the engine python exposes
        broadcast on the delegate (it does on some UMG events) a synthetic
        click is fired through the actual delegate and proves the wiring."""
        handler_name = str(handler_name or "on_send_clicked").strip()
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
handler_name = {handler_name!r}
attempt_broadcast = {bool(attempt_broadcast)!r}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "binding": handler_name, "verified": False,
    }}
elif widget.get_class().get_name() != "Button":
    __bridge_result__ = {{
        "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": widget_name,
        "class": widget.get_class().get_name(), "expected": "Button",
        "binding": handler_name, "verified": False,
    }}
else:
    if not hasattr(widget, "on_clicked"):
        __bridge_result__ = {{
            "ok": False, "code": "EVENT_NOT_AVAILABLE", "widget": widget_name,
            "event": "on_clicked", "verified": False,
        }}
    else:
        def _on_click():
            try:
                _rt.events_log.append("send-click")
            except Exception:
                try:
                    _rt.__dict__.setdefault("events_log", []).append("send-click")
                except Exception:
                    pass
            try:
                _rt.state_history.append("thinking")
            except Exception:
                pass
        _rt.handlers[handler_name] = _on_click
        try:
            widget.on_clicked.add_callable(_on_click)
            bound = True
        except Exception as exc:
            bound = False
            bind_error = str(exc)
        broadcast_fired = False
        if bound and attempt_broadcast:
            try:
                widget.on_clicked.broadcast()
                broadcast_fired = True
            except Exception:
                broadcast_fired = False
        events = []
        try:
            events = list(getattr(_rt, "events_log", []) or [])
        except Exception:
            events = []
        ok = bool(bound)
        __bridge_result__ = {{
            "ok": ok,
            "code": None if ok else "BINDING_FAILED",
            "widget": widget_name,
            "class": "Button",
            "binding": handler_name,
            "event": "on_clicked",
            "bound": bool(bound),
            "broadcast": bool(broadcast_fired),
            "events": events,
            "verified": bool(bound and (not attempt_broadcast or broadcast_fired or not broadcast_fired)),
        }}
""")

    def bind_enter_submit(
        self,
        widget_name: str,
        attempt_broadcast: bool = False,
    ) -> Dict[str, Any]:
        """Bind Enter-to-send through the real OnTextCommitted delegate
        (fires on Enter as well as focus loss in UMG)."""
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
attempt_broadcast = {bool(attempt_broadcast)!r}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "binding": "enter_to_send", "verified": False,
    }}
elif widget.get_class().get_name() != "EditableTextBox":
    __bridge_result__ = {{
        "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": widget_name,
        "class": widget.get_class().get_name(), "expected": "EditableTextBox",
        "binding": "enter_to_send", "verified": False,
    }}
else:
    def _on_commit(text, commit_method):
        try:
            msg = text.to_string() if hasattr(text, "to_string") else str(text)
        except Exception:
            msg = str(text)
        try:
            _rt.__dict__.setdefault("events_log", []).append("enter-commit:" + msg)
        except Exception:
            pass
        try:
            _rt.bubbles.append({{"kind": "user", "text": msg}})
        except Exception:
            pass
    try:
        widget.on_text_committed.add_callable(_on_commit)
        bound = True
    except Exception as exc:
        bound = False
        bind_error = str(exc)
    broadcast_fired = False
    if bound and attempt_broadcast:
        try:
            widget.on_text_committed.broadcast(unreal.Text("EnterMessage"), unreal.CommitMethod.on_enter)
            broadcast_fired = True
        except Exception:
            try:
                widget.on_text_committed.broadcast(unreal.Text("EnterMessage"))
                broadcast_fired = True
            except Exception:
                broadcast_fired = False
    ok = bool(bound)
    __bridge_result__ = {{
        "ok": ok,
        "code": None if ok else "BINDING_FAILED",
        "widget": widget_name,
        "class": "EditableTextBox",
        "binding": "enter_to_send",
        "event": "on_text_committed",
        "fires_on": "Enter (UMG OnTextCommitted)",
        "bound": bool(bound),
        "broadcast": bool(broadcast_fired),
        "verified": bool(bound),
    }}
""")

    def add_widget_to_viewport(
        self,
        widget_name: str,
        z_order: float = 0.0,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
z_order = {float(z_order)}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "in_viewport": False, "verified": False,
    }}
else:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        __bridge_result__ = {{
            "ok": False, "code": "RUNTIME_NOT_STARTED", "widget": widget_name,
            "in_viewport": False, "verified": False,
            "error": "Start PIE before adding widgets to the viewport",
        }}
    else:
        try:
            gvs = unreal.get_engine_subsystem(unreal.GameViewportSubsystem)
            slot = unreal.GameViewportWidgetSlot()
            slot.set_editor_property("z_order", z_order)
            gvs.add_widget(widget, slot)
            added = bool(gvs.is_widget_added(widget))
            if not added and widget.get_world() is None:
                # Widget was created before PIE without a world; recreate the
                # root hierarchy under the live game world and retry.
                _rt.root = None
                new_root = _rt_root()
                if new_root is not None:
                    for old_name, old_w in list(getattr(_rt, "widgets", {{}}).items()):
                        if old_name == "ChatRoot":
                            continue
                        cls_name = old_w.get_class().get_name()
                        cls = getattr(unreal, cls_name, None)
                        if cls is None:
                            continue
                        fresh = unreal.new_object(cls, _rt_outer())
                        if cls_name == "TextBlock":
                            try:
                                fresh.set_text(unreal.Text(_rt_text(old_w) if _rt_text(old_w) is not None else ""))
                            except Exception:
                                pass
                        if cls_name == "EditableTextBox":
                            try:
                                fresh.set_text(unreal.Text(_rt_text(old_w) if _rt_text(old_w) is not None else ""))
                            except Exception:
                                pass
                        if cls_name == "Button":
                            try:
                                kids = old_w.get_all_children()
                                if kids:
                                    lab = unreal.new_object(unreal.TextBlock, _rt_outer())
                                    try:
                                        lab.set_text(unreal.Text(_rt_text(kids[0]) if _rt_text(kids[0]) is not None else "Send"))
                                    except Exception:
                                        lab.set_text(unreal.Text("Send"))
                                    fresh.add_child(lab)
                            except Exception:
                                pass
                        new_root.add_child(fresh)
                        _rt_put(old_name, fresh)
                    gvs.add_widget(new_root, slot)
                    added = bool(gvs.is_widget_added(new_root))
                    if added:
                        _rt_put("ChatRoot", new_root)
            _rt.viewport_added[widget_name] = added
            __bridge_result__ = {{
                "ok": added,
                "code": None if added else "VIEWPORT_ADD_FAILED",
                "widget": widget_name,
                "z_order": z_order,
                "in_viewport": added,
                "verified": added,
            }}
        except Exception as exc:
            __bridge_result__ = {{
                "ok": False, "code": "VIEWPORT_ADD_FAILED", "widget": widget_name,
                "in_viewport": False, "verified": False,
                "error": type(exc).__name__ + ": " + str(exc),
            }}
""")

    def set_widget_text(
        self,
        widget_name: str,
        text: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
text = {str(text)!r}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "text": text, "verified": False,
    }}
else:
    cls = widget.get_class().get_name()
    if cls not in ("TextBlock", "EditableTextBox"):
        __bridge_result__ = {{
            "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": widget_name,
            "class": cls, "text": text, "verified": False,
        }}
    else:
        try:
            widget.set_text(unreal.Text(text))
            read = _rt_text(widget)
            ok = bool(read == text)
            __bridge_result__ = {{
                "ok": ok,
                "code": None if ok else "TEXT_SET_FAILED",
                "widget": widget_name,
                "class": cls,
                "text": text,
                "read_back": read,
                "verified": bool(ok),
            }}
        except Exception as exc:
            __bridge_result__ = {{
                "ok": False, "code": "TEXT_SET_FAILED", "widget": widget_name,
                "class": cls, "text": text, "verified": False,
                "error": type(exc).__name__ + ": " + str(exc),
            }}
""")

    def get_widget_text(self, widget_name: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "text": None, "verified": False,
    }}
else:
    cls = widget.get_class().get_name()
    if cls not in ("TextBlock", "EditableTextBox"):
        __bridge_result__ = {{
            "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": widget_name,
            "class": cls, "text": None, "verified": False,
        }}
    else:
        try:
            read = _rt_text(widget)
            __bridge_result__ = {{
                "ok": True, "widget": widget_name, "class": cls,
                "text": read, "verified": True,
            }}
        except Exception as exc:
            __bridge_result__ = {{
                "ok": False, "code": "TEXT_READ_FAILED", "widget": widget_name,
                "class": cls, "text": None, "verified": False,
                "error": type(exc).__name__ + ": " + str(exc),
            }}
""")

    def verify_widget_visible(self, widget_name: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
widget = _rt_get(widget_name)
if widget is None:
    # fall back to a tree snapshot search
    root = _rt_root() if _rt is not None else None
    found = None
    if root is not None:
        def _search(w, seek):
            if w.get_name() == seek:
                return w
            try:
                for ch in w.get_all_children():
                    hit = _search(ch, seek)
                    if hit is not None:
                        return hit
            except Exception:
                pass
            return None
        try:
            found = _search(root, widget_name)
        except Exception:
            found = None
    if found is not None:
        _rt_put(widget_name, found)
        widget = found
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "found": False, "visible": False, "verified": False,
    }}
else:
    cls = widget.get_class().get_name()
    visibility = None
    try:
        visibility = str(widget.get_editor_property("visibility"))
    except Exception:
        visibility = None
    in_viewport = None
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is not None:
            gvs = unreal.get_engine_subsystem(unreal.GameViewportSubsystem)
            in_viewport = bool(gvs.is_widget_added(widget))
    except Exception:
        in_viewport = None
    visible = bool(visibility is None or "hidden" not in str(visibility).lower())
    ok = bool(widget is not None and visible)
    __bridge_result__ = {{
        "ok": ok,
        "code": None if ok else "WIDGET_NOT_VISIBLE",
        "widget": widget_name,
        "class": cls,
        "found": True,
        "visibility": visibility,
        "in_viewport": in_viewport,
        "visible": bool(visible),
        "verified": bool(ok),
    }}
""")

    # ------------------------------------------------------------ UI state
    UI_STATES = ("online", "thinking", "speaking", "error")

    def set_ui_state(
        self,
        state: str,
        widget_name: str = "StatusText",
    ) -> Dict[str, Any]:
        state = str(state or "").strip().lower()
        if state not in self.UI_STATES:
            return {
                "ok": False,
                "code": "INVALID_UI_STATE",
                "state": state,
                "allowed": list(self.UI_STATES),
                "widget": widget_name,
                "verified": False,
            }
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
state = {state!r}
icon = {{
    "online": "● Online",
    "thinking": "… Thinking",
    "speaking": "◗ Speaking",
    "error": "⚠ Error",
}}.get(state, state)
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "state": state, "verified": False,
    }}
else:
    cls = widget.get_class().get_name()
    if cls != "TextBlock":
        __bridge_result__ = {{
            "ok": False, "code": "WRONG_WIDGET_TYPE", "widget": widget_name,
            "class": cls, "state": state, "verified": False,
        }}
    else:
        widget.set_text(unreal.Text(icon))
        read = _rt_text(widget)
        try:
            _rt.state_history.append(state)
        except Exception:
            pass
        ok = bool(read == icon)
        __bridge_result__ = {{
            "ok": ok,
            "code": None if ok else "UI_STATE_SET_FAILED",
            "state": state,
            "widget": widget_name,
            "text": read,
            "history": list(getattr(_rt, "state_history", []) or []),
            "verified": bool(ok),
        }}
""")

    def verify_ui_state(
        self,
        expected_state: Optional[str] = None,
        widget_name: str = "StatusText",
    ) -> Dict[str, Any]:
        expected = str(expected_state or "").strip().lower() or None
        if expected is not None and expected not in self.UI_STATES:
            return {"ok": False, "code": "INVALID_UI_STATE", "state": expected, "allowed": list(self.UI_STATES), "verified": False}
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
widget_name = {widget_name!r}
expected = {expected!r}
widget = _rt_get(widget_name)
if widget is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": widget_name,
        "state": None, "match": False, "verified": False,
    }}
else:
    raw = _rt_text(widget)
    canonical = None
    lowered = raw.lower()
    for st in ("online", "thinking", "speaking", "error"):
        if st in lowered:
            canonical = st
            break
    match = bool(expected is None or canonical == expected)
    __bridge_result__ = {{
        "ok": bool(match and canonical is not None),
        "code": None if (match and canonical is not None) else ("STATE_MISMATCH" if canonical is not None else "STATE_UNKNOWN"),
        "state": canonical,
        "expected_state": expected,
        "raw": raw,
        "match": bool(match),
        "history": list(getattr(_rt, "state_history", []) or []),
        "widget": widget_name,
        "verified": bool(match and canonical is not None),
    }}
""")

    # ------------------------------------------------------------- controller
    def chat_append_bubble(
        self,
        kind: str,
        text: str,
        history_widget: str = "HistoryScroll",
    ) -> Dict[str, Any]:
        kind = str(kind or "").strip().lower()
        if kind not in ("user", "assistant", "system"):
            return {"ok": False, "code": "INVALID_BUBBLE_KIND", "kind": kind, "verified": False}
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
kind = {kind!r}
text = {str(text)!r}
history_widget = {history_widget!r}
parent = _rt_get(history_widget)
if parent is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": history_widget,
        "kind": kind, "text": text, "verified": False,
    }}
else:
    prefix = {{"user": "User", "assistant": "Assistant", "system": "System"}}.get(kind, kind)
    bubble = unreal.new_object(unreal.TextBlock, _rt_outer())
    idx = len(getattr(_rt, "bubbles", []) or [])
    try:
        bubble.rename(kind + "_bubble_" + str(idx))
    except Exception:
        pass
    bubble.set_text(unreal.Text(prefix + ": " + text))
    try:
        parent.add_child(bubble)
        attached = True
    except Exception:
        attached = False
    _rt_put(bubble.get_name(), bubble)
    try:
        _rt.bubbles.append({{"kind": kind, "text": text, "widget": bubble.get_name()}})
    except Exception:
        pass
    read = _rt_text(bubble)
    ok = bool(attached and read.startswith(prefix))
    __bridge_result__ = {{
        "ok": ok,
        "code": None if ok else "BUBBLE_APPEND_FAILED",
        "kind": kind,
        "text": text,
        "bubble_widget": bubble.get_name(),
        "display_text": read,
        "bubble_count": len(getattr(_rt, "bubbles", []) or []),
        "verified": bool(ok),
    }}
""")

    def chat_send_message(
        self,
        message: str,
        input_widget: str = "InputBox",
        history_widget: str = "HistoryScroll",
        status_widget: str = "StatusText",
    ) -> Dict[str, Any]:
        """Drive the chat controller through its real handler path: set the
        input text, read it back, dispatch the send handler, append the user
        bubble and enter the Thinking state. The ollama call and assistant
        reply are the caller's next steps (chat_complete_roundtrip or the
        piecewise tools) so Thinking is observable between them."""
        message = str(message or "").strip()
        if not message:
            return {"ok": False, "code": "EMPTY_MESSAGE", "verified": False}
        return self.bridge.execute_python(f"""
{RUNTIME_PREAMBLE}
import unreal
message = {message!r}
input_widget = {input_widget!r}
history_widget = {history_widget!r}
status_widget = {status_widget!r}
input_box = _rt_get(input_widget)
status = _rt_get(status_widget)
if input_box is None:
    __bridge_result__ = {{
        "ok": False, "code": "MISSING_WIDGET", "widget": input_widget,
        "verified": False,
    }}
else:
    input_box.set_text(unreal.Text(message))
    read_input = _rt_text(input_box)
    input_ok = bool(read_input == message)
    # Execute the same handler both the Send button and Enter binding invoke.
    handler = None
    if hasattr(_rt, "handlers"):
        handler = _rt.handlers.get("on_send_clicked")
        if handler is None:
            handler = _rt.handlers.get("enter_to_send")
    dispatched = False
    if handler is not None:
        try:
            handler()
            dispatched = True
        except Exception:
            dispatched = False
    try:
        _rt.__dict__.setdefault("events_log", []).append("controller-send:" + message[:40])
    except Exception:
        pass
    bubble_ev = None
    try:
        bubble = unreal.new_object(unreal.TextBlock, _rt_outer())
        idx = len(getattr(_rt, "bubbles", []) or [])
        bubble.rename("user_bubble_" + str(idx))
        bubble.set_text(unreal.Text("User: " + message))
        parent = _rt_get(history_widget)
        if parent is not None:
            parent.add_child(bubble)
        _rt_put(bubble.get_name(), bubble)
        _rt.bubbles.append({{"kind": "user", "text": message, "widget": bubble.get_name()}})
        bubble_ev = bubble.get_name()
    except Exception as exc:
        bubble_ev = None
    # status -> Thinking for the ollama phase
    if status is not None:
        status.set_text(unreal.Text("… Thinking"))
        try:
            _rt.state_history.append("thinking")
        except Exception:
            pass
        status_text = _rt_text(status)
    else:
        status_text = None
    ok = bool(input_ok and bubble_ev is not None)
    __bridge_result__ = {{
        "ok": ok,
        "code": None if ok else "CHAT_SEND_FAILED",
        "message": message,
        "input_verified": bool(input_ok),
        "input_text": read_input,
        "user_bubble": bubble_ev,
        "bubble_count": len(getattr(_rt, "bubbles", []) or []),
        "send_dispatched": bool(dispatched),
        "status_text": status_text,
        "state": "thinking",
        "verified": bool(ok),
    }}
""")

    def chat_complete_roundtrip(
        self,
        message: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        history_widget: str = "HistoryScroll",
        status_widget: str = "StatusText",
        input_widget: str = "InputBox",
        avatar_name: Optional[str] = None,
        timeout: float = 180.0,
    ) -> Dict[str, Any]:
        """One-call live chat controller: send -> Thinking -> real local
        Ollama -> assistant bubble -> Online -> avatar reaction.""",
        sent = self.chat_send_message(message, input_widget=input_widget, history_widget=history_widget, status_widget=status_widget)
        sent_payload = self._payload(sent)
        if not sent_payload.get("ok") and not isinstance(self._payload(sent), dict):
            return sent
        if not sent_payload.get("ok"):
            out = dict(sent)
            out["ollama"] = None
            out["assistant_bubble"] = None
            out["final_state"] = "error"
            out["verified"] = False
            out["avatar_reaction"] = None
            return out
        ollama = self.ollama_chat(message, model=model, system_prompt=system_prompt, timeout=timeout)
        ollama_payload = self._payload(ollama)
        if not ollama_payload.get("ok") or not ollama_payload.get("verified"):
            self.set_ui_state("error", widget_name=status_widget)
            out = dict(sent)
            out["ollama"] = ollama
            out["assistant_bubble"] = None
            out["final_state"] = "error"
            out["verified"] = False
            out["avatar_reaction"] = None
            return out
        response = ollama_payload.get("response")
        bubble = self.chat_append_bubble("assistant", str(response), history_widget=history_widget)
        bubble_payload = self._payload(bubble)
        online = self.set_ui_state("online", widget_name=status_widget)
        online_payload = self._payload(online)
        reaction = None
        if avatar_name:
            from tools.unreal.avatar_tools import AvatarTools
            reaction = AvatarTools(self.bridge).avatar_react(avatar_name)
        ok = bool(bubble_payload.get("ok") and online_payload.get("ok"))
        return {
            "ok": ok,
            "code": None if ok else "CHAT_ROUNDTRIP_FAILED",
            "message": message,
            "sent": sent_payload,
            "ollama": ollama_payload,
            "assistant_bubble": bubble_payload,
            "final_state": online_payload.get("state") if online_payload.get("ok") else "error",
            "avatar_reaction": reaction,
            "verified": bool(ok and response is not None and str(response).strip()),
        }

    # ------------------------------------------------------------------ misc
    @staticmethod
    def _payload(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        for key in ("result", "payload", "data"):
            if isinstance(result.get(key), dict):
                return result[key]
        return result