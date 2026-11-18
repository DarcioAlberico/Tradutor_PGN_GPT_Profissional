from pathlib import Path
from unittest.mock import patch

from tradutor_pgn import app_actions
from tradutor_pgn.data_verification import verify_data
from tradutor_pgn.translation_output import publish_translation_bundle


def test_backups_are_counted_separately_by_type(tmp_path):
    from tradutor_pgn.database import initialize_database
    from tradutor_pgn.glossary_catalog import GlossaryCatalog
    backups = tmp_path / 'backups'
    backups.mkdir()
    initialize_database(str(backups / 'traducoes-backup-20261117-120000.db')).close()
    GlossaryCatalog(str(backups / 'glossario-v2-20261117-120000.db')).initialize()
    result = verify_data(tmp_path)
    assert result['backups']['by_type']['translations']['valid'] == 1
    assert result['backups']['by_type']['glossary']['valid'] == 1


def test_backup_candidate_list_is_limited_and_counts_omitted(tmp_path):
    backups = tmp_path / 'backups'
    backups.mkdir()
    for n in range(25):
        (backups / f'traducoes-backup-20261117-{n:06}.db').touch()
    with patch('tradutor_pgn.data_verification._database_status', return_value='ok'):
        result = verify_data(tmp_path)
    assert len(result['backups']['candidates']) == 20
    assert result['backups']['candidates_omitted'] == 5
    assert result['backups']['candidates'] == sorted(result['backups']['candidates'], reverse=True)


def test_package_inventory_reports_metadata_status_without_names(tmp_path):
    root = tmp_path / 'Minhas Traduções'
    source = tmp_path / 'source-private.pgn'
    source.write_text('original', encoding='utf-8')
    def generate(path):
        Path(path).write_text('translated', encoding='utf-8')
        return True
    publish_translation_bundle(str(source), 'pt', str(root), generate, source_language='en', provider='local')
    invalid = root / 'secret-invalid'
    invalid.mkdir()
    (invalid / 'manifesto.json').write_text('{', encoding='utf-8')
    incomplete = root / 'secret-incomplete'
    incomplete.mkdir()
    legacy = root / 'secret-legacy'
    legacy.mkdir()
    (legacy / 'original.pgn').touch()
    (legacy / 'secret-legacy.pgn').touch()
    result = verify_data(tmp_path)
    assert result['packages'] == {'ready': 1, 'legacy': 1, 'incomplete': 1, 'invalid': 1}
    assert 'secret-' not in repr(result) and 'source-private' not in repr(result)
    report = app_actions._format_data_verification(result)
    assert 'manifesto' in report.lower() and 'hash' in report.lower()


def test_missing_directories_are_distinguished_from_empty(tmp_path):
    missing = verify_data(tmp_path)
    assert missing['backup_directory'] == 'missing'
    assert missing['translations_directory'] == 'missing'
    (tmp_path / 'backups').mkdir()
    (tmp_path / 'Minhas Traduções').mkdir()
    empty = verify_data(tmp_path)
    assert empty['backup_directory'] == 'ok'
    assert empty['translations_directory'] == 'ok'


def test_incomplete_inventory_is_marked_inaccessible_without_private_errors(tmp_path):
    root = tmp_path / 'Minhas Traduções'
    root.mkdir()
    with patch('tradutor_pgn.data_verification.list_bundles', side_effect=PermissionError('private-name')):
        result = verify_data(tmp_path)
    assert result['packages'] is None
    assert 'private-name' not in repr(result)
    assert 'não foi possível' in app_actions._format_data_verification(result).lower()


def test_directory_removed_during_inventory_is_not_reported_as_empty(tmp_path):
    root = tmp_path / 'Minhas Traduções'
    root.mkdir()
    def removed(path):
        path.rmdir()
        return []
    with patch('tradutor_pgn.data_verification.list_bundles', side_effect=removed):
        result = verify_data(tmp_path)
    assert result['translations_directory'] == 'inaccessible'
    assert result['packages'] is None


def test_report_marks_partial_pgn_count_and_omitted_backup_candidates():
    result = {'database': 'missing', 'glossary': 'missing', 'settings': 'missing',
              'backups': {'valid': 25, 'invalid': 0, 'inaccessible': 0,
                          'candidates': ['traducoes-backup-20261117-000001.db'], 'candidates_omitted': 24},
              'translations': 2, 'translations_directory': 'inaccessible', 'warnings': []}
    report = app_actions._format_data_verification(result)
    assert 'listagem incompleta' in report and '24 candidato' in report


def test_inaccessible_backup_directory_is_not_presented_as_complete():
    result = {'database': 'missing', 'glossary': 'missing', 'settings': 'missing',
              'backups': {'valid': 0, 'invalid': 0, 'inaccessible': 0, 'candidates': []},
              'backup_directory': 'inaccessible', 'translations': 0, 'warnings': []}
    report = app_actions._format_data_verification(result)
    backup_line = next(line for line in report.splitlines() if line.startswith('Backups de traduções e glossário'))
    assert 'listagem incompleta' in backup_line
