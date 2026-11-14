import pytest

from tradutor_pgn.glossary_ui_helpers import scope_from_codes, scope_to_codes, describe_scope


@pytest.mark.parametrize(("raw", "codes"), [
    ("*", ("", "")), ("", ("", "")), ("pt", ("", "pt")),
    ("en>pt", ("en", "pt")), ("en>", ("en", "")), ("*>pt", ("", "pt")),
])
def test_supported_scope_roundtrip_preserves_semantics(raw, codes):
    assert scope_to_codes(raw) == codes
    assert scope_to_codes(scope_from_codes(*codes)) == codes


@pytest.mark.parametrize("raw", ["xx", "en>zz", "en>pt>fr", "en>>"])
def test_custom_or_invalid_scope_is_not_interpreted(raw):
    assert scope_to_codes(raw) is None


def test_invalid_codes_cannot_be_converted_to_global():
    with pytest.raises(ValueError):
        scope_from_codes("xx", "pt")


def test_scope_description_distinguishes_source_target_and_global():
    assert "todos" in describe_scope("*").lower()
    assert "inglês" in describe_scope("en>").lower()
    assert "português" in describe_scope("en>pt").lower()
    assert "personalizado" in describe_scope("xx").lower()
