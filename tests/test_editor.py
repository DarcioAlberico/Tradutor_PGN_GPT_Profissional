"""As funcoes puras e os widgets compartilhados do editor, historico e janela.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import io
import sqlite3
import sys
import types
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from tradutor_pgn import (
    app_actions,
    history_window,
    settings,
)
from tradutor_pgn.database import (
    count_comment_history,
    fetch_comment_history,
    machine_translation_for,
    initialize_database,
    save_translation,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    add_to_glossary,
    load_substitutions,
)
from tradutor_pgn.editor_text import diff_spans
from tradutor_pgn.editor_common import (
    clamp_geometry,
    clamp_page,
    local_index_for_offset,
    page_count,
    page_of_offset,
    page_offset,
    preview,
    row_index_for_id,
)
from tradutor_pgn.editor_text import find_text_ranges, replace_all_text, replace_text_range
from tradutor_pgn import edit_window
from tradutor_pgn.edit_window import safe_geometry
from tradutor_pgn.glossary_editor import safe_geometry as glossary_safe_geometry
from tradutor_pgn import (
    editor_common,
    editor_widgets,
    window_utils,
)
from tradutor_pgn.glossario import (
    clear_glossary_error,
    last_glossary_error,
    report_glossary_error,
    set_glossary_error_handler,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeApp,
    FakeWindow,
    call_quietly,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class HistoryChangeSummaryTests(unittest.TestCase):
    """O resumo por linha do historico (ROADMAP 22.12), sem Tk.

    A lista dizia QUANDO e QUE TIPO, e nunca o TAMANHO da mudanca — e entre 100
    linhas com o mesmo rotulo, o tamanho e o que distingue a versao procurada.
    """

    def test_it_counts_the_changed_stretches(self):
        self.assertEqual(
            history_window.history_change_summary("a torre e o bispo", "a TORRE e o BISPO"),
            "2 trecho(s)",
        )

    def test_an_action_that_did_not_touch_the_text_says_so(self):
        """"Verificacao" e "Regras automaticas" produzem entradas identicas."""
        self.assertEqual(
            history_window.history_change_summary("a torre", "a torre"),
            "sem mudanca no texto",
        )

    def test_the_first_fill_counts_as_a_change(self):
        self.assertEqual(
            history_window.history_change_summary(None, "a torre"), "1 trecho(s)"
        )


class HistoryIsAListOfChangesTests(unittest.TestCase):
    """Garantia F26: o historico lista ALTERACOES, e a versao inicial e
    recuperavel (ROADMAP 23.1).

    Medido no banco de dev de 6.500 linhas: **5.871 (90%) nao tinham nenhuma
    linha de historico** e abriam a janela em "Nenhuma alteracao registrada"; das
    889 entradas gravadas, **607 nao mudam o texto** (600 sao `verify`), e em 355
    dos 629 comentarios com historico ERA SO ISSO — os dois painels mostravam o
    mesmo texto, que e o "so aparece a traducao atual" que o usuario relatou.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = initialize_database(str(Path(self.tmp.name) / "c.db"))
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def linha(self, original="the rook", traducao="a torre"):
        save_translation(self.cur, original, traducao, "pt", "en")
        self.conn.commit()
        return self.cur.execute(
            "SELECT id FROM comments WHERE original_comment = ?", (original,)
        ).fetchone()[0]

    # ------------------------------------------- a versao da maquina

    def test_without_any_history_the_machine_version_is_the_current_text(self):
        """O `INSERT` do pipeline e o unico caminho que nao registra historico."""
        cid = self.linha()

        self.assertEqual(machine_translation_for(self.cur, cid), "a torre")

    def test_after_an_edit_the_machine_version_is_what_came_before_it(self):
        cid = self.linha()
        update_translation_by_id(self.cur, cid, "a TORRE de dama")
        self.conn.commit()

        self.assertEqual(machine_translation_for(self.cur, cid), "a torre")
        self.assertEqual(
            self.cur.execute(
                "SELECT translated_comment FROM comments WHERE id = ?", (cid,)
            ).fetchone()[0],
            "a TORRE de dama",
        )

    def test_it_walks_back_past_several_edits(self):
        """E a entrada MAIS ANTIGA que guarda o texto da maquina, e nao a ultima."""
        cid = self.linha()
        for texto in ("primeira edicao", "segunda edicao", "terceira edicao"):
            update_translation_by_id(self.cur, cid, texto)
        self.conn.commit()

        self.assertEqual(machine_translation_for(self.cur, cid), "a torre")

    def test_a_verification_in_the_middle_does_not_move_the_starting_point(self):
        """`verify` grava entrada sem mudar texto: ela nao pode virar a origem."""
        cid = self.linha()
        set_translation_verified_by_id(self.cur, cid)
        update_translation_by_id(self.cur, cid, "editada depois de verificar")
        self.conn.commit()

        self.assertEqual(machine_translation_for(self.cur, cid), "a torre")

    def test_a_line_that_does_not_exist_answers_None(self):
        self.assertIsNone(machine_translation_for(self.cur, 99999))

    # ------------------------------------------------- a lista filtrada

    def test_entries_that_do_not_change_the_text_stay_out_of_the_list(self):
        cid = self.linha()
        set_translation_verified_by_id(self.cur, cid)
        self.conn.commit()

        self.assertEqual(fetch_comment_history(self.cur, cid), [])
        self.assertEqual(
            len(fetch_comment_history(self.cur, cid, only_text_changes=False)), 1
        )

    def test_the_edits_stay(self):
        """A ancora: o filtro nao pode levar embora o que se quer restaurar."""
        cid = self.linha()
        set_translation_verified_by_id(self.cur, cid)
        update_translation_by_id(self.cur, cid, "editada")
        self.conn.commit()

        alteracoes = fetch_comment_history(self.cur, cid)
        self.assertEqual(len(alteracoes), 1)
        self.assertEqual(alteracoes[0][3], "editada")

    def test_the_limit_is_spent_on_changes_and_not_on_verifications(self):
        """O filtro e em SQL por causa disto.

        Filtrando depois de buscar, 3 verificacoes gastariam um limite de 3 e a
        alteracao — a unica coisa que interessa — ficaria de fora.
        """
        cid = self.linha()
        for _ in range(3):
            set_translation_verified_by_id(self.cur, cid)
            self.cur.execute(
                "UPDATE comments SET verified = 0 WHERE id = ?", (cid,)
            )
        update_translation_by_id(self.cur, cid, "a unica alteracao")
        self.conn.commit()

        pagina = fetch_comment_history(self.cur, cid, limit=3)

        self.assertEqual([linha[3] for linha in pagina], ["a unica alteracao"])

    def test_the_counts_say_what_was_left_out(self):
        cid = self.linha()
        set_translation_verified_by_id(self.cur, cid)
        update_translation_by_id(self.cur, cid, "editada")
        self.conn.commit()

        com, sem = count_comment_history(self.cur, cid)

        self.assertEqual((com, sem), (1, 1))

    def test_an_untouched_line_has_nothing_to_leave_out(self):
        self.assertEqual(count_comment_history(self.cur, self.linha()), (0, 0))


