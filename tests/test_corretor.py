"""O corretor de prosa (hunspell).

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import importlib
import re
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from tradutor_pgn import (
    prose_spellcheck,
)
from helpers import setup_module_sandbox, teardown_module_sandbox


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class ProseSpellcheckDependencyTests(unittest.TestCase):
    """Garantia I8: `spylls` e dependencia declarada, e o build sabe dela.

    Estava so no `requirements.txt`: `uv sync` — o caminho do README — abria o
    programa sem corretor, e `ProseSpellcheckTests` era pulada por `SkipTest`
    sem nada ficar vermelho. O `.exe` so levava o corretor porque o
    interpretador do build tinha o pacote por acaso (ROADMAP 28.1).
    """

    RAIZ = Path(__file__).resolve().parent.parent

    def test_pyproject_and_lock_declare_spylls(self):
        import tomllib

        projeto = tomllib.loads((self.RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
        dependencias = projeto["project"]["dependencies"]
        self.assertTrue(
            any(dep.startswith("spylls") for dep in dependencias),
            f"spylls nao esta em [project].dependencies: {dependencias}",
        )
        lock = (self.RAIZ / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('name = "spylls"', lock, "uv.lock nao resolve spylls")

    def test_the_spec_declares_the_module_the_spellchecker_imports(self):
        """O nome no `.spec` e o mesmo que `prose_spellcheck` importa."""
        spec = (self.RAIZ / "PGN_Tradutor_Pro.spec").read_text(encoding="utf-8")
        fonte = (self.RAIZ / "tradutor_pgn" / "prose_spellcheck.py").read_text(
            encoding="utf-8"
        )
        importado = re.search(r"from (spylls\.[\w.]+) import", fonte)
        self.assertIsNotNone(importado)
        self.assertIn(f'hiddenimports += ["{importado.group(1)}"]', spec)
        self.assertIn("AVISO: `spylls` nao esta instalado", spec)

    def test_the_spellchecker_is_importable_from_the_test_interpreter(self):
        """Se isto falhar, `ProseSpellcheckTests` esta sendo pulada em silencio."""
        import spylls.hunspell  # noqa: F401


class ProseSpellcheckTests(unittest.TestCase):
    """O corretor de prosa do idioma de destino (ROADMAP 19.11 e 26).

    O dicionario e carregado uma vez para a classe inteira: sao 4,6 MB e ~2,3 s,
    e paga-los por teste seria mais tempo do que a suite toda leva hoje.
    """

    @classmethod
    def setUpClass(cls):
        cls.dicionario = prose_spellcheck.load_dictionary("pt")
        if cls.dicionario is None:
            raise unittest.SkipTest(
                "sem dicionario pt-BR em dicionarios/ (ou sem o spylls instalado)"
            )

    def marcas(self, texto, origem=""):
        conhecidas = prose_spellcheck.source_vocabulary(origem)
        return [
            palavra
            for _i, _f, palavra in prose_spellcheck.misspelled_spans(
                texto, self.dicionario, conhecidas
            )
        ]

    def test_a_typo_is_marked_and_the_prose_around_it_is_not(self):
        self.assertEqual(
            self.marcas("As pretas ficam com uma posiçao dificil aqui."),
            ["posiçao", "dificil"],
        )

    def test_the_offsets_point_at_the_word_and_not_at_the_line(self):
        """A janela pinta por deslocamento; errar o intervalo sublinha o vizinho."""
        texto = "As pretas ficam com uma posiçao boa."
        inicio, fim, palavra = prose_spellcheck.misspelled_spans(
            texto, self.dicionario
        )[0]
        self.assertEqual(texto[inicio:fim], palavra)
        self.assertEqual(palavra, "posiçao")

    def test_chess_notation_is_never_marked(self):
        """Sem isto o corretor marca o livro inteiro: cada lance e uma palavra
        que dicionario nenhum conhece."""
        self.assertEqual(
            self.marcas("Depois de 13.Cd4 exd5 14 Bxf7+ Rxf7 0-0-0 e4-e5, tudo bem."),
            [],
        )

    def test_a_word_glued_to_a_digit_is_not_split_into_a_mark(self):
        """O defeito que a medicao das 6.500 linhas encontrou.

        Quebrar a palavra no digito transforma `Cd4` em `Cd`, e `Cd` nao casa
        padrao nenhum de notacao — eram 40 das 70 marcas mais frequentes, todas
        estilhaco de um token que o texto nao tem.
        """
        for texto in ("13.Cd4", "Cxd5", "h4-h5", "Th8", "20Ca2"):
            with self.subTest(texto=texto):
                self.assertEqual(self.marcas(texto), [])

    def test_a_name_from_the_source_text_is_not_marked(self):
        """O filtro que faz o trabalho: 3.347 marcas viram 95.

        Nome de jogador, de torneio e de cidade chegam a traducao vindos do
        original em ingles, e e la que eles estao.
        """
        original = "Anand beat Karpov in Wijk aan Zee, a Ftacnik line."
        traducao = "Anand venceu Karpov em Wijk aan Zee, numa linha de Ftacnik."
        self.assertEqual(self.marcas(traducao, original), [])
        # A contraprova: sem o texto de origem, os quatro nomes viram marca.
        self.assertTrue(len(self.marcas(traducao)) >= 4)

    def test_the_source_filter_ignores_case(self):
        """`White` no original tem de cobrir `white` na traducao, e vice-versa."""
        self.assertEqual(self.marcas("O plano de Ftacnik.", "a FTACNIK plan"), [])

    def test_a_quoted_word_does_not_keep_the_apostrophe(self):
        """O outro defeito da medicao: `'insipido'` virava a palavra
        `insipido'`, que dicionario nenhum conhece."""
        self.assertEqual(self.marcas("Um lance 'insípido' aqui."), [])

    def test_an_internal_hyphen_keeps_the_word_whole(self):
        """`bem-vindo` e uma palavra so; parti-la marca as duas metades."""
        self.assertEqual(self.marcas("Um lance bem-vindo."), [])

    def test_a_language_without_a_dictionary_says_so_instead_of_going_quiet(self):
        """Sem o aviso, "nenhuma marca" quer dizer duas coisas opostas: texto
        sem erro e corretor ausente. A janela nao distingue as duas sozinha."""
        self.assertFalse(prose_spellcheck.has_dictionary("it"))
        aviso = prose_spellcheck.unsupported_language_notice("it")
        self.assertIn("IT", aviso)
        self.assertEqual(prose_spellcheck.unsupported_language_notice("pt"), "")

    def test_without_a_dictionary_nothing_is_marked_and_nothing_raises(self):
        self.assertIsNone(prose_spellcheck.load_dictionary("it"))
        self.assertEqual(
            prose_spellcheck.misspelled_spans("qualquer coisa", None), []
        )
        self.assertEqual(prose_spellcheck.suggestions("qualquer", None), [])

    def test_the_dictionary_is_loaded_once_per_process(self):
        """A carga custa 2,3 s. Uma por tecla digitada seria o editor parado."""
        self.assertIs(
            prose_spellcheck.load_dictionary("pt"),
            prose_spellcheck.load_dictionary("pt"),
        )

    def test_threads_asking_at_once_do_not_each_load_their_own_copy(self):
        """O defeito que a suite de janelas encontrou (ROADMAP 26.4).

        A primeira versao conferia o cache com o cadeado e o SOLTAVA para
        carregar. Cada janela dispara a carga do seu lado, nenhuma tinha
        terminado quando as outras conferiram, e o processo montou varias copias
        de 4,6 MB ao mesmo tempo — 1,3 GB e a suite sem terminar.

        O teste falha com aquela versao: `chamadas` fica em 8, e nao em 1.
        """
        idioma = "zz-teste"
        chamadas = []
        real = prose_spellcheck.dictionary_files

        def falso(alvo):
            if alvo == idioma:
                return real("pt")
            return real(alvo)

        def contando(*args, **kwargs):
            chamadas.append(args)
            time.sleep(0.05)  # a janela em que a versao errada duplicava
            return object()

        modulo = importlib.import_module("spylls.hunspell")
        original = modulo.Dictionary.from_files
        prose_spellcheck.dictionary_files = falso
        modulo.Dictionary.from_files = staticmethod(contando)
        try:
            resultados = []
            threads = [
                threading.Thread(
                    target=lambda: resultados.append(
                        prose_spellcheck.load_dictionary(idioma)
                    )
                )
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            modulo.Dictionary.from_files = original
            prose_spellcheck.dictionary_files = real
            prose_spellcheck._dictionaries.pop(idioma, None)
            prose_spellcheck._language_locks.pop(idioma, None)

        self.assertEqual(len(chamadas), 1, "o dicionario foi carregado mais de uma vez")
        self.assertEqual(len(set(id(r) for r in resultados)), 1)

    def test_the_loader_never_calls_back_into_the_caller(self):
        """A janela PERGUNTA; a thread nao avisa (ROADMAP 26.5).

        A versao anterior recebia um `on_ready` e o chamava na thread de carga.
        Do outro lado isso virava `win.after(...)`, que registra um comando no
        interpretador Tk — e fora da thread principal levanta `RuntimeError:
        main thread is not in main loop`. A suite de janelas produziu esse
        traceback uma vez por janela.

        O contrato que substitui aquele: `request_dictionary` devolve o
        dicionario ou `None`, e `is_loading` diz se vale a pena perguntar de
        novo. Nenhuma das duas toca em nada de fora.
        """
        idioma = "zy-teste"
        real = prose_spellcheck.dictionary_files
        prose_spellcheck.dictionary_files = lambda alvo: (
            real("pt") if alvo == idioma else real(alvo)
        )
        try:
            self.assertIsNone(prose_spellcheck.request_dictionary(idioma))
            for _ in range(200):  # ate 20 s; a carga leva ~2,3 s
                if not prose_spellcheck.is_loading(idioma):
                    break
                time.sleep(0.1)
            self.assertFalse(prose_spellcheck.is_loading(idioma))
            self.assertIsNotNone(prose_spellcheck.request_dictionary(idioma))
        finally:
            prose_spellcheck.dictionary_files = real
            prose_spellcheck._dictionaries.pop(idioma, None)
            prose_spellcheck._language_locks.pop(idioma, None)

    def test_asking_for_a_language_without_a_dictionary_starts_no_thread(self):
        self.assertIsNone(prose_spellcheck.request_dictionary("it"))
        self.assertFalse(prose_spellcheck.is_loading("it"))

    def test_a_suggestion_is_offered_for_the_typo(self):
        self.assertIn(
            "posição", prose_spellcheck.suggestions("posiçao", self.dicionario)
        )

    def test_the_dictionary_knows_the_chess_terms_the_glossary_imposes(self):
        """A contraprova do dicionario escolhido: se ele nao souber a
        terminologia que o glossario impoe, o corretor briga com a decisao de
        quem o usa."""
        for termo in (
            "xeque", "cravada", "qualidade", "abandonaram", "peão",
            "coluna", "fila", "casa", "dama", "cavalo", "bispo", "torre",
            "lance", "partida", "final", "empate",
        ):
            with self.subTest(termo=termo):
                self.assertEqual(self.marcas(f"Uma {termo} aqui."), [])

    def test_a_term_the_dictionary_lacks_is_covered_by_the_glossary(self):
        """O que o dicionario de 2010 nao tem, o glossario cobre.

        `contra-jogo` sozinho respondia por 58 das 143 marcas do banco de
        desenvolvimento, e o filtro que o cala nao e uma lista nova: e o lado
        direito das regras que o proprio usuario escreveu.
        """
        texto = "As pretas ficam com contra-jogo suficiente."
        self.assertEqual(self.marcas(texto), ["contra-jogo"])

        vocabulario = prose_spellcheck.glossary_vocabulary(
            [("counterplay", "contra-jogo"), ("check", "xeque")]
        )
        self.assertEqual(
            prose_spellcheck.misspelled_spans(texto, self.dicionario, vocabulario),
            [],
        )

    def test_the_glossary_vocabulary_comes_from_the_replacement_side(self):
        """O lado ESQUERDO e o texto que se quer trocar — o errado. Ensina-lo ao
        corretor calaria o aviso no unico lugar em que ele acerta sozinho."""
        vocabulario = prose_spellcheck.glossary_vocabulary(
            [("posiçao", "posição")]
        )
        self.assertIn("posição", vocabulario)
        self.assertNotIn("posiçao", vocabulario)
        self.assertEqual(
            self.marcas("Uma posiçao ruim."), ["posiçao"]
        )


if __name__ == "__main__":
    unittest.main()
