import os
import re

from .pgn_utils import available_output_path, detect_encoding, write_translated_pgn


DEFAULT_SPELLING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "spelling_ssp",
    "spelling.ssp",
)
NORMALIZED_SUFFIX = "-NORM"
SUPPORTED_TAGS = {
    "White": "PLAYER",
    "Black": "PLAYER",
    "Site": "SITE",
    "Event": "EVENT",
    "Round": "ROUND",
}
SECTION_RE = re.compile(r'^@(\w+)\s+"([^"]*)"')
PGN_TAG_RE = re.compile(r'^(\[(White|Black|Site|Event|Round)\s+")((?:\\.|[^"\\])*)("\]\s*)$')
QUOTED_PAIR_RE = re.compile(r'"([^"]*)"\s+"([^"]*)"')


def is_normalized_pgn(file_path):
    name, ext = os.path.splitext(os.path.basename(file_path))
    return ext.lower() == ".pgn" and name.upper().endswith(NORMALIZED_SUFFIX)


def normalized_output_path(input_file):
    file_dir = os.path.dirname(input_file)
    name, ext = os.path.splitext(os.path.basename(input_file))
    if name.upper().endswith(NORMALIZED_SUFFIX):
        output_file = os.path.join(file_dir, f"{name}-novo{ext}")
    else:
        output_file = os.path.join(file_dir, f"{name}{NORMALIZED_SUFFIX}{ext}")
    return available_output_path(output_file)


def collect_spellcheck_pgn_files(source_path, process_subdirs):
    pgn_files = []
    skipped_normalized = 0

    def add_file(path, allow_normalized=False):
        nonlocal skipped_normalized
        if not path.lower().endswith(".pgn"):
            return
        if not allow_normalized and is_normalized_pgn(path):
            skipped_normalized += 1
            return
        pgn_files.append(path)

    if os.path.isfile(source_path):
        add_file(source_path, allow_normalized=True)
    elif process_subdirs:
        for root, _, files in os.walk(source_path):
            for filename in files:
                add_file(os.path.join(root, filename))
    else:
        for filename in os.listdir(source_path):
            add_file(os.path.join(source_path, filename))

    return sorted(pgn_files), skipped_normalized


def strip_ssp_comment(line):
    return line.split("#", 1)[0].strip()


def normalize_spell_key(value, ignore_chars):
    normalized = value.strip()
    for char in ignore_chars:
        normalized = normalized.replace(char, "")
    return normalized.casefold()


def parse_spelling_file(path=DEFAULT_SPELLING_PATH):
    sections = {}
    current_section = None
    current_canonical = None
    ignore_chars = ""
    prefix_rules = []
    suffix_rules = []

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            section_match = SECTION_RE.match(line)
            if section_match:
                current_section = section_match.group(1).upper()
                ignore_chars = section_match.group(2)
                sections[current_section] = {
                    "entries": {},
                    "ignore_chars": ignore_chars,
                    "prefix_rules": [],
                    "suffix_rules": [],
                }
                current_canonical = None
                prefix_rules = sections[current_section]["prefix_rules"]
                suffix_rules = sections[current_section]["suffix_rules"]
                continue

            if current_section is None:
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("%Bio"):
                continue

            if stripped.startswith("%Prefix"):
                pair = QUOTED_PAIR_RE.search(stripped)
                if pair:
                    prefix_rules.append((pair.group(1), pair.group(2)))
                continue

            if stripped.startswith("%Suffix"):
                pair = QUOTED_PAIR_RE.search(stripped)
                if pair:
                    suffix_rules.append((pair.group(1), pair.group(2)))
                continue

            if stripped.startswith("="):
                if current_canonical is None:
                    continue
                alias = strip_ssp_comment(stripped[1:])
                if alias:
                    key = normalize_spell_key(alias, ignore_chars)
                    sections[current_section]["entries"].setdefault(key, current_canonical)
                continue

            if line[:1].isspace():
                continue

            canonical = strip_ssp_comment(line)
            if not canonical:
                current_canonical = None
                continue

            current_canonical = canonical
            key = normalize_spell_key(canonical, ignore_chars)
            sections[current_section]["entries"].setdefault(key, current_canonical)

    return sections


