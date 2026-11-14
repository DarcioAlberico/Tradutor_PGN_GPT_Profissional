import subprocess
import sys
from unittest.mock import patch

import pytest

from tradutor_pgn.deep_translation import DeepTranslatorAdapter
from tradutor_pgn.google_cooldown import GoogleCooldown
from tradutor_pgn.translation_api import RequestPacer, translate_text_chunk


class Shared:
    def __init__(self, allow=True, fail=False):
        self.allow = allow
        self.fail = fail
        self.waited = 0
        self.delays = []

    def wait(self, cancel_flag=None):
        self.waited += 1
        if self.fail:
            raise OSError('private path')
        return self.allow

    def defer(self, delay):
        if self.fail:
            raise OSError('private path')
        self.delays.append(delay)


class Response:
    text = '<div class="result-container">Bom jogo</div>'

    def __init__(self, status, header=None):
        self.status_code = status
        self.headers = {} if header is None else {'Retry-After': header}

    def close(self):
        pass

    def json(self):
        return [[['Bom jogo', 'Good game']]]


@pytest.mark.parametrize(('status', 'header', 'delay'), [
    (429, None, 30), (429, '60', 60), (403, None, 300), (403, '600', 600),
])
def test_gtx_records_shared_cooldown(status, header, delay):
    shared = Shared()
    pacer = RequestPacer(shared_cooldown=shared)
    with patch('tradutor_pgn.translation_api.requests.get', return_value=Response(status, header)), \
         patch('tradutor_pgn.translation_api.time.sleep'):
        assert translate_text_chunk('text', 'pt', pacer=pacer) is None
    assert shared.delays and all(value == delay for value in shared.delays)
    assert shared.waited >= 1


def test_unavailable_shared_control_never_sends_text_or_logs_paths():
    pacer = RequestPacer(shared_cooldown=Shared(fail=True))
    logs = []
    with patch('tradutor_pgn.translation_api.requests.get') as get:
        assert translate_text_chunk('secret text', 'pt', logs.append, pacer=pacer) is None
    get.assert_not_called()
    assert 'private path' not in repr(logs)
    assert 'secret text' not in repr(logs)


def test_failed_cooldown_write_blocks_further_requests_in_same_run():
    class CannotWrite(Shared):
        def defer(self, delay):
            raise OSError('private path')

    pacer = RequestPacer(shared_cooldown=CannotWrite())
    logs = []
    with patch('tradutor_pgn.translation_api.requests.get', return_value=Response(429)) as get:
        assert translate_text_chunk('one', 'pt', logs.append, pacer=pacer) is None
        assert translate_text_chunk('two', 'pt', logs.append, pacer=pacer) is None
    assert get.call_count == 1
    assert 'private path' not in repr(logs)


def test_corrupted_shared_database_prevents_real_request(tmp_path):
    path = tmp_path / 'cooldown.db'
    path.write_bytes(b'not a database')
    pacer = RequestPacer(shared_cooldown=GoogleCooldown(path))
    with patch('requests.get') as get:
        assert translate_text_chunk('one', 'pt', pacer=pacer) is None
    get.assert_not_called()


def test_deep_translator_records_429_and_waits_before_network():
    shared = Shared()
    pacer = RequestPacer(shared_cooldown=shared)
    with patch('tradutor_pgn.deep_translation.requests.get', return_value=Response(429, '60')) as get:
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('text', pacer=pacer) is None
    assert get.call_count == 1
    assert shared.waited >= 1
    assert shared.delays == [60]


def test_deep_translator_does_not_send_if_shared_control_fails():
    pacer = RequestPacer(shared_cooldown=Shared(fail=True))
    logs = []
    with patch('tradutor_pgn.deep_translation.requests.get') as get:
        adapter = DeepTranslatorAdapter('en', 'pt')
        assert adapter.translate('private', logs.append, pacer=pacer) is None
    get.assert_not_called()
    assert 'private path' not in repr(logs)
    assert 'private' not in repr(logs)


