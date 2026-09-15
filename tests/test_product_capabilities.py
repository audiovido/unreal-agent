"""Deterministic tests for the generic product capabilities added to Unreal
Agent: avatar toolchain, UMG/chat toolchain, ollama_chat, UI state, runtime
validation, reopen verification, acceptance-contract mapping and the generic
product milestone planner.

All tests are offline: bridge calls are mocked the same way the existing
suite does (test_blueprint_compile style), and Ollama HTTP is mocked at the
requests layer. No test depends on a live editor.
"""
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import task_goal
from core.tool_registry import build_registry, validate_args
from tools.unreal.avatar_tools import AvatarTools
from tools.unreal.chat_tools import ChatTools
from tools.unreal.runtime_tools import RuntimeTools
from tools.unreal.unreal_bridge import UnrealBridge
import tools.unreal.chat_tools as chat_tools_module
import tools.unreal.avatar_tools as avatar_tools_module
from app import api


class FakeBridge:
    def __init__(self, response=None):
        self.response = response or {"ok": True, "result": {"ok": True}}
        self.calls = []

    def execute_python(self, code):
        self.calls.append(code)
        return self.response


def ok_payload(payload):
    return {"ok": True, "result": payload}


ALL_NEW_TOOLS = [
    "discover_character_assets", "inspect_character_asset", "install_character_assets",
    "spawn_character", "set_character_transform", "assign_animation",
    "verify_character_visible", "avatar_react",
    "ollama_chat", "create_widget_blueprint", "add_text_widget", "add_scroll_box",
    "add_editable_text_box", "add_button", "bind_button_event", "bind_enter_submit",
    "add_widget_to_viewport", "set_widget_text", "get_widget_text",
    "verify_widget_visible", "set_ui_state", "verify_ui_state", "chat_append_bubble",
    "chat_send_message", "chat_complete_roundtrip", "runtime_status",
    "runtime_widget_verify", "runtime_actor_verify", "verify_reopen_state",
]


@pytest.fixture(scope="module")
def registry():
    import tools.unreal.project_manager as pm
    return build_registry(
        pm.discover_projects, pm.inspect_project, pm.open_project, pm.create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=UnrealBridge(),
    )


@pytest.fixture()
def isolated_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")
    return tmp_path / "task_goal.json"


def long_request():
    return (
        "Build the AI assistant experience with avatar, chat UI, text input, Send, "
        "Enter-to-send, real local Ollama response, Thinking/Online state, animation, "
        "runtime verification, reopen verification, and final screenshot."
    )


# ===================================================================== registry
class TestRegistry:
    def test_all_product_tools_registered(self, registry):
        missing = [n for n in ALL_NEW_TOOLS if n not in registry]
        assert missing == []

    def test_argument_validation_valid_and_unknown(self, registry):
        spec = registry["spawn_character"]
        valid, err = validate_args(spec, {"actor_name": "X", "location": [0, 0, 0]})
        assert valid and not err
        valid, err = validate_args(spec, {"bogus": 1})
        assert not valid and "bogus" in err
        valid, err = validate_args(registry["ollama_chat"], {"prompt": "hi"})
        assert valid and not err
        valid, err = validate_args(registry["ollama_chat"], {})
        assert not valid and "prompt" in err

    def test_missing_required_arguments_rejected(self, registry):
        for tool, required in [
            ("inspect_character_asset", "asset_path"),
            ("set_character_transform", "actor_name"),
            ("verify_character_visible", "actor_name"),
            ("add_text_widget", "name"),
            ("bind_button_event", "widget_name"),
            ("bind_enter_submit", "widget_name"),
            ("set_widget_text", "widget_name"),
            ("set_ui_state", "state"),
            ("chat_send_message", "message"),
            ("runtime_widget_verify", "widget_name"),
            ("runtime_actor_verify", "actor_name"),
        ]:
            valid, err = validate_args(registry[tool], {})
            assert not valid, tool
            assert required in err, tool


