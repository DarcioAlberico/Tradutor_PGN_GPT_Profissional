import json
import sqlite3
from unittest.mock import patch

from tradutor_pgn.data_verification import verify_data
from tradutor_pgn.glossary_catalog import GlossaryCatalog
from tradutor_pgn.database import initialize_database


def make_db(path, table):
    with sqlite3.connect(path) as conn:
        conn.execute(f'CREATE TABLE "{table}" (id INTEGER)')


def make_translation_db(path):
    initialize_database(str(path)).close()


def test_verification_preserves_acervo_and_returns_only_aggregate_results(tmp_path):
    make_translation_db(tmp_path / "traducoes.db")
    GlossaryCatalog(str(tmp_path / "glossario-v2.db")).initialize()
    (tmp_path / "pgn_tradutor_pro_settings.json").write_text(
        json.dumps({"api_key": "segredo"}), encoding="utf-8"
    )
    backups = tmp_path / "backups"
    backups.mkdir()
    make_translation_db(backups / "traducoes-backup-20261106-120000.db")
    GlossaryCatalog(str(backups / "glossario-v2-20261106-120000.db")).initialize()
    translations = tmp_path / "Minhas Traduções"
    translations.mkdir()
    (translations / "livro-secreto.pgn").write_text("privado", encoding="utf-8")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = verify_data(tmp_path)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after
    assert result['database'] == 'ok'
    assert result['glossary'] == 'ok'
    assert result['settings'] == 'ok'
    assert result['backups']['valid'] == 2
    assert sorted(result['backups']['candidates']) == [
        'glossario-v2-20261106-120000.db', 'traducoes-backup-20261106-120000.db'
    ]
    assert result['translations'] == 1
    assert 'segredo' not in repr(result)
    assert 'livro-secreto' not in repr(result)
    assert result['warnings']


def test_verification_reports_corruption_and_missing_files(tmp_path):
    (tmp_path / 'traducoes.db').write_bytes(b'not a database')
    (tmp_path / 'pgn_tradutor_pro_settings.json').write_text('{', encoding='utf-8')
    result = verify_data(tmp_path)
    assert result['database'] == 'invalid'
    assert result['glossary'] == 'missing'
    assert result['settings'] == 'invalid'
    assert result['backups']['valid'] == 0


def test_verification_rejects_sqlite_database_with_wrong_schema(tmp_path):
    make_db(tmp_path / 'traducoes.db', 'unrelated')
    result = verify_data(tmp_path)
    assert result['database'] == 'invalid'


def test_verification_rejects_incomplete_glossary_schema(tmp_path):
    make_db(tmp_path / 'glossario-v2.db', 'glossary_entries')
    assert verify_data(tmp_path)['glossary'] == 'invalid'


def test_verification_rejects_comments_table_without_required_columns(tmp_path):
    make_db(tmp_path / 'traducoes.db', 'comments')
    assert verify_data(tmp_path)['database'] == 'invalid'


def test_nonempty_wal_is_not_reported_as_a_verified_snapshot(tmp_path):
    make_translation_db(tmp_path / 'traducoes.db')
    (tmp_path / 'traducoes.db-wal').write_bytes(b'pending')
    assert verify_data(tmp_path)['database'] == 'inaccessible'


def test_backup_candidate_name_does_not_disclose_custom_user_filename(tmp_path):
    backups = tmp_path / 'backups'
    backups.mkdir()
    make_translation_db(backups / 'traducoes-backup-nome-privado.db')
    result = verify_data(tmp_path)
    assert result['backups']['valid'] == 1
    assert result['backups']['candidates'] == []
    assert 'nome-privado' not in repr(result)


def test_unreadable_backup_directory_is_not_reported_as_empty(tmp_path):
    (tmp_path / 'backups').mkdir()
    original = __import__('os').scandir

    def scandir(path):
        if str(path) == str(tmp_path / 'backups'):
            raise PermissionError('private path')
        return original(path)

    with patch('tradutor_pgn.data_verification.os.scandir', side_effect=scandir):
        result = verify_data(tmp_path)
    assert any('backups' in warning for warning in result['warnings'])
    assert 'private path' not in repr(result)
