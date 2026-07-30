"""Pecas comuns aos testes que abrem janelas de verdade.

Nasceram em `test_editor_windows.py`, que foi o primeiro a precisar delas. Os
testes da janela principal precisam exatamente das mesmas coisas — o gate de
display, o silenciamento dos dialogos e o sandbox de caminhos — e uma segunda
copia de `SilentDialogs` seria a armadilha que o item 3.2 do ROADMAP descreve
nos editores: corrigir uma e esquecer a outra.

O sandbox de caminhos nao e preciosismo. A pasta de dados decide onde ficam o
banco, o glossario, as configuracoes, `backups/` e `logs/`, e a abertura do
programa roda a retencao de `backups/` (garantia S8): um teste que abra o app
sobre o diretorio do projeto **apaga backups de verdade**.
"""

import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from tradutor_pgn import (
    app_actions,
    app_paths,
    db_tools,
    edit_window,
    glossario,
    glossary_editor,
    translation_worker,
)


def _display_available():
    try:
        root = tk.Tk()
    except Exception:
        return False
    root.destroy()
    return True


DISPLAY = _display_available()

# Todo modulo capaz de abrir um dialogo durante os testes.
DIALOG_MODULES = (
    edit_window,
    glossary_editor,
    db_tools,
    app_actions,
    translation_worker,
)


_UNSET = object()


class SilentDialogs:
    """Substitui o `messagebox` do modulo sob teste e registra as chamadas."""

    def __init__(self, askyesno=True, askyesnocancel=_UNSET):
        self.calls = []
        self.askyesno_result = askyesno
        # `None` e um valor legitimo aqui — e o "Cancelar" do dialogo de tres
        # botoes —, entao o padrao nao pode ser `None` querendo dizer "use o do
        # askyesno". Sem valor informado, cai no do `askyesno`.
        self.askyesnocancel_result = (
            askyesno if askyesnocancel is _UNSET else askyesnocancel
        )

    def _record(self, kind):
        def handler(title, message, **_kwargs):
            self.calls.append((kind, title, message))
            return None

        return handler

    def install(self, *modules):
        """Silencia o `messagebox` de TODOS os modulos que possam abrir dialogo.

        Nao basta cobrir o modulo sob teste: "Aplicar automaticas" no editor de
        traducoes chama `db_tools`, que abre a confirmacao no proprio namespace.
        Um so modulo esquecido trava a suite num dialogo modal invisivel.
        """
        self.calls.clear()
        recorder = self

        class Fake:
            showinfo = staticmethod(recorder._record("info"))
            showwarning = staticmethod(recorder._record("warning"))
            showerror = staticmethod(recorder._record("error"))

            @staticmethod
            def askyesno(title, message, **_kwargs):
                recorder.calls.append(("askyesno", title, message))
                return recorder.askyesno_result

            @staticmethod
            def askyesnocancel(title, message, **_kwargs):
                recorder.calls.append(("askyesnocancel", title, message))
                return recorder.askyesnocancel_result

        self.previous = []
        for module in modules:
            if hasattr(module, "messagebox"):
                self.previous.append((module, module.messagebox))
                module.messagebox = Fake

    def restore(self):
        for module, original in self.previous:
            module.messagebox = original

    def titles(self, kind=None):
        return [t for k, t, _m in self.calls if kind is None or k == kind]

    def messages(self, kind=None):
        return [m for k, _t, m in self.calls if kind is None or k == kind]


class SilentFileDialogs:
    """Faz todo seletor de arquivo responder "cancelado".

    Sem isto, varrer os botoes abriria dialogos nativos e a suite travaria
    esperando alguem clicar.
    """

    def __init__(self):
        self.answer = ""

    def install(self, *modules):
        picker = self

        class Fake:
            asksaveasfilename = staticmethod(lambda **_kwargs: picker.answer)
            askopenfilename = staticmethod(lambda **_kwargs: picker.answer)
            askdirectory = staticmethod(lambda **_kwargs: picker.answer)

        self.previous = []
        for module in modules:
            if hasattr(module, "filedialog"):
                self.previous.append((module, module.filedialog))
                module.filedialog = Fake

    def restore(self):
        for module, original in self.previous:
            module.filedialog = original


@unittest.skipUnless(DISPLAY, "sem display para o Tk")
class GuiTestCase(unittest.TestCase):
    """Sandbox em disco, raiz do Tk e dialogos silenciados."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="gui-test-")
        self.base = Path(self.sandbox.name)
        self.addCleanup(self.sandbox.cleanup)

        # Nada aqui pode tocar os arquivos reais. `PGN_TRADUTOR_DATA` e a porta
        # unica desde a separacao de programa e dados (ROADMAP 21): glossario,
        # indice, configuracoes, banco, `backups/` e `logs/` saem todos dela.
        # `sys.argv[0]` continua trocado porque a pasta do PROGRAMA sai dele — e
        # dela que a migracao da primeira execucao tenta copiar.
        self._paths = (
            glossario._default_seed_path,
            os.environ.get(app_paths.DATA_DIR_ENV),
            sys.argv[0],
        )
        os.environ[app_paths.DATA_DIR_ENV] = str(self.base)
        # A semente e a excecao, e por outra razao: ela EXISTE no repositorio e e
        # mesclada em toda carga de regras (garantia S15), entao sem desliga-la a
        # terminologia embutida apareceria nas sugestoes de toda janela testada.
        # Ela vem com o programa, entao nao segue a pasta de dados.
        glossario._default_seed_path = lambda: str(self.base / "semente-inexistente.txt")
        sys.argv[0] = str(self.base / "PGN_Tradutor_Pro.py")
        self.addCleanup(self._restore_paths)

        self.db_path = str(self.base / "traducoes.db")
        self.root = tk.Tk()
        self.root.withdraw()          # nada pisca na tela durante a suite
        self.addCleanup(self._destroy_root)

        self.dialogs = SilentDialogs()
        self.dialogs.install(*DIALOG_MODULES)
        self.addCleanup(self.dialogs.restore)

        self.file_dialogs = SilentFileDialogs()
        self.file_dialogs.install(*DIALOG_MODULES)
        self.addCleanup(self.file_dialogs.restore)

    def _restore_paths(self):
        glossario._default_seed_path, dados, sys.argv[0] = self._paths
        if dados is None:
            os.environ.pop(app_paths.DATA_DIR_ENV, None)
        else:
            os.environ[app_paths.DATA_DIR_ENV] = dados

    def _destroy_root(self):
        # As janelas agendam trabalho com `after` (levantar a janela, restaurar a
        # posicao do divisor, o proprio `update_log`). Destruir sem cancelar
        # deixa esses callbacks dispararem no vazio e o Tk imprime
        # "invalid command name" no meio da saida da suite — barulho que
        # esconderia uma falha de verdade.
        try:
            for after_id in self.root.tk.eval("after info").split():
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump(self):
        self.root.update()