# ==================================================================== ollama
class TestOllamaChat:
    def test_success_returns_verified_real_response(self, monkeypatch):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "Yes! The live Unreal chat is working."}}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

        monkeypatch.setattr(chat_tools_module.requests, "post", fake_post)
        chat = ChatTools(FakeBridge())
        out = chat.ollama_chat("Hello Ava", model="qwen2.5:7b", timeout=30)
        assert out["ok"] is True
        assert out["verified"] is True
        assert out["local_only"] is True
        assert out["response"].startswith("Yes!")
        assert out["latency_ms"] is not None
        assert captured["url"].endswith("/api/chat")
        assert captured["body"]["model"] == "qwen2.5:7b"

    def test_connection_error_no_fake_response(self, monkeypatch):
        def boom(*a, **k):
            raise chat_tools_module.requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(chat_tools_module.requests, "post", boom)
        out = ChatTools(FakeBridge()).ollama_chat("Hi", model="m", timeout=5)
        assert out["ok"] is False
        assert out["code"] == "OLLAMA_UNREACHABLE"
        assert out["response"] is None
        assert out["verified"] is False

    def test_timeout_is_structured(self, monkeypatch):
        def boom(*a, **k):
            raise chat_tools_module.requests.exceptions.Timeout("slow")

        monkeypatch.setattr(chat_tools_module.requests, "post", boom)
        out = ChatTools(FakeBridge()).ollama_chat("Hi", model="m", timeout=5)
        assert out["code"] == "OLLAMA_TIMEOUT"
        assert out["verified"] is False

    def test_empty_response_is_not_success(self, monkeypatch):
        class EmptyResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "   "}}

        monkeypatch.setattr(chat_tools_module.requests, "post", lambda *a, **k: EmptyResp())
        out = ChatTools(FakeBridge()).ollama_chat("Hi", model="m")
        assert out["ok"] is False
        assert out["code"] == "EMPTY_OLLAMA_RESPONSE"
        assert out["verified"] is False

    def test_empty_prompt_rejected_before_http(self, monkeypatch):
        out = ChatTools(FakeBridge()).ollama_chat("   ", model="m")
        assert out["code"] == "EMPTY_PROMPT"
        assert out["verified"] is False

    def test_missing_model_is_structured(self, monkeypatch):
        monkeypatch.setattr(ChatTools, "_first_available_model", lambda self, url, timeout: None)
        out = ChatTools(FakeBridge()).ollama_chat("Hi")
        assert out["code"] == "NO_MODEL"
        assert out["verified"] is False


