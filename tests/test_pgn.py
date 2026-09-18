"""Leitura e gravacao de PGN: codificacao, extracao, requebra, metadados, saida.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import os
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tradutor_pgn import (
    settings,
)
from tradutor_pgn.app_config import (
    MAX_TRANSLATE_CHARS,
)
from tradutor_pgn.database import (
    initialize_database,
    save_translation,
)
from tradutor_pgn.pgn_utils import (
    BATCH_MAX_CHARS,
    collect_pgn_files,
    count_semicolon_comments,
    create_comment_batches,
    detect_encoding,
    extract_comments_from_file,
    flatten_comment,
    generate_translated_pgn,
    is_generated_pgn,
    join_comments_for_batch,
    misaligned_batch_part,
    split_batch_translation,
    strip_generated_suffix,
    translated_output_path,
    wrap_pgn_comment,
)
from tradutor_pgn.pgn_spellcheck import (
    SPELLING_DB_FILENAME,
    build_spelling_index,
    close_spelling_data,
    collect_spellcheck_pgn_files,
    correct_spelling_value,
    default_spelling_db_path,
    escape_pgn_tag_value,
    is_normalized_pgn,
    iter_spelling_records,
    load_spelling_data,
    spelling_index_is_stale,
    unescape_pgn_tag_value,
    normalize_pgn_metadata_content,
    normalize_pgn_metadata_file,
    normalize_pgn_metadata_path,
    normalized_output_path,
    PGN_TAG_RE,
    SUPPORTED_TAGS,
    parse_spelling_file,
)
from tradutor_pgn.chess_notation import (
    extract_moves,
    fix_move_notation,
)
from tradutor_pgn import pgn_utils
from tradutor_pgn.translation_api import split_text_for_translation
from tradutor_pgn import (
    pgn_spellcheck,
    translation_worker,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeApp,
    PGN_COMPLETO,
    _movetext,
    _tags,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class PgnUtilsTests(unittest.TestCase):
    def test_extract_and_generate_translated_pgn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {White starts. Strong move} e5 {Black replies}\n",
                encoding="utf-8",
            )

            info = extract_comments_from_file(str(pgn))

            self.assertEqual(
                info["comments"],
                ["White starts. Strong move", "Black replies"],
            )

            output = translated_output_path(str(pgn), "pt")
            self.assertTrue(output.endswith("game-BR.pgn"))
            self.assertFalse(is_generated_pgn(str(pgn)))
            self.assertTrue(is_generated_pgn(str(tmp_path / "game-BR.pgn")))

            generated = generate_translated_pgn(
                str(pgn),
                output,
                {
                    "White starts. Strong move": "White begins. Good move",
                    "Black replies": "Black answers",
                },
                info["positions"],
            )

            self.assertTrue(generated)
            output_text = Path(output).read_text(encoding="utf-8")
            self.assertIn("{White begins. Good move}", output_text)
            self.assertIn("{Black answers}", output_text)

            files, skipped = collect_pgn_files(str(tmp_path), process_subdirs=False)
            self.assertIn(str(pgn), files)
            self.assertEqual(skipped, 1)

    def test_batches_and_translation_chunks_respect_limits(self):
        batches = create_comment_batches(["a" * 2000, "b" * 2000, "c"], max_chars=3800)

        self.assertEqual(batches, [["a" * 2000], ["b" * 2000, "c"]])

        chunks = split_text_for_translation("A. " * 2000, max_chars=100)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))

    def test_batch_limit_stays_below_api_split_limit(self):
        # Garantia B1: um lote nunca pode ser grande a ponto de a camada de API
        # dividi-lo, porque o corte pode cair no meio do separador " ||| ".
        self.assertLess(BATCH_MAX_CHARS, MAX_TRANSLATE_CHARS)

        comments = ["a" * 900 for _ in range(40)]
        for batch in create_comment_batches(comments):
            self.assertLessEqual(
                len(join_comments_for_batch(batch)),
                MAX_TRANSLATE_CHARS,
            )

    def test_batch_round_trip_splits_back_into_same_number_of_parts(self):
        comments = ["First comment.", "Second one!", "Terceiro: com acento."]
        joined = join_comments_for_batch(comments)

        self.assertEqual(split_batch_translation(joined, len(comments)), comments)

        # Contagem divergente deve recusar o alinhamento em vez de adivinhar.
        self.assertIsNone(split_batch_translation(joined, len(comments) + 1))

        # O tradutor costuma mexer nos espacos ao redor do separador.
        self.assertEqual(
            split_batch_translation("um|||dois ||| tres", 3),
            ["um", "dois", "tres"],
        )

    def test_a_part_that_swallowed_its_neighbour_is_misaligned(self):
        """ROADMAP 28.12: a contagem certa nao prova que a parte `i` e do
        comentario `i`. Uma parte que dobrou e outra que sumiu passam pela
        contagem; a razao de tamanho em palavras e que as pega — pela VAZIA.
        A que dobrou tem razao perto de 2 e cabe na folga de [0,3; 3,0]; mas
        numa fusao com a contagem certa sempre sobra uma parte vazia, e e ela
        que derruba o lote."""
        originais = [
            "White has a clear advantage in the endgame after the exchange.",
            "Black must defend carefully to hold the position for a draw.",
        ]
        fundida = (
            "As brancas tem clara vantagem no final depois da troca. "
            "As pretas precisam defender com cuidado para segurar o empate."
        )
        # A primeira parte engoliu a segunda; a segunda voltou vazia.
        self.assertEqual(misaligned_batch_part([fundida, ""], originais), 1)
        # Trocadas de lugar, a vazia e a primeira que estoura.
        self.assertEqual(misaligned_batch_part(["", fundida], originais), 0)
        # Sozinha, a fundida passa: e o limite declarado da defesa.
        self.assertIsNone(misaligned_batch_part([fundida], originais[:1]))
        # Cada uma com o tamanho da sua: alinhado.
        self.assertIsNone(
            misaligned_batch_part(
                [
                    "As brancas tem clara vantagem no final depois da troca.",
                    "As pretas precisam defender com cuidado para segurar o empate.",
                ],
                originais,
            )
        )

    def test_the_size_ratio_is_measured_only_above_the_floor(self):
        """`", and"` -> `"e"` e traducao normal com razao 0,5; sem o piso de 40
        caracteres esse unico caso medido derrubaria um lote de 40 para o modo
        individual. A razao vale so para originais de 40 caracteres ou mais."""
        curto = ", and"
        self.assertLess(len(curto), 40)
        self.assertIsNone(misaligned_batch_part(["e"], [curto]))
        # A parte VAZIA e a excecao ao piso: nenhum original com texto se
        # traduz por nada. E o que o lote JSON dos modelos de linguagem devolve
        # para um id que faltou (28.7), e o piso nao pode escondê-lo.
        self.assertEqual(misaligned_batch_part([""], [curto]), 0)
        self.assertEqual(misaligned_batch_part(["   "], [curto]), 0)
        self.assertIsNone(misaligned_batch_part([""], [""]))

        longo = "and while Black is definitely better, White is by no means lost"
        self.assertGreaterEqual(len(longo), 40)
        # 12 palavras no original: 3 (0,25) e 37 (3,08) estouram; 4 e 36 cabem.
        self.assertEqual(misaligned_batch_part(["a b c"], [longo]), 0)
        self.assertEqual(misaligned_batch_part([" ".join(["x"] * 37)], [longo]), 0)
        self.assertIsNone(misaligned_batch_part(["a b c d"], [longo]))
        self.assertIsNone(misaligned_batch_part([" ".join(["x"] * 36)], [longo]))

        # O indice devolvido e o da PRIMEIRA parte fora da razao, contando as
        # que o piso pulou: e o numero que o log mostra ao usuario.
        self.assertEqual(
            misaligned_batch_part(
                ["e", "uma traducao normal com bastantes palavras", "a"],
                [curto, longo, longo],
            ),
            2,
        )

    def test_encoding_detection_reads_whole_file_not_just_a_sample(self):
        # Garantias E1/E2: um PGN com dezenas de milhares de linhas ASCII e
        # acentos so no fim nao pode ser detectado como ascii.
        filler = "".join(
            f'[Event "Open"]\n[White "Smith"]\n[Round "{i}"]\n\n'
            f'1. e4 e5 {{Quiet move}} 1-0\n\n'
            for i in range(1, 1200)
        )
        tail = '[Event "Final"]\n[White "Garcia, Jose"]\n\n1. d4 {Posicao dificil} 1-0\n'
        tail = tail.replace("Garcia, Jose", "García, José")
        tail = tail.replace("Posicao dificil", "Posição difícil")
        text = filler + tail

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for label, encoding in (("cp1252", "cp1252"), ("utf8", "utf-8")):
                pgn = tmp_path / f"grande_{label}.pgn"
                pgn.write_bytes(text.encode(encoding))
                self.assertGreater(pgn.stat().st_size, 65536)

                detected = detect_encoding(str(pgn))
                self.assertNotEqual(detected, "ascii")

                info = extract_comments_from_file(str(pgn))
                joined = " ".join(info["comments"])
                self.assertNotIn("�", joined)
                self.assertIn("Posição difícil", joined)

    def test_utf16_pgn_is_read_as_text_and_not_as_nul_separated_bytes(self):
        """Garantia E4: UTF-16 escapava de E1/E2/E3.

        Um PGN em UTF-16-LE com texto ASCII e uma letra e um `\\x00`
        alternados — e `\\x00` E ASCII valido. Entao E2 concluia "e tudo ASCII,
        adoto UTF-8" e cada comentario saia com um NUL entre cada letra. Esse
        texto vira a CHAVE DE CACHE, entao o erro nao ficava so na tela: era
        gravado no `traducoes.db` para sempre.

        O caso com BOM funcionava, mas por sorte: quem acertava era o `chardet`,
        que e um import opcional. Por isso cada caso e conferido tambem com ele
        ausente.
        """
        comentarios = ["O bispo domina a diagonal", "Posição difícil para as pretas"]
        conteudo = (
            '[Event "Torneio"]\n[White "Gonçalves, João"]\n\n'
            f"1. e4 {{{comentarios[0]}}} e5 2. Nf3 {{{comentarios[1]}}} 1-0\n"
        )
        codificacoes = [
            ("utf-8", "utf-8"),
            ("utf-8-sig", "utf-8-sig"),
            ("cp1252", "cp1252"),
            ("utf-16", "utf-16"),        # com BOM
            ("utf-16-le", "utf-16-le"),  # sem BOM: o caso que quebrava
            ("utf-16-be", "utf-16-be"),  # sem BOM
            ("utf-32", "utf-32"),
        ]

        chardet_original = pgn_utils.chardet
        try:
            for com_chardet in (True, False):
                pgn_utils.chardet = chardet_original if com_chardet else None
                rotulo = "com chardet" if com_chardet else "sem chardet"

                with tempfile.TemporaryDirectory() as tmp:
                    for nome, encoding in codificacoes:
                        pgn = Path(tmp) / f"{nome}.pgn"
                        pgn.write_bytes(conteudo.encode(encoding))

                        detectada = detect_encoding(str(pgn))
                        lidos = extract_comments_from_file(str(pgn))["comments"]

                        self.assertEqual(
                            lidos,
                            comentarios,
                            f"{nome} ({rotulo}) foi lido como {detectada}",
                        )
                        self.assertNotIn(
                            "\x00",
                            " ".join(lidos),
                            f"{nome} ({rotulo}) trouxe NUL para dentro do texto",
                        )
                        self.assertNotIn("�", " ".join(lidos))
        finally:
            pgn_utils.chardet = chardet_original

    def test_a_detected_encoding_always_decodes_the_whole_file(self):
        """Garantia E4: nada e adotado sem decodificar o arquivo inteiro.

        O palpite do `chardet` era devolvido no escuro, enquanto o fallback logo
        abaixo (`cp1252`, `latin-1`) so aceitava o que decodificava. Quando o
        palpite erra, `errors='replace'` injeta `U+FFFD` no texto lido — e esse
        texto e o que `generate_translated_pgn` grava de volta, contrariando G2.

        Aqui o `chardet` e substituido por um que responde com confianca alta uma
        codificacao que nao da conta do arquivo. Sem a verificacao, este teste
        falha com `U+FFFD` no comentario.
        """

        class ChardetMentiroso:
            @staticmethod
            def detect(_raw):
                # cp1254 (turco) nao define os bytes 0x81, 0x8D, 0x8F, 0x90, 0x9D.
                return {"encoding": "cp1254", "confidence": 0.99}

        conteudo = '[Event "Torneio"]\n\n1. e4 {Posição difícil} 1-0\n'
        bruto = conteudo.encode("cp1252") + b"\x81\x90"

        chardet_original = pgn_utils.chardet
        try:
            pgn_utils.chardet = ChardetMentiroso
            with tempfile.TemporaryDirectory() as tmp:
                pgn = Path(tmp) / "suspeito.pgn"
                pgn.write_bytes(bruto)

                detectada = detect_encoding(str(pgn))
                self.assertNotEqual(detectada, "cp1254")
                bruto.decode(detectada)  # levanta se a escolha nao decodificar

                lidos = extract_comments_from_file(str(pgn))["comments"]
                self.assertNotIn("�", " ".join(lidos))
        finally:
            pgn_utils.chardet = chardet_original

    def test_generated_pgn_preserves_accents_of_large_source(self):
        # Garantia G2: nenhum caractere pode virar U+FFFD no arquivo de saida.
        filler = "".join(
            f'[Event "Open"]\n[White "Smith"]\n[Round "{i}"]\n\n'
            f'1. e4 e5 {{Quiet move}} 1-0\n\n'
            for i in range(1, 1200)
        )
        tail = (
            '[Event "Torneio"]\n'
            '[White "Gonçalves, João"]\n'
            '[Site "São Paulo"]\n\n'
            '1. d4 {Posição difícil} 1-0\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "torneio.pgn"
            pgn.write_bytes((filler + tail).encode("cp1252"))

            info = extract_comments_from_file(str(pgn))
            translated_map = {c: c for c in info["comments"]}
            output = tmp_path / "saida.pgn"

            self.assertTrue(
                generate_translated_pgn(
                    str(pgn), str(output), translated_map, info["positions"]
                )
            )

            raw = output.read_bytes()
            written = raw.decode(detect_encoding(str(output)))
            self.assertNotIn("�", written)
            self.assertIn("Gonçalves, João", written)
            self.assertIn("São Paulo", written)
            self.assertIn("Posição difícil", written)

    def test_spelling_file_normalizes_only_pgn_metadata_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            spelling = Path(tmp) / "spelling.ssp"
            spelling.write_text(
                '@PLAYER "., -_*"\n'
                '%Prefix "GM " ""\n'
                'Speelman, Jonathan S #GM ENG [2600]\n'
                '  = Speelman, J S\n'
                'Aaberg, Anton #IM SWE [2323]\n'
                '  = Aberg, Anton\n'
                '@SITE "., -_()"\n'
                'London\n'
                '  = Londres\n'
                '@EVENT ",. -_"\n'
                'World Championship\n'
                '  = WCh\n'
                '@ROUND ""\n'
                '1\n'
                '  = 1.0\n',
                encoding="utf-8",
            )
            spelling_data = parse_spelling_file(str(spelling))
            content = (
                '[Event "WCh"]\n'
                '[Site "Londres"]\n'
                '[Round "1.0"]\n'
                '[White "GM Aberg, Anton"]\n'
                '[Black "J. S. Speelman"]\n\n'
                '1. e4 {GM Aberg, Anton should stay in comment} e5\n'
            )

            updated, changes = normalize_pgn_metadata_content(content, spelling_data)

            self.assertIn('[Event "World Championship"]', updated)
            self.assertIn('[Site "London"]', updated)
            self.assertIn('[Round "1"]', updated)
            self.assertIn('[White "Aaberg, Anton"]', updated)
            self.assertIn('[Black "Speelman, Jonathan S"]', updated)
            self.assertIn("{GM Aberg, Anton should stay in comment}", updated)
            self.assertEqual(
                [change["tag"] for change in changes],
                ["Event", "Site", "Round", "White", "Black"],
            )

    def test_spelling_normalization_writes_norm_output_only_when_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[White "Aberg, Anton"]\n'
                '[Black "Known Player"]\n\n'
                "1. e4 e5\n",
                encoding="utf-8",
            )
            spelling_data = {
                "PLAYER": {
                    "entries": {
                        "aberganton": "Aaberg, Anton",
                        "knownplayer": "Known Player",
                    },
                    "ignore_chars": "., -_*",
                    "prefix_rules": [],
                    "suffix_rules": [],
                }
            }

            result = normalize_pgn_metadata_file(str(pgn), spelling_data)

            self.assertTrue(result["changed"])
            self.assertTrue(result["output_file"].endswith("-NORM.pgn"))
            output_text = Path(result["output_file"]).read_text(encoding="utf-8")
            self.assertIn('[White "Aaberg, Anton"]', output_text)
            self.assertTrue(
                normalized_output_path(str(tmp_path / "done-NORM.pgn")).endswith(
                    "done-NORM-novo.pgn"
                )
            )

            files, skipped = collect_spellcheck_pgn_files(str(tmp_path), process_subdirs=False)
            self.assertIn(str(pgn), files)
            self.assertNotIn(result["output_file"], files)
            self.assertEqual(skipped, 1)


class MoveContextTests(unittest.TestCase):
    """O lance anterior e o seguinte de cada comentario, para o modelo de
    linguagem (ROADMAP 28.7): a metade barata da extracao continua barata."""

    PGN = (
        '[Event "T"]\n\n'
        "1. e4 {First} {Best was Bc4} {Second} e5 2. Nf3 {after} Nc6 (2... Nf6 {alt Bc4 here}) "
        "3. Bb5 {Ruy} a6 {Diagram} 4. Ba4 {Diagram} Nf6 5. O-O {castled} 1-0\n"
    )

    def test_the_neighbours_are_the_moves_outside_the_braces(self):
        contextos = pgn_utils.extract_comment_contexts(self.PGN)
        self.assertEqual(contextos["First"], ("1. e4", "e5"))
        self.assertEqual(contextos["after"], ("2. Nf3", "Nc6"))
        self.assertEqual(contextos["Ruy"], ("3. Bb5", "a6"))
        self.assertEqual(contextos["castled"], ("5. O-O", ""), "o ultimo antes do resultado")

    def test_a_move_quoted_inside_a_neighbouring_comment_is_not_context(self):
        """`{Best was Bc4}` cita um lance; os comentarios ao lado nao o herdam —
        e os tres seguidos anotam o MESMO `1. e4`, que o terceiro tem de ver."""
        contextos = pgn_utils.extract_comment_contexts(self.PGN)
        self.assertEqual(contextos["First"], ("1. e4", "e5"))
        self.assertEqual(contextos["Best was Bc4"], ("1. e4", "e5"))
        self.assertEqual(contextos["Second"], ("1. e4", "e5"))
        self.assertEqual(contextos["alt Bc4 here"], ("2... Nf6", "3. Bb5"))

    def test_a_comment_longer_than_the_window_is_cut_at_its_brace(self):
        """O vizinho de 200 caracteres nao cabe na janela de 80: o pedaco dele
        que sobra — com o `Bc4` que cita — e cortado na chave, dos dois lados."""
        longo = "x" * 150
        pgn = f"1. e4 {{{longo} Best was Bc4 here}} {{Next}} {{Then Nf3 wins {longo}}} e5 *"
        contextos = pgn_utils.extract_comment_contexts(pgn)
        self.assertEqual(contextos["Next"], ("", ""), "o lance de verdade esta fora da janela")

    def test_the_first_occurrence_of_a_repeated_comment_wins(self):
        contextos = pgn_utils.extract_comment_contexts(self.PGN)
        self.assertEqual(contextos["Diagram"], ("a6", "4. Ba4"))

    def test_the_window_stops_at_the_braces_and_empty_when_no_move(self):
        self.assertEqual(pgn_utils.move_context("{x} {y}", 4, 7), ("", ""))
        self.assertEqual(pgn_utils.extract_comment_contexts(""), {})

    def test_the_texts_come_with_contexts_only_when_asked(self):
        so_textos = pgn_utils.extract_comment_texts(self.PGN)
        self.assertNotIn("contexts", so_textos)
        com = pgn_utils.extract_comment_texts(self.PGN, with_contexts=True)
        self.assertEqual(com["comments"], so_textos["comments"])
        self.assertEqual(set(com["contexts"]), set(so_textos["comments"]))


class EncodingTests(unittest.TestCase):
    def test_python_sources_do_not_contain_common_mojibake(self):
        project_root = Path(__file__).resolve().parents[1]
        source_paths = [
            project_root / "PGN_Tradutor_Pro.py",
            *sorted((project_root / "tradutor_pgn").glob("*.py")),
            *sorted((project_root / "tests").glob("*.py")),
        ]
        suspicious_patterns = {
            "a_agudo": "\u00c3\u00a1",
            "e_agudo": "\u00c3\u00a9",
            "i_agudo": "\u00c3\u00ad",
            "o_agudo": "\u00c3\u00b3",
            "u_agudo": "\u00c3\u00ba",
            "a_til": "\u00c3\u00a3",
            "o_til": "\u00c3\u00b5",
            "cedilha": "\u00c3\u00a7",
            "double_encoded": "\u00c3\u0192",
            "nbsp_or_marker": "\u00c2",
        }
        failures = []

        for path in source_paths:
            text = path.read_text(encoding="utf-8")
            for name, pattern in suspicious_patterns.items():
                if pattern in text:
                    failures.append(f"{path.relative_to(project_root)}: {name}")

        self.assertEqual(failures, [])


class SupportedTagsSingleSourceTests(unittest.TestCase):
    """A lista de tags corrigidas tem de existir em UM lugar so.

    `SUPPORTED_TAGS` diz em que secao do spelling.ssp cada tag procura, e
    `PGN_TAG_RE` decide que linhas sao candidatas. Enquanto a lista estava
    escrita nos dois, divergir falhava em silencio e em duas direcoes opostas:

    - so no dict: o regex nunca casava a linha, e a tag nova simplesmente nao
      era corrigida — sem erro, sem aviso;
    - so no regex: `SUPPORTED_TAGS[tag_name]` levantava `KeyError` e derrubava
      a normalizacao de qualquer PGN que tivesse aquela tag.

    Este teste falha nos dois casos, porque compara o que o regex ACEITA com o
    que o dict declara, em vez de conferir o texto do padrao.
    """

    OUTRAS_TAGS = [
        "Annotator",
        "Result",
        "ECO",
        "WhiteElo",
        "BlackElo",
        "Date",
        "TimeControl",
        "Opening",
    ]

    def _casa(self, tag):
        return bool(PGN_TAG_RE.match(f'[{tag} "valor"]'))

    def test_the_regex_accepts_exactly_the_declared_tags(self):
        aceitas = {tag for tag in SUPPORTED_TAGS if self._casa(tag)}
        self.assertEqual(
            aceitas,
            set(SUPPORTED_TAGS),
            "ha tag declarada em SUPPORTED_TAGS que o regex nao reconhece",
        )

    def test_the_regex_accepts_nothing_else(self):
        for tag in self.OUTRAS_TAGS:
            with self.subTest(tag=tag):
                self.assertNotIn(tag, SUPPORTED_TAGS)
                self.assertFalse(
                    self._casa(tag),
                    f"o regex aceita {tag!r}, que nao esta em SUPPORTED_TAGS — "
                    "isso vira KeyError na normalizacao",
                )

    def test_every_declared_tag_has_a_usable_section(self):
        """A secao apontada tem de ser uma das que o spelling.ssp define."""
        self.assertEqual(
            {secao for secao in SUPPORTED_TAGS.values()} - {"PLAYER", "SITE", "EVENT", "ROUND"},
            set(),
        )


class NormalizePgnMetadataPathTests(unittest.TestCase):
    """`normalize_pgn_metadata_path`: o ponto de entrada do "Normalizar PGN".

    Era a maior lacuna de cobertura do pacote depois do `background_task`: a
    funcao inteira (45 linhas) sem um unico teste, embora seja o que o botao
    chama. Os testes que existiam paravam uma camada abaixo, no conteudo e no
    arquivo unico.
    """

    def _spelling_file(self, directory):
        """Um `spelling.ssp` de verdade, para exercitar a carga do arquivo."""
        path = Path(directory) / "spelling.ssp"
        path.write_text(
            '@PLAYER "., -_*"\n'
            '%Prefix "GM " ""\n'
            "Aaberg, Anton\n"
            "  = Aberg, Anton\n"
            "Speelman, Jonathan S\n"
            "  = J. S. Speelman\n"
            '@SITE "., -_()"\n'
            "London\n"
            "  = Londres\n"
            '@EVENT ",. -_"\n'
            "World Championship\n"
            "  = WCh\n"
            '@ROUND ""\n'
            "1\n"
            "  = 1.0\n",
            encoding="utf-8",
        )
        return str(path)

    def _write(self, directory, nome, conteudo=PGN_COMPLETO):
        path = Path(directory) / nome
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(conteudo, encoding="utf-8")
        return path

    # ---------------- garantia N1 ----------------

    def test_only_the_five_tags_change(self):
        """Garantia N1, no nivel do arquivo gerado."""
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
            antes, depois = _tags(PGN_COMPLETO), _tags(saida)

            self.assertEqual(
                {t for t in antes if antes[t] != depois[t]},
                {"Event", "Site", "Round", "White", "Black"},
            )
            self.assertEqual(depois["Result"], "1-0")
            self.assertEqual(depois["ECO"], "B76")
            self.assertEqual(
                depois["Annotator"],
                "GM Aberg, Anton",
                "Annotator nao esta entre as tags suportadas",
            )

    def test_moves_variations_and_comments_are_byte_identical(self):
        """A outra metade da N1: nada abaixo do cabecalho pode mudar.

        O PGN de teste tem os mesmos nomes DENTRO de comentarios e uma variante
        aninhada citando "Londres" — se a normalizacao escapasse do cabecalho,
        e ali que apareceria.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
            self.assertEqual(_movetext(saida), _movetext(PGN_COMPLETO))
            self.assertIn("{GM Aberg, Anton comenta aqui}", saida)
            self.assertIn("{Londres seria trocada se fosse tag}", saida)
            self.assertIn("(5... a6 6. Be3 $14)", saida)
            self.assertIn("$1", saida)
            self.assertIn("$6", saida)

    def test_the_original_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            antes = pgn.read_bytes()

            normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(pgn.read_bytes(), antes)

    # ---------------- orquestracao ----------------

    def test_a_single_file_is_counted_and_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["files"], 1)
            self.assertEqual(stats["changed_files"], 1)
            self.assertEqual(stats["unchanged_files"], 0)
            self.assertEqual(stats["changes"], 5)
            self.assertEqual(len(stats["outputs"]), 1)
            self.assertTrue(stats["outputs"][0].endswith("-NORM.pgn"))

    def test_a_file_without_corrections_produces_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            limpo = '[White "Nome Desconhecido"]\n\n1. e4 e5 1-0\n'
            pgn = self._write(tmp, "limpo.pgn", limpo)

            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["changed_files"], 0)
            self.assertEqual(stats["unchanged_files"], 1)
            self.assertEqual(stats["outputs"], [])
            self.assertEqual(list(Path(tmp).glob("*-NORM.pgn")), [])

    def test_a_directory_processes_every_pgn(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a.pgn")
            self._write(tmp, "b.pgn")
            spelling = self._spelling_file(tmp)

            stats = normalize_pgn_metadata_path(tmp, spelling_path=spelling)

            self.assertEqual(stats["files"], 2)
            self.assertEqual(stats["changed_files"], 2)
            self.assertEqual(len(stats["outputs"]), 2)

    def test_subdirectories_obey_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "raiz.pgn")
            self._write(tmp, os.path.join("sub", "dentro.pgn"))
            spelling = self._spelling_file(tmp)

            raso = normalize_pgn_metadata_path(
                tmp, process_subdirs=False, spelling_path=spelling
            )
            fundo = normalize_pgn_metadata_path(
                tmp, process_subdirs=True, spelling_path=spelling
            )

            self.assertEqual(raso["files"], 1)
            self.assertEqual(fundo["files"], 2)

    def test_already_normalized_files_are_skipped(self):
        """Sem isso, reprocessar uma pasta geraria `-NORM-NORM`, e assim por diante."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            self._write(tmp, "jogo-NORM.pgn")
            spelling = self._spelling_file(tmp)

            stats = normalize_pgn_metadata_path(tmp, spelling_path=spelling)

            self.assertEqual(stats["files"], 1)
            self.assertEqual(stats["skipped_normalized"], 1)

    def test_a_missing_dictionary_fails_loudly(self):
        """Sem o dicionario nao ha o que corrigir — e seguir calado
        produziria uma copia identica com cara de "normalizada".

        A mensagem faz parte do que se exige, e nao e preciosismo: sem a guarda
        explicita o `parse_spelling_file` levanta `FileNotFoundError` do mesmo
        jeito, ao tentar abrir o arquivo. Conferir so o TIPO deixa o teste
        passar com a guarda removida — foi o que aconteceu na primeira versao.
        O que distingue os dois casos e o texto: um nomeia o `spelling.ssp` e o
        outro e o erro cru do `open()`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            ausente = str(Path(tmp) / "nao-existe.ssp")

            with self.assertRaises(FileNotFoundError) as capturado:
                normalize_pgn_metadata_path(tmp, spelling_path=ausente)

            self.assertIn("spelling.ssp nao encontrado", str(capturado.exception))
            self.assertIn(ausente, str(capturado.exception))

    def test_progress_goes_from_zero_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            for nome in ("a.pgn", "b.pgn", "c.pgn", "d.pgn"):
                self._write(tmp, nome)
            avancos = []

            normalize_pgn_metadata_path(
                tmp,
                spelling_path=self._spelling_file(tmp),
                progress_callback=avancos.append,
            )

            self.assertEqual(len(avancos), 4)
            self.assertEqual(avancos, sorted(avancos), "o progresso nao pode voltar")
            self.assertAlmostEqual(avancos[-1], 1.0)

    def test_an_empty_folder_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = normalize_pgn_metadata_path(
                tmp, spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["files"], 0)
            self.assertEqual(stats["outputs"], [])

    def test_the_log_names_each_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            self._write(tmp, "limpo.pgn", '[White "Nome Desconhecido"]\n\n1. e4 1-0\n')
            linhas = []

            normalize_pgn_metadata_path(
                tmp,
                spelling_path=self._spelling_file(tmp),
                log_message=linhas.append,
            )

            texto = "\n".join(linhas)
            self.assertIn("jogo.pgn", texto)
            self.assertIn("limpo.pgn", texto)
            self.assertIn("sem alteracoes", texto)


