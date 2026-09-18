"""Configuracoes, caminhos de dados, primeira execucao e versao.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import json
import os
import re
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

import tradutor_pgn
from tradutor_pgn import (
    app_paths,
    db_tools,
    first_run,
    glossario,
    settings,
)
from tradutor_pgn.database import (
    initialize_database,
    save_translation,
)
from tradutor_pgn import chess_terms
from tradutor_pgn.edit_window import safe_geometry
from tradutor_pgn.failed_runs import load_failed_run
from tradutor_pgn.settings import (
    MAIN_WINDOW_DEFAULTS,
    MAIN_WINDOW_KEY,
    read_main_window_settings,
    write_main_window_settings,
    clear_editor_draft,
    get_editor_draft,
    load_settings,
    save_settings,
    set_editor_draft,
    update_settings,
)
from tradutor_pgn import (
    pgn_spellcheck,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeWindow,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class DefaultPathSafetyTests(unittest.TestCase):
    def test_default_glossary_path_is_never_the_real_project_file(self):
        # Se esta protecao cair, um teste distraido apaga o glossario do usuario.
        caminho = Path(glossario._default_substitutions_path()).resolve()
        projeto = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        self.assertNotEqual(caminho, projeto.resolve())
        self.assertIn("glossario-sandbox-", str(caminho))


class SettingsTests(unittest.TestCase):
    def test_safe_geometry_clamps_negative_saved_position(self):
        self.assertEqual(
            safe_geometry(FakeWindow(), "1360x705+-71+28"),
            "1360x705+0+28",
        )
        self.assertEqual(
            safe_geometry(FakeWindow(width=1000, height=700), "1360x900+50+-20"),
            "1000x700+0+0",
        )

    def test_settings_round_trip_and_invalid_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            data = {
                "editor": {
                    "font_size": 15,
                    "status_filter": "Pendentes",
                    "geometry": "1180x720+10+20",
                    "main_sash_y": 260,
                    "bottom_sash_x": 760,
                }
            }

            save_settings(data, str(settings_path))
            self.assertEqual(load_settings(str(settings_path)), data)

            settings_path.write_text("{invalid", encoding="utf-8")
            self.assertEqual(load_settings(str(settings_path)), {})
            self.assertEqual(load_settings(str(Path(tmp) / "missing.json")), {})

    def test_concurrent_windows_do_not_erase_each_others_settings(self):
        # Garantia R4: cada janela carrega seu proprio snapshot na abertura.
        # Se cada uma gravasse o snapshot inteiro, a ultima apagaria o que a
        # outra escreveu depois — inclusive rascunhos nao salvos.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            save_settings({"editor": {"font_size": 12}}, path)

            # As duas janelas abrem e leem o disco.
            janela_traducoes = load_settings(path)
            janela_glossario = load_settings(path)

            # O editor de traducoes salva um rascunho.
            set_editor_draft(
                janela_traducoes, "/db.sqlite", "pt", 7, "meu rascunho", "original"
            )
            update_settings(
                lambda disk: set_editor_draft(
                    disk, "/db.sqlite", "pt", 7, "meu rascunho", "original"
                ),
                path,
            )

            # Depois o editor de glossario salva as SUAS preferencias, a partir
            # de um snapshot que nao conhece o rascunho.
            janela_glossario["glossary_editor"] = {"filter": "todos"}

            def apply(disk):
                disk.setdefault("glossary_editor", {}).update({"filter": "todos"})

            update_settings(apply, path)

            gravado = load_settings(path)
            self.assertEqual(gravado["glossary_editor"]["filter"], "todos")
            # O rascunho tem de sobreviver.
            draft = get_editor_draft(gravado, "/db.sqlite", "pt", 7, "original")
            self.assertIsNotNone(draft)
            self.assertEqual(draft["text"], "meu rascunho")
            # E a preferencia original tambem.
            self.assertEqual(gravado["editor"]["font_size"], 12)

    def test_settings_write_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = tmp_path / "settings.json"
            save_settings({"editor": {"font_size": 14}}, str(path))

            self.assertTrue(path.exists())
            self.assertEqual(list(tmp_path.glob("*.tmp")), [])
            self.assertEqual(load_settings(str(path))["editor"]["font_size"], 14)

    def test_editor_drafts_are_scoped_and_base_checked(self):
        settings = {}

        self.assertTrue(
            set_editor_draft(
                settings,
                "cache.db",
                "pt",
                10,
                "draft text",
                "saved text",
                updated_at="2026-01-01 12:00:00",
            )
        )

        draft = get_editor_draft(settings, "cache.db", "pt", 10, "saved text")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["text"], "draft text")
        self.assertEqual(draft["base_translation"], "saved text")
        self.assertEqual(draft["updated_at"], "2026-01-01 12:00:00")

        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "new saved"))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "en", 10, "saved text"))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 11, "saved text"))

        self.assertTrue(clear_editor_draft(settings, "cache.db", "pt", 10))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "saved text"))
        self.assertFalse(clear_editor_draft(settings, "cache.db", "pt", 10))

    def test_editor_draft_matching_saved_text_clears_existing_draft(self):
        settings = {}
        self.assertTrue(
            set_editor_draft(settings, "cache.db", "pt", 10, "draft", "saved")
        )
        self.assertTrue(
            set_editor_draft(settings, "cache.db", "pt", 10, "saved", "saved")
        )
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "saved"))

# ===========================================================================
# A janela principal lembra o que foi escolhido
# ===========================================================================


class MainWindowSettingsTests(unittest.TestCase):
    """A leitura e a gravacao das escolhas, sem abrir janela.

    A parte que da para errar aqui e a validacao: o arquivo e JSON editavel a
    mao e sobrevive a versoes do programa, entao ele pode trazer qualquer coisa.
    """

    IDIOMAS = {"pt", "en", "es"}

    def test_an_empty_file_gives_the_defaults(self):
        self.assertEqual(
            read_main_window_settings({}, self.IDIOMAS), MAIN_WINDOW_DEFAULTS
        )

    def test_it_reads_back_what_was_stored(self):
        guardado = {
            MAIN_WINDOW_KEY: {
                "source_language": "en",
                "target_language": "es",
                "process_subdirs": False,
                "source_path": "C:/partidas",
            }
        }
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS),
            {
                "source_language": "en",
                "target_language": "es",
                "process_subdirs": False,
                "source_path": "C:/partidas",
                # Ausente no que foi gravado: a janela principal so passou a
                # lembrar tamanho e posicao em 22.12, e um arquivo de antes disso
                # tem de abrir maximizada como sempre abriu.
                "geometry": "",
                # Idem para o motor (28.7): um arquivo de antes e o Google.
                "translation_provider": "google",
            },
        )

    def test_the_saved_geometry_comes_back(self):
        """A janela principal era a unica que nunca lembrava onde estava."""
        guardado = {MAIN_WINDOW_KEY: {"geometry": "1200x800+40+20"}}
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS)["geometry"],
            "1200x800+40+20",
        )

    def test_a_geometry_that_is_not_text_falls_back_to_maximizing(self):
        guardado = {MAIN_WINDOW_KEY: {"geometry": 1200}}
        self.assertEqual(read_main_window_settings(guardado, self.IDIOMAS)["geometry"], "")

    def test_detect_survives_next_to_a_non_default_target(self):
        """A string vazia e "Detectar", uma escolha legitima.

        O que este teste protege e a SECAO: guardar "Detectar" nao pode fazer o
        resto dela ser descartado. Ele **nao** distingue tratar a string vazia
        como valor de trata-la como ausente — o padrao tambem e vazio, entao as
        duas leituras dao no mesmo. Isso esta dito no codigo, junto da guarda.
        """
        guardado = {MAIN_WINDOW_KEY: {"source_language": "", "target_language": "es"}}
        valores = read_main_window_settings(guardado, self.IDIOMAS)

        self.assertEqual(valores["source_language"], "")
        self.assertEqual(valores["target_language"], "es")

    def test_a_language_the_program_no_longer_offers_falls_back(self):
        """Um seletor nao pode ficar num estado que ele nao sabe exibir."""
        guardado = {
            MAIN_WINDOW_KEY: {"source_language": "ja", "target_language": "ja"}
        }
        valores = read_main_window_settings(guardado, self.IDIOMAS)

        self.assertEqual(valores["source_language"], "")
        self.assertEqual(valores["target_language"], "pt")

    def test_junk_of_the_wrong_type_falls_back(self):
        guardado = {
            MAIN_WINDOW_KEY: {
                "source_language": 7,
                "target_language": None,
                "process_subdirs": "sim",
                "source_path": ["/a"],
            }
        }
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS), MAIN_WINDOW_DEFAULTS
        )

    def test_a_section_that_is_not_a_dict_falls_back(self):
        self.assertEqual(
            read_main_window_settings({MAIN_WINDOW_KEY: "nada"}, self.IDIOMAS),
            MAIN_WINDOW_DEFAULTS,
        )

    def test_a_path_that_no_longer_exists_is_still_offered(self):
        """Pode ser um pendrive que ainda nao foi plugado.

        Apagar o caminho por isso seria pior do que oferece-lo: quem valida a
        existencia e o "Iniciar Traducao", que ja o fazia e diz o que houve.
        """
        guardado = {MAIN_WINDOW_KEY: {"source_path": "E:/nao-existe/partidas"}}
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS)["source_path"],
            "E:/nao-existe/partidas",
        )

    def test_writing_does_not_touch_the_editor_drafts(self):
        """Garantia R4, e e o motivo de a gravacao passar por `update_settings`.

        Os rascunhos das janelas de edicao vivem no MESMO arquivo. Gravar o
        snapshot inteiro daqui apagaria o que elas escreveram desde que este
        processo abriu — e o usuario so descobriria ao perder uma edicao.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            save_settings(
                {
                    "editor_drafts": {"chave": {"text": "rascunho vivo"}},
                    "editor": {"font_size": 15},
                },
                caminho,
            )

            write_main_window_settings({"source_language": "en"}, caminho)

            disco = load_settings(caminho)
            self.assertEqual(
                disco["editor_drafts"], {"chave": {"text": "rascunho vivo"}}
            )
            self.assertEqual(disco["editor"], {"font_size": 15})
            self.assertEqual(disco[MAIN_WINDOW_KEY]["source_language"], "en")

    def test_writing_twice_keeps_the_fields_it_was_not_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            write_main_window_settings(
                {"source_language": "en", "target_language": "pt"}, caminho
            )
            write_main_window_settings({"source_path": "C:/x"}, caminho)

            guardado = load_settings(caminho)[MAIN_WINDOW_KEY]
            self.assertEqual(guardado["source_language"], "en")
            self.assertEqual(guardado["source_path"], "C:/x")