def apply_affix_rules(value, section_data):
    result = value.strip()
    for old, new in section_data.get("prefix_rules", []):
        if result.startswith(old):
            result = new + result[len(old):]
    for old, new in section_data.get("suffix_rules", []):
        if result.endswith(old):
            result = result[: len(result) - len(old)] + new
    return result


def player_name_variants(value):
    variants = [value]
    cleaned = value.strip()
    if " " in cleaned and "," not in cleaned:
        before, after = cleaned.rsplit(" ", 1)
        variants.append(f"{after}, {before}")
    return variants


def correct_spelling_value(value, section_name, spelling_data):
    section_data = spelling_data.get(section_name)
    if not section_data:
        return value

    prepared = apply_affix_rules(value, section_data)
    variants = player_name_variants(prepared) if section_name == "PLAYER" else [prepared]
    ignore_chars = section_data.get("ignore_chars", "")
    entries = section_data.get("entries", {})

    for variant in variants:
        key = normalize_spell_key(variant, ignore_chars)
        corrected = entries.get(key)
        if corrected:
            return corrected

    return value


def normalize_pgn_metadata_content(content, spelling_data):
    changes = []
    updated_lines = []

    for line in content.splitlines(keepends=True):
        newline = ""
        body = line
        if body.endswith("\r\n"):
            body = body[:-2]
            newline = "\r\n"
        elif body.endswith("\n"):
            body = body[:-1]
            newline = "\n"

        match = PGN_TAG_RE.match(body)
        if not match:
            updated_lines.append(line)
            continue

        prefix, tag_name, value, suffix = match.groups()
        section_name = SUPPORTED_TAGS[tag_name]
        corrected = correct_spelling_value(value, section_name, spelling_data)
        if corrected != value:
            changes.append(
                {
                    "tag": tag_name,
                    "previous": value,
                    "new": corrected,
                }
            )
            body = f"{prefix}{corrected}{suffix}"

        updated_lines.append(body + newline)

    return "".join(updated_lines), changes


def normalize_pgn_metadata_file(input_file, spelling_data, output_file=None, log_message=None):
    enc = detect_encoding(input_file)
    with open(input_file, "r", encoding=enc, errors="replace") as handle:
        content = handle.read()

    updated_content, changes = normalize_pgn_metadata_content(content, spelling_data)
    if not changes:
        return {
            "input_file": input_file,
            "output_file": None,
            "changed": False,
            "changes": [],
        }

    output_file = output_file or normalized_output_path(input_file)
    output_encoding = write_translated_pgn(output_file, updated_content, enc, log_message)
    return {
        "input_file": input_file,
        "output_file": output_file,
        "changed": True,
        "changes": changes,
        "encoding": output_encoding,
    }


def normalize_pgn_metadata_path(
    source_path,
    process_subdirs=False,
    spelling_path=DEFAULT_SPELLING_PATH,
    log_message=None,
    progress_callback=None,
):
    if not os.path.exists(spelling_path):
        raise FileNotFoundError(f"Arquivo spelling.ssp nao encontrado: {spelling_path}")

    if log_message:
        log_message("Carregando spelling.ssp...")
    spelling_data = parse_spelling_file(spelling_path)

    pgn_files, skipped_normalized = collect_spellcheck_pgn_files(
        source_path,
        process_subdirs,
    )
    stats = {
        "files": len(pgn_files),
        "changed_files": 0,
        "unchanged_files": 0,
        "changes": 0,
        "skipped_normalized": skipped_normalized,
        "outputs": [],
    }

    for index, pgn_file in enumerate(pgn_files, start=1):
        result = normalize_pgn_metadata_file(
            pgn_file,
            spelling_data,
            log_message=log_message,
        )
        if result["changed"]:
            stats["changed_files"] += 1
            stats["changes"] += len(result["changes"])
            stats["outputs"].append(result["output_file"])
            if log_message:
                log_message(
                    f"  - {os.path.basename(pgn_file)}: "
                    f"{len(result['changes'])} correcao(oes) -> "
                    f"{os.path.basename(result['output_file'])}"
                )
        else:
            stats["unchanged_files"] += 1
            if log_message:
                log_message(f"  - {os.path.basename(pgn_file)}: sem alteracoes")

        if progress_callback and stats["files"]:
            progress_callback(index / stats["files"])

    return stats