class CommandAnnotationInMovesTests(unittest.TestCase):
    """As anotacoes `[%...]` nao sao lances (ROADMAP 13.1).

    Os codigos de cor do Lichess (R, G, Y, B) colidem com letras de peca:
    `Ra1h8` dentro de `[%cal ...]` tem a forma exata de um lance de Torre, e a
    correcao reescrevia a seta vermelha como `Ta1h8` — deterministicamente,
    porque o original e a fonte da ancora e o pareamento nunca falha. A
    ferramenta em massa do banco passa por estas mesmas funcoes, entao a
    exclusao daqui cobre as duas portas.
    """

    def test_cal_arrow_color_is_not_rewritten(self):
        texto, quantos = fix_move_notation(
            "[%cal Ra1h8] good plan", "[%cal Ra1h8] bom plano", "en", "pt"
        )
        self.assertEqual(texto, "[%cal Ra1h8] bom plano")
        self.assertEqual(quantos, 0)

    def test_csl_circle_color_is_not_rewritten(self):
        texto, quantos = fix_move_notation(
            "[%csl Rd4] weak square", "[%csl Rd4] casa fraca", "en", "pt"
        )
        self.assertEqual(texto, "[%csl Rd4] casa fraca")
        self.assertEqual(quantos, 0)

    def test_real_move_beside_annotation_is_still_fixed(self):
        """A exclusao nao pode desligar a correcao: o lance de verdade que
        divide o comentario com a anotacao continua sendo conferido."""
        texto, quantos = fix_move_notation(
            "[%cal Rd4d8,Ge2e4] with Kf1 next",
            "[%cal Rd4d8,Ge2e4] com Kf1 a seguir",
            "en",
            "pt",
        )
        self.assertEqual(texto, "[%cal Rd4d8,Ge2e4] com Rf1 a seguir")
        self.assertEqual(quantos, 1)

    def test_extract_moves_ignores_annotation_payload(self):
        """No ORIGINAL a anotacao viraria uma ancora esperada falsa — o outro
        lado do mesmo defeito."""
        lances = [
            m.group(0) for m in extract_moves("[%cal Rd4d8] and Rd1 wins", "en")
        ]
        self.assertEqual(lances, ["Rd1"])


