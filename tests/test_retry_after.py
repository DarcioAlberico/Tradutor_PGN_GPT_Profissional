from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import patch

from tradutor_pgn import translation_api


class Response:
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.headers = {} if retry_after is None else {'Retry-After': retry_after}

    def json(self):
        return [[['Jogada', 'Move']]]


class Session:
    def __init__(self, retry_after, status=429):
        self.responses = [Response(status, retry_after), Response(200)]
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_server_delay_seconds_is_minimum_before_retry():
    session = Session('45')
    with patch.object(translation_api.time, 'sleep') as sleep, \
         patch.object(translation_api, 'retry_delay_seconds', return_value=3):
        assert translation_api.translate_text_chunk('Move', 'pt', session=session) == 'Jogada'
    sleep.assert_called_once_with(45)
    assert session.calls == 2


def test_http_date_is_parsed_against_current_time():
    date = format_datetime(datetime(2026, 11, 7, 12, 1, 0, tzinfo=timezone.utc), usegmt=True)
    assert translation_api.parse_retry_after(date, now=1794052800) == 60
    assert translation_api.parse_retry_after('000000000000000000000000') == 0


def test_invalid_value_falls_back_to_existing_backoff():
    session = Session('not-a-date', status=503)
    with patch.object(translation_api.time, 'sleep') as sleep, \
         patch.object(translation_api, 'retry_delay_seconds', return_value=3):
        assert translation_api.translate_text_chunk('Move', 'pt', session=session) == 'Jogada'
    sleep.assert_called_once_with(3)


def test_excessive_server_delay_stops_instead_of_retrying_early():
    session = Session('999999999999999999999999')
    pacer = translation_api.RequestPacer()
    with patch.object(translation_api.time, 'sleep') as sleep:
        assert translation_api.translate_text_chunk('Move', 'pt', session=session, pacer=pacer) is None
        assert translation_api.translate_text_chunk('Another', 'pt', session=session, pacer=pacer) is None
    sleep.assert_not_called()
    assert session.calls == 1
    assert pacer.rate_limited == 1


def test_cancellation_interrupts_server_wait_before_next_request():
    session = Session('45')

    class CancelDuringWait:
        def is_set(self):
            return False

        def wait(self, timeout):
            assert timeout >= 45
            return True

    assert translation_api.translate_text_chunk(
        'Move', 'pt', session=session, cancel_flag=CancelDuringWait()
    ) is None
    assert session.calls == 1


def test_last_retry_after_is_honored_by_next_comment_in_same_run():
    session = Session('5')
    session.responses = [Response(429, '5'), Response(429, '5'), Response(429, '5'), Response(200)]
    pacer = translation_api.RequestPacer()
    now = [100.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    with patch.object(translation_api.time, 'monotonic', side_effect=lambda: now[0]), \
         patch.object(translation_api.time, 'sleep', side_effect=sleep), \
         patch.object(translation_api, 'retry_delay_seconds', return_value=1):
        assert translation_api.translate_text_chunk('Move', 'pt', session=session, pacer=pacer) is None
        assert translation_api.translate_text_chunk('Next', 'pt', session=session, pacer=pacer) == 'Jogada'
    assert sleeps == [5, 5, 5]


def test_cancel_flag_without_wait_is_checked_during_server_delay():
    session = Session('45')

    class CancelFlag:
        cancelled = False

        def is_set(self):
            return self.cancelled

    flag = CancelFlag()
    with patch.object(translation_api.time, 'sleep', side_effect=lambda _delay: setattr(flag, 'cancelled', True)) as sleep:
        assert translation_api.translate_text_chunk('Move', 'pt', session=session, cancel_flag=flag) is None
    assert sleep.call_args.args[0] <= 0.5
    assert session.calls == 1


def test_cancellation_interrupts_backoff_without_retry_after():
    session = Session(None)

    class CancelDuringWait:
        def is_set(self):
            return False

        def wait(self, delay):
            assert delay > 0
            return True

    with patch.object(translation_api.time, 'sleep'):
        assert translation_api.translate_text_chunk(
            'Move', 'pt', session=session, cancel_flag=CancelDuringWait()
        ) is None
    assert session.calls == 1
