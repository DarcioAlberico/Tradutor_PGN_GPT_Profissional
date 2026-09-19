"""O log pelo `logging` (ROADMAP 28.11): a porta, a fila, o arquivo, os niveis
e o que as bibliotecas de terceiros dizem."""

import io
import logging
import queue
import types
import unittest

from tradutor_pgn import app_log
from tradutor_pgn.app_log import LOGGER, AppLogHandler, format_record, install, level_of

from helpers import setup_module_sandbox, teardown_module_sandbox


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


def app_falso(handle=None):
    return types.SimpleNamespace(log_queue=queue.Queue(), _log_file_handle=handle)


class LevelTests(unittest.TestCase):
    def test_the_prefix_the_program_already_writes_is_the_level(self):
        casos = {
            "[ERRO GERAL] x": logging.ERROR,
            "[ERRO] Motor 'x' indisponivel": logging.ERROR,
            "[ABORTADO] 3 lotes seguidos": logging.ERROR,
            "  - [FALHA] Nao foi possivel traduzir": logging.WARNING,
            "[AVISO] Nao foi possivel anotar": logging.WARNING,
            "ATENCAO: 3 comentario(s) permaneceram": logging.WARNING,
            "Cache carregado: 12": logging.INFO,
            "": logging.INFO,
        }
        for mensagem, nivel in casos.items():
            with self.subTest(mensagem=mensagem):
                self.assertEqual(level_of(mensagem), nivel)


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = app_falso(io.StringIO())
        self.handler = install(self.app)
        self.addCleanup(LOGGER.removeHandler, self.handler)

    def drenar(self):
        itens = []
        while not self.app.log_queue.empty():
            itens.append(self.app.log_queue.get_nowait())
        return itens

    def test_the_message_reaches_the_queue_and_the_file_with_the_old_stamp(self):
        app_log.log("Cache carregado: 12")
        self.assertEqual(self.drenar(), ["Cache carregado: 12"])
        linha = self.app._log_file_handle.getvalue()
        self.assertRegex(linha, r"^\[\d\d:\d\d:\d\d\] Cache carregado: 12\n$")

    def test_without_a_file_the_queue_still_gets_it(self):
        self.app._log_file_handle = None
        app_log.log("[AVISO] sem arquivo")
        self.assertEqual(self.drenar(), ["[AVISO] sem arquivo"])

    def test_a_closed_or_full_file_does_not_take_the_screen_down(self):
        class Quebrado:
            def write(self, _texto):
                raise OSError("disco cheio")

            def flush(self):
                pass

        self.app._log_file_handle = Quebrado()
        app_log.log("continua na tela")
        self.assertEqual(self.drenar(), ["continua na tela"])
        fechado = io.StringIO()
        fechado.close()
        self.app._log_file_handle = fechado
        app_log.log("arquivo fechado")
        self.assertEqual(self.drenar(), ["arquivo fechado"])

    def test_assert_logs_sees_the_level(self):
        with self.assertLogs(LOGGER, level="WARNING") as capturado:
            app_log.log("[FALHA] um")
            app_log.log("informacao que nao conta")
            app_log.log("[ERRO] dois")
        self.assertEqual([r.levelno for r in capturado.records], [logging.WARNING, logging.ERROR])
        self.drenar()

    def test_a_third_party_warning_is_labelled_and_its_info_is_not_heard(self):
        externo = logging.getLogger("anthropic._base_client")
        externo.setLevel(logging.DEBUG)
        externo.warning("Retrying request to /v1/messages in 0.5 seconds")
        externo.info("HTTP Request: POST ...")
        self.assertEqual(
            self.drenar(),
            ["[AVISO] anthropic._base_client: Retrying request to /v1/messages in 0.5 seconds"],
        )
        externo.error("boom")
        self.assertEqual(self.drenar(), ["[ERRO] anthropic._base_client: boom"])

    def test_the_program_message_does_not_go_twice_through_the_root(self):
        """`tradutor_pgn` nao propaga, e mesmo que passe a propagar o handler
        da raiz ignora o programa: uma linha, nunca duas."""
        app_log.log("[ERRO] uma vez")
        self.assertEqual(self.drenar(), ["[ERRO] uma vez"])
        LOGGER.propagate = True
        self.addCleanup(setattr, LOGGER, "propagate", False)
        app_log.log("[ERRO] propagando")
        self.assertEqual(self.drenar(), ["[ERRO] propagando"])

    def test_installing_for_a_second_app_moves_the_log_to_it(self):
        outro = app_falso()
        segundo = install(outro)
        self.addCleanup(LOGGER.removeHandler, segundo)
        app_log.log("para o segundo")
        self.assertEqual(self.drenar(), [])
        self.assertEqual(outro.log_queue.get_nowait(), "para o segundo")
        handlers = [h for h in LOGGER.handlers if isinstance(h, AppLogHandler)]
        self.assertEqual(len(handlers), 1, "um app por vez, sem acumular handlers")
        raiz = [h for h in logging.getLogger().handlers if isinstance(h, AppLogHandler)]
        self.assertEqual(len(raiz), 1)


class FormatTests(unittest.TestCase):
    def test_an_exception_travels_with_its_traceback(self):
        try:
            raise ValueError("x")
        except ValueError:
            record = LOGGER.makeRecord(LOGGER.name, logging.ERROR, __file__, 1, "[ERRO] caiu", (), True)
            # `makeRecord` com exc_info=True nao captura sozinho: e o `sys.exc_info()`.
            import sys

            record.exc_info = sys.exc_info()
        texto = format_record(record)
        self.assertTrue(texto.startswith("[ERRO] caiu\nTraceback"))
        self.assertIn("ValueError: x", texto)


if __name__ == "__main__":
    unittest.main()
