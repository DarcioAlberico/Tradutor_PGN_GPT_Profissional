import time

import os
import threading
from types import SimpleNamespace
from unittest.mock import patch

from gui_harness import GuiTestCase
from tradutor_pgn.translation_library import LibraryBundle
from tradutor_pgn.translation_library_window import TranslationLibraryWindow


class LibraryWindowTests(GuiTestCase):
    def wait_loaded(self, window):
        deadline = time.monotonic() + 5
        while window.loading and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(window.loading)

    def test_filter_preferences_survive_reopening_without_saving_search(self):
        bundle = LibraryBundle(self.base / "livro", "ready", source_language="en",
                               target_language="pt", provider="motor")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle])
        self.wait_loaded(window)
        window.status_filter.set("Com manifesto")
        window.order_var.set("Mais antigos")
        window.source_filter.set(next(label for label, code in window._source_options.items() if code == "en"))
        window.query.set("busca privada")
        window.close()
        reopened = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle])
        self.addCleanup(reopened.close)
        self.wait_loaded(reopened)
        self.assertEqual(reopened.status_filter.get(), "Com manifesto")
        self.assertEqual(reopened.order_var.get(), "Mais antigos")
        self.assertEqual(reopened._source_options[reopened.source_filter.get()], "en")
        self.assertEqual(reopened.query.get(), "")

    def test_failed_library_load_does_not_overwrite_saved_preferences(self):
        def fail(_root):
            raise OSError("biblioteca indisponível")
        saved = {"translation_library": {"status": "ready", "source": "en"}}
        with patch("tradutor_pgn.translation_library_window.load_settings", return_value=saved), \
             patch("tradutor_pgn.translation_library_window.save_preferences") as write:
            window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=fail)
            self.wait_loaded(window)
            window.close()
        write.assert_not_called()

    def test_removed_facet_is_reset_to_all_on_reopen(self):
        saved = {"translation_library": {"source": "fr"}}
        bundle = LibraryBundle(self.base / "livro", "ready", source_language="en", target_language="pt")
        with patch("tradutor_pgn.translation_library_window.load_settings", return_value=saved):
            window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle])
            self.addCleanup(window.close)
            self.wait_loaded(window)
        self.assertEqual(window.source_filter.get(), "Origem: Todos")

    def test_failed_load_then_retry_restores_saved_facet(self):
        saved = {"translation_library": {"source": "en"}}
        bundle = LibraryBundle(self.base / "livro", "ready", source_language="en", target_language="pt")
        attempts = iter([False, True])
        def loader(_root):
            if not next(attempts):
                raise OSError("temporário")
            return [bundle]
        with patch("tradutor_pgn.translation_library_window.load_settings", return_value=saved):
            window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=loader)
            self.addCleanup(window.close)
            self.wait_loaded(window)
            window.refresh()
            self.wait_loaded(window)
        self.assertEqual(window._source_options[window.source_filter.get()], "en")

    def test_unknown_language_facet_is_restored_distinct_from_all(self):
        saved = {"translation_library": {"source": ""}}
        items = [LibraryBundle(self.base / "desconhecido", "legacy"),
                 LibraryBundle(self.base / "conhecido", "ready", source_language="en", target_language="pt")]
        with patch("tradutor_pgn.translation_library_window.load_settings", return_value=saved):
            window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: items)
            self.addCleanup(window.close)
            self.wait_loaded(window)
        self.assertEqual(window.source_filter.get(), "Origem: Não informado")
        self.assertEqual([item.directory.name for item in window.visible_bundles], ["desconhecido"])

    def test_saving_library_preferences_preserves_recent_settings_changes(self):
        from tradutor_pgn import settings
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [])
        self.wait_loaded(window)
        settings.update_settings(lambda data: data.update({"drafts": {"book": "rascunho"}}))
        window.order_var.set("Mais antigos")
        window.close()
        saved = settings.load_settings()
        self.assertEqual(saved["drafts"], {"book": "rascunho"})
        self.assertEqual(saved["translation_library"]["order"], "oldest")


    def test_closing_library_does_not_replace_corrupted_settings(self):
        from pathlib import Path
        from tradutor_pgn import settings
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [])
        self.wait_loaded(window)
        path = Path(settings.default_settings_path())
        path.write_text("{inválido", encoding="utf8")
        with patch("tradutor_pgn.translation_library_window.messagebox.showwarning") as warning:
            window.close()
        self.assertEqual(path.read_text(encoding="utf8"), "{inválido")
        self.assertFalse(list(path.parent.glob(path.name + ".corrompido-*")))
        warning.assert_called_once()

    def test_inspect_staging_button_reports_without_removing_files(self):
        old = self.base / ".obra-BR.tmp-abcdef"
        old.mkdir()
        payload = old / "original.pgn"
        payload.write_text("original", encoding="utf8")
        timestamp = time.time() - 100000
        os.utime(old, (timestamp, timestamp))
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        def run(_parent, _title, work, on_success=None, **_kwargs):
            on_success(work(SimpleNamespace(cancelado=lambda: False)))
        with patch("tradutor_pgn.translation_library_window.run_with_progress", side_effect=run), \
             patch("tradutor_pgn.translation_library_window.messagebox.showinfo") as dialog:
            window.staging_button.invoke()
        self.assertIn(old.name, dialog.call_args.args[1])
        self.assertEqual(payload.read_text(encoding="utf8"), "original")

    def test_staging_button_fits_at_minimum_width(self):
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [])
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.win.geometry("600x400+2000+2000")
        self.root.update()
        button = window.staging_button
        self.assertGreater(button.winfo_width(), 1)
        self.assertLessEqual(button.winfo_x() + button.winfo_width(), button.master.winfo_width())
        self.assertGreaterEqual(window.search_entry.winfo_width(), 100)

    def test_load_search_and_open_valid_bundle(self):
        folder = self.base / "Livro-BR"
        folder.mkdir()
        original, translated = folder / "Livro.pgn", folder / "Livro-BR.pgn"
        original.write_text("original", encoding="utf8")
        translated.write_text("traduzido", encoding="utf8")
        bundle = LibraryBundle(folder, "legacy", original, translated)
        opened = []
        window = TranslationLibraryWindow(self.root, self.base, opened.append, loader=lambda _root: [bundle])
        self.addCleanup(window.close)
        self.wait_loaded(window)
        self.assertEqual(window.visible_bundles, [bundle])
        window.query.set("inexistente")
        self.root.update()
        self.assertEqual(window.visible_bundles, [])
        window.query.set("livro")
        self.root.update()
        self.assertEqual(window.visible_bundles, [bundle])
        window.open_bundle_file(bundle, "translation")
        self.assertEqual(opened, [str(translated)])
        translated.unlink()
        window.open_bundle_file(bundle, "translation")
        self.assertEqual(opened, [str(translated)])
        self.assertIn("não está mais disponível", window.status_label.cget("text"))

    def test_empty_and_invalid_packages_are_visible(self):
        invalid = LibraryBundle(self.base / "defeituoso", "invalid")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [invalid])
        self.addCleanup(window.close)
        self.wait_loaded(window)
        self.assertEqual(window.visible_bundles, [invalid])
        self.assertIn("inválido", window.card_status(invalid).lower())
        window.query.set("nada")
        self.root.update()
        self.assertIn("Nenhum", window.status_label.cget("text"))

    def test_card_reports_generation_failures(self):
        import customtkinter as ctk
        bundle = LibraryBundle(self.base / "livro", "ready", failed_comments=3)
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle])
        self.addCleanup(window.close)
        self.wait_loaded(window)
        card = window.cards.winfo_children()[0]
        labels = [child.cget("text") for child in card.winfo_children() if isinstance(child, ctk.CTkLabel)]
        self.assertTrue(any("Falhas na geração: 3" in text for text in labels))

    def test_load_errors_are_visible(self):
        def fail(_root):
            raise OSError("disco indisponível")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=fail)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        self.assertIn("Não foi possível", window.status_label.cget("text"))

    def test_integrity_check_reports_result_in_window(self):
        from tradutor_pgn.translation_library import IntegrityResult
        bundle = LibraryBundle(self.base / "livro", "ready")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle],
                                          verifier=lambda _path: IntegrityResult("mismatch", True, False))
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.check_integrity(bundle)
        deadline = time.monotonic() + 5
        while window.verifying and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(window.verifying)
        self.assertIn("traduzido", window.status_label.cget("text").lower())
        self.assertIn("diverg", window.status_label.cget("text").lower())

    def test_integrity_check_can_be_cancelled_in_window(self):
        from tradutor_pgn import translation_library
        from tradutor_pgn.translation_output import publish_translation_bundle
        source = self.base / "original.pgn"
        source.write_text("original", encoding="utf8")
        def generate(path):
            from pathlib import Path
            Path(path).write_text("tradução", encoding="utf8")
            return True
        result = publish_translation_bundle(str(source), "pt", str(self.base / "out"), generate)
        bundle = LibraryBundle(self.base / "out" / os.path.basename(result.bundle_dir), "ready")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: [bundle])
        self.addCleanup(window.close)
        self.wait_loaded(window)
        started = threading.Event()
        original_hash = translation_library._hash_file
        def delayed(path, should_cancel):
            started.set()
            while not should_cancel():
                time.sleep(0.01)
            return original_hash(path, should_cancel)
        with patch.object(translation_library, "_hash_file", side_effect=delayed):
            window.check_integrity(bundle)
            self.assertTrue(started.wait(5))
            window.cancel_integrity_button.invoke()
            deadline = time.monotonic() + 5
            while window.verifying and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertFalse(window.verifying)
        self.assertIn("cancelada", window.status_label.cget("text").lower())

    def test_pagination_search_filter_and_sort(self):
        items = [LibraryBundle(self.base / f"Livro-{index:03}", "legacy" if index < 42 else "invalid")
                 for index in range(45)]
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: items)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        self.assertEqual(len(window.visible_bundles), 20)
        self.assertIn("1 de 3", window.page_label.cget("text"))
        window.next_page()
        self.assertEqual(window.visible_bundles[0].directory.name, "Livro-020")
        window.next_page()
        self.assertEqual(len(window.visible_bundles), 5)
        self.assertEqual(window._page_shortcut(1), "break")
        self.assertEqual(window.page_index, 2)
        self.assertEqual(window._page_shortcut(-1), "break")
        self.assertEqual(window.page_index, 1)
        window.query.set("Livro-001")
        self.assertEqual(window.page_index, 0)
        self.assertEqual(len(window.visible_bundles), 1)
        window.query.set("")
        window.status_filter.set("Manifesto inválido")
        self.assertEqual(len(window.visible_bundles), 3)
        self.assertTrue(all(item.status == "invalid" for item in window.visible_bundles))
        window.status_filter.set("Todos")
        window.order_var.set("Nome (Z–A)")
        self.assertEqual(window.visible_bundles[0].directory.name, "Livro-044")

    def test_clear_filters_and_navigation_shortcuts(self):
        items = [LibraryBundle(self.base / f"Livro-{index:03}", "legacy") for index in range(45)]
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: items)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.order_var.set("Nome (Z–A)")
        window.query.set("Livro-001")
        window.status_filter.set("Sem manifesto")
        self.assertIn("2", window.active_filters_label.cget("text"))
        self.assertEqual(window.clear_filters_shortcut(), "break")
        self.assertEqual(window.query.get(), "")
        self.assertEqual(window.status_filter.get(), "Todos")
        self.assertEqual(window.order_var.get(), "Nome (Z–A)")
        self.assertIn("0", window.active_filters_label.cget("text"))
        self.assertEqual(window.last_page_shortcut(), "break")
        self.assertEqual(window.page_index, 2)
        self.assertEqual(window.first_page_shortcut(), "break")
        self.assertEqual(window.page_index, 0)
        for sequence in ("<Control-l>", "<F5>", "<Alt-Home>", "<Alt-End>"):
            self.assertTrue(window.win.bind(sequence))
        self.assertEqual(window.refresh_shortcut(), "break")
        self.wait_loaded(window)
        self.assertEqual(len(window.visible_bundles), 20)

    def test_refresh_clamps_page_after_packages_disappear(self):
        items = [LibraryBundle(self.base / f"Livro-{index:03}", "legacy") for index in range(45)]
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: list(items))
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.next_page()
        window.next_page()
        del items[5:]
        window.refresh()
        self.wait_loaded(window)
        self.assertEqual(window.page_index, 0)
        self.assertEqual(len(window.visible_bundles), 5)
        self.assertIn("1 de 1", window.page_label.cget("text"))

    def test_language_and_provider_filters_combine_and_reset_on_refresh(self):
        items = [
            LibraryBundle(self.base / "um", "ready", source_language="en", target_language="pt", provider="google"),
            LibraryBundle(self.base / "dois", "ready", source_language="es", target_language="pt", provider="modelo"),
            LibraryBundle(self.base / "antigo", "legacy"),
        ]
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: list(items))
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.source_filter.set("Origem: Inglês (en)")
        window.target_filter.set("Destino: Português (pt)")
        window.provider_filter.set("Motor: [google]")
        self.assertEqual(window.visible_bundles, [items[0]])
        window.refresh()
        self.wait_loaded(window)
        self.assertEqual(window.source_filter.get(), "Origem: Inglês (en)")
        self.assertEqual(window.provider_filter.get(), "Motor: [google]")
        self.assertEqual(window.visible_bundles, [items[0]])
        window.provider_filter.set("Motor: [modelo]")
        self.assertEqual(window.visible_bundles, [])
        window.source_filter.set("Origem: Não informado")
        window.target_filter.set("Destino: Não informado")
        window.provider_filter.set("Motor: Não informado")
        self.assertEqual(window.visible_bundles, [items[2]])
        items.pop()
        window.refresh()
        self.wait_loaded(window)
        self.assertEqual(window.source_filter.get(), "Origem: Todos")
        self.assertEqual(window.target_filter.get(), "Destino: Todos")
        self.assertEqual(window.provider_filter.get(), "Motor: Todos")

    def test_review_opens_only_after_link_resolution(self):
        from tradutor_pgn.translation_library_links import ReviewLink, ReviewResolution
        link = ReviewLink("original.pgn", "en", "pt")
        bundle = LibraryBundle(self.base / "livro", "ready")
        opened = []
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None,
            loader=lambda _root: [bundle], review_resolver=lambda _path: ReviewResolution("ready", link),
            on_review=opened.append)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.review_bundle(bundle)
        deadline = time.monotonic() + 5
        while window.resolving_review and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(opened, [link])

    def test_unlinked_package_does_not_open_unfiltered_editor(self):
        from tradutor_pgn.translation_library_links import ReviewResolution
        bundle = LibraryBundle(self.base / "livro", "ready")
        opened = []
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None,
            loader=lambda _root: [bundle], review_resolver=lambda _path: ReviewResolution("unlinked"),
            on_review=opened.append)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.review_bundle(bundle)
        deadline = time.monotonic() + 5
        while window.resolving_review and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(opened, [])
        self.assertIn("não possui vínculo", window.status_label.cget("text"))

    def test_progress_is_shown_after_background_query(self):
        from tradutor_pgn.translation_library_links import ReviewProgress
        bundle = LibraryBundle(self.base / "livro", "ready")
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None,
            loader=lambda _root: [bundle], progress_resolver=lambda _path: ReviewProgress("ready", 3, 1, 2))
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.show_review_progress(bundle)
        deadline = time.monotonic() + 5
        while window.loading_progress and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(window.loading_progress)
        self.assertIn("1 de 3", window.status_label.cget("text"))
        self.assertIn("2 pendentes", window.status_label.cget("text"))
        self.assertIn("33%", window.status_label.cget("text"))

    def test_failure_filter_order_shortcuts_and_copy(self):
        items = [LibraryBundle(self.base / "a", "ready", failed_comments=0),
                 LibraryBundle(self.base / "b", "ready", failed_comments=3),
                 LibraryBundle(self.base / "c", "legacy")]
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None, loader=lambda _root: items)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        window.failure_filter.set("Falhas: Com falhas")
        self.assertEqual(window.visible_bundles, [items[1]])
        window.failure_filter.set("Falhas: Não informado")
        self.assertEqual(window.visible_bundles, [items[2]])
        window.failure_filter.set("Falhas: Todas")
        window.order_var.set("Mais falhas")
        self.assertEqual(window.visible_bundles, [items[1], items[0], items[2]])
        window.copy_summary(items[1])
        self.assertIn("Falhas na geração: 3", self.root.clipboard_get())
        self.assertNotIn(str(self.base), self.root.clipboard_get())
        self.assertTrue(window.win.bind("<Control-f>"))
        self.assertTrue(window.win.bind("<Alt-Left>"))
        self.assertTrue(window.win.bind("<Alt-Right>"))
        self.assertEqual(window.focus_search(), "break")

    def test_compatible_review_requires_clear_user_choice(self):
        from unittest.mock import patch
        from tradutor_pgn.translation_library_links import ReviewLink, ReviewResolution
        link = ReviewLink("original.pgn", "en", "pt")
        bundle = LibraryBundle(self.base / "antigo", "legacy")
        opened = []
        window = TranslationLibraryWindow(self.root, self.base, lambda _: None,
            loader=lambda _root: [bundle], review_resolver=lambda _path: ReviewResolution("compatible", link),
            on_review=opened.append)
        self.addCleanup(window.close)
        self.wait_loaded(window)
        with patch("tradutor_pgn.translation_library_window.messagebox.askyesno", return_value=False) as confirm:
            window.review_bundle(bundle)
            deadline = time.monotonic() + 5
            while window.resolving_review and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertEqual(opened, [])
        self.assertIn("mesmo conteúdo", confirm.call_args.args[1])
        with patch("tradutor_pgn.translation_library_window.messagebox.askyesno", return_value=True):
            window.review_bundle(bundle)
            deadline = time.monotonic() + 5
            while window.resolving_review and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertEqual(opened, [link])