# ==================================================================== avatar
class TestAvatarTools:
    def test_spawn_character_success_evidence(self):
        bridge = FakeBridge(ok_payload({
            "ok": True, "asset": "/Game/Mannequin/Character/Mesh/SK_Mannequin_Female",
            "mesh": "/Game/Mannequin/Character/Mesh/SK_Mannequin_Female",
            "class": "SkeletalMeshActor", "actor_label": "UA_Avatar",
            "actor_name": "UA_Avatar", "location": [0, 0, 100], "visible": True,
            "verified": True, "mesh_on_component": True, "animation": None,
        }))
        out = AvatarTools(bridge).spawn_character(
            actor_name="UA_Avatar", mesh_asset="/Game/Mannequin/Character/Mesh/SK_Mannequin_Female",
        )
        payload = out["result"]
        assert payload["verified"] is True
        assert payload["class"] == "SkeletalMeshActor"
        assert payload["actor_label"] == "UA_Avatar"
        assert payload["mesh"] == "/Game/Mannequin/Character/Mesh/SK_Mannequin_Female"

    def test_spawn_character_mesh_not_found_structured(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "MESH_NOT_FOUND",
                                        "mesh": "/Game/Nope", "class": None,
                                        "actor_label": "UA_Avatar", "visible": False,
                                        "verified": False}))
        out = AvatarTools(bridge).spawn_character(actor_name="UA_Avatar", mesh_asset="/Game/Nope")
        assert out["result"]["code"] == "MESH_NOT_FOUND"
        assert out["result"]["verified"] is False

    def test_spawn_character_wrong_asset_type(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "WRONG_ASSET_TYPE",
                                        "mesh": "/Game/Cube", "class": "StaticMesh",
                                        "actor_label": "UA_Avatar", "visible": False,
                                        "verified": False}))
        out = AvatarTools(bridge).spawn_character(actor_name="UA_Avatar", mesh_asset="/Game/Cube")
        assert out["result"]["code"] == "WRONG_ASSET_TYPE"
        assert out["result"]["class"] == "StaticMesh"

    def test_spawn_character_no_mesh_anywhere(self, monkeypatch):
        monkeypatch.setattr(AvatarTools, "discover_character_assets", lambda self: {"ok": True, "result": {"found": [], "best": None, "verified": False}})
        monkeypatch.setattr(AvatarTools, "install_character_assets", lambda self, **k: {"ok": False, "code": "CHARACTER_INSTALL_VERIFY_FAILED", "mesh": None, "verified": False})
        out = AvatarTools(FakeBridge()).spawn_character(actor_name="A")
        assert out.get("code") == "NO_CHARACTER_MESH"
        assert out.get("verified") is False

    def test_inspect_character_asset_invalid_path(self):
        out = AvatarTools(FakeBridge()).inspect_character_asset("NotAnAssetPath")
        assert out["code"] == "INVALID_ASSET_PATH"

    def test_inspect_character_asset_wrong_type_preserved(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "WRONG_ASSET_TYPE",
                                        "asset": "/Game/Thing", "class": "World",
                                        "verified": False}))
        out = AvatarTools(bridge).inspect_character_asset("/Game/Thing")
        assert out["result"]["code"] == "WRONG_ASSET_TYPE"
        assert out["result"]["class"] == "World"

    def test_install_character_assets_verify_failure_is_honest(self, monkeypatch, tmp_path):
        project = tmp_path / "Project"
        project.mkdir()
        engine = tmp_path / "Engine"
        template = engine.joinpath(*avatar_tools_module.MANNEQUIN_TEMPLATE_REL)
        (template / "Character" / "Mesh").mkdir(parents=True)
        (template / "Character" / "Mesh" / "SK_Mannequin_Female.uasset").write_bytes(b"x")
        (template / "Animations").mkdir(parents=True)
        (template / "Animations" / "ThirdPersonIdle.uasset").write_bytes(b"z")
        monkeypatch.setattr(avatar_tools_module, "_active_project_root", lambda bridge: project)
        monkeypatch.setattr(avatar_tools_module, "_engine_root", lambda: engine)
        bridge = FakeBridge(ok_payload({"verified": False, "counts": {}, "error": "Copied package did not verify"}))
        out = AvatarTools(bridge).install_character_assets()
        payload = out["result"]
        assert payload["ok"] is False
        assert payload["code"] == "CHARACTER_INSTALL_VERIFY_FAILED"
        assert payload["verified"] is False
        # the copy itself happened
        assert (project / "Content" / "Mannequin" / "Character" / "Mesh").exists()

    def test_install_character_assets_verified(self, monkeypatch, tmp_path):
        project = tmp_path / "P"
        project.mkdir()
        engine = tmp_path / "E"
        template = engine.joinpath(*avatar_tools_module.MANNEQUIN_TEMPLATE_REL)
        (template / "Character" / "Mesh").mkdir(parents=True)
        (template / "Character" / "Mesh" / "SK_Mannequin_Female.uasset").write_bytes(b"x")
        (template / "Character" / "Mesh" / "UE4_Mannequin_Skeleton.uasset").write_bytes(b"y")
        (template / "Animations").mkdir(parents=True)
        (template / "Animations" / "ThirdPersonIdle.uasset").write_bytes(b"z")
        monkeypatch.setattr(avatar_tools_module, "_active_project_root", lambda bridge: project)
        monkeypatch.setattr(avatar_tools_module, "_engine_root", lambda: engine)
        bridge = FakeBridge(ok_payload({
            "verified": True,
            "counts": {"SkeletalMesh": 1, "Skeleton": 1, "AnimSequence": 1},
            "assets": [{"path": "/Game/Mannequin/Character/Mesh/SK_Mannequin_Female", "class": "SkeletalMesh"}],
            "mesh": "/Game/Mannequin/Character/Mesh/SK_Mannequin_Female",
            "skeleton": "/Game/Mannequin/Character/Mesh/UE4_Mannequin_Skeleton",
            "animations": ["/Game/Mannequin/Animations/ThirdPersonIdle"],
            "error": None,
        }))
        out = AvatarTools(bridge).install_character_assets()
        assert out["result"]["ok"] is True
        assert out["result"]["mesh"].endswith("SK_Mannequin_Female")

    def test_assign_animation_passthrough(self):
        bridge = FakeBridge(ok_payload({"ok": True, "actor_label": "A", "animation": "/Game/Anims/Idle",
                                        "verified": True, "skeleton_compatible": True}))
        out = AvatarTools(bridge).assign_animation("A", animation_asset="/Game/Anims/Idle")
        assert out["result"]["verified"] is True

    def test_verify_character_visible_passthrough(self):
        bridge = FakeBridge(ok_payload({"ok": True, "actor_label": "A", "mesh": "/Game/Mesh",
                                        "visible": True, "verified": True, "class": "SkeletalMeshActor",
                                        "location": [0, 0, 0], "animation": None}))
        out = AvatarTools(bridge).verify_character_visible("A")
        assert out["result"]["verified"] is True


