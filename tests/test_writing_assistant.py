"""Contracts for offline spelling, protection and normalized provider results."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tradutor_pgn import prose_spellcheck
from tradutor_pgn.personal_dictionary import PersonalDictionary
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpyllsAdapter
from tradutor_pgn.writing_protection import protect_text
from tradutor_pgn.writing_types import WritingIssue, WritingRequest


class Dictionary:
    def lookup(self, word):
        return word.lower() in {"uma", "posição", "boa", "erro"}

    def suggest(self, word):
        yield from ("posição", "posição", "posições", "oposição", "posição boa", "posicional", "sexto")


def adapter(tmp_path, dictionary=None):
    return SpyllsAdapter(
        dictionary_loader=lambda language: dictionary if dictionary is not None else Dictionary(),
        personal_dictionary=PersonalDictionary(tmp_path / "personal.json"),
    )


def test_typo_has_stable_unique_five_suggestions_and_unicode_offsets(tmp_path):
    request = WritingRequest("🙂 Uma posiçao boa.", 7, "pt-BR")
    provider = adapter(tmp_path)
    first = provider.analyze(request, protect_text(request))
    assert len(first) == 1
    issue = first[0]
    assert (issue.start, issue.end, issue.original, issue.category) == (6, 13, "posiçao", "SPELLING")
    assert issue.suggestions == ("posição", "posições", "oposição", "posição boa", "posicional")
    assert issue.message and issue.explanation and issue.provider == "spylls"
    assert issue.text_version == 7 and issue.state == "active"
    assert first == provider.analyze(request, protect_text(request))
    issue.validate_for(request)


def test_source_glossary_personal_and_session_vocabularies_are_respected(tmp_path):
    personal = PersonalDictionary(tmp_path / "personal.json")
    personal.add("PESSOAL")
    provider = adapter(tmp_path)
    request = WritingRequest(
        "Ftacnik contra-jogo pessoal SESSÃO posiçao", 3, "pt",
        source_text="FTACNIK", glossary_terms=frozenset({"contra-jogo"}),
        session_ignored_words=frozenset({"sessão"}),
    )
    assert [issue.original for issue in provider.analyze(request, protect_text(request))] == ["posiçao"]
    personal.add("posiçao")
    assert provider.analyze(request, protect_text(request)) == ()
    personal.remove("posiçao")
    assert [issue.original for issue in provider.analyze(request, protect_text(request))] == ["posiçao"]


def test_protected_notation_and_technical_text_never_reach_lookup(tmp_path):
    class StrictDictionary(Dictionary):
        def lookup(self, word):
            assert word in {"posiçao", "20Ca2"}, word
            return False

    request = WritingRequest(
        "13.Cd4 Bxf7+ O-O $1 [%eval erro] https://typo.invalid autor@typo.invalid motor_v2 20Ca2 posiçao", 0, "pt",
    )
    issues = adapter(tmp_path, StrictDictionary()).analyze(request, protect_text(request))
    assert [issue.original for issue in issues] == ["posiçao"]


def test_known_vocabulary_is_filtered_before_dictionary_lookup(tmp_path):
    class FailingDictionary(Dictionary):
        def lookup(self, word):
            raise RuntimeError("engine must not see accepted vocabulary")

    personal = PersonalDictionary(tmp_path / "personal.json")
    personal.add("pessoal")
    request = WritingRequest("PESSOAL SESSÃO", 1, "pt", session_ignored_words=frozenset({"sessão"}))
    assert adapter(tmp_path, FailingDictionary()).analyze(request, protect_text(request)) == ()


def test_unicode_vocabulary_and_dictionary_lookup_keep_original_offsets(tmp_path):
    personal = PersonalDictionary(tmp_path / "personal.json")
    personal.add("ação")
    request = WritingRequest("🙂 ac\u0327a\u0303o STRASSE posic\u0327ao", 2, "pt",
                             session_ignored_words=frozenset({"Straße"}))
    issues = adapter(tmp_path).analyze(request, protect_text(request))
    assert [(issue.start, issue.end, issue.original) for issue in issues] == [(17, 25, "posic\u0327ao")]
    issues[0].validate_for(request)


def test_decomposed_correct_word_is_accepted_by_real_dictionary(tmp_path):
    dictionary = prose_spellcheck.load_dictionary("pt")
    assert dictionary is not None
    request = WritingRequest("🙂 posic\u0327a\u0303o boa", 1, "pt")
    assert adapter(tmp_path, dictionary).analyze(request, protect_text(request)) == ()


def test_decomposed_multiword_glossary_retains_legacy_token_vocabulary(tmp_path):
    request = WritingRequest("ação", 1, "pt", glossary_terms=frozenset({"ac\u0327a\u0303o futura"}))
    assert adapter(tmp_path).analyze(request, protect_text(request)) == ()


def test_personal_vocabulary_read_error_is_visible_and_can_recover(tmp_path):
    personal = PersonalDictionary(tmp_path / "personal.json")
    personal.path.mkdir()
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path))
    request = WritingRequest("posiçao", 1, "pt")
    result = assistant.analyze(request)
    assert result.mode == "unavailable" and result.issues == ()
    assert "vocabulário pessoal" in result.diagnostic
    personal.path.rmdir()
    assert assistant.analyze(request).mode == "spelling_only"


def test_grammar_requested_without_adapter_has_visible_fallback(tmp_path):
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path))
    result = assistant.analyze(WritingRequest("posiçao", 1, "pt", grammar_enabled=True))
    assert result.mode == "spelling_only" and result.diagnostic
    assert len(result.issues) == 1
    assistant.shutdown()
    assert assistant.status().state == "stopped"


@pytest.mark.parametrize("language", ["pt", "PT", "pt-BR", "pt_BR"])
def test_portuguese_language_aliases_load_the_bundled_dictionary(tmp_path, language):
    def load(selected):
        assert selected == "pt"
        return Dictionary()

    provider = SpyllsAdapter(dictionary_loader=load, personal_dictionary=PersonalDictionary(tmp_path / "p.json"))
    result = PortugueseWritingAssistant(spelling_adapter=provider).analyze(WritingRequest("posiçao", 0, language))
    assert result.mode == "spelling_only" and result.issues[0].original == "posiçao"


@pytest.mark.parametrize("language", ["it", "en", ""])
def test_unsupported_language_is_explicit_and_never_loads_portuguese(tmp_path, language):
    def forbidden_load(_language):
        pytest.fail("unsupported language must not load a dictionary")

    provider = SpyllsAdapter(dictionary_loader=forbidden_load, personal_dictionary=PersonalDictionary(tmp_path / "p.json"))
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    result = assistant.analyze(WritingRequest("posiçao", 5, language))
    assert result.mode == "unavailable" and result.issues == () and result.text_version == 5
    assert result.diagnostic and assistant.status().mode == "unavailable"


@pytest.mark.parametrize("failure", ["missing", "load", "lookup", "suggest"])
def test_dictionary_failures_are_visible_without_leaking_user_text(tmp_path, failure):
    secret = "segredodousuario"

    class BrokenDictionary(Dictionary):
        def lookup(self, word):
            if failure == "lookup":
                raise RuntimeError(secret)
            return False

        def suggest(self, word):
            if failure == "suggest":
                yield "primeira"
                raise RuntimeError(secret)
            yield "correção"

    def load(_language):
        if failure == "load":
            raise OSError(secret)
        return None if failure == "missing" else BrokenDictionary()

    provider = SpyllsAdapter(dictionary_loader=load, personal_dictionary=PersonalDictionary(tmp_path / "p.json"))
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    result = assistant.analyze(WritingRequest(secret, 1, "pt"))
    assert result.mode == "unavailable" and result.issues == ()
    assert result.diagnostic and secret not in result.diagnostic
    assert assistant.status().state == "failed"


def test_disabled_rule_is_filtered_and_empty_success_has_explicit_mode(tmp_path):
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path))
    result = assistant.analyze(WritingRequest("posiçao", 1, "pt"))
    disabled = result.issues[0].rule_id
    result = assistant.analyze(WritingRequest("posiçao", 2, "pt", disabled_rule_ids=frozenset({disabled})))
    assert result.mode == "spelling_only" and result.issues == ()
    assert assistant.status().state == "ready"


def test_assistant_filters_stale_invalid_protected_deduplicates_and_sorts():
    request = WritingRequest("posiçao erro termo", 8, "pt", glossary_terms=frozenset({"termo"}))

    class Provider:
        def analyze(self, request, protected):
            def issue(start, original, category="SPELLING"):
                return WritingIssue("", "TEST", category, start, start + len(original), original,
                                    "Mensagem", "Explicação", ("correção",), "error", "test", 8)
            typo = issue(0, "posiçao")
            return (issue(8, "erro"), typo, typo, replace(typo, text_version=7),
                    replace(typo, original="errada!"), issue(13, "     ", "GRAMMAR"),
                    issue(13, "     "))

    result = PortugueseWritingAssistant(spelling_adapter=Provider()).analyze(request)
    assert [(issue.start, issue.original, issue.state) for issue in result.issues] == [
        (0, "posiçao", "active"), (8, "erro", "active"), (13, "termo", "suppressed_by_glossary"),
    ]
    result.validate_for(request)


def test_real_dictionary_spelling_corpus(tmp_path):
    dictionary = prose_spellcheck.load_dictionary("pt")
    assert dictionary is not None, "bundled pt-BR dictionary is required"
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path, dictionary))
    corpus = json.loads((Path(__file__).parent / "fixtures" / "portuguese_writing_corpus.json").read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        request = WritingRequest(case["text"], 1, "pt", source_text=case["source_text"],
                                 glossary_terms=frozenset(case["glossary_terms"]))
        result = assistant.analyze(request)
        assert result.mode == "spelling_only", case["id"]
        expected = [(issue["start"], issue["end"], issue["original"]) for issue in case["expected_issues"] if issue["category"] == "SPELLING"]
        assert [(issue.start, issue.end, issue.original) for issue in result.issues] == expected, case["id"]
        for issue in result.issues:
            assert issue.suggestions, case["id"]
            for interval in case["forbidden_ranges"]:
                assert issue.end <= interval["start"] or issue.start >= interval["end"], case["id"]


def test_existing_hyphen_suggestion_is_preserved_without_inventing_correction(tmp_path):
    dictionary = prose_spellcheck.load_dictionary("pt")
    assert dictionary is not None
    request = WritingRequest("contra-jogo", 1, "pt")
    issues = adapter(tmp_path, dictionary).analyze(request, protect_text(request))
    # The corpus's editorial reference is "contrajogo", absent from VERO.
    # Preserve the shipped engine's real suggestion rather than inventing one.
    assert [issue.original for issue in issues] == ["contra-jogo"]
    assert issues[0].suggestions == ("contra jogo",)
    assert prose_spellcheck.suggestions("contra-jogo", dictionary) == ["contra jogo"]
