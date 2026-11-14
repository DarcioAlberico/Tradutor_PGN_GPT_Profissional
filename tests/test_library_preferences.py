from tradutor_pgn import library_preferences
import json
import pytest


def test_preferences_validate_values_and_preserve_unknown_facets():
    saved = {"status": "invalid", "order": "oldest", "failures": "unknown",
             "source": "en", "target": "pt", "provider": "motor"}
    assert library_preferences.parse_preferences(saved) == saved
    invalid = library_preferences.parse_preferences({"status": "inventado", "order": [], "failures": 5,
                                                       "source": {}, "target": 4, "provider": None})
    assert invalid == {"status": None, "order": "name", "failures": None,
                       "source": None, "target": None, "provider": None}


def test_empty_facet_means_unknown_not_all():
    result = library_preferences.parse_preferences({"source": "", "target": "", "provider": ""})
    assert result["source"] == result["target"] == result["provider"] == ""


def test_saving_preferences_preserves_unrelated_sections(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drafts": {"a": "edição"}}), encoding="utf8")
    library_preferences.save_preferences({"order": "oldest"}, path=str(path))
    data = json.loads(path.read_text(encoding="utf8"))
    assert data["drafts"] == {"a": "edição"}
    assert data["translation_library"]["order"] == "oldest"


def test_saving_preferences_refuses_corrupt_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{invalid", encoding="utf8")
    with pytest.raises(ValueError):
        library_preferences.save_preferences({"order": "oldest"}, path=str(path))
    assert path.read_text(encoding="utf8") == "{invalid"


def test_saving_preferences_preserves_unknown_fields_in_the_same_section(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"translation_library": {"future_option": "preservar"}}), encoding="utf8")
    library_preferences.save_preferences({"order": "oldest"}, path=str(path))
    data = json.loads(path.read_text(encoding="utf8"))
    assert data["translation_library"]["future_option"] == "preservar"
    assert data["translation_library"]["order"] == "oldest"
