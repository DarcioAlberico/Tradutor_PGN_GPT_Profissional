"""Explicação não destrutiva de um rascunho de regra do glossário."""
from dataclasses import dataclass

from .glossario import (
    GLOSSARY_RULE_AUTOMATIC, GLOSSARY_RULE_CLEANUP, GLOSSARY_RULE_SUGGESTION,
    clean_comment_for_translation, filter_glossary_entries_by_type,
    interactive_rules_from_entries, scope_languages, scope_matches,
)
from .glossary_engine import SimulationCanceled, explain_substitutions, format_explanation
from .glossary_ui_helpers import describe_scope


@dataclass(frozen=True)
class RuleImpact:
    draft: tuple
    source: str | None
    target: str | None
    scope_status: str
    sample: str
    isolated: str | None = None
    before: str | None = None
    after: str | None = None
    explanation: object | None = None


def analyze_rule(draft, entries, selected_index, sample, source, target, *, should_cancel=None):
    """Compara uma fotografia do catálogo, usando a conversão da fase real."""
    def check():
        if should_cancel is not None and should_cancel():
            raise SimulationCanceled()
    check()
    pattern, replacement, phase, priority, scope = draft
    if phase not in (GLOSSARY_RULE_SUGGESTION, GLOSSARY_RULE_CLEANUP, GLOSSARY_RULE_AUTOMATIC):
        raise ValueError("Tipo de regra desconhecido")
    before_entries = list(entries)
    after_entries = list(before_entries)
    if selected_index is None:
        after_entries.append(draft)
    elif isinstance(selected_index, int) and not isinstance(selected_index, bool) and 0 <= selected_index < len(after_entries):
        after_entries[selected_index] = draft
    else:
        raise ValueError("A seleção do catálogo mudou")
    scope_source, scope_target = scope_languages(scope)
    scope_status = ("unknown" if not target and (scope_source or scope_target) else
                    "compatible" if scope_matches(scope, source, target) else "outside")
    if not pattern or priority is None or not sample or not target:
        return RuleImpact(draft, source, target, scope_status, sample)

    def rules(items):
        check()
        if phase == GLOSSARY_RULE_SUGGESTION:
            return interactive_rules_from_entries(items, source, target)
        return filter_glossary_entries_by_type(items, phase, source, target)

    isolated_rules = filter_glossary_entries_by_type([draft], phase, source, target)
    check()
    isolated = (clean_comment_for_translation(sample, isolated_rules) if phase == GLOSSARY_RULE_CLEANUP
                else explain_substitutions(sample, isolated_rules, should_cancel=should_cancel).text)
    before_explanation = explain_substitutions(sample, rules(before_entries), should_cancel=should_cancel)
    after_explanation = explain_substitutions(sample, rules(after_entries), include_suppressed=True,
                                               max_suppressed=25, should_cancel=should_cancel)
    before, after = before_explanation.text, after_explanation.text
    if phase == GLOSSARY_RULE_CLEANUP:
        before, after = " ".join(before.split()), " ".join(after.split())
    check()
    return RuleImpact(draft, source, target, scope_status, sample, isolated, before, after, after_explanation)


def format_rule_impact(result):
    pattern, _replacement, phase, priority, scope = result.draft
    phases = {
        GLOSSARY_RULE_SUGGESTION: "Sugestão: oferece uma opção para revisão; não é aplicada automaticamente.",
        GLOSSARY_RULE_CLEANUP: "Limpeza: atua no comentário antes da tradução.",
        GLOSSARY_RULE_AUTOMATIC: "Automática: atua depois da tradução, na fase automática.",
    }
    states = {"compatible": "compatível com o par de teste", "outside": "fora do par de teste",
              "unknown": "compatibilidade não determinada sem destino"}
    lines = [phases[phase], f"{describe_scope(scope)} ({states[result.scope_status]})."]
    if phase == GLOSSARY_RULE_SUGGESTION:
        lines.append("A comparação simula a prévia interativa; ela não prevê a escolha do revisor ou do modelo.")
    elif phase == GLOSSARY_RULE_CLEANUP:
        lines.append("A fase de limpeza também normaliza espaços no texto.")
    lines.append("Prioridade inválida: informe um número inteiro." if priority is None else
                 f"Prioridade {priority}: a precedência considera prioridade, especificidade e ordem do catálogo.")
    if not pattern:
        lines.append("Informe o padrão da regra para simular.")
    elif not result.target:
        lines.append("Selecione um idioma de destino para comparar o escopo.")
    elif not result.sample:
        lines.append("Digite um texto de teste para simular.")
    elif priority is not None and result.after is not None:
        def short(value):
            return value if len(value) <= 240 else value[:239] + "…"
        lines.extend(["", f"Regra isolada: {short(result.isolated)!r}",
                      f"Catálogo antes: {short(result.before)!r}",
                      f"Catálogo com a edição: {short(result.after)!r}",
                      "", "Regras aplicadas e concorrentes na fase escolhida:",
                      format_explanation(result.explanation)])
    lines.append("\nA análise usa o catálogo carregado e a fase escolhida; não inclui regras de semente, outras fases nem textos futuros. Mudar o tipo também pode afetar a fase anterior.")
    return "\n".join(lines)
