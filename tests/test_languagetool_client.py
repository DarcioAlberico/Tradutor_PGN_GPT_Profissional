"""HTTP boundary tests: no JVM, real loopback requests and Java offsets."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time
from urllib.parse import parse_qs

import pytest
import requests

from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter, LanguageToolUnavailable
from tradutor_pgn.writing_protection import protect_text
from tradutor_pgn.writing_types import WritingRequest


@contextmanager
def http_server(payload=None, *, status=200, delay=0, location=None):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
            received.append((self.path, parse_qs(body)))
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def match(offset=3, length=5, *, rule_id="PT_AGREEMENT", category="GRAMMAR", issue_type="grammar"):
    return {
        "message": "Confira a concordância.", "shortMessage": "Concordância",
        "offset": offset, "length": length,
        "replacements": [{"value": word} for word in ("torres", "torres", "peças", "damas", "casas", "linhas", "sexto")],
        "rule": {"id": rule_id, "description": "Concordância nominal", "issueType": issue_type,
                 "category": {"id": category, "name": "Gramática"}},
        "context": {"text": "texto privado", "offset": offset, "length": length},
    }


def response(*matches):
    return {"software": {"name": "LanguageTool", "version": "6.6"},
            "language": {"name": "Portuguese (Brazil)", "code": "pt-BR"}, "matches": list(matches)}


def test_post_explicit_pt_br_disabled_rules_and_utf16_offsets(caplog):
    text = "🙂 torre boas"
    with http_server(response(match())) as (url, received):
        caplog.set_level(logging.DEBUG)
        issues = LanguageToolLocalAdapter(url).check(text, frozenset({"B", "A"}), text_version=9)
    assert received == [("/v2/check", {"text": [text], "language": ["pt-BR"], "disabledRules": ["A,B"]})]
    assert len(issues) == 1
    issue = issues[0]
    assert (issue.start, issue.end, issue.original, issue.text_version) == (2, 7, "torre", 9)
    assert (issue.category, issue.rule_id, issue.provider) == ("NOMINAL_AGREEMENT", "PT_AGREEMENT", "languagetool")
    assert issue.suggestions == ("torres", "peças", "damas", "casas", "linhas")
    assert issue.message and issue.explanation
    assert text not in caplog.text and "texto privado" not in caplog.text


@pytest.mark.parametrize("rule_id,category,issue_type,expected", [
    ("PT_VERBAL_AGREEMENT", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("PT_AGREEMENT", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("PT_WORD_REPEAT_RULE", "REDUNDANCY", "duplication", "REPEATED_WORD"),
    ("PT_COMMA", "PUNCTUATION", "typographical", "PUNCTUATION"),
    ("MORFOLOGIK_RULE_PT_BR", "TYPOS", "misspelling", "SPELLING"),
    ("UNKNOWN_RULE", "GRAMMAR", "grammar", "GRAMMAR"),
    ("GENERAL_GENDER_AGREEMENT_ERRORS", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("GENERAL_NUMBER_AGREEMENT_ERRORS", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("GENERAL_GENDER_NUMBER_AGREEMENT_ERRORS", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("LINKING_VERB_PREDICATE_AGREEMENT", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("GENERAL_VERB_AGREEMENT_ERRORS", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("REFLEXIVE_VERB_SE_AGREEMENT", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("CONCORDANCIA_SER_PLURAL", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("CONCORDANCIA_QUALQUER", "GRAMMAR", "grammar", "VERBAL_AGREEMENT"),
    ("SER_ADJECTIVE_AGREEMENT", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("TODOS_NUMBER_AGREEMENT", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("LIGACAO_ECG_V3", "GRAMMAR", "grammar", "NOMINAL_AGREEMENT"),
    ("LIGACAO_ECG_V30", "GRAMMAR", "grammar", "GRAMMAR"),
    ("LIGACAO_ECG_V2", "GRAMMAR", "grammar", "GRAMMAR"),
])
def test_category_mapping_retains_rule_identity(rule_id, category, issue_type, expected):
    with http_server(response(match(0, 5, rule_id=rule_id, category=category, issue_type=issue_type))) as (url, _):
        issue = LanguageToolLocalAdapter(url).check("torre", frozenset())[0]
    assert (issue.category, issue.rule_id) == (expected, rule_id)


def test_utf16_span_can_include_astral_character_and_combining_marks():
    with http_server(response(match(1, 4))) as (url, _):
        issue = LanguageToolLocalAdapter(url).check("a🙂e\u0301z", frozenset())[0]
    assert (issue.start, issue.end, issue.original) == (1, 4, "🙂e\u0301")


def test_disabled_rule_is_suppressed_even_if_server_returns_it():
    with http_server(response(match(0, 5))) as (url, _):
        assert LanguageToolLocalAdapter(url).check("torre", frozenset({"PT_AGREEMENT"})) == ()


@pytest.mark.parametrize("bad_match", [
    match(1, 1), match(-1, 2), match(3, 99), match(0, 0), match(True, 1),
    {**match(), "rule": {}}, {**match(), "replacements": "bad"},
])
def test_invalid_or_half_surrogate_offsets_fail_without_partial_success(bad_match):
    with http_server(response(match(3, 5), bad_match)) as (url, _):
        with pytest.raises(LanguageToolUnavailable, match="resposta"):
            LanguageToolLocalAdapter(url).check("🙂 torre", frozenset())


@pytest.mark.parametrize("payload,status", [
    (b"private text is not json", 200), ({"matches": "bad"}, 200),
    (response(), 500), (response(), 429),
    ({**response(), "software": {"name": "LanguageTool", "version": "99"}}, 200),
    ({**response(), "language": {"code": "pt-PT"}}, 200),
])
def test_bad_http_or_schema_has_safe_diagnostic(payload, status, caplog):
    with http_server(payload, status=status) as (url, _):
        with pytest.raises(LanguageToolUnavailable) as error:
            LanguageToolLocalAdapter(url).check("segredo do usuário", frozenset())
    assert "segredo" not in str(error.value)
    assert "private text" not in str(error.value)
    assert "segredo" not in caplog.text


def test_timeout_is_bounded_and_safe():
    with http_server(response(), delay=0.15) as (url, _):
        with pytest.raises(LanguageToolUnavailable):
            LanguageToolLocalAdapter(url, timeout=0.02).check("segredo", frozenset())


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8081", "http://localhost:8081", "http://192.168.1.2:8081",
    "http://example.com:8081", "http://127.0.0.1:8081/path", "http://user:pw@127.0.0.1:8081",
    "http://127.0.0.1:8081?x=1", "http://127.0.0.1:8081#secret", "http://127.0.0.1:0",
])
def test_noncanonical_loopback_url_is_rejected(url):
    with pytest.raises(ValueError):
        LanguageToolLocalAdapter(url)


def test_environment_and_session_proxies_never_receive_user_text(monkeypatch):
    with http_server(response()) as (proxy_url, proxy_requests), http_server(response()) as (url, received):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.setenv(name, proxy_url)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        session = requests.Session()
        session.proxies = {"http": proxy_url}
        LanguageToolLocalAdapter(url, session=session).check("texto reservado", frozenset())
    assert proxy_requests == []
    assert received[0][1]["text"] == ["texto reservado"]


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_never_forwards_post_payload(status):
    with http_server(response()) as (external_url, external_requests):
        with http_server(response(), status=status, location=external_url + "/v2/check") as (url, _):
            with pytest.raises(LanguageToolUnavailable):
                LanguageToolLocalAdapter(url).check("segredo", frozenset())
    assert external_requests == []


@pytest.mark.parametrize("text,source,glossary", [
    ("Kasparov analisou a posição.", "Kasparov", ()),
    ("🙂 Sa\u0303o analisou a posição.", "São", ()),
    ('“Érica analisou a posição.”', "Érica", ()),
    ("Concluiu. Kasparov analisou a posição.", "Kasparov", ()),
    ("Defesa Índia do Rei analisou a posição.", "", ("Defesa Índia do Rei",)),
])
def test_masked_capitalization_requires_hidden_initial_lexical_context(text, source, glossary):
    request = WritingRequest(text, 4, "pt-BR", source_text=source,
                             glossary_terms=frozenset(glossary), grammar_enabled=True)
    protected = protect_text(request)
    start = text.index("analisou")
    offset = len(protected.projected_text[:start].encode("utf-16-le")) // 2
    raw = match(offset, 8, rule_id="UPPERCASE_SENTENCE_START")
    raw["replacements"] = [{"value": "Analisou"}]
    with http_server(response(raw)) as (url, received):
        adapter = LanguageToolLocalAdapter(url)
        # Parsing/check remain lossless. Only the protected-context analysis
        # can establish that this capitalization premise was manufactured.
        assert len(adapter.check(protected.projected_text, frozenset(), text_version=4)) == 1
        assert adapter.analyze(request, protected) == ()
    assert all(post[1]["text"] == [protected.projected_text] for post in received)


@pytest.mark.parametrize("text,source", [
    ("analisou a posição.", ""),
    ("🙂 analisou a posição.", ""),
    ("Kasparov. analisou a posição.", "Kasparov"),
    ("Kasparov! analisou a posição.", "Kasparov"),
    ("Kasparov? analisou a posição.", "Kasparov"),
    ("Kasparov… analisou a posição.", "Kasparov"),
    ("Kasparov\nanalisou a posição.", "Kasparov"),
    ("Kasparov\r\nanalisou a posição.", "Kasparov"),
    ("Kasparov\u2028analisou a posição.", "Kasparov"),
    ("Kasparov\u2029analisou a posição.", "Kasparov"),
    ("Kasparov\x1canalisou a posição.", "Kasparov"),
    ("Kasparov\x1danalisou a posição.", "Kasparov"),
    ("Kasparov\x1eanalisou a posição.", "Kasparov"),
    ("[%eval +0.35] analisou a posição.", ""),
    ("$5 analisou a posição.", ""),
    ("Cd4 analisou a posição.", "Cd4"),
    ("13.Cd4 analisou a posição.", ""),
    ("Kasparov [%eval +0.35] analisou a posição.", "Kasparov"),
    ("kasparov analisou a posição.", "kasparov"),
    ("Kasparov; analisou a posição.", "Kasparov"),
    ("Kasparov errado analisou a posição.", "Kasparov"),
])
def test_masked_capitalization_preserves_boundaries_and_uncertain_context(text, source):
    request = WritingRequest(text, 4, "pt-BR", source_text=source, grammar_enabled=True)
    protected = protect_text(request)
    start = text.index("analisou")
    offset = len(protected.projected_text[:start].encode("utf-16-le")) // 2
    raw = match(offset, 8, rule_id="UPPERCASE_SENTENCE_START")
    raw["replacements"] = [{"value": "Analisou"}]
    with http_server(response(raw)) as (url, _):
        issues = LanguageToolLocalAdapter(url).analyze(request, protected)
    assert len(issues) == 1
    assert (issues[0].start, issues[0].end, issues[0].original) == (start, start + 8, "analisou")
    assert issues[0].suggestions == ("Analisou",)
    issues[0].validate_for(request)


@pytest.mark.parametrize("rule_id,suggestions", [
    ("OTHER_RULE", ("Analisou",)),
    ("UPPERCASE_SENTENCE_START", ("Analisou", "Analisaram")),
    ("UPPERCASE_SENTENCE_START", ()),
])
def test_masked_context_does_not_suppress_other_grammar_edits(rule_id, suggestions):
    request = WritingRequest("Kasparov analisou.", 4, "pt-BR", source_text="Kasparov")
    protected = protect_text(request)
    raw = match(9, 8, rule_id=rule_id)
    raw["replacements"] = [{"value": value} for value in suggestions]
    with http_server(response(raw)) as (url, _):
        assert len(LanguageToolLocalAdapter(url).analyze(request, protected)) == 1


@pytest.mark.parametrize("text,word", [
    ("Se 13.Cd4, então ...", "então"),
    ("Talvez …", "Talvez"),
    ("Talvez\u00a0...", "Talvez"),
    ("🙂 e\u0301 ...", "e\u0301"),
    ("Talvez ...  ", "Talvez"),
])
def test_terminal_ellipsis_preserves_standalone_editorial_punctuation(text, word):
    request = WritingRequest(text, 3, "pt-BR", grammar_enabled=True)
    protected = protect_text(request)
    start = text.index(word)
    punctuation = next(index for index in range(start + len(word), len(text)) if text[index] in ".…")
    offset = len(text[:start].encode("utf-16-le")) // 2
    raw = match(offset, punctuation + 1 - start, rule_id="SPACE_BEFORE_PUNCTUATION2")
    raw["replacements"] = [{"value": word + text[punctuation]}]
    with http_server(response(raw)) as (url, _):
        assert LanguageToolLocalAdapter(url).analyze(request, protected) == ()


@pytest.mark.parametrize("suffix", [
    " .", " ,", " !", " ?", " ;", " :", " ..", " ....", " . . .",
    " ... talvez.", "\n...", "\r\n...", "\u2028...", " ...\u2029", " ...”",
    "\x1c...", "\x1d...", "\x1e...", " ...\x1c", " ...\x1d", " ...\x1e",
])
def test_terminal_ellipsis_does_not_hide_other_spacing_or_boundaries(suffix):
    text = "Talvez" + suffix
    request = WritingRequest(text, 3, "pt-BR", grammar_enabled=True)
    punctuation = next(index for index in range(6, len(text)) if text[index] in ".,…!?;:")
    raw = match(0, punctuation + 1, rule_id="SPACE_BEFORE_PUNCTUATION2")
    raw["replacements"] = [{"value": "Talvez" + text[punctuation]}]
    protected = protect_text(request)
    with http_server(response(raw)) as (url, _):
        issues = LanguageToolLocalAdapter(url).analyze(request, protected)
    assert len(issues) == 1
    assert issues[0].original == protected.projected_text[:punctuation + 1]


@pytest.mark.parametrize("rule_id,suggestions", [
    ("SPACE_BEFORE_PUNCTUATION2", ("Outro.",)),
    ("SPACE_BEFORE_PUNCTUATION2", ("Talvez.", "Outro.")),
    ("OTHER_RULE", ("Talvez.",)),
])
def test_terminal_ellipsis_requires_only_the_same_whitespace_edit(rule_id, suggestions):
    request = WritingRequest("Talvez ...", 3, "pt-BR")
    raw = match(0, 8, rule_id=rule_id)
    raw["replacements"] = [{"value": value} for value in suggestions]
    with http_server(response(raw)) as (url, _):
        assert len(LanguageToolLocalAdapter(url).analyze(request, protect_text(request))) == 1
