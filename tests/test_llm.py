"""Os modelos de linguagem como motor (ROADMAP 28.7): chaves, prompt, provedores.

Sem rede: o `chat/completions` e exercitado por uma sessao falsa que grava o
que seria enviado e devolve o que o teste manda; o Anthropic, por um cliente
falso injetado no lugar do SDK. O que se confere e o contrato com o worker —
texto com ` ||| ` entra, texto com ` ||| ` sai, na ORDEM dos ids —, o que o
log ve (nunca a chave inteira, K1) e o que um 401 faz com o resto da execucao.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import setup_module_sandbox, teardown_module_sandbox

from tradutor_pgn import api_keys, llm_costs, llm_prompt, llm_providers, settings
from tradutor_pgn.llm_providers import (
    GOOGLE_PROVIDER,
    PROVIDERS,
    LLMTranslator,
    build_translator,
    configured_providers,
)
from tradutor_pgn.pgn_utils import BATCH_SEPARATOR


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


CHAVE = "sk-teste-0000-abcd"


# ================================================================== chaves


class ApiKeysTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "chaves.json")

    def test_a_key_round_trips_and_an_empty_one_deletes(self):
        api_keys.save_api_key("openai", CHAVE, self.path)
        self.assertEqual(api_keys.load_api_key("openai", path=self.path), CHAVE)
        self.assertEqual(api_keys.stored_key_state("openai", self.path), "ok")
        # O arquivo nao tem a chave em claro (no Windows, DPAPI; fora, base64
        # marcado como tal — e o teste aceita os dois, porque roda nos dois).
        conteudo = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn(CHAVE, conteudo)
        registro = json.loads(conteudo)["openai"]
        self.assertIn(registro["cifra"], (api_keys.CIFRA_DPAPI, api_keys.CIFRA_NENHUMA))

        api_keys.save_api_key("openai", "   ", self.path)
        self.assertIsNone(api_keys.load_api_key("openai", path=self.path))
        self.assertEqual(api_keys.stored_key_state("openai", self.path), "ausente")

    def test_saving_one_provider_leaves_the_others_alone(self):
        api_keys.save_api_key("openai", CHAVE, self.path)
        api_keys.save_api_key("deepseek", "ds-1", self.path)
        api_keys.save_api_key("openai", "", self.path)
        self.assertEqual(api_keys.load_api_key("deepseek", path=self.path), "ds-1")

    def test_the_environment_wins_over_the_file(self):
        api_keys.save_api_key("openai", CHAVE, self.path)
        with mock.patch.dict(os.environ, {"X_TESTE_KEY": " do-ambiente "}):
            self.assertEqual(api_keys.load_api_key("openai", "X_TESTE_KEY", self.path), "do-ambiente")
        with mock.patch.dict(os.environ, {"X_TESTE_KEY": ""}):
            self.assertEqual(api_keys.load_api_key("openai", "X_TESTE_KEY", self.path), CHAVE)

    def test_an_unreadable_record_is_reported_not_raised(self):
        Path(self.path).write_text(
            json.dumps({"openai": {"cifra": "dpapi", "valor": "bm90LWRwYXBp"}}), encoding="utf-8"
        )
        self.assertIsNone(api_keys.load_api_key("openai", path=self.path))
        self.assertEqual(api_keys.stored_key_state("openai", self.path), "ilegivel")
        # Lixo no arquivo: nada quebra, nada e chave.
        Path(self.path).write_text("{nao e json", encoding="utf-8")
        self.assertIsNone(api_keys.load_api_key("openai", path=self.path))
        self.assertEqual(api_keys.stored_key_state("openai", self.path), "ausente")

    def test_the_mask_shows_only_the_tail(self):
        self.assertEqual(api_keys.mask_api_key(CHAVE), "****abcd")
        self.assertEqual(api_keys.mask_api_key(""), "")
        self.assertEqual(api_keys.mask_api_key(None), "")

    def test_configured_providers_follow_the_keys(self):
        with mock.patch.object(api_keys, "keys_path", return_value=self.path):
            with mock.patch.dict(os.environ, {spec.env_var: "" for spec in PROVIDERS.values()}):
                self.assertEqual(configured_providers(), [])
                api_keys.save_api_key("deepseek", "ds", self.path)
                self.assertEqual(configured_providers(), ["deepseek"])
                with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant"}):
                    self.assertEqual(configured_providers(), ["anthropic", "deepseek"])


# ================================================================== prompt


class PromptTests(unittest.TestCase):
    def test_the_prompt_names_the_pair_letters_and_is_stable(self):
        a = llm_prompt.prompt_de_sistema("en", "pt")
        self.assertEqual(a, llm_prompt.prompt_de_sistema("en", "pt"))
        self.assertIn("K -> R, Q -> D, R -> T, B -> B, N -> C", a)
        self.assertIn("⟦n⟧", a)
        self.assertIn('{"itens": [{"id": n, "traducao": "..."}]}', a)
        self.assertIn("as brancas", a)

    def test_an_unknown_pair_keeps_the_notation_and_a_blank_source_is_detect(self):
        sem_tabela = llm_prompt.prompt_de_sistema("", "pt")
        self.assertIn("mantenha a notacao EXATAMENTE", sem_tabela)
        self.assertIn("o idioma do original", sem_tabela)
        self.assertNotIn("K -> R", sem_tabela)
        italiano = llm_prompt.prompt_de_sistema("en", "it")
        self.assertIn("K -> R, Q -> D, R -> T, B -> A, N -> C", italiano)
        self.assertNotIn("'White' -> 'as brancas'", italiano)

    def test_the_automatic_rules_block_is_empty_without_rules(self):
        self.assertEqual(llm_prompt.regras_automaticas_em_texto([]), "")
        self.assertIn("rook -> torre", llm_prompt.regras_automaticas_em_texto([("rook", "torre", "automatic")]))

    def test_validation_rejects_a_non_list(self):
        por_id, problemas = llm_prompt.validar_lote(json.dumps({"itens": {"id": 1}}), [1])
        self.assertEqual(por_id, {})
        self.assertTrue(problemas)


# ======================================================= chat/completions


class FakeResponse:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text if body is None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("nao e json")
        return self._body


class FakeSession:
    """Grava cada `post`/`get` e devolve as respostas na ordem combinada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def post(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        return self.respostas.pop(0)

    def get(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def resposta_ok(itens, finish="stop", usage=None):
    return FakeResponse(
        200,
        {
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {"content": json.dumps({"itens": itens}, ensure_ascii=False)},
                }
            ],
            "usage": usage or {"prompt_tokens": 100, "completion_tokens": 40},
        },
    )


