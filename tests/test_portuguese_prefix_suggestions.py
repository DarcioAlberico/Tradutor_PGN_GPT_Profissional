"""Known components do not justify inventing a prefixed spelling.

These controls rejected a productive-prefix prototype despite its improved
corpus score. A token alone cannot distinguish prefixation from a preposition.
"""

import threading

import pytest

from tradutor_pgn.spelling_suggestions_process import SpellingSuggestionService
from tradutor_pgn.writing_assistant import SpyllsAdapter
from tradutor_pgn.writing_protection import protect_text
from tradutor_pgn.writing_types import WritingRequest


class EmptyVocabulary:
    def list_words(self):
        return []


class KnownStems:
    def __init__(self, words=()):
        self.words = frozenset(words)

    def lookup(self, word):
        return word in self.words

    def suggest(self, word):
        yield "alternativa do motor"


def analyze(word, dictionary, **kwargs):
    request = WritingRequest(word, 3, "pt-BR", **kwargs)
    adapter = SpyllsAdapter(dictionary_loader=lambda language: dictionary,
                            personal_dictionary=EmptyVocabulary())
    return adapter.analyze(request, protect_text(request))


@pytest.mark.parametrize("word,stem", [
    ("contra-almirante", "almirante"), ("contra-harmônico", "harmônico"),
    ("contra-regra", "regra"), ("contra-senso", "senso"),
    ("contra-indicação", "indicação"), ("anti-inflamatório", "inflamatório"),
    ("bem-vindo", "vindo"), ("vice-diretor", "diretor"),
    ("pós-parto", "parto"), ("cor-de-rosa", "rosa"),
    ("contra-pé-de-meia", "pé-de-meia"), ("contra-Golpe", "golpe"),
    ("cOntra-golpe", "golpe"),
    ("contra-jjogox", "jogo"), ("contra–golpe", "golpe"),
    ("contra-quem", "quem"), ("contra-tudo", "tudo"),
    ("contra-nós", "nós"), ("contra-você", "você"),
    ("ante-tudo", "tudo"), ("contra-votaram", "votaram"),
    ("contra-todos", "todos"), ("contra-partidas", "partidas"),
    ("contra-jogo limpo", "jogo"), ("ante-tudo isso", "tudo"),
])
def test_known_stem_never_authorizes_a_synthetic_prefix_alternative(word, stem):
    issues = analyze(word, KnownStems({stem}))
    assert issues
    assert all(issue.suggestions == ("alternativa do motor",) for issue in issues)


@pytest.mark.parametrize("kwargs", [
    {"source_text": "contra-prova"},
    {"glossary_terms": frozenset({"contra-prova"})},
    {"session_ignored_words": frozenset({"contra-prova"})},
])
def test_prefix_suggestion_never_creates_a_protected_occurrence(kwargs):
    assert analyze("contra-prova", KnownStems({"prova"}), **kwargs) == ()


def test_dictionary_accepted_hyphenation_is_preserved():
    assert analyze("contra-prova", KnownStems({"contra-prova", "prova"})) == ()


def test_prefix_like_token_with_digits_stays_outside_spelling():
    assert analyze("contra-golpe2", KnownStems({"golpe2"})) == ()


@pytest.mark.parametrize("word,forbidden", [
    ("contra-quem", "contraquem"), ("ante-tudo", "antetudo"),
])
def test_real_worker_does_not_invent_agglutination_from_a_known_pronoun(word, forbidden):
    service = SpellingSuggestionService(suggestion_timeout=.2)
    updates, done = [], threading.Event()

    def receive(update):
        updates.append(update)
        if update.state in {"complete", "timed_out", "unavailable"}:
            done.set()

    try:
        service.submit("prefix-quality", word, receive)
        assert done.wait(12), "local suggestion request did not finish"
        assert updates[-1].state in {"complete", "timed_out"}
        assert all(forbidden not in update.suggestions for update in updates)
    finally:
        service.shutdown()
        service._thread.join(8)
        assert not service._thread.is_alive()