class HiddenHistoryLabelTests(unittest.TestCase):
    """A linha que diz o que a lista NAO esta mostrando (ROADMAP 23.1)."""

    def test_showing_everything_says_nothing(self):
        self.assertEqual(history_window.describe_hidden_history(3, 0), "")

    def test_it_counts_the_verifications_left_out(self):
        self.assertIn(
            "7 verificações", history_window.describe_hidden_history(2, 7)
        )

    def test_one_verification_is_singular(self):
        texto = history_window.describe_hidden_history(2, 1)
        self.assertIn("1 verificação ", texto)
        self.assertNotIn("verificações", texto)

    def test_the_cut_at_the_limit_is_still_announced(self):
        texto = history_window.describe_hidden_history(
            history_window.HISTORY_LIMIT, 0
        )
        self.assertIn(str(history_window.HISTORY_LIMIT), texto)

    def test_both_omissions_fit_in_the_same_line(self):
        texto = history_window.describe_hidden_history(
            history_window.HISTORY_LIMIT, 4
        )
        self.assertIn(str(history_window.HISTORY_LIMIT), texto)
        self.assertIn("4 verificações", texto)


class LogAutoscrollTests(unittest.TestCase):
    """Garantia F23 (log): o log so rola quando o fim ja estava visivel (22.12).

    O `see(END)` era incondicional: reler um `[AVISO]` durante uma execucao era
    ser puxado de volta a cada mensagem nova.
    """

    class FakeLog:
        def __init__(self, fim):
            self.fim = fim

        def yview(self):
            return (0.0, self.fim)

    def test_the_end_visible_means_follow(self):
        self.assertTrue(app_actions.log_is_at_the_end(self.FakeLog(1.0)))

    def test_scrolled_up_means_stay(self):
        self.assertFalse(app_actions.log_is_at_the_end(self.FakeLog(0.42)))

    def test_a_partially_visible_last_line_still_counts(self):
        """A fracao e calculada em pixels: 0,999... e "esta no fim"."""
        self.assertTrue(app_actions.log_is_at_the_end(self.FakeLog(0.9995)))

    def test_a_log_that_cannot_answer_keeps_the_old_behaviour(self):
        class SemYview:
            def yview(self):
                raise RuntimeError("ainda nao desenhado")

        self.assertTrue(app_actions.log_is_at_the_end(SemYview()))