class ChatCompletionsTranslatorTests(unittest.TestCase):
    def tradutor(self, respostas, provider="deepseek", regras=None, sugestoes=None):
        t = LLMTranslator(
            PROVIDERS[provider], "modelo-x", CHAVE, "en", "pt", regras, sugestoes
        )
        t._client = FakeSession(respostas)
        self.logs = []
        return t

    def test_a_batch_goes_as_numbered_json_and_comes_back_in_id_order(self):
        # A resposta vem embaralhada; o texto sai na ordem dos ids.
        t = self.tradutor([resposta_ok([{"id": 2, "traducao": "dois"}, {"id": 1, "traducao": "um"}])])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "dois"]))

        url, kwargs = t._client.chamadas[0]
        self.assertEqual(url, "https://api.deepseek.com/v1/chat/completions")
        corpo = kwargs["json"]
        self.assertEqual(corpo["model"], "modelo-x")
        self.assertEqual(corpo["response_format"], {"type": "json_object"})
        self.assertIn("max_tokens", corpo)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {CHAVE}")
        itens = json.loads(corpo["messages"][1]["content"].split("\n\n")[1])["itens"]
        self.assertEqual([(i["id"], i["texto"]) for i in itens], [(1, "one"), (2, "two")])
        self.assertIn("Regras que nao podem ser quebradas", corpo["messages"][0]["content"])
        self.assertEqual(t.usage.requests, 1)
        self.assertEqual((t.usage.input_tokens, t.usage.output_tokens), (100, 40))

    def test_cached_prompt_tokens_are_taken_out_of_the_input(self):
        """`prompt_tokens` inclui o cache; `Usage.input_tokens` e so o que foi
        cobrado inteiro — a mesma conta da Anthropic, para o custo ser uma so."""
        t = self.tradutor([resposta_ok(
            [{"id": 1, "traducao": "um"}],
            usage={"prompt_tokens": 1000, "completion_tokens": 40,
                   "prompt_tokens_details": {"cached_tokens": 900}},
        )], provider="openai")
        t.translate("one", "pt")
        self.assertEqual((t.usage.input_tokens, t.usage.cache_read_tokens), (100, 900))
        t = self.tradutor([resposta_ok(
            [{"id": 1, "traducao": "um"}],
            usage={"prompt_tokens": 500, "completion_tokens": 40, "prompt_cache_hit_tokens": 450},
        )])
        t.translate("one", "pt")
        self.assertEqual((t.usage.input_tokens, t.usage.cache_read_tokens), (50, 450))
        self.assertIn("450 lidos do cache", t.usage.summary())

    def test_openai_uses_the_new_output_limit_field(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}])], provider="openai")
        t.translate("one", "pt")
        corpo = t._client.chamadas[0][1]["json"]
        self.assertIn("max_completion_tokens", corpo)
        self.assertNotIn("max_tokens", corpo)
        self.assertEqual(t._client.chamadas[0][0], "https://api.openai.com/v1/chat/completions")

    def test_the_reading_context_travels_with_each_item(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}, {"id": 2, "traducao": "dois"}])])
        t.translate(BATCH_SEPARATOR.join(["one", "two"]), "pt", contexts=[("12. Nf3", "Nc6"), ("", "13. O-O")])
        corpo = t._client.chamadas[0][1]["json"]
        itens = json.loads(corpo["messages"][1]["content"].split("\n\n")[1])["itens"]
        self.assertEqual(
            [(i["antes"], i["depois"]) for i in itens], [("12. Nf3", "Nc6"), ("", "13. O-O")]
        )
        # Contexto de tamanho errado nao derruba nada: vai vazio.
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}])])
        t.translate("one", "pt", contexts=[("a", "b"), ("c", "d")])
        corpo = t._client.chamadas[0][1]["json"]
        itens = json.loads(corpo["messages"][1]["content"].split("\n\n")[1])["itens"]
        self.assertEqual((itens[0]["antes"], itens[0]["depois"]), ("", ""))

    def test_a_cut_batch_is_split_in_two_and_not_sent_item_by_item(self):
        """`max_tokens` e do conteudo do lote, nao da conexao: duas metades
        (B1), em vez de `None` — que o worker trataria como a rede caida."""
        t = self.tradutor([
            resposta_ok([{"id": 1, "traducao": "x"}], finish="length"),
            resposta_ok([{"id": 1, "traducao": "um"}, {"id": 2, "traducao": "dois"}]),
            resposta_ok([{"id": 1, "traducao": "tres"}, {"id": 2, "traducao": "quatro"}]),
        ])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two", "three", "four"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "dois", "tres", "quatro"]))
        self.assertEqual(len(t._client.chamadas), 3)
        self.assertTrue(any("lote de 4 itens dividido em 2 + 2" in l for l in self.logs), self.logs)

    def test_a_refused_item_is_isolated_and_the_rest_is_not_paid_twice(self):
        """A recusa isola o item: os outros saem das metades, e quando o
        worker os reenviar sozinhos a resposta vem da memoria do lote."""
        recusa = FakeResponse(200, {
            "choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "nao"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0},
        })
        t = self.tradutor([
            recusa,                                            # [one, two, three]
            resposta_ok([{"id": 1, "traducao": "um"}]),        # [one]
            recusa,                                            # [two, three]
            resposta_ok([{"id": 1, "traducao": "dois"}]),      # [two]
            recusa,                                            # [three]
            recusa,                                            # three, sozinho, pelo worker
        ])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two", "three"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "dois", ""]), "o recusado volta vazio")
        self.assertEqual(len(t._client.chamadas), 5)
        # O que o worker faz com a parte vazia: cada item sozinho.
        self.assertEqual(t.translate("one", "pt"), "um")
        self.assertEqual(t.translate("two", "pt"), "dois")
        self.assertEqual(len(t._client.chamadas), 5, "os dois vieram da memoria, sem requisicao")
        self.assertIsNone(t.translate("three", "pt", self.logs.append))
        self.assertEqual(len(t._client.chamadas), 6)
        self.assertTrue(any("recusou o lote" in l for l in self.logs))

    def test_a_new_batch_forgets_the_divided_one(self):
        t = self.tradutor([
            resposta_ok([{"id": 1, "traducao": "x"}], finish="length"),
            resposta_ok([{"id": 1, "traducao": "um"}]),
            resposta_ok([{"id": 1, "traducao": "dois"}]),
            resposta_ok([{"id": 1, "traducao": "tres"}, {"id": 2, "traducao": "quatro"}]),
            resposta_ok([{"id": 1, "traducao": "UM"}]),
        ])
        t.translate(BATCH_SEPARATOR.join(["one", "two"]), "pt")
        t.translate(BATCH_SEPARATOR.join(["three", "four"]), "pt")
        self.assertEqual(t.translate("one", "pt"), "UM", "o lote novo apagou a memoria do anterior")
        self.assertEqual(len(t._client.chamadas), 5)

    def test_a_single_comment_is_a_batch_of_one(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}])])
        self.assertEqual(t.translate("one", "pt"), "um")

    def test_a_missing_id_comes_back_as_an_empty_part_for_the_worker_to_resend(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}, {"id": 3, "traducao": "tres"}])])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two", "three"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "", "tres"]))
        self.assertTrue(any("id 2 faltou" in linha for linha in self.logs))

    def test_the_glossary_rules_and_matching_suggestions_travel(self):
        t = self.tradutor(
            [resposta_ok([{"id": 1, "traducao": "x"}])],
            regras=[("rook", "torre", "automatic")],
            sugestoes=[("bishop", "bispo", "suggestion"), ("queen", "dama", "suggestion")],
        )
        t.translate("the bishop and the rook", "pt")
        corpo = t._client.chamadas[0][1]["json"]
        self.assertIn("rook -> torre", corpo["messages"][0]["content"])
        self.assertIn("bishop -> bispo", corpo["messages"][1]["content"])
        self.assertNotIn("queen -> dama", corpo["messages"][1]["content"])

    def test_a_401_is_fatal_and_the_key_never_reaches_the_log(self):
        t = self.tradutor([FakeResponse(401, text="unauthorized")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        self.assertIsNotNone(t.fatal_error)
        self.assertTrue(any("[ERRO]" in linha for linha in self.logs))
        # A segunda chamada nao vai a rede: a sessao nao tem mais respostas e
        # um `post` levantaria IndexError.
        self.assertIsNone(t.translate("two", "pt", self.logs.append))
        self.assertEqual(len(t._client.chamadas), 1)
        for linha in self.logs + [t.describe()]:
            self.assertNotIn(CHAVE, linha)
        self.assertIn("****abcd", t.describe())

    def test_a_retryable_status_is_retried_and_a_final_one_is_a_failure(self):
        with mock.patch.object(llm_providers.time, "sleep") as dormiu:
            t = self.tradutor([FakeResponse(429, text="slow"), resposta_ok([{"id": 1, "traducao": "um"}])])
            self.assertEqual(t.translate("one", "pt", self.logs.append), "um")
            self.assertEqual(len(t._client.chamadas), 2)
            self.assertEqual(dormiu.call_count, 1)

            t = self.tradutor([FakeResponse(500, text="x")] * llm_providers.MAX_ATTEMPTS)
            self.assertIsNone(t.translate("one", "pt", self.logs.append))
            self.assertIsNone(t.fatal_error, "5xx nao e fatal: o proximo lote tenta de novo")
            self.assertEqual(t.usage.failures, 1)

    def test_a_truncated_answer_and_bad_json_are_failures_not_translations(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}], finish="length")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        t = self.tradutor([FakeResponse(200, text="<html>")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        t = self.tradutor([FakeResponse(200, {"choices": [{"message": {"content": "nao e json"}}]})])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))

    def test_a_set_cancel_flag_makes_no_request(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}])])
        flag = types.SimpleNamespace(is_set=lambda: True)
        self.assertIsNone(t.translate("one", "pt", None, flag))
        self.assertEqual(t._client.chamadas, [])


