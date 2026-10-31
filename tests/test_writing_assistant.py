"""Contracts for offline spelling, protection and normalized provider results."""

from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from tradutor_pgn import prose_spellcheck
from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
from tradutor_pgn.languagetool_process import LanguageToolProcess
from tradutor_pgn.personal_dictionary import PersonalDictionary
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpyllsAdapter
from tradutor_pgn.writing_protection import protect_text
from tradutor_pgn.writing_types import AssistantStatus, WritingIssue, WritingRequest


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


@pytest.mark.parametrize("protection", ["source", "glossary"])
@pytest.mark.parametrize("compound,term,start", [
    ("cor-de-rosa", "rosa", 12),
    ("pseudo-sacrificio", "pseudo", 18),
    ("contra-jogo", "jogo", 12),
    ("d'Alembert", "Alembert", 11),
    ("d’Alembert", "Alembert", 11),
])
def test_partial_protection_never_creates_spelling_fragments(tmp_path, protection, compound, term, start):
    request = WritingRequest(
        f"{compound} posiçao", 4, "pt",
        source_text=term if protection == "source" else "",
        glossary_terms=frozenset({term}) if protection == "glossary" else frozenset(),
    )
    provider = adapter(tmp_path)
    issues = provider.analyze(request, protect_text(request))
    # A protected part prevents editing the complete token. Its independent
    # neighbor must still be checked at its real code-point offsets.
    assert [(issue.start, issue.end, issue.original) for issue in issues] == [(start, start + 7, "posiçao")]
    unprotected = replace(request, source_text="", glossary_terms=frozenset())
    assert [issue.original for issue in provider.analyze(unprotected, protect_text(unprotected))] == [compound, "posiçao"]


@pytest.mark.parametrize("compound,term,protection,legacy_words", [
    ("cor-de-rosa", "rosa", "source", []),
    ("pseudo-sacrificio", "pseudo", "source", ["pseudo-sacrificio"]),
    ("contra-jogo", "jogo", "glossary", ["contra-jogo"]),
])
def test_real_compound_boundaries_survive_partial_protection(tmp_path, compound, term, protection, legacy_words):
    dictionary = prose_spellcheck.load_dictionary("pt")
    assert dictionary is not None
    known = prose_spellcheck.source_vocabulary(term)
    assert [word for _, _, word in prose_spellcheck.misspelled_spans(compound, dictionary, known)] == legacy_words
    request = WritingRequest(
        compound, 1, "pt", source_text=term if protection == "source" else "",
        glossary_terms=frozenset({term}) if protection == "glossary" else frozenset(),
    )
    # The stricter new span protection can suppress a complete compound; it
    # must never offer to replace a fragment manufactured by masking.
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path, dictionary))
    result = assistant.analyze(request)
    assert result.mode == "spelling_only"
    assert result.issues == ()


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
    # Exercise missing files through the real lifecycle, independently of
    # whether this checkout has prepared vendor resources for the real smoke.
    process = LanguageToolProcess(resource_resolver=lambda relative: tmp_path / "absent-vendor" / relative)
    assistant = PortugueseWritingAssistant(
        spelling_adapter=adapter(tmp_path), grammar_adapter=LanguageToolLocalAdapter(process=process),
    )
    try:
        result = assistant.analyze(WritingRequest("posiçao", 1, "pt", grammar_enabled=True))
        assert result.mode == "spelling_only" and result.diagnostic
        assert len(result.issues) == 1
    finally:
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


def test_grammar_disabled_never_calls_or_starts_provider(tmp_path):
    class ForbiddenGrammar:
        def analyze(self, request, protected):
            pytest.fail("disabled grammar must not call its provider")

    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=ForbiddenGrammar())
    result = assistant.analyze(WritingRequest("posiçao", 1, "pt", grammar_enabled=False))
    assert result.mode == "spelling_only" and result.diagnostic == ""
    assert [issue.original for issue in result.issues] == ["posiçao"]


