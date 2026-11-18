from unittest.mock import patch

from test_main_window import MainWindowTestCase


class CommandPaletteWindowTests(MainWindowTestCase):
    def test_new_actions_open_the_existing_dialogs_or_folders(self):
        self.app.last_run = {'files': ['book.pgn']}
        for query, method in (
            ('pasta minhas traducoes', 'open_translations_folder'),
            ('pasta ultima execucao', 'open_last_run_folder'),
            ('exportar csv', 'export_csv'), ('importar csv', 'import_csv'),
            ('backup banco', 'backup_database'),
        ):
            with self.subTest(query=query), patch.object(self.app, method) as action:
                self.app.command_palette_button.invoke()
                self.pump()
                palette = self.app.command_palette
                palette.query.set(query)
                self.pump()
                self.assertEqual(len(palette.items), 1)
                palette.execute()
                action.assert_called_once_with()

    def test_import_rechecks_translation_state_before_opening_dialog(self):
        with patch.object(self.app, 'import_csv') as action:
            self.app.command_palette_button.invoke()
            self.pump()
            palette = self.app.command_palette
            palette.query.set('importar csv')
            self.pump()
            self.app.is_processing = True
            try:
                palette.execute()
                action.assert_not_called()
                self.assertIn('andamento', palette.status.cget('text'))
            finally:
                self.app.is_processing = False
                palette.win.destroy()

    def test_button_opens_search_and_enter_runs_existing_action(self):
        with patch.object(self.app, 'open_glossary_window') as action:
            self.app.command_palette_button.invoke()
            self.pump()
            palette = self.app.command_palette
            palette.query.set('abrir glossario')
            self.pump()
            self.assertEqual([item.id for item in palette.items], ['glossary'])
            palette.execute()
            action.assert_called_once_with()
            self.assertFalse(palette.win.winfo_exists())

    def test_keyboard_binding_and_unavailable_action_explanation(self):
        self.assertTrue(self.app.root.bind('<Control-k>'))
        self.app.command_palette_button.invoke()
        self.pump()
        palette = self.app.command_palette
        palette.query.set('iniciar')
        self.pump()
        self.assertIn('arquivo', palette.status.cget('text').lower())
        palette.execute()
        self.assertTrue(palette.win.winfo_exists())
        palette.win.destroy()

    def test_arrow_navigation_and_search_without_results(self):
        self.app.command_palette_button.invoke()
        self.pump()
        palette = self.app.command_palette
        self.assertEqual(palette.listbox.curselection(), (0,))
        self.assertEqual(palette.down(), 'break')
        self.assertEqual(palette.listbox.curselection(), (1,))
        self.assertEqual(palette.up(), 'break')
        self.assertEqual(palette.listbox.curselection(), (0,))
        palette.query.set('sem correspondencia')
        self.assertIn('Nenhum', palette.status.cget('text'))
        palette.execute()
        self.assertTrue(palette.win.winfo_exists())
        palette.win.destroy()

    def test_create_rule_routes_to_the_existing_new_entry_action(self):
        from types import SimpleNamespace
        calls = []
        editor = SimpleNamespace(new_entry=lambda: calls.append('nova'))
        with patch('tradutor_pgn.command_palette._open_glossary_editor', return_value=editor):
            self.app.command_palette_button.invoke()
            self.pump()
            palette = self.app.command_palette
            palette.query.set('criar regra')
            self.pump()
            self.assertEqual([item.id for item in palette.items], ['new_rule'])
            palette.execute()
            self.assertEqual(calls, ['nova'])

    def test_review_is_unavailable_without_a_last_run(self):
        self.app.last_run = None
        self.app.command_palette_button.invoke()
        self.pump()
        palette = self.app.command_palette
        palette.query.set('revisar pendentes')
        self.pump()
        self.assertIn('execução', palette.status.cget('text'))
        palette.execute()
        self.assertTrue(palette.win.winfo_exists())
        palette.win.destroy()

    def test_pause_rechecks_state_after_the_palette_was_opened(self):
        self.app.is_processing = True
        self.app.pause_flag.clear()
        self.app.cancel_flag.clear()
        with patch.object(self.app, 'pause_translation') as action:
            self.app.command_palette_button.invoke()
            self.pump()
            palette = self.app.command_palette
            palette.query.set('pausar')
            self.pump()
            self.app.pause_flag.set()
            palette.execute()
            action.assert_not_called()
            self.assertIn('pausada', palette.status.cget('text'))
            self.app.pause_flag.clear()
            palette.execute()
            action.assert_called_once_with()
        self.app.is_processing = False

    def test_retry_delegates_to_existing_confirmation_flow(self):
        self.app.retry_button.configure(state='normal')
        with patch.object(self.app, 'retry_failed_translation') as action:
            self.app.command_palette_button.invoke()
            self.pump()
            palette = self.app.command_palette
            palette.query.set('reprocessar falhas')
            self.pump()
            palette.execute()
            action.assert_called_once_with()
