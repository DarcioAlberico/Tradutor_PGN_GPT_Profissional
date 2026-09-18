"""O glossario: regras, escopo, prioridade, conflitos, semente, trocas repetidas.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import os
import re
import sqlite3
import types
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tradutor_pgn import (
    db_tools,
    glossario,
    repeated_edits,
)
from tradutor_pgn.database import (
    fetch_file_edit_events,
    AutomaticRulesCanceled,
    apply_automatic_translation_updates,
    initialize_database,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    VersionedRules,
    build_glossary_lookup,
    order_rules_by_specificity,
    versioned_rules,
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    add_glossary_entry,
    glossary_entry_priority,
    promote_glossary_rule,
    rule_priority,
    normalize_glossary_priority,
    add_to_glossary,
    analyze_glossary_csv_import,
    apply_automatic_substitutions,
    apply_all_substitutions,
    apply_substitution,
    clean_comment_for_translation,
    deduplicate_glossary_entries,
    delete_glossary_entry,
    delete_glossary_entry_by_pair,
    glossary_entry_pair,
    case_adjusted_replacement,
    export_glossary_csv,
    find_glossary_entry_index,
    read_glossary_csv,
    import_glossary_csv,
    initialize_glossary_database,
    find_glossary_matches,
    find_glossary_suggestions,
    load_glossary_entries,
    load_glossary_entry_details,
    load_glossary_entry_details_from_db,
    load_glossary_entries_from_db,
    load_cleanup_substitutions,
    load_automatic_substitutions,
    load_suggestion_substitutions,
    load_interactive_substitutions,
    load_substitutions,
    rebuild_glossary_database,
    restore_glossary_from_backup,
    save_glossary_entries,
    sync_glossary_database,
    update_glossary_entry,
    update_glossary_entry_by_entry,
    validate_glossary_entry,
)
from tradutor_pgn.pgn_utils import (
    extract_comments_from_file,
    generate_translated_pgn,
)
from tradutor_pgn.db_tools import (
    analyze_database_automatic_rules,
    apply_database_automatic_rules,
)
from tradutor_pgn.glossary_editor import (
    build_glossary_diagnostics,
    glossary_counts,
    glossary_filter_indices,
    sort_glossary_indices,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    SynchronousProgress,
    call_quietly,
    com_prioridade,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class GlossaryResetCountsTests(unittest.TestCase):
    """Garantia S16: o dialogo de zerar conta o que apaga (ROADMAP 22.12).

    `len(app.glossary_substitutions)` conta a lista APLICAVEL, que e outra coisa:
    expande `@casa@` (uma linha vira 64 regras), soma as da semente — que zerar
    nao apaga — e exclui as de limpeza, que zerar apaga. Medido no glossario
    real: 5.910 entradas no arquivo, 7.325 anunciadas.
    """

    def test_the_description_names_each_type(self):
        self.assertEqual(
            db_tools.describe_glossary_types(
                {"suggestion": 5674, "automatic": 186, "cleanup": 50}
            ),
            "5674 sugestões, 186 automáticas e 50 limpezas",
        )

    def test_a_type_that_does_not_exist_is_not_mentioned(self):
        """"0 limpezas" num glossario que nunca teve uma e ruido."""
        self.assertEqual(
            db_tools.describe_glossary_types({"suggestion": 2}), "2 sugestões"
        )

    def test_the_singular_is_the_singular(self):
        self.assertEqual(
            db_tools.describe_glossary_types({"cleanup": 1}), "1 limpeza"
        )

    def test_an_empty_glossary_says_so(self):
        self.assertEqual(db_tools.describe_glossary_types({}), "nenhuma regra")

    def test_the_count_is_of_the_file_and_not_of_the_applicable_rules(self):
        """A linha com `@casa@` vale 64 regras na aplicacao e UMA no arquivo."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("@casa@-torre", "torre de @casa@", "suggestion"),
                    ("  x  ", "y", "cleanup"),
                ],
                str(caminho),
                create_backup=False,
            )

            total, por_tipo = db_tools.count_glossary_entries_by_type(str(caminho))

            self.assertEqual(total, 2)
            self.assertEqual(por_tipo, {"suggestion": 1, "cleanup": 1})
            # A ancora: a lista aplicavel da 64 + 0 (limpeza nao e interativa).
            aplicaveis = load_interactive_substitutions(str(caminho))
            self.assertEqual(len(aplicaveis), 64)


