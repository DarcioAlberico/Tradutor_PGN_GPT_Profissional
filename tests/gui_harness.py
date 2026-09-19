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

import functools
import gc
import os
import sys
import tempfile
import time
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
    history_window,
    repeated_edits_window,
    settings_window,
    stats_window,
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
#
# `stats_window` e `history_window` entraram em 2026-08-01, e a falta deles nao
# era teorica: a janela de estatisticas chama `filedialog.asksaveasfilename` para
# salvar o relatorio, e um teste que a exercitasse abriria o seletor NATIVO do
# Windows e travaria a suite esperando alguem clicar — foi o que aconteceu ao
# escrever os testes de 22.12. A lista precisa cobrir todo modulo que abra
# dialogo, e nao so os que ja tinham teste: e a armadilha que o item 3.2 do
# ROADMAP descreve, na sua forma mais silenciosa.
DIALOG_MODULES = (
    edit_window,
    glossary_editor,
    db_tools,
    app_actions,
    history_window,
    repeated_edits_window,
    settings_window,
    stats_window,
    translation_worker,
)


_UNSET = object()


def cancel_pending_after(root):
    """Cancela todo `after` pendente da interpretacao, sem levantar.

    As janelas agendam trabalho com `after` (levantar a janela, restaurar a
    posicao do divisor, o proprio `update_log`). Destruir sem cancelar deixa
    esses callbacks dispararem no vazio e o Tk imprime "invalid command name" no
    meio da saida da suite — barulho que esconderia uma falha de verdade.

    **O `after_cancel` do tkinter nao serve sozinho.** Antes de cancelar ele
    tenta apagar o comando registrado, e le o script com
    `splitlist(...)[0]`: quando o script e uma LISTA Tcl de varias palavras — o
    que acontece quando alguem agenda com argumentos —, esse `[0]` e uma tupla e
    o `deletecommand` levanta `TypeError`, **antes** de o timer ser cancelado.
    Um `except tk.TclError` nao pega isso, e a suite ganhava um erro de
    desmontagem numa classe que nao tinha nada a ver com o assunto.

    O `after cancel` em Tcl puro nao passa por nada disso, e e o que de fato
    para o callback; o comando orfao morre com a interpretacao.
    """
    try:
        pendentes = root.tk.eval("after info").split()
    except tk.TclError:
        return
    for after_id in pendentes:
        try:
            root.after_cancel(after_id)
        except (tk.TclError, TypeError):
            try:
                root.tk.call("after", "cancel", after_id)
            except tk.TclError:
                pass


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


# A tela que a geometria medida exige. A maior janela do programa e o editor
# de glossario, com minimo 1040 x 640; com bordas e barra de tarefas isso pede
# ~1100 x 740. O runner do GitHub tem 1024 x 768 (a largura nao cabe): no
# primeiro CI (2026-09-18), 7 testes que medem pixels falharam la — rotulo
# nao mapeado, painel 320 em vez de 330, log sem altura — e todos passam a
# 1920 x 1080. Numa tela menor que isto a janela nao cabe e o numero medido
# nao e o do produto; o teste pula dizendo por que, em vez de mentir.
SCREEN_NEEDED = (1100, 740)


def needs_room(test):
    """Pula o teste quando a tela nao comporta a maior janela (ver `SCREEN_NEEDED`)."""

    @functools.wraps(test)
    def wrapper(self, *args, **kwargs):
        largura, altura = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if largura < SCREEN_NEEDED[0] or altura < SCREEN_NEEDED[1]:
            self.skipTest(
                f"tela {largura}x{altura}: menor que {SCREEN_NEEDED[0]}x{SCREEN_NEEDED[1]}, "
                f"a maior janela nao cabe e a geometria medida nao vale aqui"
            )
        return test(self, *args, **kwargs)

    return wrapper


def criar_root():
    """`tk.Tk()`, com UMA segunda tentativa.

    No primeiro CI (2026-09-18) o segundo teste da suite falhou ao criar o
    interpretador — `invalid command name "tcl_findLibrary"`, o `init.tcl`
    nao carregado — e os 541 seguintes criaram o deles sem problema: foi um
    transiente do runner, nao um defeito. Uma segunda tentativa cobre isso;
    uma falha persistente propaga como antes.
    """
    try:
        return tk.Tk()
    except tk.TclError:
        gc.collect()
        time.sleep(0.5)
        return tk.Tk()


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
        self.root = criar_root()
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
        cancel_pending_after(self.root)

        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump(self):
        self.root.update()
