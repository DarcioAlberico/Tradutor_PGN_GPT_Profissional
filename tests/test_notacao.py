"""Notacao de xadrez e prosa: letras dos lances, ancoras, mascaras, preposicao final.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import unittest
import unittest.mock
from collections import Counter

from tradutor_pgn import app_config
from tradutor_pgn.annotation_mask import (
    has_player_name_tokens,
    mask_annotations,
    restore_annotations,
)
from tradutor_pgn.chess_notation import (
    PIECE_LETTERS,
    extract_moves,
    move_anchors,
    fix_move_notation,
    supports_notation,
)
from tradutor_pgn.prose_fixes import (
    fix_move_spacing,
    fix_piece_square_hyphen,
    fix_trailing_preposition,
    normalize_prose,
    strip_zero_width_spaces,
)
from helpers import setup_module_sandbox, teardown_module_sandbox


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class TrailingPrepositionTests(unittest.TestCase):
    """Garantia P7: o fragmento terminado em preposicao sai com ela.

    Medido no banco de dev (ROADMAP 28.4): 680 originais terminam em `after`,
    a maquina devolveu "depois" sem "de" em 532, e `'' -> 'de'` e a troca mais
    frequente da revisao. A regra so age onde o original prova a forma, e
    nunca inventa.
    """

    def fix(self, original, translation, source="en", target="pt"):
        return fix_trailing_preposition(original, translation, source, target)

    def test_after_gets_its_de_back(self):
        self.assertEqual(
            self.fix("White is clearly better after", "As brancas estao claramente melhores depois"),
            ("As brancas estao claramente melhores depois de", 1),
        )

    def test_capital_and_punctuation_are_preserved(self):
        self.assertEqual(self.fix("After", "Depois"), ("Depois de", 1))
        self.assertEqual(self.fix("and after.", "e depois."), ("e depois de.", 1))
        self.assertEqual(self.fix("(but after)", "(mas depois)"), ("(mas depois de)", 1))

    def test_nothing_to_repair_is_left_alone(self):
        """"depois de" e "apos" ja estao certos; um original sem `after` nao
        justifica mexer, por mais que a traducao termine em "depois"."""
        for original, translation in (
            ("well after", "bem depois de"),
            ("well after", "bem apos"),
            ("and then", "e depois"),
            ("after the game", "depois da partida"),
            ("", "depois"),
            ("after", ""),
        ):
            with self.subTest(original=original, translation=translation):
                self.assertEqual(self.fix(original, translation), (translation, 0))

    def test_an_adverb_before_after_closes_the_sentence(self):
        """"doesn't lose immediately after" termina a frase: "depois" esta certo.
        `right after`/`just after` nao sao excecao — sao "logo depois de"."""
        self.assertEqual(
            self.fix("doesn't lose immediately after", "nao perde imediatamente depois"),
            ("nao perde imediatamente depois", 0),
        )
        self.assertEqual(
            self.fix("wins right after", "ganha logo depois"), ("ganha logo depois de", 1)
        )

    def test_only_the_pair_that_was_measured(self):
        """A tabela e por destino: para o italiano nao ha regra, e uma origem
        declarada que nao e ingles nao casa a linha `en`. Origem nao declarada
        ("Detectar") nao desliga: a palavra `after` so e ingles."""
        self.assertEqual(self.fix("better after", "meglio dopo", target="it"), ("meglio dopo", 0))
        self.assertEqual(self.fix("better after", "melhor depois", source="es"), ("melhor depois", 0))
        self.assertEqual(self.fix("better after", "melhor depois", source=""), ("melhor depois de", 1))


class ProseNormalizationTests(unittest.TestCase):
    """Garantia P5: as normalizacoes so agem onde o original prova a forma.

    Medido no banco de dev (ROADMAP 28.2, camada 2): as formas coladas
    (`10...d5`, `...Cd3`, `12h5`) aparecem 111 vezes na saida da maquina e
    ZERO no original; `cavalo-d5` 131 vezes contra `d5-knight` 413 no original,
    e a revisao trocou 124 por "cavalo de d5"; `U+200B` 68 contra 0.
    """

    def test_the_space_after_the_ellipsis_comes_back_from_the_original(self):
        self.assertEqual(
            fix_move_spacing("After 10... d5 and ... Nd3, then 12 h5", "Depois de 10...d5 e ...Cd3, entao 12h5"),
            ("Depois de 10... d5 e ... Cd3, entao 12 h5", 3),
        )

    def test_a_space_the_original_does_not_have_is_never_invented(self):
        for original, translation in (
            ("threatening ...Qxh2+", "ameacando ...Dxh2+"),   # colado no original
            ("After 10... d5", "Depois de 10...e5"),           # ancora diferente
            ("After 10... d5", "Depois de 11...d5"),           # numero diferente
            ("after 12 h5", "depois de 13h5"),                 # numero colado, numero diferente
            ("after 12 h5", "depois de 12e5"),                 # numero colado, ancora diferente
            ("", "10...d5"),
            ("After 10... d5", ""),
        ):
            with self.subTest(original=original):
                self.assertEqual(fix_move_spacing(original, translation), (translation, 0))

    def test_an_ellipsis_glued_on_both_sides_gets_both_spaces(self):
        """"playing ... b5" vira "jogar...b5": o original prova os dois lados."""
        self.assertEqual(fix_move_spacing("playing ... b5-b4", "jogar...b5-b4"), ("jogar ... b5-b4", 1))
        # sem espaco antes no original, so o de depois volta — mesmo com a
        # traducao colada a palavra anterior
        self.assertEqual(fix_move_spacing("playing... b5-b4", "jogar...b5-b4"), ("jogar... b5-b4", 1))
        self.assertEqual(fix_move_spacing("(... b5)", "(...b5)"), ("(... b5)", 1))

    def test_captures_and_checks_do_not_break_the_anchor(self):
        self.assertEqual(
            fix_move_spacing("after 12... Nxe4+", "depois de 12...Cxe4+"),
            ("depois de 12... Cxe4+", 1),
        )

    def test_the_hyphen_becomes_de_only_with_the_original_square(self):
        self.assertEqual(
            fix_piece_square_hyphen("the d5-knight and the e7-pawn", "o cavalo-d5 e o pe\u00e3o-e7", "pt"),
            ("o cavalo de d5 e o pe\u00e3o de e7", 2),
        )
        # a casa que o original nao tem com hifen fica como esta
        self.assertEqual(
            fix_piece_square_hyphen("the d5-knight", "o cavalo-d5 e a torre-a1", "pt"),
            ("o cavalo de d5 e a torre-a1", 1),
        )
        # so a casa completa: `e-pawn` fica de fora (3 ocorrencias, a revisao nao usou "de")
        self.assertEqual(fix_piece_square_hyphen("the e-pawn", "o pe\u00e3o-e", "pt"), ("o pe\u00e3o-e", 0))

    def test_the_hyphen_rule_is_portuguese_only(self):
        self.assertEqual(fix_piece_square_hyphen("the d5-knight", "il cavallo-d5", "it"), ("il cavallo-d5", 0))
        self.assertEqual(fix_piece_square_hyphen("the d5-knight", "o cavalo-d5", ""), ("o cavalo-d5", 0))

    def test_zero_width_spaces_go_unless_the_original_has_them(self):
        self.assertEqual(strip_zero_width_spaces("a b", "a \u200b \u200bb"), ("a b", 2))
        self.assertEqual(strip_zero_width_spaces("a\u200bb", "a\u200bb"), ("a\u200bb", 0))
        self.assertEqual(strip_zero_width_spaces("a b", "a b"), ("a b", 0))

    def test_normalize_prose_composes_all_four_and_counts(self):
        self.assertEqual(
            normalize_prose(
                "The d5-knight is strong after 12... Nf6, and after",
                "O cavalo-d5 \u200b e forte depois de 12...Cf6, e depois",
                "en",
                "pt",
            ),
            ("O cavalo de d5 e forte depois de 12... Cf6, e depois de", 4),
        )
        self.assertEqual(normalize_prose("A quiet move.", "Um lance tranquilo.", "en", "pt"), ("Um lance tranquilo.", 0))


class PlayerNameMaskTests(unittest.TestCase):
    """Garantia X4: o par de nomes de uma citacao atravessa a API mascarado.

    Medido no banco de dev (ROADMAP 28.3): 821 citacoes, 19 com o NOME
    traduzido ("E. Can" -> "E. Pode", "K. Lie" -> "K. Mentira"). A sede fica de
    fora da mascara — o revisor a traduz em um terco das verificadas.
    """

    def test_the_pair_is_masked_and_the_venue_is_not(self):
        masked, tokens = mask_annotations("and White resigned in G. Sax-G. Mohr, Maribor 2000.")
        self.assertEqual(masked, "and White resigned in \u27e60\u27e7, Maribor 2000.")
        self.assertEqual(tokens, ["G. Sax-G. Mohr"])

    def test_particles_and_two_letter_initials_are_part_of_the_name(self):
        for texto, nome in (
            ("was N. De Firmian-S. Kudrin, USA 1999, and now", "N. De Firmian-S. Kudrin"),
            ("in L. Van Wely-Ju. Polgar, Wijk aan Zee 2001", "L. Van Wely-Ju. Polgar"),
            ("V. Anand-G. Kasparov, PCA World Ch match (Game 9)", "V. Anand-G. Kasparov"),
        ):
            with self.subTest(texto=texto):
                self.assertEqual(mask_annotations(texto)[1], [nome])

    def test_other_hyphens_are_left_alone(self):
        """Casa-peca, lance de-para e um par de nomes sem a virgula de citacao."""
        for texto in (
            "the e7-pawn and the h2-h4 push",
            "a Sicilian-Dragon setup",
            "see Kasparov-Karpov for details",
            # iniciais e hifen, mas sem a virgula que faz a citacao
            "compare G. Sax-G. Mohr for details",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(mask_annotations(texto), (texto, []))

    def test_names_and_annotations_share_the_verified_restoration(self):
        masked, tokens = mask_annotations("G. Sax-G. Mohr, Maribor 2000 [%clk 0:01]")
        self.assertEqual(tokens, ["[%clk 0:01]", "G. Sax-G. Mohr"])
        self.assertEqual(
            restore_annotations("\u27e61\u27e7, Maribor 2000 \u27e60\u27e7", tokens),
            ("G. Sax-G. Mohr, Maribor 2000 [%clk 0:01]", True),
        )
        self.assertFalse(restore_annotations(", Maribor 2000 \u27e60\u27e7", tokens)[1])

    def test_the_name_half_can_be_switched_off(self):
        self.assertEqual(mask_annotations("G. Sax-G. Mohr, Maribor 2000 [%clk 0:01]", player_names=False)[1], ["[%clk 0:01]"])
        self.assertTrue(has_player_name_tokens(["[%clk 0:01]", "G. Sax-G. Mohr"]))
        self.assertFalse(has_player_name_tokens(["[%clk 0:01]"]))
        self.assertFalse(has_player_name_tokens([]))

# ===========================================================================
# Letras das pecas: correcao ancorada no comentario original
# ===========================================================================


class ChessNotationTableTests(unittest.TestCase):
    """A tabela de letras, antes de qualquer correcao depender dela."""

    def test_every_language_the_program_offers_has_letters(self):
        """Um idioma no seletor e fora da tabela e uma correcao que nao roda."""
        for _nome, codigo in app_config.LANGUAGES:
            with self.subTest(idioma=codigo):
                self.assertTrue(supports_notation(codigo))

    def test_no_language_uses_the_same_letter_for_two_pieces(self):
        """A inversao `letra -> peca` precisa ser uma bijecao.

        Com duas pecas na mesma letra, ler o original vira adivinhacao — e o
        russo e exatamente o caso que quase estraga isto: Rei (Король) e Cavalo
        (Конь) comecam com a mesma letra, e a notacao usa `Кр` no rei para
        desempatar. Uma tabela com `К` nos dois tornaria todo lance de rei um
        lance de cavalo.
        """
        for idioma, letras in PIECE_LETTERS.items():
            with self.subTest(idioma=idioma):
                self.assertEqual(
                    len(set(letras.values())),
                    len(letras),
                    f"{idioma} repete uma letra: {letras}",
                )

    def test_every_language_names_the_same_five_pieces(self):
        esperado = {"K", "Q", "R", "B", "N"}
        for idioma, letras in PIECE_LETTERS.items():
            with self.subTest(idioma=idioma):
                self.assertEqual(set(letras), esperado)

    def test_the_russian_king_takes_two_letters(self):
        """Fixado porque e o unico caso multi-letra, e o que exige a alternancia
        do regex ir da letra mais longa para a mais curta."""
        self.assertEqual(PIECE_LETTERS["ru"]["K"], "Кр")
        self.assertEqual(PIECE_LETTERS["ru"]["N"], "К")


class FixMoveNotationTests(unittest.TestCase):
    """A correcao das letras dos lances (ROADMAP 10)."""

    def corrige(self, original, traduzido, origem="en", destino="pt"):
        return fix_move_notation(original, traduzido, origem, destino)

    def test_the_aliasing_that_no_sequence_of_rules_can_solve(self):
        """O caso que originou o item, e a razao de ele nao ser glossario.

        `K -> R` e `R -> T` aplicados em sequencia destroem a informacao: depois
        da primeira regra, os `R` que vieram de `K` sao indistinguiveis dos que
        ja eram `R`, e a segunda transforma os dois em `T`. Numa passagem so,
        ancorado no original, os dois chegam certos.
        """
        texto, quantos = self.corrige(
            "The king plays Kf1 and the rook Rf8 holds.",
            "O rei joga Kf1 e a torre Rf8 segura.",
        )

        self.assertEqual(texto, "O rei joga Rf1 e a torre Tf8 segura.")
        self.assertEqual(quantos, 2)

    def test_the_sequential_mutation_would_turn_both_into_the_same_piece(self):
        """A contraprova, escrita como o defeito se manifestaria.

        Sem ela, o teste acima passaria igualmente com uma implementacao que so
        acertasse por acaso — e "as duas letras ficam diferentes" e uma
        exigencia mais forte do que "o texto bate".
        """
        texto, _ = self.corrige(
            "Kf1 and Rf8.", "Kf1 e Rf8."
        )

        rei, torre = texto.split(" e ")
        self.assertNotEqual(rei[0], torre[0], f"as duas pecas viraram a mesma: {texto}")

    def test_a_move_the_translator_already_translated_is_left_correct(self):
        """O tradutor e inconstante: as vezes traduz o lance, as vezes nao.

        Os dois casos aparecem no MESMO comentario aqui, que e como a queixa
        chegou. Olhando so a traducao, o `Rf1` traduzido e o `Rxe4+` nao
        traduzido tem a mesma cara e significados diferentes.
        """
        texto, quantos = self.corrige(
            "The king goes Kf1 and the rook Rxe4+ wins.",
            "O rei vai Rf1 e a torre Rxe4+ ganha.",
        )

        self.assertEqual(texto, "O rei vai Rf1 e a torre Txe4+ ganha.")
        self.assertEqual(quantos, 1, "so o lance que estava errado conta")

    def test_applying_it_twice_changes_nothing_the_second_time(self):
        """Idempotente: o texto ja corrigido e o texto certo."""
        uma, _ = self.corrige(
            "Kf1 and Rxe4+ and Nf3.", "Kf1 e Rxe4+ e Nf3."
        )
        duas, quantos = self.corrige("Kf1 and Rxe4+ and Nf3.", uma)

        self.assertEqual(duas, uma)
        self.assertEqual(quantos, 0)

    def test_the_promotion_letter_is_translated_too(self):
        texto, quantos = self.corrige(
            "Promotion e8=Q is decisive.", "A promocao e8=Q e decisiva."
        )

        self.assertEqual(texto, "A promocao e8=D e decisiva.")
        self.assertEqual(quantos, 1)

    def test_a_capture_written_with_the_multiplication_sign_is_still_a_move(self):
        """`N×d4` aparece em material publicado e chega assim aos comentarios.

        Medido no banco real: 198 capturas escritas com `×` e 7 com `:`, contra
        4.316 com `x`. As 205 primeiras nao eram nem reconhecidas como lance,
        entao passavam sem correcao — o defeito mais silencioso possivel, porque
        o lance simplesmente nao existia para a funcao.
        """
        texto, quantos = self.corrige(
            "Instead of 12. N×d4 the rook R×e4 wins.",
            "Em vez de 12. Nxd4 a torre Rxe4 ganha.",
        )

        self.assertEqual(texto, "Em vez de 12. Cxd4 a torre Txe4 ganha.")
        self.assertEqual(quantos, 2)

    def test_the_capture_mark_of_the_translation_is_the_one_that_stays(self):
        """O corpo do lance sai da TRADUCAO, e nao do original.

        Uma regra automatica do glossario do usuario converte `×` em `x`, entao
        o original guarda `N×d4` e a traducao chega com `Nxd4`. Reescrevendo com
        o corpo do original, a correcao devolveria o `×` ao texto — desfazendo
        em silencio uma decisao tomada no glossario. O teste exige as duas
        direcoes, porque so uma delas passaria por acaso.
        """
        do_original, _ = self.corrige(
            "The rook R×e4 wins.", "A torre Rxe4 ganha."
        )
        self.assertEqual(do_original, "A torre Txe4 ganha.", "o × voltou ao texto")

        da_traducao, _ = self.corrige(
            "The rook Rxe4 wins.", "A torre R×e4 ganha."
        )
        self.assertEqual(da_traducao, "A torre T×e4 ganha.", "o × da traducao sumiu")

    def test_a_translation_without_the_piece_letter_gains_nothing(self):
        """A funcao substitui; ela nao acrescenta.

        Se a traducao perdeu a letra da peca, inserir uma seria afirmar um lance
        que o texto traduzido nao tem — e a garantia e que o pior resultado
        possivel e deixar como esta.
        """
        texto, quantos = self.corrige("The queen Qe8=Q wins.", "A dama e8=Q ganha.")

        self.assertNotIn("De8=", texto)
        self.assertEqual(quantos, 0)

    def test_captures_disambiguators_and_check_survive_untouched(self):
        """So a letra da peca muda; o resto do lance sai do proprio texto."""
        texto, _ = self.corrige(
            "After Nbd7, Qxh5+ and Rae1#, white wins.",
            "Depois de Nbd7, Qxh5+ e Rae1#, as brancas ganham.",
        )

        self.assertEqual(texto, "Depois de Cbd7, Dxh5+ e Tae1#, as brancas ganham.")

    def test_pawn_moves_and_castling_are_never_touched(self):
        """Nao tem letra de peca, entao sao iguais em todas as linguas.

        Mexer neles seria mexer em texto que nao tem o que corrigir — e `e4` e
        `O-O` aparecem com muito mais frequencia que qualquer lance de peca.
        """
        original = "After e4 exd5 and O-O, the position is equal."
        traduzido = "Depois de e4 exd5 e O-O, a posicao esta igual."

        texto, quantos = self.corrige(original, traduzido)

        self.assertEqual(texto, traduzido)
        self.assertEqual(quantos, 0)

    def test_annotation_marks_stay_glued_to_the_move(self):
        texto, _ = self.corrige("Kf1!? and Rf1?! are ideas.", "Kf1!? e Rf1?! sao ideias.")

        self.assertEqual(texto, "Rf1!? e Tf1?! sao ideias.")

    def test_the_same_square_with_two_pieces_is_resolved_by_order(self):
        """A ancora empata quando duas pecas vao para a mesma casa.

        `Rf1` (Torre) e `Kf1` (Rei) tem a mesma ancora `f1`, entao ela sozinha
        nao decide. O desempate e a ORDEM, que o tradutor preserva: ele traduz o
        texto, nao o reordena.
        """
        texto, _ = self.corrige(
            "Both Rf1 and Kf1 are playable.", "Tanto Rf1 quanto Kf1 sao jogaveis."
        )

        self.assertEqual(texto, "Tanto Tf1 quanto Rf1 sao jogaveis.")

    def test_an_ambiguous_anchor_with_a_different_count_is_left_alone(self):
        """Sem pareamento seguro, nao se inventa um.

        O original tem dois lances para `f1` e a traducao so um: nao ha como
        saber qual deles sobreviveu. Deixar como esta e o pior resultado
        possivel desta funcao, e e de proposito — corrigir para o lance errado
        seria pior do que nao corrigir.
        """
        texto, quantos = self.corrige(
            "Both Rf1 and Kf1 are playable.", "Tanto Rf1 quanto ... sao jogaveis."
        )

        self.assertEqual(texto, "Tanto Rf1 quanto ... sao jogaveis.")
        self.assertEqual(quantos, 0)

    def test_a_move_that_is_not_in_the_original_is_left_alone(self):
        """Nao ha contra o que conferi-lo, e conferir e a unica coisa que a
        funcao sabe fazer."""
        texto, quantos = self.corrige("Only Kf1.", "Apenas Kf1, e talvez Rb7.")

        self.assertEqual(texto, "Apenas Rf1, e talvez Rb7.")
        self.assertEqual(quantos, 1)

    def test_a_repeated_move_is_fixed_everywhere_it_appears(self):
        texto, _ = self.corrige("Nf3 again: Nf3.", "Cf3 de novo: Nf3.")

        self.assertEqual(texto, "Cf3 de novo: Cf3.")

    def test_the_two_letter_russian_king_is_read_before_the_knight(self):
        """`К` (Cavalo) e prefixo de `Кр` (Rei).

        Na alternancia ingenua o cavalo casaria primeiro e todo lance de rei
        sairia como lance de cavalo com um `р` sobrando. E o mesmo cuidado que a
        BOM de UTF-32 exige (garantia E4), pelo mesmo motivo.
        """
        texto, _ = fix_move_notation("Kf1 then Nf3.", "Kf1 depois Nf3.", "en", "ru")

        self.assertEqual(texto, "Крf1 depois Кf3.")

    def test_it_reads_a_russian_original_back(self):
        texto, _ = fix_move_notation("Крf1 и Кf3.", "Kf1 e Nf3.", "ru", "pt")

        self.assertEqual(texto, "Rf1 e Cf3.")

    def test_it_works_between_two_non_english_languages(self):
        """O ingles nao e especial: o problema e de qualquer par cujas letras
        divirjam. Do espanhol para o alemao, as cinco mudam."""
        texto, _ = fix_move_notation(
            "El rey Rf1, la torre Txe4, el alfil Ag5.",
            "Der Konig Rf1, der Turm Txe4, der Laufer Ag5.",
            "es",
            "de",
        )

        self.assertEqual(texto, "Der Konig Kf1, der Turm Txe4, der Laufer Lg5.")

    def test_english_notation_is_recognised_even_in_a_pair_without_english(self):
        """O tradutor as vezes devolve a notacao inglesa de qualquer jeito.

        Num par espanhol -> portugues, `K` e `N` nao pertencem a nenhum dos dois
        alfabetos. Varrendo a traducao so com as letras dos dois idiomas em jogo,
        esse `Kf1` nem seria reconhecido como lance — e ficaria como esta, que e
        exatamente o defeito que a correcao veio consertar.
        """
        texto, quantos = fix_move_notation(
            "El rey Rf1 y el caballo Cf3.", "O rei Kf1 e o cavalo Nf3.", "es", "pt"
        )

        self.assertEqual(texto, "O rei Rf1 e o cavalo Cf3.")
        self.assertEqual(quantos, 2)

    def test_the_original_is_read_only_in_the_declared_alphabet(self):
        """A outra metade da assimetria, e a que nao pode ceder.

        Na traducao a letra e ruido; no original ela e a informacao. Aqui o
        original esta em ingles e diz `Rf8` — Torre. Lido com um alfabeto
        generoso, `R` tambem seria Rei (pt/es/fr/it) e a correcao teria de
        escolher; lido no alfabeto declarado, nao ha o que escolher.
        """
        texto, _ = self.corrige("The rook Rf8 holds.", "A torre Rf8 segura.")

        self.assertEqual(texto, "A torre Tf8 segura.")

    def test_a_move_the_declared_alphabet_cannot_explain_is_not_an_anchor(self):
        """O `A` do alfil nao existe em ingles.

        Num original declarado como ingles, `Ag5` nao e um lance que o idioma
        explique — pode ser qualquer coisa. Aceita-lo como ancora faria a
        correcao afirmar uma peca que ela nao tem como saber, e e por isso que
        `extract_moves` filtra pelo alfabeto declarado.
        """
        self.assertEqual(
            [m.group(0) for m in extract_moves("Kf1 and Ag5.", "en")], ["Kf1"]
        )

        texto, quantos = self.corrige("Kf1 and Ag5.", "Rf1 e Ag5.")

        self.assertEqual(texto, "Rf1 e Ag5.", "o lance inexplicavel foi mexido")
        self.assertEqual(quantos, 0)

    def test_a_bare_pawn_move_in_the_translation_is_never_rewritten(self):
        """A guarda que impede a correcao de inventar uma peca."""
        texto, quantos = self.corrige(
            "The king plays Kf1.", "O rei joga Kf1, e o peao vai a f1."
        )

        self.assertEqual(texto, "O rei joga Rf1, e o peao vai a f1.")
        self.assertEqual(quantos, 1)

    def test_a_bare_pawn_move_does_not_count_as_a_rival_for_the_anchor(self):
        """O caso em que ignorar o peao decide se ALGO e corrigido.

        Com a ancora `f1` disputada por duas pecas, o pareamento exige que os
        dois lados tenham a mesma contagem. Um `f1` solto na traducao entrando
        como candidato faria tres contra dois — e ai **nada** e corrigido, nem os
        dois lances que estavam certos para corrigir.

        O teste anterior nao distinguia isto: com uma ancora so, a guarda de
        forma ja barrava a troca do peao e o resultado saia igual dos dois
        jeitos.
        """
        texto, quantos = self.corrige(
            "Both Rf1 and Kf1 are playable.",
            "Tanto Rf1 quanto Kf1 sao jogaveis; a casa f1 e chave.",
        )

        self.assertEqual(texto, "Tanto Tf1 quanto Rf1 sao jogaveis; a casa f1 e chave.")
        self.assertEqual(quantos, 2)

    def test_a_move_glued_to_the_end_of_a_word_is_not_a_move(self):
        """A fronteira da esquerda, fixada com um caso sintetico de proposito.

        Texto real que dispare isto e justamente o que nao da para enumerar — um
        erro de digitacao, uma colagem na importacao, um PGN mal formado. O que
        se protege e a fronteira: sem ela, qualquer sequencia terminada em letra
        de peca mais casa vira alvo de reescrita no meio de uma palavra.
        """
        texto, quantos = self.corrige("The rook Rf8 holds.", "A torreRf8 segura.")

        self.assertEqual(texto, "A torreRf8 segura.")
        self.assertEqual(quantos, 0)

    def test_languages_that_share_the_letters_change_nothing(self):
        """Espanhol e portugues so divergem no bispo; o resto ja esta certo."""
        texto, quantos = fix_move_notation(
            "El rey Rf1 y la torre Txe4.", "O rei Rf1 e a torre Txe4.", "es", "pt"
        )

        self.assertEqual(texto, "O rei Rf1 e a torre Txe4.")
        self.assertEqual(quantos, 0)

    def test_without_a_declared_source_language_nothing_is_corrected(self):
        """E a ligacao com o seletor de origem, e ela e deliberada.

        Sem saber em que alfabeto o original esta, `R` pode ser Rei ou Torre — e
        corrigir a partir de um palpite seria trocar um erro do tradutor por um
        erro do programa. Declarar o idioma e o que liga a correcao.
        """
        texto, quantos = self.corrige("Kf1 and Rf8.", "Kf1 e Rf8.", origem="")

        self.assertEqual(texto, "Kf1 e Rf8.")
        self.assertEqual(quantos, 0)

    def test_the_same_language_on_both_sides_is_a_no_op(self):
        texto, quantos = self.corrige("Kf1.", "Kf1.", origem="en", destino="en")

        self.assertEqual(texto, "Kf1.")
        self.assertEqual(quantos, 0)

    def test_an_unknown_language_is_a_no_op(self):
        texto, quantos = self.corrige("Kf1.", "Kf1.", origem="en", destino="ja")

        self.assertEqual(texto, "Kf1.")
        self.assertEqual(quantos, 0)

    def test_text_without_moves_comes_back_identical(self):
        texto, quantos = self.corrige(
            "A quiet positional comment.", "Um comentario posicional tranquilo."
        )

        self.assertEqual(texto, "Um comentario posicional tranquilo.")
        self.assertEqual(quantos, 0)

    def test_letters_inside_words_are_not_moves(self):
        """`Ke5` dentro de uma palavra nao e lance, e a fronteira e o que separa.

        Sem ela, qualquer palavra que por acaso tenha uma letra de peca seguida
        de casa viraria alvo de correcao — no meio de um comentario em prosa.
        """
        original = "The plan Kf1 works. Rebe5x is not a move."
        traduzido = "O plano Kf1 funciona. Rebe5x nao e um lance."

        texto, quantos = self.corrige(original, traduzido)

        self.assertEqual(texto, "O plano Rf1 funciona. Rebe5x nao e um lance.")
        self.assertEqual(quantos, 1)

    def test_an_empty_side_is_a_no_op(self):
        self.assertEqual(self.corrige("", "Kf1."), ("Kf1.", 0))
        self.assertEqual(self.corrige("Kf1.", ""), ("", 0))


class AnnotationMaskTests(unittest.TestCase):
    """Mascara e restauracao verificada das anotacoes (ROADMAP 13.3)."""

    def test_roundtrip_is_byte_for_byte(self):
        original = "Good move [%cal Ra1h8] here [%clk 0:05:30] end"
        mascarado, tokens = mask_annotations(original)
        self.assertNotIn("[%", mascarado)
        restaurado, ok = restore_annotations(mascarado, tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, original)

    def test_translator_spacing_around_sentinel_is_tolerated(self):
        _, tokens = mask_annotations("[%cal Ra1h8] x [%clk 0:05:30]")
        restaurado, ok = restore_annotations("⟦ 1 ⟧ y ⟦0⟧", tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, "[%clk 0:05:30] y [%cal Ra1h8]")

    def test_missing_sentinel_is_detected(self):
        _, tokens = mask_annotations("[%cal Ra1h8] and [%eval +0.35]")
        _, ok = restore_annotations("so sobrou ⟦0⟧", tokens)
        self.assertFalse(ok)

    def test_duplicated_sentinel_is_detected(self):
        _, tokens = mask_annotations("[%cal Ra1h8]")
        _, ok = restore_annotations("⟦0⟧ de novo ⟦0⟧", tokens)
        self.assertFalse(ok)

    def test_sentinel_leaked_from_neighbour_is_detected(self):
        """Um sentinela num comentario que nao mascarou nada e vazamento de
        outro comentario do lote — o rastro de um separador comido."""
        _, ok = restore_annotations("vazou ⟦3⟧ aqui", [])
        self.assertFalse(ok)

    def test_text_without_annotations_passes_untouched(self):
        mascarado, tokens = mask_annotations("um comentario comum")
        self.assertEqual(mascarado, "um comentario comum")
        self.assertEqual(tokens, [])
        restaurado, ok = restore_annotations("um comentario comum", tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, "um comentario comum")


# ===========================================================================
# Secao 16 — o aviso de qualidade passa a conhecer xadrez
# ===========================================================================


class MoveAnchorTests(unittest.TestCase):
    """A ancora que a garantia Q1 compara, e por que ela nao tem idioma."""

    def test_the_anchor_is_the_same_move_in_two_languages(self):
        """`Nf3` e `Cf3` sao o mesmo lance: so a letra muda."""
        self.assertEqual(move_anchors("plays Nf3 here"), move_anchors("joga Cf3 aqui"))

    def test_pawn_moves_count_too(self):
        """`extract_moves` os descarta (nao ha letra para corrigir); aqui um
        `h5` que sumiu importa tanto quanto um `Nf3`."""
        self.assertEqual(move_anchors("then h5"), Counter({("h5", "", ""): 1}))

    def test_the_check_mark_is_part_of_the_anchor(self):
        self.assertNotEqual(move_anchors("Bxf7+"), move_anchors("Bxf7"))

    def test_the_capture_mark_is_normalized(self):
        """O original traz `N×d4` e a traducao chega com `Nxd4`, porque uma regra
        automatica do glossario ja converteu o sinal."""
        self.assertEqual(move_anchors("N×d4"), move_anchors("Cxd4"))

    def test_a_command_annotation_is_not_a_move(self):
        """`[%cal Ra1h8]` tem a forma de um lance de Torre e nao e lance nenhum
        (garantia X1)."""
        self.assertEqual(move_anchors("boa {[%cal Ra1h8]}"), Counter())

    def test_repetition_is_counted(self):
        """Multiconjunto, e nao conjunto: a traducao que repetiu um lance a mais
        que o original tambem divergiu."""
        self.assertEqual(move_anchors("Nf3 Nf3")[("f3", "", "")], 2)

    def test_empty_text_has_no_anchors(self):
        for vazio in ("", None):
            with self.subTest(vazio=vazio):
                self.assertEqual(move_anchors(vazio), Counter())


if __name__ == "__main__":
    unittest.main()