# ====================================================================== UMG
class TestChatToolsWidgets:
    def test_add_text_widget_verified(self):
        bridge = FakeBridge(ok_payload({"ok": True, "widget": "TitleText", "widget_name": "TitleText",
                                        "class": "TextBlock", "parent": "ChatRoot", "attached": True,
                                        "text": "AI Assistant", "verified": True}))
        out = ChatTools(bridge).add_text_widget("TitleText", text="AI Assistant")
        assert out["result"]["verified"] is True
        assert out["result"]["class"] == "TextBlock"

    def test_add_widget_unsupported_class(self):
        out = ChatTools(FakeBridge())._add_widget("NotAWidget", "X", {}, None)
        assert out["code"] == "UNSUPPORTED_WIDGET_CLASS"

    def test_add_widget_missing_name(self):
        out = ChatTools(FakeBridge())._add_widget("TextBlock", "", {}, None)
        assert out["code"] == "MISSING_WIDGET_NAME"

    def test_add_editable_text_box_passthrough(self):
        bridge = FakeBridge(ok_payload({"ok": True, "widget": "InputBox", "class": "EditableTextBox",
                                        "attached": True, "verified": True}))
        out = ChatTools(bridge).add_editable_text_box("InputBox", hint_text="Type...")
        assert out["result"]["verified"] is True

    def test_bind_button_event_wrong_type(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "WRONG_WIDGET_TYPE", "widget": "InputBox",
                                        "class": "EditableTextBox", "expected": "Button", "verified": False}))
        out = ChatTools(bridge).bind_button_event("InputBox")
        assert out["result"]["code"] == "WRONG_WIDGET_TYPE"

    def test_bind_enter_submit_binding_failure_structured(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "BINDING_FAILED", "widget": "InputBox",
                                        "bound": False, "verified": False}))
        out = ChatTools(bridge).bind_enter_submit("InputBox")
        assert out["result"]["bound"] is False
        assert out["result"]["verified"] is False

    def test_add_widget_to_viewport_requires_runtime(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "RUNTIME_NOT_STARTED", "widget": "ChatRoot",
                                        "in_viewport": False, "verified": False}))
        out = ChatTools(bridge).add_widget_to_viewport("ChatRoot")
        assert out["result"]["code"] == "RUNTIME_NOT_STARTED"

    def test_add_widget_to_viewport_in_viewport(self):
        bridge = FakeBridge(ok_payload({"ok": True, "widget": "ChatRoot", "in_viewport": True, "verified": True}))
        out = ChatTools(bridge).add_widget_to_viewport("ChatRoot")
        assert out["result"]["in_viewport"] is True
        assert out["result"]["verified"] is True

    def test_set_get_widget_text_mismatch_not_verified(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "TEXT_SET_FAILED", "widget": "T",
                                        "text": "A", "read_back": "B", "verified": False}))
        out = ChatTools(bridge).set_widget_text("T", "A")
        assert out["result"]["verified"] is False

    def test_verify_widget_visible_missing(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "MISSING_WIDGET", "widget": "Ghost",
                                        "found": False, "visible": False, "verified": False}))
        out = ChatTools(bridge).verify_widget_visible("Ghost")
        assert out["result"]["found"] is False
        assert out["result"]["verified"] is False


# ================================================================== UI state
class TestUiState:
    def test_invalid_state_rejected(self):
        out = ChatTools(FakeBridge()).set_ui_state("paused")
        assert out["code"] == "INVALID_UI_STATE"
        assert "allowed" in out

    def test_verify_invalid_state_rejected(self):
        out = ChatTools(FakeBridge()).verify_ui_state(expected_state="paused")
        assert out["code"] == "INVALID_UI_STATE"

    def test_set_state_verified(self):
        bridge = FakeBridge(ok_payload({"ok": True, "state": "thinking", "widget": "StatusText",
                                        "text": "… Thinking", "history": ["online", "thinking"],
                                        "verified": True}))
        out = ChatTools(bridge).set_ui_state("thinking")
        assert out["result"]["state"] == "thinking"
        assert out["result"]["verified"] is True

    def test_verify_state_mismatch(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "STATE_MISMATCH", "state": "thinking",
                                        "expected_state": "online", "match": False, "verified": False}))
        out = ChatTools(bridge).verify_ui_state(expected_state="online")
        assert out["result"]["code"] == "STATE_MISMATCH"
        assert out["result"]["verified"] is False