def test_full_mode_restores_grammar_offsets_deduplicates_spelling_and_filters_rules(tmp_path):
    class Grammar:
        def analyze(self, request, protected):
            def issue(start, end, rule, category):
                return WritingIssue("", rule, category, start, end, protected.projected_text[start:end],
                                    "Mensagem", "Explicação", ("correção",), "warning", "languagetool", request.text_version)
            grammar = issue(14, 18, "AGREEMENT", "NOMINAL_AGREEMENT")
            return (grammar, grammar, issue(2, 9, "MORFOLOGIK_RULE_PT_BR", "SPELLING"),
                    issue(10, 13, "DISABLED", "GRAMMAR"), issue(2, 9, "SECOND_REASON", "GRAMMAR"))

    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=Grammar())
    request = WritingRequest("🙂 posiçao boa erro", 8, "pt-BR", grammar_enabled=True,
                             disabled_rule_ids=frozenset({"DISABLED"}))
    result = assistant.analyze(request)
    assert result.mode == "full" and result.diagnostic == ""
    assert [(issue.start, issue.rule_id, issue.provider) for issue in result.issues] == [
        (2, "SECOND_REASON", "languagetool"), (2, "SPELLING_UNKNOWN_WORD", "spylls"),
        (14, "AGREEMENT", "languagetool"),
    ]
    result.validate_for(request)
    assert assistant.status().mode == "full"


def test_grammar_projection_hides_domain_text_and_suppresses_exact_glossary_conflict(tmp_path):
    seen = []

    class Grammar:
        def analyze(self, request, protected):
            seen.append(protected.projected_text)
            def issue(start, end):
                return WritingIssue("", "GRAMMAR_RULE", "GRAMMAR", start, end, protected.projected_text[start:end],
                                    "Mensagem", "Explicação", ("correção",), "warning", "languagetool", request.text_version)
            return (issue(0, 4), issue(5, 10), issue(11, 16), issue(17, 24))

    request = WritingRequest("Bxf7 termo NomeX posiçao", 1, "pt", source_text="NomeX",
                             glossary_terms=frozenset({"termo"}), grammar_enabled=True)
    result = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=Grammar()).analyze(request)
    assert seen == ["                 posiçao"]
    assert [(issue.original, issue.state) for issue in result.issues] == [
        ("termo", "suppressed_by_glossary"), ("posiçao", "active"), ("posiçao", "active"),
    ]
    assert result.mode == "full"
    result.validate_for(request)


def test_grammar_failure_preserves_spelling_without_leaking_provider_payload(tmp_path):
    class BrokenGrammar:
        def analyze(self, request, protected):
            raise RuntimeError(request.text)

    request = WritingRequest("posiçao", 4, "pt", grammar_enabled=True)
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=BrokenGrammar())
    result = assistant.analyze(request)
    assert result.mode == "spelling_only" and len(result.issues) == 1
    assert result.diagnostic and request.text not in result.diagnostic
    assert assistant.status().mode == "spelling_only"


def test_assistant_shutdown_closes_grammar_resource_once(tmp_path):
    closed = []

    class Grammar:
        def analyze(self, request, protected):
            return ()

        def shutdown(self):
            closed.append(True)

    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=Grammar())
    assert assistant.analyze(WritingRequest("boa", 1, "pt", grammar_enabled=True)).mode == "full"
    assistant.shutdown()
    assistant.shutdown()
    assert closed == [True]
    assert assistant.status().state == "stopped"


@pytest.mark.parametrize("vocabulary", ["personal", "session"])
def test_grammar_preserves_accepted_spelling_vocabulary_and_valid_grammar(tmp_path, vocabulary):
    personal = PersonalDictionary(tmp_path / "personal.json")
    if vocabulary == "personal":
        personal.add("POSICAO")

    class Grammar:
        def analyze(self, request, protected):
            return (
                WritingIssue("", "MORFOLOGIK_RULE_PT_BR", "SPELLING", 0, 7, "posicao",
                             "Grafia", "Grafia", ("posição",), "warning", "languagetool", request.text_version),
                WritingIssue("", "GENERAL_GENDER_AGREEMENT_ERRORS", "NOMINAL_AGREEMENT", 8, 11, "boa",
                             "Concordância", "Concordância", ("boas",), "warning", "languagetool", request.text_version),
            )

    request = WritingRequest("posicao boa", 2, "pt-BR",
                             session_ignored_words=frozenset({"POSICAO"}) if vocabulary == "session" else frozenset())
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=Grammar())
    assert assistant.analyze(request).issues == ()
    result = assistant.analyze(replace(request, grammar_enabled=True))
    assert result.mode == "full"
    assert [(issue.original, issue.category) for issue in result.issues] == [("boa", "NOMINAL_AGREEMENT")]


