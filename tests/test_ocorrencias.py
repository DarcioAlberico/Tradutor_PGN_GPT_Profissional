"""Onde cada traducao foi lida: ocorrencias, ordem de leitura e a posicao (FEN).

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import io
import os
import re
import sqlite3
import tempfile
import unittest
import unittest.mock
from collections import Counter
from pathlib import Path

from tradutor_pgn import (
    pgn_positions,
    settings,
)
from tradutor_pgn.database import (
    OCCURRENCES_TABLE,
    ORDER_BY_OCCURRENCE,
    SEARCH_MODE_SUBSTRING,
    SCHEMA_VERSION,
    clear_all_translations,
    count_review_rows,
    fetch_comment_occurrences,
    fetch_occurrence_fen,
    fetch_review_rows,
    fetch_review_rows_page,
    get_file_progress,
    get_review_row_offset,
    get_review_status_counts,
    get_database_stats,
    initialize_database,
    list_occurrence_files,
    reads_in_occurrence_order,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
    set_translation_verified_by_id,
)
from tradutor_pgn.pgn_utils import (
    comment_reading_context,
    extract_comments_from_content,
    extract_comments_from_file,
    flatten_comment,
)
from tradutor_pgn import (
    translation_worker,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeApp,
    PGN_COM_VARIANTES,
    WorkerFallbackHarness,
    _chess_installed,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


@unittest.skipUnless(_chess_installed(), "python-chess nao instalado")
class PgnPositionsWalkTests(unittest.TestCase):
    """O visitor sem `board.copy()` (ROADMAP 28.8): a FEN de cada comentario,
    na ordem do arquivo, conferida contra o metodo com copia."""

    def referencia(self, content):
        import chess.pgn

        fonte = io.StringIO(pgn_positions.normalize_line_endings(content))
        pares = []
        while True:
            game = chess.pgn.read_game(fonte)
            if game is None:
                break

            def rec(node):
                for child in node.variations:
                    if child.starting_comment:
                        pares.append((flatten_comment(child.starting_comment), node.board().fen()))
                    if child.comment:
                        pares.append((flatten_comment(child.comment), child.board().fen()))
                    rec(child)

            if game.comment:
                pares.append((flatten_comment(game.comment), game.board().fen()))
            rec(game)
        return pares

    def test_every_comment_gets_the_fen_of_the_copying_method(self):
        parsed = pgn_positions.parsed_comments_by_game(PGN_COM_VARIANTES)
        self.assertEqual(len(parsed), 1)
        meus = parsed[0]
        self.assertEqual(Counter(meus), Counter(self.referencia(PGN_COM_VARIANTES)))
        # E na ordem do ARQUIVO: principal, variantes inteiras, continuacao.
        self.assertEqual(
            [texto for texto, _fen in meus],
            [
                "Antes do primeiro lance.", "Depois de e4.", "Em vez disso",
                "d4 comentado", "ou", "cavalo", "gambito", "Siciliana",
                "Dragao a caminho",
            ],
        )
        # A variante de varios lances e desfeita INTEIRA ao sair: o comentario
        # da linha principal depois dela esta na posicao da linha principal.
        fen_siciliana = dict(meus)["Siciliana"]
        self.assertTrue(fen_siciliana.startswith("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w"))
        self.assertTrue(dict(meus)["Em vez disso"].endswith(" w KQkq - 0 1"), "antes de 1.d4 e a inicial")

    def test_a_file_with_only_cr_line_endings_is_parsed(self):
        so_cr = PGN_COM_VARIANTES.replace("\n", "\r")
        parsed = pgn_positions.parsed_comments_by_game(so_cr)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(parsed[0]), 9)

    def test_two_games_give_two_lists(self):
        dois = PGN_COM_VARIANTES + "\n" + PGN_COM_VARIANTES.replace("Siciliana", "Outra")
        parsed = pgn_positions.parsed_comments_by_game(dois)
        self.assertEqual([len(p) for p in parsed], [9, 9])

    def test_cancel_returns_none(self):
        self.assertIsNone(
            pgn_positions.parsed_comments_by_game(PGN_COM_VARIANTES, should_cancel=lambda: True)
        )

    def test_compute_comment_fens_lines_up_with_the_extraction(self):
        info = extract_comments_from_content(PGN_COM_VARIANTES)
        fens = pgn_positions.compute_comment_fens(PGN_COM_VARIANTES, info["occurrences"])
        self.assertEqual(len(fens), len(info["occurrences"]))
        self.assertTrue(all(fens), "todo comentario deste PGN tem posicao")


class PgnPositionsAlignTests(unittest.TestCase):
    """O casamento por texto, sem `python-chess`: puro sobre listas."""

    def occ(self, textos, partida=1):
        return [(n + 1, partida, None, t) for n, t in enumerate(textos)]

    def test_exact_matches_advance_in_order(self):
        parsed = [[("a", "F1"), ("b", "F2"), ("c", "F3")]]
        self.assertEqual(pgn_positions.align_fens(self.occ(["a", "b", "c"]), parsed), ["F1", "F2", "F3"])

    def test_a_skipped_comment_gets_none_and_the_rest_resyncs(self):
        parsed = [[("a", "F1"), ("c", "F3")]]
        self.assertEqual(pgn_positions.align_fens(self.occ(["a", "b", "c"]), parsed), ["F1", None, "F3"])
        # Depois de casar para a frente, o ponteiro passa do casado: dois
        # "Diagram" seguidos no parser sao dois na extracao, e nao o mesmo.
        parsed = [[("a", "F1"), ("Diagram", "F2"), ("Diagram", "F3")]]
        self.assertEqual(
            pgn_positions.align_fens(self.occ(["a", "b", "Diagram", "Diagram"]), parsed),
            ["F1", None, "F2", "F3"],
        )

    def test_a_merged_comment_gives_the_same_fen_to_both_pieces(self):
        # O parser juntou `{x} {y}` do mesmo lance em "x y"; os dois pedacos da
        # extracao recebem a mesma FEN e o ponteiro segue para o proximo.
        parsed = [[("x y", "F1"), ("z", "F2")]]
        self.assertEqual(pgn_positions.align_fens(self.occ(["x", "y", "z"]), parsed), ["F1", "F1", "F2"])

    def test_a_short_piece_is_not_matched_far_ahead_when_the_merged_one_is_here(self):
        # ":" existe sozinho la na frente; a busca para a frente o casaria e
        # deixaria "Instead" e os seguintes atras do ponteiro (medido: 245).
        parsed = [[(": Instead", "F1"), ("is better after", "F2"), (":", "F9")]]
        self.assertEqual(
            pgn_positions.align_fens(self.occ([":", "Instead", "is better after", ":"]), parsed),
            ["F1", "F1", "F2", "F9"],
        )

    def test_never_a_fen_on_a_different_text(self):
        parsed = [[("Diagram", "F1"), ("Diagram", "F2")]]
        fens = pgn_positions.align_fens(self.occ(["Other", "Diagram", "Diagram"]), parsed)
        self.assertEqual(fens, [None, "F1", "F2"])

    def test_forward_search_is_bounded(self):
        longe = [(f"x{n}", f"F{n}") for n in range(pgn_positions.FORWARD_SEARCH_LIMIT + 5)]
        parsed = [longe + [("alvo", "FA")]]
        self.assertEqual(pgn_positions.align_fens(self.occ(["alvo"]), parsed), [None])

    def test_games_resync_when_the_counts_match(self):
        parsed = [[("a", "F1")], [("a", "F2")]]
        occ = self.occ(["a"], partida=1) + self.occ(["a"], partida=2)
        self.assertEqual(pgn_positions.align_fens(occ, parsed), ["F1", "F2"])
        # A ressincronizacao e o que impede a FEN da partida 2 de cair num
        # comentario da partida 1 que o parser nao alcancou: "Diagram" existe
        # nas duas, e a sequencia global o casaria com a partida errada.
        parsed_diagrama = [[("x", "F1")], [("Diagram", "F2")]]
        occ_diagrama = self.occ(["Diagram"], partida=1) + self.occ(["Diagram"], partida=2)
        self.assertEqual(pgn_positions.align_fens(occ_diagrama, parsed_diagrama), [None, "F2"])
        # A extracao viu uma partida so (PGN com `\r`, ROADMAP 18): cai para a
        # sequencia global, ainda em ordem.
        occ1 = self.occ(["a", "a"], partida=1)
        self.assertEqual(pgn_positions.align_fens(occ1, parsed), ["F1", "F2"])

    def test_without_the_package_everything_is_none(self):
        self.assertEqual(pgn_positions.align_fens(self.occ(["a"]), None), [None])
        self.assertEqual(pgn_positions.compute_comment_fens("", []), [])


class FenBoardRowsTests(unittest.TestCase):
    INICIAL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    def test_the_initial_position_reads_as_eight_rows_of_eight(self):
        linhas = pgn_positions.fen_board_rows(self.INICIAL)
        self.assertEqual(len(linhas), 8)
        self.assertEqual(linhas[0], list("rnbqkbnr"))
        self.assertEqual(linhas[4], [""] * 8)
        self.assertEqual(linhas[7], list("RNBQKBNR"))

    def test_garbage_is_none(self):
        for ruim in (None, "", "8/8/8", "9/8/8/8/8/8/8/8 w", "rnbqkbnX/8/8/8/8/8/8/8 w"):
            with self.subTest(ruim=ruim):
                self.assertIsNone(pgn_positions.fen_board_rows(ruim))

    def test_side_to_move(self):
        self.assertEqual(pgn_positions.side_to_move(self.INICIAL), "Brancas jogam")
        self.assertEqual(pgn_positions.side_to_move("8/8/8/8/8/8/8/8 b - - 0 1"), "Pretas jogam")
        self.assertEqual(pgn_positions.side_to_move("8/8/8/8/8/8/8/8"), "")
        self.assertEqual(pgn_positions.side_to_move(None), "")


class OccurrenceFenTests(unittest.TestCase):
    """A coluna `occurrences.fen` (schema 11): gravada com as ocorrencias,
    lida pelo editor com preferencia pelo arquivo do filtro."""

    LIVRO = "C:/obras/livro.pgn"
    OUTRO = "C:/obras/outro.pgn"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "t.db")
        self.conn = initialize_database(self.db_path)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def test_fens_are_stored_alongside_and_none_stays_null(self):
        save_translation(self.cur, "a", "A", "pt", "en")
        save_translation(self.cur, "b", "B", "pt", "en")
        ids = resolve_comment_ids(self.cur, "pt", ["a", "b"], "en")
        occ = [(1, 1, 1, "a"), (2, 1, 2, "b")]
        record_occurrences(self.cur, self.LIVRO, occ, ids, fens=["F-a", None])
        self.assertEqual(fetch_occurrence_fen(self.cur, ids["a"]), "F-a")
        self.assertIsNone(fetch_occurrence_fen(self.cur, ids["b"]))
        # Sem a lista: tudo nulo, e nada quebra.
        record_occurrences(self.cur, self.OUTRO, occ, ids)
        self.assertEqual(fetch_occurrence_fen(self.cur, ids["a"]), "F-a")

    def test_the_filter_file_wins(self):
        save_translation(self.cur, "a", "A", "pt", "en")
        ids = resolve_comment_ids(self.cur, "pt", ["a"], "en")
        record_occurrences(self.cur, self.LIVRO, [(1, 1, 1, "a")], ids, fens=["F-livro"])
        record_occurrences(self.cur, self.OUTRO, [(1, 1, 1, "a")], ids, fens=["F-outro"])
        self.assertEqual(
            fetch_occurrence_fen(self.cur, ids["a"], preferred_file=os.path.abspath(self.OUTRO)),
            "F-outro",
        )
        self.assertEqual(
            fetch_occurrence_fen(self.cur, ids["a"], preferred_file=os.path.abspath(self.LIVRO)),
            "F-livro",
        )

    def test_a_version_10_database_gains_the_column(self):
        caminho = str(Path(self.tmp.name) / "v10.db")
        velho = sqlite3.connect(caminho)
        velho.execute(
            f"CREATE TABLE {OCCURRENCES_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " comment_id INTEGER NOT NULL, source_file TEXT NOT NULL, game_index INTEGER,"
            " comment_index INTEGER NOT NULL, move_number INTEGER, recorded_at TEXT,"
            " UNIQUE(source_file, comment_index))"
        )
        velho.execute("PRAGMA user_version = 10")
        velho.commit()
        velho.close()
        conn = initialize_database(caminho)
        try:
            colunas = [r[1] for r in conn.execute(f"PRAGMA table_info({OCCURRENCES_TABLE})")]
            self.assertIn("fen", colunas)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        finally:
            conn.close()


class WorkerFenTests(WorkerFallbackHarness, unittest.TestCase):
    """O worker calcula a FEN na vez do arquivo, quando a opcao esta ligada e
    o pacote existe; senao grava nulo e diz por que."""

    def traduz(self, text, *_a, **_k):
        if " ||| " in text:
            return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
        return f"[{text}]"

    def fens(self, tmp_path):
        conn = initialize_database(str(tmp_path / "cache.db"))
        try:
            return [r[0] for r in conn.execute(f"SELECT fen FROM {OCCURRENCES_TABLE} ORDER BY comment_index")]
        finally:
            conn.close()

    @unittest.skipUnless(_chess_installed(), "python-chess nao instalado")
    def test_fens_are_recorded_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, self.traduz)
            fens = self.fens(tmp_path)
        self.assertEqual(len(fens), 3)
        self.assertTrue(all(fens))
        self.assertTrue(fens[0].startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b"))
        self.assertTrue(any("Posicoes (FEN) calculadas: 3/3" in linha for linha in app.logs))

    def test_the_option_off_records_nothing_and_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            caminho = settings.default_settings_path()
            settings.save_settings({"board": {"fen": False}}, caminho)
            # O arquivo vive no sandbox do MODULO: sem apagar, os testes
            # seguintes rodariam com a opcao desligada.
            self.addCleanup(lambda: os.path.exists(caminho) and os.remove(caminho))
            app, _pgn = self.run_worker(tmp_path, self.traduz)
            fens = self.fens(tmp_path)
        self.assertEqual(fens, [None, None, None])
        self.assertFalse(any("FEN" in linha for linha in app.logs))

    def test_without_the_package_it_warns_once_and_records_null(self):
        original = translation_worker.chess_available
        translation_worker.chess_available = lambda: False
        self.addCleanup(setattr, translation_worker, "chess_available", original)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, self.traduz)
            fens = self.fens(tmp_path)
        self.assertEqual(fens, [None, None, None])
        avisos = [linha for linha in app.logs if "python-chess nao esta instalado" in linha]
        self.assertEqual(len(avisos), 1)
        self.assertIn("Configuracoes", avisos[0])


# ===========================================================================
# Secao 18 — o banco passa a saber de onde cada traducao veio
# ===========================================================================


class ReadingContextTests(unittest.TestCase):
    """O contexto de leitura sai do PGN: partida, indice e numero do lance.

    Tudo aqui roda sobre `comment_reading_context`, que e a funcao pura, e sobre a
    extracao de verdade num arquivo em disco. Nenhum destes numeros existia no
    banco antes desta secao — a lista do editor era ordem de insercao, e ordem de
    insercao mistura todos os PGN ja processados.
    """

    def contexto(self, texto):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\{.*?\}", texto, re.DOTALL)]
        return comment_reading_context(texto, spans)

    def test_the_move_cited_inside_a_comment_is_not_the_position(self):
        """O caso que obriga a apagar os spans antes de ler o movetext.

        Comentario de livro cita lance a vontade ("melhor era 14. Bxf7"). Lido
        junto com o movetext, o lance CITADO no comentario 1 passaria a ser a
        posicao do comentario 2 — um numero errado com cara de medido.
        """
        texto = '[Event "A"]\n\n1. e4 {melhor era 14. Bxf7} 2. Nf3 {aqui}\n'
        self.assertEqual(self.contexto(texto), [(1, 1), (1, 2)])

    def test_a_file_with_only_cr_line_endings_counts_its_games(self):
        """A exportacao do ChessBase usa so `\\r`; `^` com MULTILINE so ve
        `\\n`, e no PGN real do usuario (99 partidas) tudo saia como partida 1
        (achado em ROADMAP 28.8). A linha de tag tambem precisa ser reconhecida
        para o `[Date "2011.05.12"]` nao virar lance."""
        texto = (
            '[Event "A"]\r[Round "12."]\r\r1. e4 {um} 2. Nf3 {dois}\r\r'
            '[Event "B"]\r\r1. d4 {tres}\r'
        )
        self.assertEqual(self.contexto(texto), [(1, 1), (1, 2), (2, 1)])
        self.assertEqual(
            self.contexto(texto.replace("\r", "\r\n")), [(1, 1), (1, 2), (2, 1)]
        )

    def test_an_event_tag_inside_a_comment_does_not_start_a_game(self):
        """A mesma protecao, do outro lado: o comentario tambem nao cria partida."""
        texto = '[Event "A"]\n\n1. e4 {citando\n[Event "B"]\nno meio} 2. Nf3 {aqui}\n'
        self.assertEqual([partida for partida, _lance in self.contexto(texto)], [1, 1])

    def test_a_comment_before_the_first_move_has_no_move_number(self):
        """E `None`, e nao o lance da partida ANTERIOR.

        Sem o recorte por partida, um comentario colado nas tags da partida 2
        herdaria o lance 41 da partida 1 e afirmaria com confianca uma posicao que
        nao existe. `None` e a unica resposta verdadeira.
        """
        texto = (
            '[Event "A"]\n\n1. e4 e5 41. Kf1 1-0\n\n'
            '[Event "B"]\n[White "X"]\n\n{antes de tudo} 1. d4 {depois} 1/2-1/2\n'
        )
        self.assertEqual(self.contexto(texto), [(2, None), (2, 1)])

    def test_the_game_number_counts_the_event_tags(self):
        texto = (
            '[Event "A"]\n\n1. e4 {um} 1-0\n\n'
            '[Event "B"]\n\n1. d4 {dois} 1-0\n\n'
            '[Event "C"]\n\n1. c4 {tres} 1-0\n'
        )
        self.assertEqual([p for p, _l in self.contexto(texto)], [1, 2, 3])

    def test_a_date_tag_is_not_a_move_number(self):
        """`[Date "2011.??.??"]` — a data com mes e dia desconhecidos.

        A data COMPLETA (`2011.05.12`) nao serve para este teste, e descobri-lo foi
        o que a mutacao deu: ela ja e recusada pela regra do decimal, entao o teste
        passava com a checagem de linha de tag e sem ela. A forma com `??` e comum
        em PGN de banco de dados, e nela o `2011.` vira lance 2011 se ninguem
        reparar que aquilo e uma linha de tag.
        """
        texto = '[Event "A"]\n[Date "2011.??.??"]\n\n{antes do primeiro lance} 1. e4\n'
        self.assertEqual(self.contexto(texto), [(1, None)])

    def test_a_semicolon_comment_does_not_give_a_move_number(self):
        """Comentario `;` e texto, nao movetext — e o programa nem o traduz.

        O `;` tem de ser a ULTIMA coisa antes do comentario, e isto tambem saiu da
        mutacao: com um `2. Nf3` depois dele, o lance certo vinha do `2.` e o teste
        passava sem a checagem nenhuma.
        """
        texto = '[Event "A"]\n\n1. e4 ; ver a partida 99. Kh1\n{aqui}\n'
        self.assertEqual(self.contexto(texto), [(1, 1)])

    def test_movetext_with_no_tags_is_a_single_game(self):
        """Nao existe partida zero em ordem de leitura."""
        self.assertEqual(self.contexto("1. e4 {um} 2. Nf3 {dois}"), [(1, 1), (1, 2)])

    def test_the_decimal_inside_the_movetext_is_not_taken_as_a_move(self):
        """`+0.35` num comentario nao chega aqui (o span e apagado), mas um
        decimal solto no movetext tambem nao pode virar lance.

        Este teste falhou quando foi escrito: o `0.` casava e o comentario
        seguinte saia com "lance 0" — um numero errado, e visivel na tela.
        """
        texto = "1. e4 {um} +0.35 {dois}"
        self.assertEqual([lance for _p, lance in self.contexto(texto)], [1, 1])

    def test_castling_written_with_zeros_is_still_a_move(self):
        """A contraprova do recorte acima, e o que impede a correcao larga.

        Recusar todo digito depois do ponto (`1. 0-0`, roque escrito com zeros em
        PGN antigo) apagaria um lance legitimo. O que caracteriza decimal e o
        digito COLADO no ponto.
        """
        self.assertEqual(self.contexto("1. 0-0 {depois do roque}"), [(1, 1)])

    def test_the_index_counts_only_the_comments_that_become_rows(self):
        """Um `{}` vazio nao ocupa posicao: ele nao vira linha no banco.

        Se ocupasse, o indice do comentario seguinte pularia um numero e a ordem
        de leitura teria um buraco que nada explica.
        """
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        pgn = base / "vazio.pgn"
        pgn.write_text(
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {} 3. Bb5 {dois}\n', encoding="utf-8"
        )

        info = extract_comments_from_file(str(pgn))
        self.assertEqual(
            info["occurrences"],
            [(1, 1, 1, "um"), (2, 1, 3, "dois")],
        )

    def test_the_extraction_keeps_the_occurrences_aligned_with_the_comments(self):
        """`comments[i]` e `occurrences[i]` falam da mesma posicao do arquivo."""
        base = Path(tempfile.mkdtemp())
        pgn = base / "alinhado.pgn"
        pgn.write_text(
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 3. Bb5 {tres}\n',
            encoding="utf-8",
        )

        info = extract_comments_from_file(str(pgn))
        self.assertEqual(
            [texto for _i, _p, _l, texto in info["occurrences"]], info["comments"]
        )
        self.assertEqual(
            [indice for indice, _p, _l, _t in info["occurrences"]], [1, 2, 3]
        )

    def test_a_file_that_cannot_be_read_returns_an_empty_occurrence_list(self):
        """O worker le a chave sem checar; ela precisa existir sempre."""
        info = extract_comments_from_file(str(Path(tempfile.mkdtemp()) / "nao-existe.pgn"))
        self.assertEqual(info["occurrences"], [])


class OccurrenceTestCase(unittest.TestCase):
    """Base das ocorrencias: um banco novo e dois PGN de mentira em disco."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.conn = initialize_database(str(self.base / "cache.db"))
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def caminho(self, nome, pasta=None):
        """Um caminho ABSOLUTO, que e como a ocorrencia guarda arquivo."""
        destino = self.base if pasta is None else self.base / pasta
        destino.mkdir(parents=True, exist_ok=True)
        return str(destino / nome)

    def gravar(self, *textos, source="en", target="pt"):
        for texto in textos:
            save_translation(self.cur, texto, f"T {texto}", target, source)
        self.conn.commit()
        return resolve_comment_ids(self.cur, target, list(textos), source)

    def registrar(self, arquivo, ocorrencias, ids=None, target="pt", source="en"):
        if ids is None:
            ids = resolve_comment_ids(
                self.cur, target, [t for _i, _p, _l, t in ocorrencias], source
            )
        resultado = record_occurrences(self.cur, arquivo, ocorrencias, ids)
        self.conn.commit()
        return resultado

    def linhas_de_ocorrencia(self):
        return self.cur.execute(
            f"SELECT source_file, game_index, comment_index, move_number"
            f" FROM {OCCURRENCES_TABLE} ORDER BY source_file, comment_index"
        ).fetchall()


