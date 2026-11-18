from types import SimpleNamespace
from threading import Event

from tradutor_pgn.command_palette import commands_for, filter_commands, run_command


def fake_app(path='', busy=False):
    calls = []
    app = SimpleNamespace(source_path=SimpleNamespace(get=lambda: path), is_processing=busy)
    app.pause_flag = Event()
    app.cancel_flag = Event()
    app.retry_button = SimpleNamespace(cget=lambda _: 'disabled')
    for name in ('select_file', 'select_directory', 'start_translation', 'open_translation_library',
                 'open_glossary_window', 'open_settings_window', 'review_last_run', 'export_tmx', 'verify_user_data',
                 'open_edit_window', 'retry_failed_translation', 'pause_translation', 'resume_translation', 'cancel_translation'):
        setattr(app, name, lambda name=name: calls.append(name))
    for name in ('open_translations_folder', 'open_last_run_folder', 'export_csv', 'import_csv', 'backup_database'):
        setattr(app, name, lambda name=name: calls.append(name))
    return app, calls


def test_palette_offers_twenty_frequent_actions():
    app, _ = fake_app()
    assert {item.id for item in commands_for(app)} == {'file', 'start', 'library', 'glossary', 'settings',
                                                        'directory', 'review', 'new_rule', 'export_tmx', 'verify_data',
                                                        'edit_translations', 'retry', 'pause', 'resume', 'cancel',
                                                        'translations_folder', 'last_run_folder', 'export_csv', 'import_csv', 'backup'}


def test_new_commands_search_and_delegate_to_existing_flows():
    app, calls = fake_app()
    app.last_run = {'files': ['book.pgn']}
    for query, command_id, method in (
        ('pasta minhas traducoes', 'translations_folder', 'open_translations_folder'),
        ('pasta ultima execucao', 'last_run_folder', 'open_last_run_folder'),
        ('exportar csv', 'export_csv', 'export_csv'),
        ('importar csv', 'import_csv', 'import_csv'),
        ('backup banco', 'backup', 'backup_database'),
    ):
        assert command_id in [item.id for item in filter_commands(commands_for(app), query)]
        assert run_command(app, command_id) is None
        assert calls[-1] == method


def test_last_run_folder_and_import_recheck_current_state():
    app, calls = fake_app()
    assert run_command(app, 'last_run_folder')
    app.last_run = {'files': ['book.pgn']}
    assert next(item for item in commands_for(app) if item.id == 'last_run_folder').reason is None
    app.last_run = None
    assert run_command(app, 'last_run_folder')
    assert next(item for item in commands_for(app) if item.id == 'import_csv').reason is None
    app.is_processing = True
    assert 'andamento' in run_command(app, 'import_csv')
    assert run_command(app, 'export_csv') is None
    assert run_command(app, 'backup') is None
    assert calls == ['export_csv', 'backup_database']


def test_search_accepts_accents_case_and_multiple_terms():
    app, _ = fake_app()
    assert [c.id for c in filter_commands(commands_for(app), 'ABRIR GLOSSARIO')] == ['glossary']
    assert [c.id for c in filter_commands(commands_for(app), 'traducao iniciar')] == ['start']
    assert not filter_commands(commands_for(app), 'nao existe')


def test_start_explains_missing_path_and_does_not_execute():
    app, calls = fake_app()
    start = next(c for c in commands_for(app) if c.id == 'start')
    assert 'arquivo' in start.reason.lower()
    assert run_command(app, 'start') == start.reason
    assert calls == []


def test_running_state_is_checked_again_when_command_is_executed(tmp_path):
    source = tmp_path / 'partida.pgn'
    source.write_text('x')
    app, calls = fake_app(str(source))
    assert next(c for c in commands_for(app) if c.id == 'start').reason is None
    app.is_processing = True
    assert 'andamento' in run_command(app, 'start').lower()
    assert calls == []
    app.is_processing = False
    assert run_command(app, 'start') is None
    assert calls == ['start_translation']


def test_each_action_delegates_to_existing_application_command():
    app, calls = fake_app()
    for command_id in ('file', 'library', 'glossary', 'settings'):
        assert run_command(app, command_id) is None
    assert calls == ['select_file', 'open_translation_library', 'open_glossary_window', 'open_settings_window']


def test_directory_and_export_delegate_to_existing_actions():
    app, calls = fake_app()
    assert run_command(app, 'directory') is None
    assert run_command(app, 'export_tmx') is None
    assert calls == ['select_directory', 'export_tmx']


def test_review_requires_a_last_run_and_rechecks_before_execution():
    app, calls = fake_app()
    assert 'execução' in run_command(app, 'review')
    app.last_run = {'files': ['game.pgn']}
    assert next(c for c in commands_for(app) if c.id == 'review').reason is None
    app.last_run = None
    assert run_command(app, 'review')
    assert calls == []
    app.last_run = {'files': ['game.pgn']}
    assert run_command(app, 'review') is None
    assert calls == ['review_last_run']


def test_data_check_prevents_a_second_concurrent_verification():
    app, calls = fake_app()
    app._data_verification_active = True
    assert 'andamento' in run_command(app, 'verify_data')
    assert calls == []
    app._data_verification_active = False
    assert run_command(app, 'verify_data') is None
    assert calls == ['verify_user_data']


def test_new_rule_uses_editor_new_entry_flow(monkeypatch):
    from tradutor_pgn import command_palette
    app, _ = fake_app()
    calls = []
    editor = SimpleNamespace(new_entry=lambda: calls.append('new_entry'))
    monkeypatch.setattr(command_palette, '_open_glossary_editor', lambda actual: editor if actual is app else None)
    assert run_command(app, 'new_rule') is None
    assert calls == ['new_entry']


def test_edit_translations_opens_existing_editor():
    app, calls = fake_app()
    assert run_command(app, 'edit_translations') is None
    assert calls == ['open_edit_window']


def test_retry_uses_the_existing_button_state_and_rechecks_before_execution():
    app, calls = fake_app()
    assert run_command(app, 'retry')
    app.retry_button = SimpleNamespace(cget=lambda _: 'normal')
    assert next(c for c in commands_for(app) if c.id == 'retry').reason is None
    app.is_processing = True
    assert 'andamento' in run_command(app, 'retry')
    app.is_processing = False
    assert run_command(app, 'retry') is None
    assert calls == ['retry_failed_translation']


def test_pause_and_resume_follow_processing_and_pause_state():
    app, calls = fake_app()
    assert run_command(app, 'pause') and run_command(app, 'resume')
    app.is_processing = True
    assert run_command(app, 'pause') is None
    assert run_command(app, 'resume')
    app.pause_flag.set()
    assert run_command(app, 'pause')
    assert run_command(app, 'resume') is None
    assert calls == ['pause_translation', 'resume_translation']


def test_cancel_requires_active_translation_and_refuses_repeat():
    app, calls = fake_app()
    assert run_command(app, 'cancel')
    app.is_processing = True
    assert run_command(app, 'cancel') is None
    app.cancel_flag.set()
    assert run_command(app, 'cancel')
    assert run_command(app, 'pause') and run_command(app, 'resume')
    assert calls == ['cancel_translation']