@pytest.mark.parametrize("transient", ["starting", "restarting"])
@pytest.mark.parametrize("previous", ["fresh", "spelling_only"])
def test_assistant_publishes_active_grammar_transitions_before_first_full_result(tmp_path, transient, previous):
    entered = threading.Event()
    release = threading.Event()
    results = []
    errors = []

    class Grammar:
        current = AssistantStatus("stopped", "spelling_only")

        def analyze(self, request, protected):
            self.current = AssistantStatus(transient, "spelling_only", restart_attempted=transient == "restarting")
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("test did not release grammar provider")
            self.current = AssistantStatus("ready", "full", restart_attempted=transient == "restarting")
            return ()

        def status(self):
            return self.current

    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path), grammar_adapter=Grammar())
    request = WritingRequest("boa", 3, "pt-BR", grammar_enabled=True)
    if previous == "spelling_only":
        assert assistant.analyze(replace(request, grammar_enabled=False)).mode == "spelling_only"

    def analyze():
        try:
            results.append(assistant.analyze(request))
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=analyze)
    worker.start()
    try:
        assert entered.wait(timeout=3)
        status = assistant.status()
        assert (status.state, status.mode, status.restart_attempted) == (
            transient, "spelling_only", transient == "restarting",
        )
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert len(results) == 1 and results[0].mode == "full"
    assert assistant.status().state == "ready" and assistant.status().mode == "full"


class CountingSpelling:
    cache_revision = "adapter-v1"

    def __init__(self):
        self.calls = []

    def analyze(self, request, protected):
        self.calls.append(request.text)
        return (WritingIssue("", "TYPO", "SPELLING", 0, len(request.text), request.text,
                             "Grafia", "Confira", ("correta",), "error", "test", request.text_version),)


def test_cache_reuses_content_across_versions_and_rebinds_every_issue(tmp_path):
    provider = CountingSpelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    request = WritingRequest("palavra", 1, "pt")
    first = assistant.analyze(request)
    second = assistant.analyze(replace(request, text_version=9))
    second.validate_for(replace(request, text_version=9))
    assert second.text_version == second.issues[0].text_version == 9
    assert second.issues[0].issue_id == first.issues[0].issue_id
    assert provider.calls == ["palavra"]
    assert list(tmp_path.iterdir()) == []


def test_cache_has_bounded_lru_eviction():
    provider = CountingSpelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider, cache_capacity=2)
    for version, text in enumerate(("alfa", "beta", "alfa", "gama", "beta")):
        assert assistant.analyze(WritingRequest(text, version, "pt")).issues[0].original == text
    assert provider.calls == ["alfa", "beta", "gama", "beta"]


@pytest.mark.parametrize("field,value", [
    ("source_text", "nome"), ("target_language", "pt-BR"),
    ("glossary_terms", frozenset({"termo"})),
    ("session_ignored_words", frozenset({"sessão"})),
    ("disabled_rule_ids", frozenset({"REGRA"})), ("grammar_enabled", True),
])
def test_cache_includes_every_analysis_input(field, value):
    class Grammar:
        def analyze(self, request, protected):
            return ()

    provider = CountingSpelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider, grammar_adapter=Grammar())
    request = WritingRequest("palavra", 1, "pt")
    assistant.analyze(request)
    assistant.analyze(replace(request, **{field: value}))
    assert provider.calls == ["palavra", "palavra"]


@pytest.mark.parametrize("revision", ["glossary", "vocabulary", "rules", "providers"])
def test_cache_revision_change_and_explicit_invalidation_reanalyze(revision):
    provider = CountingSpelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    request = WritingRequest("palavra", 1, "pt")
    assistant.analyze(request)
    assistant.set_cache_revisions(**{revision: "next"})
    assistant.analyze(request)
    assistant.set_cache_revisions(**{revision: "next"})
    assistant.analyze(request)
    assert len(provider.calls) == 2
    assistant.invalidate_cache()
    assistant.analyze(request)
    assert len(provider.calls) == 3


def test_cache_observes_adapter_version_changes():
    provider = CountingSpelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    request = WritingRequest("palavra", 1, "pt")
    assistant.analyze(request)
    provider.cache_revision = "adapter-v2"
    assistant.analyze(request)
    assert len(provider.calls) == 2


def test_cache_observes_personal_vocabulary_changes_from_another_instance(tmp_path):
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path))
    request = WritingRequest("posiçao", 1, "pt")
    assert len(assistant.analyze(request).issues) == 1
    external = PersonalDictionary(tmp_path / "personal.json")
    external.add("posiçao")
    assert assistant.analyze(request).issues == ()
    external.remove("posiçao")
    assert len(assistant.analyze(request).issues) == 1


