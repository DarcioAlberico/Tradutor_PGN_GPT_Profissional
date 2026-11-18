"""Explicações estruturadas das regras aplicadas pelo motor existente."""

from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
from bisect import bisect_left
import sqlite3

from .database import AutomaticRulesCanceled, _iter_automatic_rule_rows

from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    apply_all_substitutions,
    filter_glossary_entries_by_type,
    find_glossary_matches,
    order_rules_by_specificity,
    rule_priority,
    versioned_rules,
)


@dataclass(frozen=True)
class AppliedMatch:
    pattern: str
    configured_replacement: str
    matched: str
    replacement: str
    priority: int
    start: int
    end: int
    order: int


@dataclass(frozen=True)
class SuppressedMatch:
    pattern: str
    configured_replacement: str
    matched: str
    start: int
    end: int
    priority: int
    winner: AppliedMatch
    reason: str


@dataclass(frozen=True)
class Explanation:
    text: str
    matches: tuple[AppliedMatch, ...]
    suppressed: tuple[SuppressedMatch, ...] = ()
    truncated: bool = False
    analyzed_suppression: bool = False


@dataclass(frozen=True)
class SimulationItem:
    text: str
    source_language: str | None
    target_language: str | None
    reference: int | None = None


@dataclass(frozen=True)
class SimulationExample:
    item: SimulationItem
    before: str
    after: str


@dataclass(frozen=True)
class SimulationPair:
    source_language: str | None
    target_language: str
    scanned: int
    changed: int


@dataclass(frozen=True)
class SimulationResult:
    scanned: int
    changed: int
    unchanged: int
    examples: tuple[SimulationExample, ...]
    pairs: tuple[SimulationPair, ...] = ()


class SimulationCanceled(Exception):
    """A simulação foi cancelada e seus resultados parciais foram descartados."""


def format_simulation_summary(result):
    """Resume a fotografia analisada, sem inferir impacto em textos futuros."""
    if not result.scanned:
        return "Nenhuma tradução pendente foi encontrada para os filtros selecionados."
    percent = result.changed * 100 // result.scanned
    lines = [f"{result.changed} de {result.scanned} traduções analisadas teriam resultado diferente ({percent}%)."]
    if result.pairs:
        lines.append("Por par de idiomas:")
        for pair in result.pairs[:10]:
            lines.append(f"  {pair.source_language or '?'} → {pair.target_language}: {pair.changed} de {pair.scanned}.")
        if len(result.pairs) > 10:
            lines.append(f"  Mais {len(result.pairs) - 10} par(es) não exibidos.")
    omitted = result.changed - len(result.examples)
    if omitted > 0:
        lines.append(f"{omitted} exemplo(s) de alterações não exibidos.")
    return "\n".join(lines)


def format_simulation_examples(result):
    def shorten(value):
        return value if len(value) <= 160 else value[:159] + "…"

    def format_one(example):
        item = example.item
        header = (f"Comentário #{item.reference} ({item.source_language or '?'} → {item.target_language}):\n"
                  if item.reference is not None else "")
        return f"{header}Atual: {shorten(example.before)}\nCom a edição: {shorten(example.after)}"

    return "\n\n".join(format_one(example) for example in result.examples)


def simulate_rule_change(items, before_entries, after_entries, *, max_examples=10, should_cancel=None):
    """Compara o efeito das regras automáticas em um fluxo, sem gravar dados."""
    if not isinstance(max_examples, int) or isinstance(max_examples, bool) or max_examples < 0:
        raise ValueError("O limite de exemplos deve ser um inteiro não negativo")
    if should_cancel is not None and should_cancel():
        raise SimulationCanceled()
    before_entries, after_entries = list(before_entries), list(after_entries)
    cached = {}
    pair_counts = {}
    scanned = changed = 0
    examples = []
    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise SimulationCanceled()
    for item in items:
        check_cancel()
        if not item.target_language:
            raise ValueError("A simulação precisa do idioma de destino de cada texto")
        pair = (item.source_language, item.target_language)
        if pair not in cached:
            cached[pair] = tuple(versioned_rules(filter_glossary_entries_by_type(
                entries, GLOSSARY_RULE_AUTOMATIC, *pair
            )) for entries in (before_entries, after_entries))
        old_rules, new_rules = cached[pair]
        cancel_check = check_cancel if should_cancel is not None else None
        before = apply_all_substitutions(item.text, old_rules, _check_cancel=cancel_check)
        after = apply_all_substitutions(item.text, new_rules, _check_cancel=cancel_check)
        scanned += 1
        counts = pair_counts.setdefault(pair, [0, 0])
        counts[0] += 1
        if before != after:
            changed += 1
            counts[1] += 1
            if len(examples) < max_examples:
                examples.append(SimulationExample(item, before, after))
    if should_cancel is not None and should_cancel():
        raise SimulationCanceled()
    pairs = tuple(SimulationPair(source, target, counts[0], counts[1])
                  for (source, target), counts in pair_counts.items())
    return SimulationResult(scanned, changed, scanned - changed, tuple(examples), pairs)


