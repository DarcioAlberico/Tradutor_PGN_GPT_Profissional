"""Regression evidence for the final catalog review, using isolated real data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import threading
import types
from unittest.mock import patch

import pytest

from tradutor_pgn import db_tools, glossario
from tradutor_pgn.glossary_catalog import (
    GlossaryCatalog, GlossaryConflictError, GlossaryEntryChanges, GlossaryEntryDraft,
)


@pytest.fixture
def catalog(tmp_path):
    result = GlossaryCatalog(str(tmp_path / 'catalog.db'), str(tmp_path / 'mirror.txt'))
    result.initialize()
    return result


def test_clear_requires_displayed_revision_and_invalidates_entry_tokens(catalog):
    first = catalog.add(GlossaryEntryDraft('rook', 'torre'), 1)
    before = catalog.add(GlossaryEntryDraft('queen', 'dama'), 2).snapshot
    with pytest.raises(GlossaryConflictError):
        catalog.clear(first.snapshot.catalog_revision)
    assert catalog.list_entries() == before
    cleared = catalog.clear(before.catalog_revision)
    assert cleared.snapshot.entries == ()
    assert cleared.snapshot.catalog_revision == 4
    assert glossario._load_glossary_entry_details_from_file(catalog.mirror_path) == []
    with pytest.raises(GlossaryConflictError):
        catalog.update(first.entry.stable_id, 1, GlossaryEntryChanges(priority=2))


def test_reset_tool_clears_authoritative_catalog_and_mirror(tmp_path, monkeypatch):
    mirror = tmp_path / "Substituicoes.txt"
    mirror.write_text("substituicoes = [('rook', 'torre')]", encoding="utf-8")
    database = tmp_path / "glossario-v2.db"
    monkeypatch.setattr(glossario, "_default_substitutions_path", lambda: str(mirror))
    monkeypatch.setattr(glossario, "glossary_catalog_path", lambda: str(database))
    monkeypatch.setattr(glossario, "_default_glossary_db_path", lambda: str(tmp_path / "cache.db"))
    glossario.initialize_catalog_glossary()
    monkeypatch.setattr(db_tools, "ask_typed_confirmation", lambda *_a, **_k: True)
    monkeypatch.setattr(db_tools.messagebox, "showinfo", lambda *_a, **_k: None)
    monkeypatch.setattr(db_tools.messagebox, "showerror", lambda *_a, **_k: None)
    app = types.SimpleNamespace(
        root=None, glossary_substitutions=[("rook", "torre")],
        glossary_change_callbacks=[], log_message=lambda _message: None,
    )

    db_tools.reset_glossary(app)

    snapshot = GlossaryCatalog(str(database), str(mirror)).list_entries()
    assert snapshot.entries == ()
    assert glossario._load_glossary_entry_details_from_file(str(mirror)) == []


def test_reset_tool_refuses_catalog_changed_after_confirmation_was_prepared(tmp_path, monkeypatch):
    mirror = tmp_path / "Substituicoes.txt"
    mirror.write_text("substituicoes = [('rook', 'torre')]", encoding="utf-8")
    database = tmp_path / "glossario-v2.db"
    monkeypatch.setattr(glossario, "_default_substitutions_path", lambda: str(mirror))
    monkeypatch.setattr(glossario, "glossary_catalog_path", lambda: str(database))
    monkeypatch.setattr(glossario, "_default_glossary_db_path", lambda: str(tmp_path / "cache.db"))
    glossario.initialize_catalog_glossary()
    catalog = GlossaryCatalog(str(database), str(mirror))
    errors = []

    def concurrent_change(*_args, **_kwargs):
        catalog.add(GlossaryEntryDraft("queen", "dama"), 1)
        return True

    monkeypatch.setattr(db_tools, "ask_typed_confirmation", concurrent_change)
    monkeypatch.setattr(db_tools.messagebox, "showinfo", lambda *_a, **_k: None)
    monkeypatch.setattr(db_tools.messagebox, "showerror", lambda _t, message, **_k: errors.append(message))
    app = types.SimpleNamespace(
        root=None, glossary_substitutions=[], glossary_change_callbacks=[],
        log_message=lambda _message: None,
    )

    db_tools.reset_glossary(app)

    assert [entry.original_text for entry in catalog.list_entries().entries] == ["rook", "queen"]
    assert errors and "nada foi apagado" in errors[0].lower()


def test_legacy_default_writer_refuses_to_claim_success_after_v2_exists(tmp_path, monkeypatch):
    mirror = tmp_path / "Substituicoes.txt"
    mirror.write_text("substituicoes = [('rook', 'torre')]", encoding="utf-8")
    database = tmp_path / "glossario-v2.db"
    monkeypatch.setattr(glossario, "_default_substitutions_path", lambda: str(mirror))
    monkeypatch.setattr(glossario, "glossary_catalog_path", lambda: str(database))
    monkeypatch.setattr(glossario, "_default_glossary_db_path", lambda: str(tmp_path / "cache.db"))
    glossario.initialize_catalog_glossary()

    with pytest.raises(RuntimeError, match="SQLite V2"):
        glossario.save_glossary_entries([], str(mirror), create_backup=False)

    assert [entry.original_text for entry in GlossaryCatalog(str(database)).list_entries().entries] == ["rook"]
    assert glossario._load_glossary_entries_from_file(str(mirror)) == [("rook", "torre")]


INVALID_FIELDS = [
    {'scope': 'xx'}, {'scope': 'en>pt>it'}, {'original_text': '  '},
    {'replacement_text': '  '}, {'original_text': 7}, {'replacement_text': None},
    {'rule_type': 'unknown'}, {'rule_type': False}, {'priority': True},
    {'priority': 'bad'}, {'priority': 1.5}, {'priority': 2**63}, {'priority': -2**63 - 1},
]


@pytest.mark.parametrize('fields', INVALID_FIELDS)
def test_add_rejects_unpersistible_entry_before_commit(catalog, fields):
    before = catalog.list_entries()
    with pytest.raises(ValueError):
        catalog.add(replace(GlossaryEntryDraft('rook', 'torre'), **fields), 1)
    assert catalog.list_entries() == before


@pytest.mark.parametrize('fields', [f for f in INVALID_FIELDS if None not in f.values()])
def test_update_rejects_unpersistible_entry_without_changing_revision(catalog, fields):
    before = catalog.add(GlossaryEntryDraft('rook', 'torre'), 1)
    with pytest.raises(ValueError):
        catalog.update(before.entry.stable_id, 1, GlossaryEntryChanges(**fields))
    assert catalog.list_entries() == before.snapshot


@pytest.mark.parametrize('fields', INVALID_FIELDS)
def test_migration_rejects_invalid_raw_values_before_publication(tmp_path, fields):
    draft = replace(GlossaryEntryDraft('rook', 'torre'), **fields)
    row = (draft.original_text, draft.replacement_text, draft.rule_type, draft.priority, draft.scope)
    source = tmp_path / 'legacy.txt'
    source.write_text('substituicoes = ' + repr([row]), encoding='utf-8')
    target = tmp_path / 'catalog.db'
    with pytest.raises(ValueError):
        glossario.migrate_legacy_glossary(str(source), str(target), str(tmp_path / 'cache.db'))
    assert not target.exists()


def test_import_int64_overflow_is_invalid_and_valid_rows_still_commit(catalog):
    rows = [('huge', 'alto', 'suggestion', 2**63, ''),
            ('tiny', 'baixo', 'suggestion', -2**63 - 1, ''),
            ('rook', 'torre', 'suggestion', 0, 'pt')]
    preview = catalog.preview_import(rows)
    assert [row.status for row in preview.rows] == ['invalid', 'invalid', 'new']
    result = catalog.import_entries(rows, 'append', preview.catalog_revision)
    assert result.inserted_count == 1
    assert result.snapshot.entries[0].original_text == 'rook'


def test_valid_normalization_cleanup_and_int64_edges_roundtrip_backup(catalog, tmp_path):
    catalog.add(GlossaryEntryDraft('  rook ', ' torre ', 'sugestão', ' en > pt ', -2**63), 1)
    catalog.add(GlossaryEntryDraft('noise', '', 'limpeza', '*', 2**63 - 1), 2)
    backup = catalog.backup(str(tmp_path / 'backup.db'))
    restored = catalog.restore(backup.path, 3)
    assert [(e.original_text, e.replacement_text, e.rule_type, e.scope, e.priority)
            for e in restored.snapshot.entries] == [
                ('rook', 'torre', 'suggestion', 'en>pt', -2**63),
                ('noise', '', 'cleanup', '', 2**63 - 1),
            ]


@pytest.mark.parametrize('crash', [False, True])
def test_mirror_publication_recovers_after_replace_before_metadata(catalog, crash):
    catalog.add(GlossaryEntryDraft('rook', 'torre'), 1)
    real_set = GlossaryCatalog._set_metadata

    class SimulatedCrash(BaseException):
        pass

    def fail_hash(conn, key, value):
        if key == 'legacy_mirror_hash':
            raise SimulatedCrash() if crash else sqlite3.OperationalError('post replace failure')
        return real_set(conn, key, value)

    with patch.object(GlossaryCatalog, '_set_metadata', side_effect=fail_hash):
        if crash:
            with pytest.raises(SimulatedCrash):
                catalog.add(GlossaryEntryDraft('queen', 'dama'), 2)
        else:
            assert catalog.add(GlossaryEntryDraft('queen', 'dama'), 2).mirror_pending
    assert len(glossario._load_glossary_entry_details_from_file(catalog.mirror_path)) == 2
    reopened = GlossaryCatalog(catalog.db_path, catalog.mirror_path)
    result = reopened.initialize()
    assert result is not None and not result.mirror_pending
    with closing(reopened._connect()) as conn:
        assert reopened._metadata(conn, 'mirror_pending') == '0'


def test_failed_publication_intent_never_accepts_unrelated_external_text(catalog):
    catalog.add(GlossaryEntryDraft('rook', 'torre'), 1)
    with patch('tradutor_pgn.glossary_catalog.os.replace', side_effect=OSError('disk')):
        assert catalog.add(GlossaryEntryDraft('queen', 'dama'), 2).mirror_pending
    external = b"substituicoes = [('external', 'externo')]\n"
    Path(catalog.mirror_path).write_bytes(external)
    assert catalog.initialize().mirror_pending
    assert Path(catalog.mirror_path).read_bytes() == external


@pytest.mark.parametrize('concurrent', [False, True])
def test_migration_without_hardlinks_publishes_once(tmp_path, concurrent):
    source = tmp_path / 'legacy.txt'
    source.write_text("substituicoes = [('rook', 'torre')]", encoding='utf-8')
    target = tmp_path / 'catalog.db'
    barrier = threading.Barrier(2)
    real_validate = GlossaryCatalog._validate_migration

    def validate(conn, count):
        real_validate(conn, count)
        if concurrent:
            barrier.wait(timeout=10)

    def migrate():
        return glossario.migrate_legacy_glossary(str(source), str(target), str(tmp_path / 'cache.db'))

    with patch.object(GlossaryCatalog, '_validate_migration', side_effect=validate):
        if concurrent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(pool.map(lambda _: migrate(), range(2)))
        else:
            reports = [migrate()]
    assert sum(r.migrated for r in reports) == 1
    result = GlossaryCatalog(str(target), str(source))
    before = result.list_entries()
    assert len(before.entries) == 1
    assert not migrate().migrated
    assert result.list_entries() == before


@pytest.mark.parametrize('phase,scope', [('cleanup', 'pt'), ('suggestion', 'it')])
def test_validation_identity_distinguishes_phase_and_scope(phase, scope):
    entries = [('rook', 'torre', 'suggestion', 0, 'pt')]
    for replacement in ('torre', 'castelo'):
        warnings = glossario.validate_glossary_entry(
            'rook', replacement, entries, rule_type=phase, scope=scope,
        )
        assert not warnings
    assert glossario.validate_glossary_entry(
        ' rook ', ' torre ', entries, rule_type='sugestão', scope=' pt ',
    ) == ['Entrada duplicada.']
