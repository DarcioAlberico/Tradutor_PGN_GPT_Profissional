"""Testes do despachante de tarefas em segundo plano.

`run_with_progress` e o que tira backup, restauracao, importacao de CSV e
"Aplicar automaticas" da thread da interface (ROADMAP 2.11). Sao sete pontos de
chamada em `db_tools`, e **o despachante em si nao tinha teste nenhum**: 17% de
cobertura, com todo o corpo da funcao (linhas 73-173) sem exercicio.

O motivo era razoavel. Os testes dos chamadores usam o `SynchronousProgress`,
que roda o trabalho na hora, porque o que eles verificam e a orquestracao das
operacoes de banco e nao a thread. O efeito colateral e que **o substituto
duplica o criterio de despacho do original**: se o de verdade mudasse, o dublê
manteria o comportamento antigo e todos os testes dos chamadores continuariam
passando.

Aqui o alvo e o contrario: a mecanica de thread e de janela, com a coisa real.
O que estes testes fixam e a garantia C1 — o trabalho roda fora da thread do Tk,
e tudo o que volta chega na thread do Tk.

Precisam de display; sem ele a classe inteira e pulada.
"""

import threading
import time
import tkinter as tk
import unittest

# `gui_harness`, e nao `tests.gui_harness`: o runner documentado no README e
# `unittest discover -s tests`, que poe `tests/` no `sys.path` — e nao a raiz do
# projeto. Com o nome pontuado este modulo INTEIRO deixava de ser carregado,
# ficando como um unico `ImportError` no meio de 1.369 testes que passavam. Os
# outros dois modulos de janela sempre usaram a forma sem ponto.
from gui_harness import GuiTestCase
from tradutor_pgn import background_task
from tradutor_pgn.background_task import (
    BackgroundTask,
    TaskCanceled,
    run_with_progress,
)


class BackgroundTaskHandleTests(unittest.TestCase):
    """O handle passado para a funcao de trabalho. Nao precisa de Tk."""

    def test_starts_uncanceled(self):
        self.assertFalse(BackgroundTask().cancelado())

    def test_cancel_is_visible_to_the_worker(self):
        task = BackgroundTask()
        task.cancel()
        self.assertTrue(task.cancelado())

    def test_raise_if_canceled_is_quiet_until_it_is(self):
        task = BackgroundTask()
        task.raise_if_canceled()          # nao levanta
        task.cancel()
        with self.assertRaises(TaskCanceled):
            task.raise_if_canceled()

    def test_report_forwards_to_the_callback(self):
        recebidos = []
        task = BackgroundTask(on_progress=lambda f, t: recebidos.append((f, t)))
        task.report(3, 10)
        self.assertEqual(recebidos, [(3, 10)])

    def test_report_without_a_callback_is_a_no_op(self):
        # O trabalho nao deve precisar saber se alguem esta ouvindo.
        BackgroundTask().report(1, 2)


