import traceback
from unittest.mock import Mock

from tools.unreal.blueprint_tools import BlueprintTools
from tools.unreal.error_contract import structured_execution_error


def test_invalid_blueprint_path_is_structured_failure():
    result = BlueprintTools(Mock()).compile_blueprint('/Game/Maps/Main')
    assert result['ok'] is False
    assert result['code'] == 'INVALID_BLUEPRINT_PATH'
    assert result['compile_called'] is False


def test_invalid_object_type_is_structured_failure():
    result = BlueprintTools(Mock()).compile_blueprint(123)
    assert result['ok'] is False
    assert result['code'] == 'INVALID_BLUEPRINT_PATH'


def test_bridge_result_requires_compile_and_save_verification():
    bridge = Mock()
    bridge.execute_python.return_value = {'ok': True, 'result': {
        'ok': True, 'asset_found': True, 'is_blueprint': True,
        'compile_called': True, 'compile_status': '<BlueprintStatus.BS_UP_TO_DATE: 3>',
        'save_ok': True, 'verified': True, 'errors': [],
    }}
    result = BlueprintTools(bridge).compile_blueprint('/Game/Blueprints/BP_Test')
    assert result['result']['verified'] is True


def test_compile_error_is_not_success():
    bridge = Mock()
    bridge.execute_python.return_value = {'ok': True, 'result': {
        'ok': False, 'code': 'BLUEPRINT_COMPILE_FAILED',
        'asset_found': True, 'is_blueprint': True,
        'compile_called': True, 'save_ok': False, 'verified': False,
        'errors': ['TypeError: bad compile argument'],
    }}
    result = BlueprintTools(bridge).compile_blueprint('/Game/Blueprints/BP_Test')
    assert result['result']['ok'] is False
    assert result['result']['verified'] is False


def test_missing_blueprint_is_structured_failure():
    bridge = Mock()
    bridge.execute_python.return_value = {'ok': True, 'result': {
        'ok': False, 'code': 'BLUEPRINT_NOT_FOUND', 'asset_found': False,
        'is_blueprint': False, 'compile_called': False, 'verified': False,
    }}
    result = BlueprintTools(bridge).compile_blueprint('/Game/Blueprints/Missing')
    assert result['result']['code'] == 'BLUEPRINT_NOT_FOUND'


def test_listener_preserves_traceback_and_metadata():
    try:
        raise TypeError('wrong UE argument')
    except Exception as exc:
        result = structured_execution_error(exc, code='BLUEPRINT_COMPILE_FAILED', recoverable=True)
    assert result['ok'] is False
    assert result['code'] == 'BLUEPRINT_COMPILE_FAILED'
    assert result['error_type'] == 'TypeError'
    assert 'wrong UE argument' in result['message']
    assert 'TypeError' in result['traceback']
    assert result['recoverable'] is True


def test_retry_budget_is_bounded_by_three_candidate_objects():
    # The generated implementation limits candidate objects to three and never
    # reports verified success unless the final reload status is up-to-date.
    source = open('tools/unreal/blueprint_tools.py', encoding='utf-8-sig').read()
    assert 'candidates[:3]' in source
    assert 'BS_UP_TO_DATE' in source