# ============================================================= chat controller
class TestChatController:
    def test_empty_message_rejected(self):
        out = ChatTools(FakeBridge()).chat_send_message("   ")
        assert out["code"] == "EMPTY_MESSAGE"

    def test_chat_send_verified(self):
        bridge = FakeBridge(ok_payload({"ok": True, "message": "Hello", "input_verified": True,
                                        "input_text": "Hello", "user_bubble": "user_bubble_0",
                                        "bubble_count": 1, "send_dispatched": True,
                                        "status_text": "… Thinking", "state": "thinking", "verified": True}))
        out = ChatTools(bridge).chat_send_message("Hello")
        assert out["result"]["input_verified"] is True
        assert out["result"]["state"] == "thinking"

    def test_chat_append_bubble_invalid_kind(self):
        out = ChatTools(FakeBridge()).chat_append_bubble("robot", "hi")
        assert out["code"] == "INVALID_BUBBLE_KIND"

    def test_complete_roundtrip_verified(self, monkeypatch):
        chat = ChatTools(FakeBridge())
        monkeypatch.setattr(chat, "chat_send_message", lambda *a, **k: ok_payload({
            "ok": True, "verified": True, "input_verified": True, "state": "thinking"}))
        monkeypatch.setattr(chat, "ollama_chat", lambda *a, **k: ok_payload({
            "ok": True, "verified": True, "response": "The live Unreal chat is working.",
            "model": "m", "local_only": True}))
        monkeypatch.setattr(chat, "chat_append_bubble", lambda *a, **k: ok_payload({"ok": True, "verified": True}))
        monkeypatch.setattr(chat, "set_ui_state", lambda *a, **k: ok_payload({"ok": True, "verified": True, "state": "online"}))
        monkeypatch.setattr(avatar_tools_module.AvatarTools, "avatar_react", lambda self, *a, **k: ok_payload({"ok": True, "verified": True, "moved": True}))
        out = chat.chat_complete_roundtrip("Hello", avatar_name="UA_Avatar")
        assert out["verified"] is True
        assert out["final_state"] == "online"
        assert out["avatar_reaction"]["result"]["moved"] is True

    def test_complete_roundtrip_ollama_failure_is_error(self, monkeypatch):
        chat = ChatTools(FakeBridge())
        monkeypatch.setattr(chat, "chat_send_message", lambda *a, **k: ok_payload({
            "ok": True, "verified": True, "input_verified": True, "state": "thinking"}))
        monkeypatch.setattr(chat, "ollama_chat", lambda *a, **k: ok_payload({
            "ok": False, "verified": False, "code": "OLLAMA_UNREACHABLE", "response": None}))
        monkeypatch.setattr(chat, "set_ui_state", lambda *a, **k: ok_payload({"ok": True, "verified": True, "state": "error"}))
        out = chat.chat_complete_roundtrip("Hello")
        assert out["verified"] is False
        assert out["final_state"] == "error"
        assert out["ollama"]["result"]["code"] == "OLLAMA_UNREACHABLE"

    def test_runtime_widget_verify_not_playing(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "RUNTIME_NOT_STARTED", "widget": "T",
                                        "is_playing": False, "found": False, "verified": False}))
        out = RuntimeTools(bridge).runtime_widget_verify("T")
        assert out["result"]["code"] == "RUNTIME_NOT_STARTED"
        assert out["result"]["verified"] is False

    def test_runtime_status_playing(self):
        bridge = FakeBridge(ok_payload({"ok": True, "is_playing": True, "world_name": "UEDPIE_0_X",
                                        "world_path": "/Game/Maps/UEDPIE_0_X.X"}))
        out = RuntimeTools(bridge).runtime_status()
        assert out["result"]["is_playing"] is True

    def test_verify_reopen_state_mismatch(self):
        bridge = FakeBridge(ok_payload({"ok": False, "code": "REOPEN_STATE_MISMATCH",
                                        "active_map": "/Game/Maps/Other.Other",
                                        "startup_map": "/Game/Maps/Other", "verified": False,
                                        "checks": {"project_identity_ok": True, "active_map_ok": False, "startup_map_ok": True}}))
        out = RuntimeTools(bridge).verify_reopen_state(expected_map="/Game/Maps/AvaLive_Main")
        assert out["result"]["verified"] is False
        assert out["result"]["code"] == "REOPEN_STATE_MISMATCH"