def simulate_database_rule_change(path, before_entries, after_entries, *, max_examples=10,
                                  target_language=None, source_language=None,
                                  should_cancel=None, progress_callback=None):
    """Compara regras nas traduções pendentes, abrindo o banco somente para leitura."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = _iter_automatic_rule_rows(conn.cursor(), target_language,
                                         source_language=source_language, only_pending=True,
                                         should_cancel=should_cancel, progress_callback=progress_callback)

        def items():
            try:
                for row in rows:
                    yield SimulationItem(row[2], row[3], row[4], row[0])
            except AutomaticRulesCanceled as exc:
                raise SimulationCanceled() from exc

        return simulate_rule_change(items(), before_entries, after_entries,
                                    max_examples=max_examples, should_cancel=should_cancel)


def explain_substitutions(text, rules, *, include_suppressed=False, max_suppressed=100, should_cancel=None):
    if not isinstance(max_suppressed, int) or isinstance(max_suppressed, bool) or max_suppressed < 0:
        raise ValueError("O limite de ocorrências deve ser um inteiro não negativo")
    if should_cancel is not None and should_cancel():
        raise SimulationCanceled()
    text = text or ""
    ordered = order_rules_by_specificity(rules)
    matches = []

    def record(rule, matched, replacement, start, end, order):
        matches.append(AppliedMatch(rule[0], rule[1], matched, replacement, rule_priority(rule), start, end, order))

    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise SimulationCanceled()

    result = apply_all_substitutions(text, ordered, order_by_specificity=False, _on_match=record,
                                     _check_cancel=check_cancel if should_cancel is not None else None)
    if not include_suppressed:
        return Explanation(result, tuple(matches))
    if should_cancel is not None and should_cancel():
        raise SimulationCanceled()
    if not matches:
        return Explanation(result, (), (), False, True)
    winners = sorted(matches, key=lambda match: match.start)
    starts = [winner.start for winner in winners]
    suppressed = []
    truncated = False
    for order, rule in enumerate(ordered):
        if should_cancel is not None and should_cancel():
            raise SimulationCanceled()
        for start, end in find_glossary_matches(text, rule[0]):
            position = max(0, bisect_left(starts, start) - 1)
            overlaps = []
            while position < len(winners) and winners[position].start < end:
                winner = winners[position]
                if winner.end > start and winner.order < order:
                    overlaps.append(winner)
                position += 1
            if not overlaps:
                continue
            if len(suppressed) >= max_suppressed:
                truncated = True
                break
            winner = min(overlaps, key=lambda match: match.order)
            priority = rule_priority(rule)
            reason = ("prioridade" if winner.priority > priority else
                      "especificidade" if len(winner.pattern) > len(rule[0]) else "ordem")
            suppressed.append(SuppressedMatch(rule[0], rule[1], text[start:end], start, end, priority, winner, reason))
        if truncated:
            break
    return Explanation(result, tuple(matches), tuple(suppressed), truncated, True)


def format_explanation(explanation, max_rules=15):
    """Mostra regras efetivamente usadas, com limite para textos longos."""
    counts = {}
    for match in explanation.matches:
        key = (match.pattern, match.configured_replacement, match.priority)
        counts[key] = counts.get(key, 0) + 1
    def shorten(value):
        return value if len(value) <= 100 else value[:99] + "…"

    lines = [f"{shorten(orig)!r} → {shorten(replacement)!r} · prioridade {priority} · {count} ocorrência(s)"
             for (orig, replacement, priority), count in list(counts.items())[:max(0, max_rules)]]
    remaining = len(counts) - len(lines)
    if remaining:
        lines.append(f"Mais {remaining} regra(s) aplicada(s).")
    if not lines:
        lines.append("Nenhuma regra foi aplicada.")
    if explanation.analyzed_suppression:
        lines.append("\nOcorrências aplicadas no texto original:")
        for match in sorted(explanation.matches, key=lambda match: match.start)[:10]:
            lines.append(f"Caracteres {match.start + 1}–{match.end}: {shorten(match.matched)!r} "
                         f"→ {shorten(match.replacement)!r}.")
        if len(explanation.matches) > 10:
            lines.append("Lista de ocorrências aplicada limitada às primeiras 10.")
        lines.append("\nCandidatas bloqueadas por sobreposição no texto original:")
        for blocked in explanation.suppressed[:10]:
            reason = (f"prioridade {blocked.winner.priority} > {blocked.priority}"
                      if blocked.reason == "prioridade" else blocked.reason)
            lines.append(f"{shorten(blocked.pattern)!r} → {shorten(blocked.configured_replacement)!r} "
                         f"(caracteres {blocked.start + 1}–{blocked.end}) bloqueada por "
                         f"{shorten(blocked.winner.pattern)!r} → {shorten(blocked.winner.configured_replacement)!r}: "
                         f"{reason}.")
        if not explanation.suppressed:
            lines.append("Nenhuma sobreposição bloqueada foi encontrada.")
        if explanation.truncated or len(explanation.suppressed) > 10:
            lines.append("Lista limitada; outras ocorrências podem existir.")
        lines.append("A análise cobre apenas ocorrências identificadas no texto original.")
    return "\n".join(lines)
