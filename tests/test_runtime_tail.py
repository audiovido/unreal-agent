from app import api


def test_not_found_is_absence_success():
    assert api._resource_is_absent({'ok': False, 'error': 'Asset not found: /Game/Probe'})
    assert api._resource_is_absent({'ok': True, 'result': {'exists': False}})
    assert api._resource_is_absent({'ok': True, 'result': {'ok': False, 'error': 'Asset not found'}})


def test_actor_identity_not_found_is_absence_success():
    # The bridge identity resolver reports absence as
    # "actor_not_resolved: not_found" (status=not_found). A verified-clean
    # actor removal must count this as absence, not as resource_still_present.
    bridge_envelope = {
        'ok': True,
        'message': 'Python executed on Unreal main thread',
        'result': {
            'ok': False,
            'error': 'actor_not_resolved: not_found',
            'query': 'UI_DEMO_CUBE',
            'matches': [],
        },
        'stdout': '',
    }
    assert api._resource_is_absent(bridge_envelope)
    assert api._resource_is_absent({'ok': False, 'error': 'actor_not_found: Ghost'})


def test_cleanup_pending_tracks_only_unverified_disposable_resources():
    s = {'created_resources': [
        {'path': '/Game/A', 'disposable': True, 'verified_clean': False},
        {'path': '/Game/B', 'disposable': True, 'verified_clean': True},
        {'path': '/Game/C', 'disposable': False},
    ]}
    assert [r['path'] for r in api._cleanup_pending(s)] == ['/Game/A']


def test_complete_predicate_requires_validation_and_all_steps():
    s = {'validation_result': 'passed', 'failed_step': None, 'created_resources': [], 'plan': {'steps': [{'status': 'completed'}]}}
    assert api._can_complete(s)
    s['plan']['steps'][0]['status'] = 'pending'
    assert not api._can_complete(s)
