#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

# Sem console — o `.exe` do PyInstaller e o `pythonw` —, `sys.stderr` e `None`,
# e o customtkinter escreve avisos DIRETO nele (`sys.stderr.write`), inclusive
# durante o proprio import: quando o Windows recusa as fontes que ele registra
# (pasta funda demais, ou a politica que bloqueia fontes fora de
# `Windows\Fonts`), o aviso levantava AttributeError dentro do import e o
# programa nao abria — "Unhandled exception in script" (garantia I9). Por isso
# isto vem ANTES de qualquer import de terceiros. So o `stderr`: o `stdout`
# `None` e como o glossario e as configuracoes sabem que nao ha console.
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import customtkinter as ctk  # noqa: E402

from tradutor_pgn.app import PGNTranslatorApp  # noqa: E402


def main():
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    PGNTranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
