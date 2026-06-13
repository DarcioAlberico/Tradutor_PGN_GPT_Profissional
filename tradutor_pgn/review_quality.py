from collections import Counter


QUALITY_REPORT_HEADERS = [
    "id",
    "target_language",
    "status",
    "warning_count",
    "warnings",
    "original_comment",
    "translated_comment",
]


def evaluate_translation_quality(original, translated):
    original = (original or "").strip()
    translated = (translated or "").strip()
    warnings = []

    if not translated:
        warnings.append("Tradução vazia.")
        return warnings

    if original and translated.casefold() == original.casefold():
        warnings.append("Tradução igual ao original.")

    if "{" in translated or "}" in translated:
        warnings.append("Contém chaves { } que podem interferir no comentário PGN.")

    original_len = len(original)
    translated_len = len(translated)
    if original_len >= 40:
        if translated_len < original_len * 0.35:
            warnings.append("Tradução muito curta em relação ao original.")
        elif translated_len > original_len * 2.5:
            warnings.append("Tradução muito longa em relação ao original.")

    return warnings


def row_quality_warnings(row):
    if len(row) < 3:
        return []
    return evaluate_translation_quality(row[1], row[2])


def row_has_quality_warning(row):
    return bool(row_quality_warnings(row))


def filter_quality_warning_rows(rows):
    return [row for row in rows if row_has_quality_warning(row)]


def build_quality_report_rows(rows, target_language=""):
    report_rows = []
    for row in rows:
        if len(row) < 4:
            continue

        warnings = row_quality_warnings(row)
        if not warnings:
            continue

        status = "verified" if row[3] == 1 else "pending"
        report_rows.append((
            row[0],
            target_language,
            status,
            len(warnings),
            " | ".join(warnings),
            row[1] or "",
            row[2] or "",
        ))

    return report_rows


def summarize_quality_warnings(rows):
    warning_counts = Counter()
    summary = {
        "total_rows": 0,
        "warning_rows": 0,
        "pending_warning_rows": 0,
        "verified_warning_rows": 0,
        "warning_total": 0,
        "warning_counts": {},
    }

    for row in rows:
        if len(row) < 3:
            continue

        summary["total_rows"] += 1
        warnings = row_quality_warnings(row)
        if not warnings:
            continue

        summary["warning_rows"] += 1
        summary["warning_total"] += len(warnings)
        warning_counts.update(warnings)

        if len(row) > 3 and row[3] == 1:
            summary["verified_warning_rows"] += 1
        else:
            summary["pending_warning_rows"] += 1

    summary["warning_counts"] = dict(
        sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return summary


def find_first_quality_warning(rows, start_index=0):
    for index, row in enumerate(rows[start_index:], start=start_index):
        warnings = row_quality_warnings(row)
        if warnings:
            return index, row, warnings

    return None
