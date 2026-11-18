from tradutor_pgn.database import (
    initialize_database, record_occurrences, resolve_comment_ids, save_translation, set_review_status_by_id,
)
from tradutor_pgn.translation_library_links import bundle_review_progress
from test_library_review_progress import create_linked


def test_progress_separates_doubt_rejected_and_pending_quality_warnings(tmp_path):
    db, bundle, _ = create_linked(tmp_path)
    conn = initialize_database(str(db))
    cur = conn.cursor()
    for text in ('third', 'fourth'):
        save_translation(cur, text, text, 'pt', 'en')
    ids = resolve_comment_ids(cur, 'pt', ['hello', 'world', 'third', 'fourth'], 'en')
    original = str(tmp_path / 'livro.pgn')
    record_occurrences(cur, original, [(1, 1, 1, 'hello'), (2, 1, 2, 'hello'), (3, 1, 3, 'world'),
                                       (4, 1, 4, 'third'), (5, 1, 5, 'fourth')], ids)
    set_review_status_by_id(cur, ids['world'], 'rejected')
    set_review_status_by_id(cur, ids['third'], 'doubt')
    for text, flag in [('hello', 1), ('world', 1), ('third', 1), ('fourth', 0)]:
        cur.execute('UPDATE comments SET quality_warning=? WHERE id=?', (flag, ids[text]))
    conn.commit()
    conn.close()
    result = bundle_review_progress(db, bundle)
    assert (result.total, result.verified, result.pending) == (4, 1, 3)
    assert (result.doubt, result.rejected, result.pending_warnings, result.pending_without_warnings) == (1, 1, 2, 1)


def test_cancel_before_lookup_does_not_return_partial_counts(tmp_path):
    db, bundle, _ = create_linked(tmp_path)
    result = bundle_review_progress(db, bundle, should_cancel=lambda: True)
    assert result.status == 'canceled'
    assert result.total is None and result.pending_warnings is None


def test_cancel_during_integrity_verification_has_no_counts(tmp_path, monkeypatch):
    from threading import Event
    from tradutor_pgn import translation_library
    db, bundle, _ = create_linked(tmp_path)
    canceled = Event()
    original = translation_library._hash_file
    def stop_during_hash(path, should_cancel=None):
        canceled.set()
        return original(path, should_cancel)
    monkeypatch.setattr(translation_library, '_hash_file', stop_during_hash)
    result = bundle_review_progress(db, bundle, should_cancel=canceled.is_set)
    assert result.status == 'canceled' and result.total is None


def test_cancel_after_database_query_discards_counts(tmp_path, monkeypatch):
    from threading import Event
    from tradutor_pgn import database
    db, bundle, _ = create_linked(tmp_path)
    canceled = Event()
    original = database.get_review_status_counts
    def query(*args, **kwargs):
        result = original(*args, **kwargs)
        canceled.set()
        return result
    monkeypatch.setattr(database, 'get_review_status_counts', query)
    result = bundle_review_progress(db, bundle, should_cancel=canceled.is_set)
    assert result.status == 'canceled' and result.total is None


def test_cancel_after_an_unsuccessful_resolution_takes_precedence(tmp_path, monkeypatch):
    from threading import Event
    from tradutor_pgn import translation_library_links
    canceled = Event()
    def resolve(*args, **kwargs):
        canceled.set()
        return translation_library_links.ReviewResolution('integrity')
    monkeypatch.setattr(translation_library_links, 'resolve_bundle_review', resolve)
    result = bundle_review_progress(tmp_path / 'db', tmp_path / 'bundle', should_cancel=canceled.is_set)
    assert result.status == 'canceled' and result.total is None
