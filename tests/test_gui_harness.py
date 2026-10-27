"""Regressions for GUI test cleanup, using actual Tcl callbacks and widgets."""

import tkinter as tk
import unittest

from gui_harness import DISPLAY, GuiTestCase, cancel_pending_after


def force_destroy(root):
    """Clean up even an intentionally corrupted widget command registry."""
    try:
        root.tk.call("destroy", ".")
    except tk.TclError:
        pass
    if getattr(tk, "_default_root", None) is root:
        tk._default_root = None


@unittest.skipUnless(DISPLAY, "sem display para o Tk")
class PendingCallbackCleanupTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.destroyed = []
        self.root.bind("<Destroy>", self.record_root_destroyed, add="+")
        self.addCleanup(self.destroy_root)

    def record_root_destroyed(self, event):
        if event.widget is self.root:
            self.destroyed.append(True)

    def destroy_root(self):
        # A failing cleanup assertion must not leave a native window behind.
        force_destroy(self.root)

    def test_canceling_child_callbacks_keeps_widget_destruction_valid(self):
        child = tk.Frame(self.root)
        child.after(60_000, lambda: self.fail("Canceled callback ran"))

        cancel_pending_after(self.root)

        self.assertFalse(self.root.tk.call("after", "info"))
        child.destroy()
        self.assertFalse(child.winfo_exists())
        self.root.destroy()
        self.assertEqual(self.destroyed, [True])

    def test_canceling_a_tcl_list_script_does_not_need_a_python_command(self):
        self.root.tk.call("after", 60_000, ("list", "argument"))

        cancel_pending_after(self.root)

        self.assertFalse(self.root.tk.call("after", "info"))
        self.root.destroy()
        self.assertEqual(self.destroyed, [True])

    def test_teardown_does_not_hide_a_destruction_error_leaving_the_root_alive(self):
        child = tk.Frame(self.root)
        callback = child.after(60_000, lambda: None)
        # Reproduce ownership corruption from canceling via the wrong widget.
        self.root.after_cancel(callback)
        case = GuiTestCase()
        case.root = self.root

        with self.assertRaises(tk.TclError):
            case._destroy_root()


@unittest.skipUnless(DISPLAY, "sem display para o Tk")
class MainWindowFixtureCleanupTests(unittest.TestCase):
    def test_callback_fixture_destroys_root_with_a_child_callback_pending(self):
        from test_editor_windows import CallbackErrorHookTests

        case = CallbackErrorHookTests("test_an_exploding_callback_becomes_a_dialog")
        destroyed = []
        try:
            case.setUp()
            root = case.root
            root.bind("<Destroy>", lambda event: destroyed.append(True) if event.widget is root else None, add="+")
            child = tk.Frame(root)
            child.after(60_000, lambda: None)
            case.doCleanups()
            self.assertEqual(destroyed, [True], "The callback fixture left its native root alive")
        finally:
            case.doCleanups()
            if hasattr(case, "root"):
                force_destroy(case.root)

    def test_closing_fixture_still_destroys_its_root_after_stubbing_close(self):
        from test_main_window import ClosingTheMainWindowTests

        case = ClosingTheMainWindowTests("test_the_x_is_wired")
        destroyed = []
        try:
            case.setUp()
            root = case.root
            root.bind("<Destroy>", lambda event: destroyed.append(True) if event.widget is root else None, add="+")
            case.test_the_x_is_wired()
            case.doCleanups()
            self.assertEqual(destroyed, [True], "The closing fixture left its native root alive")
        finally:
            case.doCleanups()
            if hasattr(case, "root"):
                force_destroy(case.root)