class EditorTextTests(unittest.TestCase):
    def test_find_text_ranges_respects_case_option(self):
        self.assertEqual(find_text_ranges("Mate mate MATE", "mate"), [(0, 4), (5, 9), (10, 14)])
        self.assertEqual(
            find_text_ranges("Mate mate MATE", "mate", case_sensitive=True),
            [(5, 9)],
        )
        self.assertEqual(find_text_ranges("abc", ""), [])

    def test_replace_text_range_clamps_offsets(self):
        self.assertEqual(replace_text_range("abcdef", 2, 4, "XX"), "abXXef")
        self.assertEqual(replace_text_range("abcdef", -5, 2, "X"), "Xcdef")
        self.assertEqual(replace_text_range("abcdef", 4, 99, "X"), "abcdX")

    def test_replace_all_text_returns_count(self):
        self.assertEqual(
            replace_all_text("Knight knight KNIGHT", "knight", "N"),
            ("N N N", 3),
        )
        self.assertEqual(
            replace_all_text("Knight knight", "Knight", "N", case_sensitive=True),
            ("N knight", 1),
        )
        self.assertEqual(replace_all_text("abc", "x", "y"), ("abc", 0))


class CallbackErrorReportingTests(unittest.TestCase):
    """Roadmap 6.2 / garantia C3: erro de lock nao pode virar traceback invisivel.

    Sob `pythonw` nao ha console. Ate aqui, um `sqlite3.OperationalError` no
    editor sumia sem deixar rastro e a gravacao apenas nao acontecia — sem
    mensagem, sem log, sem nada que o usuario pudesse notar.
    """

    def test_a_lock_says_what_to_do_about_it(self):
        titulo, mensagem = window_utils.describe_callback_error(
            sqlite3.OperationalError("database is locked")
        )
        self.assertEqual(titulo, window_utils.DATABASE_BUSY_TITLE)
        self.assertIn("traducao em andamento", mensagem)
        self.assertIn("Nada foi gravado", mensagem)
        self.assertIn("tente de novo", mensagem.lower())

    def test_another_database_error_is_not_disguised_as_a_lock(self):
        titulo, mensagem = window_utils.describe_callback_error(
            sqlite3.OperationalError("no such column: foo")
        )
        self.assertEqual(titulo, window_utils.DATABASE_ERROR_TITLE)
        self.assertIn("no such column", mensagem)

    def test_any_other_error_still_reaches_the_user(self):
        titulo, mensagem = window_utils.describe_callback_error(ValueError("xyz"))
        self.assertEqual(titulo, window_utils.UNEXPECTED_ERROR_TITLE)
        self.assertIn("ValueError", mensagem)
        self.assertIn("xyz", mensagem)

    def _reporter(self, relogio):
        raiz = types.SimpleNamespace()
        dialogos = []
        logs = []
        handler = window_utils.install_callback_error_reporter(
            raiz,
            log_message=logs.append,
            show_error=lambda titulo, msg: dialogos.append((titulo, msg)),
            now=lambda: relogio[0],
        )
        return raiz, handler, dialogos, logs

    def dispara(self, handler, exc):
        try:
            raise exc
        except type(exc):
            handler(type(exc), exc, sys.exc_info()[2])

    def test_the_handler_is_installed_on_the_root(self):
        raiz, handler, _dialogos, _logs = self._reporter([0.0])
        self.assertIs(raiz.report_callback_exception, handler)

    def test_a_burst_of_the_same_error_opens_one_dialog(self):
        """Um callback periodico que falha sempre nao pode encher a tela."""
        relogio = [0.0]
        _raiz, handler, dialogos, logs = self._reporter(relogio)

        for _ in range(5):
            relogio[0] += 0.1
            self.dispara(handler, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(dialogos), 1)
        self.assertEqual(len(logs), 10, "toda ocorrencia vai para o log")

    def test_trying_again_later_warns_again(self):
        """A supressao contem rajada; nao pode calar quem tentou de novo."""
        relogio = [0.0]
        _raiz, handler, dialogos, _logs = self._reporter(relogio)

        self.dispara(handler, sqlite3.OperationalError("database is locked"))
        relogio[0] += window_utils.ERROR_DIALOG_REPEAT_SECONDS + 0.1
        self.dispara(handler, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(dialogos), 2)

    def test_a_different_error_is_never_suppressed(self):
        relogio = [0.0]
        _raiz, handler, dialogos, _logs = self._reporter(relogio)

        self.dispara(handler, sqlite3.OperationalError("database is locked"))
        self.dispara(handler, ValueError("outra coisa"))

        self.assertEqual(len(dialogos), 2)

    def test_the_traceback_goes_to_the_log(self):
        _raiz, handler, _dialogos, logs = self._reporter([0.0])
        self.dispara(handler, ValueError("xyz"))

        texto = "\n".join(logs)
        self.assertIn("Traceback", texto)
        self.assertIn("ValueError", texto)

    def test_a_failing_dialog_does_not_replace_the_original_error(self):
        """O relator de erros nao pode ser a proxima fonte de erro."""
        raiz = types.SimpleNamespace()
        logs = []

        def explode(*_args):
            raise RuntimeError("sem display")

        handler = window_utils.install_callback_error_reporter(
            raiz, log_message=logs.append, show_error=explode
        )
        self.dispara(handler, ValueError("xyz"))
        self.assertTrue(logs)


