from tradutor_pgn.data_verification import verify_data
from tradutor_pgn.settings import SETTINGS_FILENAME


def test_data_check_accepts_settings_with_utf8_bom(tmp_path):
    (tmp_path / SETTINGS_FILENAME).write_bytes(b'\xef\xbb\xbf{"theme": "dark"}')
    assert verify_data(tmp_path)["settings"] == "ok"


def test_data_check_reports_deeply_nested_invalid_settings(tmp_path):
    (tmp_path / SETTINGS_FILENAME).write_text("[" * 3000 + "]" * 3000, encoding="utf-8")
    assert verify_data(tmp_path)["settings"] == "invalid"
