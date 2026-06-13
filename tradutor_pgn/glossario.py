# glossario.py
# Carrega e manipula o arquivo Substituicoes.txt.

import ast
import os
import sys


SUBSTITUTION_VARIABLES = {"substituições", "substituicoes"}


def _default_substitutions_path():
    """Retorna o caminho padrão do arquivo Substituicoes.txt."""
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, "Substituicoes.txt")


def _read_substitution_assignment(code, path):
    tree = ast.parse(code, filename=path)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in SUBSTITUTION_VARIABLES:
                value = ast.literal_eval(node.value)
                if not isinstance(value, (list, tuple)):
                    raise ValueError("A variável de substituições precisa ser uma lista.")
                return value

    raise ValueError("Variável 'substituições' ou 'substituicoes' não encontrada.")


def load_substitutions(path=None):
    """
    Carrega a lista de substituições do arquivo Substituicoes.txt.

    Espera uma atribuição Python contendo uma lista de pares:
        substituições = [
            ('tower', 'torre'),
            ('pawn', 'peão'),
        ]
    """
    if path is None:
        path = _default_substitutions_path()

    if not os.path.exists(path):
        print(f"[GLOSSÁRIO] Arquivo não encontrado: {path}")
        return []

    substitutions = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_items = _read_substitution_assignment(f.read(), path)

        seen = set()
        for item in raw_items:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                orig, new = item
                pair = (str(orig), str(new))
                if pair in seen:
                    continue
                seen.add(pair)
                substitutions.append(pair)

        print(f"[GLOSSÁRIO] Carregadas {len(substitutions)} entradas do glossário.")
        return substitutions

    except Exception as e:
        print(f"[GLOSSÁRIO] Erro ao carregar Substituicoes.txt: {e}")
        return []


def find_glossary_suggestions(text, substitutions, max_suggestions=80):
    """
    Retorna entradas do glossário que aparecem em text.
    """
    if not text:
        return []

    suggestions = []
    for orig, new in substitutions:
        if orig and orig in text:
            suggestions.append((orig, new))
            if len(suggestions) >= max_suggestions:
                break

    return suggestions


def apply_substitution(text, orig, new):
    """Aplica uma substituição, na primeira ocorrência encontrada."""
    return text.replace(orig, new, 1)


def apply_all_substitutions(text, suggestions):
    """Aplica todas as substituições sugeridas em sequência."""
    for orig, new in suggestions:
        if orig in text:
            text = text.replace(orig, new)
    return text


def add_to_glossary(orig, new, path=None):
    """
    Adiciona um par (orig, new) ao arquivo Substituicoes.txt.
    """
    if path is None:
        path = _default_substitutions_path()

    try:
        orig = str(orig)
        new = str(new)

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("substituicoes = [\n]\n")

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        raw_items = _read_substitution_assignment("".join(lines), path)
        existing = {
            (str(item[0]), str(item[1]))
            for item in raw_items
            if isinstance(item, (list, tuple)) and len(item) == 2
        }
        if (orig, new) in existing:
            return True

        insert_at = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() in {"]", "];"}:
                insert_at = i
                break

        if insert_at is None:
            raise ValueError("Não foi encontrado o fechamento da lista de substituições.")

        lines.insert(insert_at, f"    ({orig!r}, {new!r}),\n")

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return True

    except Exception as e:
        print(f"[GLOSSÁRIO] Erro ao adicionar entrada: {e}")
        return False
