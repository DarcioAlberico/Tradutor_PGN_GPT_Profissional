from types import SimpleNamespace
from unittest.mock import patch

from tradutor_pgn import settings_window
from tradutor_pgn.api_keys import mask_api_key
from tradutor_pgn.settings_window import SettingsWindow


def test_environment_key_is_identified_when_another_key_is_stored(monkeypatch):
    spec = SimpleNamespace(id="openai", env_var="OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-1234")
    with patch("tradutor_pgn.api_keys.stored_key_state", return_value="ok"), \
         patch("tradutor_pgn.api_keys.load_api_key", side_effect=lambda _id, env=None: "environment-1234" if env else "stored-5678"):
        label = SettingsWindow.describe_key_state(None, spec)
    assert "ambiente" in label
    assert "1234" in label
    assert "environment-1234" not in label


def test_storage_explanation_warns_when_windows_encryption_is_unavailable():
    with patch("tradutor_pgn.api_keys.dpapi_available", return_value=False):
        warning = settings_window.key_storage_description().lower()
    assert "sem criptografia" in warning
    assert "variável de ambiente" in warning


def test_short_key_is_not_displayed_in_full():
    for key in ("a", "abc", "1234"):
        assert key not in mask_api_key(key)
