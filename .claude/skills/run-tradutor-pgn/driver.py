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
        """Devolve o `Toplevel` — nao ha instancia para devolver.

        Assimetria que custa caro e nao da para adivinhar:
        `open_translation_editor` devolve o `TranslationEditor`, entao la todo
        metodo e widget e alcancavel pelo nome. `open_glossary_editor` ainda e
        uma funcao com tudo em closures e devolve `None`; aqui o unico handle e
        a janela, e mexer nela e andar na arvore de widgets. Use `button`,
        `button_containing` e `label_starting` abaixo.
        """
        self.glossary_editor.open_glossary_editor(self.app)
        self.pump(1.2)
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        return tops[-1] if tops else None

    # ------------------------------------------------- achar widget sem handle

    @staticmethod
    def walk(widget):
        yield widget
        for filho in widget.winfo_children():
            yield from Driver.walk(filho)

    def widgets(self, raiz, kind):
        return [w for w in self.walk(raiz) if isinstance(w, kind)]

    def _texto(self, w):
        try:
            return w.cget("text") or ""
        except tk.TclError:
            return ""

    def button(self, raiz, rotulo):
        """Botao cujo rotulo e exatamente `rotulo`."""
        for w in self.widgets(raiz, self.ctk.CTkButton):
            if self._texto(w).strip() == rotulo:
                return w
        raise LookupError(
            f"botao {rotulo!r} nao encontrado; ha: "
            f"{sorted({self._texto(w).strip() for w in self.widgets(raiz, self.ctk.CTkButton)})}"
        )

    def button_containing(self, raiz, trecho):
        """Botao cujo rotulo CONTEM `trecho`.

        As linhas das listas tem rotulo de tres linhas
        (`AVISO  #1  -  Sugestao\\nDe: rook\\nPara: torre`), entao selecionar uma
        entrada e achar o botao por um pedaco do texto e invocar.
        """
        for w in self.widgets(raiz, self.ctk.CTkButton):
            if trecho in self._texto(w):
                return w
        raise LookupError(f"nenhum botao contem {trecho!r}")

    def label_starting(self, raiz, prefixo, so_visiveis=True):
        """Textos dos rotulos que comecam com `prefixo`.

        `so_visiveis` importa: o aviso de conflito existe sempre como widget e
        sai do grid quando nao ha conflito. Ler o texto sem checar
        `winfo_ismapped()` acha aviso que nao esta na tela.
        """
        achados = []
        for w in self.widgets(raiz, self.ctk.CTkLabel):
            texto = self._texto(w)
            if texto.startswith(prefixo) and (not so_visiveis or w.winfo_ismapped()):
                achados.append(texto)
        return achados

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


# ===========================================================================
# Worker de traducao — invocacao direta, sem abrir janela nenhuma
# ===========================================================================


class _RaizImediata:
    """`root.after(ms, cb)` executando na hora.

    O worker roda numa thread e agenda toda atualizacao de interface pela fila
    do Tk (garantia C1). Sem janela, executar na hora e o equivalente honesto —
    e e o que expoe os dialogos do fim da execucao, que precisam ser silenciados.
    """

    def after(self, _ms, callback=None, *a):
        if callback is not None:
            callback(*a)


class _ProgressoMudo:
    def set(self, _valor):
        pass


class HeadlessApp:
    """O minimo que `run_translation` exige. Nove atributos, nenhum widget."""

    def __init__(self, output_db, verboso=True):
        import threading

        self.output_db = output_db
        self.translation_cache = {}
        self.pause_flag = threading.Event()
        self.cancel_flag = threading.Event()
        self.is_processing = True
        self.root = _RaizImediata()
        self.progress = _ProgressoMudo()
        self.logs = []
        self.verboso = verboso

    def log_message(self, mensagem):
        self.logs.append(mensagem)
        if self.verboso:
            print(f"    [worker] {mensagem}")

    def _reset_buttons(self):
        pass


