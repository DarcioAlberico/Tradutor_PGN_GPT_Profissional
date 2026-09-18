"""Os dubles e os moldes que os modulos de teste dividem entre si (ROADMAP 28.11).

`test_core.py` chegou a 21 mil linhas e 182 classes; foi dividido por dominio
(banco, ocorrencias, glossario, worker, api, ferramentas, pgn, notacao, editor,
settings, qa, corretor). Nenhum teste mudou — mudou o ciclo "mudei uma funcao,
rodo os testes dela". O que os modulos compartilham vive aqui: os `Fake*`, o
`WorkerFallbackHarness`, os PGN de amostra e o sandbox por modulo.

**Todo modulo de teste chama `setup_module_sandbox` no seu `setUpModule`**:
e o que impede um teste distraido de escrever no glossario real do projeto
(ver a docstring dela).
"""

import io
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import redirect_stdout
from pathlib import Path

from tradutor_pgn import (
    app_paths,
    glossario,
)
from tradutor_pgn.glossario import (
    GLOSSARY_PRIORITY_DEFAULT,
)
from tradutor_pgn.background_task import TaskCanceled
from tradutor_pgn.background_task import BackgroundTask
from tradutor_pgn import (
    translation_worker,
)




_GLOSSARY_SANDBOX = None


def setup_module_sandbox():
    """Impede que qualquer teste escreva no glossario real do projeto.

    `glossario._default_substitutions_path()` deriva o caminho de
    `sys.argv[0]`. Sob `python -m unittest`, `sys.argv[0]` e a string
    `'python.exe -m unittest'` — sem barra nenhuma —, entao
    `os.path.dirname(os.path.abspath(...))` resolve para o DIRETORIO ATUAL. Como
    a suite roda da raiz do projeto, o caminho padrao aponta para o
    `Substituicoes.txt` de verdade, com as milhares de regras do usuario.

    Hoje nenhum teste chama essas funcoes sem passar um caminho, mas basta um
    esquecimento para uma execucao da suite apagar entradas do glossario real,
    silenciosamente e sem relacao aparente com o teste que falhou. Redirecionar
    o padrao para um diretorio temporario elimina a categoria inteira.
    """
    global _GLOSSARY_SANDBOX
    _GLOSSARY_SANDBOX = tempfile.TemporaryDirectory(prefix="glossario-sandbox-")
    base = Path(_GLOSSARY_SANDBOX.name)
    # Uma alavanca so, e a MESMA que o programa usa: desde a separacao de
    # programa e dados (ROADMAP 21), todo caminho de usuario sai de
    # `app_paths.data_dir()`, e ele obedece a esta variavel. Antes eram tres
    # funcoes substituidas por dublês — o que protegia o glossario real e, de
    # quebra, escondia dos testes o codigo que de fato calcula os caminhos.
    os.environ[app_paths.DATA_DIR_ENV] = str(base)
    # A semente tambem sai do caminho, e por uma razao diferente: ela EXISTE no
    # repositorio e e mesclada em toda carga de regras (garantia S15), entao um
    # teste que compara a lista de regras exata veria a terminologia embutida
    # junto. Quem quer exercitar a semente passa `seed_path` explicitamente —
    # ver `SeedGlossaryTests`.
    glossario._default_seed_path = lambda: str(base / "semente-inexistente.txt")


def teardown_module_sandbox():
    os.environ.pop(app_paths.DATA_DIR_ENV, None)
    if _GLOSSARY_SANDBOX is not None:
        _GLOSSARY_SANDBOX.cleanup()


