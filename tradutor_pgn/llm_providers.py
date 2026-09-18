"""Os provedores de modelo de linguagem (ROADMAP 28.7): Claude, ChatGPT e DeepSeek.

Tres nomes, dois protocolos: o Claude fala pela API da Anthropic (SDK
`anthropic`, com `output_config` para a resposta vir no esquema do lote e
`cache_control` no bloco de sistema); ChatGPT e DeepSeek falam pelo MESMO
protocolo de `chat/completions` (a DeepSeek o adotou de proposito), por
`requests` — sem SDK de terceiro no `.exe`.

**A costura com o worker e a mesma do Google.** O worker monta o lote como
texto com ` ||| ` entre os comentarios, chama UMA funcao e divide a resposta
pelo mesmo separador (B1/B2). O provedor de modelo recebe esse texto, separa
os comentarios, manda um JSON numerado (`llm_prompt`), confere cada id
exatamente uma vez (B5) e devolve os pedacos juntados de novo pelo separador.
O que faltou no JSON volta como pedaco VAZIO — e o `misaligned_batch_part`
do worker acusa o vazio como desalinhamento e reenvia aquele comentario
sozinho, como ja faz com o Google. Nada do pipeline muda de lugar: mascara
X1 antes, regras automaticas, correcao de lances e prosa depois, disjuntor,
cancelamento — e os 70 pontos dos testes que substituem
`translation_worker.translate_text` continuam valendo, porque o worker
resolve o nome na chamada.

**Chave e custo, o que o log ve**: a chave so aparece como `****wxyz` (K1);
no fim da execucao o worker escreve quantas requisicoes e tokens o modelo
gastou. Um erro de autenticacao (401) e FATAL para a execucao: o provedor
para de chamar a API na hora e devolve `None` a cada lote, e o disjuntor do
worker (B3) encerra a execucao com o motivo no log — insistir seria pagar
por 40 requisicoes que ninguem vai atender.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Protocol

import requests

from .api_keys import load_api_key, mask_api_key
from .llm_prompt import (
    ESQUEMA_DO_LOTE,
    mensagem_do_lote,
    prompt_de_sistema,
    regras_automaticas_em_texto,
    sugestoes_para_o_lote,
    validar_lote,
)
from .pgn_utils import BATCH_SEPARATOR
from .settings import LLM_DEFAULTS, TRANSLATION_PROVIDER_GOOGLE, TRANSLATION_PROVIDER_IDS
from .translation_api import RETRYABLE_STATUS, CancelFlag, LogMessage, retry_delay_seconds

GOOGLE_PROVIDER = TRANSLATION_PROVIDER_GOOGLE

# Comprimento maximo da resposta — o MESMO do piloto (`MAX_TOKENS = 16000`),
# que e o numero em que os zero lotes cortados foram medidos. Um lote do
# worker tem ate ~4.800 caracteres de entrada (BATCH_MAX_CHARS) e a traducao
# raramente passa do dobro, mas o limite conta tambem o pensamento do modelo
# (adaptativo por padrao no Opus 5; os `reasoning tokens` da OpenAI entram em
# `max_completion_tokens`), e 8 mil era metade do que o piloto deu.
MAX_OUTPUT_TOKENS = 16000

# Os motivos de uma chamada sem texto. `cut` e `refusal` sao do CONTEUDO — o
# lote e dividido ao meio e tentado de novo (B1); os outros sao do transporte
# ou da conta, e voltam `None` ao worker, que os trata como a rede caida.
REASON_OK = "ok"
REASON_CUT = "cut"
REASON_REFUSAL = "refusal"
REASON_ERROR = "error"
REQUEST_TIMEOUT = 120
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ProviderSpec:
    """O que a tela, o dialogo e o worker sabem de cada provedor."""

    id: str
    label: str
    env_var: str
    default_model: str
    kind: str  # "anthropic" | "openai"
    base_url: str = ""
    # O nome do campo de limite de saida no `chat/completions`: a OpenAI
    # aposentou `max_tokens` nos modelos novos; a DeepSeek ainda o usa.
    max_tokens_field: str = "max_tokens"
    console_url: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        id="anthropic",
        label="Claude (Anthropic)",
        env_var="ANTHROPIC_API_KEY",
        default_model=LLM_DEFAULTS["anthropic_model"],
        kind="anthropic",
        console_url="https://console.anthropic.com/",
    ),
    "openai": ProviderSpec(
        id="openai",
        label="ChatGPT (OpenAI)",
        env_var="OPENAI_API_KEY",
        default_model=LLM_DEFAULTS["openai_model"],
        kind="openai",
        base_url="https://api.openai.com/v1",
        max_tokens_field="max_completion_tokens",
        console_url="https://platform.openai.com/",
    ),
    "deepseek": ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        default_model=LLM_DEFAULTS["deepseek_model"],
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        console_url="https://platform.deepseek.com/",
    ),
}
PROVIDER_ORDER = tuple(PROVIDERS)
# O arquivo de configuracoes valida o motor gravado sem importar este modulo;
# as duas listas tem de dizer o mesmo.
assert (GOOGLE_PROVIDER, *PROVIDER_ORDER) == TRANSLATION_PROVIDER_IDS


def model_setting_key(provider_id: str) -> str:
    """A chave de `settings.LLM_DEFAULTS` com o modelo deste provedor."""
    return f"{provider_id}_model"


def provider_label(provider_id: str) -> str:
    """O nome de exibicao; "Google" para o motor de sempre."""
    if provider_id in PROVIDERS:
        return PROVIDERS[provider_id].label
    return "Google (gratuito)"


def configured_providers() -> list[str]:
    """Os provedores com chave em uso (ambiente ou arquivo), na ordem da tela."""
    return [
        spec.id
        for spec in PROVIDERS.values()
        if load_api_key(spec.id, spec.env_var)
    ]


def anthropic_sdk_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


class ChatClient(Protocol):
    """O que um cliente de `chat/completions` precisa ter: so o `post`."""

    def post(self, url: str, **kwargs: Any) -> requests.Response: ...


@dataclass
class Usage:
    """Contagem do que a execucao gastou, para o resumo e o custo do log.

    `input_tokens` e a entrada que o provedor cobrou INTEIRA — fora do cache
    — nos dois protocolos: a Anthropic ja separa leitura e escrita do cache na
    resposta, e do `prompt_tokens` da OpenAI/DeepSeek (que inclui o cache) o
    provedor desconta os `cached_tokens`. E o que deixa `llm_costs.actual_cost`
    fazer uma conta so para os tres.
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    failures: int = 0
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        cache = f", {self.cache_read_tokens} lidos do cache" if self.cache_read_tokens else ""
        if self.cache_write_tokens:
            cache += f", {self.cache_write_tokens} escritos no cache"
        return (
            f"{self.requests} requisicao(oes), {self.input_tokens} tokens de entrada"
            f"{cache}, {self.output_tokens} de saida, {self.failures} falha(s)"
        )


