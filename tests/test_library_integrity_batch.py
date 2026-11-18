from pathlib import Path

import pytest

from tradutor_pgn.library_integrity_batch import (
    BatchIntegrityCanceled, format_integrity_batch, verify_bundles,
)
from tradutor_pgn.translation_library import IntegrityResult, LibraryBundle


def test_batch_checks_all_items_and_reports_progress():
    items = [LibraryBundle(Path(f'book-{n}'), 'ready') for n in range(25)]
    calls, progress = [], []
    def verify(path, should_cancel=None):
        calls.append(path)
        return IntegrityResult('verified', True, True)
    result = verify_bundles(items, verifier=verify, progress=lambda n, total: progress.append((n, total)))
    assert len(calls) == 25 and result.verified == 25
    assert progress[-1] == (25, 25)


def test_batch_separates_mismatch_changed_and_unavailable():
    items = [LibraryBundle(Path(name), 'ready') for name in ('ok', 'wrong', 'changed', 'legacy')]
    statuses = iter(('verified', 'mismatch', 'changed', 'unavailable'))
    result = verify_bundles(items, verifier=lambda *_a, **_k: IntegrityResult(next(statuses)))
    assert (result.verified, result.mismatch, result.changed, result.unavailable) == (1, 1, 1, 1)
    text = format_integrity_batch(result)
    assert 'hash' in text.lower() and 'autentic' in text.lower()


def test_failure_examples_are_limited_and_contain_no_absolute_paths():
    items = [LibraryBundle(Path('C:/private') / f'book-{n}', 'ready') for n in range(15)]
    result = verify_bundles(items, verifier=lambda *_a, **_k: IntegrityResult('mismatch'), max_examples=3)
    assert len(result.examples) == 3 and result.mismatch == 15
    text = format_integrity_batch(result)
    assert '12' in text and 'private' not in text


def test_cancel_discards_partial_result_and_stops():
    items = [LibraryBundle(Path(f'book-{n}'), 'ready') for n in range(3)]
    calls = []
    def verify(path, should_cancel=None):
        calls.append(path)
        return IntegrityResult('verified')
    with pytest.raises(BatchIntegrityCanceled):
        verify_bundles(items, verifier=verify, should_cancel=lambda: len(calls) >= 1)
    assert len(calls) == 1


def test_cancel_from_verifier_also_discards_results():
    items = [LibraryBundle(Path('book'), 'ready')]
    with pytest.raises(BatchIntegrityCanceled):
        verify_bundles(items, verifier=lambda *_a, **_k: IntegrityResult('canceled'))


def test_real_packages_and_legacy_are_verified_without_mutating_files(tmp_path):
    from tradutor_pgn.translation_library import list_bundles
    from tradutor_pgn.translation_output import publish_translation_bundle
    source = tmp_path / 'input.pgn'
    source.write_text('original', encoding='utf-8')
    root = tmp_path / 'library'
    def generate(path):
        Path(path).write_text('translated', encoding='utf-8')
        return True
    first = publish_translation_bundle(str(source), 'pt', str(root), generate)
    second = publish_translation_bundle(str(source), 'pt', str(root), generate)
    Path(second.translated_path).write_text('changed', encoding='utf-8')
    (root / 'legacy').mkdir()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = verify_bundles(list_bundles(root))
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert first.status == second.status == 'published'
    assert (result.verified, result.mismatch, result.unavailable) == (1, 1, 1)
    assert before == after


def test_unexpected_status_does_not_create_a_success_report():
    with pytest.raises(ValueError):
        verify_bundles([LibraryBundle(Path('book'), 'ready')],
                       verifier=lambda *_a, **_k: IntegrityResult('unknown'))
