"""Driver do PGN Tradutor Pro: sobe o app de verdade e deixa mexer nele.

O app e Tkinter/CustomTkinter, entao nao ha Playwright nem DevTools: o jeito de
dirigi-lo e carrega-lo NO PROPRIO PROCESSO e bombear o laco de eventos a mao.
`mainloop()` nao serve — ele bloqueia para sempre.

Uso como biblioteca:

    from driver import Driver
    with Driver() as d:
        editor = d.open_translation_editor()
        editor.select_index(0)
        d.pump()
        d.shot("editor.png", editor.win)

Uso como smoke test (abre tudo, captura, sai):

    python .claude/skills/run-tradutor-pgn/driver.py

Por padrao roda em SANDBOX: `sys.argv[0]` e apontado para um diretorio
temporario, e o app cria banco, glossario, settings, backups e logs la dentro.
Isso nao e preciosismo — na abertura o programa roda a retencao de `backups/`
(garantia S8), entao dirigi-lo sobre o diretorio real APAGA backups do usuario.
Use `Driver(sandbox=False)` so quando o alvo for exatamente o dado real.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk

PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CAPTURAS = os.path.join(PROJETO, ".claude", "skills", "run-tradutor-pgn", "capturas")


class _SemDialogos:
    """Todo `messagebox` responde sem abrir nada.

    Sem isto qualquer erro inesperado abre um dialogo modal de verdade e o
    driver trava para sempre — o app chama `showerror` de dentro de um
    `except Exception`, e ninguem vai clicar em OK.
    """

    showinfo = staticmethod(lambda *a, **k: None)
    showwarning = staticmethod(lambda *a, **k: None)
    showerror = staticmethod(lambda *a, **k: None)
    askyesno = staticmethod(lambda *a, **k: True)
    askokcancel = staticmethod(lambda *a, **k: True)


class _SemSeletorDeArquivo:
    """Todo seletor de arquivo responde "cancelado" (tambem sao modais)."""

    asksaveasfilename = staticmethod(lambda **k: "")
    askopenfilename = staticmethod(lambda **k: "")
    askdirectory = staticmethod(lambda **k: "")


class Driver:
    def __init__(self, sandbox=True, silenciar_dialogos=True):
        self.sandbox = sandbox
        self.silenciar = silenciar_dialogos
        self.dir_dados = None
        self.root = None
        self.app = None
        self._argv0 = None
        self._popup = None

    # ---------------------------------------------------------- ciclo de vida

    def start(self):
        if PROJETO not in sys.path:
            sys.path.insert(0, PROJETO)

        self._argv0 = sys.argv[0]
        if self.sandbox:
            self.dir_dados = tempfile.mkdtemp(prefix="pgn-driver-")
        else:
            self.dir_dados = PROJETO
        # TUDO no app deriva daqui: banco, glossario, settings, backups, logs.
        sys.argv[0] = os.path.join(self.dir_dados, "PGN_Tradutor_Pro.py")

        import customtkinter as ctk

        from tradutor_pgn import app_actions, db_tools, edit_window, glossary_editor
        from tradutor_pgn.app import PGNTranslatorApp

        self.ctk = ctk
        self.edit_window = edit_window
        self.glossary_editor = glossary_editor

        if self.silenciar:
            for modulo in (edit_window, glossary_editor, db_tools, app_actions):
                if hasattr(modulo, "messagebox"):
                    modulo.messagebox = _SemDialogos
                if hasattr(modulo, "filedialog"):
                    modulo.filedialog = _SemSeletorDeArquivo
            # `tk_popup` e modal: chamado de verdade, espera um clique humano.
            self._popup = tk.Menu.tk_popup
            tk.Menu.tk_popup = lambda self, x, y, *a: None

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.app = PGNTranslatorApp(self.root)
        # `bring_window_to_front` agenda `after(50)` e `after(200)`: antes disso
        # a janela ainda nao tem posicao e a captura sai preta ou torta.
        self.pump(1.5)
        return self

    def stop(self):
        if self._popup is not None:
            tk.Menu.tk_popup = self._popup
        if self.root is not None:
            # Cancelar os `after` pendentes antes de destruir, senao o Tk
            # imprime "invalid command name" no meio da saida.
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
            self.root = None
        if self._argv0 is not None:
            sys.argv[0] = self._argv0
        if self.sandbox and self.dir_dados:
            # No Windows um arquivo SQLite aberto nao pode ser apagado; se o app
            # deixou conexao viva, apagar falha. Nao e motivo para erro.
            shutil.rmtree(self.dir_dados, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()

    # --------------------------------------------------------------- controle

    def pump(self, segundos=0.8):
        """Roda o laco de eventos do Tk por um tempo. Substitui o `mainloop`."""
        fim = time.time() + segundos
        while time.time() < fim:
            if self.root is None:
                return
            self.root.update()
            time.sleep(0.02)

    def seed(self, traducoes=(), glossario_entradas=(), idioma="pt"):
        """Poe traducoes no banco e regras no glossario do sandbox."""
        from tradutor_pgn import glossario as g
        from tradutor_pgn.database import initialize_database, save_translation

        if traducoes:
            conn = initialize_database(self.app.output_db)
            cur = conn.cursor()
            for original, traduzido in traducoes:
                save_translation(cur, original, traduzido, idioma)
            conn.commit()
            conn.close()

        if glossario_entradas:
            g.save_glossary_entries(
                list(glossario_entradas),
                os.path.join(self.dir_dados, "Substituicoes.txt"),
                create_backup=False,
            )
            self.app.glossary_substitutions = g.load_interactive_substitutions()

    def open_translation_editor(self):
        """Devolve a instancia de `TranslationEditor` — da para chamar metodos."""
        editor = self.edit_window.open_translation_editor(self.app)
        self.pump(1.2)
        return editor

    def open_glossary_editor(self):
        self.glossary_editor.open_glossary_editor(self.app)
        self.pump(1.2)
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        return tops[-1] if tops else None

    def key(self, widget, atalho):
        """Dispara um atalho DE VERDADE no widget.

        `focus_set` primeiro nao e supersticao: sem um widget com foco o Tk
        simplesmente NAO entrega alguns eventos sinteticos (`<Control-f>` e um
        deles, enquanto `<Control-s>` chega).
        """
        widget.focus_set()
        self.pump(0.3)
        widget.event_generate(atalho)
        self.pump(0.5)

    def shot(self, nome, alvo=None):
        """Captura a regiao de um widget (ou a janela toda) num PNG.

        `ImageGrab` fotografa a TELA, entao o alvo precisa estar visivel e por
        cima. Uma janela `withdraw()`n sai como o que estiver atras dela.
        """
        from PIL import ImageGrab

        alvo = alvo if alvo is not None else self.root
        alvo.update_idletasks()
        self.pump(0.3)
        x, y = alvo.winfo_rootx(), alvo.winfo_rooty()
        w, h = alvo.winfo_width(), alvo.winfo_height()
        os.makedirs(CAPTURAS, exist_ok=True)
        caminho = os.path.join(CAPTURAS, nome)
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(caminho)
        print(f"  captura {caminho} ({w}x{h})")
        return caminho


def smoke():
    """Abre o app, as duas janelas de edicao, captura cada uma e sai."""
    with Driver() as d:
        print(f"app aberto  | dados em {d.dir_dados}")
        d.seed(
            traducoes=[
                ("The bishop dominates the long diagonal.", "O bispo domina a diagonal longa."),
                ("White has a decisive advantage.", "As brancas tem vantagem decisiva."),
            ],
            glossario_entradas=[("bishop", "bispo", "suggestion")],
        )
        d.shot("00-janela-principal.png")

        editor = d.open_translation_editor()
        editor.select_index(0)
        d.pump()
        print(f"editor      | {editor.state.total_rows} traducoes; "
              f"carregada: {editor.draft_text()[:40]!r}")
        d.shot("01-editor-traducoes.png", editor.win)

        # Um fluxo de usuario de ponta a ponta: marcar em negrito com Ctrl+B.
        texto = editor.draft_text()
        editor.trans_text.tag_add("sel", "1.0", f"1.0+{texto.index(' e ') if ' e ' in texto else 8}c")
        d.key(editor.trans_text, "<Control-b>")
        marcas = len(editor.trans_text.tag_ranges("bold")) // 2
        print(f"Ctrl+B      | {marcas} trecho(s) em negrito")
        d.shot("02-negrito-selecao.png", editor.trans_text)

        glossario = d.open_glossary_editor()
        if glossario is not None:
            d.shot("03-editor-glossario.png", glossario)
            print("glossario   | janela aberta")

        assert marcas == 1, "o Ctrl+B nao marcou o trecho"
        print("\nOK")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--real", action="store_true",
                   help="usa os dados reais do projeto (APAGA backups pela retencao S8)")
    args = p.parse_args()
    if args.real:
        print("ATENCAO: rodando sobre os dados reais; a limpeza de arranque poda backups/.")
        Driver.__init__.__defaults__ = (False, True)
    smoke()
