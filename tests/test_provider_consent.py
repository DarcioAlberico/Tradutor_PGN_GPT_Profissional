from types import SimpleNamespace
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tradutor_pgn import app_actions, app_paths
from tradutor_pgn.provider_consent import ConsentStore


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(app_actions, 'configured_providers', lambda: [])
    monkeypatch.setattr(app_actions.messagebox, 'showerror', lambda *a, **k: None)
    app = SimpleNamespace(translation_provider='google')
    return app, tmp_path


def test_declining_unofficial_provider_does_not_save_or_start(harness, monkeypatch):
    app, _ = harness
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'deep-translator')
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', lambda *a, **k: False)
    assert app_actions.choose_translation_provider(app) is None
    assert app.translation_provider == 'google'
    assert not ConsentStore(app_paths.data_path('provider-consent.db')).accepted('deep-translator', 1)


def test_consent_persists_per_provider_and_across_new_app(harness, monkeypatch):
    app, _ = harness
    choice = ['google']
    confirm = Mock(return_value=True)
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: choice[0])
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', confirm)
    assert app_actions.choose_translation_provider(app) == 'google'
    assert app_actions.choose_translation_provider(SimpleNamespace(translation_provider='google')) == 'google'
    assert confirm.call_count == 1
    choice[0] = 'deep-translator'
    assert app_actions.choose_translation_provider(app) == 'deep-translator'
    assert confirm.call_count == 2


def test_failed_consent_write_does_not_allow_translation(harness, monkeypatch):
    app, _ = harness
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'google')
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', lambda *a, **k: True)
    monkeypatch.setattr(ConsentStore, 'accept', Mock(side_effect=OSError('private path')))
    assert app_actions.choose_translation_provider(app) is None


def test_unknown_provider_never_falls_back_to_google(harness, monkeypatch):
    app, _ = harness
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'unknown')
    confirm = Mock()
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', confirm)
    assert app_actions.choose_translation_provider(app) is None
    confirm.assert_not_called()


@pytest.mark.parametrize('value', [0, 2])
def test_stale_or_invalid_consent_is_not_treated_as_acceptance(harness, monkeypatch, value):
    app, _ = harness
    ConsentStore(app_paths.data_path('provider-consent.db')).accept('google', value)
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'google')
    confirm = Mock(return_value=False)
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', confirm)
    assert app_actions.choose_translation_provider(app) is None
    confirm.assert_called_once()


def test_independent_processes_preserve_both_provider_consents(tmp_path):
    path = tmp_path / 'provider-consent.db'
    script = (
        'import sys; from tradutor_pgn.provider_consent import ConsentStore; '
        'ConsentStore(sys.argv[1]).accept(sys.argv[2], 1)'
    )
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path), provider])
                 for provider in ('google', 'deep-translator')]
    assert [process.wait(timeout=20) for process in processes] == [0, 0]
    store = ConsentStore(path)
    assert store.accepted('google', 1)
    assert store.accepted('deep-translator', 1)


def test_corrupt_consent_database_blocks_translation_without_overwriting(harness, monkeypatch):
    app, path = harness
    consent_file = path / 'provider-consent.db'
    consent_file.write_bytes(b'corrupted user data')
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'google')
    confirm = Mock(return_value=True)
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', confirm)
    assert app_actions.choose_translation_provider(app) is None
    confirm.assert_not_called()
    assert consent_file.read_bytes() == b'corrupted user data'


def test_stale_in_memory_settings_do_not_replace_fresh_consent_check(harness, monkeypatch):
    app, _ = harness
    monkeypatch.setattr(app_actions.messagebox, 'askyesno', lambda *a, **k: False)
    stale = {'unofficial_google_consent': {'google': 1}}
    monkeypatch.setattr(app_actions, 'load_settings', lambda: stale)
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *a: 'google')
    assert app_actions.choose_translation_provider(app) is None
