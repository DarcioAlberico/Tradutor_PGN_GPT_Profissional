"""Os avisos de qualidade: heuristicas, versao, reavaliacao, terminologia suspeita.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import sqlite3
import tempfile
import unittest
import unittest.mock
from collections import Counter
from pathlib import Path

from tradutor_pgn import (
    database,
)
from tradutor_pgn.app_config import (
    LANGUAGES,
)
from tradutor_pgn.database import (
    QUALITY_VERSION_KEY,
    QualityReevaluationCanceled,
    SCHEMA_VERSION,
    apply_automatic_translation_updates,
    backfill_quality_warnings,
    count_from_status_counts,
    count_review_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    get_db_metadata,
    get_quality_heuristics_version,
    get_review_status_counts,
    quality_warning_flag,
    initialize_database,
    quality_heuristics_are_current,
    reevaluate_quality_warnings,
    save_translation,
    set_db_metadata,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    apply_automatic_substitutions,
)
from tradutor_pgn.review_quality import (
    QUALITY_HEURISTICS_VERSION,
    QUALITY_REPORT_HEADERS,
    eval_symbols,
    build_quality_report_rows,
    evaluate_translation_quality,
    filter_quality_warning_rows,
    find_first_quality_warning,
    row_has_quality_warning,
    row_language_pair,
    summarize_quality_warnings,
)
from tradutor_pgn import chess_terms
from tradutor_pgn.chess_terms import (
    find_suspect_terms,
    load_suspect_terms,
    suspect_terms_for,
)
from tradutor_pgn.db_tools import (
    format_quality_stats,
)
from tradutor_pgn.glossario import (
    set_glossary_error_handler,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    _schema3_database,
    call_quietly,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class QualityWarningColumnTests(unittest.TestCase):
    """A coluna quality_warning e um cache; o perigo e ela ficar obsoleta."""

    def _flags(self, cursor):
        return dict(
            cursor.execute(
                "SELECT id, quality_warning FROM comments ORDER BY id"
            ).fetchall()
        )

    def _recalculado(self, cursor):
        return {
            row_id: (1 if evaluate_translation_quality(orig, trans) else 0)
            for row_id, orig, trans in cursor.execute(
                "SELECT id, original_comment, translated_comment FROM comments ORDER BY id"
            ).fetchall()
        }

    def test_column_stays_in_sync_across_every_write_path(self):
        longo = "White plays a very strong move on the kingside " * 2
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "cache.db"))
            cursor = conn.cursor()

            # 1. insercao: uma com aviso (chaves), uma sem
            save_translation(cursor, "White plays", "As brancas jogam", "pt")
            save_translation(cursor, "Black plays", "Contem {chaves}", "pt")
            # 2. linha vazia depois preenchida
            save_translation(cursor, longo, "", "pt")
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[2], 1)  # chaves -> aviso

            # 3. preenchimento de vazia com traducao curta demais -> aviso
            save_translation(cursor, longo, "curta", "pt")
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[3], 1)

            # 4. edicao manual que RESOLVE o aviso
            update_translation_by_id(cursor, 2, "Sem chaves agora")
            conn.commit()
            self.assertEqual(self._flags(cursor)[2], 0)
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # 5. edicao manual que CRIA um aviso
            update_translation_by_id(cursor, 1, "{quebrado}")
            conn.commit()
            self.assertEqual(self._flags(cursor)[1], 1)
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # 6. verificar nao mexe no texto, entao nao pode mexer no flag
            antes = self._flags(cursor)
            set_translation_verified_by_id(cursor, 1, True)
            conn.commit()
            self.assertEqual(self._flags(cursor), antes)

            # 7. regras automaticas em massa
            apply_automatic_translation_updates(
                cursor,
                [("{quebrado}", "consertado")],
                apply_automatic_substitutions,
                target_language="pt",
            )
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[1], 0)

            conn.close()

    def test_backfill_fills_legacy_rows_and_counts_match_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            conn = initialize_database(db_path)
            cursor = conn.cursor()
            for i in range(30):
                trans = "Contem {chaves}" if i % 3 == 0 else f"Traducao boa {i}"
                save_translation(cursor, f"Original number {i}", trans, "pt")
            conn.commit()

            # Simula uma base antiga: coluna existe mas esta toda NULL.
            cursor.execute("UPDATE comments SET quality_warning = NULL")
            cursor.execute("PRAGMA user_version = 0")
            conn.commit()
            conn.close()

            # Reabrir dispara a migracao e o backfill.
            conn = initialize_database(db_path)
            cursor = conn.cursor()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # A contagem em SQL tem de bater com a avaliacao em Python.
            esperado = len(
                filter_quality_warning_rows(fetch_review_rows(cursor, "pt"))
            )
            self.assertEqual(
                count_review_rows(cursor, "pt", status_filter="warnings"),
                esperado,
            )
            self.assertEqual(
                get_review_status_counts(cursor, "pt")["warnings"],
                esperado,
            )

            # E a pagina do filtro so pode trazer linhas que realmente tem aviso.
            pagina = fetch_review_rows_page(
                cursor, "pt", limit=100, offset=0, status_filter="warnings"
            )
            self.assertTrue(pagina)
            self.assertTrue(all(row_has_quality_warning(row) for row in pagina))
            self.assertEqual(len(pagina), esperado)
            conn.close()

    def test_migration_runs_once_and_is_skipped_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            conn = initialize_database(db_path)
            conn.close()

            conn = initialize_database(db_path)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            # Nada a preencher numa base ja migrada.
            self.assertEqual(backfill_quality_warnings(conn), 0)
            conn.close()


class ReviewQualityTests(unittest.TestCase):
    def test_review_quality_warnings(self):
        self.assertEqual(evaluate_translation_quality("Original", ""), ["Tradução vazia."])
        self.assertIn(
            "Tradução igual ao original.",
            evaluate_translation_quality("Same text", "same text"),
        )
        self.assertIn(
            "Contém chaves { } que podem interferir no comentário PGN.",
            evaluate_translation_quality("Original text", "Texto com {chave}"),
        )
        self.assertIn(
            "Tradução muito curta em relação ao original.",
            evaluate_translation_quality("a" * 80, "curta"),
        )
        self.assertIn(
            "Tradução muito longa em relação ao original.",
            evaluate_translation_quality("a" * 40, "b" * 120),
        )
        self.assertEqual(evaluate_translation_quality("Checkmate threat", "Ameaça de mate"), [])

    def test_find_first_quality_warning(self):
        rows = [
            (1, "Checkmate threat", "Ameaça de mate", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
        ]

        found = find_first_quality_warning(rows)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 1)
        self.assertEqual(found[1][0], 2)
        self.assertIn("Tradução igual ao original.", found[2])

        found = find_first_quality_warning(rows, start_index=2)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 2)
        self.assertEqual(found[1][0], 3)
        self.assertEqual(found[2], ["Tradução vazia."])

        self.assertIsNone(find_first_quality_warning(rows, start_index=3))

    def test_quality_warning_row_filter(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
            (4, "Original text", "Texto com {chave}", 1),
        ]

        self.assertFalse(row_has_quality_warning(rows[0]))
        self.assertTrue(row_has_quality_warning(rows[1]))
        self.assertEqual([row[0] for row in filter_quality_warning_rows(rows)], [2, 3, 4])

    def test_quality_report_rows(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original text", "Texto com {chave}", 1),
        ]

        report = build_quality_report_rows(rows, "pt")

        self.assertEqual(
            QUALITY_REPORT_HEADERS,
            [
                "id",
                "target_language",
                "status",
                "warning_count",
                "warnings",
                "original_comment",
                "translated_comment",
            ],
        )
        self.assertEqual(len(report), 2)
        self.assertEqual(report[0][0], 2)
        self.assertEqual(report[0][1], "pt")
        self.assertEqual(report[0][2], "pending")
        self.assertEqual(report[0][3], 1)
        self.assertIn("igual ao original", report[0][4])
        self.assertEqual(report[1][0], 3)
        self.assertEqual(report[1][2], "verified")
        self.assertIn("chaves", report[1][4])

    def test_quality_summary(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
            (4, "Original text", "Texto com {chave}", 1),
        ]

        summary = summarize_quality_warnings(rows)

        self.assertEqual(summary["total_rows"], 4)
        self.assertEqual(summary["warning_rows"], 3)
        self.assertEqual(summary["pending_warning_rows"], 2)
        self.assertEqual(summary["verified_warning_rows"], 1)
        self.assertEqual(summary["warning_total"], 3)
        self.assertEqual(len(summary["warning_counts"]), 3)
        self.assertTrue(
            format_quality_stats(summary, "  ").startswith("  Com avisos QA: 3")
        )


class ProseQualityHeuristicsTests(unittest.TestCase):
    """Garantia Q4: as tres heuristicas de prosa e as formas novas da lista.

    Medidas contra as decisoes humanas do banco de dev (ROADMAP 28.2, camada
    1): `after`/`depois` 124/1, "Brancas" no meio 10/0, "sao melhores" 8/1.
    Juntas com a lista ampliada, a versao 2 marca 1.254 linhas da saida da
    maquina (a 1: 359) com 96 % de precisao humana. "ele" para o lado (6/5)
    ficou de fora.
    """

    def avisos(self, original, translated, source="en", target="pt"):
        return evaluate_translation_quality(original, translated, source, target)

    def test_after_without_de_is_flagged_and_de_is_not(self):
        self.assertTrue(any("sem o 'de'" in a for a in self.avisos("White is better after", "As brancas estao melhores depois")))
        self.assertEqual(self.avisos("White is better after", "As brancas estao melhores depois de"), [])
        self.assertEqual(self.avisos("White is better after", "As brancas estao melhores apos"), [])

    def test_the_adverbial_after_is_not_flagged(self):
        self.assertEqual(self.avisos("does not lose immediately after", "nao perde imediatamente depois"), [])

    def test_the_after_heuristic_is_pair_scoped(self):
        """A primeira heuristica com escopo de PAR: le o original em ingles.
        Origem nao declarada nao a desliga; uma origem que nao e ingles, sim."""
        self.assertTrue(self.avisos("White is better after", "As brancas estao melhores depois", source=""))
        self.assertEqual(self.avisos("White is better after", "As brancas estao melhores depois", source="es"), [])

    def test_capitalized_side_mid_sentence(self):
        self.assertTrue(any("mai" in a for a in self.avisos("a refutation of White's setup", "uma refutacao da configuracao das Brancas")))
        self.assertEqual(self.avisos("White's setup", "As Brancas tem uma configuracao"), [], "no inicio da frase e caixa normal")

    def test_side_are_better(self):
        self.assertTrue(any("estao" in a or "est\u00e3o" in a for a in self.avisos("Black is better", "as pretas sao melhores")))
        self.assertEqual(self.avisos("Black is better", "as pretas estao melhores"), [])

    def test_nothing_fires_outside_portuguese(self):
        for original, translated in (
            ("White is better after", "le bianche stanno meglio dopo"),
            ("a refutation of White's setup", "una confutazione delle Bianche"),
            ("Black is better", "le nere sono migliori"),
            # Texto que CASARIA os padroes do portugues: e o destino que desliga.
            ("White is better after", "as brancas estao melhores depois"),
            ("Black is better", "as pretas sao melhores"),
            ("White's setup", "a configuracao das Brancas"),
        ):
            with self.subTest(translated=translated):
                self.assertEqual(self.avisos(original, translated, target="it"), [])

    def test_the_materialized_flag_and_the_screen_agree_on_the_pair(self):
        """Garantia Q3, agora com uma heuristica que depende do PAR: a coluna
        materializada e a exibicao recebem os mesmos argumentos, entao o
        veredito e o mesmo para cada origem — inclusive onde ele muda."""
        original, translated = "White is better after", "As brancas estao melhores depois"
        for source in ("en", "", "es"):
            with self.subTest(source=source):
                self.assertEqual(
                    quality_warning_flag(original, translated, source, "pt"),
                    1 if self.avisos(original, translated, source=source) else 0,
                )
        self.assertEqual(quality_warning_flag(original, translated, "en", "pt"), 1)
        self.assertEqual(quality_warning_flag(original, translated, "es", "pt"), 0)

    def test_the_new_suspect_forms_are_shipped_and_the_rejected_ones_are_not(self):
        termos = {(t, s) for t, s, e in load_suspect_terms() if e == "pt"}
        for par in (("move", "movimento"), ("resign", "renunci"), ("check", "verific"), ("exchange sacrifice", "troca"), ("kingside", "lado do rei")):
            self.assertIn(par, termos)
        for par in (("game", "jogo"), ("move", "jogada"), ("the exchange", "troca"), ("fork", "bifurca")):
            self.assertNotIn(par, termos, "ficou de fora pela medicao")
        self.assertTrue(any("Terminologia: 'exchange sacrifice'" in a for a in self.avisos("a classic exchange sacrifice", "um classico sacrificio de troca")))
        self.assertEqual(self.avisos("to exchange the knights", "trocar os cavalos"), [], "o verbo e troca mesmo")

    def test_the_heuristics_version_moved(self):
        """Q2: mexer nas heuristicas obriga a subir a versao, senao o banco
        continua com o veredito da 1."""
        self.assertGreaterEqual(QUALITY_HEURISTICS_VERSION, 2)


class PendingOnlyQaFilterTests(unittest.TestCase):
    """Garantia F28, a metade do banco: "pending_warnings" e a fila de F7."""

    def banco(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = initialize_database(str(Path(tmp.name) / "c.db"))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        # Igual ao original => aviso nas tres; a segunda e verificada.
        for texto in ("AAA igual", "BBB igual", "CCC igual"):
            save_translation(cur, texto, texto, "pt", "en")
        cur.execute("UPDATE comments SET verified = 1 WHERE original_comment = 'BBB igual'")
        conn.commit()
        return cur

    def test_the_filter_and_the_summary_count_only_pending_warnings(self):
        cur = self.banco()
        contagens = get_review_status_counts(cur, "pt")
        self.assertEqual(contagens["warnings"], 3)
        self.assertEqual(contagens["pending_warnings"], 2)
        self.assertEqual(count_from_status_counts(contagens, "pending_warnings"), 2)
        linhas = [r[1] for r in fetch_review_rows(cur, "pt", status_filter="pending_warnings")]
        self.assertEqual(linhas, ["AAA igual", "CCC igual"])
        self.assertEqual(len(list(fetch_review_rows(cur, "pt", status_filter="warnings"))), 3, "o relatorio continua levando todas")

    def test_the_summary_still_reads_only_the_index(self):
        """22.13 de novo: a coluna nova do resumo nao pode tirar a cobertura."""
        cur = self.banco()
        sql, params = database.review_status_counts_query("pt")
        plano = " ".join(l[3] for l in cur.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall())
        self.assertIn("COVERING INDEX", plano)

    def test_find_first_quality_warning_skips_verified_on_request(self):
        pendente = (1, "AAA igual", "AAA igual", 0)
        verificada = (2, "BBB igual", "BBB igual", 1)
        rows = [verificada, pendente]
        self.assertEqual(find_first_quality_warning(rows)[0], 0)
        self.assertEqual(find_first_quality_warning(rows, include_verified=False)[0], 1)
        self.assertIsNone(find_first_quality_warning([verificada], include_verified=False))


class ChessQualityHeuristicsTests(unittest.TestCase):
    """Garantia Q1 e as demais heuristicas de xadrez (ROADMAP 16.1)."""

    def avisos(self, original, traduzida, origem=None, destino=None):
        return evaluate_translation_quality(original, traduzida, origem, destino)

    def um(self, original, traduzida, trecho, origem=None, destino=None):
        """Exige que algum aviso contenha `trecho`, e devolve esse aviso."""
        avisos = self.avisos(original, traduzida, origem, destino)
        achados = [a for a in avisos if trecho in a]
        self.assertTrue(achados, f"nenhum aviso com {trecho!r}; havia {avisos}")
        return achados[0]

    def nenhum(self, original, traduzida, trecho, origem=None, destino=None):
        avisos = self.avisos(original, traduzida, origem, destino)
        self.assertEqual(
            [a for a in avisos if trecho in a], [], f"avisos: {avisos}"
        )

    # --------------------------------------------------- Q1: lance perdido

    def test_a_move_the_translator_ate_is_a_warning(self):
        """O aviso de maior valor da secao: o texto continua lendo bem e diz
        outra coisa."""
        aviso = self.um(
            "White plays Bxf7+ and then Qd5+ wins.",
            "As brancas jogam Bxf7+ e ganham.",
            "não aparece na tradução",
        )
        self.assertIn("d5+", aviso)

    def test_a_move_the_translator_invented_is_a_warning(self):
        aviso = self.um(
            "White plays Bxf7+ and wins the game right there.",
            "As brancas jogam Bxf7+ e Dd5+ e ganham a partida ali mesmo.",
            "não está no original",
        )
        self.assertIn("d5+", aviso)

    def test_translating_the_piece_letter_is_not_a_warning(self):
        """A contraprova que faz o aviso valer: `Nf3` -> `Cf3` e o certo."""
        self.nenhum(
            "White plays Nf3 and Rd1, a good setup for the coming attack.",
            "As brancas jogam Cf3 e Td1, uma boa formação para o ataque.",
            "aparece na tradução",
        )

    def test_the_number_glued_to_the_move_is_caught(self):
        """Medido no banco de desenvolvimento: 4 dos 6 casos reais. `20 Na2` ->
        `20Ca2` deixa de ser notacao valida, e o aviso e o que faz alguem ver."""
        self.um(
            "on account of 20 Na2, winning a pawn for White in the endgame.",
            "por conta de 20Ca2, ganhando um peão para as brancas no final.",
            "não aparece na tradução",
        )

    # ------------------------------------------------ Q1: anotacao rompida

    def test_a_broken_annotation_is_a_warning(self):
        """Enquanto a mascara da secao 13 nao existia, este aviso era a rede;
        depois dela, e como se acha o legado que ja esta no banco."""
        aviso = self.um(
            "Good move {[%eval +0.35]} in this position, says the engine.",
            "Bom lance {[%eval +0. 35]} nesta posição, diz o motor.",
            "Anotação do original ausente",
        )
        self.assertIn("[%eval +0.35]", aviso)

    def test_an_intact_annotation_is_not_a_warning(self):
        self.nenhum(
            "Good move [%eval +0.35] in this position, says the engine here.",
            "Bom lance [%eval +0.35] nesta posição, diz o motor aqui.",
            "Anotação",
        )

    def test_an_annotation_that_appeared_out_of_nowhere_is_a_warning(self):
        self.um(
            "Good move in this position, or so the engine seems to believe.",
            "Bom lance [%clk 0:05:00] nesta posição, ou o motor assim acredita.",
            "Anotação na tradução",
        )

    # ------------------------------------------------- NAGs e simbolos

    def test_a_lost_nag_is_a_warning(self):
        self.um(
            "This is the critical moment of the whole game $14 for both sides.",
            "Este é o momento crítico de toda a partida para os dois lados.",
            "NAG do original ausente",
        )

    def test_a_lost_evaluation_symbol_is_a_warning(self):
        self.um(
            "White is much better here $$ and the position speaks +- for itself.",
            "As brancas estão muito melhor aqui e a posição fala por si.",
            "Símbolo de avaliação do original ausente",
        )

    def test_ordinary_question_marks_are_not_symbols(self):
        """`!` e `?` sozinhos sao pontuacao. "Is this sound?" -> "Isso e
        correto?" tem um `?` de cada lado por acidente, e uma frase que ganha ou
        perde um ponto de interrogacao e prosa normal."""
        self.nenhum(
            "Is this really the best that White can do in such a position?",
            "Será que isto é realmente o melhor que as brancas podem fazer!",
            "Símbolo de avaliação",
        )

    def test_a_longer_symbol_is_not_counted_twice(self):
        """Contando do mais curto para o mais longo, `+/-` viraria tambem um
        `+/` e todo texto com avaliacao pareceria ter simbolos a mais."""
        self.assertEqual(eval_symbols("+/-"), Counter({"+/-": 1}))
        self.assertEqual(eval_symbols("+/- +/-"), Counter({"+/-": 2}))

    # ------------------------------------------------------- sinais diretos

    def test_the_replacement_character_is_a_warning(self):
        """As garantias E4 e G2 impedem isso na leitura nova; isto acha o legado
        que ja esta gravado."""
        self.um(
            "A posi�ao das brancas e melhor aqui do que parece a primeira vista.",
            "A posição das brancas é melhor aqui do que parece à primeira vista.",
            "U+FFFD",
        )

    def test_the_batch_separator_in_the_stored_text_is_a_warning(self):
        """No texto GRAVADO ele e evidencia de um desalinhamento que a contagem
        de partes nao pegou (garantia B2)."""
        self.um(
            "First comment here about the position of the white pieces.",
            "Primeiro comentário ||| segundo comentário que vazou para cá.",
            "separador de lote",
        )

    # -------------------------------------------------------- quase-igualdade

    def test_a_translation_that_barely_changed_is_a_warning(self):
        original = (
            "The position after 15 Nf3 is balanced and both sides have chances."
        )
        self.um(original, original.replace("balanced", "balancedo"), "quase idêntica")

    def test_a_citation_that_is_almost_identical_is_not_a_warning(self):
        """O falso positivo que a medicao achou, e a razao de a conta ter dois
        passos: o `quick_ratio` da 0,953 aqui porque a citacao domina a contagem
        de caracteres, e o `ratio` ve o bloco comum e responde 0,822."""
        self.nenhum(
            "is about equal, Z. Hracek-G. Jones, Porto Carras 2011.",
            "é quase igual, Z. Hracek-G. Jones, Porto Carras 2011.",
            "quase idêntica",
        )

    def test_a_short_original_is_left_alone(self):
        """Abaixo do piso, ser quase identica e o resultado certo: nao ha o que
        traduzir numa citacao curta."""
        self.nenhum("Tilburg 1993", "Tilburgo 1993", "quase idêntica")

    def test_an_exactly_equal_translation_keeps_its_own_warning(self):
        """"Igual" e "quase igual" nao podem virar dois avisos para o mesmo
        fato."""
        texto = "The position after 15 Nf3 is balanced and both sides have chances."
        avisos = self.avisos(texto, texto)
        self.assertIn("Tradução igual ao original.", avisos)
        self.assertEqual([a for a in avisos if "quase" in a], [])

    # ----------------------------------------------------- as cinco antigas

    def test_the_five_generic_heuristics_still_answer(self):
        """A secao 16 acrescenta; nao substitui. Medido no banco de
        desenvolvimento: das 11 linhas que o `quality_warning` marcava, zero
        deixaram de ser marcadas."""
        self.assertEqual(self.avisos("qualquer", ""), ["Tradução vazia."])
        self.assertIn("igual ao original", " ".join(self.avisos("mesmo", "mesmo")))
        self.assertIn("chaves", " ".join(self.avisos("a", "b {c}")))
        longo = "palavra " * 20
        self.assertIn("muito curta", " ".join(self.avisos(longo, "curta")))
        self.assertIn("muito longa", " ".join(self.avisos(longo, longo * 3)))


class SuspectTerminologyTests(unittest.TestCase):
    """Terminologia suspeita por par de idiomas (ROADMAP 16.1, item 8)."""

    def arquivo(self, linhas):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        corpo = ",\n    ".join(repr(t) for t in linhas)
        caminho.write_text(f"termos = [\n    {corpo},\n]\n", encoding="utf-8")
        return str(caminho)

    def test_the_term_must_be_in_the_original_and_the_form_in_the_translation(self):
        """As duas condicoes juntas sao o que faz o aviso ser especifico:
        "ritmo" numa traducao e palavra comum, e so vira suspeita quando o
        original diz "tempo"."""
        caminho = self.arquivo([("tempo", "ritmo", "pt")])

        self.assertEqual(
            find_suspect_terms("loses a tempo", "perde um ritmo", "en", "pt", caminho),
            [("tempo", "ritmo")],
        )
        self.assertEqual(
            find_suspect_terms("a fast game", "um jogo de ritmo alto", "en", "pt", caminho),
            [],
            "sem o termo no original nao ha suspeita",
        )
        self.assertEqual(
            find_suspect_terms("loses a tempo", "perde um tempo", "en", "pt", caminho),
            [],
            "com a forma certa na traducao nao ha suspeita",
        )

    def test_the_suspect_form_matches_inflected(self):
        """Em portugues ela chega flexionada: "quadrado" aparece como
        "quadrados", "fixado" como "fixada"."""
        caminho = self.arquivo([("square", "quadrado", "pt")])
        self.assertEqual(
            find_suspect_terms("the squares", "os quadrados", "en", "pt", caminho),
            [("square", "quadrado")],
        )

    def test_the_term_matches_whole_words_only(self):
        """Sem a fronteira, `pin` casaria "opinion" e o aviso viraria ruido.

        A palavra do exemplo tem de conter o termo DE VERDADE. A primeira versao
        deste teste usava "opening", que nao tem "pin" nenhum — e ele passava com
        a fronteira e sem ela, o que e a definicao de nao proteger nada.
        """
        caminho = self.arquivo([("pin", "alfinete", "pt")])
        for palavra in ("opinion", "spinning"):
            with self.subTest(palavra=palavra):
                self.assertEqual(
                    find_suspect_terms(
                        f"in my {palavra}", "o alfinete", "en", "pt", caminho
                    ),
                    [],
                )
        # Contraprova: o termo sozinho continua sendo achado.
        self.assertEqual(
            find_suspect_terms("a nasty pin", "um alfinete", "en", "pt", caminho),
            [("pin", "alfinete")],
        )

    def test_the_scope_keeps_the_list_inside_its_pair(self):
        """Garantia S11: a lista de portugues nao pode acusar erro numa traducao
        para o italiano."""
        caminho = self.arquivo([("file", "arquivo", "pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", "pt", caminho),
            [("file", "arquivo")],
        )
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", "it", caminho),
            [],
        )

    def test_without_a_target_language_nothing_is_applied(self):
        """E o oposto do que `scope_matches` faz sozinho — la o destino ausente
        nao filtra nada, o que e certo para o glossario e errado aqui."""
        caminho = self.arquivo([("file", "arquivo", "pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", None, caminho),
            [],
        )
        self.assertEqual(suspect_terms_for(None, None, caminho), [])

    def test_a_pair_scope_needs_the_declared_source(self):
        caminho = self.arquivo([("file", "arquivo", "en>pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo", "en", "pt", caminho),
            [("file", "arquivo")],
        )
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo", "", "pt", caminho),
            [],
            "origem nao declarada nao satisfaz um escopo de par",
        )

    def test_a_malformed_entry_is_skipped_and_the_rest_survives(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        caminho.write_text(
            "termos = [\n"
            "    ('so', 'dois'),\n"
            "    ('', 'vazio', 'pt'),\n"
            "    ('check', 'cheque', 'pt'),\n"
            "]\n",
            encoding="utf-8",
        )
        self.assertEqual(
            load_suspect_terms(str(caminho)), [("check", "cheque", "pt")]
        )

    def test_a_broken_file_degrades_and_reports(self):
        """Ela vem com o programa, entao um defeito nela e nosso — e nao pode
        impedir o programa de funcionar nem passar calado (garantia S5)."""
        reportados = []
        anterior = set_glossary_error_handler(reportados.append)
        self.addCleanup(set_glossary_error_handler, anterior)

        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        caminho.write_text("termos = [('a',\n", encoding="utf-8")

        self.assertEqual(call_quietly(load_suspect_terms, str(caminho)), [])
        self.assertEqual(len(reportados), 1)
        self.assertIn("termos suspeitos", reportados[0])

    def test_a_missing_file_is_simply_empty(self):
        self.assertEqual(load_suspect_terms("nao-existe-em-lugar-nenhum.txt"), [])


class ShippedSuspectTermsTests(unittest.TestCase):
    """O arquivo que vem com o programa, medido no banco de desenvolvimento."""

    def setUp(self):
        self.entradas = load_suspect_terms(chess_terms._default_terms_path())

    def test_it_is_not_empty(self):
        self.assertGreater(len(self.entradas), 10)

    def test_white_and_black_cover_every_non_english_target(self):
        """O que se detecta e o termo ter ficado EM INGLES. Para 'en' nao existe:
        la "White" e a palavra certa."""
        for idioma, _nome in [(code, nome) for nome, code in LANGUAGES]:
            escopos = {
                escopo for termo, _s, escopo in self.entradas if termo == "White"
            }
            with self.subTest(idioma=idioma):
                if idioma == "en":
                    self.assertNotIn("en", escopos)
                else:
                    self.assertIn(idioma, escopos)

    def test_the_measured_pt_terms_are_there(self):
        pares_pt = {
            (termo, suspeito)
            for termo, suspeito, escopo in self.entradas
            if escopo == "pt"
        }
        for par in [
            ("check", "cheque"),
            ("file", "arquivo"),
            ("tempo", "ritmo"),
            ("square", "quadrado"),
            ("pin", "alfinete"),
            ("sound", "som"),
        ]:
            with self.subTest(par=par):
                self.assertIn(par, pares_pt)

    def test_the_two_that_the_measurement_rejected_are_absent(self):
        """`exchange` -> `troca` marcava 178 linhas e a maioria estava CERTA
        ("trocar" e a traducao boa do verbo); `rank` -> `classificacao` marcava 2
        e uma estava certa ("the rank of master player"). Sobrou `back rank`."""
        pares = {(termo, suspeito) for termo, suspeito, _e in self.entradas}
        self.assertNotIn(("exchange", "troca"), pares)
        self.assertNotIn(("rank", "classificação"), pares)
        self.assertIn(("back rank", "classificação"), pares)

    def test_no_entry_is_its_own_correct_translation(self):
        """Uma entrada em que a forma suspeita e a certa marcaria toda traducao
        boa. So `White`/`Black` sao iguais dos dois lados, e ai o suspeito e
        justamente NAO ter mudado."""
        for termo, suspeito, escopo in self.entradas:
            if termo in ("White", "Black"):
                self.assertEqual(termo, suspeito)
                continue
            with self.subTest(termo=termo):
                self.assertNotEqual(termo.casefold(), suspeito.casefold())

    def test_a_real_sentence_from_the_book_is_flagged(self):
        """Uma das 321 linhas que o filtro "Avisos QA" nao mostrava."""
        avisos = evaluate_translation_quality(
            "White has more space and control of the only entirely open file.",
            "As brancas têm mais espaço e controle do único arquivo aberto.",
            "en",
            "pt",
        )
        self.assertTrue(
            any("'file' no original e 'arquivo'" in a for a in avisos), avisos
        )


class QualityHeuristicsVersionTests(unittest.TestCase):
    """Garantia Q2: as heuristicas tem versao, e muda-las reavalia o banco."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_a_fresh_database_records_the_current_version_when_reevaluated(self):
        conn = self.banco()
        self.assertEqual(get_quality_heuristics_version(conn), 0)
        self.assertFalse(quality_heuristics_are_current(conn))

        set_db_metadata(conn, QUALITY_VERSION_KEY, QUALITY_HEURISTICS_VERSION)
        self.assertTrue(quality_heuristics_are_current(conn))

    def test_a_missing_mark_reads_as_zero(self):
        """Zero e a resposta certa: um banco gravado antes desta versao teve os
        avisos calculados pelas cinco genericas, e nao ha como distinguir isso de
        "nunca calculado" — as duas pedem a mesma acao."""
        conn = self.banco()
        self.assertEqual(get_quality_heuristics_version(conn), 0)

    def test_a_garbage_mark_reads_as_zero_too(self):
        conn = self.banco()
        set_db_metadata(conn, QUALITY_VERSION_KEY, "nao e numero")
        self.assertEqual(get_quality_heuristics_version(conn), 0)

    def test_metadata_survives_a_reopen(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = str(Path(sandbox.name) / "cache.db")

        conn = initialize_database(db_path)
        set_db_metadata(conn, QUALITY_VERSION_KEY, 7)
        conn.commit()
        conn.close()

        conn = initialize_database(db_path)
        try:
            self.assertEqual(get_quality_heuristics_version(conn), 7)
        finally:
            conn.close()

    def test_reading_the_mark_tolerates_a_database_without_the_table(self):
        """Um banco antes da migracao 6 nao tem `db_metadata`, e perguntar pela
        marca nao pode levantar."""
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = Path(sandbox.name) / "antigo.db"
        _schema3_database(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            self.assertIsNone(get_db_metadata(conn, QUALITY_VERSION_KEY))
            self.assertEqual(get_quality_heuristics_version(conn), 0)
        finally:
            conn.close()

    def test_the_backfill_does_not_advance_the_version(self):
        """E a diferenca entre ele e a reavaliacao: preencher `NULL` bastava
        enquanto o unico jeito de a coluna estar errada fosse nao existir."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "orig", "trans", "pt", "en")
        cur.execute("UPDATE comments SET quality_warning = NULL")
        conn.commit()

        self.assertEqual(backfill_quality_warnings(conn), 1)
        self.assertEqual(get_quality_heuristics_version(conn), 0)


class QualityReevaluationTests(unittest.TestCase):
    """A reavaliacao em massa: o que ela muda, o que ela relata, o que ela nao grava."""

    def banco(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.db_path = str(Path(self.sandbox.name) / "cache.db")
        conn = initialize_database(self.db_path)
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        conn.commit()
        return conn

    def flags(self, conn):
        return dict(
            conn.execute("SELECT original_comment, quality_warning FROM comments")
        )

    def test_a_stale_verdict_is_corrected(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        stats = reevaluate_quality_warnings(conn)

        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(
            self.flags(conn), {"White plays Nf3.": 0, "The open file.": 1}
        )

    def test_running_twice_changes_nothing_the_second_time(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        reevaluate_quality_warnings(conn)
        self.assertEqual(reevaluate_quality_warnings(conn)["changed"], 0)

    def test_the_pair_comes_from_the_row_and_not_from_an_argument(self):
        """O banco tem pares diferentes na mesma tabela, e a terminologia e
        escopada por idioma: avaliar tudo com um par so acusaria erro onde nao
        ha."""
        conn = self.banco()
        cur = conn.cursor()
        # Mesmo texto, destino italiano: a lista de portugues nao vale aqui.
        save_translation(cur, "The open file.", "O arquivo aberto.", "it", "en")
        conn.commit()

        reevaluate_quality_warnings(conn)

        self.assertEqual(
            conn.execute(
                "SELECT quality_warning FROM comments"
                " WHERE target_language = 'it'"
            ).fetchone()[0],
            0,
        )

    def test_progress_is_reported_and_ends_at_the_total(self):
        conn = self.banco()
        marcos = []
        reevaluate_quality_warnings(conn, progress_callback=lambda f, t: marcos.append((f, t)))
        self.assertEqual(marcos[0], (0, 2))
        self.assertEqual(marcos[-1], (2, 2))

    def test_cancelling_raises_and_leaves_the_rest_alone(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        with self.assertRaises(QualityReevaluationCanceled):
            reevaluate_quality_warnings(conn, batch_size=1, should_cancel=lambda: True)

    def test_an_empty_database_is_scanned_without_error(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "vazio.db"))
        try:
            self.assertEqual(
                reevaluate_quality_warnings(conn), {"scanned": 0, "changed": 0}
            )
        finally:
            conn.close()


class QualityColumnMatchesTheScreenTests(unittest.TestCase):
    """Garantia R6 com as heuristicas novas: a coluna nao pode divergir da tela.

    A terminologia depende do par de idiomas, entao o par tem de chegar aos DOIS
    caminhos — a gravacao (que materializa o bit) e a leitura (que mostra as
    frases). Se um deles avaliar sem par, a contagem do rodape passa a nao bater
    com o que a lista exibe, e nada quebra.
    """

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def linhas(self, conn, destino="pt"):
        return fetch_review_rows(conn.cursor(), destino)

    def test_the_saved_flag_agrees_with_the_row_evaluation(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        conn.commit()

        for row in self.linhas(conn):
            with self.subTest(original=row[1]):
                gravado = conn.execute(
                    "SELECT quality_warning FROM comments WHERE id = ?", (row[0],)
                ).fetchone()[0]
                self.assertEqual(gravado, 1 if row_has_quality_warning(row) else 0)

    def test_the_row_carries_the_pair_at_the_end(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        conn.commit()

        row = self.linhas(conn)[0]
        self.assertEqual(row_language_pair(row), ("en", "pt"))

    def test_a_row_without_the_pair_is_still_evaluated(self):
        """Tolerante de proposito: uma tupla de sete campos continua sendo
        avaliada, so sem a parte de terminologia."""
        curta = (1, "The open file.", "O arquivo aberto.", 0, None, None, None)
        self.assertEqual(row_language_pair(curta), (None, None))
        self.assertFalse(row_has_quality_warning(curta))

    def test_editing_a_translation_keeps_the_flag_in_agreement(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "A coluna aberta.", "pt", "en")
        conn.commit()
        row_id = self.linhas(conn)[0][0]

        # A edicao introduz o erro de terminologia: o bit tem de acompanhar.
        update_translation_by_id(cur, row_id, "O arquivo aberto.")
        conn.commit()

        row = self.linhas(conn)[0]
        gravado = conn.execute(
            "SELECT quality_warning FROM comments WHERE id = ?", (row_id,)
        ).fetchone()[0]
        self.assertEqual(gravado, 1)
        self.assertTrue(row_has_quality_warning(row))

    def test_the_counts_agree_with_the_rows(self):
        """A agregada de status conta pela coluna; a lista avalia em Python. Os
        dois numeros tem de ser o mesmo."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        save_translation(cur, "A nasty check.", "Um cheque desagradável.", "pt", "en")
        conn.commit()

        resumo = get_review_status_counts(cur, "pt")
        self.assertEqual(
            resumo["warnings"],
            len(filter_quality_warning_rows(self.linhas(conn))),
        )


if __name__ == "__main__":
    unittest.main()