def call_quietly(func, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


class FakeRoot:
    def after(self, _delay, callback=None):
        if callback is not None:
            callback()


class FakeProgress:
    def __init__(self):
        self.value = 0

    def set(self, value):
        self.value = value


class FakeWindow:
    def __init__(self, width=1920, height=1080):
        self.width = width
        self.height = height

    def winfo_screenwidth(self):
        return self.width

    def winfo_screenheight(self):
        return self.height


class FakeApp:
    def __init__(self, db_path):
        self.output_db = str(db_path)
        self.translation_cache = {}
        self.pause_flag = threading.Event()
        self.cancel_flag = threading.Event()
        self.root = FakeRoot()
        self.progress = FakeProgress()
        self.is_processing = True
        self.logs = []
        self.reset_called = False

    def log_message(self, message):
        self.logs.append(message)

    def _reset_buttons(self):
        self.reset_called = True


def com_prioridade(entries, priority=GLOSSARY_PRIORITY_DEFAULT, scope=""):
    """Entradas de tres campos como o arquivo as devolve: com prioridade e escopo.

    A entrada detalhada ganhou um quarto campo no item 1.5 parte 2 e um quinto na
    secao 15. Nos testes cujo assunto nao e nenhum dos dois, escrever `, 0, ""`
    em cada tupla so acrescenta ruido — mas apagar os campos da comparacao
    esconderia um deles mexido por engano. Este helper diz explicitamente o que
    se espera nos dois.
    """
    return [
        (orig, new, rule_type, priority, scope) for orig, new, rule_type in entries
    ]


class SynchronousProgress:
    """Substitui `run_with_progress` rodando o trabalho na hora.

    O `run_with_progress` de verdade abre um `CTkToplevel` e sobe uma thread que
    so devolve o resultado por `root.after` — o que exige display e um
    `mainloop()` rodando. Os testes abaixo verificam a ORQUESTRACAO das
    operacoes de banco (o que e chamado, em que ordem, o que acontece ao
    cancelar), e nada disso e sobre a thread.

    O substituto e fiel no que importa: chama o trabalho com um
    `BackgroundTask` de verdade e despacha para `on_success`/`on_error`/
    `on_cancel` pelo mesmo criterio do original. E registra cada chamada, que e
    o que permite exigir que uma operacao passe por aqui — se alguem devolver o
    trabalho para dentro do callback do Tk, a lista fica vazia.
    """

    def __init__(self, cancelar=False):
        self.chamadas = []
        self.cancelar = cancelar

    def install(self, testcase, modulo):
        testcase.addCleanup(setattr, modulo, "run_with_progress", modulo.run_with_progress)
        modulo.run_with_progress = self

    def __call__(
        self,
        parent,
        title,
        work,
        on_success=None,
        on_error=None,
        on_cancel=None,
        message="Processando...",
        allow_cancel=True,
    ):
        self.chamadas.append({"title": title, "message": message, "allow_cancel": allow_cancel})

        task = BackgroundTask()
        if self.cancelar:
            task.cancel()

        try:
            resultado = work(task)
        except TaskCanceled:
            if on_cancel is not None:
                on_cancel(None)
            return task
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            return task

        destino = on_cancel if task.cancelado() else on_success
        if destino is not None:
            destino(resultado)
        return task

    def titles(self):
        return [c["title"] for c in self.chamadas]


def _stamp(moment):
    return moment.strftime("%Y%m%d-%H%M%S")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("resposta nao e JSON")
        return self._payload


class FakeSession:
    """Devolve respostas roteirizadas e conta as requisicoes."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self.script.pop(0) if self.script else FakeResponse(200, [[["", ""]]])
        if isinstance(item, Exception):
            raise item
        return item


class WorkerFallbackHarness:
    """Roda `run_translation` com a rede substituida por uma funcao do teste.

    Fica separado do `TestCase` porque duas classes precisam dele (B2 e C3) e
    herdar de uma classe de teste faria os testes da outra rodarem duas vezes.
    """

    PGN = (
        '[Event "Test"]\n\n'
        "1. e4 {First comment here} e5 {Second comment here} "
        "2. Nf3 {Third comment here}\n"
    )
    COMMENTS = ["First comment here", "Second comment here", "Third comment here"]

    def run_worker(self, tmp_path, translate, **kwargs):
        """`kwargs` vao para `run_translation` (o `provider` de 28.7, por exemplo)."""
        pgn = tmp_path / "game.pgn"
        pgn.write_text(self.PGN, encoding="utf-8")
        app = FakeApp(tmp_path / "cache.db")

        # `showerror` TAMBEM: o `except Exception` do worker cai nele, e o
        # `FakeRoot.after` executa na hora — sem isto, um teste que force o
        # `[ERRO GERAL]` abre um dialogo modal de verdade e a suite trava em
        # vez de falhar (a mesma armadilha do `setUp` de TranslationWorkerTests;
        # custou 40 minutos de suite parada em 2026-09-14).
        originals = (
            translation_worker.translate_text,
            translation_worker.messagebox.showinfo,
            translation_worker.messagebox.showwarning,
            translation_worker.messagebox.showerror,
        )
        try:
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            translation_worker.messagebox.showwarning = lambda *_a, **_k: None
            translation_worker.messagebox.showerror = lambda *_a, **_k: None
            translation_worker.run_translation(app, str(pgn), "pt", False, **kwargs)
        finally:
            (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
                translation_worker.messagebox.showerror,
            ) = originals

        return app, pgn

    def stored(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return dict(
                conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()


def escrita_disponivel(db_path, espera_ms=2000):
    """True se OUTRA conexao consegue pegar o lock de escrita agora.

    `BEGIN IMMEDIATE` + `ROLLBACK`: pega o lock e devolve sem alterar nada. E a
    pergunta que o editor faz implicitamente toda vez que grava uma traducao
    enquanto o worker esta rodando.

    A espera curta e proposital. Em producao o `busy_timeout` e 30 s; aqui, uma
    regressao que volte a segurar o lock deve falhar em 2 s, e nao arrastar o
    teste por meio minuto.
    """
    conn = sqlite3.connect(str(db_path), timeout=espera_ms / 1000)
    try:
        conn.execute(f"PRAGMA busy_timeout = {espera_ms}")
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


# PGN com tudo o que a normalizacao NAO pode tocar: variantes aninhadas,
# comentarios contendo nomes que o dicionario corrigiria numa tag, NAGs,
# avaliacoes e uma tag fora da lista das cinco suportadas.
PGN_COMPLETO = (
    '[Event "WCh"]\n'
    '[Site "Londres"]\n'
    '[Round "1.0"]\n'
    '[White "GM Aberg, Anton"]\n'
    '[Black "J. S. Speelman"]\n'
    '[Result "1-0"]\n'
    '[ECO "B76"]\n'
    '[Annotator "GM Aberg, Anton"]\n'
    '\n'
    '1. e4 c5 {GM Aberg, Anton comenta aqui} 2. Nf3 d6 $1 3. d4 cxd4\n'
    '4. Nxd4 Nf6 (4... g6 5. Nc3 {Londres seria trocada se fosse tag} Bg7\n'
    '(5... a6 6. Be3 $14) 6. Be3) 5. Nc3 g6 $6 {J. S. Speelman aqui tambem}\n'
    '6. Be3 Bg7 1-0\n'
)

def _movetext(texto):
    """So as linhas de lance: tudo o que nao e cabecalho nem linha em branco."""
    return [
        linha
        for linha in texto.splitlines()
        if linha.strip() and not linha.lstrip().startswith("[")
    ]


def _tags(texto):
    return dict(
        re.findall(r'^\[(\w+)\s+"(.*)"\]', texto, flags=re.MULTILINE)
    )


# ===========================================================================
# Idioma de origem: schema, migracao, adocao e filtro
# ===========================================================================


def _schema3_database(db_path):
    """Um banco no schema 3 — o que existia antes de a origem entrar na chave.

    Escrito a mao, e nao gerado pelo programa: o ponto do teste e que a migracao
    receba exatamente a tabela antiga, com a UNIQUE antiga e sem a coluna nova.
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_comment TEXT,
            translated_comment TEXT,
            target_language TEXT,
            verified INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            verified_at TEXT,
            quality_warning INTEGER,
            UNIQUE(original_comment, target_language)
        );
        CREATE TABLE comment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            previous_translation TEXT,
            new_translation TEXT,
            previous_verified INTEGER,
            new_verified INTEGER,
            created_at TEXT
        );
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()


