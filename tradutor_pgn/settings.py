import json
import os
import sys
from datetime import datetime


SETTINGS_FILENAME = "pgn_tradutor_pro_settings.json"
MAX_EDITOR_DRAFTS = 200


def default_settings_path():
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, SETTINGS_FILENAME)


def load_settings(path=None):
    if path is None:
        path = default_settings_path()

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def save_settings(settings, path=None):
    """Grava as configuracoes de forma atomica.

    `open(..., "w")` trunca o arquivo antes de escrever: uma queda no meio do
    `json.dump` deixaria um JSON invalido, e `load_settings` devolve `{}` em
    silencio nesse caso — ou seja, todas as preferencias e rascunhos sumiriam.
    Grava num temporario e troca de nome (garantia R4 da SPEC.md).
    """
    if path is None:
        path = default_settings_path()

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    os.replace(tmp_path, path)


def update_settings(mutator, path=None):
    """Aplica `mutator` sobre o estado atual do disco e grava o resultado.

    Cada janela do app carrega seu proprio snapshot das configuracoes na
    abertura. Se cada uma gravasse esse snapshot inteiro, a ultima a salvar
    apagaria tudo o que a outra tivesse escrito depois — inclusive os rascunhos
    de traducao nao salvos. Reler do disco imediatamente antes de gravar
    preserva o que a outra janela mudou (garantia R4 da SPEC.md).

    `mutator` recebe o dicionario lido do disco e o altera no lugar; o valor que
    devolver e repassado ao chamador.
    """
    settings = load_settings(path)
    result = mutator(settings)
    save_settings(settings, path)
    return result


def editor_draft_key(db_path, target_language, comment_id):
    normalized_db = os.path.normcase(os.path.abspath(str(db_path or "")))
    return f"{normalized_db}::{target_language or ''}::{int(comment_id)}"


def _ensure_editor_drafts(settings):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        drafts = {}
        settings["editor_drafts"] = drafts
    return drafts


def prune_editor_drafts(settings, max_entries=MAX_EDITOR_DRAFTS):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return 0

    max_entries = max(0, int(max_entries))
    overflow = len(drafts) - max_entries
    if overflow <= 0:
        return 0

    def sort_key(item):
        _key, draft = item
        if isinstance(draft, dict):
            return draft.get("updated_at") or ""
        return ""

    removed = 0
    for key, _draft in sorted(drafts.items(), key=sort_key)[:overflow]:
        drafts.pop(key, None)
        removed += 1
    return removed


def set_editor_draft(
    settings,
    db_path,
    target_language,
    comment_id,
    text,
    base_translation,
    updated_at=None,
    max_entries=MAX_EDITOR_DRAFTS,
):
    text = text or ""
    base_translation = base_translation or ""
    key = editor_draft_key(db_path, target_language, comment_id)
    drafts = _ensure_editor_drafts(settings)

    if text == base_translation:
        return drafts.pop(key, None) is not None

    drafts[key] = {
        "text": text,
        "base_translation": base_translation,
        "updated_at": updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    prune_editor_drafts(settings, max_entries)
    return True


def get_editor_draft(settings, db_path, target_language, comment_id, current_translation):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return None

    draft = drafts.get(editor_draft_key(db_path, target_language, comment_id))
    if not isinstance(draft, dict):
        return None

    text = draft.get("text")
    base_translation = draft.get("base_translation")
    if not isinstance(text, str) or not isinstance(base_translation, str):
        return None

    current_translation = current_translation or ""
    if base_translation != current_translation or text == current_translation:
        return None

    return {
        "text": text,
        "base_translation": base_translation,
        "updated_at": draft.get("updated_at") or "",
    }


def clear_editor_draft(settings, db_path, target_language, comment_id):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return False
    return drafts.pop(editor_draft_key(db_path, target_language, comment_id), None) is not None


MAIN_WINDOW_KEY = "main_window"

MAIN_WINDOW_DEFAULTS = {
    "source_language": "",
    "target_language": "pt",
    "process_subdirs": True,
    "source_path": "",
}


def read_main_window_settings(settings, known_languages):
    """As escolhas da janela principal, validadas contra os idiomas que existem.

    O arquivo e JSON editavel a mao e sobrevive a versoes do programa, entao um
    idioma que o programa nao oferece mais nao pode deixar o seletor num estado
    invalido — ele cai no padrao, como todo campo desconhecido do glossario.

    Pura de proposito: quem decide o que e valido nao precisa de Tk nem de
    disco, e a validacao e a parte que da para errar.
    """
    guardado = settings.get(MAIN_WINDOW_KEY)
    if not isinstance(guardado, dict):
        return dict(MAIN_WINDOW_DEFAULTS)

    valores = dict(MAIN_WINDOW_DEFAULTS)

    origem = guardado.get("source_language")
    # A string vazia e "Detectar", um valor legitimo e nao um campo ausente. O
    # `origem == ""` e explicito de proposito, e **hoje ele nao muda o
    # resultado**: o padrao tambem e vazio, entao recusar a string vazia cairia
    # no mesmo lugar. Vale pelo dia em que o padrao mudar — e porque um leitor
    # que veja so `origem in known_languages` conclui, errado, que "Detectar"
    # nao pode ser lembrado.
    if isinstance(origem, str) and (origem == "" or origem in known_languages):
        valores["source_language"] = origem

    destino = guardado.get("target_language")
    if isinstance(destino, str) and destino in known_languages:
        valores["target_language"] = destino

    subdirs = guardado.get("process_subdirs")
    if isinstance(subdirs, bool):
        valores["process_subdirs"] = subdirs

    caminho = guardado.get("source_path")
    if isinstance(caminho, str):
        # Nao se checa existencia aqui: o caminho pode estar num pendrive que
        # ainda nao foi plugado, e apaga-lo por isso seria pior do que
        # oferece-lo. Quem valida e o "Iniciar Traducao", que ja o fazia.
        valores["source_path"] = caminho

    return valores


def write_main_window_settings(values, path=None):
    """Grava as escolhas relendo o disco antes (garantia R4).

    As janelas de edicao guardam rascunhos no MESMO arquivo. Gravar o snapshot
    inteiro daqui apagaria o que elas escreveram desde que este processo abriu —
    que e exatamente o defeito que R4 existe para impedir.
    """
    def mutator(settings):
        guardado = settings.get(MAIN_WINDOW_KEY)
        if not isinstance(guardado, dict):
            guardado = {}
            settings[MAIN_WINDOW_KEY] = guardado
        guardado.update(values)
        return guardado

    return update_settings(mutator, path)