class FlattenDecimalTests(unittest.TestCase):
    """O achatamento nao insere espaco entre digitos (ROADMAP 13.2).

    `[%eval +0.35]` virava `[%eval +0. 35]` ANTES de qualquer traducao, e o
    texto quebrado era tres coisas ao mesmo tempo: a chave de cache, o que ia
    para a API e o que voltava ao PGN gerado.
    """

    def test_eval_annotation_survives(self):
        self.assertEqual(flatten_comment("[%eval +0.35]"), "[%eval +0.35]")

    def test_decimal_in_prose_survives(self):
        self.assertEqual(flatten_comment("2.5 pawns up"), "2.5 pawns up")
        self.assertEqual(flatten_comment("v1.2.3 fixed it"), "v1.2.3 fixed it")

    def test_sentence_spacing_is_still_normalized(self):
        """O que o achatamento sempre fez continua feito — inclusive depois de
        numero de lance, onde o que segue o ponto e letra, nao digito."""
        self.assertEqual(flatten_comment("End.Next"), "End. Next")
        self.assertEqual(flatten_comment("ok!Next"), "ok! Next")
        self.assertEqual(flatten_comment("14.Bxf7+ wins"), "14. Bxf7+ wins")


class SemicolonCommentTests(unittest.TestCase):
    """Comentarios `;` sao contados e anunciados (garantia X3)."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

    def test_count_skips_tags_and_brace_contents(self):
        conteudo = (
            '[Event "a;b"]\n'
            "\n"
            "1. e4 ; melhor lance\n"
            "e5 {com ; dentro} 2. Nf3 ; outra nota\n"
            "3. Bb5 sem nada\n"
        )
        self.assertEqual(count_semicolon_comments(conteudo), 2)

    def test_multiline_brace_does_not_join_neighbours(self):
        conteudo = "1. e4 ; um\n{quebra\nde linha} 2. d4 ; dois\n"
        self.assertEqual(count_semicolon_comments(conteudo), 2)

    def test_pgn_with_only_semicolon_comments_is_announced(self):
        """Antes, um PGN anotado so com `;` terminava em "nenhum comentario
        encontrado" — o programa parecia nao ter funcionado."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n1. e4 ; melhor lance\ne5 ; resposta\n',
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            translation_worker.run_translation(app, str(pgn), "pt", False)

            self.assertTrue(
                any("2 comentario(s) no formato ';'" in log for log in app.logs)
            )
            self.assertTrue(
                any(
                    "que o programa nao traduz" in log
                    for log in app.logs
                )
            )

    def test_mixed_file_reports_ignored_count_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n1. e4 {White starts} e5 ; nota\n',
                encoding="utf-8",
            )

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "White starts", "As brancas comecam", "pt")
            conn.commit()
            conn.close()

            app = FakeApp(db_path)
            translation_worker.run_translation(app, str(pgn), "pt", False)

            self.assertTrue(
                any(
                    "Comentarios ';' ignorados (nao suportado): 1" in log
                    for log in app.logs
                )
            )