class SettingsWithBomTests(unittest.TestCase):
    """Um BOM no arquivo de configuracoes apagava a memoria inteira do programa.

    O arquivo e JSON editavel a mao, e o Bloco de Notas do Windows grava UTF-8
    **com BOM**. Lido como `utf-8`, o `json.load` levanta, o `except` devolve
    `{}` e o programa segue como se nao houvesse configuracao nenhuma — e a
    proxima gravacao escreve um arquivo novo sem nada. Nada avisa.

    Encontrado conferindo o executavel antes de publicar a v0.2.1: as escolhas
    da janela principal nao voltavam, e a causa nao era a janela.
    """

    def arquivo(self, conteudo, com_bom):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        bruto = json.dumps(conteudo).encode("utf-8")
        caminho.write_bytes((b"\xef\xbb\xbf" if com_bom else b"") + bruto)
        return str(caminho)

    def test_a_file_with_a_bom_is_read_and_not_discarded(self):
        caminho = self.arquivo({"editor": {"font_size": 15}}, com_bom=True)

        self.assertEqual(load_settings(caminho), {"editor": {"font_size": 15}})

    def test_a_file_without_a_bom_still_works(self):
        caminho = self.arquivo({"editor": {"font_size": 15}}, com_bom=False)

        self.assertEqual(load_settings(caminho), {"editor": {"font_size": 15}})

    def test_the_drafts_survive_a_bom(self):
        """Garantia R4 pela porta dos fundos.

        O que R4 protege e o rascunho nao salvo de uma janela contra a gravacao
        de outra. De nada adianta se um caractere invisivel no inicio do arquivo
        faz o programa inteiro esquecer que ele existe.
        """
        caminho = self.arquivo(
            {"editor_drafts": {"chave": {"text": "nao salvo", "base_translation": ""}}},
            com_bom=True,
        )

        self.assertIn("chave", load_settings(caminho).get("editor_drafts", {}))

    def test_the_failed_run_list_survives_a_bom(self):
        """Garantia T4: a lista do "Reprocessar Falhas" mora no mesmo arquivo."""
        caminho = self.arquivo(
            {
                "failed_translation": {
                    "target_language": "pt",
                    "files": ["/a/b.pgn"],
                    "failed_count": 3,
                }
            },
            com_bom=True,
        )

        registro = load_failed_run(caminho)
        self.assertIsNotNone(registro)
        self.assertEqual(registro["files"], ["/a/b.pgn"])

    def test_writing_never_adds_a_bom(self):
        """Aceita-se o BOM na leitura; nao se escreve um.

        Gravar com BOM funcionaria com esta leitura e quebraria qualquer outro
        leitor de JSON — e o arquivo existe para ser editavel a mao.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            save_settings({"editor": {"font_size": 12}}, caminho)

            self.assertFalse(Path(caminho).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_a_round_trip_through_a_bom_keeps_everything(self):
        """O caminho completo: le com BOM, grava uma secao, o resto continua la.

        E o cenario que perde dado de verdade — ler devolvendo `{}` e depois
        gravar por cima e o que torna a perda definitiva.
        """
        caminho = self.arquivo(
            {
                "editor_drafts": {"chave": {"text": "nao salvo"}},
                "editor": {"font_size": 15},
            },
            com_bom=True,
        )

        write_main_window_settings({"source_language": "en"}, caminho)

        disco = load_settings(caminho)
        self.assertEqual(disco["editor_drafts"], {"chave": {"text": "nao salvo"}})
        self.assertEqual(disco["editor"], {"font_size": 15})
        self.assertEqual(disco[MAIN_WINDOW_KEY]["source_language"], "en")

    def test_a_file_that_is_not_json_at_all_still_degrades_to_empty(self):
        """A tolerancia ao BOM nao pode virar tolerancia a lixo.

        Um arquivo corrompido continua devolvendo `{}` — o programa abre com os
        padroes em vez de nao abrir.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        caminho.write_bytes(b"\xef\xbb\xbf isto nao e json {{{")

        self.assertEqual(load_settings(str(caminho)), {})

    def test_bytes_that_are_not_utf8_degrade_to_empty(self):
        """Nem toda falha de leitura e de JSON: um arquivo binario levanta
        `UnicodeDecodeError`, que precisa ser tratado junto."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        caminho.write_bytes(b"\xff\xfe\x00\x00 lixo binario")

        self.assertEqual(load_settings(str(caminho)), {})


class UserOptionSettingsTests(unittest.TestCase):
    """As opcoes que a tela de Configuracoes le e grava (ROADMAP 28.10, M4)."""

    def test_parse_wrap_columns_applies_the_same_rule_as_the_json_reader(self):
        # Vazio e zero desligam; o piso e o mesmo de `read_output_settings`.
        self.assertEqual(settings.parse_wrap_columns(""), (0, None))
        self.assertEqual(settings.parse_wrap_columns("  0 "), (0, None))
        self.assertEqual(settings.parse_wrap_columns("80"), (80, None))
        self.assertEqual(settings.parse_wrap_columns(str(settings.MIN_WRAP_COLUMNS)),
                         (settings.MIN_WRAP_COLUMNS, None))
        for ruim in ("abc", "1.5", "-5", str(settings.MIN_WRAP_COLUMNS - 1)):
            with self.subTest(ruim=ruim):
                valor, erro = settings.parse_wrap_columns(ruim)
                self.assertIsNone(valor)
                self.assertTrue(erro)
                # O que a tela recusa, o leitor do JSON tambem nao aceitaria.
                if ruim.lstrip("-").isdigit():
                    self.assertEqual(
                        settings.read_output_settings({"output": {"wrap_columns": int(ruim)}})[
                            "wrap_columns"
                        ],
                        0,
                    )

    def test_read_appearance_settings_falls_back_to_system(self):
        self.assertEqual(settings.read_appearance_settings({}), {"theme": "system"})
        self.assertEqual(
            settings.read_appearance_settings({"appearance": {"theme": "dark"}}),
            {"theme": "dark"},
        )
        for lixo in ({"appearance": "dark"}, {"appearance": {"theme": "Dark"}},
                     {"appearance": {"theme": 1}}, {"appearance": {"theme": "neon"}}):
            with self.subTest(lixo=lixo):
                self.assertEqual(settings.read_appearance_settings(lixo), {"theme": "system"})

    def test_appearance_mode_from_settings_speaks_customtkinter(self):
        self.assertEqual(settings.appearance_mode_from_settings({}), "System")
        self.assertEqual(
            settings.appearance_mode_from_settings({"appearance": {"theme": "light"}}), "Light"
        )
        self.assertEqual(
            settings.appearance_mode_from_settings({"appearance": {"theme": "dark"}}), "Dark"
        )
        # Toda opcao da tela tem um nome no CustomTkinter, e so elas.
        self.assertEqual(set(settings.CTK_APPEARANCE_MODES), set(settings.APPEARANCE_THEMES))

    def test_write_settings_sections_rereads_the_disk_and_touches_only_its_keys(self):
        """R4 para duas secoes numa escrita so."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = os.path.join(tmp, "s.json")
            settings.save_settings(
                {"main_window": {"target_language": "it"}, "output": {"utf8_bom": True}},
                caminho,
            )
            gravadas = settings.write_settings_sections(
                {"output": {"wrap_columns": 80}, "appearance": {"theme": "dark"}}, caminho
            )
            self.assertEqual(
                gravadas,
                {"output": {"utf8_bom": True, "wrap_columns": 80}, "appearance": {"theme": "dark"}},
            )
            lido = settings.load_settings(caminho)
            self.assertEqual(lido["main_window"], {"target_language": "it"}, "apagou outra secao")
            self.assertEqual(lido["output"], {"utf8_bom": True, "wrap_columns": 80})
            self.assertEqual(lido["appearance"], {"theme": "dark"})

            # Uma secao que no arquivo nao e um objeto e recomecada, nao mesclada.
            settings.save_settings({"output": "lixo"}, caminho)
            settings.write_settings_sections({"output": {"utf8_bom": False}}, caminho)
            self.assertEqual(settings.load_settings(caminho)["output"], {"utf8_bom": False})

    def test_user_option_sections_cover_output_appearance_board_and_llm_only(self):
        # A lista que M4 enumera. `main_window` e `editor_drafts` sao estado
        # das janelas, nao escolha do usuario, e ficam de fora de proposito.
        # As CHAVES de API tambem ficam de fora: nao vivem no settings (K1).
        self.assertEqual(
            settings.USER_OPTION_SECTIONS,
            {
                "output": settings.OUTPUT_DEFAULTS,
                "appearance": settings.APPEARANCE_DEFAULTS,
                "board": settings.BOARD_DEFAULTS,
                "llm": settings.LLM_DEFAULTS,
            },
        )

    def test_read_board_settings_falls_back_to_on(self):
        self.assertEqual(settings.read_board_settings({}), {"fen": True})
        self.assertEqual(settings.read_board_settings({"board": {"fen": False}}), {"fen": False})
        for lixo in ({"board": "nao"}, {"board": {"fen": 0}}, {"board": {"fen": "false"}}):
            with self.subTest(lixo=lixo):
                self.assertEqual(settings.read_board_settings(lixo), {"fen": True})


