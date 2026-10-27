"""O que uma execucao com modelo de linguagem vai custar, e o que custou (ROADMAP 28.7).

Puro: sem rede, sem Tk, sem banco. Duas contas e uma tabela.

**A estimativa e uma regra de tres calibrada no piloto** (2026-09-15, 200
comentarios, 40.426 caracteres de original, `claude-opus-5`): 36.844 tokens de
entrada — o bloco de sistema, os itens em JSON e as sugestoes do glossario,
13.190 deles lidos do cache — e 21.823 de saida. Por caractere de original,
0,91 de entrada e 0,54 de saida, e 36 % da entrada vindo do cache. E a mesma
conta para os tres provedores, embora cada um conte tokens do seu jeito: e uma
estimativa, o dialogo diz `~`, e a fatura do provedor e o que vale. O que ela
NAO inclui de proposito e o que ja esta no banco: o worker so a faz depois da
carga do cache, sobre os comentarios que vao mesmo para a API.

**A tabela de precos tem data.** Os provedores mudam preco e nome de modelo
mais depressa do que o programa lanca versao; um modelo fora da tabela recebe
os tokens e nenhum dolar — nunca um numero inventado. O casamento e pelo id
exato ou pelo id seguido de uma data (`claude-opus-5-20260401` e o
`claude-opus-5`); `gpt-5-mini` NAO e `gpt-5`, e por isso tem linha propria.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Referencia: as paginas de precos dos tres provedores em 2026-09-18, em US$
# por milhao de tokens. `cache_read` e o que a leitura do cache de prompt
# custa; `cache_write` so existe na Anthropic (1,25x a entrada). A DeepSeek
# cobra a metade fora do horario de pico — a tabela traz o pico, que e o
# teto — e, desde 2026-09-14, atende `deepseek-v4-pro` e os nomes antigos do
# V4-Flash pelo V4.1-Flash, ao preco dele.
PRICES_DATED = "2026-09"


@dataclass(frozen=True)
class Price:
    """US$ por milhao de tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float = 0.0