class OccurrenceRecordingTests(OccurrenceTestCase):
    """Gravar de onde o comentario veio, sem tocar na identidade da traducao."""

    def test_the_same_comment_in_two_books_is_one_row_and_two_occurrences(self):
        """O coracao do desenho (ROADMAP 18): a relacao e N para 1.

        O reuso e o que faz o acervo valer — o mesmo comentario em doze livros e
        uma traducao e uma revisao. Se o contexto tivesse entrado como coluna de
        `comments`, cada livro teria criado a sua linha e a revisao passaria a ser
        feita doze vezes.
        """
        ids = self.gravar("Diagram")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 5, "Diagram")], ids)
        self.registrar(self.caminho("cap02.pgn"), [(1, 3, 9, "Diagram")], ids)

        self.assertEqual(
            self.cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 1
        )
        self.assertEqual(
            self.cur.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0],
            2,
        )

    def test_the_occurrence_keeps_the_game_and_the_move(self):
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(7, 3, 24, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 3, 7, 24)])

    def test_a_comment_before_the_first_move_stores_a_null_move(self):
        """`None` chega ao banco como NULL, e nao como zero: zero se confundiria
        com medicao."""
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, None, "um")], ids)

        self.assertIsNone(self.linhas_de_ocorrencia()[0][3])

    def test_reprocessing_the_same_file_does_not_duplicate_the_positions(self):
        """Traduzir a mesma pasta duas vezes e rotina (o cache existe para isso)."""
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        posicoes = [(1, 1, 1, "um"), (2, 1, 2, "dois")]

        self.registrar(arquivo, posicoes, ids)
        self.registrar(arquivo, posicoes, ids)

        self.assertEqual(len(self.linhas_de_ocorrencia()), 2)

    def test_a_file_that_shrank_loses_the_positions_that_no_longer_exist(self):
        """O arquivo em disco e a verdade sobre a obra.

        O usuario apagou metade do capitulo e reprocessou: as posicoes que
        sobravam nao existem mais, e mante-las deixaria o banco afirmando que o
        comentario 2 daquele arquivo e um texto que nao esta la.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um"), (2, 1, 2, "dois")], ids)

        self.registrar(arquivo, [(1, 1, 1, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 1, 1, 1)])

    def test_a_comment_without_a_row_is_counted_and_not_recorded(self):
        """Um comentario que falhou na traducao nao tem linha para apontar.

        A ocorrencia aponta para uma traducao; sem ela nao ha para onde apontar. O
        que nao pode acontecer e o numero desaparecer — "a obra tem 2 posicoes" e
        diferente de "tem 2, uma ainda sem traducao".
        """
        ids = self.gravar("um")
        gravadas, sem_linha = self.registrar(
            self.caminho("cap01.pgn"),
            [(1, 1, 1, "um"), (2, 1, 2, "o que falhou")],
            ids,
        )

        self.assertEqual((gravadas, sem_linha), (1, 1))
        self.assertEqual(len(self.linhas_de_ocorrencia()), 1)

    def test_two_spellings_of_the_same_path_are_one_work(self):
        """O caminho e a chave da obra, e `cap01.pgn` e `./cap01.pgn` sao o mesmo
        arquivo. Duas grafias no banco dariam duas obras no filtro, cada uma com
        metade do livro."""
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um")], ids)
        self.registrar(os.path.join(str(self.base), ".", "cap01.pgn"),
                       [(1, 1, 1, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 1, 1, 1)])

    def test_a_position_of_the_work_has_a_single_owner(self):
        """A UNIQUE da tabela, exercitada por fora de `record_occurrences`.

        Ela nao inclui `comment_id` de proposito: com ele, o comentario 5 de um
        arquivo poderia ter dois donos ao mesmo tempo — a afirmacao velha e a nova
        convivendo, e a ordem de leitura decidindo por sorteio qual aparece.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")

        with self.assertRaises(sqlite3.IntegrityError):
            self.cur.executemany(
                f"INSERT INTO {OCCURRENCES_TABLE}"
                f" (comment_id, source_file, game_index, comment_index)"
                f" VALUES (?, ?, 1, 5)",
                [(ids["um"], arquivo), (ids["dois"], arquivo)],
            )

    def test_resolve_only_answers_inside_the_pair(self):
        """O mesmo texto vindo do espanhol e outra traducao (garantia P1).

        Resolver sem o par faria a ocorrencia de um PGN ingles apontar para a linha
        espanhola — o contexto certo no comentario errado.
        """
        save_translation(self.cur, "Nada", "Nothing", "pt", "es")
        self.conn.commit()

        self.assertEqual(resolve_comment_ids(self.cur, "pt", ["Nada"], "en"), {})
        self.assertEqual(
            list(resolve_comment_ids(self.cur, "pt", ["Nada"], "es")), ["Nada"]
        )

    def test_recording_nothing_still_clears_the_file(self):
        """Um arquivo que ficou sem nenhuma posicao resolvivel nao pode manter as
        antigas: elas falam de um conteudo que ninguem mais le ali."""
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um")], ids)

        self.registrar(arquivo, [(1, 1, 1, "outro texto")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [])


class ReadingOrderTests(OccurrenceTestCase):
    """A lista do editor em ordem de leitura da obra, e o filtro por arquivo."""

    def setUp(self):
        super().setUp()
        # Inseridos FORA da ordem de leitura, de proposito: e o que acontece de
        # verdade, porque quem grava e a ordem em que a API respondeu e o cache
        # encheu. Com `ORDER BY id` a lista sai nesta ordem aqui.
        self.ids = self.gravar("C terceiro", "A primeiro", "B segundo")
        self.arquivo = self.caminho("cap01.pgn")
        self.outro = self.caminho("cap02.pgn")
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "A primeiro"),
                (2, 1, 3, "B segundo"),
                (3, 2, 12, "C terceiro"),
            ],
            self.ids,
        )

    def originais(self, **kwargs):
        return [
            linha[1]
            for linha in fetch_review_rows_page(self.cur, "pt", **kwargs)
        ]

    def leitura(self, **kwargs):
        return self.originais(
            source_file=self.arquivo, order=ORDER_BY_OCCURRENCE, **kwargs
        )

    def test_the_list_follows_the_work_and_not_the_insertion_order(self):
        """O item inteiro da secao 18, numa linha: `ORDER BY id` nao e ordem de
        leitura de nada."""
        self.assertEqual(self.originais(), ["C terceiro", "A primeiro", "B segundo"])
        self.assertEqual(self.leitura(), ["A primeiro", "B segundo", "C terceiro"])

    def test_a_comment_repeated_in_the_file_appears_once(self):
        """"Diagram" aparece trinta vezes num livro, e a lista e de comentarios."""
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "A primeiro"),
                (2, 1, 2, "A primeiro"),
                (3, 1, 3, "A primeiro"),
                (4, 1, 4, "B segundo"),
            ],
            self.ids,
        )

        self.assertEqual(self.leitura(), ["A primeiro", "B segundo"])

    def test_the_repeated_comment_is_ordered_by_its_first_position(self):
        """Onde o leitor o encontra primeiro, e nao onde ele reaparece."""
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "B segundo"),
                (2, 1, 2, "A primeiro"),
                (3, 1, 3, "B segundo"),
            ],
            self.ids,
        )

        self.assertEqual(self.leitura(), ["B segundo", "A primeiro"])

    def test_the_file_filter_leaves_out_the_other_book(self):
        self.registrar(self.outro, [(1, 1, 1, "C terceiro")], self.ids)

        self.assertEqual(
            self.originais(source_file=self.outro, order=ORDER_BY_OCCURRENCE),
            ["C terceiro"],
        )
        self.assertEqual(
            count_review_rows(self.cur, "pt", source_file=self.outro), 1
        )

    def test_a_row_with_no_occurrence_is_outside_every_file(self):
        """As 201.607 linhas migradas nao pertencem a obra nenhuma — e o filtro
        "Todos" continua sendo o unico lugar em que elas aparecem."""
        self.gravar("sem arquivo")

        self.assertEqual(len(self.originais()), 4)
        self.assertNotIn("sem arquivo", self.leitura())

    def test_the_status_counts_respect_the_file(self):
        self.registrar(self.outro, [(1, 1, 1, "C terceiro")], self.ids)

        resumo = get_review_status_counts(self.cur, "pt", source_file=self.outro)
        self.assertEqual((resumo["total"], resumo["pending"]), (1, 1))

    def test_the_offset_of_an_id_follows_the_active_order(self):
        """A classe de defeito que a garantia R10 fechou, pelo outro lado.

        "C terceiro" e o primeiro id do banco e o ULTIMO da obra. Com a lista em
        ordem de leitura e o offset contado por id, o "Ir para ID" mandaria a
        janela para a pagina do offset 0 e selecionaria outra linha — sem erro
        nenhum na tela.
        """
        alvo = self.ids["C terceiro"]

        self.assertEqual(get_review_row_offset(self.cur, "pt", alvo), 0)
        self.assertEqual(
            get_review_row_offset(
                self.cur, "pt", alvo,
                source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
            ),
            2,
        )

    def test_the_offset_and_the_page_agree_in_reading_order(self):
        """O offset serve para posicionar na pagina: os dois criterios tem de ser
        o mesmo. Conferido linha por linha, e nao so na primeira."""
        for esperado, texto in enumerate(["A primeiro", "B segundo", "C terceiro"]):
            offset = get_review_row_offset(
                self.cur, "pt", self.ids[texto],
                source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
            )
            self.assertEqual(offset, esperado, texto)
            self.assertEqual(
                self.leitura(limit=1, offset=offset), [texto], texto
            )

    def test_paging_in_reading_order_neither_repeats_nor_skips(self):
        """Ordem total: sem desempate, duas linhas podem trocar de lugar entre
        duas paginas — uma sai duas vezes e a outra nenhuma."""
        paginas = [
            self.leitura(limit=2, offset=0),
            self.leitura(limit=2, offset=2),
        ]

        self.assertEqual(
            paginas[0] + paginas[1], ["A primeiro", "B segundo", "C terceiro"]
        )

    def test_asking_for_reading_order_without_a_file_falls_back_to_id(self):
        """Sem arquivo, ordenar pela primeira ocorrencia de cada comentario
        custaria uma agregacao da tabela por pagina — a garantia R5."""
        self.assertFalse(reads_in_occurrence_order(ORDER_BY_OCCURRENCE, None))
        self.assertEqual(
            self.originais(order=ORDER_BY_OCCURRENCE),
            ["C terceiro", "A primeiro", "B segundo"],
        )

    def test_the_search_and_the_file_filter_compose(self):
        self.assertEqual(
            self.leitura(search_text="segundo", search_mode=SEARCH_MODE_SUBSTRING),
            ["B segundo"],
        )

    def test_the_status_filter_and_the_reading_order_compose(self):
        set_translation_verified_by_id(self.cur, self.ids["B segundo"])
        self.conn.commit()

        self.assertEqual(self.leitura(status_filter="verified"), ["B segundo"])
        self.assertEqual(
            self.leitura(status_filter="pending"), ["A primeiro", "C terceiro"]
        )

    def test_the_full_row_fetch_takes_the_order_too(self):
        """`fetch_review_rows` alimenta o relatorio QA e as estatisticas; sem a
        ordem, o relatorio de uma obra sairia embaralhado."""
        self.assertEqual(
            [
                linha[1]
                for linha in fetch_review_rows(
                    self.cur, "pt",
                    source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
                )
            ],
            ["A primeiro", "B segundo", "C terceiro"],
        )


