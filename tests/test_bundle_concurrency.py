from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock
from contextlib import contextmanager
import time
import json
import subprocess
import sys
import os
from unittest.mock import Mock, patch

from tradutor_pgn.translation_output import publish_translation_bundle
from tradutor_pgn.pgn_utils import translated_bundle_paths
from tradutor_pgn.translation_library import verify_bundle
from tradutor_pgn import translation_output


def test_simultaneous_publications_get_distinct_complete_bundles(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    output = tmp_path / "out"
    barrier = Barrier(2)

    def publish(content):
        def generate(path):
            Path(path).write_text(content, encoding="utf8")
            barrier.wait(timeout=10)
            return True
        return publish_translation_bundle(str(source), "pt", str(output), generate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ["primeiro", "segundo"]))
    assert [r.status for r in results] == ["published", "published"]
    assert len({r.bundle_dir for r in results}) == 2
    assert {Path(r.translated_path).read_text(encoding="utf8") for r in results} == {"primeiro", "segundo"}
    for result in results:
        manifest = json.loads((Path(result.bundle_dir) / "manifesto.json").read_text(encoding="utf8"))
        assert manifest["files"]["translation"]["path"] == Path(result.translated_path).name
        assert verify_bundle(result.bundle_dir).status == "verified"


def test_separate_processes_publish_same_name_without_conflict(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    code = """
import json, sys, time
from pathlib import Path
from tradutor_pgn.translation_output import publish_translation_bundle
source, root, name, sync = sys.argv[1:]
def generate(path):
    Path(path).write_text(name, encoding='utf8')
    (Path(sync) / (name + '.ready')).write_text('ready')
    deadline = time.monotonic() + 10
    while len(list(Path(sync).glob('*.ready'))) < 2:
        if time.monotonic() > deadline: raise TimeoutError('barreira')
        time.sleep(0.01)
    return True
result = publish_translation_bundle(source, 'pt', root, generate)
print(json.dumps({'status': result.status, 'bundle': result.bundle_dir, 'error': str(result.error)}))
"""
    processes = [subprocess.Popen([sys.executable, "-c", code, str(source), str(root), name, str(tmp_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for name in ("first", "second")]
    try:
        outputs = [process.communicate(timeout=20) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert all(process.returncode == 0 for process in processes), outputs
    results = [json.loads(stdout) for stdout, _stderr in outputs]
    assert [result["status"] for result in results] == ["published", "published"]
    assert len({result["bundle"] for result in results}) == 2


def test_collision_can_rename_files_without_overwriting_original(tmp_path):
    source = tmp_path / "game-BR-2.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    barrier = Barrier(2)

    def publish(content):
        def generate(path):
            Path(path).write_text(content, encoding="utf8")
            barrier.wait(timeout=10)
            return True
        return publish_translation_bundle(str(source), "pt", str(root), generate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ["primeiro", "segundo"]))
    assert all(result.status == "published" for result in results)
    assert all(Path(result.original_path).read_text(encoding="utf8") == "original" for result in results)
    for result in results:
        manifest = json.loads((Path(result.bundle_dir) / "manifesto.json").read_text(encoding="utf8"))
        assert manifest["files"]["original"]["path"] == Path(result.original_path).name
        assert manifest["files"]["translation"]["path"] == Path(result.translated_path).name


def test_failed_collision_rename_keeps_existing_package_and_source(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    def generate(path):
        Path(path).write_text("traduzido", encoding="utf8")
        occupied = root / "game-BR"
        occupied.mkdir()
        (occupied / "existente.txt").write_text("preservado", encoding="utf8")
        return True
    actual_replace = os.replace
    def fail_rename(src, dst):
        if ".renomear-" in str(dst):
            raise OSError("falha injetada")
        return actual_replace(src, dst)
    with patch("tradutor_pgn.translation_output.os.replace", side_effect=fail_rename):
        result = publish_translation_bundle(str(source), "pt", str(root), generate)
    assert result.status == "failed"
    assert source.read_text(encoding="utf8") == "original"
    assert (root / "game-BR" / "existente.txt").read_text(encoding="utf8") == "preservado"
    assert not (root / "game-BR-2").exists()
    assert not list(root.glob("*.tmp-*"))


def test_dangling_link_name_is_treated_as_occupied(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    occupied = root / "game-BR"
    real_lexists = os.path.lexists
    def lexists(path):
        return str(path) == str(occupied) or real_lexists(path)
    with patch("tradutor_pgn.pgn_utils.os.path.lexists", side_effect=lexists):
        bundle, _original, _translation = translated_bundle_paths(str(tmp_path / "game.pgn"), "pt", str(root))
    assert Path(bundle).name == "game-BR-2"


def test_cancel_immediately_before_publication_leaves_no_bundle(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    def generate(path):
        Path(path).write_text("tradução", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(root), generate,
                                        is_canceled=lambda: (root / ".publicacao.lock").exists())
    assert result.status == "canceled"
    assert not any(path.is_dir() for path in root.iterdir())
    assert source.read_text(encoding="utf8") == "original"


def test_cancel_during_source_copy_discards_partial_bundle(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_bytes(b"x" * (3 * 1024 * 1024))
    root = tmp_path / "out"
    def generate(path):
        Path(path).write_bytes(b"traduzido")
        return True
    observed_sizes = []
    def canceled():
        for path in root.glob(".game-BR.tmp-*/game.pgn"):
            size = path.stat().st_size
            if size >= 1024 * 1024:
                observed_sizes.append(size)
                return True
        return False
    result = publish_translation_bundle(str(source), "pt", str(root), generate, is_canceled=canceled)
    assert result.status == "canceled"
    assert observed_sizes[0] < source.stat().st_size
    assert not any(path.is_dir() for path in root.iterdir())
    assert source.stat().st_size == 3 * 1024 * 1024


def test_cancel_during_translation_hash_discards_partial_bundle(tmp_path):
    import hashlib
    source = tmp_path / "game.pgn"
    source.write_bytes(b"original")
    root = tmp_path / "out"
    original_sha256 = hashlib.sha256
    processed = []
    class Digest:
        def __init__(self):
            self.digest = original_sha256()
        def update(self, chunk):
            if chunk.startswith(b"y"):
                processed.append(len(chunk))
            self.digest.update(chunk)
        def hexdigest(self):
            return self.digest.hexdigest()
    def generate(path):
        Path(path).write_bytes(b"y" * (3 * 1024 * 1024))
        return True
    with patch("tradutor_pgn.translation_output.hashlib.sha256", side_effect=Digest):
        result = publish_translation_bundle(str(source), "pt", str(root), generate,
                                            is_canceled=lambda: bool(processed))
    assert result.status == "canceled"
    assert sum(processed) < 3 * 1024 * 1024
    assert not any(path.is_dir() for path in root.iterdir())


def test_initial_fingerprint_can_be_cancelled_before_extraction(tmp_path):
    from types import SimpleNamespace
    from threading import Event
    from tradutor_pgn import translation_worker
    from tradutor_pgn.translation_output import _PublicationCanceled
    source = tmp_path / "game.pgn"
    source.write_bytes(b"original")
    flag = Event()
    app = SimpleNamespace(cancel_flag=flag, log_message=Mock())
    def stopped(_path, is_canceled=None):
        flag.set()
        assert is_canceled is not None and is_canceled()
        raise _PublicationCanceled()
    with patch.object(translation_worker, "source_sha256", side_effect=stopped), \
         patch.object(translation_worker, "extract_comment_texts_from_file") as extract:
        assert translation_worker._first_pass(app, [str(source)]) is None
    extract.assert_not_called()


def test_fingerprint_cancellation_after_extraction_discards_first_pass(tmp_path):
    from types import SimpleNamespace
    from tradutor_pgn import translation_worker
    from tradutor_pgn.translation_output import _PublicationCanceled
    source = tmp_path / "game.pgn"
    source.write_bytes(b"original")
    flag = Event()
    app = SimpleNamespace(cancel_flag=flag, log_message=Mock())
    def digest(_path, _cancel):
        if flag.is_set():
            raise _PublicationCanceled()
        return "hash"
    def extract(*_args, **_kwargs):
        flag.set()
        return {"comments": ["example"]}
    with patch.object(translation_worker, "source_sha256", side_effect=digest), \
         patch.object(translation_worker, "extract_comment_texts_from_file", side_effect=extract):
        assert translation_worker._first_pass(app, [str(source)]) is None


def test_cancel_while_waiting_for_publication_lock_returns_promptly(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    generated, cancel, waiting = Event(), Event(), Event()
    held_lock = Lock()
    held_lock.acquire()
    class ObservedLock:
        def acquire(self, *args, **kwargs):
            waiting.set()
            return held_lock.acquire(*args, **kwargs)
        def release(self):
            held_lock.release()
        def __enter__(self):
            self.acquire()
            return self
        def __exit__(self, *_args):
            self.release()
    def generate(path):
        Path(path).write_text("tradução", encoding="utf8")
        generated.set()
        return True
    with patch.object(translation_output, "_BUNDLE_PUBLICATION_LOCK", ObservedLock()), \
         ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(publish_translation_bundle, str(source), "pt", str(root), generate, cancel.is_set)
            assert generated.wait(5)
            assert waiting.wait(5)
            assert not future.done()
            cancel.set()
            assert future.result(timeout=2).status == "canceled"
        finally:
            held_lock.release()
    assert not any(path.is_dir() for path in root.iterdir())


def test_cancel_while_another_process_holds_publication_lock(tmp_path):
    source = tmp_path / "game.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    root.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"
    code = """
import sys, time
from pathlib import Path
from tradutor_pgn.settings import _settings_lock_handle
with _settings_lock_handle(sys.argv[1]):
    Path(sys.argv[2]).write_text('ready')
    deadline = time.monotonic() + 15
    while not Path(sys.argv[3]).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(root / ".publicacao"), str(ready), str(release)])
    waiting, cancel = Event(), Event()
    original_lock = translation_output._settings_lock_handle
    @contextmanager
    def observed_lock(*args, **kwargs):
        waiting.set()
        with original_lock(*args, **kwargs):
            yield
    def generate(path):
        Path(path).write_text("traduzido", encoding="utf8")
        return True
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        with patch.object(translation_output, "_settings_lock_handle", observed_lock), \
             ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(publish_translation_bundle, str(source), "pt", str(root), generate, cancel.is_set)
                assert waiting.wait(5)
                cancel.set()
                assert future.result(timeout=2).status == "canceled"
            finally:
                release.write_text("release", encoding="utf8")
    finally:
        release.touch()
        process.wait(timeout=10)
    assert not any(path.is_dir() for path in root.iterdir())