class SettingsWriteSafetyTests(unittest.TestCase):
    """Garantia M3: a gravacao nunca sobrescreve um arquivo que nao leu.

    `update_settings` lia com `load_settings`, que devolve `{}` para QUALQUER
    erro. Um `PermissionError` transitorio — antivirus, indexador, OneDrive
    tocando o `.json` por uma fracao de segundo — fazia a gravacao seguinte
    escrever um arquivo novo so com a chave que estava mudando: rascunhos (R4),
    lista de falhas (T4) e preferencias (M1) sumiam de vez, sem aviso.
    Reproduzido com a funcao real (ROADMAP 28.1).
    """

    CONTEUDO = {
        "editor_drafts": {"chave": {"text": "nao salvo", "base_translation": ""}},
        "failed_translation": {"files": ["a.pgn"]},
        "main_window": {"target_language": "pt"},
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name)
        self.caminho = self.pasta / "settings.json"
        self.avisos = []
        anterior = settings.set_settings_warning_handler(self.avisos.append)
        self.addCleanup(settings.set_settings_warning_handler, anterior)

    def gravar_es(self):
        return update_settings(
            lambda disk: disk.setdefault("main_window", {}).update(
                {"target_language": "es"}
            ),
            str(self.caminho),
        )

    def test_a_transient_read_error_does_not_wipe_the_file(self):
        save_settings(self.CONTEUDO, str(self.caminho))
        alvo = os.path.abspath(self.caminho)
        real_open = open

        def open_falho(arquivo, *args, **kwargs):
            modo = str(args[0] if args else kwargs.get("mode", "r"))
            if os.path.abspath(str(arquivo)) == alvo and modo.startswith("r"):
                raise PermissionError(13, "arquivo em uso por outro processo")
            return real_open(arquivo, *args, **kwargs)

        with unittest.mock.patch("tradutor_pgn.settings.open", open_falho, create=True):
            with self.assertRaises(OSError):
                self.gravar_es()

        # O arquivo no disco e o de antes, byte a byte no que importa.
        self.assertEqual(load_settings(str(self.caminho)), self.CONTEUDO)
        self.assertEqual(len(self.avisos), 1)
        self.assertIn("descartada", self.avisos[0])

    def test_a_corrupt_file_is_set_aside_and_the_program_carries_on(self):
        self.caminho.write_text("{invalid", encoding="utf-8")

        self.gravar_es()

        renomeados = list(self.pasta.glob("settings.json.corrompido-*"))
        self.assertEqual(len(renomeados), 1, "o corrompido tem de ficar ao lado")
        self.assertEqual(renomeados[0].read_text(encoding="utf-8"), "{invalid")
        self.assertEqual(
            load_settings(str(self.caminho)), {"main_window": {"target_language": "es"}}
        )
        self.assertEqual(len(self.avisos), 1)
        self.assertIn(renomeados[0].name, self.avisos[0])

    def test_invalid_bytes_and_a_non_object_count_as_corrupt(self):
        """Um byte invalido nao e `OSError`; uma lista nao e configuracao."""
        for bruto in (b"\xff\xfe{}", b"[1, 2]"):
            with self.subTest(bruto=bruto):
                for velho in self.pasta.glob("settings.json.corrompido-*"):
                    velho.unlink()
                self.caminho.write_bytes(bruto)

                self.gravar_es()

                self.assertEqual(len(list(self.pasta.glob("settings.json.corrompido-*"))), 1)
                self.assertEqual(
                    load_settings(str(self.caminho)),
                    {"main_window": {"target_language": "es"}},
                )

    def test_a_missing_file_is_created_without_a_warning(self):
        self.gravar_es()

        self.assertEqual(
            load_settings(str(self.caminho)), {"main_window": {"target_language": "es"}}
        )
        self.assertEqual(self.avisos, [])

    def test_readers_stay_tolerant(self):
        """Quem LE continua degradando para `{}`: uma janela sem preferencias e
        melhor do que uma janela que nao abre."""
        self.caminho.write_text("{invalid", encoding="utf-8")

        self.assertEqual(load_settings(str(self.caminho)), {})
        self.assertTrue(self.caminho.exists(), "ler nao renomeia nada")