def run_worker(pgn, idioma="pt", traduzir=None, online=False, verboso=True):
    """Roda o worker de traducao de verdade sobre um PGN, sem abrir janela.

    `pgn` e o conteudo do arquivo. Devolve
    `(app, caminho_do_pgn_gerado, diretorio)`.

    Por padrao a rede e substituida por uma funcao determinista: o worker inteiro
    roda — lotes, cache, regras, gravacao, geracao do PGN —, so a chamada HTTP
    que nao acontece. Use `online=True` para exercitar a rede de verdade (endpoint
    publico do Google Translate; deixe o arquivo pequeno).

    O diretorio devolvido NAO e apagado: e onde estao o PGN gerado, o banco e o
    log para voce inspecionar.
    """
    if PROJETO not in sys.path:
        sys.path.insert(0, PROJETO)

    dados = tempfile.mkdtemp(prefix="pgn-worker-")
    argv0 = sys.argv[0]
    sys.argv[0] = os.path.join(dados, "PGN_Tradutor_Pro.py")

    from tradutor_pgn import translation_worker

    origem = os.path.join(dados, "entrada.pgn")
    with open(origem, "w", encoding="utf-8") as f:
        f.write(pgn)

    app = HeadlessApp(os.path.join(dados, "traducoes.db"), verboso=verboso)

    if traduzir is None and not online:
        def traduzir(texto, *_a, **_k):
            # Mantem o separador de lote intacto: o worker precisa reencontra-lo
            # para realinhar as partes (garantia B2).
            return " ||| ".join(f"[{p.strip()}]" for p in texto.split(" ||| "))

    anteriores = (
        translation_worker.translate_text,
        translation_worker.messagebox,
    )
    try:
        if traduzir is not None:
            translation_worker.translate_text = traduzir
        # O worker termina chamando `messagebox` pela fila do Tk. Com a raiz
        # imediata isso abre um dialogo modal DE VERDADE e trava o processo.
        translation_worker.messagebox = _SemDialogos
        translation_worker.run_translation(app, origem, idioma, False)
    finally:
        translation_worker.translate_text, translation_worker.messagebox = anteriores
        sys.argv[0] = argv0

    gerados = [
        os.path.join(dados, n)
        for n in os.listdir(dados)
        if n.endswith(".pgn") and n != "entrada.pgn"
    ]
    return app, (gerados[0] if gerados else None), dados


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
        d.shot("03-editor-glossario.png", glossario)
        print("glossario   | janela aberta")

        # Fluxo do editor de glossario: selecionar a regra que PERDE um conflito
        # e ler o aviso que diz qual esta valendo (garantia S9).
        d.seed(glossario_entradas=[
            ("rook", "torre", "suggestion"),
            ("rook", "torre alta", "suggestion"),   # perde para a de cima
            ("queen", "dama", "suggestion"),
        ])
        d.button(glossario, "Recarregar").invoke()
        d.pump()
        d.button_containing(glossario, "torre alta").invoke()
        d.pump()

        avisos = d.label_starting(glossario, "Conflito em")
        print(f"conflito    | {avisos[0] if avisos else 'NENHUM AVISO'}")
        d.shot("04-glossario-conflito.png", glossario)

        assert marcas == 1, "o Ctrl+B nao marcou o trecho"
        assert avisos, "o aviso de conflito (S9) nao apareceu na tela"
        assert "vence a regra" in avisos[0], "o aviso nao diz qual regra vence"
        print("\nOK")


def smoke_worker(online=False):
    """Roda o worker de traducao de ponta a ponta. Nenhuma janela e aberta."""
    pgn = (
        '[Event "Smoke"]\n\n'
        "1. e4 {The bishop eyes the long diagonal.} e5 {Black must be careful.}\n"
        "2. Nf3 {White develops with tempo.} Nc6 *\n"
    )
    app, saida, dados = run_worker(pgn, online=online)
    assert saida, "nenhum PGN de saida foi gerado"
    conteudo = open(saida, encoding="utf-8").read()
    print(f"\n  PGN gerado: {saida}")
    print(f"  dados em:   {dados}")
    assert "1. e4" in conteudo and "Nc6" in conteudo, "os lances nao sobreviveram (G1)"
    assert "{" in conteudo, "os comentarios sumiram"
    assert not any("FALHA" in linha for linha in app.logs), "houve falha de traducao"
    print("\nOK")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--real", action="store_true",
                   help="usa os dados reais do projeto (APAGA backups pela retencao S8)")
    p.add_argument("--worker", action="store_true",
                   help="roda o worker de traducao em vez da interface (sem janela)")
    p.add_argument("--online", action="store_true",
                   help="com --worker: usa a rede de verdade em vez da traducao falsa")
    args = p.parse_args()

    if args.worker:
        smoke_worker(online=args.online)
    else:
        if args.real:
            print("ATENCAO: rodando sobre os dados reais; a limpeza de arranque poda backups/.")
            Driver.__init__.__defaults__ = (False, True)
        smoke()