class SharedEditorWidgetsTests(unittest.TestCase):
    """Roadmap 3.2: as pecas que os dois editores usavam em copia.

    `save_window_section` e a que importa: ela implementa a garantia R4 —
    gravar SO a secao desta janela, relendo o disco antes. Enquanto existiam
    duas copias, corrigir uma e esquecer a outra reproduzia exatamente o defeito
    que R4 existe para impedir, e sem quebrar nada na hora: o usuario e que
    perdia um rascunho depois.

    Nao precisa de Tk: `window=None` e `sashes=()` cobrem a parte que mexe no
    disco, que e a arriscada.
    """

    def test_it_writes_only_its_own_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings(
                {"editor_drafts": {"x": "rascunho"}, "editor": {"font_size": 9}}, path
            )
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            local = {"glossary_editor": {"sort": "antiga"}}
            editor_widgets.save_window_section(
                local, "glossary_editor", {"sort": "Original A-Z"}
            )

            disco = settings.load_settings(path)
            self.assertEqual(disco["glossary_editor"]["sort"], "Original A-Z")
            self.assertEqual(disco["editor_drafts"], {"x": "rascunho"}, "apagou rascunhos")
            self.assertEqual(disco["editor"], {"font_size": 9}, "apagou a outra janela")

    def test_it_rereads_the_disk_instead_of_writing_its_snapshot(self):
        """O caso concreto que R4 descreve: a outra janela gravou nesse meio-tempo."""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            # Snapshot que esta janela carregou na abertura: ainda sem rascunhos.
            local = settings.load_settings(path)
            # A outra janela grava um rascunho DEPOIS disso.
            settings.save_settings({"editor_drafts": {"y": "novo"}}, path)

            editor_widgets.save_window_section(local, "editor", {"font_size": 14})

            disco = settings.load_settings(path)
            self.assertEqual(
                disco["editor_drafts"],
                {"y": "novo"},
                "gravou o snapshot antigo por cima do que a outra janela escreveu",
            )
            self.assertEqual(disco["editor"]["font_size"], 14)

    def test_a_corrupted_section_is_replaced_and_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({"editor": "isto nao e um dicionario"}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            editor_widgets.save_window_section({}, "editor", {"font_size": 12})
            self.assertEqual(settings.load_settings(path)["editor"], {"font_size": 12})

    def test_the_local_snapshot_stays_coherent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            local = {}
            editor_widgets.save_window_section(local, "editor", {"font_size": 20})
            self.assertEqual(local["editor"]["font_size"], 20)

    def test_the_sash_limits_keep_a_panel_reachable(self):
        """A decisao de onde colocar o divisor, sem abrir janela.

        Uma posicao gravada numa tela grande deixaria o painel fora da janela
        numa tela menor, e nao haveria como traze-lo de volta a nao ser apagando
        as configuracoes na mao.
        """
        self.assertEqual(editor_common.clamped_sash_position(400, 360, 520), 400)
        self.assertEqual(editor_common.clamped_sash_position(9999, 360, 520), 520)
        self.assertEqual(editor_common.clamped_sash_position(10, 360, 520), 360)
        self.assertEqual(editor_common.clamped_sash_position(600, 520), 600, "sem teto")

    def test_a_position_that_was_never_saved_is_refused(self):
        for valor in (None, 0, -5, "480", 12.5, True):
            with self.subTest(valor=valor):
                self.assertIsNone(editor_common.clamped_sash_position(valor, 360, 520))

    def test_a_disk_failure_does_not_propagate(self):
        """A chamada acontece ao fechar a janela: falhar ali nao pode derrubar nada."""
        self.addCleanup(setattr, settings, "update_settings", settings.update_settings)
        self.addCleanup(setattr, editor_widgets, "update_settings",
                        editor_widgets.update_settings)

        def explode(_mutator, _path=None):
            raise OSError("disco cheio")

        editor_widgets.update_settings = explode
        local = {}
        editor_widgets.save_window_section(local, "editor", {"font_size": 11})
        self.assertEqual(local["editor"]["font_size"], 11, "o snapshot local continua")


class EditorCommonTests(unittest.TestCase):
    """Logica das janelas de edicao, agora testavel sem abrir uma janela."""

    def test_page_count_and_clamp(self):
        self.assertEqual(page_count(0, 100), 0)
        self.assertEqual(page_count(1, 100), 1)
        self.assertEqual(page_count(100, 100), 1)
        self.assertEqual(page_count(101, 100), 2)
        self.assertEqual(page_count(250, 100), 3)
        # Defensivo: nao pode estourar com tamanho de pagina invalido.
        self.assertEqual(page_count(10, 0), 0)
        self.assertEqual(page_count(-5, 100), 0)

        # Depois de excluir/filtrar, a pagina atual pode ficar alem do fim.
        self.assertEqual(clamp_page(5, 250, 100), 2)
        self.assertEqual(clamp_page(0, 250, 100), 0)
        self.assertEqual(clamp_page(-3, 250, 100), 0)
        self.assertEqual(clamp_page(7, 0, 100), 0)

    def test_offsets_round_trip(self):
        self.assertEqual(page_offset(0, 100), 0)
        self.assertEqual(page_offset(3, 100), 300)
        self.assertEqual(page_offset(-1, 100), 0)

        self.assertEqual(page_of_offset(0, 100), 0)
        self.assertEqual(page_of_offset(99, 100), 0)
        self.assertEqual(page_of_offset(100, 100), 1)
        self.assertEqual(page_of_offset(250, 100), 2)

        for offset in (0, 1, 99, 100, 101, 999):
            pagina = page_of_offset(offset, 100)
            self.assertLessEqual(page_offset(pagina, 100), offset)
            self.assertLess(offset - page_offset(pagina, 100), 100)

    def test_local_index_is_clamped_to_the_page_actually_returned(self):
        # Caso normal.
        self.assertEqual(local_index_for_offset(250, 100, 100), 50)
        # A pagina veio menor do que o esperado (o banco mudou no meio):
        # o indice tem de ser limitado, nao estourar IndexError depois.
        self.assertEqual(local_index_for_offset(250, 100, 10), 9)
        # Pagina vazia.
        self.assertIsNone(local_index_for_offset(250, 100, 0))

    def test_clamp_geometry_fits_saved_window_into_current_screen(self):
        # Cabe: preservado.
        self.assertEqual(
            clamp_geometry("1200x700+100+50", 1920, 1080, 1120, 680),
            "1200x700+100+50",
        )
        # Posicao negativa salva num monitor que nao existe mais.
        self.assertEqual(
            clamp_geometry("1360x705+-71+28", 1920, 1080, 1120, 680),
            "1360x705+0+28",
        )
        # Maior que a tela atual: encolhe e reposiciona.
        self.assertEqual(
            clamp_geometry("3000x2000+500+400", 1920, 1080, 1120, 680),
            "1920x1080+0+0",
        )
        # Menor que o minimo da janela: cresce.
        self.assertEqual(
            clamp_geometry("300x200+10+10", 1920, 1080, 1120, 680),
            "1120x680+10+10",
        )
        # Formato desconhecido passa intacto.
        self.assertEqual(clamp_geometry("zoomed", 1920, 1080, 1120, 680), "zoomed")
        self.assertIsNone(clamp_geometry(None, 1920, 1080, 1120, 680))

    def test_preview_collapses_whitespace_and_truncates(self):
        self.assertEqual(preview("  varios   espacos \n aqui "), "varios espacos aqui")
        self.assertEqual(preview("", 10), "")
        self.assertIsNotNone(preview(None))
        self.assertEqual(preview("abcdefghij", 10), "abcdefghij")
        self.assertEqual(preview("abcdefghijk", 10), "abcdefg...")
        self.assertLessEqual(len(preview("x" * 500, 54)), 54)

    def test_both_editors_share_the_same_geometry_logic(self):
        # As duas janelas so devem divergir no tamanho minimo. O do editor de
        # traducoes sai das constantes dos paineis desde 22.10 — escrever 1176
        # aqui a mao recriaria a segunda fonte que aquele item eliminou.
        janela = FakeWindow(1920, 1080)
        self.assertEqual(
            safe_geometry(janela, "300x200+10+10"),
            clamp_geometry(
                "300x200+10+10",
                1920,
                1080,
                edit_window.MIN_WIDTH,
                edit_window.MIN_HEIGHT,
            ),
        )
        self.assertEqual(
            glossary_safe_geometry(janela, "300x200+10+10"),
            clamp_geometry("300x200+10+10", 1920, 1080, 1040, 640),
        )


class GlossaryErrorChannelTests(unittest.TestCase):
    """Garantia S5: falha de carga do glossario chega ate a interface."""

    def setUp(self):
        self.reported = []
        self.previous = set_glossary_error_handler(self.reported.append)
        self.addCleanup(set_glossary_error_handler, self.previous)
        self.addCleanup(clear_glossary_error)
        clear_glossary_error()

    def test_malformed_file_reports_instead_of_failing_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")

            entries = call_quietly(load_substitutions, str(glossary))

            self.assertEqual(entries, [])
            self.assertEqual(len(self.reported), 1)
            self.assertIn("Substituicoes.txt", self.reported[0])
            self.assertIn("NÃO serão aplicadas", self.reported[0])
            self.assertEqual(last_glossary_error(), self.reported[0])

    def test_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "Substituicoes.txt")

            self.assertEqual(call_quietly(load_substitutions, missing), [])
            self.assertEqual(len(self.reported), 1)
            self.assertIn("não encontrado", self.reported[0].lower())

    def test_successful_load_clears_the_previous_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")
            call_quietly(load_substitutions, str(glossary))
            self.assertIsNotNone(last_glossary_error())

            glossary.write_text("substituicoes = [('a', 'b')]\n", encoding="utf-8")
            self.assertEqual(
                call_quietly(load_substitutions, str(glossary)), [("a", "b")]
            )
            self.assertIsNone(last_glossary_error())

    def test_a_broken_handler_never_escapes(self):
        def explode(_message):
            raise RuntimeError("handler quebrado")

        set_glossary_error_handler(explode)
        # Nao pode levantar: reportar um erro nao pode virar um erro pior.
        call_quietly(report_glossary_error, "falha de teste")
        self.assertEqual(last_glossary_error(), "falha de teste")

    def test_without_a_handler_the_message_is_still_recorded(self):
        set_glossary_error_handler(None)
        call_quietly(report_glossary_error, "sem interface")
        self.assertEqual(last_glossary_error(), "sem interface")


