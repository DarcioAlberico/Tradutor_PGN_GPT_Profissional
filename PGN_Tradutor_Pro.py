#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import customtkinter as ctk

from tradutor_pgn.app import PGNTranslatorApp


def main():
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    PGNTranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
