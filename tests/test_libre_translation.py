from threading import Event
from tradutor_pgn.libre_translation import LibreTranslator

class Response:
    status_code = 200
    def json(self):
        return {'translatedText': ['Olá', 'mundo']}
    def close(self):
        pass

def test_batch_is_sent_as_array_and_key_is_optional():
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    client = LibreTranslator('http://127.0.0.1:5000', None, 'en', 'pt', post=post)
    assert client.translate_batch(['Hello', 'world'], 'pt', lambda _: None, Event()) == ['Olá', 'mundo']
    assert calls[0][0] == 'http://127.0.0.1:5000/translate'
    assert calls[0][1]['json']['q'] == ['Hello', 'world']
    assert 'api_key' not in calls[0][1]['json']

def test_invalid_batch_response_fails_closed():
    response = Response()
    response.json = lambda: {'translatedText': ['one']}
    client = LibreTranslator('http://localhost:5000', 'secret', 'en', 'pt', post=lambda *a, **kw: response)
    assert client.translate_batch(['a', 'b'], 'pt', lambda _: None, Event()) is None

def test_cancel_prevents_network_call():
    cancel = Event()
    cancel.set()
    client = LibreTranslator('http://localhost:5000', None, 'en', 'pt', post=lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    assert client.translate_batch(['a'], 'pt', lambda _: None, cancel) is None

def test_api_key_is_sent_only_in_payload_and_error_does_not_expose_it():
    calls, logs = [], []
    class Failure:
        status_code = 403
        def close(self):
            pass
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Failure()
    client = LibreTranslator('https://example.org', 'secret', '', 'pt', post=post)
    assert client.translate_batch(['private'], 'pt', logs.append, Event()) is None
    assert calls[0][1]['json']['api_key'] == 'secret'
    assert calls[0][1]['json']['source'] == 'auto'
    assert 'secret' not in str(logs)
    assert calls[0][1]['allow_redirects'] is False


def test_url_rejects_embedded_credentials():
    import pytest
    with pytest.raises(ValueError):
        LibreTranslator('https://user:secret@example.org', None, 'en', 'pt')


def test_provider_is_available_without_llm_key(monkeypatch):
    from types import SimpleNamespace
    from tradutor_pgn import app_actions
    monkeypatch.setattr(app_actions, 'configured_providers', lambda: [])
    monkeypatch.setattr(app_actions, 'load_settings', lambda: {})
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *args: 'libretranslate')
    monkeypatch.setattr(app_actions, 'write_main_window_settings', lambda *args: None)
    app = SimpleNamespace(translation_provider='google')
    assert app_actions.choose_translation_provider(app) == 'libretranslate'
    assert app.translation_provider == 'libretranslate'

def test_worker_sends_structured_batch_and_saves_results(tmp_path, monkeypatch):
    from helpers import WorkerFallbackHarness
    from tradutor_pgn import translation_worker
    calls = []
    class FakeLibre:
        run_label = 'libretranslate'
        def __init__(self, *args):
            pass
        def describe(self):
            return 'LibreTranslate'
        def translate_batch(self, texts, target, log, cancel, contexts=None):
            calls.append(list(texts))
            return [f'<{text}>' for text in texts]
    monkeypatch.setattr(translation_worker, 'LibreTranslator', FakeLibre)
    monkeypatch.setattr(translation_worker.api_keys, 'load_api_key', lambda *args: None)
    harness = WorkerFallbackHarness()
    def no_google(*args, **kwargs):
        raise AssertionError('Google was called')
    app, _ = harness.run_worker(tmp_path, no_google, provider='libretranslate')
    assert calls == [harness.COMMENTS]
    assert harness.stored(tmp_path / 'cache.db') == {text: f'<{text}>' for text in harness.COMMENTS}
    assert not any('[ERRO GERAL]' in line for line in app.logs)