class GlossaryFailureUiTests(unittest.TestCase):
    """O handler que a janela principal registra (`app_actions`)."""

    def setUp(self):
        self.app = FakeApp(":memory:")
        shown = []
        self.shown = shown

        class FakeMessagebox:
            @staticmethod
            def showerror(title, message, **kwargs):
                shown.append((title, message))

        previous = app_actions.messagebox
        app_actions.messagebox = FakeMessagebox
        self.addCleanup(setattr, app_actions, "messagebox", previous)

    def test_failure_reaches_both_the_log_and_a_dialog(self):
        app_actions.report_glossary_failure(self.app, "arquivo quebrado")

        self.assertTrue(any("arquivo quebrado" in line for line in self.app.logs))
        self.assertEqual(len(self.shown), 1)
        self.assertIn("arquivo quebrado", self.shown[0][1])

    def test_the_same_failure_opens_only_one_dialog(self):
        """A carga se repete a cada recarga; um modal por vez travaria o uso."""
        for _ in range(5):
            app_actions.report_glossary_failure(self.app, "arquivo quebrado")

        self.assertEqual(len(self.shown), 1)
        self.assertEqual(
            len([line for line in self.app.logs if "arquivo quebrado" in line]), 5
        )

    def test_a_different_failure_opens_a_new_dialog(self):
        app_actions.report_glossary_failure(self.app, "primeira falha")
        app_actions.report_glossary_failure(self.app, "segunda falha")

        self.assertEqual(len(self.shown), 2)

    def test_startup_load_degrades_instead_of_killing_the_window(self):
        """Sem isso, um `Substituicoes.txt` quebrado impedia o programa de abrir."""

        def explode(**_kwargs):
            raise ValueError("arquivo invalido")

        previous = app_actions.load_interactive_substitutions
        app_actions.load_interactive_substitutions = explode
        self.addCleanup(
            setattr, app_actions, "load_interactive_substitutions", previous
        )
        previous_handler = set_glossary_error_handler(
            lambda message: app_actions.report_glossary_failure(self.app, message)
        )
        self.addCleanup(set_glossary_error_handler, previous_handler)

        entries = call_quietly(app_actions.load_interactive_glossary, self.app)

        self.assertEqual(entries, [])
        self.assertEqual(len(self.shown), 1)
        self.assertIn("arquivo invalido", self.shown[0][1])


