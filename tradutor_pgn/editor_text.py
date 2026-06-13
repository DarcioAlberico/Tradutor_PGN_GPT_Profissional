def find_text_ranges(text, query, case_sensitive=False):
    text = text or ""
    query = query or ""
    if not query:
        return []

    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    ranges = []
    start = 0
    step = max(1, len(query))

    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        ranges.append((index, index + len(query)))
        start = index + step

    return ranges


def replace_text_range(text, start, end, replacement):
    text = text or ""
    replacement = replacement or ""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return text[:start] + replacement + text[end:]


def replace_all_text(text, query, replacement, case_sensitive=False):
    ranges = find_text_ranges(text, query, case_sensitive=case_sensitive)
    if not ranges:
        return text or "", 0

    updated = text or ""
    for start, end in reversed(ranges):
        updated = replace_text_range(updated, start, end, replacement)
    return updated, len(ranges)
