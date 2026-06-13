def bring_window_to_front(window, parent=None, maximize=False):
    def maximize_window():
        try:
            window.state("zoomed")
            return
        except Exception:
            pass

        try:
            window.attributes("-zoomed", True)
            return
        except Exception:
            pass

        try:
            width = window.winfo_screenwidth()
            height = window.winfo_screenheight()
            window.geometry(f"{width}x{height}+0+0")
        except Exception:
            pass

    def raise_window():
        try:
            window.overrideredirect(False)
            window.resizable(True, True)
            try:
                window.attributes("-toolwindow", False)
            except Exception:
                pass
            window.deiconify()
            if maximize:
                maximize_window()
            window.lift(parent) if parent is not None else window.lift()
            window.attributes("-topmost", True)
            window.focus_force()
            window.after(200, lambda: window.attributes("-topmost", False))
        except Exception:
            pass

    window.after(50, raise_window)