class OccurrenceListingTests(OccurrenceTestCase):
    """O que o filtro por arquivo e o rodape do editor leem do banco."""

    def test_the_file_list_separates_positions_from_comments(self):
        """As duas contagens dizem coisas diferentes: tamanho da obra e trabalho
        de revisao. A diferenca entre elas e a repeticao interna do livro."""
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(
            arquivo,
            [(1, 1, 1, "um"), (2, 1, 2, "um"), (3, 1, 3, "dois")],
            ids,
        )

        self.assertEqual(list_occurrence_files(self.cur, "pt"), [(arquivo, 3, 2)])

    def test_the_file_list_is_scoped_to_the_pair(self):
        """O editor mostra um par por vez (garantia R9), e o menu de arquivos
        precisa acompanhar: um arquivo do par espanhol no menu do ingles seria um
        filtro que devolve zero linhas."""
        ids_en = self.gravar("um", source="en")
        ids_es = self.gravar("uno", source="es")
        self.registrar(self.caminho("ingles.pgn"), [(1, 1, 1, "um")], ids_en)
        self.registrar(
            self.caminho("espanhol.pgn"), [(1, 1, 1, "uno")], ids_es, source="es"
        )

        self.assertEqual(
            [linha[0] for linha in list_occurrence_files(self.cur, "pt", "en")],
            [self.caminho("ingles.pgn")],
        )
        self.assertEqual(
            len(list_occurrence_files(self.cur, "pt")), 2
        )

    def test_the_file_list_is_ordered_by_name(self):
        """E como capitulo se ordena — e nao por quantidade, que faria a ordem do
        menu mudar a cada execucao."""
        ids = self.gravar("um")
        for nome in ("cap03.pgn", "cap01.pgn", "cap02.pgn"):
            self.registrar(self.caminho(nome), [(1, 1, 1, "um")], ids)

        self.assertEqual(
            [os.path.basename(linha[0]) for linha in list_occurrence_files(self.cur, "pt")],
            ["cap01.pgn", "cap02.pgn", "cap03.pgn"],
        )

    def test_the_occurrences_of_a_comment_come_with_the_full_total(self):
        """A lista vem cortada e o total vem inteiro: o rodape mostra as primeiras
        e diz quantas faltam."""
        ids = self.gravar("Diagram")
        for nome in ("cap01.pgn", "cap02.pgn", "cap03.pgn"):
            self.registrar(self.caminho(nome), [(1, 1, 1, "Diagram")], ids)

        linhas, total = fetch_comment_occurrences(self.cur, ids["Diagram"], limit=2)

        self.assertEqual(total, 3)
        self.assertEqual(len(linhas), 2)

    def test_the_preferred_file_comes_first(self):
        """Quem esta lendo o capitulo 7 nao pode ver no rodape a posicao do mesmo
        comentario no capitulo 1: e verdade, responde outra pergunta, e na tela
        passa por erro."""
        ids = self.gravar("Diagram")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "Diagram")], ids)
        self.registrar(self.caminho("cap07.pgn"), [(1, 1, 1, "Diagram")], ids)

        linhas, _total = fetch_comment_occurrences(
            self.cur, ids["Diagram"], limit=1,
            preferred_file=self.caminho("cap07.pgn"),
        )

        self.assertEqual([os.path.basename(l[0]) for l in linhas], ["cap07.pgn"])

    def test_a_comment_with_no_occurrence_answers_empty(self):
        ids = self.gravar("um")
        self.assertEqual(fetch_comment_occurrences(self.cur, ids["um"]), ([], 0))


