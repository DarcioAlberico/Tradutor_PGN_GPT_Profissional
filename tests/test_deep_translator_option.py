from unittest.mock import patch
from tradutor_pgn import settings


def test_deep_translator_is_a_remembered_translation_provider():
    options = settings.read_main_window_settings({'main_window': {'translation_provider': 'deep-translator'}}, {})
    assert options['translation_provider'] == 'deep-translator'


def test_deep_translator_uses_requested_languages_and_translates():
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.return_value = 'Bom jogo'
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('Good game') == 'Bom jogo'
        factory.assert_called_once_with('en', 'pt')


def test_deep_translator_reports_error_without_exposing_text():
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    log = []
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.side_effect = RuntimeError('private input')
        assert DeepTranslatorAdapter('', 'pt').translate('private input', log.append) is None
    assert log and 'private input' not in str(log)


def test_provider_choice_is_available_without_api_keys(monkeypatch):
    from types import SimpleNamespace
    from tradutor_pgn import app_actions
    monkeypatch.setattr(app_actions, 'configured_providers', lambda: [])
    monkeypatch.setattr(app_actions, 'load_settings', lambda: {})
    monkeypatch.setattr(app_actions, 'ask_translation_provider', lambda *args: 'deep-translator')
    monkeypatch.setattr(app_actions, 'write_main_window_settings', lambda *args: None)
    app = SimpleNamespace(translation_provider='google')
    assert app_actions.choose_translation_provider(app) == 'deep-translator'
    assert app.translation_provider == 'deep-translator'


def test_rate_limit_slows_subsequent_requests():
    from deep_translator.exceptions import TooManyRequests
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    from tradutor_pgn.translation_api import RequestPacer
    pacer = RequestPacer()
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.side_effect = TooManyRequests()
        assert DeepTranslatorAdapter('en', 'pt').translate('test', pacer=pacer) is None
    assert pacer.rate_limited == 1


def test_deep_translator_http_has_timeout_without_modifying_requests(monkeypatch):
    import requests
    import deep_translator.google as google
    from tradutor_pgn.deep_translation import timed_google_translator
    class Response:
        status_code = 200
        text = '<div class="result-container">Bom jogo</div>'
        def close(self): pass
    calls = []
    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return Response()
    monkeypatch.setattr(requests, 'get', fake_get)
    original_module_requests = google.requests
    translator = timed_google_translator('en', 'pt')
    assert translator.translate('Good game') == 'Bom jogo'
    assert calls[0]['timeout'] == 30
    assert google.requests is original_module_requests


def test_long_input_respects_pacing_between_requests(monkeypatch):
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    from tradutor_pgn.translation_api import RequestPacer
    delays = []
    import time
    monkeypatch.setattr(time, 'sleep', delays.append)
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.side_effect = lambda text: text
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('a' * 6000, pacer=RequestPacer(base_range=(2, 2)))
    assert len(delays) == 1 and 1.9 <= delays[0] <= 2


def test_separate_calls_respect_pacing_even_after_rate_limit(monkeypatch):
    from deep_translator.exceptions import TooManyRequests
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    from tradutor_pgn.translation_api import RequestPacer
    now = [100.0]
    waits = []
    monkeypatch.setattr('time.monotonic', lambda: now[0])
    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
    monkeypatch.setattr('time.sleep', sleep)
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.side_effect = [TooManyRequests(), 'resultado']
        pacer = RequestPacer(base_range=(2, 2), first_multiplier=3, growth=1)
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('first', pacer=pacer) is None
        assert adapter.translate('second', pacer=pacer) == 'resultado'
    assert waits == [6]


def test_cancelled_before_repeated_call_does_not_wait(monkeypatch):
    from types import SimpleNamespace
    from tradutor_pgn.deep_translation import DeepTranslatorAdapter
    from tradutor_pgn.translation_api import RequestPacer
    waits = []
    monkeypatch.setattr('time.sleep', waits.append)
    with patch('tradutor_pgn.deep_translation.timed_google_translator') as factory:
        factory.return_value.translate.return_value = 'resultado'
        adapter = DeepTranslatorAdapter('en', 'pt')
        pacer = RequestPacer(base_range=(2, 2))
        assert adapter.translate('first', pacer=pacer) == 'resultado'
        assert adapter.translate('second', cancel_flag=SimpleNamespace(is_set=lambda: True), pacer=pacer) is None
    assert waits == []
