from types import SimpleNamespace
from unittest.mock import patch

from tradutor_pgn.settings_window import SettingsWindow
from tradutor_pgn.settings import WRITING_KEY


def test_key_write_failure_reports_possible_partial_save():
    window = SimpleNamespace(values=lambda: ({WRITING_KEY: {}}, None), key_changes=lambda: {"openai": "secret"},
                             _writing_category_changes={}, status_label=object(), win=object())
    with patch("tradutor_pgn.settings_window.write_settings_sections"), \
         patch("tradutor_pgn.settings_window.api_keys.save_api_key", side_effect=OSError), \
         patch("tradutor_pgn.settings_window.flash_message") as message:
        assert SettingsWindow.save(window) is False
    assert "parcial" in message.call_args.args[2].lower()
