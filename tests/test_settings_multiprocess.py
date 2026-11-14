import json
import os
import subprocess
import sys
import time

import pytest


CHILD = r'''
import sys, time
from pathlib import Path
from tradutor_pgn.settings import update_settings
path, started, entered, release, key = map(Path, sys.argv[1:])
started.write_text('started')
def mutate(data):
    entered.write_text('entered')
    if str(key) == 'first':
        deadline = time.monotonic() + 15
        while not release.exists():
            if time.monotonic() > deadline: raise TimeoutError('release missing')
            time.sleep(.01)
    data[str(key)] = 'preserved'
update_settings(mutate, str(path))
'''


def wait_for(path, timeout=10):
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert path.exists(), f'process did not reach {path.name}'


def test_concurrent_processes_serialize_read_modify_write(tmp_path):
    path = tmp_path / 'settings.json'
    first_started, first_entered = tmp_path / 'first-started', tmp_path / 'first-entered'
    second_started, second_entered = tmp_path / 'second-started', tmp_path / 'second-entered'
    release = tmp_path / 'release'
    first = subprocess.Popen([sys.executable, '-c', CHILD, str(path), str(first_started),
                              str(first_entered), str(release), 'first'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = None
    try:
        wait_for(first_entered)
        second = subprocess.Popen([sys.executable, '-c', CHILD, str(path), str(second_started),
                                   str(second_entered), str(release), 'second'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_for(second_started)
        deadline = time.monotonic() + 1
        while not second_entered.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        entered_too_early = second_entered.exists()
    finally:
        release.write_text('go')
        first_output = first.communicate(timeout=20)
        second_output = second.communicate(timeout=20) if second is not None else (b'', b'')
    assert not entered_too_early, 'second process entered while the first held the update'
    assert first.returncode == 0, first_output
    assert second is not None and second.returncode == 0, second_output
    assert json.loads(path.read_text(encoding='utf-8')) == {'first': 'preserved', 'second': 'preserved'}


def test_crashed_writer_does_not_permanently_hold_lock(tmp_path):
    path = tmp_path / 'settings.json'
    script = '''
import os, sys
from tradutor_pgn.settings import update_settings
def crash(data):
    data['unfinished'] = True
    os._exit(0)
update_settings(crash, sys.argv[1])
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], timeout=20)
    assert result.returncode == 0
    from tradutor_pgn.settings import update_settings
    update_settings(lambda data: data.update({'recovered': True}), str(path))
    assert json.loads(path.read_text(encoding='utf-8')) == {'recovered': True}


def test_lock_timeout_does_not_modify_settings(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"existing": true}', encoding='utf-8')
    started, entered, release = tmp_path / 'started', tmp_path / 'entered', tmp_path / 'release'
    first = subprocess.Popen([sys.executable, '-c', CHILD, str(path), str(started),
                              str(entered), str(release), 'first'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    script = '''
import sys
from tradutor_pgn import settings
settings.SETTINGS_LOCK_TIMEOUT_SECONDS = 0.15
warnings = []
settings.set_settings_warning_handler(warnings.append)
try:
    settings.update_settings(lambda data: data.update({'intruder': True}), sys.argv[1])
except TimeoutError:
    sys.exit(0 if warnings else 3)
sys.exit(2)
'''
    try:
        wait_for(entered)
        second = subprocess.run([sys.executable, '-c', script, str(path)],
                                capture_output=True, timeout=20)
        assert second.returncode == 0, second.stderr
        assert json.loads(path.read_text(encoding='utf-8')) == {'existing': True}
    finally:
        release.write_text('go')
        output = first.communicate(timeout=20)
    assert first.returncode == 0, output
    assert json.loads(path.read_text(encoding='utf-8')) == {'existing': True, 'first': 'preserved'}


def test_existing_empty_lock_file_is_not_modified(tmp_path):
    from tradutor_pgn import settings
    path = tmp_path / 'settings.json'
    lock = tmp_path / 'settings.json.lock'
    lock.write_bytes(b'')
    settings.update_settings(lambda data: data.update({'value': 1}), str(path))
    assert lock.read_bytes() == b''


def test_lock_open_failure_warns_and_preserves_settings(tmp_path, monkeypatch):
    import builtins
    from tradutor_pgn import settings
    path = tmp_path / 'settings.json'
    path.write_text('{"safe": true}', encoding='utf-8')
    warnings = []
    old = settings.set_settings_warning_handler(warnings.append)
    original_open = builtins.open

    def failing_open(name, *args, **kwargs):
        if str(name).endswith('.lock'):
            raise PermissionError('not accessible')
        return original_open(name, *args, **kwargs)

    monkeypatch.setattr(settings, 'open', failing_open, raising=False)
    try:
        with pytest.raises(PermissionError):
            settings.update_settings(lambda data: data.update({'new': 1}), str(path))
    finally:
        settings.set_settings_warning_handler(old)
    assert warnings
    assert json.loads(path.read_text(encoding='utf-8')) == {'safe': True}


def test_unlock_failure_does_not_mask_update_outcome(tmp_path, monkeypatch):
    from tradutor_pgn import settings
    if os.name == 'nt':
        import msvcrt
        original = msvcrt.locking

        def locking(fd, operation, size):
            if operation == msvcrt.LK_UNLCK:
                raise OSError('unlock failed')
            return original(fd, operation, size)

        monkeypatch.setattr(msvcrt, 'locking', locking)
    else:
        import fcntl
        original = fcntl.flock

        def flock(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError('unlock failed')
            return original(fd, operation)

        monkeypatch.setattr(fcntl, 'flock', flock)

    path = tmp_path / 'settings.json'
    settings.update_settings(lambda data: data.update({'saved': True}), str(path))
    assert json.loads(path.read_text(encoding='utf-8')) == {'saved': True}

    def fail(_data):
        raise ValueError('original failure')

    with pytest.raises(ValueError, match='original failure'):
        settings.update_settings(fail, str(path))