class RowIndexForIdTests(unittest.TestCase):
    """Roadmap 3.3: reencontrar a linha pelo id apos a lista ser recarregada."""

    ROWS = [
        (10, "orig a", "trad a", 0),
        (11, "orig b", "trad b", 0),
        (12, "orig c", "trad c", 1),
    ]

    def test_finds_the_row_by_id(self):
        self.assertEqual(row_index_for_id(self.ROWS, 10), 0)
        self.assertEqual(row_index_for_id(self.ROWS, 11), 1)
        self.assertEqual(row_index_for_id(self.ROWS, 12), 2)

    def test_the_id_wins_over_the_fallback(self):
        # E o ponto do item 3.3: a posicao antiga esta errada, o id nao.
        self.assertEqual(row_index_for_id(self.ROWS, 12, fallback=0), 2)

    def test_reload_that_drops_a_row_keeps_the_target(self):
        """O cenario exato do bug.

        A lista tinha [A, B, C] e o clique foi em B (posicao 1). Gravar removeu
        A do filtro "Avisos QA", entao a lista virou [B, C] e a posicao 1 agora
        e C. Pelo id, B continua sendo B.
        """
        antes = self.ROWS
        clicada = 1
        alvo = antes[clicada][0]

        depois = [row for row in antes if row[0] != 10]

        self.assertEqual(depois[clicada][0], 12, "a posicao antiga aponta para C")
        self.assertEqual(row_index_for_id(depois, alvo, fallback=clicada), 0)

    def test_missing_id_falls_back_to_the_neighbour(self):
        self.assertEqual(row_index_for_id(self.ROWS, 999, fallback=1), 1)

    def test_fallback_is_clamped_to_the_current_list(self):
        # A lista encolheu entre o clique e a leitura.
        self.assertEqual(row_index_for_id(self.ROWS[:2], 999, fallback=5), 1)
        self.assertEqual(row_index_for_id(self.ROWS, 999, fallback=-3), 0)

    def test_empty_list_has_nothing_to_select(self):
        self.assertIsNone(row_index_for_id([], 10, fallback=0))
        self.assertIsNone(row_index_for_id([], None))

    def test_none_id_uses_the_fallback(self):
        self.assertEqual(row_index_for_id(self.ROWS, None, fallback=2), 2)
        self.assertEqual(row_index_for_id(self.ROWS, None, fallback=99), 2)

    def test_first_match_wins(self):
        duplicadas = [(7, "a", "b", 0), (7, "c", "d", 0)]
        self.assertEqual(row_index_for_id(duplicadas, 7), 0)