@pytest.mark.parametrize('provider', ['gtx', 'deep'])
def test_cancelled_during_shared_check_never_sends(provider):
    import threading

    flag = threading.Event()

    class CancellingShared(Shared):
        def wait(self, cancel_flag=None):
            flag.set()
            return True

    pacer = RequestPacer(shared_cooldown=CancellingShared())
    with patch('requests.get') as get:
        if provider == 'gtx':
            assert translate_text_chunk('secret', 'pt', cancel_flag=flag, pacer=pacer) is None
        else:
            assert DeepTranslatorAdapter('en', 'pt').translate('secret', cancel_flag=flag, pacer=pacer) is None
    get.assert_not_called()


def test_deep_translator_respects_403_retry_after():
    shared = Shared()
    pacer = RequestPacer(shared_cooldown=shared)
    with patch('tradutor_pgn.deep_translation.requests.get', return_value=Response(403, '600')):
        assert DeepTranslatorAdapter('en', 'pt').translate('text', pacer=pacer) is None
    assert shared.delays == [600]


def test_two_processes_share_a_403_cooldown_without_real_network(tmp_path):
    path = tmp_path / 'cooldown.db'
    recorder = '''
import sys
from tradutor_pgn.google_cooldown import GoogleCooldown
from tradutor_pgn.translation_api import RequestPacer, translate_text_chunk
class Response:
    status_code = 403
    headers = {}
class Session:
    def get(self, *args, **kwargs): return Response()
translate_text_chunk("one", "pt", session=Session(), pacer=RequestPacer(shared_cooldown=GoogleCooldown(sys.argv[1])))
'''
    checker = '''
import sys
from tradutor_pgn.google_cooldown import GoogleCooldown
from tradutor_pgn.translation_api import RequestPacer, translate_text_chunk
class Cancel:
    def is_set(self): return False
    def wait(self, delay): return True
class Session:
    def get(self, *args, **kwargs): raise AssertionError("network should not be reached")
assert translate_text_chunk("two", "pt", session=Session(), cancel_flag=Cancel(), pacer=RequestPacer(shared_cooldown=GoogleCooldown(sys.argv[1]))) is None
assert GoogleCooldown(sys.argv[1]).remaining() > 290
'''
    for script in (recorder, checker):
        completed = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True, text=True, timeout=20)
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('provider', ['gtx', 'deep'])
def test_both_google_adapters_reserve_quota_before_every_request(tmp_path, provider):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 100)
    pacer = RequestPacer(base_range=(0, 0), shared_cooldown=control)

    class CancelWhileWaiting:
        def is_set(self):
            return False

        def wait(self, _delay):
            return True

    with patch('requests.get', return_value=Response(200)) as get:
        if provider == 'gtx':
            assert translate_text_chunk('Good game', 'pt', pacer=pacer) == 'Bom jogo'
            assert translate_text_chunk('Other', 'pt', pacer=pacer, cancel_flag=CancelWhileWaiting()) is None
        else:
            adapter = DeepTranslatorAdapter('en', 'pt')
            assert adapter.translate('Good game', pacer=pacer) == 'Bom jogo'
            assert adapter.translate('Other', pacer=pacer, cancel_flag=CancelWhileWaiting()) is None
    assert get.call_count == 1


def test_deep_translator_internal_retry_also_reserves_quota(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 100)
    pacer = RequestPacer(base_range=(0, 0), shared_cooldown=control)
    response = Response(200)
    response.text = '<div class="result-container">Same</div>'

    class CancelWhileWaiting:
        def is_set(self):
            return False

        def wait(self, _delay):
            return True

    with patch('requests.get', return_value=response) as get:
        adapter = DeepTranslatorAdapter('en', 'pt')
        adapter.client._url_params['hl'] = 'en'
        assert adapter.translate('Same', pacer=pacer, cancel_flag=CancelWhileWaiting()) is None
    assert get.call_count == 1
