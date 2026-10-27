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
