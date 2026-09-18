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

# Comprimento maximo da resposta. Um lote do worker tem ate ~4.800 caracteres
# de entrada (BATCH_MAX_CHARS); a traducao raramente passa do dobro, e 8 mil
# tokens dao folga de sobra sem deixar um modelo tagarela correr solto.
MAX_OUTPUT_TOKENS = 8000
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
    """Contagem do que a execucao gastou, para o resumo do log."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    failures: int = 0
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        cache = f", {self.cache_read_tokens} lidos do cache" if self.cache_read_tokens else ""
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
        **_ignored: Any,
    ) -> str | None:
        if self.fatal_error is not None:
            return None
        if cancel_flag is not None and cancel_flag.is_set():
            return None
        partes = text.split(BATCH_SEPARATOR) if BATCH_SEPARATOR in text else [text]
        itens = [{"id": n, "texto": parte} for n, parte in enumerate(partes, start=1)]
        sugestoes = sugestoes_para_o_lote(partes, self.suggestion_rules)
        mensagem = mensagem_do_lote(itens, sugestoes)
        resposta = self._call(mensagem, log_message, cancel_flag)
        if resposta is None:
            return None
        por_id, problemas = validar_lote(resposta, range(1, len(partes) + 1))
        if problemas and log_message:
            log_message(f"  - {self.spec.label}: {'; '.join(problemas[:3])}")
            self.usage.problems.extend(problemas)
        if not por_id:
            return None
        # O que faltou volta vazio: o worker ve o vazio como parte deslocada e
        # reenvia o comentario sozinho — o mesmo caminho do lote desalinhado.
        return BATCH_SEPARATOR.join(por_id.get(n, "") for n in range(1, len(partes) + 1))

    def _call(
        self, mensagem: str, log_message: LogMessage | None, cancel_flag: CancelFlag | None
    ) -> str | None:
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

    def _call_anthropic(self, mensagem: str, log_message: LogMessage | None) -> str | None:
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
            return None
        except anthropic.PermissionDeniedError as exc:
            self._fatal(f"chave sem permissao na Anthropic ({exc.status_code})", log_message)
            return None
        except anthropic.NotFoundError:
            self._fatal(f"modelo '{self.model}' nao existe na Anthropic", log_message)
            return None
        except anthropic.RateLimitError:
            self._failure("limite de requisicoes da Anthropic (429) esgotou as tentativas", log_message)
            return None
        except anthropic.APIStatusError as exc:
            self._failure(f"erro {exc.status_code} da Anthropic: {exc.message}", log_message)
            return None
        except anthropic.APIConnectionError as exc:
            self._failure(f"sem conexao com a Anthropic: {exc}", log_message)
            return None
        uso = getattr(resposta, "usage", None)
        if uso is not None:
            self.usage.input_tokens += getattr(uso, "input_tokens", 0) or 0
            self.usage.output_tokens += getattr(uso, "output_tokens", 0) or 0
            self.usage.cache_read_tokens += getattr(uso, "cache_read_input_tokens", 0) or 0
        if getattr(resposta, "stop_reason", None) == "refusal":
            self._failure("a Anthropic recusou o lote (refusal)", log_message)
            return None
        if getattr(resposta, "stop_reason", None) == "max_tokens":
            self._failure("resposta cortada por max_tokens; o lote sera dividido", log_message)
            return None
        for bloco in getattr(resposta, "content", []) or []:
            if getattr(bloco, "type", None) == "text":
                return str(bloco.text)
        self._failure("resposta sem texto", log_message)
        return None

    # ------------------------------------------------------ chat/completions

    def _http(self) -> ChatClient:
        if self._client is None:
            self._client = requests.Session()
        return self._client

    def _call_chat_completions(
        self, mensagem: str, log_message: LogMessage | None, cancel_flag: CancelFlag | None
    ) -> str | None:
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
                return None
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
                return None
            status = resposta.status_code
            if status in (401, 403):
                self._fatal(f"chave recusada por {self.spec.label} ({status})", log_message)
                return None
            if status == 404:
                self._fatal(f"modelo '{self.model}' nao existe em {self.spec.label}", log_message)
                return None
            if status in RETRYABLE_STATUS and tentativa < MAX_ATTEMPTS:
                time.sleep(retry_delay_seconds(tentativa, status))
                continue
            if status != 200:
                self._failure(
                    f"erro {status} de {self.spec.label}: {resposta.text[:200]}", log_message
                )
                return None
            return self._parse_chat_completion(resposta, log_message)
        return None

    def _parse_chat_completion(
        self, resposta: requests.Response, log_message: LogMessage | None
    ) -> str | None:
        try:
            dados = resposta.json()
        except ValueError:
            self._failure(f"resposta de {self.spec.label} nao e JSON", log_message)
            return None
        uso = dados.get("usage") or {}
        self.usage.input_tokens += int(uso.get("prompt_tokens") or 0)
        self.usage.output_tokens += int(uso.get("completion_tokens") or 0)
        detalhes = uso.get("prompt_tokens_details") or {}
        self.usage.cache_read_tokens += int(
            detalhes.get("cached_tokens") or uso.get("prompt_cache_hit_tokens") or 0
        )
        try:
            escolha = dados["choices"][0]
            conteudo = escolha["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self._failure(f"resposta de {self.spec.label} sem 'choices'", log_message)
            return None
        if escolha.get("finish_reason") == "length":
            self._failure("resposta cortada pelo limite de saida; o lote sera dividido", log_message)
            return None
        if not isinstance(conteudo, str):
            conteudo = json.dumps(conteudo)
        return conteudo

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
