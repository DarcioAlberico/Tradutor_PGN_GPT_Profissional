from unittest.mock import patch

from tradutor_pgn.deep_translation import DeepTranslatorAdapter
from tradutor_pgn.translation_api import RequestPacer


class Response:
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.headers = {} if retry_after is None else {'Retry-After': retry_after}
        self.text = '<div class="result-container">Bom jogo</div>'
        self.closed = False

    def close(self):
        self.closed = True


def test_deep_translator_honors_server_wait_on_next_comment():
    first, second = Response(429, '45'), Response(200)
    responses = [first, second]
    pacer = RequestPacer(base_range=(0, 0))
    now = [100.0]
    waits = []

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    with patch('tradutor_pgn.deep_translation.requests.get', side_effect=lambda *a, **kw: responses.pop(0)) as get, \
         patch('time.monotonic', side_effect=lambda: now[0]), patch('time.sleep', side_effect=sleep):
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('Bad position', pacer=pacer) is None
        assert adapter.translate('Good game', pacer=pacer) == 'Bom jogo'
    assert waits == [45]
    assert get.call_count == 2
    assert first.closed
    assert pacer.rate_limited == 1


def test_deep_translator_does_not_retry_during_excessive_server_wait():
    first = Response(429, '999999999999999999999')
    with patch('tradutor_pgn.deep_translation.requests.get', return_value=first) as get:
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('first') is None
        assert adapter.translate('second') is None
    assert get.call_count == 1
    assert first.closed


def test_deep_translator_can_cancel_while_waiting():
    first = Response(503, '45')

    class CancelDuringWait:
        def is_set(self):
            return False

        def wait(self, delay):
            assert 44 <= delay <= 45
            return True

    with patch('tradutor_pgn.deep_translation.requests.get', return_value=first) as get:
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('first') is None
        assert adapter.translate('second', cancel_flag=CancelDuringWait()) is None
    assert get.call_count == 1
    assert first.closed


def test_cooldown_survives_caller_omitting_the_pacer_on_next_call():
    responses = [Response(429, '45'), Response(200)]
    now = [100.0]
    waits = []

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    with patch('tradutor_pgn.deep_translation.requests.get', side_effect=lambda *a, **kw: responses.pop(0)), \
         patch('time.monotonic', side_effect=lambda: now[0]), patch('time.sleep', side_effect=sleep):
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('first', pacer=RequestPacer(base_range=(0, 0))) is None
        assert adapter.translate('second') == 'Bom jogo'
    assert waits == [45]