class LLMTranslator:
    """Um provedor pronto para traduzir: modelo, chave, prompt e contadores.

    `translate(text, ...)` tem a forma de `translation_api.translate_text` do
    ponto de vista do worker: texto (um comentario, ou varios com ` ||| `),
    log e flag de cancelamento; devolve o texto traduzido ou `None`.
    """

    def __init__(
        self,
        spec: ProviderSpec,
        model: str,
        api_key: str,
        source_language: str,
        target_language: str,
        automatic_rules: list[Any] | None = None,
        suggestion_rules: list[Any] | None = None,
    ) -> None:
        self.spec = spec
        self.model = model or spec.default_model
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.suggestion_rules = list(suggestion_rules or [])
        self.system_blocks = [prompt_de_sistema(source_language, target_language)]
        regras = regras_automaticas_em_texto(automatic_rules or [])
        if regras:
            self.system_blocks.append(regras)
        self.usage = Usage()
        # Depois de um 401 ninguem mais e chamado (ver o docstring do modulo).
        self.fatal_error: str | None = None
        self._client: Any = None
        # O que o ultimo lote dividido traduziu, por texto enviado: quando o
        # worker reenvia sozinho um item que ja saiu certo de uma das metades,
        # a resposta vem daqui, sem requisicao (ver `_translate_parts`).
        self._divided: dict[str, str] = {}

    # ------------------------------------------------------------ identidade

    @property
    def run_label(self) -> str:
        """O nome gravado na execucao (Z5): `anthropic:claude-opus-5`."""
        return f"{self.spec.id}:{self.model}"

    def describe(self) -> str:
        """A linha do log ao iniciar — com a chave mascarada (K1)."""
        return (
            f"Motor: {self.spec.label}, modelo {self.model}, "
            f"chave {mask_api_key(self.api_key)}."
        )

    # -------------------------------------------------------------- traducao

    def translate(
        self,
        text: str,
        target_language: str,
        log_message: LogMessage | None = None,
        cancel_flag: CancelFlag | None = None,
        contexts: Sequence[tuple[str, str]] | None = None,
        **_ignored: Any,
    ) -> str | None:
        """O texto traduzido (com ` ||| ` entre as partes, como veio) ou `None`.

        `contexts` e o lance anterior e o seguinte de cada parte, na ordem
        delas (ROADMAP 28.7): e o contexto que o piloto tinha e que o worker
        agora manda; sem ele os campos vao vazios, como o prompt admite.
        """
        if self.fatal_error is not None:
            return None
        if cancel_flag is not None and cancel_flag.is_set():
            return None
        partes = text.split(BATCH_SEPARATOR) if BATCH_SEPARATOR in text else [text]
        contextos = list(contexts or [])
        if len(contextos) != len(partes):
            contextos = [("", "")] * len(partes)
        if len(partes) == 1 and partes[0] in self._divided:
            # Ja saiu certo de uma das metades do ultimo lote dividido.
            return self._divided[partes[0]]
        if len(partes) > 1:
            self._divided = {}
        traduzidas = self._translate_parts(partes, contextos, log_message, cancel_flag)
        if traduzidas is None or not any(traduzidas):
            return None
        # O que faltou volta vazio: o worker ve o vazio como parte deslocada e
        # reenvia o comentario sozinho — o mesmo caminho do lote desalinhado.
        return BATCH_SEPARATOR.join(t or "" for t in traduzidas)

    def _translate_parts(
        self,
        partes: list[str],
        contextos: list[tuple[str, str]],
        log_message: LogMessage | None,
        cancel_flag: CancelFlag | None,
    ) -> list[str | None] | None:
        """Uma requisicao para `partes`; cortada ou recusada, duas metades.

        Devolve a traducao de cada parte (`None` na que falhou sozinha), ou
        `None` quando o transporte falhou — ai o worker faz o que faz com a
        rede caida (B3). A resposta cortada por `max_tokens` e a recusa sao
        problemas do CONTEUDO do lote, nao da conexao: o lote e dividido ao
        meio e cada metade tentada de novo, ate o item sozinho (a regra B1,
        pela API que a exige). Isola o item que o modelo recusa sem perder os
        outros, e um lote longo demais custa duas requisicoes em vez de uma
        por item. As metades que deram certo ficam em `_divided`: quando o
        worker reenviar sozinho os itens do lote (a parte vazia e
        desalinhamento para ele), os que ja tem traducao nao pagam de novo.
        """
        if cancel_flag is not None and cancel_flag.is_set():
            return None
        itens = [
            {"id": n, "texto": parte, "antes": antes, "depois": depois}
            for n, (parte, (antes, depois)) in enumerate(zip(partes, contextos), start=1)
        ]
        sugestoes = sugestoes_para_o_lote(partes, self.suggestion_rules)
        resposta, motivo = self._call(mensagem_do_lote(itens, sugestoes), log_message, cancel_flag)
        if resposta is None:
            if motivo not in (REASON_CUT, REASON_REFUSAL):
                return None
            if len(partes) == 1:
                return [None]
            meio = len(partes) // 2
            if log_message:
                log_message(
                    f"  - {self.spec.label}: lote de {len(partes)} itens dividido em "
                    f"{meio} + {len(partes) - meio}"
                )
            esquerda = self._translate_parts(partes[:meio], contextos[:meio], log_message, cancel_flag)
            if esquerda is None:
                return None
            direita = self._translate_parts(partes[meio:], contextos[meio:], log_message, cancel_flag)
            if direita is None:
                return None
            traduzidas = esquerda + direita
        else:
            por_id, problemas = validar_lote(resposta, range(1, len(partes) + 1))
            if problemas and log_message:
                log_message(f"  - {self.spec.label}: {'; '.join(problemas[:3])}")
                self.usage.problems.extend(problemas)
            if not por_id:
                return None
            traduzidas = [por_id.get(n) for n in range(1, len(partes) + 1)]
        for parte, traducao in zip(partes, traduzidas):
            if traducao:
                self._divided[parte] = traducao
        return traduzidas

    def _call(
        self, mensagem: str, log_message: LogMessage | None, cancel_flag: CancelFlag | None
    ) -> tuple[str | None, str]:
        """`(texto, motivo)`: o texto da resposta e `REASON_OK`, ou `None` e por que."""
        if self.spec.kind == "anthropic":
            return self._call_anthropic(mensagem, log_message)
        return self._call_chat_completions(mensagem, log_message, cancel_flag)

    # ------------------------------------------------------------- anthropic

    def _anthropic_client(self) -> Any:
        if self._client is None:
            import anthropic

            # O SDK ja tenta de novo 429 e 5xx (duas vezes, com espera crescente).
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=REQUEST_TIMEOUT)
        return self._client

    def _call_anthropic(
        self, mensagem: str, log_message: LogMessage | None
    ) -> tuple[str | None, str]:
        import anthropic

        sistema = [
            {"type": "text", "text": bloco, "cache_control": {"type": "ephemeral"}}
            for bloco in self.system_blocks
        ]
        self.usage.requests += 1
        try:
            resposta = self._anthropic_client().messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=sistema,
                messages=[{"role": "user", "content": mensagem}],
                output_config={"format": {"type": "json_schema", "schema": ESQUEMA_DO_LOTE}},
            )
        except anthropic.AuthenticationError as exc:
            self._fatal(f"chave recusada pela Anthropic ({exc.status_code})", log_message)
            return None, REASON_ERROR
        except anthropic.PermissionDeniedError as exc:
            self._fatal(f"chave sem permissao na Anthropic ({exc.status_code})", log_message)
            return None, REASON_ERROR
        except anthropic.NotFoundError:
            self._fatal(f"modelo '{self.model}' nao existe na Anthropic", log_message)
            return None, REASON_ERROR
        except anthropic.RateLimitError:
            self._failure("limite de requisicoes da Anthropic (429) esgotou as tentativas", log_message)
            return None, REASON_ERROR
        except anthropic.APIStatusError as exc:
            self._failure(f"erro {exc.status_code} da Anthropic: {exc.message}", log_message)
            return None, REASON_ERROR
        except anthropic.APIConnectionError as exc:
            self._failure(f"sem conexao com a Anthropic: {exc}", log_message)
            return None, REASON_ERROR
        uso = getattr(resposta, "usage", None)
        if uso is not None:
            self.usage.input_tokens += getattr(uso, "input_tokens", 0) or 0
            self.usage.output_tokens += getattr(uso, "output_tokens", 0) or 0
            self.usage.cache_read_tokens += getattr(uso, "cache_read_input_tokens", 0) or 0
            self.usage.cache_write_tokens += getattr(uso, "cache_creation_input_tokens", 0) or 0
        if getattr(resposta, "stop_reason", None) == "refusal":
            self._failure("a Anthropic recusou o lote (refusal)", log_message)
            return None, REASON_REFUSAL
        if getattr(resposta, "stop_reason", None) == "max_tokens":
            self._failure("resposta cortada por max_tokens", log_message)
            return None, REASON_CUT
        for bloco in getattr(resposta, "content", []) or []:
            if getattr(bloco, "type", None) == "text":
                return str(bloco.text), REASON_OK
        self._failure("resposta sem texto", log_message)
        return None, REASON_ERROR

    # ------------------------------------------------------ chat/completions

    def _http(self) -> ChatClient:
        if self._client is None:
            self._client = requests.Session()
        return self._client

    def _call_chat_completions(
        self, mensagem: str, log_message: LogMessage | None, cancel_flag: CancelFlag | None
    ) -> tuple[str | None, str]:
        corpo: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "\n\n".join(self.system_blocks)},
                {"role": "user", "content": mensagem},
            ],
            "response_format": {"type": "json_object"},
            self.spec.max_tokens_field: MAX_OUTPUT_TOKENS,
        }
        cabecalhos = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.spec.base_url}/chat/completions"
        for tentativa in range(1, MAX_ATTEMPTS + 1):
            if cancel_flag is not None and cancel_flag.is_set():
                return None, REASON_ERROR
            self.usage.requests += 1
            try:
                resposta = self._http().post(
                    url, json=corpo, headers=cabecalhos, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                if tentativa < MAX_ATTEMPTS:
                    time.sleep(retry_delay_seconds(tentativa))
                    continue
                self._failure(f"sem conexao com {self.spec.label}: {exc}", log_message)
                return None, REASON_ERROR
            status = resposta.status_code
            if status in (401, 403):
                self._fatal(f"chave recusada por {self.spec.label} ({status})", log_message)
                return None, REASON_ERROR
            if status == 404:
                self._fatal(f"modelo '{self.model}' nao existe em {self.spec.label}", log_message)
                return None, REASON_ERROR
            if status in RETRYABLE_STATUS and tentativa < MAX_ATTEMPTS:
                time.sleep(retry_delay_seconds(tentativa, status))
                continue
            if status != 200:
                self._failure(
                    f"erro {status} de {self.spec.label}: {resposta.text[:200]}", log_message
                )
                return None, REASON_ERROR
            return self._parse_chat_completion(resposta, log_message)
        return None, REASON_ERROR

    def _parse_chat_completion(
        self, resposta: requests.Response, log_message: LogMessage | None
    ) -> tuple[str | None, str]:
        try:
            dados = resposta.json()
        except ValueError:
            self._failure(f"resposta de {self.spec.label} nao e JSON", log_message)
            return None, REASON_ERROR
        uso = dados.get("usage") or {}
        detalhes = uso.get("prompt_tokens_details") or {}
        em_cache = int(detalhes.get("cached_tokens") or uso.get("prompt_cache_hit_tokens") or 0)
        # `prompt_tokens` INCLUI o que veio do cache; `Usage.input_tokens` e
        # so o que foi cobrado inteiro (ver o docstring de `Usage`).
        self.usage.input_tokens += max(0, int(uso.get("prompt_tokens") or 0) - em_cache)
        self.usage.cache_read_tokens += em_cache
        self.usage.output_tokens += int(uso.get("completion_tokens") or 0)
        try:
            escolha = dados["choices"][0]
            mensagem = escolha["message"]
            conteudo = mensagem["content"]
        except (KeyError, IndexError, TypeError):
            self._failure(f"resposta de {self.spec.label} sem 'choices'", log_message)
            return None, REASON_ERROR
        if escolha.get("finish_reason") == "length":
            self._failure("resposta cortada pelo limite de saida", log_message)
            return None, REASON_CUT
        if isinstance(mensagem, dict) and mensagem.get("refusal"):
            self._failure(f"{self.spec.label} recusou o lote (refusal)", log_message)
            return None, REASON_REFUSAL
        if not isinstance(conteudo, str):
            conteudo = json.dumps(conteudo)
        return conteudo, REASON_OK

    # ---------------------------------------------------------------- erros

    def _failure(self, motivo: str, log_message: LogMessage | None) -> None:
        self.usage.failures += 1
        if log_message:
            log_message(f"  - Falha na API: {motivo}")

    def _fatal(self, motivo: str, log_message: LogMessage | None) -> None:
        self.usage.failures += 1
        self.fatal_error = motivo
        if log_message:
            log_message(f"[ERRO] {motivo}. Nenhuma outra requisicao sera feita nesta execucao.")


def build_translator(
    provider_id: str,
    model: str,
    source_language: str,
    target_language: str,
    automatic_rules: list[Any] | None = None,
    suggestion_rules: list[Any] | None = None,
    api_key: str | None = None,
) -> LLMTranslator:
    """O provedor pronto, ou `ValueError`/`LookupError` dizendo o que falta.

    `api_key` explicita e para os testes; sem ela, a chave vem do ambiente
    ou do arquivo (`api_keys`).
    """
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise ValueError(f"provedor desconhecido: {provider_id!r}")
    chave = api_key or load_api_key(spec.id, spec.env_var)
    if not chave:
        raise LookupError(f"sem chave de API para {spec.label}")
    if spec.kind == "anthropic" and not anthropic_sdk_available():
        raise ImportError("o pacote 'anthropic' nao esta instalado (uv sync --extra llm)")
    return LLMTranslator(
        spec, model, chave, source_language, target_language, automatic_rules, suggestion_rules
    )