class OutputFidelityTests(unittest.TestCase):
    """Fim de linha preservado e BOM opcional na saida (ROADMAP 13.6)."""

    def test_crlf_input_stays_crlf_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(
                b'[Event "T"]\r\n\r\n1. e4 {White starts} e5\r\n'
            )
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada),
                str(saida),
                {"White starts": "As brancas comecam"},
                posicoes,
            )
            raw = saida.read_bytes()
            self.assertEqual(
                raw,
                b'[Event "T"]\r\n\r\n1. e4 {As brancas comecam} e5\r\n',
            )

    def test_lf_input_stays_lf_even_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(b'[Event "T"]\n\n1. e4 {White starts} e5\n')
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada),
                str(saida),
                {"White starts": "As brancas comecam"},
                posicoes,
            )
            raw = saida.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertIn(b"{As brancas comecam}\n", raw.replace(b" e5", b""))

    def test_bom_option_prefixes_utf8_output(self):
        """Um PGN ASCII cuja traducao introduz acentos sai UTF-8; sem BOM o
        ChessBase do Windows le ANSI e exibe mojibake. A opcao existe para
        esse consumidor — e desligada nada muda."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(b'[Event "T"]\n\n1. e4 {White starts} e5\n')
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            com_bom = tmp_path / "bom.pgn"
            generate_translated_pgn(
                str(entrada),
                str(com_bom),
                {"White starts": "Tradução com acento"},
                posicoes,
                use_bom=True,
            )
            self.assertTrue(com_bom.read_bytes().startswith(b"\xef\xbb\xbf"))

            sem_bom = tmp_path / "sem.pgn"
            generate_translated_pgn(
                str(entrada),
                str(sem_bom),
                {"White starts": "Tradução com acento"},
                posicoes,
            )
            self.assertFalse(sem_bom.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_read_output_settings_validates_types_for_output(self):
        padrao = {"utf8_bom": False, "wrap_columns": 0}
        self.assertEqual(settings.read_output_settings({}), padrao)
        self.assertEqual(
            settings.read_output_settings({"output": {"utf8_bom": True}}),
            dict(padrao, utf8_bom=True),
        )
        # Tipo errado cai no padrao: o arquivo e editavel a mao.
        self.assertEqual(
            settings.read_output_settings({"output": {"utf8_bom": "yes"}}),
            padrao,
        )
        self.assertEqual(settings.read_output_settings({"output": "lixo"}), padrao)

    def test_the_wrap_width_is_validated(self):
        """A requebra e um numero de colunas, e o arquivo e editavel a mao
        (ROADMAP 19, item 13)."""
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": 80}})["wrap_columns"],
            80,
        )
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": 0}})["wrap_columns"],
            0,
        )
        # `True` E um int em Python: sem a checagem de bool, um `true` no arquivo
        # requebraria em UMA coluna — uma palavra por linha.
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": True}})["wrap_columns"],
            0,
        )
        # E o mesmo acidente escrito com numero.
        for invalido in (1, 19, -80, "80", 12.5):
            self.assertEqual(
                settings.read_output_settings(
                    {"output": {"wrap_columns": invalido}}
                )["wrap_columns"],
                0,
                invalido,
            )


class GeneratedSuffixWithCollisionTests(unittest.TestCase):
    """`game-BR-2.pgn` nao era reconhecido como gerado (ROADMAP 17.10).

    Confirmado: a terceira execucao sobre a mesma pasta pegava aquele arquivo
    como ENTRADA, traduzia portugues para portugues e produzia
    `game-BR-2-BR.pgn` — e cada execucao seguinte acrescentava mais um.
    """

    def test_the_collision_suffix_is_stripped(self):
        self.assertEqual(strip_generated_suffix("game-BR"), "game")
        self.assertEqual(strip_generated_suffix("game-BR-2"), "game")
        self.assertEqual(strip_generated_suffix("game-BR-17"), "game")

    def test_a_generated_file_with_a_collision_suffix_is_recognized(self):
        for nome in ("game-BR-2.pgn", "game-EN-3.pgn", "partida-br-2.pgn"):
            with self.subTest(nome=nome):
                self.assertTrue(is_generated_pgn(nome))

    def test_an_ordinary_numbered_name_is_left_alone(self):
        """`torneio-2.pgn` e um arquivo do usuario: nao tem sufixo de idioma."""
        self.assertEqual(strip_generated_suffix("torneio-2"), "torneio-2")
        self.assertFalse(is_generated_pgn("torneio-2.pgn"))
        self.assertFalse(is_generated_pgn("game-2.pgn"))

    def test_the_scan_of_a_folder_skips_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("game.pgn", "game-BR.pgn", "game-BR-2.pgn"):
                (base / nome).write_text("[Event \"T\"]\n", encoding="utf-8")

            arquivos, ignorados = collect_pgn_files(str(base), False)

            self.assertEqual([os.path.basename(a) for a in arquivos], ["game.pgn"])
            self.assertEqual(ignorados, 2)

    def test_the_normalizer_recognizes_its_own_collision_output(self):
        for nome in ("game-NORM.pgn", "game-NORM-2.pgn", "game-norm-3.pgn"):
            with self.subTest(nome=nome):
                self.assertTrue(is_normalized_pgn(nome))
        self.assertFalse(is_normalized_pgn("game-2.pgn"))

    def test_the_normalizer_scan_skips_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("game.pgn", "game-NORM.pgn", "game-NORM-2.pgn"):
                (base / nome).write_text("[Event \"T\"]\n", encoding="utf-8")

            arquivos, ignorados = collect_spellcheck_pgn_files(str(base), False)

            self.assertEqual([os.path.basename(a) for a in arquivos], ["game.pgn"])
            self.assertEqual(ignorados, 2)

    def test_the_output_name_of_a_collision_input_does_not_grow(self):
        with tempfile.TemporaryDirectory() as tmp:
            entrada = os.path.join(tmp, "game-BR-2.pgn")
            Path(entrada).write_text("[Event \"T\"]\n", encoding="utf-8")
            self.assertEqual(
                os.path.basename(translated_output_path(entrada, "pt")), "game-BR.pgn"
            )


class SpellingSectionMergeTests(unittest.TestCase):
    """Uma secao repetida no `spelling.ssp` APAGAVA a anterior (ROADMAP 17.10).

    Era uma atribuicao onde devia ser merge — e o jeito natural de acrescentar
    nomes ao arquivo e criar um segundo bloco `@PLAYER` no fim.
    """

    def arquivo(self, texto):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "spelling.ssp"
        caminho.write_text(texto, encoding="utf-8")
        return str(caminho)

    def test_a_repeated_section_adds_instead_of_replacing(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            "=Garry Kasparov\n"
            '@PLAYER ""\n'
            "Karpov, Anatoly\n"
            "=Anatoly Karpov\n"
        )

        secoes = parse_spelling_file(caminho)

        entradas = secoes["PLAYER"]["entries"]
        self.assertIn("kasparov, garry", entradas)
        self.assertIn("karpov, anatoly", entradas)

    def test_the_first_block_still_wins_a_repeated_key(self):
        """Dentro de um bloco o primeiro a definir a chave vence
        (`setdefault`); entre blocos vale a mesma regra."""
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            '@PLAYER ""\n'
            "KASPAROV, GARRY JR\n"
            "=Kasparov, Garry\n"
        )

        entradas = parse_spelling_file(caminho)["PLAYER"]["entries"]

        self.assertEqual(entradas["kasparov, garry"], "Kasparov, Garry")

    def test_affix_rules_of_both_blocks_survive(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            '%Prefix "Van " "van "\n'
            '@PLAYER ""\n'
            '%Suffix " Jr" " Jr."\n'
        )

        secao = parse_spelling_file(caminho)["PLAYER"]

        self.assertEqual(secao["prefix_rules"], [("Van ", "van ")])
        self.assertEqual(secao["suffix_rules"], [(" Jr", " Jr.")])

    def test_different_sections_stay_separate(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            '@SITE ""\n'
            "Linares\n"
        )

        secoes = parse_spelling_file(caminho)

        self.assertIn("kasparov, garry", secoes["PLAYER"]["entries"])
        self.assertIn("linares", secoes["SITE"]["entries"])
        self.assertNotIn("linares", secoes["PLAYER"]["entries"])


class PgnTagValueEscapingTests(unittest.TestCase):
    """O valor corrigido era inserido sem re-escapar aspas (ROADMAP 17.10)."""

    def test_the_two_helpers_are_inverses(self):
        for valor in ('O"Kelly', "barra\\aqui", 'os dois \\ e "', "sem nada"):
            with self.subTest(valor=valor):
                self.assertEqual(
                    unescape_pgn_tag_value(escape_pgn_tag_value(valor)), valor
                )

    def test_a_quote_in_the_canonical_value_does_not_break_the_tag(self):
        """`[White "O"Kelly"]` deixa de ser uma tag valida, e o dano aparece no
        ChessBase de quem abre o arquivo, nao aqui."""
        dados = {
            "PLAYER": {
                "entries": {"okelly": 'O"Kelly'},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        saida, mudancas = normalize_pgn_metadata_content(
            '[White "OKelly"]\n', dados
        )

        self.assertEqual(len(mudancas), 1)
        self.assertEqual(saida, '[White "O\\"Kelly"]\n')
        # E o resultado volta a ser lido como o nome com aspas.
        self.assertEqual(
            unescape_pgn_tag_value(PGN_TAG_RE.match(saida.rstrip("\n")).group(3)),
            'O"Kelly',
        )

    def test_an_escaped_value_in_the_file_is_compared_unescaped(self):
        """O dicionario fala na forma que se escreve; o arquivo, na escapada.
        Comparar sem desescapar fazia o nome com aspas nunca casar."""
        dados = {
            "PLAYER": {
                "entries": {'o"kelly': 'O\'Kelly, Albéric'},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        _saida, mudancas = normalize_pgn_metadata_content(
            '[White "O\\"Kelly"]\n', dados
        )

        self.assertEqual([m["new"] for m in mudancas], ["O'Kelly, Albéric"])

    def test_a_value_without_quotes_comes_out_byte_for_byte(self):
        dados = {
            "PLAYER": {
                "entries": {"kasparov": "Kasparov, Garry"},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        saida, _mudancas = normalize_pgn_metadata_content(
            '[White "Kasparov"]\n[Black "Karpov"]\n', dados
        )

        self.assertEqual(saida, '[White "Kasparov, Garry"]\n[Black "Karpov"]\n')


class NormalizerPartialFailureTests(unittest.TestCase):
    """Uma falha num arquivo derrubava o lote inteiro (ROADMAP 17.10)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.spelling = self.base / "spelling.ssp"
        self.spelling.write_text(
            '@PLAYER ""\nKasparov, Garry\n=Kasparov\n', encoding="utf-8"
        )

        for nome in ("a.pgn", "b.pgn", "c.pgn"):
            (self.base / nome).write_text(
                '[White "Kasparov"]\n\n1. e4 *\n', encoding="utf-8"
            )

    def rodar(self, quebrar=None):
        original = pgn_spellcheck.normalize_pgn_metadata_file

        def falso(input_file, spelling_data, **kwargs):
            if quebrar and os.path.basename(input_file) == quebrar:
                raise OSError("permissao negada")
            return original(input_file, spelling_data, **kwargs)

        pgn_spellcheck.normalize_pgn_metadata_file = falso
        self.addCleanup(
            setattr, pgn_spellcheck, "normalize_pgn_metadata_file", original
        )
        self.logs = []
        return normalize_pgn_metadata_path(
            str(self.base),
            spelling_path=str(self.spelling),
            log_message=self.logs.append,
        )

    def test_the_other_files_are_still_normalized(self):
        stats = self.rodar(quebrar="b.pgn")

        self.assertEqual(stats["changed_files"], 2)
        self.assertEqual([f["file"] for f in stats["failed"]].__len__(), 1)
        self.assertTrue(os.path.basename(stats["failed"][0]["file"]) == "b.pgn")

    def test_the_reason_reaches_the_log(self):
        self.rodar(quebrar="b.pgn")

        self.assertTrue(
            any("permissao negada" in linha for linha in self.logs),
            f"o motivo nao apareceu no log: {self.logs}",
        )

    def test_the_progress_still_reaches_the_end(self):
        valores = []
        original = pgn_spellcheck.normalize_pgn_metadata_file

        def falso(input_file, spelling_data, **kwargs):
            if os.path.basename(input_file) == "a.pgn":
                raise OSError("disco cheio")
            return original(input_file, spelling_data, **kwargs)

        pgn_spellcheck.normalize_pgn_metadata_file = falso
        self.addCleanup(
            setattr, pgn_spellcheck, "normalize_pgn_metadata_file", original
        )

        normalize_pgn_metadata_path(
            str(self.base),
            spelling_path=str(self.spelling),
            progress_callback=valores.append,
        )

        self.assertEqual(valores[-1], 1.0)

    def test_a_clean_run_reports_no_failures(self):
        stats = self.rodar()

        self.assertEqual(stats["failed"], [])
        self.assertEqual(stats["changed_files"], 3)