class AutomaticRulesSinglePassTests(unittest.TestCase):
    """Item 2.7: uma passagem para aplicar, com progresso e cancelamento.

    `apply_automatic_translation_updates` comecava chamando
    `analyze_automatic_translation_updates` — que percorre a tabela inteira
    aplicando as regras — e so entao percorria tudo de novo para gravar. Com a
    previa que a interface ja calcula, um clique custava tres passagens: 38,1 s
    no banco real, com a janela travada.
    """

    REGRAS = [("rainha", "dama"), ("torre", "roque")]

    def _semear(self, db_path, linhas=40):
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        for indice in range(linhas):
            # Metade muda, metade nao: separa "varreu" de "alterou".
            texto = "A rainha avanca" if indice % 2 == 0 else "O bispo avanca"
            save_translation(cursor, f"orig {indice}", texto, "pt")
        conn.commit()
        conn.close()
        return linhas

    def _contador(self):
        """Envolve a aplicacao de regras contando quantas vezes ela roda."""
        chamadas = []

        def contando(texto, regras):
            chamadas.append(texto)
            return apply_all_substitutions(texto, regras)

        return chamadas, contando

    def test_applying_runs_the_rules_once_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            linhas = self._semear(db_path)
            chamadas, contando = self._contador()

            conn = initialize_database(str(db_path))
            try:
                stats = apply_automatic_translation_updates(
                    conn.cursor(),
                    self.REGRAS,
                    contando,
                    target_language="pt",
                )
                conn.commit()
            finally:
                conn.close()

        self.assertEqual(stats["scanned"], linhas)
        self.assertEqual(stats["changed"], linhas // 2)
        self.assertEqual(
            len(chamadas),
            linhas,
            "as regras foram aplicadas mais de uma vez por linha: "
            "a passagem de analise voltou para dentro da de escrita",
        )

    def test_applying_reports_progress_and_keeps_the_totals_honest(self):
        progresso = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            linhas = self._semear(db_path)

            conn = initialize_database(str(db_path))
            try:
                stats = apply_automatic_translation_updates(
                    conn.cursor(),
                    self.REGRAS,
                    apply_all_substitutions,
                    target_language="pt",
                    progress_callback=lambda feito, total: progresso.append((feito, total)),
                )
                conn.commit()
            finally:
                conn.close()

        self.assertTrue(progresso)
        self.assertEqual(progresso[0], (0, linhas))
        self.assertEqual(progresso[-1], (linhas, linhas))
        self.assertTrue(
            all(0 <= feito <= total == linhas for feito, total in progresso),
            f"progresso incoerente: {progresso}",
        )
        self.assertEqual(stats["scanned"], linhas)

    def test_canceling_leaves_the_database_untouched(self):
        """Cancelar no meio nao pode deixar metade das traducoes alteradas."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            self._semear(db_path, linhas=600)

            def antes():
                conn = sqlite3.connect(str(db_path))
                try:
                    return dict(
                        conn.execute(
                            "SELECT id, translated_comment FROM comments"
                        ).fetchall()
                    )
                finally:
                    conn.close()

            original = antes()

            vistas = {"n": 0}

            def cancelar_depois_de_algumas():
                vistas["n"] += 1
                return vistas["n"] > 1  # cancela cedo, com escritas ja feitas

            with self.assertRaises(AutomaticRulesCanceled):
                apply_database_automatic_rules(
                    str(db_path),
                    target_language="pt",
                    automatic_rules=self.REGRAS,
                    backup_dir=str(tmp_path / "backups"),
                    should_cancel=cancelar_depois_de_algumas,
                )

            self.assertEqual(
                antes(),
                original,
                "o rollback devia ter desfeito as alteracoes ja gravadas",
            )


class GlossaryTests(unittest.TestCase):
    def test_load_and_append_glossary_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text(
                "substituicoes = [\n"
                "    ('foo', 'bar'),\n"
                "]\n",
                encoding="utf-8",
            )

            self.assertEqual(call_quietly(load_substitutions, str(glossary)), [("foo", "bar")])
            self.assertTrue(add_to_glossary("baz", "qux", str(glossary)))
            self.assertIn(("baz", "qux"), call_quietly(load_substitutions, str(glossary)))

    def test_load_glossary_accepts_accented_variable_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text(
                "substituições = [\n"
                "    ('mate threat', 'ameaça de mate'),\n"
                "]\n",
                encoding="utf-8",
            )

            self.assertEqual(
                call_quietly(load_substitutions, str(glossary)),
                [("mate threat", "ameaça de mate")],
            )

    def test_save_glossary_entries_creates_backup_and_persists_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            backup_dir = tmp_path / "backups"
            glossary.write_text(
                "substituicoes = [\n"
                "    ('old', 'entry'),\n"
                "]\n",
                encoding="utf-8",
            )

            result = save_glossary_entries(
                [("mate threat", "ameaça de mate"), ("bad move", "lance ruim")],
                str(glossary),
                backup_dir=str(backup_dir),
                timestamp="20260101-120000",
            )

            backup_path = Path(result["backup_path"])
            self.assertTrue(backup_path.exists())
            self.assertIn("('old', 'entry')", backup_path.read_text(encoding="utf-8"))
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("mate threat", "ameaça de mate"), ("bad move", "lance ruim")],
            )

    def test_glossary_crud_operations_update_persistent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("foo", "bar"), ("bad move", "lance ruim")],
                str(glossary),
                create_backup=False,
            )

            update_stats = update_glossary_entry(
                1,
                "good move",
                "bom lance",
                str(glossary),
                timestamp="20260101-120000",
            )
            self.assertEqual(update_stats["status"], "updated")
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("foo", "bar"), ("good move", "bom lance")],
            )

            delete_stats = delete_glossary_entry(
                0,
                str(glossary),
                timestamp="20260101-120001",
            )
            self.assertEqual(delete_stats["removed"], ("foo", "bar"))
            self.assertEqual(load_glossary_entries(str(glossary)), [("good move", "bom lance")])

            add_stats = add_glossary_entry(
                "zugzwang",
                "zugzwang",
                str(glossary),
                timestamp="20260101-120002",
            )
            self.assertEqual(add_stats["status"], "inserted")
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("good move", "bom lance"), ("zugzwang", "zugzwang")],
            )

            unchanged_stats = add_glossary_entry("zugzwang", "zugzwang", str(glossary))
            self.assertEqual(unchanged_stats["status"], "unchanged")

    def test_glossary_rule_types_are_persisted_without_breaking_pair_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"
            csv_path = tmp_path / "glossario.csv"

            save_glossary_entries(
                [
                    ("mate threat", "ameaca de mate"),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            self.assertEqual(
                load_glossary_entries(str(glossary), db_path=str(glossary_db)),
                [
                    ("mate threat", "ameaca de mate"),
                    ("== EndSquare ==", ""),
                    ("rainha", "dama"),
                ],
            )
            self.assertEqual(
                load_glossary_entry_details(str(glossary), db_path=str(glossary_db)),
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )
            self.assertEqual(
                load_glossary_entry_details_from_db(str(glossary_db)),
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

            add_glossary_entry(
                "queen",
                "dama",
                str(glossary),
                rule_type="automatica",
            )
            update_glossary_entry(
                0,
                "mate threat",
                "ameaca de mate",
                str(glossary),
                rule_type=GLOSSARY_RULE_CLEANUP,
            )
            self.assertEqual(
                load_glossary_entry_details(str(glossary), prefer_db=False),
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_CLEANUP),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                    ("queen", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

            export_glossary_csv(str(csv_path), path=str(glossary))
            self.assertIn(
                "original,replacement,type,priority",
                csv_path.read_text(encoding="utf-8-sig"),
            )

    def test_cleanup_rules_are_separate_from_suggestions_and_allow_empty_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("rainha", "dama"),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("== StartSquare ==", "", GLOSSARY_RULE_CLEANUP),
                ],
                str(glossary),
                create_backup=False,
            )

            self.assertEqual(load_substitutions(str(glossary)), [("rainha", "dama")])
            self.assertEqual(load_automatic_substitutions(str(glossary)), [])
            self.assertEqual(
                load_cleanup_substitutions(str(glossary)),
                [("== EndSquare ==", ""), ("== StartSquare ==", "")],
            )
            self.assertNotIn(
                "Texto de substituição vazio.",
                validate_glossary_entry(
                    "== EndSquare ==",
                    "",
                    rule_type=GLOSSARY_RULE_CLEANUP,
                ),
            )
            self.assertEqual(
                clean_comment_for_translation(
                    "White plays == StartSquare == e4 == EndSquare ==",
                    load_cleanup_substitutions(str(glossary)),
                ),
                "White plays e4",
            )
            self.assertEqual(
                clean_comment_for_translation(
                    "== StartSquare == == EndSquare ==",
                    load_cleanup_substitutions(str(glossary)),
                ),
                "",
            )

    def test_automatic_rules_are_loaded_and_applied_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("file", "coluna"),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                    ("mate", "xeque-mate", GLOSSARY_RULE_AUTOMATIC),
                ],
                str(glossary),
                create_backup=False,
            )

            self.assertEqual(load_substitutions(str(glossary)), [("file", "coluna")])
            self.assertEqual(
                load_automatic_substitutions(str(glossary)),
                [("rainha", "dama"), ("mate", "xeque-mate")],
            )
            self.assertEqual(
                load_interactive_substitutions(str(glossary)),
                [
                    ("file", "coluna"),
                    ("rainha", "dama"),
                    ("mate", "xeque-mate"),
                ],
            )
            self.assertEqual(
                apply_automatic_substitutions(
                    "A rainha ameaca mate, mas rainhas ficam.",
                    load_automatic_substitutions(str(glossary)),
                ),
                "A dama ameaca xeque-mate, mas rainhas ficam.",
            )
            self.assertEqual(
                apply_automatic_substitutions(
                    "Cavaleiro CAVALEIRO cavaleiro.",
                    [("cavaleiro", "cavalo")],
                ),
                "Cavalo CAVALO cavalo.",
            )

    def test_glossary_validation_and_deduplication(self):
        entries = [
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça direta"),
        ]

        self.assertEqual(
            deduplicate_glossary_entries(entries),
            [("mate threat", "ameaça de mate"), ("mate threat", "ameaça direta")],
        )
        self.assertIn(
            "Entrada duplicada.",
            validate_glossary_entry(
                "mate threat",
                "ameaça de mate",
                entries,
                current_index=2,
            ),
        )
        self.assertIn(
            "Mesmo original com substituição diferente.",
            validate_glossary_entry("mate threat", "outra", entries),
        )
        self.assertIn("Texto original vazio.", validate_glossary_entry("", "x"))
        self.assertIn(
            "Entradas não podem conter quebras de linha.",
            validate_glossary_entry("a\nb", "x"),
        )

    def test_glossary_suggestions_respect_word_boundaries(self):
        substitutions = [
            ("for", "para"),
            ("branca", "brancas"),
            ("brancas joga", "brancas jogam"),
            (", as brancas joga", ", as brancas jogam"),
        ]
        text = "; as brancas jogaram de forma consistente."

        self.assertEqual(find_glossary_matches(text, "for"), [])
        self.assertEqual(find_glossary_matches(text, "branca"), [])
        self.assertEqual(find_glossary_matches(text, "brancas joga"), [])
        self.assertEqual(find_glossary_suggestions(text, substitutions), [])

        text = "for branca brancas joga, as brancas joga"
        # Garantia S3: as sugestoes vem da mais especifica para a mais generica,
        # que e a ordem em que serao aplicadas. Assim uma regra curta nao consome
        # o trecho que uma regra longa pretendia casar, e o corte por
        # max_suggestions descarta as genericas, nao as especificas.
        self.assertEqual(
            find_glossary_suggestions(text, substitutions),
            [
                (", as brancas joga", ", as brancas jogam"),
                ("brancas joga", "brancas jogam"),
                ("branca", "brancas"),
                ("for", "para"),
            ],
        )
        self.assertEqual(find_glossary_matches("Cavaleiro", "cavaleiro"), [(0, 9)])
        self.assertEqual(
            find_glossary_suggestions("Cavaleiro ativo", [("cavaleiro", "cavalo")]),
            [("cavaleiro", "cavalo")],
        )
        self.assertEqual(apply_substitution("forma for", "for", "para"), "forma para")
        self.assertEqual(apply_substitution("forma", "for", "para"), "forma")
        self.assertEqual(
            apply_all_substitutions("forma for branca", [("for", "para"), ("branca", "brancas")]),
            "forma para brancas",
        )

    def test_specific_rule_wins_over_generic_rule_regardless_of_file_order(self):
        # Garantia S3: a regra curta nao pode consumir o texto que a longa casaria.
        rules = [
            ("verificação", "xeque"),
            ("da verificação intermediária", "do xeque intermediário"),
        ]
        text = "Ele saiu da verificação intermediária com vantagem."

        self.assertEqual(
            apply_all_substitutions(text, rules),
            "Ele saiu do xeque intermediário com vantagem.",
        )
        # Inverter a ordem no arquivo nao pode mudar o resultado.
        self.assertEqual(
            apply_all_substitutions(text, list(reversed(rules))),
            "Ele saiu do xeque intermediário com vantagem.",
        )

        # Caso real do glossario: 'Cavaleiros' nao pode encobrir a regra completa.
        chess_rules = [
            ("Cavaleiros", "Cavalos"),
            ("Jogo dos Três Cavaleiros", "Partida dos Três Cavalos"),
        ]
        self.assertEqual(
            apply_all_substitutions("Jogo dos Três Cavaleiros é classico", chess_rules),
            "Partida dos Três Cavalos é classico",
        )

        # Quem precisar da ordem literal do arquivo continua podendo pedi-la.
        self.assertEqual(
            apply_all_substitutions(text, rules, order_by_specificity=False),
            "Ele saiu da xeque intermediária com vantagem.",
        )

    def test_replaced_text_is_frozen_against_contradictory_rules(self):
        # Caso real do glossario: duas regras que se desfazem uma a outra.
        rules = [
            ("Rei das brancas estão", "Rei das brancas está"),
            ("brancas está", "brancas estão"),
        ]
        # A regra especifica entrega o que declarou; a generica nao reverte.
        self.assertEqual(
            apply_all_substitutions("Rei das brancas estão", rules),
            "Rei das brancas está",
        )
        # E o resultado nao depende da ordem em que foram digitadas no arquivo.
        self.assertEqual(
            apply_all_substitutions("Rei das brancas estão", list(reversed(rules))),
            "Rei das brancas está",
        )
        # A regra generica continua valendo onde a especifica nao alcanca.
        self.assertEqual(
            apply_all_substitutions("As brancas está bem", rules),
            "As brancas estão bem",
        )
        # O encadeamento antigo continua disponivel para quem precisar.
        self.assertEqual(
            apply_all_substitutions(
                "Rei das brancas estão", rules, protect_replacements=False
            ),
            "Rei das brancas estão",
        )

    def test_ordering_cache_never_changes_the_result(self):
        """Item 2.10: a ordenacao virou memorizada — nao pode mudar nada.

        S3 depende inteiramente desta ordem. Um cache que devolva a lista errada,
        ou que se deixe corromper por quem mutar o resultado, quebra a garantia
        de forma dificil de perceber: as regras continuam sendo aplicadas, so que
        na ordem errada.
        """
        regras = [
            ("verificacao", "xeque"),
            ("da verificacao intermediaria", "do xeque intermediario"),
            ("torre", "roque"),
            ("rei", "rei"),
        ]
        outras = [("a", "b"), ("ccc", "d")]

        esperado = [
            ("da verificacao intermediaria", "do xeque intermediario"),
            ("verificacao", "xeque"),
            ("torre", "roque"),
            ("rei", "rei"),
        ]
        self.assertEqual(order_rules_by_specificity(regras), esperado)
        # Segunda chamada: agora vem do cache.
        self.assertEqual(order_rules_by_specificity(regras), esperado)
        # Uma lista diferente nao pode receber o resultado da anterior.
        self.assertEqual(
            order_rules_by_specificity(outras),
            [("ccc", "d"), ("a", "b")],
        )
        self.assertEqual(order_rules_by_specificity(regras), esperado)

        # Mutar o resultado nao pode contaminar a proxima chamada.
        devolvido = order_rules_by_specificity(regras)
        devolvido.append(("intruso", "x"))
        devolvido[0] = ("trocado", "y")
        self.assertEqual(order_rules_by_specificity(regras), esperado)

        # Uma lista com o MESMO conteudo, mas objeto diferente, e equivalente.
        self.assertEqual(order_rules_by_specificity(list(regras)), esperado)

        # E o conteudo e o que decide: mudar uma regra muda a ordem.
        # O padrao precisa ser mais longo que os 28 caracteres de
        # "da verificacao intermediaria" para assumir o primeiro lugar.
        mais_longa = ("uma regra com o padrao bem mais longo que os outros", "x")
        alteradas = list(regras)
        alteradas[2] = mais_longa
        self.assertGreater(len(mais_longa[0]), len("da verificacao intermediaria"))
        self.assertEqual(order_rules_by_specificity(alteradas)[0], mais_longa)

    def test_order_rules_by_specificity_is_stable_for_equal_lengths(self):
        rules = [("aa", "1"), ("bb", "2"), ("cccc", "3"), ("dd", "4")]
        self.assertEqual(
            order_rules_by_specificity(rules),
            [("cccc", "3"), ("aa", "1"), ("bb", "2"), ("dd", "4")],
        )

    def test_glossary_matches_never_overlap(self):
        # Garantia S1: nenhum caractere fora de um match pode desaparecer.
        for text, orig, new, expected in (
            ("de de de", "de de", "de", "de de"),
            ("com com com", "com com", "com", "com com"),
            ("em em em", "em em", "em", "em em"),
        ):
            matches = find_glossary_matches(text, orig)
            for (_, first_end), (second_start, _) in zip(matches, matches[1:]):
                self.assertLessEqual(first_end, second_start)
            self.assertEqual(apply_all_substitutions(text, [(orig, new)]), expected)

        # Duas ocorrencias realmente separadas continuam sendo substituidas.
        self.assertEqual(
            apply_all_substitutions("de de x de de", [("de de", "de")]),
            "de x de",
        )

    def test_glossary_matching_survives_characters_whose_lowercase_grows(self):
        # Garantia S2: len('İ'.lower()) == 2; os indices tem de ser do texto original.
        self.assertEqual(len("İ".lower()), 2)

        text = "İstanbul rook attack"
        matches = find_glossary_matches(text, "rook")
        self.assertEqual(len(matches), 1)
        start, end = matches[0]
        self.assertEqual(text[start:end], "rook")
        self.assertEqual(
            apply_all_substitutions(text, [("rook", "torre")]),
            "İstanbul torre attack",
        )

        # Regra que comeca com caractere nao-alfanumerico nao pode comer vizinhos.
        self.assertEqual(
            apply_all_substitutions("İ a -fileira, ok", [("-fileira", "-coluna")]),
            "İ a -coluna, ok",
        )

    def test_delete_by_pair_removes_the_chosen_entry_even_with_duplicates(self):
        # Garantia S6: excluir por indice quebra quando a lista exibida e
        # deduplicada e a exclusao opera sobre a lista completa do arquivo.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("a", "b"), ("a", "b"), ("king", "rei"), ("queen", "dama")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            def pares(deduplicate):
                return [
                    glossary_entry_pair(entry)
                    for entry in load_glossary_entry_details(
                        str(glossary), deduplicate=deduplicate, prefer_db=False
                    )
                ]

            # A duplicata faz as duas listas terem tamanhos diferentes: e a
            # condicao que provocava a exclusao errada.
            self.assertEqual(len(pares(False)), 4)
            self.assertEqual(len(pares(True)), 3)

            result = delete_glossary_entry_by_pair(
                "king", "rei", str(glossary), backup_dir=None
            )
            self.assertIsNotNone(result)
            self.assertEqual(result["removed"], ("king", "rei"))

            restante = pares(False)
            self.assertNotIn(("king", "rei"), restante)
            # Nada mais pode ter sumido junto.
            self.assertEqual(restante, [("a", "b"), ("a", "b"), ("queen", "dama")])

            # Par inexistente nao altera o arquivo e sinaliza com None.
            self.assertIsNone(
                delete_glossary_entry_by_pair(
                    "nao", "existe", str(glossary), backup_dir=None
                )
            )
            self.assertEqual(pares(False), restante)

    def test_entries_are_stored_without_edge_whitespace(self):
        # Um espaco no fim do padrao e consumido pelo casamento mas nao devolvido
        # pela substituicao, colando duas palavras no texto final.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("rook", "torre")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            add_glossary_entry(
                " a-coluna ", " coluna a ", str(glossary), backup_dir=None
            )

            pares = [
                glossary_entry_pair(entry)
                for entry in load_glossary_entry_details(
                    str(glossary), deduplicate=False, prefer_db=False
                )
            ]
            self.assertIn(("a-coluna", "coluna a"), pares)
            for orig, new in pares:
                self.assertEqual(orig, orig.strip())
                self.assertEqual(new, new.strip())

            # E o efeito pratico: a regra normalizada nao cola as palavras.
            self.assertEqual(
                apply_all_substitutions(
                    "na a-coluna aberta", [("a-coluna", "coluna a")]
                ),
                "na coluna a aberta",
            )
            # Comportamento antigo, para deixar o defeito explicito no teste.
            self.assertEqual(
                apply_all_substitutions(
                    "na a-coluna aberta", [(" a-coluna ", " coluna a")]
                ),
                "na coluna aaberta",
            )

    def test_validation_lookup_matches_full_scan(self):
        # O indice existe por desempenho; nao pode mudar o resultado.
        entries = [
            ("rook", "torre"),
            ("Rook", "Torre"),
            ("pawn", "peão"),
            ("rook", "torre de rei"),
            ("queen", "dama"),
        ]
        lookup = build_glossary_lookup(entries)

        casos = [
            ("rook", "torre"),          # duplicata exata
            ("rook", "outra coisa"),    # mesmo original, substituicao diferente
            ("queen", "dama"),          # duplicata
            ("bishop", "bispo"),        # inedito
            ("Rook", "Torre"),          # sensivel a caixa
            ("", "vazio"),              # original vazio
        ]
        for orig, new in casos:
            for current_index in (None, 0, 3):
                self.assertEqual(
                    validate_glossary_entry(
                        orig, new, entries, current_index=current_index
                    ),
                    validate_glossary_entry(
                        orig,
                        new,
                        current_index=current_index,
                        existing_lookup=lookup,
                    ),
                    f"divergiu em {orig!r}->{new!r} (current_index={current_index})",
                )

    def test_csv_import_analysis_detects_duplicates_within_the_same_file(self):
        # A deduplicacao interna passou a usar um set; o resultado tem de ser
        # o mesmo de antes, inclusive para linhas repetidas dentro do CSV.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre")],
                str(glossary),
                create_backup=False,
                db_path=str(tmp_path / "glossario.db"),
            )

            csv_path = tmp_path / "import.csv"
            csv_path.write_text(
                "original,replacement,type\n"
                "rook,torre,suggestion\n"          # ja existe -> duplicata
                "knight,cavalo,suggestion\n"       # nova
                "knight,cavalo,suggestion\n"       # repetida no proprio CSV
                "bishop,,suggestion\n"             # invalida
                "pawn,peão,suggestion\n",          # nova
                encoding="utf-8-sig",
            )

            stats = analyze_glossary_csv_import(str(glossary), str(csv_path))
            self.assertEqual(stats["total_rows"], 5)
            self.assertEqual(stats["inserted"], 2)
            self.assertEqual(stats["duplicates"], 2)
            self.assertEqual(stats["invalid"], 1)
            self.assertEqual(
                [(o, n) for o, n, _t, _p in stats["entries"]],
                [("knight", "cavalo"), ("pawn", "peão")],
            )

    def test_glossary_is_independent_from_translation_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            db_path = tmp_path / "traducoes.db"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("knight fork", "garfo de cavalo")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )
            conn = initialize_database(str(db_path))
            conn.close()
            db_path.unlink()

            self.assertFalse(db_path.exists())
            self.assertTrue(glossary_db.exists())
            self.assertEqual(
                load_glossary_entries(str(glossary), db_path=str(glossary_db)),
                [("knight fork", "garfo de cavalo")],
            )
            self.assertEqual(
                load_glossary_entries_from_db(str(glossary_db)),
                [("knight fork", "garfo de cavalo")],
            )

    def test_glossary_database_can_be_rebuilt_and_loaded_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("pin", "cravada"), ("fork", "garfo")],
                str(glossary),
                create_backup=False,
                sync_db=False,
            )
            self.assertFalse(glossary_db.exists())

            stats = rebuild_glossary_database(str(glossary), str(glossary_db))
            self.assertEqual(stats["synced"], 2)
            self.assertEqual(
                load_glossary_entries_from_db(str(glossary_db)),
                [("pin", "cravada"), ("fork", "garfo")],
            )

            sync_glossary_database(
                [("skewer", "raio x")],
                db_path=str(glossary_db),
                source_path=str(glossary),
            )
            self.assertEqual(load_glossary_entries_from_db(str(glossary_db)), [("skewer", "raio x")])

            conn = initialize_glossary_database(str(glossary_db))
            try:
                indexes = {
                    row[1]
                    for row in conn.execute("PRAGMA index_list(glossary_entries)").fetchall()
                }
            finally:
                conn.close()
            self.assertIn("idx_glossary_original", indexes)
            self.assertIn("idx_glossary_replacement", indexes)

    def test_glossary_editor_filters_and_counts_large_lists(self):
        entries = [
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça direta"),
            ("", "vazio"),
            ("fork", "fork"),
        ]
        diagnostics = build_glossary_diagnostics(entries)

        # `conflicts` conta 2, e nao 3: a duplicata exata (#2) nao e conflito —
        # a vencedora produz exatamente o que ela queria, e o aviso dela e
        # "Entrada duplicada". Era 3 porque a avaliacao antiga bastava "ha duas
        # substituicoes distintas no grupo" e arrastava a duplicata junto,
        # contra o que a propria garantia S9 dizia. Com S12 a pergunta passou a
        # ser por regra: "o que a vencedora produz AQUI e diferente do que esta
        # regra queria?" (ROADMAP 14.4)
        self.assertEqual(
            glossary_counts(entries, diagnostics),
            {"total": 5, "duplicates": 2, "conflicts": 2, "invalid": 5},
        )
        self.assertEqual(
            glossary_filter_indices(entries, "mate", "Todas", diagnostics),
            [0, 1, 2],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "", "Duplicadas", diagnostics),
            [0, 1],
        )
        # A duplicata exata (#2) fica fora de "Conflitos" pelo mesmo motivo da
        # contagem acima: a vencedora produz exatamente o que ela queria. Ela
        # continua em "Duplicadas", que e o aviso dela.
        self.assertEqual(
            glossary_filter_indices(entries, "", "Conflitos", diagnostics),
            [0, 2],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "fork", "Inválidas", diagnostics),
            [4],
        )
        self.assertEqual(sort_glossary_indices(entries, [2, 0, 4], "Original A-Z"), [4, 0, 2])
        self.assertEqual(
            sort_glossary_indices(entries, [0, 2, 4], "Maior original"),
            [0, 2, 4],
        )

    def test_glossary_csv_export_import_preview_and_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            csv_path = tmp_path / "glossario.csv"
            backup_dir = tmp_path / "backups"

            save_glossary_entries(
                [("mate threat", "ameaça de mate"), ("fork", "garfo")],
                str(glossary),
                create_backup=False,
            )

            export_stats = export_glossary_csv(str(csv_path), path=str(glossary))
            self.assertEqual(export_stats["exported"], 2)
            self.assertIn("original,replacement", csv_path.read_text(encoding="utf-8-sig"))

            csv_path.write_text(
                "original,replacement\n"
                "mate threat,ameaça de mate\n"
                "fork,garfo duplo\n"
                "pin,cravada\n"
                ",sem original\n"
                "skewer,\n",
                encoding="utf-8-sig",
            )

            preview = analyze_glossary_csv_import(str(glossary), str(csv_path))
            self.assertEqual(preview["total_rows"], 5)
            self.assertEqual(preview["inserted"], 1)
            self.assertEqual(preview["duplicates"], 1)
            self.assertEqual(preview["conflicts"], 1)
            self.assertEqual(preview["invalid"], 2)
            self.assertEqual(preview["skipped"], 4)

            stats = import_glossary_csv(
                str(glossary),
                str(csv_path),
                backup_dir=str(backup_dir),
                timestamp="20260101-120000",
            )
            self.assertEqual(stats["inserted"], 1)
            self.assertTrue(Path(stats["backup_path"]).exists())
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [
                    ("mate threat", "ameaça de mate"),
                    ("fork", "garfo"),
                    ("pin", "cravada"),
                ],
            )

    def test_restore_glossary_from_backup_replaces_file_and_keeps_safety_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            backup = tmp_path / "backup.txt"
            safety_dir = tmp_path / "safety"

            save_glossary_entries([("current", "atual")], str(glossary), create_backup=False)
            save_glossary_entries([("backup", "copia")], str(backup), create_backup=False)

            result = restore_glossary_from_backup(
                str(glossary),
                str(backup),
                safety_backup_dir=str(safety_dir),
                timestamp="20260101-120000",
            )

            self.assertTrue(Path(result["safety_backup_path"]).exists())
            self.assertEqual(load_glossary_entries(str(glossary)), [("backup", "copia")])
            self.assertEqual(
                load_glossary_entries(result["safety_backup_path"]),
                [("current", "atual")],
            )


class GlossaryEntryLocationTests(unittest.TestCase):
    """Roadmap 3.4 / garantia S6: operar pela entrada, nao pela posicao."""

    ENTRIES = [
        ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
        ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
        ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
    ]

    def _write(self, directory, entries):
        path = Path(directory) / "Substituicoes.txt"
        save_glossary_entries(entries, str(path), create_backup=False, sync_db=False)
        return path

    def test_finds_the_entry_regardless_of_position(self):
        self.assertEqual(
            find_glossary_entry_index(self.ENTRIES, ("queen", "dama", "suggestion")),
            1,
        )

    def test_missing_entry_returns_none(self):
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("bishop", "bispo", "suggestion"))
        )

    def test_type_participates_in_the_match(self):
        # Mesmo par, tipo diferente: nao e a mesma entrada.
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("pawn", "peao", "suggestion"))
        )
        self.assertEqual(
            find_glossary_entry_index(
                self.ENTRIES, ("pawn", "peao", "suggestion"), match_type=False
            ),
            2,
        )

    def test_it_finds_what_the_write_normalized(self):
        """A gravacao tira os espacos das pontas; a busca tem de saber disso.

        Apareceu ao cobrir `save_as_new` do editor de glossario: com
        `"  bishop  "` no formulario, a entrada ia para o arquivo como
        `"bishop"` e `locate_saved_entry` nao a reencontrava — a entrada recem
        gravada ficava sem selecao, sem erro nenhum. A docstring de
        `locate_saved_entry` ja afirmava que os dois lados eram normalizados; e
        que nao eram.
        """
        self.assertEqual(
            find_glossary_entry_index(
                self.ENTRIES, ("  queen  ", "  dama  ", "suggestion")
            ),
            1,
        )
        # Do outro lado tambem: uma entrada nao normalizada na lista.
        self.assertEqual(
            find_glossary_entry_index(
                [("  rook  ", "torre ", GLOSSARY_RULE_SUGGESTION)],
                ("rook", "torre", "suggestion"),
            ),
            0,
        )
        # E normalizar nao pode fazer o par casar com quem ele nao e.
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("qu een", "dama", "suggestion"))
        )

    def test_hint_decides_between_exact_duplicates(self):
        """Com duplicatas identicas, vale a que estava na tela."""
        entries = [
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
            ("x", "y", GLOSSARY_RULE_SUGGESTION),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        alvo = ("a", "b", GLOSSARY_RULE_SUGGESTION)

        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=2), 2)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=0), 0)
        # Palpite invalido ou apontando para outra coisa: cai na busca.
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=1), 0)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=99), 0)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint="nao"), 0)

    def test_update_by_entry_survives_an_external_insertion(self):
        """O bug do item 3.4, reproduzido.

        A janela guarda a posicao de "queen" (1) no carregamento. O outro
        editor insere uma regra no inicio do arquivo. Salvar por posicao
        gravaria por cima de "queen" — que agora esta em 2 — destruindo a
        entrada vizinha sem aviso.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            posicao_no_carregamento = 1

            # Alteracao externa: uma entrada nova no inicio do arquivo.
            deslocado = [("bishop", "bispo", GLOSSARY_RULE_SUGGESTION)] + list(
                self.ENTRIES
            )
            save_glossary_entries(
                deslocado, str(path), create_backup=False, sync_db=False
            )

            result = update_glossary_entry_by_entry(
                ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
                "queen",
                "rainha",
                path=str(path),
                index_hint=posicao_no_carregamento,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertIsNotNone(result)
            self.assertEqual(result["index"], 2)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade([
                    ("bishop", "bispo", GLOSSARY_RULE_SUGGESTION),
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("queen", "rainha", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_positional_update_is_what_used_to_corrupt_the_neighbour(self):
        """Contraprova: a funcao antiga, no mesmo cenario, grava na errada."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            deslocado = [("bishop", "bispo", GLOSSARY_RULE_SUGGESTION)] + list(
                self.ENTRIES
            )
            save_glossary_entries(
                deslocado, str(path), create_backup=False, sync_db=False
            )

            update_glossary_entry(
                1,
                "queen",
                "rainha",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            entradas = load_glossary_entry_details(str(path), deduplicate=False)
            # "rook" foi destruida e "queen" continua intacta: a entrada errada.
            self.assertEqual(
            entradas[1], ("queen", "rainha", GLOSSARY_RULE_SUGGESTION, 0, "")
        )
            self.assertIn(("queen", "dama", GLOSSARY_RULE_SUGGESTION, 0, ""), entradas)
            self.assertNotIn(("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""), entradas)

    def test_update_by_entry_refuses_when_the_entry_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            sem_queen = [e for e in self.ENTRIES if e[0] != "queen"]
            save_glossary_entries(
                sem_queen, str(path), create_backup=False, sync_db=False
            )

            result = update_glossary_entry_by_entry(
                ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
                "queen",
                "rainha",
                path=str(path),
                index_hint=1,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertIsNone(result)
            # Nada foi gravado: o arquivo continua exatamente como estava.
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(sem_queen),
            )

    def test_update_by_entry_normalizes_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            result = update_glossary_entry_by_entry(
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                "  rook  ",
                "  torre alta  ",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(result["index"], 0)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False)[0],
                ("rook", "torre alta", GLOSSARY_RULE_SUGGESTION, 0, ""),
            )

    def test_update_by_entry_keeps_the_type_when_none_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            update_glossary_entry_by_entry(
                ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                "pawn",
                "peao livre",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False)[2],
                ("pawn", "peao livre", GLOSSARY_RULE_AUTOMATIC, 0, ""),
            )

    def test_delete_by_pair_can_target_the_type_and_the_duplicate(self):
        entries = [
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
            ("a", "b", GLOSSARY_RULE_AUTOMATIC),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, entries)

            removed = delete_glossary_entry_by_pair(
                "a",
                "b",
                path=str(path),
                rule_type=GLOSSARY_RULE_SUGGESTION,
                index_hint=2,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(removed["index"], 2)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(entries[:2]),
            )

    def test_delete_by_pair_without_a_type_still_matches_only_the_pair(self):
        """Comportamento antigo preservado para quem so conhece o par."""
        entries = [
            ("x", "y", GLOSSARY_RULE_AUTOMATIC),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, entries)

            removed = delete_glossary_entry_by_pair(
                "x", "y", path=str(path), backup_dir=str(Path(tmp) / "backups")
            )

            self.assertEqual(removed["index"], 0)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(entries[1:]),
            )

    def test_delete_by_pair_returns_none_for_a_missing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            self.assertIsNone(
                delete_glossary_entry_by_pair(
                    "bishop",
                    "bispo",
                    path=str(path),
                    backup_dir=str(Path(tmp) / "backups"),
                )
            )
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(self.ENTRIES),
            )


class GlossaryPriorityTests(unittest.TestCase):
    """Item 1.5 parte 2 / garantia S10: a prioridade decide antes do comprimento.

    A queixa do item era que a especificidade e derivada do texto: para adiantar
    uma regra era preciso alongar o padrao — mudar o que ela casa para mudar
    quando ela roda. Com a prioridade a intencao e declarada.
    """

    def test_priority_beats_length(self):
        curta = ("torre", "roque", 5)
        longa = ("torre da dama", "torre longa")

        ordem = order_rules_by_specificity([longa, curta])

        self.assertEqual(ordem[0], curta, "o comprimento venceu a prioridade")

    def test_without_priority_nothing_changes(self):
        """Prioridade zero e o caso de praticamente todas as regras."""
        curta = ("torre", "roque")
        longa = ("torre da dama", "torre longa")

        self.assertEqual(order_rules_by_specificity([curta, longa]), [longa, curta])

    def test_a_negative_priority_pushes_the_rule_back(self):
        adiada = ("torre da dama", "torre longa", -1)
        normal = ("torre", "roque")

        self.assertEqual(order_rules_by_specificity([adiada, normal]), [normal, adiada])

    def test_equal_priority_falls_back_to_length_then_file_order(self):
        regras = [
            ("bispo", "alfil", 2),
            ("bispo de casas claras", "alfil claro", 2),
            ("dama", "rainha", 2),
        ]

        ordem = order_rules_by_specificity(regras)

        self.assertEqual(ordem[0], regras[1], "o comprimento nao desempatou")
        self.assertEqual(ordem[1:], [regras[0], regras[2]], "a ordem do arquivo nao desempatou")

    def test_the_ordering_cache_notices_a_change_of_priority(self):
        """Duas listas com os mesmos pares e prioridades diferentes.

        A chave do cache era so os pares. Sem a prioridade nela, a segunda lista
        receberia a ordem da primeira: as regras continuariam sendo aplicadas,
        so que na ordem errada — sem erro nenhum, que e o pior modo de falhar.
        """
        sem = [("torre", "roque"), ("torre da dama", "torre longa")]
        com = [("torre", "roque", 5), ("torre da dama", "torre longa")]

        primeira = order_rules_by_specificity(sem)
        segunda = order_rules_by_specificity(com)

        self.assertEqual(primeira[0], sem[1])
        self.assertEqual(segunda[0], com[0], "o cache devolveu a ordem da outra lista")

    def test_the_priority_changes_what_the_text_receives(self):
        """A prova de que a ordem importa: o texto sai diferente."""
        sem = [("torre", "roque"), ("torre da dama", "torre longa")]
        com = [("torre", "roque", 5), ("torre da dama", "torre longa")]

        self.assertEqual(apply_all_substitutions("a torre da dama", sem), "a torre longa")
        self.assertEqual(apply_all_substitutions("a torre da dama", com), "a roque da dama")

    # ------------------------------------------------ o valor em si

    def test_anything_that_is_not_an_integer_becomes_the_default(self):
        """O arquivo e o CSV sao editaveis a mao e sobrevivem a versoes.

        Uma prioridade escrita como `"alta"` nao pode virar excecao no meio da
        carga do glossario — isso desligaria as 7 mil regras por causa de uma.
        """
        for valor in (None, "", "alta", "1.5", [], {}, True, False):
            with self.subTest(valor=valor):
                self.assertEqual(normalize_glossary_priority(valor), 0)

        self.assertEqual(normalize_glossary_priority("3"), 3)
        self.assertEqual(normalize_glossary_priority(" -2 "), -2)
        self.assertEqual(normalize_glossary_priority(7), 7)

    def test_a_plain_pair_still_has_a_priority(self):
        self.assertEqual(rule_priority(("a", "b")), 0)
        self.assertEqual(rule_priority(("a", "b", 4)), 4)

    # ------------------------------------------------ persistencia

    def test_the_file_only_writes_the_field_when_there_is_one(self):
        """7 mil linhas nao podem ganhar `, 0` por causa de quatro decisoes."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC, 0, ""),
                    ("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3, ""),
                ],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            texto = path.read_text(encoding="utf-8")
            self.assertIn("('rook', 'torre'),", texto)
            self.assertIn("('pawn', 'peao', 'automatic'),", texto)
            self.assertIn("('queen', 'dama', 'suggestion', 3),", texto)

    def test_a_file_from_before_this_version_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            path.write_text(
                "substituicoes = [\n"
                "    ('rook', 'torre'),\n"
                "    ('pawn', 'peao', 'automatic'),\n"
                "]\n",
                encoding="utf-8",
            )

            entradas = load_glossary_entry_details(str(path), prefer_db=False)

            self.assertEqual(
                entradas,
                com_prioridade([
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_the_priority_survives_the_round_trip_through_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            do_banco = load_glossary_entry_details_from_db(str(db_path))
            self.assertEqual(do_banco, [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3, "")])

    def test_a_database_from_the_previous_schema_is_rebuilt(self):
        """O `ALTER TABLE` sozinho seria uma armadilha.

        A coluna nova entra com o padrao para todas as regras, e o `mtime` do
        arquivo nao mudou para acusar: o banco continuaria valendo como cache e
        as prioridades do arquivo seriam lidas como zero.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            # Um banco gravado pela versao anterior: sem a marca de esquema.
            conn = initialize_glossary_database(str(db_path))
            conn.execute("DELETE FROM glossary_metadata WHERE key = 'schema_version'")
            conn.execute("UPDATE glossary_entries SET priority = 0")
            conn.commit()
            conn.close()

            entradas = load_glossary_entry_details(str(path), db_path=str(db_path))

            self.assertEqual(
                glossary_entry_priority(entradas[0]), 3, "leu a prioridade do cache velho"
            )

    def _clonar(self, origem, destino):
        """O que um `git clone` faz com os dois arquivos, e so isso.

        Copia o conteudo para outra pasta e da ao `Substituicoes.txt` uma data
        nova — o git nao guarda `mtime`, entao o arquivo baixado tem sempre a
        hora do checkout, e nunca a de quem o gravou.
        """
        destino.mkdir(parents=True, exist_ok=True)
        for nome in ("Substituicoes.txt", "glossario.db"):
            (destino / nome).write_bytes((origem / nome).read_bytes())
        outra_data = os.path.getmtime(origem / "Substituicoes.txt") + 86400
        os.utime(destino / "Substituicoes.txt", (outra_data, outra_data))

    def test_the_cached_index_survives_a_clone(self):
        """A razao de versionar o `glossario.db` (ROADMAP 3.7).

        As marcas antigas nao sobreviviam ao clone: o `source_path` era absoluto,
        entao mudar de pasta ja bastava para divergir, e o `source_mtime` era a
        data do arquivo, que o checkout reescreve. As duas acusavam diferenca
        onde nao havia, e o cache versionado era descartado e reconstruido em
        toda maquina — o oposto do que versiona-lo pretende.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "original"
            original.mkdir()
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(original / "Substituicoes.txt"),
                create_backup=False,
                db_path=str(original / "glossario.db"),
            )

            clone = base / "outra-pasta" / "projeto"
            self._clonar(original, clone)

            self.assertFalse(
                glossario._glossary_database_needs_sync(
                    str(clone / "Substituicoes.txt"), str(clone / "glossario.db")
                ),
                "o cache clonado foi descartado: as marcas nao viajaram",
            )

            # E o conteudo continua certo, com a prioridade que so o cache valido
            # entrega sem reconstruir.
            entradas = load_glossary_entry_details(
                str(clone / "Substituicoes.txt"), db_path=str(clone / "glossario.db")
            )
            self.assertEqual(glossary_entry_priority(entradas[0]), 3)

    def test_a_changed_glossary_still_invalidates_the_cache(self):
        """A outra metade: a marca nova nao pode ser frouxa.

        Trocar o `mtime` pelo hash so vale se o hash ainda acusar o que o `mtime`
        acusava. Sem esta, "nunca reconstruir" passaria no teste de cima.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            self.assertFalse(
                glossario._glossary_database_needs_sync(str(path), str(db_path))
            )

            path.write_text(
                "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
            )

            self.assertTrue(
                glossario._glossary_database_needs_sync(str(path), str(db_path)),
                "o glossario mudou e o cache continuou valendo",
            )

    def test_rewriting_the_same_content_does_not_invalidate_the_cache(self):
        """O ganho de lado do hash, que o `mtime` nao dava.

        A gravacao do glossario e atomica (arquivo temporario + troca), entao o
        `mtime` muda mesmo quando o conteudo e identico — e o cache era refeito
        por nada. O hash olha o que importa.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            conteudo = path.read_bytes()
            path.write_bytes(conteudo)
            futuro = os.path.getmtime(path) + 3600
            os.utime(path, (futuro, futuro))

            self.assertFalse(
                glossario._glossary_database_needs_sync(str(path), str(db_path)),
                "reconstruiu por causa da data, com o conteudo igual",
            )

    def test_the_csv_carries_the_priority_and_tolerates_its_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            csv_path = base / "glossario.csv"
            entradas = [
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""),
                ("queen", "dama", GLOSSARY_RULE_AUTOMATIC, 2, ""),
            ]
            export_glossary_csv(str(csv_path), entradas)

            self.assertEqual(read_glossary_csv(str(csv_path)), entradas)

            # Um CSV de tres colunas — de antes desta versao, ou montado numa
            # planilha — continua importavel.
            antigo = base / "antigo.csv"
            antigo.write_text(
                "original,replacement,type\r\nrook,torre,suggestion\r\n",
                encoding="utf-8-sig",
            )
            self.assertEqual(
                read_glossary_csv(str(antigo)),
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")],
            )

    def test_saving_a_new_priority_finds_the_entry_to_update(self):
        """A prioridade nao entra na identidade da entrada, de proposito.

        O editor localiza a linha pelo estado que exibiu quando ela foi
        selecionada, e mudar a prioridade e justamente uma das coisas que
        "Salvar" faz. Se ela contasse na comparacao, salvar uma prioridade nova
        nunca encontraria a entrada a atualizar.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            # A entrada JA TEM prioridade, e e esse o caso que importa: com uma
            # entrada em zero, um criterio que comparasse a prioridade acertaria
            # por coincidencia, porque a linha-base tambem vale zero.
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            resultado = update_glossary_entry_by_entry(
                # O editor identifica a linha pelo que exibiu — sem prioridade.
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                "rook",
                "torre",
                str(path),
                backup_dir=str(Path(tmp) / "backups"),
                priority=5,
            )

            self.assertIsNotNone(resultado, "nao achou a entrada para atualizar")
            entradas = load_glossary_entry_details(str(path), prefer_db=False)
            self.assertEqual(entradas, [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 5, "")])

    def test_locating_an_entry_ignores_the_priority(self):
        """O mesmo, direto na funcao — e o que a promocao tambem depende.

        Depois de "Priorizar esta" a regra fica com prioridade 1 e a janela
        precisa reencontra-la pelo par e pelo tipo para manter a selecao. Com a
        prioridade na comparacao, a busca falha e o formulario e limpo.
        """
        entradas = [("torre", "castle", GLOSSARY_RULE_SUGGESTION, 1)]

        self.assertEqual(
            find_glossary_entry_index(entradas, ("torre", "castle", GLOSSARY_RULE_SUGGESTION)),
            0,
        )

    def test_updating_without_an_opinion_keeps_the_priority(self):
        """Quem chama sem falar de prioridade nao pode zerar a que existia."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 6)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            update_glossary_entry(
                0,
                "rook",
                "torre alta",
                str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            entradas = load_glossary_entry_details(str(path), prefer_db=False)
            self.assertEqual(glossary_entry_priority(entradas[0]), 6)

    def test_adding_the_same_rule_with_another_priority_is_not_a_new_rule(self):
        """Senao a insercao criaria duas linhas identicas disputando entre si —
        exatamente o problema que a prioridade existe para resolver."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            resultado = add_glossary_entry(
                "rook", "torre", str(path), rule_type=GLOSSARY_RULE_SUGGESTION, priority=9
            )

            self.assertEqual(resultado["status"], "unchanged")
            self.assertEqual(
                len(load_glossary_entry_details(str(path), prefer_db=False)), 1
            )


class GlossaryPromotionTests(unittest.TestCase):
    """`promote_glossary_rule`: resolver o conflito sem apagar nada."""

    ENTRIES = [
        ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
        ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
    ]

    def test_promoting_the_loser_makes_it_win_without_removing_anything(self):
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)

        self.assertEqual(len(promovidas), 3, "a promocao removeu alguma regra")
        self.assertEqual(glossary_entry_priority(promovidas[2]), 1)
        self.assertEqual(glossary_entry_priority(promovidas[0]), 0, "mexeu na outra")

        conflitos = glossario.glossary_conflicts(promovidas)
        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 2)

    def test_the_promotion_reaches_the_text(self):
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)
        regras = [
            (orig, new, prio)
            for orig, new, _tipo, prio, _e in promovidas
        ]

        self.assertEqual(apply_all_substitutions("a torre", self.ENTRIES), "a rook")
        self.assertEqual(apply_all_substitutions("a torre", regras), "a castle")

    def test_promoting_the_winner_changes_nothing(self):
        self.assertIsNone(promote_glossary_rule(list(self.ENTRIES), 0))

    def test_promoting_a_rule_without_conflict_changes_nothing(self):
        self.assertIsNone(promote_glossary_rule(list(self.ENTRIES), 1))

    def test_the_decision_can_be_reversed(self):
        """E a diferenca em relacao a "Manter esta": nada foi perdido."""
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)
        de_volta = promote_glossary_rule(promovidas, 0)

        self.assertIsNotNone(de_volta, "a decisao anterior nao pode ser revista")
        self.assertEqual(glossary_entry_priority(de_volta[0]), 2)
        conflitos = glossario.glossary_conflicts(de_volta)
        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 0)


class GlossaryConflictTests(unittest.TestCase):
    """Roadmap 1.5 / garantia S9: em cada conflito, qual regra esta valendo.

    Dois padroes identicos empatam em comprimento, entao `order_rules_by_specificity`
    desempata pela ordem do arquivo e o congelamento de S4 impede a segunda de
    rever o trecho: vence quem foi digitado primeiro. A interface nao dizia isso,
    e as duas regras apareciam lado a lado com o mesmo aspecto.
    """

    def aplicada(self, rules, texto):
        """A substituicao que o programa de fato produz para `texto`."""
        return apply_all_substitutions(texto, rules)

    def vencedores(self, entradas):
        """Os indices que a janela anuncia como vencedores, em todo contexto."""
        conflitos = glossario.glossary_conflicts(entradas)
        return {
            contexto["winner"]
            for info in conflitos.values()
            for contexto in info["contexts"]
        }

    def test_the_announcement_follows_a_change_in_the_application_order(self):
        """A prova de que o criterio e um so, e nao dois que hoje coincidem.

        Os outros testes desta classe exigem que anuncio e aplicacao concordem —
        e concordariam tambem com **duas copias** do mesmo criterio, que era o
        estado anterior. O que separa os dois casos e mexer no criterio uma vez
        so e exigir que os dois lados virem juntos.

        A inversao usada aqui e do desempate por ordem do arquivo, que e
        justamente o termo que decide entre padroes identicos. Com o criterio
        duplicado, `order_rules_by_specificity` obedeceria e `glossary_conflicts`
        continuaria anunciando o antigo vencedor — a divergencia que a SPEC
        listava como limite conhecido.
        """
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
        ]
        regras = [(orig, new) for orig, new, _tipo in entradas]

        # Linha de base: vence a primeira do arquivo, e o texto recebe 'rook'.
        self.assertEqual(self.vencedores(entradas), {0})
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a rook avanca")

        original = glossario._rule_sort_key

        def desempate_invertido(rule, position):
            prioridade, comprimento, posicao = original(rule, position)
            return (prioridade, comprimento, -posicao)

        # O cache guarda a ordem, nao o criterio: sem limpa-lo, a aplicacao
        # devolveria a ordem calculada antes da troca e o teste passaria por
        # motivo errado.
        def restaurar():
            glossario._rule_sort_key = original
            glossario._ordered_rules_cache.clear()

        self.addCleanup(restaurar)
        glossario._rule_sort_key = desempate_invertido
        glossario._ordered_rules_cache.clear()

        self.assertEqual(
            self.vencedores(entradas),
            {1},
            "o anuncio nao seguiu o criterio da aplicacao: ha uma copia dele",
        )
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a castle avanca")

    def test_the_announced_winner_is_the_one_actually_applied(self):
        """O teste central: o que o editor anuncia e o que o texto recebe.

        Anunciar um vencedor que nao e o aplicado seria pior do que nao anunciar
        nada, entao a afirmacao e verificada contra `apply_all_substitutions`, e
        nao contra outra copia da mesma regra de ordenacao.
        """
        for posicao_vencedora, regras in enumerate(
            [
                [("torre", "rook"), ("torre", "castle")],
                [("torre", "castle"), ("torre", "rook")],
            ]
        ):
            with self.subTest(ordem=posicao_vencedora):
                entradas = [
                    (orig, new, GLOSSARY_RULE_SUGGESTION) for orig, new in regras
                ]
                conflitos = glossario.glossary_conflicts(entradas)

                self.assertEqual(sorted(conflitos), [0, 1])
                for info in conflitos.values():
                    for contexto in info["contexts"]:
                        self.assertEqual(contexto["winner"], 0)

                # A ordem do arquivo decide: invertida, o resultado muda junto.
                esperado = regras[0][1]
                self.assertEqual(self.aplicada(regras, "a torre avanca"), f"a {esperado} avanca")

    def test_the_announced_winner_follows_the_priority_too(self):
        """A mesma exigencia, agora com a prioridade no meio (garantia S10).

        E aqui que um criterio duplicado se paga caro: `glossary_conflicts`
        decide o vencedor por conta propria, e se ele divergir de
        `order_rules_by_specificity` a janela anuncia uma regra e o texto recebe
        outra. Por isso a afirmacao continua sendo verificada contra
        `apply_all_substitutions`.
        """
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION, 0, ""),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION, 2, ""),
        ]
        conflitos = glossario.glossary_conflicts(entradas)

        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 1, "a ordem do arquivo venceu")

        regras = [(orig, new, prio) for orig, new, _tipo, prio, _e in entradas]
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a castle avanca")

        # E a mensagem acompanha: quem perde continua sendo avisado.
        self.assertIn("nunca é aplicada", glossario.describe_glossary_conflict(entradas, 0, conflitos))
        self.assertNotIn("nunca é aplicada", glossario.describe_glossary_conflict(entradas, 1, conflitos))

    def test_the_loser_is_told_it_never_applies(self):
        entradas = [
            ("as Pretas", "das pretas", GLOSSARY_RULE_AUTOMATIC),
            ("as Pretas", "as pretas", GLOSSARY_RULE_AUTOMATIC),
        ]
        conflitos = glossario.glossary_conflicts(entradas)

        vencedora = glossario.describe_glossary_conflict(entradas, 0, conflitos)
        perdedora = glossario.describe_glossary_conflict(entradas, 1, conflitos)

        self.assertIn("vence esta regra", vencedora)
        self.assertNotIn("nunca é aplicada", vencedora)
        self.assertIn("#1", perdedora)
        self.assertIn("das pretas", perdedora)
        self.assertIn("nunca é aplicada", perdedora)

        # Uma regra automatica e carregada em dois contextos (as automaticas e as
        # sugestoes do editor) e vence nos dois. Nomear os dois seria repetir a
        # mesma frase com rotulos diferentes.
        self.assertNotIn("regras automáticas", vencedora)

    def test_a_rule_that_loses_in_the_editor_can_still_win_elsewhere(self):
        """O caso real de `'/\\'`, e o erro que ele pegou.

        A regra automatica vem depois da de sugestao, entao perde no editor, que
        carrega as duas. Mas na aplicacao das regras automaticas ela e a unica
        daquele padrao — e la ela e aplicada. Dizer "nunca e aplicada" seria
        falso, e era o que a primeira versao desta mensagem dizia.
        """
        entradas = [
            ("/\\", "com a ideia de", GLOSSARY_RULE_SUGGESTION),
            ("/\\", "Com a ideia de", GLOSSARY_RULE_AUTOMATIC),
        ]
        conflitos = glossario.glossary_conflicts(entradas)
        automatica = glossario.describe_glossary_conflict(entradas, 1, conflitos)

        self.assertIn("regras automáticas", automatica)
        self.assertIn("sugestões do editor", automatica)
        self.assertNotIn("nunca é aplicada", automatica)

        # E a contraprova pelo comportamento, nao pela mensagem.
        pares = [(orig, new) for orig, new, _tipo in entradas]
        self.assertEqual(self.aplicada(pares, "1. e4 /\\"), "1. e4 com a ideia de")
        so_automaticas = glossario.filter_glossary_entries_by_type(
            entradas, GLOSSARY_RULE_AUTOMATIC
        )
        self.assertEqual(self.aplicada(so_automaticas, "1. e4 /\\"), "1. e4 Com a ideia de")

    def test_exact_duplicates_are_not_a_conflict(self):
        """Duplicata e redundancia, nao disputa — e ja tem aviso proprio."""
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_rules_never_loaded_together_do_not_conflict(self):
        """Limpeza roda antes da API; sugestao, no editor. Nunca no mesmo texto."""
        entradas = [
            ("torre", "", GLOSSARY_RULE_CLEANUP),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_keeping_one_rule_removes_only_the_rules_that_competed(self):
        entradas = [
            ("torre", "", GLOSSARY_RULE_CLEANUP),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
            ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
        ]
        restantes = glossario.resolve_glossary_conflict(entradas, 2)

        self.assertEqual(
            restantes,
            [
                ("torre", "", GLOSSARY_RULE_CLEANUP),
                ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
                ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
            ],
            "a regra de limpeza nunca competiu e nao pode sair junto",
        )
        # Resolvido de verdade: o glossario que sobra nao tem mais disputa.
        self.assertEqual(glossario.glossary_conflicts(restantes), {})

    def test_resolving_a_rule_without_conflict_writes_nothing(self):
        entradas = [("torre", "rook", GLOSSARY_RULE_SUGGESTION)]
        self.assertIsNone(glossario.resolve_glossary_conflict(entradas, 0))
        self.assertEqual(glossario.describe_glossary_conflict(entradas, 0), "")

    def test_the_real_glossary_has_no_undecided_conflict(self):
        """O `Substituicoes.txt` versionado nao tem disputa pendente.

        Eram dois conflitos quando 1.5 foi aberto e quatro quando ele foi
        resolvido — dois entraram no meio do caminho, sem que ninguem notasse,
        porque nada os vigiava. Os quatro foram decididos (ver ROADMAP 1.5); este
        teste existe para que o quinto quebre a suite em vez de aparecer numa
        medicao daqui a um ano.

        Falhar aqui nao e defeito de codigo: e uma regra nova disputando um
        padrao com uma antiga. A saida diz quais sao, e a decisao e de quem
        editou o glossario — o botao "Manter esta" resolve cada uma.
        """
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        entradas = load_glossary_entry_details(str(path), deduplicate=False)
        conflitos = glossario.glossary_conflicts(entradas)

        relatorio = "\n".join(
            "  " + glossario.describe_glossary_conflict(entradas, index, conflitos)
            for index in sorted(conflitos)
        )
        self.assertEqual(
            conflitos,
            {},
            f"conflito novo no glossario, decida qual regra fica:\n{relatorio}",
        )


class CaseAdjustedReplacementTests(unittest.TestCase):
    """Propagacao de caixa do texto encontrado para a substituicao."""

    def test_all_caps_matched_text_uppercases_the_replacement(self):
        self.assertEqual(case_adjusted_replacement("ROOK", "torre"), "TORRE")

    def test_leading_capital_capitalizes_the_replacement(self):
        self.assertEqual(case_adjusted_replacement("Rook", "torre"), "Torre")

    def test_lowercase_is_left_alone(self):
        self.assertEqual(case_adjusted_replacement("rook", "torre"), "torre")

    def test_only_the_first_letter_changes(self):
        # Nao pode virar "Torre Alta": a substituicao decide o resto.
        self.assertEqual(case_adjusted_replacement("Rook", "torre alta"), "Torre alta")

    def test_a_single_capital_letter_counts_as_all_caps(self):
        self.assertEqual(case_adjusted_replacement("R", "torre"), "TORRE")

    def test_text_without_letters_does_not_change_anything(self):
        # Sem letras nao ha caixa a propagar; decidir por "tudo maiusculo"
        # transformaria "1-0" em substituicao gritada.
        self.assertEqual(case_adjusted_replacement("1-0", "vitoria"), "vitoria")
        self.assertEqual(case_adjusted_replacement("...", "reticencias"), "reticencias")

    def test_leading_symbol_uses_the_first_letter(self):
        self.assertEqual(case_adjusted_replacement("-Rook", "torre"), "Torre")
        self.assertEqual(case_adjusted_replacement("-rook", "torre"), "torre")

    def test_mixed_case_is_left_alone(self):
        self.assertEqual(case_adjusted_replacement("rOOk", "torre"), "torre")

    def test_empty_inputs_are_safe(self):
        self.assertEqual(case_adjusted_replacement("", "torre"), "torre")
        self.assertEqual(case_adjusted_replacement("ROOK", ""), "")
        self.assertIsNone(case_adjusted_replacement("ROOK", None))

    def test_accented_letters_follow_the_same_rule(self):
        self.assertEqual(case_adjusted_replacement("ÁRVORE", "tree"), "TREE")
        self.assertEqual(case_adjusted_replacement("Árvore", "tree"), "Tree")


class ReadGlossaryCsvTests(unittest.TestCase):
    """Leitura do CSV de importacao do glossario."""

    def write_csv(self, directory, content, encoding="utf-8-sig"):
        path = Path(directory) / "entrada.csv"
        path.write_text(content, encoding=encoding, newline="")
        return str(path)

    def test_reads_the_exported_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp,
                "original,replacement,type\r\nrook,torre,suggestion\r\npawn,peao,automatic\r\n",
            )

            self.assertEqual(
                read_glossary_csv(path),
                com_prioridade([
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_round_trip_with_the_exporter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "saida.csv")
            entries = [
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                ("pawn", "peão", GLOSSARY_RULE_AUTOMATIC),
            ]
            export_glossary_csv(path, entries)

            self.assertEqual(read_glossary_csv(path), com_prioridade(entries))

    def test_accepts_the_portuguese_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "Original,Substituição,Tipo\r\nrook,torre,limpeza\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_CLEANUP, 0, "")]
            )

    def test_headers_are_matched_ignoring_case_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "  ORIGINAL ,  Replacement  \r\nrook,torre\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_missing_type_column_defaults_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,replacement\r\nrook,torre\r\n")

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_unknown_type_falls_back_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement,type\r\nrook,torre,inventado\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_values_are_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\n  rook  ,  torre  \r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_missing_required_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,tipo\r\nrook,suggestion\r\n")

            with self.assertRaises(ValueError):
                read_glossary_csv(path)

    def test_empty_file_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_glossary_csv(self.write_csv(tmp, "")), [])

    def test_header_only_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,replacement,type\r\n")
            self.assertEqual(read_glossary_csv(path), [])

    def test_bom_does_not_leak_into_the_first_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\nrook,torre\r\n", encoding="utf-8-sig"
            )
            # Sem tratar o BOM, o primeiro campo viria como "﻿original" e a
            # coluna obrigatoria pareceria ausente.
            self.assertEqual(len(read_glossary_csv(path)), 1)

    def test_accents_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\ncheck,xeque à descoberta\r\n"
            )

            self.assertEqual(read_glossary_csv(path)[0][1], "xeque à descoberta")


class EmptyCleanupSpanRemovalTests(unittest.TestCase):
    """O comentario esvaziado pela limpeza sai do arquivo (garantia X2)."""

    def test_empty_translation_removes_span_and_one_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            conteudo = '[Event "T"]\n\n1. e4 {junk} e5 {keep} 2. Nf3\n'
            entrada.write_text(conteudo, encoding="utf-8")
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            ok = generate_translated_pgn(
                str(entrada),
                str(saida),
                {"junk": "", "keep": "fica"},
                posicoes,
            )
            self.assertTrue(ok)
            texto = saida.read_text(encoding="utf-8")
            self.assertNotIn("{}", texto)
            self.assertIn("1. e4 e5", texto)
            self.assertIn("{fica}", texto)

    def test_adjacent_spans_do_not_eat_each_other(self):
        """`{a}{b}` colados: o espaco vizinho que sai e so espaco — nunca o
        comeco do span seguinte."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_text(
                '[Event "T"]\n\n1. e4 {junk}{keep} e5\n', encoding="utf-8"
            )
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada), str(saida), {"junk": "", "keep": "fica"}, posicoes
            )
            texto = saida.read_text(encoding="utf-8")
            self.assertIn("1. e4{fica} e5", texto)
            self.assertNotIn("{}", texto)


class CaseShadowConflictTests(unittest.TestCase):
    """Conflito por diferenca de caixa (garantia S12, ROADMAP 14.4).

    Uma regra escrita toda em minusculas casa sem diferenciar caixa, entao ela
    engole a versao capitalizada que venha depois. O detector agrupava por
    padrao EXATO: `'black'` e `'Black'` eram padroes diferentes, e a janela
    mostrava as duas lado a lado sem dizer que a segunda estava morta.
    """

    def test_lowercase_rule_shadows_the_capitalized_one(self):
        entradas = [("black", "pretas"), ("Black", "as pretas")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertEqual(sorted(conflitos), [0, 1])
        mensagem = glossario.describe_glossary_conflict(entradas, 1, conflitos)
        self.assertIn("nunca é aplicada", mensagem)
        self.assertIn("'pretas'", mensagem)

    def test_case_sensitive_first_leaves_both_alive(self):
        """A relacao nao e simetrica. Com a de caixa fixa na frente, cada uma
        pega o seu: `Black` o texto capitalizado, `black` o resto."""
        entradas = [("Black", "as pretas"), ("black", "pretas")]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_capitalization_propagation_is_not_a_conflict(self):
        """O caso que domina o glossario real (166 das 210): a vencedora ja
        produz o que a morta queria, porque a substituicao propaga a
        capitalizacao do texto encontrado. E redundancia, nao conflito."""
        entradas = [
            ("as pretas deve", "as pretas devem"),
            ("As pretas deve", "As pretas devem"),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_the_middle_rule_can_be_alive_and_the_last_dead(self):
        """Com tres variantes o vencedor e por REGRA, e nao do grupo: a
        primeira de caixa fixa vive, a insensivel vive, e o que vem depois dela
        morre."""
        entradas = [("Black", "x"), ("black", "y"), ("BLACK", "z")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertNotIn(0, conflitos)
        self.assertIn(2, conflitos)
        self.assertEqual(conflitos[2]["contexts"][0]["winner"], 1)

    def test_priority_revives_the_shadowed_rule(self):
        """A saida nao destrutiva: a prioridade poe a capitalizada na frente e
        as duas passam a valer (garantia S10)."""
        entradas = [("black", "pretas"), ("Black", "as pretas", "suggestion", 1)]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_keeping_a_rule_also_removes_the_exact_duplicate(self):
        """`group` nao e o conjunto em disputa: a duplicata exata nao e conflito
        (a vencedora produz o mesmo que ela), mas continua engolindo quem vem
        depois. Fora do grupo, "Manter esta" deixaria a escolhida morta."""
        entradas = [("x", "a"), ("x", "a"), ("x", "b")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertEqual(conflitos[2]["group"], [0, 1, 2])
        mantidas = glossario.resolve_glossary_conflict(entradas, 2, conflitos)
        self.assertEqual(mantidas, [("x", "b")])
        self.assertEqual(glossario.glossary_conflicts(mantidas), {})

    def test_a_cleanup_rule_is_not_dragged_into_the_group(self):
        entradas = [("x", "a"), ("x", "b"), ("x", "c", "cleanup")]
        conflitos = glossario.glossary_conflicts(entradas)
        self.assertEqual(conflitos[0]["group"], [0, 1])


class UnknownRuleTypeTests(unittest.TestCase):
    """Tipo de regra desconhecido avisa (garantia S13, ROADMAP 14.6)."""

    def test_masculine_and_short_aliases_are_understood(self):
        """Faltavam, e sao o erro mais facil de cometer: a regra virava
        sugestao, deixava de rodar depois da API, e nada avisava."""
        for escrito in ("automático", "automatico", "auto", "AUTOMÁTICO"):
            with self.subTest(escrito=escrito):
                self.assertEqual(
                    glossario._normalize_rule_type(escrito),
                    glossario.GLOSSARY_RULE_AUTOMATIC,
                )
        self.assertEqual(
            glossario._normalize_rule_type("clean"), glossario.GLOSSARY_RULE_CLEANUP
        )

    def test_unknown_values_are_listed_once_each(self):
        desconhecidos = glossario.unknown_rule_types(
            [
                ("a", "b", "automático"),
                ("c", "d", "xyz"),
                ("e", "f", "xyz"),
                ("g", "h", "zzz"),
                ("i", "j"),
            ]
        )
        self.assertEqual(desconhecidos, ["xyz", "zzz"])

    def test_loading_a_file_with_a_bad_type_warns_and_degrades(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n"
            "    ('rook', 'torre', 'automatico'),\n"
            "    ('queen', 'dama', 'perto'),\n"
            "]\n",
            encoding="utf-8",
        )

        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        entradas = glossario.load_glossary_entry_details(
            str(caminho), prefer_db=False
        )

        # Degrada, como S5 manda: uma regra torta nao desliga as outras.
        self.assertEqual(
            [(o, n, t) for o, n, t, _p, _e in entradas],
            [
                ("rook", "torre", glossario.GLOSSARY_RULE_AUTOMATIC),
                ("queen", "dama", glossario.GLOSSARY_RULE_SUGGESTION),
            ],
        )
        # ...mas avisa, uma vez, dizendo qual valor nao foi entendido.
        self.assertEqual(len(avisos), 1)
        self.assertIn("'perto'", avisos[0])
        self.assertNotIn("automatico", avisos[0])


class SquarePlaceholderTests(unittest.TestCase):
    """O placeholder de casa (ROADMAP 14.7).

    1.235 das 7.105 regras enumeravam casas a mao, e a enumeracao manual tem o
    defeito de toda enumeracao manual: buracos. Sete familias paravam em 56
    regras — faltava a fileira 3 inteira.
    """

    def test_one_rule_becomes_sixty_four(self):
        regras = glossario.expand_square_placeholder(
            ("@casa@-torre", "torre de @casa@")
        )
        self.assertEqual(len(regras), 64)
        self.assertIn(("a1-torre", "torre de a1"), regras)
        self.assertIn(("e3-torre", "torre de e3"), regras)
        self.assertIn(("h8-torre", "torre de h8"), regras)

    def test_a_rule_without_the_placeholder_is_untouched(self):
        self.assertEqual(
            glossario.expand_square_placeholder(("rook", "torre")),
            [("rook", "torre")],
        )

    def test_priority_survives_the_expansion(self):
        regras = glossario.expand_square_placeholder(("@casa@ x", "y @casa@", 3))
        self.assertEqual(regras[0], ("a1 x", "y a1", 3))

    def test_the_original_decides_the_expansion(self):
        """Sem placeholder no original nao ha o que resolver: expandir daria 64
        regras iguais para um padrao unico, mudando o que a regra casa."""
        self.assertEqual(
            glossario.expand_square_placeholder(("torre", "torre de @casa@")),
            [("torre", "torre de @casa@")],
        )

    def test_loading_expands_and_the_editor_still_sees_one_entry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n"
            "    ('@casa@-torre', 'torre de @casa@'),\n"
            "]\n",
            encoding="utf-8",
        )

        entradas = glossario.load_glossary_entry_details(str(caminho), prefer_db=False)
        self.assertEqual(len(entradas), 1, "o editor edita a linha com o placeholder")

        regras = glossario.load_suggestion_substitutions(str(caminho))
        self.assertEqual(len(regras), 64)
        self.assertEqual(
            glossario.apply_all_substitutions("o e3-torre domina", regras),
            "o torre de e3 domina",
        )

    def test_the_real_glossary_uses_the_placeholder(self):
        """O colapso aconteceu: o arquivo versionado nao volta a enumerar casas.

        Falhar aqui significa que alguem reescreveu uma familia casa a casa —
        1.203 linhas de volta, com os buracos de volta junto.
        """
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        entradas = glossario.load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        com_placeholder = [
            orig
            for orig, _new, _tipo, _prio, _escopo in entradas
            if glossario.GLOSSARY_SQUARE_PLACEHOLDER in orig
        ]
        self.assertGreaterEqual(len(com_placeholder), 20)

        casa_literal = re.compile(r"\b[a-h][1-8]\b")
        enumeradas = [
            orig
            for orig, _new, _tipo, _prio, _escopo in entradas
            if casa_literal.search(orig)
        ]
        # Sobram so as 28 automaticas de peao, que ficaram literais de proposito
        # para nao mudar o tipo de 91 padroes (ROADMAP 14.7).
        self.assertLessEqual(len(enumeradas), 40)


class LanguageScopeTests(unittest.TestCase):
    """Escopo de idioma por regra (garantia S11, ROADMAP 15.1).

    O glossario era global: as regras que corrigem portugues rodavam sobre a
    traducao para o italiano tambem, e `('movimento', 'lance')` transformava
    `il movimento` em `il lance`.
    """

    def test_the_scope_names_the_target(self):
        self.assertTrue(glossario.scope_matches("pt", "en", "pt"))
        self.assertFalse(glossario.scope_matches("pt", "en", "it"))
        self.assertTrue(glossario.scope_matches("", "en", "it"), "sem escopo vale sempre")

    def test_the_pair_form_requires_both(self):
        self.assertTrue(glossario.scope_matches("en>pt", "en", "pt"))
        self.assertFalse(glossario.scope_matches("en>pt", "es", "pt"))

    def test_a_pair_scope_does_not_match_an_undeclared_source(self):
        """Em "Detectar" nao ha como afirmar que o original esta em ingles, e
        aplicar seria um palpite — a mesma escolha da correcao de lances (P3)."""
        self.assertFalse(glossario.scope_matches("en>pt", "", "pt"))

    def test_no_declared_pair_filters_nothing(self):
        """O comportamento de antes desta versao, e o que mantem de pe todo
        chamador que nao passa idioma."""
        self.assertTrue(glossario.scope_matches("pt", None, None))

    def test_star_and_empty_mean_the_same(self):
        self.assertEqual(glossario.normalize_glossary_scope("*"), "")
        self.assertEqual(glossario.normalize_glossary_scope(None), "")
        self.assertEqual(glossario.normalize_glossary_scope(" pt "), "pt")

    def test_the_portuguese_rule_no_longer_reaches_italian(self):
        """O dano medido que abriu a secao 15, agora com o escopo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "escopo = 'pt'\n"
            "substituicoes = [\n"
            "    ('movimento', 'lance', 'automatic'),\n"
            "    ('\\u00d7', 'x', 'automatic', 0, '*'),\n"
            "]\n",
            encoding="utf-8",
        )

        para_it = load_automatic_substitutions(
            str(caminho), source_language="en", target_language="it"
        )
        para_pt = load_automatic_substitutions(
            str(caminho), source_language="en", target_language="pt"
        )

        self.assertEqual(
            glossario.apply_all_substitutions("Il movimento della torre", para_it),
            "Il movimento della torre",
        )
        self.assertEqual(
            glossario.apply_all_substitutions("O movimento da torre", para_pt),
            "O lance da torre",
        )
        # A regra de notacao e global de proposito: `×` nao e portugues.
        self.assertEqual(
            glossario.apply_all_substitutions("N×d4", para_it), "Nxd4"
        )

    def test_a_file_without_the_declaration_behaves_exactly_as_before(self):
        """Retrocompatibilidade: sem `escopo`, toda regra vale para todo par."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
        )

        self.assertEqual(glossario.glossary_default_scope(str(caminho)), "")
        for destino in ("pt", "it", "ru"):
            with self.subTest(destino=destino):
                regras = load_suggestion_substitutions(
                    str(caminho), source_language="en", target_language=destino
                )
                self.assertEqual(regras, [("rook", "torre")])

    def test_the_declaration_is_one_line_and_the_rules_inherit_it(self):
        """O argumento do formato: declarar uma vez em vez de escrever `, 'pt'`
        em cinco mil e setecentas regras, que seria um diff do arquivo inteiro."""
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("×", "x", "automatic", 0, ""),
            ("bishop", "alfiere", "suggestion", 0, "it"),
        ]
        texto = glossario._serialize_entries(entradas, default_scope="pt")

        self.assertIn("escopo = 'pt'", texto)
        # Herda: o campo nao aparece.
        self.assertIn("    ('rook', 'torre'),\n", texto)
        # Discorda: aparece, e `'*'` e como se escreve "todo par".
        self.assertIn("('×', 'x', 'automatic', 0, '*'),", texto)
        self.assertIn("('bishop', 'alfiere', 'suggestion', 0, 'it'),", texto)

    def test_the_round_trip_through_the_file_preserves_every_scope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("×", "x", "automatic", 0, ""),
            ("bishop", "alfiere", "suggestion", 0, "it"),
        ]
        caminho.write_text(
            glossario._serialize_entries(entradas, default_scope="pt"),
            encoding="utf-8",
        )

        relidas = load_glossary_entry_details(
            str(caminho), deduplicate=False, prefer_db=False
        )
        self.assertEqual(relidas, entradas)

    def test_saving_an_entry_keeps_the_file_declaration(self):
        """Sem isto, a primeira gravacao pela janela apagaria o `escopo = 'pt'` e
        as milhares de regras portuguesas voltariam a ser globais."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "escopo = 'pt'\nsubstituicoes = [\n    ('rook', 'torre'),\n]\n",
            encoding="utf-8",
        )

        glossario.add_glossary_entry("queen", "dama", path=str(caminho))

        texto = caminho.read_text(encoding="utf-8")
        self.assertIn("escopo = 'pt'", texto)
        relidas = load_glossary_entry_details(
            str(caminho), deduplicate=False, prefer_db=False
        )
        self.assertEqual(
            relidas,
            [
                ("rook", "torre", "suggestion", 0, "pt"),
                ("queen", "dama", "suggestion", 0, "pt"),
            ],
            "a entrada nova herda o padrao do arquivo",
        )

    def test_the_scope_survives_the_round_trip_through_the_database(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "glossario.db"
        sync_glossary_database(
            [("rook", "torre", "suggestion", 0, "pt")], db_path=str(db)
        )
        self.assertEqual(
            load_glossary_entry_details_from_db(str(db)),
            [("rook", "torre", "suggestion", 0, "pt")],
        )

    def test_the_csv_carries_the_scope_and_tolerates_its_absence(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        csv_path = Path(tmp.name) / "g.csv"
        glossario.export_glossary_csv(
            str(csv_path), entries=[("rook", "torre", "suggestion", 0, "pt")]
        )
        self.assertEqual(
            glossario.read_glossary_csv(str(csv_path)),
            [("rook", "torre", "suggestion", 0, "pt")],
        )

        sem_coluna = Path(tmp.name) / "antigo.csv"
        sem_coluna.write_text(
            "original,replacement\nrook,torre\n", encoding="utf-8"
        )
        self.assertEqual(
            glossario.read_glossary_csv(str(sem_coluna)),
            [("rook", "torre", "suggestion", 0, "")],
        )

    def test_rules_for_different_targets_do_not_conflict(self):
        """Elas nunca sao carregadas juntas, entao acusa-las de conflito seria
        descrever uma briga que nao acontece."""
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("rook", "tour", "suggestion", 0, "fr"),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_an_unscoped_rule_still_conflicts_with_a_scoped_one(self):
        """Escopo vazio cruza com todos: a regra global alcanca o par da outra."""
        entradas = [
            ("rook", "torre", "suggestion", 0, ""),
            ("rook", "tour", "suggestion", 0, "fr"),
        ]
        self.assertEqual(sorted(glossario.glossary_conflicts(entradas)), [0, 1])

    def test_an_unknown_scope_language_warns_instead_of_going_global(self):
        """Degradar para "vale para todos" espalharia a regra em vez de
        limita-la, que e o oposto do que a intencao diz."""
        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n    ('rook', 'torre', 'suggestion', 0, 'ptt'),\n]\n",
            encoding="utf-8",
        )

        entradas = load_glossary_entry_details(str(caminho), prefer_db=False)
        self.assertEqual(glossario.glossary_entry_scope(entradas[0]), "ptt")
        self.assertTrue(any("ptt" in aviso for aviso in avisos))
        # E ela nao casa par nenhum: fica muda, e o aviso e o que a denuncia.
        self.assertEqual(
            load_suggestion_substitutions(
                str(caminho), source_language="en", target_language="pt"
            ),
            [],
        )

    def test_the_real_glossary_declares_the_portuguese_scope(self):
        """O acervo versionado esta escopado. Falhar aqui significa que o
        `escopo = 'pt'` saiu do arquivo, e as milhares de regras portuguesas
        voltaram a alcancar as traducoes para os outros seis idiomas."""
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        self.assertEqual(glossario.glossary_default_scope(str(path)), "pt")

        entradas = load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        escopos = {glossario.glossary_entry_scope(e) for e in entradas}
        self.assertEqual(escopos, {"pt", ""}, "so 'pt' e as globais de notacao")

        # As globais sao notacao, e nao lingua: nenhuma delas tem letra acentuada
        # nem palavra portuguesa.
        globais = [
            glossario.glossary_entry_pair(e)[0]
            for e in entradas
            if not glossario.glossary_entry_scope(e)
        ]
        self.assertLessEqual(len(globais), 25)
        self.assertIn("×", globais)


class SeedGlossaryTests(unittest.TestCase):
    """O dicionario-semente (garantia S15, ROADMAP 15.2)."""

    def seed_path(self):
        return (
            Path(__file__).resolve().parent.parent
            / "tradutor_pgn"
            / "Substituicoes-semente.txt"
        )

    def test_the_seed_ships_with_the_program(self):
        caminho = self.seed_path()
        self.assertTrue(caminho.exists(), "a semente vem com o programa")
        entradas = glossario.load_seed_entries(str(caminho))
        self.assertGreater(len(entradas), 100)

    def test_every_seed_rule_is_scoped_and_a_suggestion(self):
        """Sem escopo, uma regra da semente para o italiano alcancaria o
        portugues — o defeito que a secao 15 existe para fechar. E `suggestion`
        porque a semente e um palpite generico sobre a terminologia de quem usa.
        """
        for entry in glossario.load_seed_entries(str(self.seed_path())):
            orig, _new = glossario.glossary_entry_pair(entry)
            with self.subTest(orig=orig):
                self.assertTrue(glossario.glossary_entry_scope(entry))
                self.assertEqual(
                    glossario.glossary_entry_type(entry),
                    glossario.GLOSSARY_RULE_SUGGESTION,
                )

    def test_no_seed_scope_names_an_unknown_language(self):
        entradas = glossario.load_seed_entries(str(self.seed_path()))
        self.assertEqual(glossario.unknown_scope_languages(entradas), [])

    def test_the_seed_gives_terminology_to_a_language_that_had_none(self):
        """Cinco idiomas tinham ZERO regras. Agora tem o nucleo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vazio = Path(tmp.name) / "Substituicoes.txt"
        vazio.write_text("substituicoes = []\n", encoding="utf-8")

        for destino, esperado in (("it", "alfiere"), ("de", "Läufer"), ("ru", "слон")):
            with self.subTest(destino=destino):
                regras = load_interactive_substitutions(
                    str(vazio),
                    source_language="en",
                    target_language=destino,
                    seed_path=str(self.seed_path()),
                )
                self.assertIn(("bishop", esperado), [(r[0], r[1]) for r in regras])

    def test_the_user_rule_always_wins(self):
        """Garantia S15: para o mesmo padrao no mesmo escopo, a semente sai."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n"
            "    ('bishop', 'o meu bispo', 'suggestion', 0, 'it'),\n"
            "]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        para_bishop = [r[1] for r in regras if r[0] == "bishop"]
        self.assertEqual(para_bishop, ["o meu bispo"])

    def test_an_unscoped_user_rule_also_beats_the_seed(self):
        """Uma decisao que vale para todo par vence a semente do par especifico:
        o usuario disse "sempre assim", e a semente e o palpite."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n    ('bishop', 'sempre assim'),\n]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        self.assertEqual([r[1] for r in regras if r[0] == "bishop"], ["sempre assim"])

    def test_the_seed_yields_on_a_case_difference_too(self):
        """A licao de S12: uma semente em minusculas engoliria a versao
        capitalizada do usuario sem que nada dissesse."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n"
            "    ('Bishop', 'O Meu Bispo', 'suggestion', 0, 'it'),\n"
            "]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        self.assertEqual(
            [(r[0], r[1]) for r in regras if r[0].casefold() == "bishop"],
            [("Bishop", "O Meu Bispo")],
        )

    def test_a_broken_seed_does_not_stop_the_user_glossary(self):
        """A semente e conveniencia: um defeito nela nao pode desligar o
        glossario de quem usa. Mas tambem nao pode ser silencioso — ela vem com
        o programa, entao o defeito e nosso."""
        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        quebrada = Path(tmp.name) / "semente.txt"
        quebrada.write_text("isto nao e python {{{", encoding="utf-8")
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
        )

        entradas = load_glossary_entry_details(str(do_usuario), prefer_db=False)
        regras = glossario._seed_rules_for(
            entradas,
            {glossario.GLOSSARY_RULE_SUGGESTION},
            source_language="en",
            target_language="pt",
            seed_path=str(quebrada),
        )
        self.assertEqual(regras, [])
        self.assertTrue(any("semente" in aviso for aviso in avisos))


class CuratedGlossaryTests(unittest.TestCase):
    """O que a curadoria da secao 14 corrigiu no `Substituicoes.txt` real.

    Cada asserto fixa uma decisao de xadrez, nao uma linha de codigo: sem
    isto, a proxima edicao do glossario pode desfazer a correcao sem que nada
    acuse.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            raise unittest.SkipTest("Substituicoes.txt nao esta neste checkout")
        cls.entradas = glossario.load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        cls.por_padrao = {}
        for orig, new, tipo, prio, _escopo in cls.entradas:
            cls.por_padrao.setdefault(orig, []).append((new, tipo, prio))

    def substituicoes(self, padrao):
        return [new for new, _tipo, _prio in self.por_padrao.get(padrao, [])]

    def test_the_evaluation_symbols_name_the_right_side(self):
        """`=/+` (⩱) e vantagem das PRETAS. O arquivo dava a mesma leitura para
        ele e para `+/=`, entao metade das avaliacoes saia invertida."""
        self.assertEqual(
            self.substituicoes("=/+"), ["com leve superioridade para as pretas"]
        )
        self.assertEqual(
            self.substituicoes("+/="), ["as brancas têm leve superioridade"]
        )
        self.assertEqual(
            self.substituicoes("-+"), ["com vantagem decisiva das pretas"]
        )
        self.assertEqual(
            self.substituicoes("+-"), ["com vantagem decisiva das brancas"]
        )

    def test_castling_is_a_noun_and_back_rank_is_the_last_one(self):
        self.assertEqual(self.substituicoes("castling"), ["roque"])
        self.assertEqual(self.substituicoes("back rank"), ["última fila"])
        self.assertEqual(self.substituicoes("back-rank"), ["última fila"])

    def test_the_rules_that_broke_portuguese_are_gone(self):
        """Medidas, nao supostas: cada uma corrompeu uma frase de teste real.

        As que o relatorio inicial acusava e a fronteira de palavra protegia
        (`the`, `if`, `with`, `by`) ficaram — nenhuma delas e palavra
        portuguesa, e nenhuma corrompeu frase nenhuma.
        """
        for padrao in ("for", "por", "#", "luz", "negro"):
            with self.subTest(padrao=padrao):
                self.assertEqual(self.por_padrao.get(padrao, []), [])

    def test_rank_and_file_are_not_inverted_anymore(self):
        """As genericas convertiam toda 'fileira' em 'coluna'; as precisas
        alcancam so o que vem depois de uma letra de coluna."""
        self.assertEqual(self.por_padrao.get("-fileira", []), [])
        self.assertEqual(self.substituicoes("e-fileira"), ["coluna e"])

    def test_the_junk_deletion_rules_are_cleanup(self):
        """Apagar lixo de conversao e trabalho de limpeza: roda antes da API, e
        assim para de pagar traducao de lixo (garantia S14)."""
        delecoes = [
            (orig, tipo)
            for orig, new, tipo, _prio, _escopo in self.entradas
            if not new
        ]
        self.assertTrue(delecoes)
        for orig, tipo in delecoes:
            with self.subTest(orig=orig):
                self.assertEqual(tipo, glossario.GLOSSARY_RULE_CLEANUP)

    def test_no_rule_returns_what_it_found(self):
        for orig, new, _tipo, _prio, _escopo in self.entradas:
            if orig:
                with self.subTest(orig=orig):
                    self.assertNotEqual(orig, new)

    def test_the_priority_field_is_finally_in_use(self):
        """A prioridade existia desde o item 1.5 e nunca havia sido usada em
        regra nenhuma das 7.105. A que a usa e `('Black', 'as pretas')`, que
        estava morta: o artigo e gramatica, e a prioridade a revive sem apagar
        a concorrente."""
        priorizadas = [
            (orig, new, prio)
            for orig, new, _tipo, prio, _escopo in self.entradas
            if prio != glossario.GLOSSARY_PRIORITY_DEFAULT
        ]
        self.assertIn(("Black", "as pretas", 1), priorizadas)


class GlossaryOrderingKeyTests(unittest.TestCase):
    """A chave do cache de ordenacao era O(n) por consulta (ROADMAP 20.6).

    Uma tupla de 7.334 elementos montada e hasheada a cada tecla do editor:
    1,75 ms dos 9,15 ms que uma tecla custava. Com o numero de versao, 0,0002 ms.
    """

    def test_a_loaded_list_has_a_constant_sized_key(self):
        regras = versioned_rules([(f"palavra {i}", f"outra {i}") for i in range(5000)])

        chave = glossario._ordered_rules_cache_key(regras)

        self.assertEqual(len(chave), 2, "a chave nao pode crescer com as regras")
        self.assertIs(chave[0], VersionedRules)

    def test_two_loads_of_the_same_content_do_not_share_the_entry(self):
        pares = [("a", "b"), ("cc", "dd")]
        primeira = versioned_rules(pares)
        segunda = versioned_rules(pares)

        self.assertNotEqual(
            glossario._ordered_rules_cache_key(primeira),
            glossario._ordered_rules_cache_key(segunda),
        )
        # E as duas continuam recebendo a MESMA ordem: a chave nova custa uma
        # reordenacao, nunca uma resposta errada.
        self.assertEqual(
            order_rules_by_specificity(primeira),
            order_rules_by_specificity(segunda),
        )

    def test_mutating_the_list_invalidates_the_cached_order(self):
        """O modo de falha que a chave por conteudo nao tinha.

        Uma lista marcada por identidade que mude no lugar continuaria valendo
        como a mesma, e a ordem devolvida traria regras que nao estao mais nela.
        Cada mutacao renova a versao.
        """
        regras = versioned_rules([("curta", "x")])
        self.assertEqual(order_rules_by_specificity(regras), [("curta", "x")])

        regras.append(("uma regra bem mais longa", "y"))

        self.assertEqual(
            order_rules_by_specificity(regras),
            [("uma regra bem mais longa", "y"), ("curta", "x")],
        )

    def test_every_mutation_renews_the_version(self):
        regras = versioned_rules([("a", "b"), ("cc", "dd"), ("eee", "fff")])
        vistas = {regras.version}

        for mutacao in (
            lambda r: r.append(("z", "z")),
            lambda r: r.extend([("y", "y")]),
            lambda r: r.insert(0, ("x", "x")),
            lambda r: r.remove(("x", "x")),
            lambda r: r.pop(),
            lambda r: r.sort(),
            lambda r: r.reverse(),
            lambda r: r.clear(),
            lambda r: r.__setitem__(0, ("w", "w")),
            lambda r: r.__delitem__(0),
            lambda r: r.__iadd__([("v", "v")]),
            lambda r: r.__imul__(2),
        ):
            antes = regras.version
            if not regras:
                regras.extend([("a", "b"), ("cc", "dd")])
            mutacao(regras)
            self.assertNotEqual(
                regras.version, antes, f"{mutacao} nao renovou a versao"
            )
            self.assertNotIn(regras.version, vistas)
            vistas.add(regras.version)

    def test_a_plain_list_still_gets_the_content_key(self):
        """Uma lista literal — de teste, ou escrita a mao — continua valendo."""
        chave = glossario._ordered_rules_cache_key([("a", "b"), ("cc", "dd", 5)])

        self.assertEqual(chave, (("a", "b", 0), ("cc", "dd", 5)))

    def test_the_loaders_hand_out_versioned_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "Substituicoes.txt"
            arquivo.write_text(
                "substituicoes = [\n"
                "    ('knight', 'cavalo', 'suggestion', 0, '*'),\n"
                "]\n",
                encoding="utf-8",
            )

            regras = load_interactive_substitutions(str(arquivo))

        self.assertIsInstance(regras, VersionedRules)
        self.assertEqual(len(glossario._ordered_rules_cache_key(regras)), 2)

    def test_the_suggestions_are_the_same_with_and_without_the_version(self):
        pares = [
            ("knight", "cavalo"),
            ("the knight on f3", "o cavalo em f3"),
            ("rook", "torre"),
        ]
        texto = "The knight on f3 and the rook are placed."

        self.assertEqual(
            find_glossary_suggestions(texto, versioned_rules(pares)),
            find_glossary_suggestions(texto, list(pares)),
        )


# ===========================================================================
# ROADMAP 28.5: o glossario com escopo (S19), impacto (S20) e historico (S21)
# ===========================================================================


class AutomaticRulesScopeTests(unittest.TestCase):
    """Garantia S19: "Aplicar Automaticas" tem escopo, e o padrao e "so pendentes".

    A consulta nao filtrava por `verified`: promover uma regra na linha 500 e
    clicar a ferramenta reescrevia as 499 que o revisor ja tinha aprovado — 9
    das 39 linhas que as regras de hoje alterariam no banco de dev.
    """

    REGRAS = [("rainha", "dama")]

    def _semear(self, db_path):
        """Quatro linhas que casam: pendente e verificada, com e sem arquivo."""
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "pending in file", "A rainha pendente no arquivo", "pt", "en")
        save_translation(cur, "verified in file", "A rainha verificada no arquivo", "pt", "en")
        save_translation(cur, "pending outside", "A rainha pendente fora", "pt", "en")
        save_translation(cur, "verified outside", "A rainha verificada fora", "pt", "en")
        ids = resolve_comment_ids(
            cur, "pt",
            ["pending in file", "verified in file", "pending outside", "verified outside"],
            "en",
        )
        set_translation_verified_by_id(cur, ids["verified in file"], True)
        set_translation_verified_by_id(cur, ids["verified outside"], True)
        self.arquivo = str(db_path.parent / "cap01.pgn")
        record_occurrences(
            cur, self.arquivo,
            [(1, 1, 1, "pending in file"), (2, 1, 2, "verified in file")],
            ids,
        )
        conn.commit()
        conn.close()
        return ids

    def _traducoes(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return dict(
                conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()

    def _alteradas(self, db_path):
        return sorted(
            orig for orig, texto in self._traducoes(db_path).items() if "dama" in texto
        )

    # ------------------------------------------------------------ o banco

    def test_the_default_scan_still_reaches_every_row(self):
        """Sem pedir nada, a funcao de banco e a de antes: o filtro e opt-in, e
        quem decide o padrao "so pendentes" e a ferramenta (teste abaixo)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            stats = apply_database_automatic_rules(
                str(db_path), target_language="pt", automatic_rules=self.REGRAS,
                create_backup=False,
            )
            self.assertEqual(stats["changed"], 4)

    def test_only_pending_leaves_the_verified_rows_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            preview = analyze_database_automatic_rules(
                str(db_path), target_language="pt", automatic_rules=self.REGRAS,
                only_pending=True,
            )
            stats = apply_database_automatic_rules(
                str(db_path), target_language="pt", automatic_rules=self.REGRAS,
                create_backup=False, only_pending=True,
            )
            self.assertEqual(preview["changed"], 2, "a previa tem de usar o mesmo escopo")
            self.assertEqual(stats["changed"], 2)
            self.assertEqual(
                self._alteradas(db_path), ["pending in file", "pending outside"]
            )
            self.assertEqual(
                self._traducoes(db_path)["verified in file"],
                "A rainha verificada no arquivo",
                "linha verificada reescrita no escopo 'so pendentes'",
            )

    def test_the_file_scope_reaches_only_the_rows_of_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            stats = apply_database_automatic_rules(
                str(db_path), target_language="pt", automatic_rules=self.REGRAS,
                create_backup=False, only_pending=True, source_file=self.arquivo,
            )
            self.assertEqual(stats["changed"], 1)
            self.assertEqual(self._alteradas(db_path), ["pending in file"])

    def test_a_file_the_database_never_saw_matches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            preview = analyze_database_automatic_rules(
                str(db_path), target_language="pt", automatic_rules=self.REGRAS,
                source_file=str(Path(tmp) / "outro.pgn"),
            )
            self.assertEqual((preview["scanned"], preview["changed"]), (0, 0))

    # -------------------------------------------------------- a ferramenta

    def _dialogos(self, confirmar=True):
        vistos = []
        self.addCleanup(setattr, db_tools, "messagebox", db_tools.messagebox)
        db_tools.messagebox = types.SimpleNamespace(
            askyesno=lambda t, m, **_kw: (vistos.append(("askyesno", t, m)), confirmar)[1],
            showinfo=lambda t, m, **_kw: vistos.append(("info", t, m)),
            showerror=lambda t, m, **_kw: vistos.append(("error", t, m)),
        )
        return vistos

    def _rodar(self, db_path, **kwargs):
        SynchronousProgress().install(self, db_tools)
        recebidos = []
        db_tools.apply_automatic_rules_to_database(
            types.SimpleNamespace(output_db=str(db_path), translation_cache={}, root=None),
            target_language="pt",
            on_finish=recebidos.append,
            automatic_rules=self.REGRAS,
            **kwargs,
        )
        return recebidos

    def test_the_tool_defaults_to_pending_rows_and_says_so(self):
        """O padrao e a garantia: sem pedir, nenhuma verificada muda, e o dialogo
        de confirmacao diz "so pendentes" — o usuario le o escopo, nao o supoe."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos(confirmar=True)

            recebidos = self._rodar(db_path)

            self.assertEqual(recebidos[0]["changed"], 2)
            self.assertEqual(
                self._alteradas(db_path), ["pending in file", "pending outside"]
            )
            pergunta = [m for tipo, _t, m in vistos if tipo == "askyesno"][0]
            self.assertIn("só pendentes", pergunta)
            self.assertNotIn("verificadas", pergunta.split("Escopo:")[1].split("\n")[0])

    def test_the_tool_reaches_verified_rows_only_when_the_scope_asks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos(confirmar=True)

            recebidos = self._rodar(db_path, include_verified=True)

            self.assertEqual(recebidos[0]["changed"], 4)
            pergunta = [m for tipo, _t, m in vistos if tipo == "askyesno"][0]
            self.assertIn("pendentes e verificadas", pergunta)

    def test_the_tool_names_the_file_and_stays_inside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos(confirmar=True)

            recebidos = self._rodar(db_path, source_file=self.arquivo)

            self.assertEqual(recebidos[0]["changed"], 1)
            self.assertEqual(self._alteradas(db_path), ["pending in file"])
            pergunta = [m for tipo, _t, m in vistos if tipo == "askyesno"][0]
            self.assertIn("arquivo cap01.pgn", pergunta)
            resumo = [m for tipo, _t, m in vistos if tipo == "info"][0]
            self.assertIn("arquivo cap01.pgn", resumo)

    def test_explicit_rules_are_used_instead_of_the_glossary(self):
        """`automatic_rules` e o caminho de "Trocas repetidas": UMA regra recem
        criada, sem carregar (nem depender de) o glossario inteiro."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._dialogos(confirmar=True)
            chamadas = []
            self.addCleanup(
                setattr, db_tools, "load_automatic_substitutions",
                db_tools.load_automatic_substitutions,
            )
            db_tools.load_automatic_substitutions = lambda **kw: chamadas.append(kw) or []

            recebidos = self._rodar(db_path)

            self.assertEqual(chamadas, [], "carregou o glossario com regras explicitas")
            self.assertEqual(recebidos[0]["changed"], 2)

    def test_the_scope_text_lists_every_restriction(self):
        self.assertEqual(
            db_tools.format_automatic_rules_scope("pt"),
            "idioma atual (pt), só pendentes",
        )
        self.assertEqual(
            db_tools.format_automatic_rules_scope(
                "pt", "en", "C:/livros/cap01.pgn", include_verified=True
            ),
            "idioma atual (pt), origem Inglês, arquivo cap01.pgn, pendentes e verificadas",
        )


class PromotionPreviewTests(unittest.TestCase):
    """Garantia S20: promover a `automatic` mostra o impacto antes, fora do Tk.

    `analyze_automatic_translation_updates` ja calculava; o item liga a conta ao
    editor de glossario. A varredura parecida de 2.7 segurou a interface por
    38 s, entao a conta passa por `run_with_progress` — e o teste exige isso.
    """

    ENTRADA = ("Black esta", "as pretas estão", "automatic", 0, "en>pt")

    def _semear(self, db_path):
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "Black is fine", "Black esta bem", "pt", "en")
        save_translation(cur, "Black is ok", "Black esta ok", "pt", "en")
        save_translation(cur, "Black is done", "Black esta verificada", "pt", "en")
        save_translation(cur, "Black is italian", "Black esta italiana", "it", "en")
        save_translation(cur, "Black is spanish", "Black esta espanhola", "pt", "es")
        ids = resolve_comment_ids(cur, "pt", ["Black is done"], "en")
        set_translation_verified_by_id(cur, ids["Black is done"], True)
        conn.commit()
        conn.close()

    def _dialogos(self, confirmar=True):
        vistos = []
        self.addCleanup(setattr, db_tools, "messagebox", db_tools.messagebox)
        db_tools.messagebox = types.SimpleNamespace(
            askyesno=lambda t, m, **_kw: (vistos.append(("askyesno", t, m)), confirmar)[1],
            showinfo=lambda t, m, **_kw: vistos.append(("info", t, m)),
            showerror=lambda t, m, **_kw: vistos.append(("error", t, m)),
        )
        return vistos

    def _rodar(self, db_path, entrada=None):
        progresso = SynchronousProgress()
        progresso.install(self, db_tools)
        decisoes = []
        db_tools.preview_automatic_rule_impact(
            types.SimpleNamespace(output_db=str(db_path), root=None),
            self.ENTRADA if entrada is None else entrada,
            on_decision=decisoes.append,
        )
        return progresso, decisoes

    def test_the_dialog_brings_the_number_and_the_sample(self):
        """A contagem e so das PENDENTES do par da regra: a verificada, a do
        italiano e a vinda do espanhol ficam de fora — sao 2, nao 5."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos(confirmar=True)

            progresso, decisoes = self._rodar(db_path)

            self.assertEqual(decisoes, [True])
            self.assertEqual(len(vistos), 1)
            _tipo, titulo, mensagem = vistos[0]
            self.assertIn("2 tradução(ões) pendente(s) de 2 analisadas", mensagem)
            self.assertIn("'Black esta' -> 'as pretas estão'", mensagem)
            self.assertIn("Antes: Black esta bem", mensagem)
            # "As", e nao "as": a substituicao devolve a caixa do texto casado
            # (`case_adjusted_replacement`), e `Black` comeca em maiuscula. E
            # exatamente o que a previa existe para mostrar antes de promover —
            # a amostra e a saida do pipeline, nao o lado direito da regra.
            self.assertIn("Depois: As pretas estão bem", mensagem)
            self.assertNotIn("verificada", mensagem.split("Exemplos:")[1].split("Uma regra")[0])

    def test_the_count_runs_through_the_progress_window(self):
        """Chamar a varredura direto no callback do botao passaria em tudo acima
        e travaria a janela — e o "teste de thread" que a garantia pede."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._dialogos()

            progresso, _decisoes = self._rodar(db_path)

            self.assertEqual(progresso.titles(), ["Promover a automática"])

    def test_declining_reports_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._dialogos(confirmar=False)
            _progresso, decisoes = self._rodar(db_path)
            self.assertEqual(decisoes, [False])

    def test_a_rule_without_language_scope_scans_the_whole_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos()
            self._rodar(db_path, ("Black esta", "as pretas estão", "automatic", 0, ""))
            self.assertIn("4 tradução(ões) pendente(s) de 4 analisadas", vistos[0][2])

    def test_a_rule_that_changes_nothing_still_asks_with_the_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            vistos = self._dialogos()
            _p, decisoes = self._rodar(db_path, ("inexistente", "x", "automatic", 0, "pt"))
            self.assertIn("não alteraria nenhuma tradução pendente", vistos[0][2])
            self.assertEqual(decisoes, [True])

    def test_a_failed_measurement_does_not_promote(self):
        """"Nao consegui medir" nao e licenca para criar uma regra que reescreve
        sem perguntar: o erro aparece e a decisao e `False`."""
        with tempfile.TemporaryDirectory() as tmp:
            vistos = self._dialogos()
            _p, decisoes = self._rodar(Path(tmp) / "nao-existe" / "cache.db")
            self.assertEqual(decisoes, [False])
            self.assertEqual([tipo for tipo, _t, _m in vistos], ["error"])

    def test_the_square_placeholder_is_expanded_before_counting(self):
        """A regra e medida como o pipeline a aplica (S9): `@casa@` vale 64 casas."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            save_translation(conn.cursor(), "the d5 knight", "o cavalo-d5 avança", "pt", "en")
            conn.commit()
            conn.close()
            vistos = self._dialogos()
            self._rodar(db_path, ("cavalo-@casa@", "cavalo de @casa@", "automatic", 0, "pt"))
            self.assertIn("1 tradução(ões) pendente(s)", vistos[0][2])
            self.assertIn("Depois: o cavalo de d5 avança", vistos[0][2])


class RepeatedEditsTests(unittest.TestCase):
    """Garantia S21: os pares que a revisao mais trocou, e se ja ha regra."""

    def test_token_replacements_return_only_the_replaced_blocks(self):
        pares = repeated_edits.token_replacements(
            "White wins the troca after 5.Nf3 in this jogo",
            "White wins the qualidade after 5.Nf3 in this partida",
        )
        self.assertEqual(pares, [("troca", "qualidade"), ("jogo", "partida")])

    def test_pure_insertions_and_deletions_are_not_pairs(self):
        """`'' -> 'de'` foi a troca mais frequente da revisao e nao e regra de
        nada: uma regra precisa de um texto para casar (e o P7 resolveu isso)."""
        self.assertEqual(repeated_edits.token_replacements("depois 5.Nf3", "depois de 5.Nf3"), [])
        self.assertEqual(repeated_edits.token_replacements("final de jogo", "final"), [])

    def test_multiword_blocks_stay_together(self):
        self.assertEqual(
            repeated_edits.token_replacements("White renunciou.", "as brancas abandonaram."),
            [("White renunciou", "as brancas abandonaram")],
        )

    def test_counting_separates_occurrences_from_lines(self):
        eventos = [
            (1, "troca boa, troca ruim", "qualidade boa, qualidade ruim"),
            (2, "a troca", "a qualidade"),
            (3, "o jogo", "a partida"),
            (4, "o jogo", "a partida"),
            (5, "unica", "única"),
        ]
        itens = repeated_edits.count_repeated_edits(eventos)
        self.assertEqual(
            [(i["old"], i["new"], i["count"], i["lines"], i["example_id"]) for i in itens],
            [
                ("troca", "qualidade", 3, 2, 1),
                ("o jogo", "a partida", 2, 2, 3),
            ],
        )

    def test_the_minimum_and_the_limit_are_honoured(self):
        eventos = [(n, "ax", "ay") for n in range(3)] + [(9, "bx", "bz")]
        self.assertEqual(
            [i["old"] for i in repeated_edits.count_repeated_edits(eventos)],
            ["ax"],
        )
        self.assertEqual(
            [i["old"] for i in repeated_edits.count_repeated_edits(eventos, min_count=1)],
            ["ax", "bx"],
        )
        self.assertEqual(
            [i["old"] for i in repeated_edits.count_repeated_edits(eventos, min_count=1, limit=1)],
            ["ax"],
        )

    # ------------------------------------------------------- a coluna "regra"

    ENTRADAS = [
        ("cheque", "xeque", "automatic", 0, "pt"),
        ("troca", "permuta", "suggestion", 0, "pt"),
        ("Brancas", "brancas", "suggestion", 0, "pt"),
        ("o jogo", "a partida", "suggestion", 0, "pt"),
    ]

    def status(self, old, new):
        indice = repeated_edits.glossary_rule_index(self.ENTRADAS)
        estado = repeated_edits.rule_status(indice, old, new)
        return estado, repeated_edits.format_rule_status(estado, old, new)

    def test_a_rule_that_produces_the_reviewers_text_is_named_by_type(self):
        self.assertEqual(self.status("cheque", "xeque"), (("automatic", "xeque"), "automática"))
        self.assertEqual(
            self.status("o jogo", "a partida"), (("suggestion", "a partida"), "sugestão")
        )

    def test_a_rule_that_fires_but_produces_something_else_says_what(self):
        estado, rotulo = self.status("troca", "qualidade")
        self.assertEqual(estado, ("suggestion", "permuta"))
        self.assertEqual(rotulo, "sugestão (produz 'permuta')")

    def test_an_inert_rule_is_not_reported_as_no_rule(self):
        """`Brancas -> brancas` existe no glossario do usuario e nunca produz nada:
        a substituicao devolve a caixa do texto casado. E o pipeline de verdade
        (`apply_substitution`) que decide, nao uma comparacao de strings."""
        estado, rotulo = self.status("Brancas", "brancas")
        self.assertEqual(estado, ("suggestion", "Brancas"))
        self.assertEqual(rotulo, "sugestão (não altera o texto)")

    def test_no_rule_is_no_rule(self):
        self.assertEqual(self.status("são", "estão"), (None, "sem regra"))

    def test_the_case_insensitive_rule_covers_the_capitalised_change(self):
        indice = repeated_edits.glossary_rule_index([("jogo", "partida", "automatic", 0, "pt")])
        self.assertEqual(
            repeated_edits.rule_status(indice, "Jogo", "Partida"), ("automatic", "Partida")
        )

    def test_the_report_annotates_every_pair(self):
        eventos = [(1, "troca", "qualidade"), (2, "troca", "qualidade"), (3, "cheque", "xeque"), (4, "cheque", "xeque")]
        relatorio = repeated_edits.repeated_edits_report(eventos, self.ENTRADAS)
        self.assertEqual(
            [(i["old"], i["rule_label"]) for i in relatorio],
            [("cheque", "automática"), ("troca", "sugestão (produz 'permuta')")],
        )


class FileEditEventsTests(unittest.TestCase):
    """`fetch_file_edit_events`: so edicoes humanas, com mudanca, das linhas da obra."""

    def _semear(self, db_path):
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "in file", "a troca", "pt", "en")
        save_translation(cur, "outside", "a troca fora", "pt", "en")
        save_translation(cur, "other pair", "a troca italiana", "it", "en")
        save_translation(cur, "other source", "a troca espanhola", "pt", "es")
        ids = resolve_comment_ids(cur, "pt", ["in file", "outside"], "en")
        ids_it = resolve_comment_ids(cur, "it", ["other pair"], "en")
        ids_es = resolve_comment_ids(cur, "pt", ["other source"], "es")
        self.arquivo = str(db_path.parent / "livro.pgn")
        record_occurrences(
            cur, self.arquivo,
            [(1, 1, 1, "in file"), (2, 1, 2, "other pair"), (3, 1, 3, "other source")],
            {**ids, **ids_it, **ids_es},
        )
        # Humana, com mudanca: entra.
        update_translation_by_id(cur, ids["in file"], "a qualidade", history_action="edit")
        # Humana, SEM mudanca de texto ("Salvar e verificar" com o texto igual):
        # fora. `mark_verified` e o que faz a entrada existir — sem mudar nem
        # texto nem status a funcao nao grava historico nenhum, e o cenario nao
        # exercitaria a clausula (foi uma mutacao sobrevivente que mostrou).
        update_translation_by_id(
            cur, ids["in file"], "a qualidade", mark_verified=True,
            history_action="edit_verify",
        )
        # Do programa: fora, mesmo mudando o texto.
        update_translation_by_id(cur, ids["in file"], "a qualidade!", history_action="automatic_rules")
        # Humana, mas de linha que nao esta no arquivo: fora.
        update_translation_by_id(cur, ids["outside"], "a qualidade fora", history_action="edit")
        # Humana, no arquivo, mas de OUTRO destino: fora.
        update_translation_by_id(cur, ids_it["other pair"], "la qualità", history_action="edit")
        # Humana, no arquivo, mesmo destino, OUTRA origem: fora com o filtro de
        # origem, dentro sem ele (o teste seguinte).
        update_translation_by_id(cur, ids_es["other source"], "a qualidade espanhola", history_action="edit")
        conn.commit()
        conn.close()
        return ids

    def test_only_the_human_changes_of_the_files_rows_come_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            ids = self._semear(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                eventos = fetch_file_edit_events(conn.cursor(), self.arquivo, "pt", "en")
            finally:
                conn.close()
            self.assertEqual(eventos, [(ids["in file"], "a troca", "a qualidade")])

    def test_without_a_source_filter_every_origin_of_the_target_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                pt = fetch_file_edit_events(conn.cursor(), self.arquivo, "pt")
                it = fetch_file_edit_events(conn.cursor(), self.arquivo, "it")
            finally:
                conn.close()
            self.assertEqual(
                sorted(e[2] for e in pt), ["a qualidade", "a qualidade espanhola"]
            )
            self.assertEqual([e[2] for e in it], ["la qualità"])


if __name__ == "__main__":
    unittest.main()