class GlossaryErrorWithoutConsoleTests(unittest.TestCase):
    """Garantia S5 sob `pythonw` (ROADMAP 17.9).

    `report_glossary_error` fazia `print(...)` ANTES de chamar o handler da
    interface — e sob `pythonw` / PyInstaller windowed `sys.stdout` e `None`,
    entao o `print` levantava e o handler nunca rodava. A funcao que existe para
    tornar a falha visivel era a unica que quebrava no empacotado, que e
    exatamente onde nao ha console para ler o erro.
    """

    def setUp(self):
        self.reported = []
        self.previous = set_glossary_error_handler(self.reported.append)
        self.addCleanup(set_glossary_error_handler, self.previous)
        self.addCleanup(clear_glossary_error)
        clear_glossary_error()

    def sem_console(self):
        """Simula o `pythonw`: `sys.stdout` e `None`, e nao um arquivo fechado."""
        self.addCleanup(setattr, sys, "stdout", sys.stdout)
        sys.stdout = None

    def test_the_message_reaches_the_interface_without_a_console(self):
        self.sem_console()

        report_glossary_error("glossario quebrado")

        self.assertEqual(self.reported, ["glossario quebrado"])
        self.assertEqual(last_glossary_error(), "glossario quebrado")

    def test_a_load_failure_still_degrades_and_reports(self):
        """O caminho de verdade: carregar um arquivo quebrado devolve lista vazia
        E avisa, com ou sem console."""
        self.sem_console()
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")

            self.assertEqual(load_substitutions(str(glossary)), [])

        self.assertEqual(len(self.reported), 1)
        self.assertIn("Substituicoes.txt", self.reported[0])

    def test_a_closed_stdout_is_survived_too(self):
        """Um `stdout` fechado (pipe rompido) levanta `ValueError`, e tambem nao
        pode ser o motivo de o usuario nao ser avisado."""
        fechado = io.StringIO()
        fechado.close()
        self.addCleanup(setattr, sys, "stdout", sys.stdout)
        sys.stdout = fechado

        report_glossary_error("com stdout fechado")

        self.assertEqual(self.reported, ["com stdout fechado"])

    def test_adding_an_entry_that_fails_does_not_raise_without_a_console(self):
        """O mesmo `print` cru estava no `except` de `add_to_glossary`: sob
        `pythonw` ele transformava "nao consegui gravar a regra" num
        `AttributeError` no meio do popup do editor."""
        self.sem_console()
        with tempfile.TemporaryDirectory() as tmp:
            # Um diretorio no lugar do arquivo: a gravacao falha, e a funcao
            # precisa devolver False em vez de levantar.
            caminho = Path(tmp) / "Substituicoes.txt"
            caminho.mkdir()

            self.assertFalse(add_to_glossary("rook", "torre", path=str(caminho)))

    def test_with_a_console_the_message_is_printed(self):
        """Contraprova: a guarda nao pode ter calado o log de quem tem console."""
        saida = io.StringIO()
        with redirect_stdout(saida):
            report_glossary_error("com console")

        self.assertIn("com console", saida.getvalue())


