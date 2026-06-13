def bring_window_to_front(window, parent=None):
    if parent is not None:
        try:
            window.transient(parent)
        except Exception:
            pass

    def raise_window():
        try:
            window.deiconify()
            window.lift(parent) if parent is not None else window.lift()
            window.attributes("-topmost", True)
            window.focus_force()
            window.after(200, lambda: window.attributes("-topmost", False))
        except Exception:
            pass

    window.after(50, raise_window)