@pytest.mark.parametrize("capacity", [0, 2])
def test_cache_never_freezes_failure_and_disabling_cache_reanalyzes(capacity):
    class Recovering(CountingSpelling):
        broken = True

        def analyze(self, request, protected):
            if self.broken:
                raise RuntimeError("unavailable")
            return super().analyze(request, protected)

    provider = Recovering()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider, cache_capacity=capacity)
    request = WritingRequest("palavra", 1, "pt")
    assert assistant.analyze(request).mode == "unavailable"
    provider.broken = False
    assert len(assistant.analyze(request).issues) == 1
    assistant.analyze(request)
    assert len(provider.calls) == (2 if capacity == 0 else 1)


def test_shutdown_during_spelling_cannot_publish_ready_or_cache_late_result():
    entered, release = threading.Event(), threading.Event()

    class Blocking(CountingSpelling):
        def analyze(self, request, protected):
            entered.set()
            assert release.wait(3)
            return super().analyze(request, protected)

    assistant = PortugueseWritingAssistant(spelling_adapter=Blocking())
    request = WritingRequest("palavra", 1, "pt")
    results = []
    worker = threading.Thread(target=lambda: results.append(assistant.analyze(request)))
    worker.start()
    try:
        assert entered.wait(3)
        assistant.shutdown()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert assistant.status().state == "stopped"
    assert results[0].mode == "unavailable"
    assert assistant.analyze(request).mode == "unavailable"
    assert assistant.status().state == "stopped"


def test_invalidation_during_analysis_prevents_old_check_refilling_cache():
    entered, release = threading.Event(), threading.Event()

    class Blocking(CountingSpelling):
        def analyze(self, request, protected):
            entered.set()
            assert release.wait(3)
            return super().analyze(request, protected)

    provider = Blocking()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    request = WritingRequest("palavra", 1, "pt")
    results = []
    worker = threading.Thread(target=lambda: results.append(assistant.analyze(request)))
    worker.start()
    try:
        assert entered.wait(3)
        assistant.invalidate_cache()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and len(results) == 1
    assistant.analyze(request)
    assert len(provider.calls) == 2


def test_cached_full_result_cannot_hide_sidecar_failure_and_fallback_can_recover():
    class Grammar:
        state = AssistantStatus("ready", "full")

        def status(self):
            return self.state

        def analyze(self, request, protected):
            if self.state.mode != "full":
                raise RuntimeError("failed")
            return ()

    provider, grammar = CountingSpelling(), Grammar()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider, grammar_adapter=grammar)
    request = WritingRequest("palavra", 1, "pt", grammar_enabled=True)
    assert assistant.analyze(request).mode == "full"
    grammar.state = AssistantStatus("failed", "spelling_only", restart_attempted=True)
    fallback = assistant.analyze(request)
    assert fallback.mode == "spelling_only" and fallback.diagnostic
    assert len(fallback.issues) == 1 and len(provider.calls) == 2
    grammar.state = AssistantStatus("ready", "full", restart_attempted=True)
    assert assistant.analyze(request).mode == "full"


def test_cached_spelling_cannot_hide_personal_vocabulary_read_failure(tmp_path):
    assistant = PortugueseWritingAssistant(spelling_adapter=adapter(tmp_path))
    request = WritingRequest("posiçao", 1, "pt")
    assert assistant.analyze(request).mode == "spelling_only"
    path = tmp_path / "personal.json"
    path.mkdir()
    try:
        result = assistant.analyze(request)
        assert result.mode == "unavailable" and result.diagnostic
    finally:
        path.rmdir()
    assert assistant.analyze(request).mode == "spelling_only"


@pytest.mark.parametrize("capacity", [-1, True, 1.5])
def test_cache_rejects_invalid_capacity(capacity):
    with pytest.raises(ValueError):
        PortugueseWritingAssistant(cache_capacity=capacity)


def test_shutdown_during_spelling_does_not_start_grammar_after_close():
    entered, release = threading.Event(), threading.Event()
    grammar_calls = []

    class Blocking(CountingSpelling):
        def analyze(self, request, protected):
            entered.set()
            assert release.wait(3)
            return super().analyze(request, protected)

    class Grammar:
        def analyze(self, request, protected):
            grammar_calls.append(request.text_version)
            return ()

    assistant = PortugueseWritingAssistant(spelling_adapter=Blocking(), grammar_adapter=Grammar())
    request = WritingRequest("palavra", 1, "pt", grammar_enabled=True)
    worker = threading.Thread(target=lambda: assistant.analyze(request))
    worker.start()
    try:
        assert entered.wait(3)
        assistant.shutdown()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert grammar_calls == []