class FileProgressTests(OccurrenceTestCase):
    """Progresso por obra: "faltam 120 comentarios do capitulo 7"."""

    def test_a_comment_repeated_in_the_file_counts_once(self):
        """O numero mais facil de errar aqui.

        Somando `verified` sobre o `JOIN`, um comentario verificado que aparece
        tres vezes viraria tres verificacoes e o progresso passaria de 100%.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(
            arquivo,
            [
                (1, 1, 1, "um"),
                (2, 1, 2, "um"),
                (3, 1, 3, "um"),
                (4, 1, 4, "dois"),
            ],
            ids,
        )
        set_translation_verified_by_id(self.cur, ids["um"])
        self.conn.commit()

        (linha,) = get_file_progress(self.cur)
        _arquivo, posicoes, comentarios, verificadas, pendentes, _avisos = linha

        self.assertEqual((comentarios, verificadas, pendentes), (2, 1, 1))
        # As posicoes, essas sim, contam a repeticao: e o tamanho da obra.
        self.assertEqual(posicoes, 4)

    def test_the_progress_counts_the_quality_warnings_of_the_work(self):
        arquivo = self.caminho("cap01.pgn")
        save_translation(self.cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(self.cur, "The rook.", "A torre.", "pt", "en")
        self.conn.commit()
        self.registrar(
            arquivo,
            [(1, 1, 1, "The open file."), (2, 1, 2, "The rook.")],
        )

        self.assertEqual(get_file_progress(self.cur)[0][5], 1)

    def test_each_work_is_counted_on_its_own(self):
        ids = self.gravar("um", "dois")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)
        self.registrar(
            self.caminho("cap02.pgn"),
            [(1, 1, 1, "um"), (2, 1, 2, "dois")],
            ids,
        )

        self.assertEqual(
            [(os.path.basename(l[0]), l[2]) for l in get_file_progress(self.cur)],
            [("cap01.pgn", 1), ("cap02.pgn", 2)],
        )

    def test_a_database_with_no_occurrence_has_no_work(self):
        """O estado de todo banco migrado: traducao ha, procedencia nao."""
        self.gravar("um")
        self.assertEqual(get_file_progress(self.cur), [])
        self.assertEqual(get_database_stats(self.cur)["per_file"], [])

    def test_the_stats_carry_the_progress_per_work(self):
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)

        self.assertEqual(
            get_database_stats(self.cur)["per_file"], get_file_progress(self.cur)
        )


class OccurrenceSchemaTests(unittest.TestCase):
    """A migracao 6 -> 7, e o que ela deliberadamente NAO faz."""

    def banco_no_schema_6(self):
        """Um banco completo, menos a tabela de ocorrencias.

        Feito derrubando a tabela e voltando a marca de versao: o ponto do teste e
        que a abertura seguinte reconheca o banco antigo e complete o schema, e
        essa e exatamente a situacao do banco do usuario depois da atualizacao.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "cache.db"

        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        conn.commit()
        conn.execute(f"DROP TABLE {OCCURRENCES_TABLE}")
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
        conn.close()
        return db_path

    def test_opening_an_older_database_creates_the_table(self):
        db_path = self.banco_no_schema_6()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)

        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
        )
        self.assertEqual(
            conn.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0], 0
        )

    def test_the_migration_does_not_invent_a_provenance(self):
        """Nao ha de onde derivar arquivo, partida e lance das linhas ja gravadas.

        Um backfill teria de inventar, e uma procedencia falsa e pior do que a
        ausencia: ela apareceria no filtro por arquivo como uma obra que ninguem
        traduziu.
        """
        db_path = self.banco_no_schema_6()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        self.assertEqual(list_occurrence_files(cur, "pt"), [])
        self.assertEqual(
            cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2
        )

    def test_the_unique_of_comments_is_untouched(self):
        """A tabela ao lado nao pode ter mexido no que define uma traducao."""
        db_path = self.banco_no_schema_6()
        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        self.assertEqual(save_translation(cur, "the rook", "outra", "pt", "en"), "unchanged")
        self.assertEqual(save_translation(cur, "the rook", "la torre", "es", "en"), "inserted")


