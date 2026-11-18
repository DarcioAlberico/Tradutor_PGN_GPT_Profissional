"""Confirmar cada substituição verbal no contexto antes de alterar o livro."""

from dataclasses import replace


class VerbalPreviewCancelled(Exception):
    """A contextual preview was cancelled before any change."""


def filter_verbal_preview(preview, issue, request, assistant, *, cancelled=lambda: False):
    """Retain only protected-span candidates confirmed by the same grammar rule."""
    try:
        issue.validate_for(request)
        if (not request.grammar_enabled or issue.category != "VERBAL_AGREEMENT"
                or issue.state != "active" or issue.rule_id in request.disabled_rule_ids
                or preview.original != issue.original
                or preview.replacement not in issue.suggestions
                or preview.target_language != request.target_language):
            raise ValueError("invalid context")
        rows = []
        for row in preview.rows:
            if cancelled():
                raise VerbalPreviewCancelled()
            candidate = replace(request, text=row.text, text_version=row.revision,
                                source_text=row.source_text, glossary_terms=preview.glossary_terms)
            result = assistant.analyze(candidate)
            result.validate_for(candidate)
            if result.mode != "full" or result.diagnostic:
                raise ValueError("grammar unavailable")
            confirmed = {(item.start, item.end) for item in result.issues
                         if item.state == "active" and item.category == "VERBAL_AGREEMENT"
                         and item.rule_id == issue.rule_id and item.original == preview.original
                         and preview.replacement in item.suggestions}
            spans = tuple(span for span in row.spans if span in confirmed)
            if spans:
                rows.append(replace(row, spans=spans))
        if cancelled():
            raise VerbalPreviewCancelled()
        return replace(preview, rows=tuple(rows))
    except VerbalPreviewCancelled:
        raise
    except Exception as error:
        raise ValueError("Não foi possível confirmar a concordância em todo o livro. Nada foi alterado.") from error