PRICE_TABLE: dict[str, Price] = {
    # Anthropic
    "claude-opus-5": Price(5.0, 25.0, 0.5, 6.25),
    "claude-opus-4-8": Price(5.0, 25.0, 0.5, 6.25),
    "claude-opus-4-7": Price(5.0, 25.0, 0.5, 6.25),
    "claude-opus-4-6": Price(5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-5": Price(2.0, 10.0, 0.2, 2.5),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.3, 3.75),
    "claude-haiku-4-5": Price(1.0, 5.0, 0.1, 1.25),
    "claude-fable-5-1": Price(10.0, 50.0, 0.25, 12.5),
    "claude-fable-5": Price(10.0, 50.0, 1.0, 12.5),
    # OpenAI (entrada em cache a 10 %; o gpt-4.1 a 25 %)
    "gpt-5.6-sol": Price(4.0, 20.0, 0.4),
    "gpt-5.6-terra": Price(2.0, 12.0, 0.2),
    "gpt-5.6-luna": Price(0.2, 1.2, 0.02),
    "gpt-5.5": Price(5.0, 30.0, 0.5),
    "gpt-5.4": Price(2.5, 15.0, 0.25),
    "gpt-5.4-mini": Price(0.75, 4.5, 0.075),
    "gpt-5.4-nano": Price(0.2, 1.25, 0.02),
    "gpt-5.2": Price(1.75, 14.0, 0.175),
    "gpt-5.1": Price(1.25, 10.0, 0.125),
    "gpt-5": Price(1.25, 10.0, 0.125),
    "gpt-5-mini": Price(0.25, 2.0, 0.025),
    "gpt-5-nano": Price(0.05, 0.4, 0.005),
    "gpt-4.1": Price(2.0, 8.0, 0.5),
    # DeepSeek (V4.1-Flash, pico)
    "deepseek-flash": Price(0.3, 1.2, 0.006),
    "deepseek-v4-pro": Price(0.3, 1.2, 0.006),
    "deepseek-v4-flash": Price(0.3, 1.2, 0.006),
}

# A calibracao do piloto (ver o docstring do modulo).
INPUT_TOKENS_PER_CHAR = 36_844 / 40_426
OUTPUT_TOKENS_PER_CHAR = 21_823 / 40_426
CACHED_INPUT_SHARE = 13_190 / 36_844


def price_for(model: str) -> Price | None:
    """A linha da tabela para `model`: o id exato, ou o id seguido de uma data."""
    nome = (model or "").strip().lower()
    if nome in PRICE_TABLE:
        return PRICE_TABLE[nome]
    for candidato in sorted(PRICE_TABLE, key=len, reverse=True):
        sufixo = nome[len(candidato) :]
        if nome.startswith(candidato) and sufixo.startswith("-") and sufixo[1:].isdigit():
            return PRICE_TABLE[candidato]
    return None


@dataclass(frozen=True)
class CostEstimate:
    """O que o dialogo mostra antes de iniciar."""

    comments: int
    characters: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


def estimate_cost(model: str, texts: Iterable[str]) -> CostEstimate:
    """A estimativa para os `texts` que vao mesmo para a API (fora do cache)."""
    quantos = 0
    caracteres = 0
    for texto in texts:
        if texto:
            quantos += 1
            caracteres += len(texto)
    entrada = int(round(caracteres * INPUT_TOKENS_PER_CHAR))
    saida = int(round(caracteres * OUTPUT_TOKENS_PER_CHAR))
    preco = price_for(model)
    custo = None
    if preco is not None:
        do_cache = int(round(entrada * CACHED_INPUT_SHARE))
        custo = (
            (entrada - do_cache) * preco.input
            + do_cache * preco.cache_read
            + saida * preco.output
        ) / 1_000_000
    return CostEstimate(quantos, caracteres, entrada, saida, custo)


def actual_cost(model: str, usage: Any) -> float | None:
    """O custo do que `usage` (um `llm_providers.Usage`) contou, ou `None`.

    `input_tokens` e a entrada NAO cacheada, nos dois protocolos — o provedor
    ja descontou o cache do `prompt_tokens` da OpenAI/DeepSeek, e a Anthropic
    os separa na origem.
    """
    preco = price_for(model)
    if preco is None:
        return None
    return (
        getattr(usage, "input_tokens", 0) * preco.input
        + getattr(usage, "cache_read_tokens", 0) * preco.cache_read
        + getattr(usage, "cache_write_tokens", 0) * preco.cache_write
        + getattr(usage, "output_tokens", 0) * preco.output
    ) / 1_000_000


def format_usd(value: float) -> str:
    """`US$ 27,30`, `US$ 0,67`: virgula decimal, ponto de milhar."""
    inteiro, centavos = divmod(int(round(value * 100)), 100)
    return f"US$ {inteiro:,}".replace(",", ".") + f",{centavos:02d}"


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def describe_estimate(
    estimate: CostEstimate, provider_label: str, model: str, cached: int
) -> str:
    """O texto do dialogo "Custo estimado" (e a linha do log)."""
    de_cache = (
        f" ({format_int(cached)} já estavam no banco e não serão enviados)" if cached else ""
    )
    if estimate.cost_usd is None:
        custo = (
            f"Custo: sem preço na tabela para o modelo '{model}' — a fatura do "
            f"provedor é o que vale."
        )
    else:
        custo = (
            f"Custo estimado: cerca de {format_usd(estimate.cost_usd)} (tabela de "
            f"preços de {PRICES_DATED}; a fatura do provedor é o que vale)."
        )
    return (
        f"Motor: {provider_label}, modelo {model}.\n\n"
        f"Comentários a traduzir pelo modelo: {format_int(estimate.comments)}{de_cache}, "
        f"{format_int(estimate.characters)} caracteres.\n"
        f"Tokens estimados: ~{format_int(estimate.input_tokens)} de entrada, "
        f"~{format_int(estimate.output_tokens)} de saída.\n\n"
        f"{custo}"
    )


def describe_outcome(model: str, estimated: float | None, usage: Any) -> str:
    """A linha "estimado -> real" do fim da execucao."""
    real = actual_cost(model, usage)
    if estimated is None or real is None:
        return f"Custo: sem preco na tabela para o modelo '{model}' — veja a fatura do provedor."
    return (
        f"Custo em dolares: estimado ~{format_usd(estimated)}, real {format_usd(real)} "
        f"(tabela de {PRICES_DATED}; a fatura do provedor e o que vale)."
    )


def describe_estimate_line(estimate: CostEstimate, model: str, cached: int) -> str:
    """A mesma estimativa numa linha so, para o log."""
    if estimate.cost_usd is None:
        custo = "sem preco na tabela"
    else:
        custo = f"~{format_usd(estimate.cost_usd)}"
    return (
        f"Estimativa para o modelo {model}: {format_int(estimate.comments)} comentarios "
        f"para a API ({format_int(cached)} no banco), {format_int(estimate.characters)} "
        f"caracteres, ~{format_int(estimate.input_tokens)} tokens de entrada, "
        f"~{format_int(estimate.output_tokens)} de saida, {custo}."
    )
