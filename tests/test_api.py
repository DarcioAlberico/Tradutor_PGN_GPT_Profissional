"""A camada de rede: divisao por sentenca, tentativas, ritmo, cancelamento.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import threading
import unittest
import unittest.mock

from tradutor_pgn import (
    translation_api,
)
from tradutor_pgn.translation_api import split_text_for_translation, translate_text
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeResponse,
    FakeSession,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class TranslationApiTests(unittest.TestCase):
    def test_translate_text_uses_provided_session(self):
        class FakeResponse:
            status_code = 200

            def json(self):
                return [[["Ola", "Hello"]]]

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, params=None, timeout=None):
                self.calls.append((url, params, timeout))
                return FakeResponse()

        session = FakeSession()

        result = translate_text("Hello", "pt", session=session)

        self.assertEqual(result, "Ola")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["q"], "Hello")
        self.assertEqual(session.calls[0][2], 30)


class CancelReachesTheRetryLoopTests(unittest.TestCase):
    """Garantia C4: "Cancelar" alcanca o laco de tentativas (ROADMAP 22.13).

    `translate_text_chunk` nem RECEBIA o `cancel_flag`: o laco de tres tentativas
    dormia em `time.sleep` sem olhar cancelamento, e `translate_text` so conferia
    entre chunks — o que nao cobre nada num comentario de um chunk so, que e a
    maioria. Com o timeout real de 30 s por tentativa, a janela sem efeito chega
    a ~93 s por chunk.
    """

    class SessaoQueFalha:
        """Devolve sempre um status que pede nova tentativa, sem dormir de verdade."""

        def __init__(self, status=503, ligar_flag=None):
            self.chamadas = 0
            self.status = status
            self.ligar_flag = ligar_flag

        def get(self, _url, params=None, timeout=None):
            self.chamadas += 1
            if self.ligar_flag is not None:
                self.ligar_flag.set()

            class Resposta:
                status_code = self.status

                def json(self_inner):  # pragma: no cover - nao chega a ser lido
                    return [[["", ""]]]

            return Resposta()

    def setUp(self):
        # As esperas do retry sao reais (1,5 s + 3 s). O teste substitui o
        # `sleep` porque o assunto dele e QUANTAS tentativas acontecem, e nao
        # quanto elas esperam — e uma suite que dorme 4,5 s por caso deixa de ser
        # rodada. As esperas tem teste proprio em `retry_delay_seconds`.
        self.dormidas = []
        self.sleep_original = translation_api.time.sleep
        translation_api.time.sleep = self.dormidas.append
        self.addCleanup(setattr, translation_api.time, "sleep", self.sleep_original)

    def test_without_the_flag_it_still_tries_three_times(self):
        """A ancora: sem cancelamento, o retry continua sendo o de sempre."""
        sessao = self.SessaoQueFalha()

        resultado = translation_api.translate_text_chunk("Hello", "pt", session=sessao)

        self.assertIsNone(resultado)
        self.assertEqual(sessao.chamadas, translation_api.MAX_ATTEMPTS)

    def test_cancelling_during_the_first_attempt_stops_the_others(self):
        """Era o defeito medido: as tres rodavam com o flag ja ligado."""
        flag = threading.Event()
        sessao = self.SessaoQueFalha(ligar_flag=flag)

        resultado = translation_api.translate_text_chunk(
            "Hello", "pt", session=sessao, cancel_flag=flag
        )

        self.assertIsNone(resultado)
        self.assertEqual(sessao.chamadas, 1)

    def test_it_does_not_wait_before_giving_up(self):
        """Conferido antes da espera: desistir depois de dormir 1,5 s e desistir tarde."""
        flag = threading.Event()
        sessao = self.SessaoQueFalha(ligar_flag=flag)

        translation_api.translate_text_chunk(
            "Hello", "pt", session=sessao, cancel_flag=flag
        )

        self.assertEqual(self.dormidas, [])

    def test_cancelling_DURING_the_wait_stops_the_next_attempt(self):
        """A segunda conferencia, e a que cobre a janela de tempo que importa.

        As duas esperas somam 4,5 s e a requisicao pode levar 30 — e ali, parado,
        que o usuario clica em Cancelar. Uma mutacao mostrou que sem este caso a
        conferencia do topo do laco podia ser removida sem nada ficar vermelho: a
        de antes da espera ja pegava o cenario em que o flag e ligado DURANTE a
        requisicao.
        """
        flag = threading.Event()
        sessao = self.SessaoQueFalha()
        # O cancelamento acontece enquanto o programa dorme entre as tentativas.
        translation_api.time.sleep = lambda _s: flag.set()

        resultado = translation_api.translate_text_chunk(
            "Hello", "pt", session=sessao, cancel_flag=flag
        )

        self.assertIsNone(resultado)
        self.assertEqual(sessao.chamadas, 1)

    def test_a_flag_already_set_does_not_call_the_api_at_all(self):
        flag = threading.Event()
        flag.set()
        sessao = self.SessaoQueFalha()

        resultado = translation_api.translate_text_chunk(
            "Hello", "pt", session=sessao, cancel_flag=flag
        )

        self.assertIsNone(resultado)
        self.assertEqual(sessao.chamadas, 0)

    def test_the_flag_crosses_from_translate_text(self):
        """Um comentario de um chunk so nao tinha conferencia nenhuma."""
        flag = threading.Event()
        sessao = self.SessaoQueFalha(ligar_flag=flag)

        resultado = translation_api.translate_text(
            "Hello", "pt", cancel_flag=flag, session=sessao
        )

        self.assertIsNone(resultado)
        self.assertEqual(sessao.chamadas, 1)


class RetryBackoffTests(unittest.TestCase):
    """Roadmap 7.2: a espera entre tentativas cresce, e reage a 429.

    Era `random.uniform(0.3, 2.2)` fixo entre as tres tentativas. Contra 429 isso
    e quase o mesmo que nao esperar: se o servidor pediu para desacelerar, a
    terceira tentativa chegava tao cedo quanto a primeira.

    O jitter e sorteado, entao comparar duas esperas reais seria instavel — as
    faixas de tentativas vizinhas se sobrepoem. Aqui o fator e fixado; a
    integracao logo abaixo confere que a espera real cai dentro da faixa.
    """

    def espera(self, attempt, status=None, jitter=1.0):
        return translation_api.retry_delay_seconds(attempt, status, jitter=jitter)

    def test_the_wait_doubles_at_each_attempt(self):
        base = translation_api.RETRY_BASE_SECONDS
        self.assertEqual(self.espera(1, 503), base)
        self.assertEqual(self.espera(2, 503), base * 2)
        self.assertEqual(self.espera(3, 503), base * 4)

    def test_a_rate_limit_waits_longer_than_a_server_error(self):
        """429 e 5xx tem causas diferentes e merecem esperas diferentes."""
        for attempt in (1, 2, 3):
            with self.subTest(attempt=attempt):
                self.assertGreater(self.espera(attempt, 429), self.espera(attempt, 503))

    def test_the_wait_is_capped(self):
        self.assertEqual(
            self.espera(40, 429), translation_api.RETRY_MAX_SECONDS
        )

    def test_a_network_error_uses_the_server_error_pace(self):
        """Sem resposta nao ha status; a espera nao pode virar zero nem explodir."""
        self.assertEqual(self.espera(1, None), translation_api.RETRY_BASE_SECONDS)

    def test_the_jitter_is_multiplicative(self):
        """Duas execucoes que tomem 429 juntas precisam se espalhar em proporcao.

        Um jitter aditivo de fracoes de segundo nao separa esperas de 8 s; um
        multiplicativo separa.
        """
        cheio = self.espera(3, 429, jitter=None)
        alvo = min(
            translation_api.RETRY_BASE_429_SECONDS * 4,
            translation_api.RETRY_MAX_SECONDS,
        )
        menor, maior = translation_api.RETRY_JITTER
        self.assertGreaterEqual(cheio, alvo * menor)
        self.assertLessEqual(cheio, alvo * maior)


class RequestPacerTests(unittest.TestCase):
    """Roadmap 7.2: o intervalo normal reage ao que a API responde.

    O retry conserta a requisicao que falhou, nao a causa: esgotadas as
    tentativas o comentario falha igual. Um 429 e o unico sinal confiavel de que
    o ritmo esta alto demais, e o intervalo das requisicoes SEGUINTES e o unico
    lugar onde esse sinal pode ser usado.
    """

    def pacer(self, **kwargs):
        return translation_api.RequestPacer(**kwargs)

    def test_at_rest_it_behaves_exactly_like_before(self):
        """Sem 429, o intervalo e o sorteio de sempre — multiplicador 1."""
        pacer = self.pacer()
        self.assertEqual(pacer.multiplier, 1.0)
        menor, maior = pacer.base_range
        for _ in range(50):
            self.assertGreaterEqual(pacer.next_delay(), menor)
            self.assertLessEqual(pacer.next_delay(), maior)

    def test_the_first_rate_limit_lifts_the_pace_off_the_floor(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        self.assertEqual(pacer.multiplier, pacer.first_multiplier)
        self.assertGreater(pacer.next_delay(), min(pacer.base_range))

    def test_repeated_rate_limits_keep_slowing_down_up_to_a_ceiling(self):
        pacer = self.pacer()
        anteriores = []
        for _ in range(10):
            pacer.record_rate_limited()
            anteriores.append(pacer.multiplier)

        self.assertEqual(anteriores[1], anteriores[0] * pacer.growth)
        self.assertEqual(anteriores[-1], pacer.maximum, "sem teto, o ritmo some")
        self.assertEqual(sorted(anteriores), anteriores, "o ritmo nunca acelera aqui")

    def test_a_clean_streak_is_needed_before_speeding_up_again(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        alto = pacer.multiplier

        for _ in range(pacer.clean_streak - 1):
            pacer.record_success()
        self.assertEqual(pacer.multiplier, alto, "acelerou antes da sequencia limpa")

        pacer.record_success()
        self.assertEqual(pacer.multiplier, max(1.0, alto * pacer.decay))

    def test_a_rate_limit_resets_the_clean_streak(self):
        """Meia sequencia limpa seguida de 429 nao pode contar como progresso."""
        pacer = self.pacer()
        pacer.record_rate_limited()
        for _ in range(pacer.clean_streak - 1):
            pacer.record_success()

        pacer.record_rate_limited()
        alto = pacer.multiplier
        pacer.record_success()
        self.assertEqual(pacer.multiplier, alto)

    def test_the_pace_never_goes_below_the_original_interval(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        for _ in range(pacer.clean_streak * 40):
            pacer.record_success()

        self.assertEqual(pacer.multiplier, 1.0)
        self.assertLessEqual(pacer.next_delay(), max(pacer.base_range))


class TranslateTextChunkTests(unittest.TestCase):
    """Retry/backoff da camada de rede (item 5 do ROADMAP).

    Nenhum destes testes toca a rede: a sessao HTTP e injetada.
    """

    OK_PAYLOAD = [[["Bom dia", "Good morning"], [" mundo", " world"]]]

    def setUp(self):
        # O backoff real dorme ate 2,2 s por tentativa — 4,4 s por teste que
        # esgota as tentativas. Aqui so registramos que dormiu.
        #
        # `translation_api.time` E o modulo padrao, entao isto troca
        # `time.sleep` globalmente enquanto o teste roda. E aceitavel porque a
        # suite e sequencial e o `addCleanup` devolve o original mesmo se o
        # teste falhar no meio.
        self.sleeps = []
        self.previous_sleep = translation_api.time.sleep
        translation_api.time.sleep = self.sleeps.append
        self.addCleanup(
            setattr, translation_api.time, "sleep", self.previous_sleep
        )
        self.logs = []

    def translate(self, script, text="Good morning world"):
        session = FakeSession(script)
        result = translation_api.translate_text_chunk(
            text, "pt", self.logs.append, session=session
        )
        return result, session

    def test_success_joins_the_segments(self):
        result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)])

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(self.sleeps, [], "nao dorme quando acerta de primeira")

    def test_request_carries_only_the_text(self):
        """Garantia W1: nada alem do texto a traduzir sai daqui."""
        _result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)], "abc")

        params = session.calls[0]["params"]
        self.assertEqual(params["q"], "abc")
        self.assertEqual(params["tl"], "pt")
        self.assertEqual(set(params) - {"client", "sl", "tl", "dt", "q"}, set())

    def test_the_declared_source_language_goes_in_the_request(self):
        """`sl=auto` faz o endpoint adivinhar a partir do texto.

        Um comentario curto de xadrez — "Ng5!", "Bien jugado" — e pouco texto
        para adivinhar, e o palpite errado produz uma traducao errada sem erro
        nenhum. Dito o idioma, ele para de tentar.
        """
        session = FakeSession([FakeResponse(200, self.OK_PAYLOAD)])
        translation_api.translate_text_chunk(
            "abc", "pt", self.logs.append, session=session, source_language="es"
        )

        self.assertEqual(session.calls[0]["params"]["sl"], "es")

    def test_without_a_declared_source_it_still_asks_for_detection(self):
        """O padrao continua sendo o que o programa sempre fez."""
        _result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)], "abc")

        self.assertEqual(session.calls[0]["params"]["sl"], "auto")

    def test_the_source_language_survives_the_split_into_chunks(self):
        """Um comentario longo vira varias requisicoes, e todas sao do mesmo PGN.

        Perder o idioma entre a primeira e a segunda daria metade da traducao
        com o idioma declarado e metade adivinhada.
        """
        session = FakeSession([FakeResponse(200, self.OK_PAYLOAD) for _ in range(10)])
        texto = ("Frase. " * 2000).strip()
        self.assertGreater(len(split_text_for_translation(texto)), 1)

        translation_api.translate_text(
            texto, "pt", session=session, source_language="it"
        )

        self.assertTrue(session.calls)
        self.assertEqual(
            {chamada["params"]["sl"] for chamada in session.calls}, {"it"}
        )

    def test_empty_segments_are_skipped(self):
        payload = [[["Um", "One"], None, ["", ""], [" dois", " two"]]]
        result, _session = self.translate([FakeResponse(200, payload)])

        self.assertEqual(result, "Um dois")

    def test_retryable_status_is_retried_three_times(self):
        result, session = self.translate([FakeResponse(503) for _ in range(3)])

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 3)
        # Dorme entre as tentativas, nao depois da ultima.
        self.assertEqual(len(self.sleeps), 2)

    def test_retryable_then_success(self):
        result, session = self.translate(
            [FakeResponse(429), FakeResponse(200, self.OK_PAYLOAD)]
        )

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(len(self.sleeps), 1)

    def test_every_retryable_status_is_retried(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.sleeps.clear()
                result, session = self.translate(
                    [FakeResponse(status), FakeResponse(200, self.OK_PAYLOAD)]
                )
                self.assertEqual(result, "Bom dia mundo")
                self.assertEqual(len(session.calls), 2)

    def test_other_statuses_fail_immediately(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.sleeps.clear()
                result, session = self.translate([FakeResponse(status)])
                self.assertIsNone(result)
                self.assertEqual(len(session.calls), 1, "nao pode insistir")
                self.assertEqual(self.sleeps, [])

    def test_network_error_is_retried(self):
        result, session = self.translate(
            [
                translation_api.requests.RequestException("timeout"),
                translation_api.requests.RequestException("timeout"),
                FakeResponse(200, self.OK_PAYLOAD),
            ]
        )

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 3)

    def test_network_error_exhausted_returns_none(self):
        result, session = self.translate(
            [translation_api.requests.RequestException("timeout") for _ in range(3)]
        )

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 3)
        self.assertTrue(any("tentativa 3/3" in line for line in self.logs))

    def test_unexpected_payload_fails_without_retrying(self):
        """Uma resposta 200 ilegivel nao melhora tentando de novo."""
        result, session = self.translate([FakeResponse(200, raise_on_json=True)])

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(any("inesperada" in line.lower() for line in self.logs))

    def test_failure_is_always_logged(self):
        """Garantia T2: falha nunca passa em silencio."""
        self.translate([FakeResponse(500) for _ in range(3)])
        self.assertTrue(self.logs)
        self.assertTrue(all("[ERRO API]" in line for line in self.logs))

    def test_each_wait_falls_inside_its_attempt_window(self):
        """A espera real e sorteada, mas dentro da faixa daquela tentativa."""
        self.translate([FakeResponse(503) for _ in range(3)])

        self.assertEqual(len(self.sleeps), 2)
        menor, maior = translation_api.RETRY_JITTER
        for indice, dormiu in enumerate(self.sleeps):
            attempt = indice + 1
            alvo = min(
                translation_api.RETRY_BASE_SECONDS * (2 ** indice),
                translation_api.RETRY_MAX_SECONDS,
            )
            with self.subTest(tentativa=attempt):
                self.assertGreaterEqual(dormiu, alvo * menor)
                self.assertLessEqual(dormiu, alvo * maior)

    def test_a_rate_limit_slows_the_following_requests(self):
        """O 429 precisa sair daqui e mudar o ritmo, nao so a proxima tentativa."""
        pacer = translation_api.RequestPacer()
        session = FakeSession([FakeResponse(429), FakeResponse(200, self.OK_PAYLOAD)])

        resultado = translation_api.translate_text_chunk(
            "Good morning world", "pt", self.logs.append, session=session, pacer=pacer
        )

        self.assertEqual(resultado, "Bom dia mundo")
        self.assertEqual(pacer.rate_limited, 1)
        self.assertGreater(pacer.multiplier, 1.0)

    def test_a_server_error_does_not_change_the_pace(self):
        """503 e problema do servidor, nao ritmo alto demais. Sao coisas distintas."""
        pacer = translation_api.RequestPacer()
        session = FakeSession([FakeResponse(503), FakeResponse(200, self.OK_PAYLOAD)])

        translation_api.translate_text_chunk(
            "Good morning world", "pt", self.logs.append, session=session, pacer=pacer
        )

        self.assertEqual(pacer.rate_limited, 0)
        self.assertEqual(pacer.multiplier, 1.0)

    def test_an_unreadable_200_does_not_count_as_a_clean_request(self):
        """Uma 200 ilegivel nao e sinal de que o ritmo esta bom."""
        pacer = translation_api.RequestPacer()
        pacer.record_rate_limited()
        pacer.clean_run = pacer.clean_streak - 1

        translation_api.translate_text_chunk(
            "x",
            "pt",
            self.logs.append,
            session=FakeSession([FakeResponse(200, raise_on_json=True)]),
            pacer=pacer,
        )

        self.assertEqual(pacer.clean_run, pacer.clean_streak - 1)

    def test_the_pacer_is_optional(self):
        """A camada de rede continua utilizavel sem ele."""
        resultado, _session = self.translate([FakeResponse(200, self.OK_PAYLOAD)])
        self.assertEqual(resultado, "Bom dia mundo")

    def test_works_without_a_logger(self):
        session = FakeSession([FakeResponse(404)])
        self.assertIsNone(
            translation_api.translate_text_chunk("x", "pt", None, session=session)
        )


class TranslateTextTests(unittest.TestCase):
    """A camada acima: divisao em partes e cancelamento."""

    def setUp(self):
        self.previous = translation_api.translate_text_chunk
        self.addCleanup(
            setattr, translation_api, "translate_text_chunk", self.previous
        )

    def test_one_failed_chunk_fails_the_whole_text(self):
        """Garantia T3: nao se monta uma traducao pela metade."""
        chamadas = []

        def fake(chunk, _lang, _log=None, session=None, pacer=None, source_language="", cancel_flag=None):
            chamadas.append(chunk)
            return None if len(chamadas) == 2 else "ok"

        translation_api.translate_text_chunk = fake
        texto = ("Frase. " * 2000).strip()
        self.assertGreater(len(split_text_for_translation(texto)), 1)

        self.assertIsNone(translation_api.translate_text(texto, "pt"))

    def test_cancel_flag_stops_before_the_next_request(self):
        chamadas = []
        flag = threading.Event()

        def fake(chunk, _lang, _log=None, session=None, pacer=None, source_language="", cancel_flag=None):
            chamadas.append(chunk)
            flag.set()
            return "ok"

        translation_api.translate_text_chunk = fake
        texto = ("Frase. " * 2000).strip()

        self.assertIsNone(
            translation_api.translate_text(texto, "pt", cancel_flag=flag)
        )
        self.assertEqual(len(chamadas), 1, "parou apos o primeiro pedaco")


if __name__ == "__main__":
    unittest.main()
