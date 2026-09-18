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

from tradutor_pgn import api_keys, llm_prompt, llm_providers, settings
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
    """Grava cada `post` e devolve as respostas na ordem combinada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def post(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        return self.respostas.pop(0)


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

    def test_openai_uses_the_new_output_limit_field(self):
        t = self.tradutor([resposta_ok([{"id": 1, "traducao": "um"}])], provider="openai")
        t.translate("one", "pt")
        corpo = t._client.chamadas[0][1]["json"]
        self.assertIn("max_completion_tokens", corpo)
        self.assertNotIn("max_tokens", corpo)
        self.assertEqual(t._client.chamadas[0][0], "https://api.openai.com/v1/chat/completions")

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
        usage=types.SimpleNamespace(input_tokens=200, output_tokens=50, cache_read_input_tokens=150),
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

    def test_refusal_and_max_tokens_are_failures(self):
        t = self.tradutor([resposta_anthropic([], stop_reason="refusal")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        t = self.tradutor([resposta_anthropic([], stop_reason="max_tokens")])
        self.assertIsNone(t.translate("one", "pt", self.logs.append))
        self.assertIsNone(t.fatal_error)

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
