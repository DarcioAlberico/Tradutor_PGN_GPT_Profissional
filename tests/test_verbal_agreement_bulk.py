from contextlib import closing
import os

import pytest

from tradutor_pgn.database import (
    WritingConflictError, apply_identical_replacements, initialize_database,
    preview_identical_replacements, record_occurrences, resolve_comment_ids,
    save_translation, undo_identical_replacements,
)
from tradutor_pgn.verbal_agreement_bulk import VerbalPreviewCancelled, filter_verbal_preview
from tradutor_pgn.writing_types import WritingIssue, WritingRequest, WritingResult


def make_issue(text, original='domina', replacement='dominam', *, rule='GENERAL_VERB_AGREEMENT_ERRORS', version=0, start=None):
    start = text.index(original) if start is None else start
    return WritingIssue('', rule, 'VERBAL_AGREEMENT', start, start + len(original), original,
                        'Concordância verbal', '', (replacement,), 'warning', 'languagetool', version)


def setup_preview(tmp_path, texts):
    conn = initialize_database(str(tmp_path / 'cache.db'))
    cur = conn.cursor()
    originals = [f'source {n}' for n in range(len(texts))]
    for source, text in zip(originals, texts):
        save_translation(cur, source, text, 'pt', 'en')
    ids = resolve_comment_ids(cur, 'pt', originals, 'en')
    book = str(tmp_path / 'book.pgn')
    record_occurrences(cur, book, [(n + 1, 1, n + 1, source) for n, source in enumerate(originals)], ids)
    conn.commit()
    preview = preview_identical_replacements(conn, book, 'pt', 'domina', 'dominam')
    return conn, preview


class ContextualAssistant:
    def analyze(self, request):
        issues = []
        if 'Os bispos domina' in request.text:
            start = request.text.index('Os bispos domina') + len('Os bispos ')
            issues.append(make_issue(request.text, version=request.text_version, start=start))
        return WritingResult(request.text_version, tuple(issues), 'full')


def test_batch_applies_only_verbal_issues_reconfirmed_in_context_and_undoes(tmp_path):
    texts = ['Os bispos domina. O bispo domina.', 'O bispo domina.', 'Os bispos domina.']
    conn, preview = setup_preview(tmp_path, texts)
    request = WritingRequest(texts[0], 0, 'pt', grammar_enabled=True)
    issue = make_issue(texts[0])
    filtered = filter_verbal_preview(preview, issue, request, ContextualAssistant())
    assert filtered.count == 2 and len(filtered.rows) == 2
    operation = apply_identical_replacements(conn, filtered)
    assert [row[0] for row in conn.execute('SELECT translated_comment FROM comments ORDER BY id')] == [
        'Os bispos dominam. O bispo domina.', 'O bispo domina.', 'Os bispos dominam.']
    undo_identical_replacements(conn, operation)
    assert [row[0] for row in conn.execute('SELECT translated_comment FROM comments ORDER BY id')] == texts
    conn.close()


def test_only_same_rule_and_suggestion_are_accepted(tmp_path):
    conn, preview = setup_preview(tmp_path, ['Os bispos domina.', 'Os bispos domina.'])
    request = WritingRequest('Os bispos domina.', 0, 'pt', grammar_enabled=True)
    class OtherRule:
        def analyze(self, request):
            return WritingResult(request.text_version, (make_issue(request.text, rule='OTHER', version=request.text_version),), 'full')
    filtered = filter_verbal_preview(preview, make_issue(request.text), request, OtherRule())
    assert filtered.count == 0
    conn.close()


def test_unavailable_grammar_aborts_instead_of_partial_result(tmp_path):
    conn, preview = setup_preview(tmp_path, ['Os bispos domina.', 'Os bispos domina.'])
    request = WritingRequest('Os bispos domina.', 0, 'pt', grammar_enabled=True)
    class Offline:
        def analyze(self, request):
            return WritingResult(request.text_version, (), 'spelling_only', 'indisponível')
    with pytest.raises(ValueError, match='concordância'):
        filter_verbal_preview(preview, make_issue(request.text), request, Offline())
    assert conn.execute('SELECT COUNT(*) FROM writing_bulk_rows').fetchone()[0] == 0
    conn.close()


def test_snapshot_change_rejects_contextually_filtered_batch(tmp_path):
    conn, preview = setup_preview(tmp_path, ['Os bispos domina.'])
    request = WritingRequest('Os bispos domina.', 0, 'pt', grammar_enabled=True)
    filtered = filter_verbal_preview(preview, make_issue(request.text), request, ContextualAssistant())
    with closing(initialize_database(str(tmp_path / 'cache.db'))) as other:
        other.execute("UPDATE comments SET translated_comment='alterado', writing_revision=writing_revision+1")
        other.commit()
    with pytest.raises(WritingConflictError):
        apply_identical_replacements(conn, filtered)
    assert conn.execute('SELECT translated_comment FROM comments').fetchone()[0] == 'alterado'
    conn.close()


def test_cancellation_stops_preview_without_writing(tmp_path):
    conn, preview = setup_preview(tmp_path, ['Os bispos domina.'])
    request = WritingRequest('Os bispos domina.', 0, 'pt', grammar_enabled=True)
    with pytest.raises(VerbalPreviewCancelled):
        filter_verbal_preview(preview, make_issue(request.text), request, ContextualAssistant(),
                              cancelled=lambda: True)
    assert conn.execute('SELECT translated_comment FROM comments').fetchone()[0] == request.text
    conn.close()


def test_disabled_grammar_cannot_authorize_batch(tmp_path):
    conn, preview = setup_preview(tmp_path, ['Os bispos domina.'])
    request = WritingRequest('Os bispos domina.', 0, 'pt', grammar_enabled=False)
    with pytest.raises(ValueError):
        filter_verbal_preview(preview, make_issue(request.text), request, ContextualAssistant())
    conn.close()


@pytest.mark.skipif(os.environ.get('PGN_TEST_REAL_LANGUAGETOOL') != '1', reason='requires local LanguageTool')
def test_real_languagetool_confirms_bulk_context(tmp_path):
    from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
    from tradutor_pgn.writing_assistant import PortugueseWritingAssistant

    class NoSpelling:
        def analyze(self, request, protected):
            return ()

    texts = ['Os bispos domina o centro.', 'O bispo domina o centro.', 'Os bispos domina a posição.']
    conn, preview = setup_preview(tmp_path, texts)
    adapter = LanguageToolLocalAdapter()
    try:
        assistant = PortugueseWritingAssistant(spelling_adapter=NoSpelling(), grammar_adapter=adapter)
        request = WritingRequest(texts[0], 0, 'pt', grammar_enabled=True)
        issue = next(item for item in assistant.analyze(request).issues
                     if item.category == 'VERBAL_AGREEMENT' and item.original == 'domina'
                     and 'dominam' in item.suggestions)
        filtered = filter_verbal_preview(preview, issue, request, assistant)
        assert filtered.count == 2
        apply_identical_replacements(conn, filtered)
        assert [row[0] for row in conn.execute('SELECT translated_comment FROM comments ORDER BY id')] == [
            'Os bispos dominam o centro.', 'O bispo domina o centro.', 'Os bispos dominam a posição.']
    finally:
        adapter.shutdown()
        conn.close()
