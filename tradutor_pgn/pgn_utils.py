import os
import re

from .app_config import LANGUAGE_OUTPUT_SUFFIXES

try:
    import chardet
except ImportError:
    chardet = None


def flatten_comment(text: str) -> str:
    text = " ".join(text.split())
    return re.sub(r'([.!?])\s*(\w)', r'\1 \2', text)


def detect_encoding(file_path: str) -> str:
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(65536)

        if raw.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'

        if chardet is not None:
            result = chardet.detect(raw)
            enc = result['encoding'] or 'utf-8'
            confidence = result.get('confidence') or 0

            if confidence >= 0.60 and enc.lower() == 'windows-1252':
                return 'cp1252'
            if confidence >= 0.60 and enc.lower() in ['iso-8859-1', 'latin-1']:
                return 'latin-1'
            if confidence >= 0.60:
                return enc

        for enc in ('utf-8', 'cp1252', 'latin-1'):
            try:
                raw.decode(enc)
                return enc
            except UnicodeDecodeError:
                pass

    except Exception:
        pass

    return 'utf-8'


def output_suffix_for_language(target_language: str) -> str:
    return LANGUAGE_OUTPUT_SUFFIXES.get(target_language, target_language.upper())


def strip_generated_suffix(filename_without_ext: str) -> str:
    suffixes = "|".join(re.escape(s) for s in LANGUAGE_OUTPUT_SUFFIXES.values())
    return re.sub(rf"-({suffixes})$", "", filename_without_ext, flags=re.IGNORECASE)


def is_generated_pgn(file_path: str) -> bool:
    name, ext = os.path.splitext(os.path.basename(file_path))
    if ext.lower() != ".pgn":
        return False
    return strip_generated_suffix(name) != name


def translated_output_path(input_file: str, target_language: str) -> str:
    file_dir = os.path.dirname(input_file)
    name, ext = os.path.splitext(os.path.basename(input_file))
    base_name = strip_generated_suffix(name)
    suffix = output_suffix_for_language(target_language)
    output_file = os.path.join(file_dir, f"{base_name}-{suffix}{ext}")

    if os.path.abspath(output_file) == os.path.abspath(input_file):
        output_file = os.path.join(file_dir, f"{name}-novo{ext}")

    return output_file


def available_output_path(output_file: str) -> str:
    if not os.path.exists(output_file):
        return output_file

    file_dir = os.path.dirname(output_file)
    name, ext = os.path.splitext(os.path.basename(output_file))
    index = 2

    while True:
        candidate = os.path.join(file_dir, f"{name}-{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1


def collect_pgn_files(source_path: str, process_subdirs: bool):
    pgn_files = []
    skipped_generated = 0

    def add_file(path, allow_generated=False):
        nonlocal skipped_generated
        if not path.lower().endswith(".pgn"):
            return
        if not allow_generated and is_generated_pgn(path):
            skipped_generated += 1
            return
        pgn_files.append(path)

    if os.path.isfile(source_path):
        add_file(source_path, allow_generated=True)
    elif process_subdirs:
        for root, _, files in os.walk(source_path):
            for f in files:
                add_file(os.path.join(root, f))
    else:
        for f in os.listdir(source_path):
            add_file(os.path.join(source_path, f))

    return sorted(pgn_files), skipped_generated


def extract_comments_from_file(pgn_file: str, log_message=None):
    comments = []
    positions = []
    comment_pattern = re.compile(r'\{(.*?)\}', re.DOTALL)

    try:
        enc = detect_encoding(pgn_file)
        if log_message:
            log_message(f"Arquivo: {os.path.basename(pgn_file)} | Codificacao detectada: {enc}")

        with open(pgn_file, 'r', encoding=enc, errors='replace') as f:
            content = f.read()

        for match in comment_pattern.finditer(content):
            normalized = flatten_comment(match.group(1))
            if not normalized:
                continue

            comments.append(normalized)
            positions.append((match.start(), match.end(), normalized))

        return {"comments": comments, "positions": positions}

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao extrair comentarios de {pgn_file}: {e}")
        return {"comments": [], "positions": []}


def create_comment_batches(comments, max_chars=3800):
    batches = []
    current = []
    length = 0

    for comment in comments:
        l = len(comment)
        if l > max_chars:
            if current:
                batches.append(current)
            batches.append([comment])
            current = []
            length = 0
        elif length + l > max_chars:
            batches.append(current)
            current = [comment]
            length = l
        else:
            current.append(comment)
            length += l

    if current:
        batches.append(current)

    return batches


def sanitize_pgn_comment(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def write_translated_pgn(output_file: str, content: str, preferred_encoding: str, log_message=None):
    try:
        with open(output_file, 'w', encoding=preferred_encoding) as f:
            f.write(content)
        return preferred_encoding
    except UnicodeEncodeError:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)
        if log_message:
            log_message(f"  - Codificacao de saida alterada para UTF-8: {output_file}")
        return 'utf-8'


def generate_translated_pgn(input_file, output_file, translated_map, positions, log_message=None):
    try:
        enc = detect_encoding(input_file)
        with open(input_file, 'r', encoding=enc, errors='replace') as f:
            content = f.read()

        replacements = []
        for start, end, norm in positions:
            if norm in translated_map:
                repl = "{" + sanitize_pgn_comment(translated_map[norm]) + "}"
                replacements.append((start, end, repl))

        replacements.sort(reverse=True, key=lambda x: x[0])

        for start, end, rep in replacements:
            content = content[:start] + rep + content[end:]

        write_translated_pgn(output_file, content, enc, log_message)
        return True

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao gravar PGN traduzido: {e}")
        return False
