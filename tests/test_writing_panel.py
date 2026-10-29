from gui_harness import GuiTestCase
from tradutor_pgn import writing_panel
from tradutor_pgn.writing_types import AssistantStatus, WritingIssue


def issue(start=0, version=1, category="SPELLING"):
    return WritingIssue("", "SPELLING_UNKNOWN_WORD", category, start, start + 5,
                        "errao", "Grafia", "Confira a grafia.", ("erro", "errado"),
                        "error", "test", version)


class WritingPanelTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.selected = []
        self.applied = []
        self.panel = writing_panel.WritingPanel(
            self.root, on_select=self.selected.append,
            on_apply=lambda item, text: self.applied.append((item, text)),
        )
        self.panel.pack()

    def test_sorted_navigation_suggestions_and_noncolor_category(self):
        first, second = issue(), issue(10, category="GRAMMAR")
        self.panel.set_snapshot((second, first), AssistantStatus("ready", "full"))
        self.assertEqual(self.panel.issues, (first, second))
        self.assertIn("Ortografia", self.panel.issue_buttons[0].cget("text"))
        self.assertIn("Gramática", self.panel.issue_buttons[1].cget("text"))
        self.panel.select(1)
        self.assertEqual(self.selected[-1], second)
        self.panel.navigate(-1)
        self.panel.apply_button.invoke()
        self.assertEqual(self.applied, [(first, "erro")])
        self.assertIn("1/2", self.panel.status_label.cget("text"))

    def test_manual_collapse_survives_resize_and_loading_is_explicit(self):
        self.panel.set_snapshot((), AssistantStatus("starting", "spelling_only", "Carregando dicionário"))
        self.assertIn("Iniciando", self.panel.status_label.cget("text"))
        self.assertIn("Carregando", self.panel.diagnostic_label.cget("text"))
        self.panel.set_available_width(900)
        self.assertTrue(self.panel.collapsed)
        self.panel.set_available_width(1800)
        self.assertFalse(self.panel.collapsed)
        self.panel.toggle_collapsed()
        self.panel.set_available_width(1800)
        self.assertTrue(self.panel.collapsed)
        self.panel.destroy()
        self.assertEqual(self.panel.issues, ())
        self.assertEqual(self.selected, [])

    def test_selection_is_safe_without_suggestions_or_after_destruction(self):
        from dataclasses import replace
        self.panel.set_snapshot((replace(issue(), suggestions=()),), AssistantStatus("failed", "unavailable", "Dicionário ausente"))
        self.assertEqual(self.panel.apply_button.cget("state"), "disabled")
        self.panel.destroy()
        self.panel.navigate(1)
        self.assertEqual(self.applied, [])
