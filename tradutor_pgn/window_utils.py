import sqlite3
import time
import traceback


DATABASE_BUSY_TITLE = "Banco de dados ocupado"
DATABASE_ERROR_TITLE = "Erro no banco de dados"
UNEXPECTED_ERROR_TITLE = "Erro inesperado"

# Janela em que a MESMA mensagem nao reabre o dialogo. Curta de proposito: ela
# existe para conter uma rajada (um callback periodico que falha sempre encheria
# a tela de dialogos), e nao para calar o erro — quem clicar em "Salvar" de novo
# daqui a alguns segundos precisa ser avisado de novo.
ERROR_DIALOG_REPEAT_SECONDS = 2.0


def describe_callback_error(exc):
    """`(titulo, mensagem)` para uma excecao que escapou de um callback do Tk.

    Funcao pura, para ser testada sem abrir janela. O lock do SQLite tem texto
    proprio porque e o unico caso previsto e com causa conhecida: o worker e o
    editor usam o mesmo `traducoes.db` e duas conexoes nunca escrevem ao mesmo
    tempo, nem em WAL (garantia C3). Dizer "erro inesperado" ali seria esconder
    do usuario justamente a informacao que resolve o problema — esperar.
    """
    if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
        return (
            DATABASE_BUSY_TITLE,
            "O banco de dados esta sendo usado por outra parte do programa, "
            "provavelmente uma traducao em andamento.\n\n"
            "Nada foi gravado. Espere alguns segundos e tente de novo.",
        )
    if isinstance(exc, sqlite3.Error):
        return (
            DATABASE_ERROR_TITLE,
            f"Nao foi possivel acessar o banco de dados:\n\n"
            f"{type(exc).__name__}: {exc}\n\nNada foi gravado.",
        )
    return (
        UNEXPECTED_ERROR_TITLE,
        f"A operacao foi interrompida por um erro:\n\n{type(exc).__name__}: {exc}",
    )


def install_callback_error_reporter(
    root,
    log_message=None,
    show_error=None,
    now=time.monotonic,
):
    """Faz um erro em callback do Tk virar mensagem, e nao traceback invisivel.

    Empacotado com `pythonw` nao ha console nenhum: hoje qualquer excecao que
    escape de um callback simplesmente desaparece, e a operacao apenas nao
    acontece. Era o buraco que a garantia C3 deixou em aberto para o
    `sqlite3.OperationalError` — mas ele nunca foi so do lock, e sim de todo
    callback do programa.

    O gancho e o do proprio Tk: `Misc._report_exception` chama
    `self._root().report_callback_exception(...)`, entao instalar na raiz cobre
    tambem as janelas de edicao, que sao `Toplevel` dessa raiz.

    Tratar aqui, e nao em cada acesso ao banco, e o que mantem o comportamento
    atual: a excecao continua abortando o fluxo em andamento. Capturar dentro de
    `save_changes` e seguir seria pior do que hoje — a navegacao continuaria e a
    edicao do usuario seria descartada em silencio.
    """
    if show_error is None:
        from tkinter import messagebox

        show_error = messagebox.showerror

    ultimo = {"chave": None, "quando": None}

    def handler(exc_type, exc_value, exc_tb):
        titulo, mensagem = describe_callback_error(exc_value)

        if log_message is not None:
            log_message(f"[ERRO] {titulo}: {type(exc_value).__name__}: {exc_value}")
            detalhe = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            ).rstrip()
            if detalhe:
                log_message(detalhe)

        chave = (titulo, mensagem)
        agora = now()
        if (
            ultimo["chave"] == chave
            and ultimo["quando"] is not None
            and agora - ultimo["quando"] < ERROR_DIALOG_REPEAT_SECONDS
        ):
            return
        ultimo["chave"] = chave
        ultimo["quando"] = agora

        try:
            show_error(titulo, mensagem)
        except Exception:
            # O relator de erros nao pode ser a proxima fonte de erro.
            pass

    # Resolvido para a raiz de verdade. `Misc._report_exception` procura o
    # handler em `self._root()`, entao instalar num `Toplevel` produziria o pior
    # resultado possivel: tudo parece configurado e nada nunca dispara — que e
    # exatamente a classe de defeito que este relator existe para eliminar.
    alvo = root
    resolver = getattr(root, "_root", None)
    if callable(resolver):
        try:
            alvo = resolver()
        except Exception:
            alvo = root

    alvo.report_callback_exception = handler
    return handler


def bring_window_to_front(window, parent=None, maximize=False):
    """Levanta a janela, e opcionalmente a maximiza.

    **`maximize` e agendado a +50 ms, e por isso ele VENCE qualquer
    `geometry()` chamado depois.** Era esse o defeito: os dois editores
    restauravam a geometria salva na construcao e a chamada agendada aqui a
    sobrescrevia meio segundo depois — todo o caminho de `safe_geometry`, com
    `clamp_geometry` e testes, estava morto na pratica. Quem quer restaurar
    tamanho e posicao nao pode pedir `maximize=True`; ver
    `restore_or_maximize`.
    """
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


def restore_or_maximize(window, parent, geometry):
    """Restaura a geometria salva; sem ela, maximiza.

    Os dois editores faziam as duas coisas — `bring_window_to_front(...,
    maximize=True)` na construcao e `geometry(saved)` logo depois — e a segunda
    perdia sempre, porque a primeira e agendada e roda por ultimo. O resultado
    era que a janela ignorava em silencio o tamanho e a posicao que o usuario
    tinha deixado, e nada no codigo parecia errado: as duas linhas estavam la.

    Escolher aqui, num lugar so, e o que torna a decisao visivel — sao
    alternativas, e nao duas configuracoes que se somam. Sem geometria salva
    (primeira abertura) maximizar continua sendo o certo: as duas janelas sao
    listas largas, e abrir em 1280x760 num monitor grande desperdicaria a tela.

    Devolve `True` se restaurou, `False` se maximizou — o teste precisa poder
    distinguir os dois sem inspecionar a janela.
    """
    if isinstance(geometry, str) and geometry:
        try:
            window.geometry(geometry)
        except Exception:
            bring_window_to_front(window, parent, maximize=True)
            return False
        bring_window_to_front(window, parent, maximize=False)
        return True

    bring_window_to_front(window, parent, maximize=True)
    return False