class ClearTranslationsTakesOccurrencesTests(OccurrenceTestCase):
    """Garantia Z3: zerar leva historico, indice, cache — e ocorrencias."""

    def test_zeroing_the_bank_takes_the_occurrences(self):
        """O `AUTOINCREMENT` reinicia com a tabela.

        Uma ocorrencia sobrevivente apontaria para a PRIMEIRA traducao gravada
        depois do zeramento: o comentario errado, no arquivo certo, sem nada
        acusando na tela.
        """
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)

        clear_all_translations(self.conn)

        cur = self.conn.cursor()
        self.assertEqual(
            cur.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0], 0
        )
        self.assertEqual(get_file_progress(cur), [])

    def test_the_table_still_exists_after_zeroing(self):
        """Derrubar sem recriar deixaria o proximo filtro por arquivo em erro."""
        clear_all_translations(self.conn)
        cur = self.conn.cursor()

        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)
        self.assertEqual(len(get_file_progress(cur)), 1)


class WorkerOccurrenceTests(unittest.TestCase):
    """O worker grava a procedencia com os dados que ele ja tem na mao."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "cache.db"

    def falso_translate(self, resposta=None):
        def falso(text, *_a, **_k):
            if resposta is not None:
                return resposta
            # Devolve o texto com um prefixo, preservando os separadores de lote:
            # assim o realinhamento continua valendo e cada comentario ganha uma
            # traducao propria.
            return " ||| ".join(f"T {parte}" for parte in text.split(" ||| "))

        original = translation_worker.translate_text
        translation_worker.translate_text = falso
        self.addCleanup(setattr, translation_worker, "translate_text", original)

    def escreve(self, nome, conteudo):
        caminho = self.base / nome
        caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def ocorrencias(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                f"SELECT o.source_file, o.game_index, o.comment_index,"
                f" o.move_number, c.original_comment"
                f" FROM {OCCURRENCES_TABLE} o JOIN comments c ON c.id = o.comment_id"
                f" ORDER BY o.source_file, o.comment_index"
            ).fetchall()
        finally:
            conn.close()

    def test_a_run_records_where_each_comment_was_read(self):
        """Ponta a ponta: do PGN em disco a tabela de ocorrencias."""
        self.falso_translate()
        pgn = self.escreve(
            "cap01.pgn",
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 1-0\n\n'
            '[Event "B"]\n\n1. d4 {tres} 1-0\n',
        )

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="en"
        )

        self.assertEqual(
            self.ocorrencias(),
            [
                (str(pgn), 1, 1, 1, "um"),
                (str(pgn), 1, 2, 2, "dois"),
                (str(pgn), 2, 3, 1, "tres"),
            ],
        )

    def test_a_comment_reused_from_the_cache_is_recorded_too(self):
        """A segunda execucao nao chama a API — e a procedencia do arquivo novo
        tem de aparecer do mesmo jeito. Registrar so o que a API respondeu deixaria
        de fora justamente o acervo que o cache existe para reaproveitar."""
        self.falso_translate()
        primeiro = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 1-0\n')
        translation_worker.run_translation(
            FakeApp(self.db_path), str(primeiro), "pt", False, source_language="en"
        )

        segundo = self.escreve("cap02.pgn", '[Event "A"]\n\n1. e4 e5 2. Nf3 {um} 1-0\n')
        translation_worker.run_translation(
            FakeApp(self.db_path), str(segundo), "pt", False, source_language="en"
        )

        self.assertEqual(
            [(os.path.basename(l[0]), l[3]) for l in self.ocorrencias()],
            [("cap01.pgn", 1), ("cap02.pgn", 2)],
        )

    def test_the_run_says_how_many_positions_it_recorded(self):
        """O numero no log e o que separa "a obra tem 2 posicoes" de "tem 2, uma
        ainda sem traducao"."""
        self.falso_translate()
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 1-0\n')
        app = FakeApp(self.db_path)

        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="en"
        )

        self.assertTrue(
            any("Posicoes registradas: 2/2" in linha for linha in app.logs),
            app.logs,
        )

    def test_a_comment_the_api_refused_is_reported_as_missing(self):
        """A API nao respondeu: o comentario fica no idioma original e sem linha no
        banco, e a posicao dele nao pode ser inventada."""
        self.falso_translate(resposta="")
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 1-0\n')
        app = FakeApp(self.db_path)

        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="en"
        )

        self.assertEqual(self.ocorrencias(), [])
        self.assertTrue(
            any("1 sem traducao no banco" in linha for linha in app.logs), app.logs
        )

    def test_the_occurrence_is_recorded_under_the_declared_pair(self):
        """A ocorrencia aponta para a LINHA, e a linha e do par: o mesmo PGN
        declarado como espanhol e como ingles da duas traducoes, cada uma com a
        sua procedencia."""
        self.falso_translate()
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {Nada} 1-0\n')

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )
        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="it"
        )

        conn = initialize_database(str(self.db_path))
        self.addCleanup(conn.close)
        # O arquivo e o mesmo, entao a posicao 1 dele tem um dono so: a ultima
        # execucao. As duas linhas de traducao continuam existindo.
        self.assertEqual(
            conn.execute(
                f"SELECT c.source_language FROM {OCCURRENCES_TABLE} o"
                f" JOIN comments c ON c.id = o.comment_id"
            ).fetchall(),
            [("it",)],
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2
        )


if __name__ == "__main__":
    unittest.main()
