from datetime import datetime
from unittest.mock import patch

from tradutor_pgn import settings


def test_deeply_nested_settings_can_be_read_and_preserved_for_recovery(tmp_path):
    path = tmp_path / "settings.json"
    damaged = "[" * 3000 + "]" * 3000
    path.write_text(damaged, encoding="utf-8")
    assert settings.load_settings(path) == {}
    assert settings._read_settings_for_update(path) == {}
    assert next(tmp_path.glob("settings.json.corrompido-*")).read_text(encoding="utf-8") == damaged


def test_repeated_corruption_does_not_overwrite_previous_backup(tmp_path):
    path = tmp_path / "settings.json"
    previous = tmp_path / "settings.json.corrompido-20261113-120000"
    previous.write_text("primeiro", encoding="utf-8")
    path.write_text("segundo", encoding="utf-8")
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 11, 13, 12, 0, 0)
    with patch.object(settings, "datetime", FrozenDateTime):
        assert settings._read_settings_for_update(str(path)) == {}
    assert previous.read_text(encoding="utf-8") == "primeiro"
    assert sorted(p.read_text(encoding="utf-8") for p in tmp_path.iterdir()) == ["primeiro", "segundo"]
