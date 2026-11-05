"""Opt-in local LT 6.6 quality controls, separate from the fixed gold corpus.

Run with PGN_TEST_REAL_LANGUAGETOOL=1 and the prepared build/vendor runtime.
No remote provider, altered vendor configuration, or pipeline pool is used.
"""

import os

import pytest

from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
from tradutor_pgn.writing_protection import protect_text, restore_issue_offsets
from tradutor_pgn.writing_types import WritingRequest


@pytest.fixture(scope="module")
def local_grammar():
    if os.environ.get("PGN_TEST_REAL_LANGUAGETOOL") != "1":
        pytest.skip("opt in to the prepared local LT 6.6 runtime")
    adapter = LanguageToolLocalAdapter()
    try:
        yield adapter
    finally:
        adapter.shutdown()


def visible_issues(adapter, request):
    protected = protect_text(request)
    return tuple(restored for issue in adapter.analyze(request, protected)
                 if (restored := restore_issue_offsets(issue, protected)) is not None
                 and restored.state == "active")


@pytest.mark.parametrize("text,original,suggestion", [
    ("A palavra está correto.", "correto", "correta"),
    ("As palavras estão corretos.", "corretos", "corretas"),
    ("A avaliação é correto.", "correto", "correta"),
    ("As avaliações são corretos.", "corretos", "corretas"),
    ("Ela está bonito hoje.", "bonito", "bonita"),
    ("Elas estão bonitos hoje.", "bonitos", "bonitas"),
    ("🙂 A posição está ativo.", "ativo", "ativa"),
])
def test_real_nominal_predicative_gender(local_grammar, text, original, suggestion):
    request = WritingRequest(text, 6, "pt-BR", grammar_enabled=True)
    nominal = [issue for issue in visible_issues(local_grammar, request) if issue.rule_id == "LIGACAO_ECG_V3"]
    assert len(nominal) == 1
    issue = nominal[0]
    assert issue.category == "NOMINAL_AGREEMENT"
    assert (issue.start, issue.end, issue.original) == (text.index(original), text.index(original) + len(original), original)
    assert suggestion in issue.suggestions
    issue.validate_for(request)


@pytest.mark.parametrize("text", [
    "A palavra está correta.", "As palavras estão corretas.", "Ela está bonita hoje.",
    "A gente é maluco.", "A cidade foi alvo de uma ofensiva.",
    "As baleias são mamíferos de grande porte.", "O vinho e a cerveja estão bons.",
])
def test_real_nominal_correct_and_ambiguous_controls(local_grammar, text):
    request = WritingRequest(text, 6, "pt-BR", grammar_enabled=True)
    assert not any(issue.rule_id == "LIGACAO_ECG_V3" for issue in visible_issues(local_grammar, request))


def test_real_capitalization_is_created_by_masked_initial_name(local_grammar):
    request = WritingRequest("Kasparov analisou a posição com Kramnik.", 6, "pt-BR",
                             source_text="Kasparov analyzed with Kramnik.", grammar_enabled=True)
    projected = protect_text(request).projected_text
    assert not any(issue.rule_id == "UPPERCASE_SENTENCE_START"
                   for issue in local_grammar.check(request.text, frozenset(), text_version=6))
    assert any(issue.rule_id == "UPPERCASE_SENTENCE_START"
               for issue in local_grammar.check(projected, frozenset(), text_version=6))
    assert not any(issue.rule_id == "UPPERCASE_SENTENCE_START"
                   for issue in visible_issues(local_grammar, request))


@pytest.mark.parametrize("text,source,glossary", [
    ("🙂 Sa\u0303o analisou a posição.", "São", ()),
    ('“Érica analisou a posição.”', "Érica", ()),
    ("Concluiu. Kasparov analisou a posição.", "Kasparov", ()),
    ("Defesa Índia do Rei permite a iniciativa.", "", ("Defesa Índia do Rei",)),
])
def test_real_capitalization_unicode_and_lexical_protections(local_grammar, text, source, glossary):
    request = WritingRequest(text, 6, "pt-BR", source_text=source,
                             glossary_terms=frozenset(glossary), grammar_enabled=True)
    assert not any(issue.rule_id == "UPPERCASE_SENTENCE_START"
                   for issue in visible_issues(local_grammar, request))


@pytest.mark.parametrize("text,source", [
    ("analisou a posição.", ""),
    ("Kasparov. analisou a posição.", "Kasparov"),
    ("Kasparov! analisou a posição.", "Kasparov"),
    ("Kasparov\nanalisou a posição.", "Kasparov"),
    ("Kasparov\r\nanalisou a posição.", "Kasparov"),
    ("Kasparov\u2028analisou a posição.", "Kasparov"),
    ("[%eval +0.35] analisou a posição.", ""),
    ("$5 analisou a posição.", ""),
    ("Cd4 analisou a posição.", "Cd4"),
    ("13.Cd4 analisou a posição.", ""),
])
def test_real_capitalization_errors_remain_available(local_grammar, text, source):
    request = WritingRequest(text, 6, "pt-BR", source_text=source, grammar_enabled=True)
    issues = [issue for issue in visible_issues(local_grammar, request) if issue.rule_id == "UPPERCASE_SENTENCE_START"]
    assert len(issues) == 1
    assert issues[0].original == "analisou" and issues[0].suggestions == ("Analisou",)
    issues[0].validate_for(request)


@pytest.mark.parametrize("text", [
    "Se 13.Cd4, então ...", "Se 13.Cd4, então …", "Talvez\u00a0...", "🙂 Talvez ...",
])
def test_real_terminal_ellipsis_is_preserved(local_grammar, text):
    request = WritingRequest(text, 6, "pt-BR", grammar_enabled=True)
    assert not any(issue.rule_id == "SPACE_BEFORE_PUNCTUATION2"
                   for issue in visible_issues(local_grammar, request))


@pytest.mark.parametrize("text,provider_alert", [
    ("Talvez .", True), ("Talvez ,", True), ("Talvez ;", True), ("Talvez :", True),
    ("Talvez ..", True), ("Talvez ....", False),
    ("Talvez ... depois.", True), ("Talvez\n...", True), ("Talvez ...”", True),
])
def test_real_spacing_controls_are_not_disabled(local_grammar, text, provider_alert):
    request = WritingRequest(text, 6, "pt-BR", grammar_enabled=True)
    # LT's own four-dot leader antipattern yields no match. Compare raw and
    # integrated output so that absence is never attributed to our filtering.
    raw = tuple(issue for issue in local_grammar.check(text, frozenset(), text_version=6)
                if issue.rule_id == "SPACE_BEFORE_PUNCTUATION2")
    assert bool(raw) == provider_alert
    assert tuple(issue for issue in visible_issues(local_grammar, request)
                 if issue.rule_id == "SPACE_BEFORE_PUNCTUATION2") == raw


def test_real_rule_disable_sequence_restores_same_nominal_issue(local_grammar):
    request = WritingRequest("A posição está ativo.", 6, "pt-BR", grammar_enabled=True)
    protected = protect_text(request)
    first = local_grammar.analyze(request, protected)
    disabled = WritingRequest(request.text, 6, "pt-BR", grammar_enabled=True,
                              disabled_rule_ids=frozenset({"LIGACAO_ECG_V3"}))
    assert local_grammar.analyze(disabled, protected) == ()
    assert local_grammar.analyze(request, protected) == first
    assert first[0].category == "NOMINAL_AGREEMENT"