class RunWithProgressTests(GuiTestCase):
    """`run_with_progress` de verdade: thread, janela e despacho."""

    def setUp(self):
        super().setUp()
        self.main_thread = threading.get_ident()
        self.resultados = []

    # ---------------- infra ----------------

    def _run(self, work, **kwargs):
        """Dispara a tarefa registrando por onde ela voltou."""
        opcoes = {
            "on_success": lambda valor: self.resultados.append(
                ("success", valor, threading.get_ident())
            ),
            "on_error": lambda exc: self.resultados.append(
                ("error", exc, threading.get_ident())
            ),
            "on_cancel": lambda valor: self.resultados.append(
                ("cancel", valor, threading.get_ident())
            ),
        }
        opcoes.update(kwargs)
        return run_with_progress(self.root, "Teste", work, **opcoes)

    def _pump_until(self, condicao, timeout=10.0):
        """Roda o laco de eventos DE VERDADE ate a condicao valer.

        Tem de ser `mainloop()`, e nao um laco de `update()`: a thread de
        trabalho devolve o controle por `parent.after`, e o Tk so aceita `after`
        vindo de outra thread enquanto a principal esta DENTRO do mainloop. Fora
        dele levanta `RuntimeError: main thread is not in main loop` — que o
        `run_with_progress` engole de proposito, porque a essa altura nao ha
        mais a quem avisar.

        Isso faz do laco de `update()` a pior armadilha possivel aqui: nada
        acusa o problema, o trabalho roda ate o fim e a resposta simplesmente
        desaparece. A primeira versao destes testes caiu exatamente nisso, com
        12 falhas identicas de "nunca devolveu o controle" — e o defeito era do
        teste, nao da producao, que roda sob `mainloop()`.

        A condicao e conferida de dentro do proprio laco, por um `after`
        encadeado; o `quit()` devolve o controle para o teste.
        """
        alcancada = {"ok": False}
        limite = time.monotonic() + timeout

        def checar():
            if condicao():
                alcancada["ok"] = True
                self.root.quit()
            elif time.monotonic() > limite:
                self.root.quit()
            else:
                self.root.after(10, checar)

        self.root.after(0, checar)
        self.root.mainloop()
        return alcancada["ok"]

    def _aguardar_resposta(self):
        self.assertTrue(
            self._pump_until(lambda: self.resultados),
            "a tarefa nunca devolveu o controle para a thread do Tk",
        )
        return self.resultados[0]

    def _janelas(self):
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]

    # ---------------- garantia C1 ----------------

    def test_the_work_runs_off_the_tk_thread(self):
        """Se rodasse na thread do Tk, a janela congelaria — o bug do 2.11."""
        onde = {}
        self._run(lambda task: onde.setdefault("thread", threading.get_ident()))
        self._aguardar_resposta()

        self.assertIn("thread", onde)
        self.assertNotEqual(
            onde["thread"], self.main_thread, "o trabalho rodou na thread da interface"
        )

    def test_the_answer_comes_back_on_the_tk_thread(self):
        """A outra metade da C1: nenhum callback toca widget fora da thread."""
        self._run(lambda task: "pronto")
        tipo, valor, thread = self._aguardar_resposta()

        self.assertEqual((tipo, valor), ("success", "pronto"))
        self.assertEqual(thread, self.main_thread)

    # ---------------- despacho ----------------

    def test_an_exception_goes_to_on_error(self):
        falha = ValueError("deu ruim")

        def work(task):
            raise falha

        self._run(work)
        tipo, valor, thread = self._aguardar_resposta()

        self.assertEqual(tipo, "error")
        self.assertIs(valor, falha)
        self.assertEqual(thread, self.main_thread)
        self.assertEqual(len(self.resultados), 1, "nao pode avisar duas vezes")

    def test_task_canceled_goes_to_on_cancel(self):
        def work(task):
            raise TaskCanceled()

        self._run(work)
        tipo, _valor, _thread = self._aguardar_resposta()

        self.assertEqual(tipo, "cancel")

    def test_returning_normally_after_a_cancel_still_counts_as_canceled(self):
        """O trabalho pode desistir devolvendo em vez de levantar.

        Varias operacoes de `db_tools` conferem `cancelado()` e saem com o que
        deu tempo de fazer. Esse retorno NAO e sucesso: tratar como sucesso
        anunciaria "importacao concluida" para uma importacao interrompida.
        """

        def work(task):
            task.cancel()
            return "parcial"

        self._run(work)
        tipo, valor, _thread = self._aguardar_resposta()

        self.assertEqual(tipo, "cancel")
        self.assertEqual(valor, "parcial")

    def test_a_result_of_none_is_still_a_success(self):
        # `None` e um retorno legitimo; nao pode ser confundido com desistencia.
        self._run(lambda task: None)
        tipo, valor, _thread = self._aguardar_resposta()

        self.assertEqual((tipo, valor), ("success", None))

    def test_missing_callbacks_are_tolerated(self):
        terminou = threading.Event()
        run_with_progress(
            self.root, "Teste", lambda task: terminou.set() or "x"
        )
        self.assertTrue(self._pump_until(terminou.is_set))
        # E a janela some do mesmo jeito, sem ninguem para avisar.
        self.assertTrue(self._pump_until(lambda: not self._janelas()))

    # ---------------- janela ----------------

    def test_the_progress_window_opens_and_closes(self):
        liberar = threading.Event()

        def work(task):
            liberar.wait(5)
            return "ok"

        self._run(work)
        self.assertTrue(
            self._pump_until(lambda: len(self._janelas()) == 1),
            "a janela de progresso nao apareceu",
        )

        liberar.set()
        self._aguardar_resposta()
        self.assertTrue(
            self._pump_until(lambda: not self._janelas()),
            "a janela de progresso ficou aberta depois do fim",
        )

    def test_the_cancel_button_reaches_the_worker(self):
        viu_cancelamento = threading.Event()

        def work(task):
            for _ in range(500):
                if task.cancelado():
                    viu_cancelamento.set()
                    raise TaskCanceled()
                time.sleep(0.01)
            return "terminou sozinho"

        self._run(work)
        self.assertTrue(self._pump_until(lambda: len(self._janelas()) == 1))

        botao = self._botao_cancelar()
        botao.invoke()

        self.assertTrue(
            self._pump_until(viu_cancelamento.is_set),
            "o trabalho nunca enxergou o cancelamento",
        )
        tipo, _valor, _thread = self._aguardar_resposta()
        self.assertEqual(tipo, "cancel")

    def test_cancel_can_be_forbidden(self):
        liberar = threading.Event()
        self._run(lambda task: liberar.wait(5), allow_cancel=False)
        self.assertTrue(self._pump_until(lambda: len(self._janelas()) == 1))

        self.assertEqual(str(self._botao_cancelar().cget("state")), "disabled")

        liberar.set()
        self._aguardar_resposta()

    def test_progress_reports_reach_the_window(self):
        """`report` e chamado da thread de trabalho e so pode AGENDAR."""
        liberar = threading.Event()

        def work(task):
            task.report(30, 100)
            liberar.wait(5)
            return "ok"

        self._run(work)
        self.assertTrue(self._pump_until(lambda: len(self._janelas()) == 1))
        self.assertTrue(
            self._pump_until(lambda: self._texto_detalhe() != ""),
            "o progresso nunca chegou na janela",
        )
        self.assertIn("30", self._texto_detalhe())

        liberar.set()
        self._aguardar_resposta()

    def test_reporting_after_the_window_closed_is_harmless(self):
        """A thread pode relatar depois do fim; isso nao pode virar excecao."""
        task_ref = {}

        def work(task):
            task_ref["task"] = task
            return "ok"

        self._run(work)
        self._aguardar_resposta()
        self.assertTrue(self._pump_until(lambda: not self._janelas()))

        task_ref["task"].report(1, 2)     # janela ja destruida
        self.root.update()

    # ---------------- helpers de widget ----------------

    def _widgets(self, kind):
        def descend(widget):
            yield widget
            for child in widget.winfo_children():
                yield from descend(child)

        encontrados = []
        for janela in self._janelas():
            encontrados.extend(w for w in descend(janela) if isinstance(w, kind))
        return encontrados

    def _botao_cancelar(self):
        botoes = self._widgets(background_task.ctk.CTkButton)
        self.assertTrue(botoes, "a janela de progresso nao tem botao")
        return botoes[0]

    def _texto_detalhe(self):
        textos = [
            str(w.cget("text")) for w in self._widgets(background_task.ctk.CTkLabel)
        ]
        # O primeiro rotulo e a mensagem fixa; o detalhe e o que muda.
        return next((t for t in textos if any(c.isdigit() for c in t)), "")


if __name__ == "__main__":
    unittest.main()