class WrapPgnCommentTests(unittest.TestCase):
    """Requebra em 80 colunas na gravacao (ROADMAP 19, item 13)."""

    def test_no_line_passes_the_width(self):
        texto = " ".join(["palavra"] * 30)
        linhas = wrap_pgn_comment(texto, 40, 40).split("\n")

        self.assertTrue(len(linhas) > 1)
        self.assertTrue(all(len(l) <= 40 for l in linhas), linhas)

    def test_only_whitespace_changes(self):
        """A promessa que permite requebrar sem tocar na chave de cache: as palavras
        saem na mesma ordem e com os mesmos caracteres."""
        texto = "a coluna aberta e uma estrada para a torre"
        requebrado = wrap_pgn_comment(texto, 20, 20)

        self.assertEqual(requebrado.split(), texto.split())

    def test_the_first_line_knows_it_starts_mid_line(self):
        """Depois de `12. Nf3 {` sobra menos espaco. Sem isso, a requebra acertaria
        todas as linhas menos a unica que divide espaco com o movetext."""
        texto = "uma duas tres quatro cinco"

        primeira = wrap_pgn_comment(texto, 30, 10).split("\n")[0]

        self.assertLessEqual(len(primeira), 10)

    def test_an_annotation_is_never_broken(self):
        """A garantia X1 gastou uma secao protegendo esses spans; quebra-los na
        gravacao seria desfazer o trabalho no ultimo passo."""
        texto = "antes [%cal Ra1h8,Rb2b7] depois"

        for largura in range(12, 32):
            requebrado = wrap_pgn_comment(texto, largura, largura)
            self.assertIn("[%cal Ra1h8,Rb2b7]", requebrado, largura)

    def test_a_word_longer_than_the_line_stays_whole(self):
        """Cortar no meio dela produziria um token que nao existe."""
        gigante = "a" * 50
        requebrado = wrap_pgn_comment(f"antes {gigante} depois", 20, 20)

        self.assertIn(gigante, requebrado)

    def test_an_empty_comment_survives(self):
        self.assertEqual(wrap_pgn_comment("", 80, 80), "")
        self.assertEqual(wrap_pgn_comment(None, 80, 80), "")