class RestoreOrMaximizeTests(unittest.TestCase):
    """A geometria salva era ignorada em silencio (ROADMAP 17.10).

    Os dois editores restauravam a geometria na construcao, e o `maximize=True`
    agendado a +50 ms a sobrescrevia depois: todo o caminho de `safe_geometry`,
    com `clamp_geometry` e testes proprios, estava morto na pratica.
    """

    class JanelaFalsa:
        def __init__(self, falhar=False):
            self.geometrias = []
            self.agendados = []
            self.falhar = falhar

        def geometry(self, valor):
            if self.falhar:
                raise RuntimeError("geometria invalida")
            self.geometrias.append(valor)

        def after(self, _delay, callback=None):
            self.agendados.append(callback)

    def test_a_saved_geometry_is_applied_and_nothing_maximizes(self):
        win = self.JanelaFalsa()

        self.assertTrue(window_utils.restore_or_maximize(win, None, "900x600+10+20"))

        self.assertEqual(win.geometrias, ["900x600+10+20"])

    def test_without_a_saved_geometry_it_maximizes(self):
        """Primeira abertura: as duas janelas sao listas largas, e 1280x760 num
        monitor grande desperdicaria a tela."""
        win = self.JanelaFalsa()

        for vazio in (None, "", 0):
            with self.subTest(vazio=vazio):
                self.assertFalse(window_utils.restore_or_maximize(win, None, vazio))

        self.assertEqual(win.geometrias, [], "nao ha geometria para aplicar")

    def test_a_geometry_the_tk_refuses_falls_back_to_maximizing(self):
        win = self.JanelaFalsa(falhar=True)

        self.assertFalse(
            window_utils.restore_or_maximize(win, None, "isto-nao-e-geometria")
        )

    def test_the_editors_do_not_ask_for_both(self):
        """A prova de que a escolha ficou num lugar so: nenhum dos dois editores
        chama `bring_window_to_front` com `maximize=True` na construcao."""
        for modulo in ("edit_window.py", "glossary_editor.py"):
            with self.subTest(modulo=modulo):
                fonte = (
                    Path(__file__).resolve().parent.parent / "tradutor_pgn" / modulo
                ).read_text(encoding="utf-8")
                self.assertNotIn(
                    "bring_window_to_front(self.win", fonte,
                    "a janela principal do editor deve passar por restore_or_maximize",
                )


class DiffSpansTests(unittest.TestCase):
    """As faixas pintadas na previa de "Aplicar todas" (item 5)."""

    def test_the_changed_word_is_marked_on_both_sides(self):
        antes = "a coluna aberta"
        depois = "a fileira aberta"

        faixas_antes, faixas_depois = diff_spans(antes, depois)

        self.assertEqual([antes[i:f] for i, f in faixas_antes], ["coluna"])
        self.assertEqual([depois[i:f] for i, f in faixas_depois], ["fileira"])

    def test_identical_texts_have_no_spans(self):
        self.assertEqual(diff_spans("igual", "igual"), ([], []))

    def test_the_diff_is_by_word_and_not_by_character(self):
        """Por caractere, `torre`/`Torre` viraria um `T` trocado no meio de uma
        palavra inteira pintada de igual — e o que o revisor precisa ver e a palavra
        que mudou."""
        antes, depois = "a torre", "a Torre"

        _antes_spans, faixas_depois = diff_spans(antes, depois)

        self.assertEqual([depois[i:f] for i, f in faixas_depois], ["Torre"])

    def test_an_insertion_marks_only_the_new_side(self):
        faixas_antes, faixas_depois = diff_spans("a torre", "a torre branca")

        self.assertEqual(faixas_antes, [])
        self.assertEqual(len(faixas_depois), 1)

    def test_many_replacements_are_all_marked(self):
        """O caso do item: conferir 80 substituicoes a olho nu e o mesmo que nao
        conferir."""
        antes = " ".join(f"palavra{i}" for i in range(10))
        depois = " ".join(
            (f"trocada{i}" if i % 2 == 0 else f"palavra{i}") for i in range(10)
        )

        _faixas_antes, faixas_depois = diff_spans(antes, depois)

        self.assertEqual(len(faixas_depois), 5)


if __name__ == "__main__":
    unittest.main()