def _chess_installed():
    try:
        import chess  # noqa: F401
    except ImportError:
        return False
    return True


PGN_COM_VARIANTES = (
    '[Event "T"]\n[White "A"]\n[Black "B"]\n[Result "*"]\n\n'
    "{Antes do primeiro lance.} 1. e4 {Depois de e4.} "
    "({Em vez disso} 1. d4 {d4 comentado} d5 ({ou} 1... Nf6 {cavalo}) 2. c4 {gambito}) "
    "1... c5 {Siciliana} 2. Nf3 {} d6 {Dragao a caminho} *\n"
)


def _pgn_com_comentarios(caminho, quantos, tamanho=180, prefixo="c"):
    """PGN sintetico com `quantos` comentarios distintos. Devolve o caminho.

    Usado nas medicoes da secao 20: os testes de custo precisam de um arquivo
    grande o bastante para que a diferenca entre O(n) e O(n.m) apareca, e pequeno
    o bastante para a suite nao demorar.
    """
    partes = ['[Event "Medicao"]\n[Site "?"]\n\n']
    for i in range(quantos):
        partes.append(f"{i % 60 + 1}. Nf3 {{{prefixo} {i} " + "x" * tamanho + "}} Nf6 ")
        if i % 20 == 19:
            partes.append("\n")
    partes.append("1-0\n")
    Path(caminho).write_text("".join(partes), encoding="utf-8", newline="")
    return str(caminho)