class WrapOnDiskTests(unittest.TestCase):
    """A requebra dentro da gravacao do PGN, com o fim de linha do arquivo."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.texto = (
            "A coluna aberta e uma estrada para a torre, e as pretas precisam "
            "disputa-la agora mesmo antes que seja tarde demais para isso."
        )

    def gerar(self, eol, **kwargs):
        entrada = self.base / "entrada.pgn"
        entrada.write_bytes(
            f'[Event "A"]{eol}{eol}1. e4 {{{self.texto}}} 1-0{eol}'.encode("utf-8")
        )
        info = extract_comments_from_file(str(entrada))
        saida = self.base / "saida.pgn"
        generate_translated_pgn(
            str(entrada), str(saida), {info["comments"][0]: self.texto},
            info["positions"], **kwargs
        )
        return saida.read_bytes()

    def test_it_is_off_by_default(self):
        """O comportamento de sempre: comentario em linha unica."""
        bruto = self.gerar("\n").decode("utf-8")

        self.assertIn("{" + self.texto + "}", bruto)

    def test_with_the_width_no_line_passes_it(self):
        bruto = self.gerar("\n", wrap_columns=80).decode("utf-8")

        self.assertTrue(any("\n" in l for l in [bruto]))
        for linha in bruto.split("\n"):
            self.assertLessEqual(len(linha), 80, linha)

    def test_the_line_ending_of_the_file_is_used(self):
        """O conteudo e lido com `newline=''` justamente para o `\\r\\n` sobreviver
        (ROADMAP 13.6): inserir `\\n` puro daria um PGN de fim de linha misturado."""
        bruto = self.gerar("\r\n", wrap_columns=80)

        self.assertNotIn(b"\n", bruto.replace(b"\r\n", b""))

    def test_the_words_are_the_same_as_without_wrapping(self):
        sem = self.gerar("\n").decode("utf-8")
        com = self.gerar("\n", wrap_columns=60).decode("utf-8")

        self.assertEqual(sem.split(), com.split())


class SpellingIndexTests(unittest.TestCase):
    """O `spelling.ssp` era reparseado a cada uso (ROADMAP 20.5).

    985 mil linhas, 1,0 s e 72 MB de pico para corrigir cinco tags de um PGN de
    20 KB. O indice derivado abre em 29 ms — 27 deles conferindo o hash do
    fonte — e consulta por chave.
    """

    SSP = (
        '@PLAYER ",."\n'
        "Kasparov, Garry\n"
        "=Kasparov\n"
        "=Kasparow\n"
        '%Prefix "Van " "van "\n'
        '@SITE ""\n'
        "Linares ESP\n"
        "=Linares\n"
        '%Suffix " ESP" " Espanha"\n'
        '@PLAYER ""\n'
        "Karpov, Anatoly\n"
        "=Karpov\n"
        "=Kasparov\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fonte = self.base / "spelling.ssp"
        self.fonte.write_text(self.SSP, encoding="utf-8")
        self.db = self.base / SPELLING_DB_FILENAME

    def abrir(self, **kwargs):
        dados = load_spelling_data(str(self.fonte), str(self.db), **kwargs)
        self.addCleanup(close_spelling_data, dados)
        return dados

    def test_the_index_sits_next_to_the_source(self):
        """Junto do fonte, e nao numa pasta de cache do sistema.

        E a mesma escolha do `glossario.db`: apagar um e obvio quando se apaga o
        outro, e ninguem procura por um cache invisivel para forcar a
        reconstrucao.
        """
        self.assertEqual(
            default_spelling_db_path(str(self.fonte)), str(self.db)
        )

    def test_the_index_answers_exactly_like_the_dictionary(self):
        dicionario = parse_spelling_file(str(self.fonte))
        indice = self.abrir()

        casos = [
            ("Kasparov", "PLAYER"),
            ("kasparow", "PLAYER"),
            ("Karpov", "PLAYER"),
            ("Van der Wiel", "PLAYER"),
            ("desconhecido", "PLAYER"),
            ("Linares", "SITE"),
            ("Linares ESP", "SITE"),
            ("qualquer", "EVENT"),
        ]
        for valor, secao in casos:
            self.assertEqual(
                correct_spelling_value(valor, secao, indice),
                correct_spelling_value(valor, secao, dicionario),
                f"{secao}: {valor!r}",
            )

    def test_a_repeated_section_keeps_appending_in_the_index(self):
        """A semantica de 17.10, atravessada pelo indice.

        Um segundo bloco `@PLAYER` ACRESCENTA; e a chave repetida (`=Kasparov`
        nos dois blocos) continua valendo pelo PRIMEIRO. Sem o `INSERT OR
        IGNORE`, o bloco de baixo passaria a sobrescrever o de cima.
        """
        indice = self.abrir()

        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")
        self.assertEqual(indice.entry("PLAYER", "karpov"), "Karpov, Anatoly")

    def test_the_section_parameters_come_from_the_last_block(self):
        indice = self.abrir()
        dicionario = parse_spelling_file(str(self.fonte))

        self.assertEqual(
            indice.get("PLAYER")["ignore_chars"],
            dicionario["PLAYER"]["ignore_chars"],
        )
        self.assertEqual(
            indice.get("PLAYER")["prefix_rules"],
            dicionario["PLAYER"]["prefix_rules"],
        )
        self.assertEqual(
            indice.get("SITE")["suffix_rules"], dicionario["SITE"]["suffix_rules"]
        )

    def test_the_second_use_does_not_read_the_source_again(self):
        """O ponto do item: o custo de 1,0 s acontece uma vez, e nao por uso."""
        self.abrir()

        leituras = []
        original = pgn_spellcheck.iter_spelling_records

        def contando(*args, **kwargs):
            leituras.append(args)
            return original(*args, **kwargs)

        pgn_spellcheck.iter_spelling_records = contando
        self.addCleanup(
            setattr, pgn_spellcheck, "iter_spelling_records", original
        )

        indice = self.abrir()

        self.assertEqual(leituras, [], "o indice valido nao devia ser reconstruido")
        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")

    def test_a_changed_source_rebuilds_the_index(self):
        self.abrir()
        self.assertFalse(spelling_index_is_stale(str(self.fonte), str(self.db)))

        self.fonte.write_text(
            '@PLAYER ""\nTal, Mihail\n=Tal\n', encoding="utf-8"
        )

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "tal"), "Tal, Mihail")
        self.assertIsNone(indice.entry("PLAYER", "kasparov"))

    def test_an_index_without_the_final_mark_is_rebuilt(self):
        """Construcao interrompida: a marca e gravada por ultimo, de proposito."""
        build_spelling_index(str(self.fonte), str(self.db))
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("DELETE FROM spelling_metadata WHERE key = 'source_hash'")
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))

    def test_an_index_from_another_schema_is_rebuilt(self):
        build_spelling_index(str(self.fonte), str(self.db))
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "UPDATE spelling_metadata SET value = '0' WHERE key = 'schema_version'"
            )
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))

    def test_a_corrupt_index_is_rebuilt_instead_of_breaking_the_button(self):
        self.db.write_bytes(b"isto nao e um banco sqlite")

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")

    def test_it_falls_back_to_the_dictionary_when_the_index_cannot_be_used(self):
        """Disco sem permissao de escrita: o botao continua funcionando.

        O log tem de dizer o motivo — degradar em silencio faria a normalizacao
        custar 1,0 s por arquivo sem que nada explicasse por que.
        """
        logs = []
        original = pgn_spellcheck.sqlite3.connect

        def recusando(*_args, **_kwargs):
            raise sqlite3.OperationalError("unable to open database file")

        pgn_spellcheck.sqlite3.connect = recusando
        try:
            dados = load_spelling_data(
                str(self.fonte), str(self.db), log_message=logs.append
            )
        finally:
            pgn_spellcheck.sqlite3.connect = original

        self.assertIsInstance(dados, dict)
        self.assertEqual(
            correct_spelling_value("Kasparov", "PLAYER", dados), "Kasparov, Garry"
        )
        self.assertTrue(any("[AVISO]" in linha for linha in logs), logs)

    def test_use_index_false_never_touches_the_disk(self):
        dados = load_spelling_data(str(self.fonte), str(self.db), use_index=False)

        self.assertIsInstance(dados, dict)
        self.assertFalse(self.db.exists())

    def test_the_index_starts_from_scratch_and_forgets_what_left_the_source(self):
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "kasparow"), "Kasparov, Garry")
        close_spelling_data(indice)

        self.fonte.write_text(
            '@PLAYER ",."\nKasparov, Garry\n=Kasparov\n', encoding="utf-8"
        )
        indice = self.abrir()

        self.assertIsNone(
            indice.entry("PLAYER", "kasparow"),
            "o apelido saiu do arquivo e nao pode sobreviver no indice",
        )

    def test_the_normalizer_uses_the_index_and_closes_it(self):
        """No Windows, um `spelling.db` preso ao processo nao pode ser trocado."""
        pgn = self.base / "game.pgn"
        pgn.write_text('[White "Kasparov"]\n\n1. e4 *\n', encoding="utf-8")
        logs = []

        stats = normalize_pgn_metadata_path(
            str(self.base), spelling_path=str(self.fonte), log_message=logs.append
        )

        self.assertEqual(stats["changed_files"], 1)
        self.assertTrue(self.db.exists())
        saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
        self.assertIn('[White "Kasparov, Garry"]', saida)
        # Se a conexao tivesse ficado aberta, o `os.remove` levantaria aqui.
        os.remove(self.db)

    def test_the_records_are_a_stream_and_not_a_list(self):
        """O gerador e o que mantem o pico de memoria baixo na construcao."""
        registros = iter_spelling_records(str(self.fonte))

        self.assertTrue(hasattr(registros, "__next__"))
        self.assertEqual(next(registros), ("section", "PLAYER", ",.", None))


if __name__ == "__main__":
    unittest.main()