# ====================================================== acceptance mapping
class TestAcceptanceMapping:
    def _goal(self, isolated_goal):
        goal = task_goal.build_acceptance_contract(long_request())
        task_goal.save_task_goal(goal)
        return goal

    def test_avatar_cleared_only_by_verified_spawn(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_character", "parameters": {"actor_name": "UA_Avatar"}},
                                        ok_payload({"ok": True, "verified": True, "mesh": "/Game/Mesh", "mesh_on_component": True}))
        assert "deliverable:avatar" in goal["completed_criteria"]

    def test_avatar_pending_when_evidence_missing(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_character", "parameters": {"actor_name": "UA_Avatar"}},
                                        ok_payload({"ok": True, "verified": False, "mesh": None}))
        assert "deliverable:avatar" not in goal["completed_criteria"]
        assert "deliverable:avatar" in goal["pending_criteria"]

    def test_avatar_cleared_by_readback(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "verify_character_visible", "parameters": {"actor_name": "A"}},
                                        ok_payload({"ok": True, "verified": True, "mesh": "/Game/M", "visible": True, "class": "SkeletalMeshActor"}))
        assert "deliverable:avatar" in goal["completed_criteria"]

    def test_animation_cleared_by_assign_and_reaction(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "assign_animation", "parameters": {"actor_name": "A"}},
                                        ok_payload({"ok": True, "verified": True, "animation": "/Game/Anims/Idle"}))
        assert "deliverable:animation" in goal["completed_criteria"]
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "avatar_react", "parameters": {"actor_name": "A"}},
                                        ok_payload({"ok": True, "verified": True, "moved": True}))
        assert "deliverable:animation" in goal["completed_criteria"]

    def test_animation_not_cleared_by_asset_existence(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "discover_character_assets"},
                                        ok_payload({"ok": True, "found": [{"path": "/Game/Idle", "class": "AnimSequence"}], "verified": True}))
        assert "deliverable:animation" not in goal["completed_criteria"]

    def test_chat_ui_cleared_by_viewport_verified(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "add_widget_to_viewport", "parameters": {"widget_name": "ChatRoot"}},
                                        ok_payload({"ok": True, "verified": True, "in_viewport": True}))
        assert "deliverable:chat_ui" in goal["completed_criteria"]

    def test_chat_ui_pending_when_viewport_missing(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "add_widget_to_viewport", "parameters": {"widget_name": "ChatRoot"}},
                                        ok_payload({"ok": True, "verified": False, "in_viewport": False}))
        assert "deliverable:chat_ui" not in goal["completed_criteria"]

    def test_text_input_send_enter_mapping(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "add_editable_text_box", "parameters": {"name": "InputBox"}},
                                        ok_payload({"ok": True, "verified": True, "class": "EditableTextBox"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "bind_button_event", "parameters": {"widget_name": "SendButton"}},
                                        ok_payload({"ok": True, "verified": True, "bound": True, "class": "Button"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "bind_enter_submit", "parameters": {"widget_name": "InputBox"}},
                                        ok_payload({"ok": True, "verified": True, "bound": True, "class": "EditableTextBox"}))
        assert "deliverable:text_input" in goal["completed_criteria"]
        assert "deliverable:send" in goal["completed_criteria"]
        assert "deliverable:enter-to-send" in goal["completed_criteria"]

    def test_send_not_cleared_by_unbound_step(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "bind_button_event", "parameters": {"widget_name": "B"}},
                                        ok_payload({"ok": True, "verified": False, "bound": False, "code": "BINDING_FAILED"}))
        assert "deliverable:send" not in goal["completed_criteria"]

    def test_ollama_cleared_by_verified_response(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "ollama_chat", "parameters": {"prompt": "Hi"}},
                                        ok_payload({"ok": True, "verified": True, "response": "real answer", "local_only": True}))
        assert "deliverable:ollama" in goal["completed_criteria"]

    def test_ollama_never_cleared_without_real_response(self, isolated_goal):
        goal = self._goal(isolated_goal)
        # ok=True envelope, but no verified response content: must stay pending.
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "ollama_chat", "parameters": {"prompt": "Hi"}},
                                        ok_payload({"ok": True, "verified": False, "response": None}))
        assert "deliverable:ollama" not in goal["completed_criteria"]
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "ollama_chat", "parameters": {"prompt": "Hi"}},
                                        {"ok": False, "error": "OLLAMA_TIMEOUT"})
        assert "deliverable:ollama" not in goal["completed_criteria"]

    def test_thinking_online_mapping(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "set_ui_state", "parameters": {"state": "thinking"}},
                                        ok_payload({"ok": True, "verified": True, "state": "thinking"}))
        assert "deliverable:thinking" in goal["completed_criteria"]
        assert "deliverable:online" not in goal["completed_criteria"]
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "set_ui_state", "parameters": {"state": "online"}},
                                        ok_payload({"ok": True, "verified": True, "state": "online"}))
        assert "deliverable:online" in goal["completed_criteria"]

    def test_state_mismatch_stays_pending(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "set_ui_state", "parameters": {"state": "online"}},
                                        ok_payload({"ok": True, "verified": True, "state": "thinking"}))
        assert "deliverable:online" not in goal["completed_criteria"]

    def test_runtime_requires_is_playing(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "runtime_status"},
                                        ok_payload({"ok": True, "is_playing": False, "world_name": None}))
        assert "deliverable:runtime" not in goal["completed_criteria"]
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "runtime_status"},
                                        ok_payload({"ok": True, "is_playing": True, "world_name": "UEDPIE_0_X"}))
        assert "deliverable:runtime" in goal["completed_criteria"]

    def test_runtime_actor_verify_requires_found(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "runtime_actor_verify", "parameters": {"actor_name": "A"}},
                                        ok_payload({"ok": True, "verified": True, "is_playing": True, "found": False, "code": "ACTOR_NOT_FOUND_AT_RUNTIME"}))
        assert "deliverable:runtime" not in goal["completed_criteria"]

    def test_reopen_cleared_by_verified_state(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "verify_reopen_state"},
                                        ok_payload({"ok": True, "verified": True, "active_map": "/Game/Maps/X.X", "startup_map": "/Game/Maps/X"}))
        assert "deliverable:reopen" in goal["completed_criteria"]

    def test_reopen_pending_on_mismatch(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "verify_reopen_state"},
                                        ok_payload({"ok": False, "verified": False, "code": "REOPEN_STATE_MISMATCH"}))
        assert "deliverable:reopen" not in goal["completed_criteria"]

    def test_catch_all_goal_clears_only_after_all_real_criteria_plus_evidence(self, isolated_goal):
        """The synthetic task:original_goal_complete criterion must remain
        pending until every real criterion is complete AND viewport evidence
        exists; planner steps alone never clear it."""
        goal = task_goal.build_acceptance_contract("algolia")
        # "algolia" parses no concrete criteria -> the catch-all is the only criterion.
        assert goal["acceptance_criteria"] == ["task:original_goal_complete"]
        # a successful non-evidence step must not clear it
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "unreal_ping"}, ok_payload({"ok": True}))
        assert "task:original_goal_complete" in goal["pending_criteria"]
        # viewport evidence (the only real checkable item) clears it once captured
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "capture_unreal_viewport"}, ok_payload({"ok": True, "path": "x.png"}))
        assert "task:original_goal_complete" in goal["completed_criteria"]
        assert task_goal.contract_complete(goal) is True

    def test_all_criteria_complete_together(self, isolated_goal):
        goal = self._goal(isolated_goal)
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_character", "parameters": {"actor_name": "A"}}, ok_payload({"ok": True, "verified": True, "mesh": "/Game/M", "mesh_on_component": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "verify_character_visible", "parameters": {"actor_name": "A"}}, ok_payload({"ok": True, "verified": True, "mesh": "/Game/M", "visible": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "assign_animation", "parameters": {"actor_name": "A"}}, ok_payload({"ok": True, "verified": True, "animation": "/Game/I"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "avatar_react", "parameters": {"actor_name": "A"}}, ok_payload({"ok": True, "verified": True, "moved": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "create_widget_blueprint", "parameters": {"asset_path": "/Game/W"}}, ok_payload({"ok": True, "verified": True, "is_widget": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "add_widget_to_viewport", "parameters": {"widget_name": "C"}}, ok_payload({"ok": True, "verified": True, "in_viewport": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "add_editable_text_box", "parameters": {"name": "I"}}, ok_payload({"ok": True, "verified": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "bind_button_event", "parameters": {"widget_name": "S"}}, ok_payload({"ok": True, "verified": True, "bound": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "bind_enter_submit", "parameters": {"widget_name": "I"}}, ok_payload({"ok": True, "verified": True, "bound": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "chat_send_message", "parameters": {"message": "hi"}}, ok_payload({"ok": True, "verified": True, "input_verified": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "ollama_chat", "parameters": {"prompt": "hi"}}, ok_payload({"ok": True, "verified": True, "response": "ok", "local_only": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "set_ui_state", "parameters": {"state": "thinking"}}, ok_payload({"ok": True, "verified": True, "state": "thinking"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "set_ui_state", "parameters": {"state": "online"}}, ok_payload({"ok": True, "verified": True, "state": "online"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "runtime_status"}, ok_payload({"ok": True, "is_playing": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "runtime_actor_verify", "parameters": {"actor_name": "A"}}, ok_payload({"ok": True, "verified": True, "is_playing": True, "found": True}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "verify_reopen_state"}, ok_payload({"ok": True, "verified": True, "active_map": "/Game/M", "startup_map": "/Game/M"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "open_map"}, ok_payload({"ok": True, "verified": True, "level_path": "/Game/M"}))
        goal = task_goal.reconcile_step(goal, {"preferred_tool": "capture_unreal_viewport"}, ok_payload({"ok": True, "result": {"path": "x.png"}}))
        assert task_goal.contract_complete(goal) is True
        pending = [c for c in goal["pending_criteria"] if "deliverable:" in c]
        assert pending == []