# ============================================================== anthropic


class FakeAnthropicMessages:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def resposta_anthropic(itens, stop_reason="end_turn"):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=json.dumps({"itens": itens}))],
        usage=types.SimpleNamespace(
            input_tokens=200, output_tokens=50, cache_read_input_tokens=150,
            cache_creation_input_tokens=30,
        ),
        stop_reason=stop_reason,
    )


@unittest.skipUnless(llm_providers.anthropic_sdk_available(), "sem o SDK anthropic")
class AnthropicTranslatorTests(unittest.TestCase):
    def tradutor(self, respostas):
        t = LLMTranslator(PROVIDERS["anthropic"], "claude-x", CHAVE, "en", "pt", [("rook", "torre", "a")])
        t._client = types.SimpleNamespace(messages=FakeAnthropicMessages(respostas))
        self.logs = []
        return t

    def test_the_request_carries_the_cached_system_blocks_and_the_schema(self):
        t = self.tradutor([resposta_anthropic([{"id": 1, "traducao": "um"}, {"id": 2, "traducao": "dois"}])])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "dois"]))
        pedido = t._client.messages.chamadas[0]
        self.assertEqual(pedido["model"], "claude-x")
        self.assertEqual(len(pedido["system"]), 2, "regras duras + glossario automatico")
        for bloco in pedido["system"]:
            self.assertEqual(bloco["cache_control"], {"type": "ephemeral"})
        self.assertEqual(pedido["output_config"]["format"]["schema"], llm_prompt.ESQUEMA_DO_LOTE)
        self.assertEqual(t.usage.cache_read_tokens, 150)
        self.assertEqual(t.usage.cache_write_tokens, 30)
        self.assertIn("30 escritos no cache", t.usage.summary())

    def test_refusal_and_max_tokens_are_failures(self):
        t = self.tradutor([resposta_anthropic([], stop_reason="refusal")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        t = self.tradutor([resposta_anthropic([], stop_reason="max_tokens")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        self.assertIsNone(t.fatal_error)

    def test_a_cut_batch_is_split_and_the_limit_is_the_pilot_one(self):
        t = self.tradutor([
            resposta_anthropic([], stop_reason="max_tokens"),
            resposta_anthropic([{"id": 1, "traducao": "um"}]),
            resposta_anthropic([{"id": 1, "traducao": "dois"}]),
        ])
        saida = t.translate(BATCH_SEPARATOR.join(["one", "two"]), "pt", self.logs.append)
        self.assertEqual(saida, BATCH_SEPARATOR.join(["um", "dois"]))
        pedido = t._client.messages.chamadas[0]
        self.assertEqual(pedido["max_tokens"], 16000, "o mesmo max_tokens do piloto")
        self.assertEqual(len(t._client.messages.chamadas), 3)

    def test_an_authentication_error_is_fatal(self):
        import anthropic

        # A excecao real exige uma resposta HTTP de verdade; a classe basta
        # para o `except`, e o `status_code` e o unico campo que o codigo le.
        erro = anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)
        Exception.__init__(erro, "bad key")
        erro.status_code = 401
        t = self.tradutor([erro])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        self.assertIsNotNone(t.fatal_error)
        self.assertIsNone(t.translate("two", "pt", self.logs.append))
        self.assertEqual(len(t._client.messages.chamadas), 1)
        for linha in self.logs:
            self.assertNotIn(CHAVE, linha)


# ============================================================ conferencia


class CheckCredentialsTests(unittest.TestCase):
    """O botao "Testar chaves e modelos": uma requisicao gratuita que diz se a
    chave e o nome do modelo valem, ANTES de uma execucao descobrir."""

    def confere(self, respostas, provider="openai", modelo="gpt-5"):
        sessao = FakeSession(respostas)
        ok, texto = llm_providers.check_credentials(provider, modelo, api_key=CHAVE, session=sessao)
        return ok, texto, sessao

    def test_the_model_endpoint_answers_and_the_key_never_reaches_the_text(self):
        ok, texto, sessao = self.confere([FakeResponse(200, {"id": "gpt-5"})])
        self.assertTrue(ok)
        self.assertIn("modelo gpt-5 existe", texto)
        self.assertNotIn(CHAVE, texto)
        url, kwargs = sessao.chamadas[0]
        self.assertEqual(url, "https://api.openai.com/v1/models/gpt-5")
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {CHAVE}")

    def test_a_rejected_key_is_named(self):
        for status in (401, 403):
            with self.subTest(status=status):
                ok, texto, _s = self.confere([FakeResponse(status, {"error": "no"})])
                self.assertFalse(ok)
                self.assertIn(f"chave recusada ({status})", texto)

    def test_a_404_falls_back_to_the_list_where_deepseek_documents_only_the_list(self):
        lista = FakeResponse(200, {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]})
        ok, texto, sessao = self.confere(
            [FakeResponse(404, {"error": "no"}), lista], provider="deepseek", modelo="deepseek-flash"
        )
        self.assertTrue(ok, texto)
        self.assertEqual(sessao.chamadas[1][0], "https://api.deepseek.com/v1/models")
        ok, texto, _s = self.confere(
            [FakeResponse(404, {"error": "no"}), lista], provider="deepseek", modelo="deepseek-chat"
        )
        self.assertFalse(ok)
        self.assertIn("não está na lista do provedor (deepseek-flash, deepseek-v4-pro)", texto)

    def test_a_404_without_a_list_is_model_not_found(self):
        ok, texto, _s = self.confere([FakeResponse(404, {"error": "no"}), FakeResponse(500, text="x")])
        self.assertFalse(ok)
        self.assertIn("modelo 'gpt-5' não encontrado (404)", texto)

    def test_other_statuses_and_no_connection_are_reported(self):
        ok, texto, _s = self.confere([FakeResponse(503, text="down")])
        self.assertEqual((ok, texto), (False, "erro 503: down"))
        import requests

        ok, texto, _s = self.confere([requests.ConnectionError("dns")])
        self.assertFalse(ok)
        self.assertIn("sem conexão", texto)

    def test_without_a_key_nothing_is_asked(self):
        with mock.patch.object(llm_providers, "load_api_key", return_value=""):
            ok, texto = llm_providers.check_credentials("openai", "gpt-5", session=FakeSession([]))
        self.assertEqual((ok, texto), (False, "sem chave para testar"))
        self.assertEqual(llm_providers.check_credentials("nada", "x", api_key=CHAVE)[0], False)

    @unittest.skipUnless(llm_providers.anthropic_sdk_available(), "sem o SDK anthropic")
    def test_anthropic_uses_the_models_api_of_the_sdk(self):
        import anthropic

        class Models:
            def __init__(self, resultado):
                self.resultado = resultado
                self.pedidos = []

            def retrieve(self, modelo):
                self.pedidos.append(modelo)
                if isinstance(self.resultado, Exception):
                    raise self.resultado
                return self.resultado

        cliente = types.SimpleNamespace(models=Models(types.SimpleNamespace(display_name="Claude Opus 5")))
        ok, texto = llm_providers.check_credentials("anthropic", "claude-opus-5", api_key=CHAVE, client=cliente)
        self.assertEqual((ok, texto), (True, "chave aceita; modelo claude-opus-5 (Claude Opus 5) existe"))
        self.assertEqual(cliente.models.pedidos, ["claude-opus-5"])

        erro = anthropic.NotFoundError.__new__(anthropic.NotFoundError)
        Exception.__init__(erro, "no")
        erro.status_code = 404
        cliente = types.SimpleNamespace(models=Models(erro))
        ok, texto = llm_providers.check_credentials("anthropic", "claude-x", api_key=CHAVE, client=cliente)
        self.assertEqual((ok, texto), (False, "modelo 'claude-x' não existe"))

        erro = anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)
        Exception.__init__(erro, "bad")
        erro.status_code = 401
        ok, texto = llm_providers.check_credentials(
            "anthropic", "claude-opus-5", api_key=CHAVE, client=types.SimpleNamespace(models=Models(erro))
        )
        self.assertEqual((ok, texto), (False, "chave recusada (401)"))


# ================================================================= custo


class CostTests(unittest.TestCase):
    """A estimativa antes de iniciar e o "estimado -> real" do fim (28.7)."""

    def test_the_price_matches_the_exact_id_or_the_id_with_a_date(self):
        opus = llm_costs.PRICE_TABLE["claude-opus-5"]
        self.assertEqual(llm_costs.price_for("claude-opus-5"), opus)
        self.assertEqual(llm_costs.price_for(" Claude-Opus-5-20260401 "), opus)
        self.assertEqual(llm_costs.price_for("gpt-5-mini"), llm_costs.PRICE_TABLE["gpt-5-mini"])
        self.assertNotEqual(llm_costs.price_for("gpt-5-mini"), llm_costs.PRICE_TABLE["gpt-5"])
        for fora in ("gpt-5-turbo", "modelo-falso", "", None):
            with self.subTest(modelo=fora):
                self.assertIsNone(llm_costs.price_for(fora))

    def test_the_defaults_of_the_three_providers_have_a_price(self):
        """Um padrao sem preco mostraria "sem preco na tabela" na primeira
        execucao de todo mundo."""
        for modelo in settings.LLM_DEFAULTS.values():
            with self.subTest(modelo=modelo):
                self.assertIsNotNone(llm_costs.price_for(modelo))

    def test_the_estimate_reproduces_the_pilot(self):
        """200 comentarios de 202 caracteres: os tokens e os US$ 0,67 do
        piloto, menos o que o arredondamento leva."""
        estimativa = llm_costs.estimate_cost("claude-opus-5", ["x" * 202] * 200 + ["", None])
        self.assertEqual((estimativa.comments, estimativa.characters), (200, 40_400))
        self.assertAlmostEqual(estimativa.input_tokens, 36_844, delta=100)
        self.assertAlmostEqual(estimativa.output_tokens, 21_823, delta=100)
        self.assertAlmostEqual(estimativa.cost_usd, 0.67, places=2)

    def test_a_model_off_the_table_gets_tokens_and_no_dollars(self):
        estimativa = llm_costs.estimate_cost("modelo-falso", ["abc"])
        self.assertEqual((estimativa.comments, estimativa.input_tokens > 0), (1, True))
        self.assertIsNone(estimativa.cost_usd)
        texto = llm_costs.describe_estimate(estimativa, "Falso", "modelo-falso", 0)
        self.assertIn("sem preço na tabela para o modelo 'modelo-falso'", texto)
        self.assertNotIn("US$", texto)
        self.assertIn("sem preco na tabela", llm_costs.describe_estimate_line(estimativa, "modelo-falso", 0))

    def test_the_dialog_text_names_the_cache_and_the_date_of_the_table(self):
        estimativa = llm_costs.estimate_cost("claude-opus-5", ["x" * 202] * 200)
        texto = llm_costs.describe_estimate(estimativa, "Claude (Anthropic)", "claude-opus-5", 287)
        self.assertIn("Motor: Claude (Anthropic), modelo claude-opus-5.", texto)
        self.assertIn("200 (287 já estavam no banco e não serão enviados)", texto)
        self.assertIn("cerca de US$ 0,67", texto)
        self.assertIn(llm_costs.PRICES_DATED, texto)
        linha = llm_costs.describe_estimate_line(estimativa, "claude-opus-5", 287)
        self.assertEqual(linha.count(chr(10)), 0, "uma linha so, para o log")
        self.assertIn("200 comentarios para a API (287 no banco)", linha)

    def test_the_actual_cost_prices_the_cache_separately(self):
        uso = llm_providers.Usage(
            requests=10, input_tokens=23_654, cache_read_tokens=13_190,
            cache_write_tokens=0, output_tokens=21_823,
        )
        self.assertAlmostEqual(llm_costs.actual_cost("claude-opus-5", uso), 0.6704, places=3)
        uso.cache_write_tokens = 1_000_000
        self.assertAlmostEqual(llm_costs.actual_cost("claude-opus-5", uso), 0.6704 + 6.25, places=3)
        self.assertIsNone(llm_costs.actual_cost("modelo-falso", uso))
        self.assertIn("estimado ~US$ 0,50, real US$ 6,92", llm_costs.describe_outcome("claude-opus-5", 0.5, uso))
        self.assertIn("sem preco na tabela", llm_costs.describe_outcome("modelo-falso", 0.5, uso))
        self.assertIn("sem preco na tabela", llm_costs.describe_outcome("claude-opus-5", None, uso))

    def test_dollars_are_written_the_brazilian_way(self):
        self.assertEqual(llm_costs.format_usd(1234.5), "US$ 1.234,50")
        self.assertEqual(llm_costs.format_usd(0.6704), "US$ 0,67")
        self.assertEqual(llm_costs.format_usd(0), "US$ 0,00")


# ============================================================ build/config


class BuildTranslatorTests(unittest.TestCase):
    def test_unknown_provider_missing_key_and_missing_sdk_are_named(self):
        with self.assertRaises(ValueError):
            build_translator("inventado", "", "en", "pt")
        with mock.patch.object(llm_providers, "load_api_key", return_value=None):
            with self.assertRaises(LookupError):
                build_translator("openai", "", "en", "pt")
        with mock.patch.object(llm_providers, "anthropic_sdk_available", return_value=False):
            with self.assertRaises(ImportError):
                build_translator("anthropic", "", "en", "pt", api_key=CHAVE)

    def test_the_run_label_and_the_default_model(self):
        t = build_translator("deepseek", "", "en", "pt", api_key=CHAVE)
        self.assertEqual(t.model, PROVIDERS["deepseek"].default_model)
        self.assertEqual(t.run_label, f"deepseek:{PROVIDERS['deepseek'].default_model}")
        t = build_translator("deepseek", "deepseek-reasoner", "en", "pt", api_key=CHAVE)
        self.assertEqual(t.run_label, "deepseek:deepseek-reasoner")

    def test_the_settings_know_the_same_providers(self):
        self.assertEqual(
            settings.TRANSLATION_PROVIDER_IDS, (GOOGLE_PROVIDER, *llm_providers.PROVIDER_ORDER)
        )
        for pid in PROVIDERS:
            self.assertIn(llm_providers.model_setting_key(pid), settings.LLM_DEFAULTS)

    def test_llm_settings_fall_back_to_the_defaults(self):
        lidas = settings.read_llm_settings({"llm": {"openai_model": "  gpt-x ", "deepseek_model": 3}})
        self.assertEqual(lidas["openai_model"], "gpt-x")
        self.assertEqual(lidas["deepseek_model"], settings.LLM_DEFAULTS["deepseek_model"])
        self.assertEqual(settings.read_llm_settings({}), settings.LLM_DEFAULTS)

    def test_the_remembered_provider_is_validated(self):
        lidas = settings.read_main_window_settings({"main_window": {"translation_provider": "openai"}}, {"pt"})
        self.assertEqual(lidas["translation_provider"], "openai")
        lidas = settings.read_main_window_settings({"main_window": {"translation_provider": "bing"}}, {"pt"})
        self.assertEqual(lidas["translation_provider"], GOOGLE_PROVIDER)


if __name__ == "__main__":
    sys.exit(unittest.main())
