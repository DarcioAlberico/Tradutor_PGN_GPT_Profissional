"""Verificação de integridade de uma fotografia dos pacotes filtrados."""
from dataclasses import dataclass
import unicodedata

from .translation_library import verify_bundle


class BatchIntegrityCanceled(Exception):
    """O cancelamento descarta todas as contagens parciais."""


@dataclass(frozen=True)
class IntegrityExample:
    name: str
    status: str
    original_ok: bool | None = None
    translation_ok: bool | None = None


@dataclass(frozen=True)
class BatchIntegrityResult:
    total: int
    verified: int
    mismatch: int
    changed: int
    unavailable: int
    examples: tuple[IntegrityExample, ...]


def verify_bundles(bundles, *, verifier=verify_bundle, should_cancel=None, progress=None, max_examples=10):
    if not isinstance(max_examples, int) or isinstance(max_examples, bool) or max_examples < 0:
        raise ValueError("Limite de exemplos inválido")
    items = tuple(bundles)
    counts = {name: 0 for name in ("verified", "mismatch", "changed", "unavailable")}
    examples = []
    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise BatchIntegrityCanceled()
    check_cancel()
    for index, bundle in enumerate(items, 1):
        check_cancel()
        result = verifier(bundle.directory, should_cancel=should_cancel)
        check_cancel()
        if result.status == "canceled":
            raise BatchIntegrityCanceled()
        if result.status not in counts:
            raise ValueError("Resultado de integridade desconhecido")
        counts[result.status] += 1
        if result.status != "verified" and len(examples) < max_examples:
            examples.append(IntegrityExample(bundle.directory.name, result.status,
                                             result.original_ok, result.translation_ok))
        if progress is not None:
            progress(index, len(items))
    check_cancel()
    return BatchIntegrityResult(len(items), counts["verified"], counts["mismatch"], counts["changed"],
                                counts["unavailable"], tuple(examples))


def format_integrity_batch(result):
    lines = [f"Pacotes analisados: {result.total}.",
             f"Correspondem aos hashes: {result.verified}.",
             f"Divergentes: {result.mismatch}.",
             f"Alterados durante a leitura: {result.changed}.",
             f"Não verificáveis: {result.unavailable}."]
    labels = {"mismatch": "divergência", "changed": "alterado durante a leitura", "unavailable": "não verificável"}
    if result.examples:
        lines.append("\nExemplos que precisam de atenção:")
        for item in result.examples:
            name = ''.join(' ' if unicodedata.category(c).startswith('C') else c for c in item.name)
            name = name if len(name) <= 100 else name[:99] + "…"
            detail = labels[item.status]
            if item.status == "mismatch":
                files = (["original"] if item.original_ok is False else []) + (["traduzido"] if item.translation_ok is False else [])
                if files:
                    detail += ": " + " e ".join(files)
            lines.append(f"• {name} — {detail}")
    omitted = result.mismatch + result.changed + result.unavailable - len(result.examples)
    if omitted:
        lines.append(f"Mais {omitted} pacote(s) não exibidos.")
    lines.append("\nPacotes sem manifesto compatível não podem ser conferidos. Os hashes não autenticam a procedência do manifesto.")
    return "\n".join(lines)