# =============================================================== planner
PRODUCT_REGISTRY_KEYS = [
    "inspect_project", "unreal_ping", "spawn_actor", "open_map", "create_umg_widget",
    "save_level", "capture_unreal_viewport", "list_level_actors", "get_actor",
    "create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default",
    "add_blueprint_component", "compile_blueprint", "save_blueprint",
    "discover_character_assets", "inspect_character_asset", "install_character_assets",
    "spawn_character", "set_character_transform", "assign_animation",
    "verify_character_visible", "avatar_react", "ollama_chat", "create_widget_blueprint",
    "add_text_widget", "add_scroll_box", "add_editable_text_box", "add_button",
    "bind_button_event", "bind_enter_submit", "add_widget_to_viewport", "set_widget_text",
    "get_widget_text", "verify_widget_visible", "set_ui_state", "verify_ui_state",
    "chat_append_bubble", "chat_send_message", "chat_complete_roundtrip",
    "runtime_status", "runtime_widget_verify", "runtime_actor_verify",
    "verify_reopen_state", "start_pie", "stop_pie", "capture_pie_viewport",
    "get_pie_status",
]


class TestProductPlanner:
    @pytest.fixture(autouse=True)
    def _registry(self, monkeypatch):
        fake = {name: object() for name in PRODUCT_REGISTRY_KEYS}
        monkeypatch.setattr(api, "REGISTRY", fake)
        return fake

    def test_product_request_emits_full_pipeline_without_llm(self):
        task = (
            "Create a simple AI assistant screen with a character, chat input, Send button, "
            "Enter-to-send, local Ollama response, Online/Thinking states, runtime "
            "verification, save, reopen, and screenshot."
        )
        plan = api.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        for expected in [
            "spawn_character", "assign_animation", "verify_character_visible",
            "create_widget_blueprint", "add_text_widget", "add_scroll_box",
            "add_editable_text_box", "add_button", "bind_button_event",
            "bind_enter_submit", "add_widget_to_viewport", "save_level",
            "start_pie", "chat_send_message", "ollama_chat", "set_ui_state",
            "verify_ui_state", "avatar_react", "runtime_actor_verify",
            "runtime_widget_verify", "capture_pie_viewport", "stop_pie",
            "open_map", "verify_reopen_state", "capture_unreal_viewport",
        ]:
            assert expected in tools, f"missing {expected} in plan: {tools}"
        ids = [s["step_id"] for s in plan["steps"]]
        # deterministic ordering: send -> thinking-verify -> ollama -> online -> online-verify
        assert ids.index("live_send") < ids.index("verify_thinking_state") < ids.index("live_ollama")
        assert ids.index("live_ollama") < ids.index("state_online") < ids.index("verify_online_after")
        assert ids.index("runtime_start") < ids.index("live_send")
        assert ids.index("verify_online_after") < ids.index("avatar_reaction")
        assert ids.index("runtime_stop") < ids.index("save_product_final") < ids.index("reopen_map") < ids.index("final_screenshot")

    def test_cube_and_light_flow_has_no_product_pipeline(self):
        task = "Create a test scene: spawn a cube named ProbeCube, add a light, save, verify both, and capture a screenshot."
        plan = api.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        assert "spawn_character" not in tools
        assert "add_editable_text_box" not in tools
        assert "bind_button_event" not in tools

    def test_bp_variable_flow_unaffected(self):
        task = "Create a blueprint at /Game/Probe with String variable Greeting set initially to hello and expected value is hello."
        plan = api.normalize_execution_plan(task, None)
        tools = [s["preferred_tool"] for s in plan["steps"]]
        assert "create_blueprint" in tools
        assert "spawn_character" not in tools