class SettingsConcurrencyTests(unittest.TestCase):
    """O rascunho passou a gravar em segundo plano (item 10).

    Duas threads chamando `update_settings` sem lock fazem a segunda ler o disco
    ANTES de a primeira gravar, e o que a primeira escreveu desaparece — a perda que
    a garantia R4 existe para impedir, agora por corrida.
    """

    def test_concurrent_updates_do_not_lose_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")

            def gravar(indice):
                def mutator(disk):
                    disk[f"chave_{indice}"] = indice
                settings.update_settings(mutator, caminho)

            threads = [
                threading.Thread(target=gravar, args=(i,)) for i in range(24)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            gravado = settings.load_settings(caminho)
            self.assertEqual(
                sorted(gravado), sorted(f"chave_{i}" for i in range(24))
            )


class DataDirRuleTests(unittest.TestCase):
    """Onde os dados moram, e por que depende de como o programa iniciou.

    A regra existe para que atualizar o programa nao passe por cima do trabalho
    do usuario (ROADMAP 21), e para que o app instalado e o checkout convivam na
    mesma maquina sem ver os dados um do outro.
    """

    def setUp(self):
        # `APPDATA` entra na lista, e o motivo custou uma falha: um teste que o
        # define e depois faz `pop` **apaga do processo** o valor de verdade, e o
        # resto da suite roda sem `%APPDATA%` — as janelas do Tk quebram lá na
        # frente, longe daqui, e o teste que falha nao tem relacao nenhuma com
        # este arquivo. Snapshot e restauracao, nunca `pop`.
        self.ambiente = {
            nome: os.environ.get(nome)
            for nome in (app_paths.DATA_DIR_ENV, "APPDATA")
        }
        self.frozen_original = getattr(sys, "frozen", None)
        self.addCleanup(self.restaurar)

    def restaurar(self):
        for nome, valor in self.ambiente.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor
        if self.frozen_original is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = self.frozen_original

    def test_running_from_source_keeps_the_data_beside_the_script(self):
        """O comportamento de sempre, e o que a suite inteira depende."""
        os.environ.pop(app_paths.DATA_DIR_ENV, None)
        if hasattr(sys, "frozen"):
            del sys.frozen

        self.assertEqual(app_paths.data_dir(), app_paths.program_dir())
        self.assertFalse(app_paths.running_frozen())

    def test_frozen_puts_the_data_in_appdata_and_not_beside_the_exe(self):
        os.environ.pop(app_paths.DATA_DIR_ENV, None)
        sys.frozen = True
        with tempfile.TemporaryDirectory() as tmp:
            # O `APPDATA` volta ao valor real no `restaurar` do `addCleanup`.
            os.environ["APPDATA"] = tmp
            pasta = app_paths.data_dir()

            self.assertEqual(pasta, os.path.join(tmp, app_paths.APP_DATA_FOLDER))
        self.assertNotEqual(pasta, app_paths.program_dir())

    def test_the_environment_variable_wins_over_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[app_paths.DATA_DIR_ENV] = tmp
            sys.frozen = True
            self.assertEqual(app_paths.data_dir(), os.path.abspath(tmp))
            del sys.frozen
            self.assertEqual(app_paths.data_dir(), os.path.abspath(tmp))

    def test_an_empty_variable_is_absence_and_not_the_current_directory(self):
        """`set PGN_TRADUTOR_DATA=` e o jeito natural de desligar a variavel.

        Lido como caminho, o vazio viraria o diretorio de trabalho de quem
        chamou — o acervo gravado onde o atalho por acaso apontava.
        """
        os.environ[app_paths.DATA_DIR_ENV] = "   "
        if hasattr(sys, "frozen"):
            del sys.frozen

        self.assertEqual(app_paths.data_dir(), app_paths.program_dir())

    def _fingir_exe(self, pasta):
        """Faz `program_dir()` apontar para `pasta`, como um `.exe` faria.

        `program_dir` sai de `sys.argv[0]`, entao e ele que muda — inventar um
        dublê para a funcao mediria o dublê, e nao a regra.
        """
        original = sys.argv[0]
        sys.argv[0] = os.path.join(pasta, "PGN_Tradutor_Pro.exe")
        self.addCleanup(lambda: sys.argv.__setitem__(0, original))

    def test_the_portable_marker_puts_the_data_inside_the_program_folder(self):
        """O modo portatil (ROADMAP 27): o mesmo `.exe`, com um arquivo ao lado.

        E o que separa a versao instalavel da portatil. Sem isto, as duas
        precisariam de builds diferentes — duas coisas para testar e manter em
        dia por causa de uma linha de diferenca.
        """
        os.environ.pop(app_paths.DATA_DIR_ENV, None)
        sys.frozen = True
        with tempfile.TemporaryDirectory() as tmp:
            self._fingir_exe(tmp)
            os.environ["APPDATA"] = tmp  # para o contraste abaixo ser justo

            self.assertFalse(app_paths.running_portable())
            instalado = app_paths.data_dir()

            Path(app_paths.portable_marker_path()).write_text("", encoding="utf-8")

            self.assertTrue(app_paths.running_portable())
            self.assertEqual(
                app_paths.data_dir(),
                os.path.join(tmp, app_paths.PORTABLE_DATA_FOLDER),
            )
            self.assertNotEqual(app_paths.data_dir(), instalado)

    def test_the_portable_marker_does_nothing_when_running_from_source(self):
        """Um `portatil.txt` esquecido no checkout nao pode mudar a suite.

        Do fonte os dados JA ficam ao lado do script, entao o marcador nao teria
        o que alterar — e um arquivo solto no repositorio nao pode ter efeito
        sobre onde os testes gravam.
        """
        os.environ.pop(app_paths.DATA_DIR_ENV, None)
        if hasattr(sys, "frozen"):
            del sys.frozen
        with tempfile.TemporaryDirectory() as tmp:
            self._fingir_exe(tmp)
            Path(app_paths.portable_marker_path()).write_text("", encoding="utf-8")

            self.assertFalse(app_paths.running_portable())
            self.assertEqual(app_paths.data_dir(), app_paths.program_dir())

    def test_the_variable_still_wins_over_the_portable_marker(self):
        """Apontar um `.exe` de pendrive para um acervo do disco e o caso que a
        variavel existe para atender."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as alvo:
            sys.frozen = True
            self._fingir_exe(tmp)
            Path(app_paths.portable_marker_path()).write_text("", encoding="utf-8")
            os.environ[app_paths.DATA_DIR_ENV] = alvo

            self.assertTrue(app_paths.running_portable())
            self.assertEqual(app_paths.data_dir(), os.path.abspath(alvo))

    def test_the_announced_line_names_the_mode_and_not_only_the_folder(self):
        """Duas situacoes diferentes podem dar a MESMA pasta, e saber qual esta
        valendo e o que explica o que a proxima atualizacao fara com o acervo."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ.pop(app_paths.DATA_DIR_ENV, None)
            if hasattr(sys, "frozen"):
                del sys.frozen
            self.assertIn("do fonte", first_run.describe_data_dir())

            sys.frozen = True
            self._fingir_exe(tmp)
            os.environ["APPDATA"] = tmp
            self.assertIn("instalado", first_run.describe_data_dir())

            Path(app_paths.portable_marker_path()).write_text("", encoding="utf-8")
            self.assertIn("portatil", first_run.describe_data_dir())

            os.environ[app_paths.DATA_DIR_ENV] = tmp
            self.assertIn(app_paths.DATA_DIR_ENV, first_run.describe_data_dir())

    def test_appdata_missing_still_does_not_fall_back_to_the_program_folder(self):
        """Sem `%APPDATA%` — servico, conta de sistema, ambiente de build."""
        os.environ.pop(app_paths.DATA_DIR_ENV, None)
        os.environ.pop("APPDATA", None)   # restaurado no `addCleanup`
        sys.frozen = True

        pasta = app_paths.data_dir()

        self.assertNotEqual(pasta, app_paths.program_dir())
        self.assertIn(app_paths.APP_DATA_FOLDER, pasta)

    def test_every_user_file_follows_the_data_dir(self):
        """As seis funcoes de caminho, todas pela mesma porta.

        Uma que ficasse para tras gravaria na pasta do programa, e seria
        exatamente o arquivo perdido na atualizacao seguinte.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[app_paths.DATA_DIR_ENV] = tmp
            esperado = os.path.abspath(tmp)

            caminhos = {
                "glossario": glossario._default_substitutions_path(),
                "indice do glossario": glossario._default_glossary_db_path(),
                "configuracoes": settings.default_settings_path(),
                "indice de grafias": pgn_spellcheck.default_spelling_db_path(),
            }
            for rotulo, caminho in caminhos.items():
                self.assertEqual(
                    os.path.dirname(os.path.abspath(caminho)), esperado, rotulo
                )

    def test_what_ships_with_the_program_does_not_follow_the_data_dir(self):
        """Semente, termos suspeitos e `spelling.ssp` sao dados de PROGRAMA.

        Eles saem de `__file__`, viajam dentro do pacote e sao substituidos por
        uma atualizacao — que e justamente o que nao pode acontecer com o que
        esta na pasta de dados.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[app_paths.DATA_DIR_ENV] = tmp
            modulo = Path(glossario.__file__).resolve().parent

            # A semente fica de fora desta lista de proposito: o sandbox da
            # suite a aponta para um arquivo inexistente (senao a terminologia
            # embutida entraria em todo teste que compara listas de regras), e
            # e a propria `setUpModule` que documenta isso.
            self.assertEqual(
                Path(chess_terms._default_terms_path()).resolve().parent, modulo
            )
            self.assertEqual(
                Path(first_run.packaged_glossary_path()).resolve().parent, modulo
            )
            self.assertNotIn(
                os.path.abspath(tmp),
                os.path.abspath(pgn_spellcheck.DEFAULT_SPELLING_PATH),
            )


class VersionTests(unittest.TestCase):
    """Uma fonte so para a versao (ROADMAP 21.6).

    Havia tres numeros que nao se falavam — `pyproject.toml` em 0.2.1, o
    cabecalho TMX em 1.0 e o instalador em 1.0.0 —, e nenhum derivava de outro.
    O que impede que voltem a divergir e este arquivo.
    """

    RAIZ = Path(__file__).resolve().parent.parent

    def test_the_version_is_three_numbers(self):
        """O recurso de versao do Windows e a comparacao do instalador exigem
        numeros; um sufixo teria de ser traduzido em dois lugares."""
        self.assertRegex(tradutor_pgn.__version__, r"^\d+\.\d+\.\d+$")

    def test_pyproject_says_the_same_thing(self):
        texto = (self.RAIZ / "pyproject.toml").read_text(encoding="utf-8")
        declarada = re.search(r'^version = "([^"]+)"', texto, re.MULTILINE)

        self.assertIsNotNone(declarada, "o pyproject.toml perdeu a versao")
        self.assertEqual(
            declarada.group(1),
            tradutor_pgn.__version__,
            "pyproject.toml e tradutor_pgn.__version__ divergiram",
        )

    def test_the_installer_does_not_declare_a_version_of_its_own(self):
        """Ele le a do executavel; declarar a sua seria o quarto numero.

        O `#ifndef` continua valendo — e por onde o roteiro de verificacao
        simula uma atualizacao sem reconstruir o `.exe`.
        """
        iss = (self.RAIZ / "instalador" / "PGN_Tradutor_Pro.iss").read_text(
            encoding="utf-8"
        )

        self.assertIn("GetStringFileInfo", iss)
        self.assertNotRegex(
            iss, r'#define AppVersion "\d', "o instalador voltou a fixar a versao"
        )

    def test_the_exported_tmx_carries_the_real_version(self):
        """O cabecalho viaja para dentro do OmegaT de quem importar a memoria."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            save_translation(conn.cursor(), "A comment.", "Um comentario.", "pt", "en")
            conn.commit()
            conn.close()

            saida = Path(tmp) / "memoria.tmx"
            db_tools.export_translations_to_tmx(str(db_path), str(saida))
            cabecalho = saida.read_text(encoding="utf-8")

        self.assertIn(
            f'creationtoolversion="{tradutor_pgn.__version__}"', cabecalho
        )

    def test_the_window_title_shows_it(self):
        """"Qual versao voce esta rodando?" e a primeira pergunta do suporte."""
        fonte = (self.RAIZ / "tradutor_pgn" / "app.py").read_text(encoding="utf-8")

        self.assertIn('title(f"PGN Tradutor Pro {__version__}")', fonte)


class FirstRunTests(unittest.TestCase):
    """A primeira execucao depois de instalar (ROADMAP 21)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.dados = self.base / "dados"
        self.programa = self.base / "programa"
        self.programa.mkdir()

        self.env_original = os.environ.get(app_paths.DATA_DIR_ENV)
        os.environ[app_paths.DATA_DIR_ENV] = str(self.dados)
        self.addCleanup(self.restaurar_env)

        self.program_dir_original = app_paths.program_dir
        app_paths.program_dir = lambda: str(self.programa)
        first_run.program_dir = app_paths.program_dir
        self.addCleanup(setattr, app_paths, "program_dir", self.program_dir_original)
        self.addCleanup(setattr, first_run, "program_dir", self.program_dir_original)

        self.pacote_original = first_run.packaged_glossary_path
        self.pacote = self.base / "Substituicoes-inicial.txt"
        self.pacote.write_text(
            "substituicoes = [\n    ('knight', 'cavalo', 'suggestion'),\n]\n",
            encoding="utf-8",
        )
        first_run.packaged_glossary_path = lambda: str(self.pacote)
        self.addCleanup(
            setattr, first_run, "packaged_glossary_path", self.pacote_original
        )

    def restaurar_env(self):
        if self.env_original is None:
            os.environ.pop(app_paths.DATA_DIR_ENV, None)
        else:
            os.environ[app_paths.DATA_DIR_ENV] = self.env_original

    def test_a_fresh_install_gets_the_glossary_that_ships_in_the_package(self):
        copiados = first_run.prepare_data_dir()

        destino = self.dados / "Substituicoes.txt"
        self.assertTrue(destino.exists())
        self.assertIn("Substituicoes.txt", copiados)
        self.assertIn("knight", destino.read_text(encoding="utf-8"))

    def test_data_from_a_previous_install_is_copied_and_not_moved(self):
        """Copiar, e nao mover: voltar a versao antiga tem de continuar valendo."""
        (self.programa / "Substituicoes.txt").write_text(
            "substituicoes = [\n    ('rook', 'torre', 'suggestion'),\n]\n",
            encoding="utf-8",
        )
        (self.programa / "traducoes.db").write_bytes(b"SQLite format 3\x00")

        copiados = first_run.prepare_data_dir()

        self.assertIn("Substituicoes.txt", copiados)
        self.assertIn("traducoes.db", copiados)
        self.assertIn(
            "rook", (self.dados / "Substituicoes.txt").read_text(encoding="utf-8")
        )
        self.assertTrue(
            (self.programa / "Substituicoes.txt").exists(),
            "o arquivo da instalacao anterior nao pode sumir",
        )

    def test_an_existing_glossary_is_never_overwritten(self):
        """A regra que governa o modulo inteiro, e a razao de ele existir."""
        self.dados.mkdir()
        meu = self.dados / "Substituicoes.txt"
        meu.write_text(
            "substituicoes = [\n    ('minha regra', 'curada a mao', 'automatic'),\n]\n",
            encoding="utf-8",
        )
        (self.programa / "Substituicoes.txt").write_text(
            "substituicoes = [\n    ('outra', 'coisa', 'suggestion'),\n]\n",
            encoding="utf-8",
        )

        copiados = first_run.prepare_data_dir()

        self.assertEqual(copiados, [])
        self.assertIn("curada a mao", meu.read_text(encoding="utf-8"))

    def test_running_from_source_migrates_nothing(self):
        """Pasta de dados e pasta do programa sao a mesma: nao ha de onde copiar.

        Sem esta guarda, a copia teria origem e destino iguais — e o unico
        motivo de nada quebrar hoje seria o `_copiar_se_faltar` desistir por
        acaso, que e correcao por acidente.
        """
        os.environ[app_paths.DATA_DIR_ENV] = str(self.programa)
        (self.programa / "Substituicoes.txt").write_text("substituicoes = []\n", encoding="utf-8")

        copiados = first_run.prepare_data_dir()

        self.assertEqual(copiados, [])

    def test_the_second_run_does_nothing(self):
        first_run.prepare_data_dir()
        antes = (self.dados / "Substituicoes.txt").read_bytes()

        copiados = first_run.prepare_data_dir()

        self.assertEqual(copiados, [])
        self.assertEqual((self.dados / "Substituicoes.txt").read_bytes(), antes)

    def test_the_big_folders_are_left_behind_and_the_log_says_so(self):
        (self.programa / "Substituicoes.txt").write_text("substituicoes = []\n", encoding="utf-8")
        (self.programa / "backups").mkdir()
        logs = []

        first_run.prepare_data_dir(logs.append)

        self.assertFalse((self.dados / "backups").exists())
        self.assertTrue(
            any("backups" in linha and "NAO foi copiada" in linha for linha in logs),
            f"o usuario precisa saber onde os backups ficaram: {logs}",
        )

    def test_the_data_dir_is_announced(self):
        self.assertIn(str(self.dados), first_run.describe_data_dir())


if __name__ == "__main__":
    unittest.main()
