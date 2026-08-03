import json
import os
import threading
from datetime import datetime

from .app_paths import data_path


SETTINGS_FILENAME = "pgn_tradutor_pro_settings.json"
MAX_EDITOR_DRAFTS = 200


def default_settings_path():
    return data_path(SETTINGS_FILENAME)


def load_settings(path=None):
    """Le as configuracoes, tolerando um BOM no arquivo.

    `utf-8-sig` na LEITURA e `utf-8` na gravacao: aceita-se o BOM, nao se
    escreve um. E a mesma assimetria que a leitura de CSV do programa ja usa, e
    aqui ela evita uma perda de dados silenciosa e total.

    O arquivo e JSON e editavel a mao — e o Bloco de Notas do Windows grava UTF-8
    **com BOM**. Lido como `utf-8`, o BOM faz o `json.load` levantar
    `JSONDecodeError`, este `except` devolve `{}` e o programa segue como se o
    arquivo estivesse vazio: somem os rascunhos nao salvos das janelas de edicao
    (garantia R4), a lista de arquivos que ficaram devendo (T4), o modo de busca,
    o tamanho da fonte e as escolhas da janela principal (M1).

    E a perda e definitiva, porque nada avisa: a proxima gravacao escreve um
    arquivo novo sem nada daquilo. Um caractere invisivel no inicio do arquivo
    apagava a memoria inteira do programa.
    """
    if path is None:
        path = default_settings_path()

    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
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


# Serializa o ciclo ler-alterar-gravar. Ele passou a acontecer de mais de uma
# thread (ROADMAP 19, item 10): o rascunho do editor grava em segundo plano, e o
# resto do programa continua gravando na thread do Tk. Sem o lock, duas gravacoes
# simultaneas fazem a segunda ler o disco ANTES de a primeira ter gravado, e o que
# a primeira escreveu desaparece — exatamente a perda que a garantia R4 existe para
# impedir, agora por corrida em vez de por snapshot velho.
#
# O lock protege este processo, que e onde a corrida existe: `save_settings` grava
# num temporario e troca de nome, entao um segundo processo veria um arquivo
# completo, nunca um pela metade.
_UPDATE_LOCK = threading.Lock()


def update_settings(mutator, path=None):
    """Aplica `mutator` sobre o estado atual do disco e grava o resultado.

    Cada janela do app carrega seu proprio snapshot das configuracoes na
    abertura. Se cada uma gravasse esse snapshot inteiro, a ultima a salvar
    apagaria tudo o que a outra tivesse escrito depois — inclusive os rascunhos
    de traducao nao salvos. Reler do disco imediatamente antes de gravar
    preserva o que a outra janela mudou (garantia R4 da SPEC.md).

    `mutator` recebe o dicionario lido do disco e o altera no lugar; o valor que
    devolver e repassado ao chamador.

    O ciclo inteiro roda sob um lock (ver `_UPDATE_LOCK`): a leitura, a alteracao e
    a gravacao sao uma coisa so, e desde que o rascunho passou a ser gravado em
    segundo plano ha duas threads chamando isto.
    """
    with _UPDATE_LOCK:
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


OUTPUT_KEY = "output"

# Menor requebra aceita. Abaixo disto o arquivo deixa de ser um PGN requebrado e
# passa a ser uma palavra por linha; 20 colunas nao servem para nada de util e ja
# sao larguras que ninguem digita por engano.
MIN_WRAP_COLUMNS = 20

OUTPUT_DEFAULTS = {
    # UTF-8 com BOM na saida. Desligado por padrao: e o comportamento de
    # sempre, e um BOM que ninguem pediu tambem incomoda (git, diff, parsers
    # estritos). Quem le os PGN gerados no ChessBase do Windows — que trata
    # UTF-8 sem BOM como ANSI e exibe mojibake — liga isto no
    # `pgn_tradutor_pro_settings.json` (ROADMAP 13.6).
    "utf8_bom": False,
    # Requebra dos comentarios na gravacao, em colunas (ROADMAP 19, item 13). Zero
    # desliga, que e o comportamento de sempre — comentario em linha unica. 80 e o
    # export format do padrao PGN, o que editora espera receber.
    #
    # Desligado por padrao pelo mesmo motivo do BOM: quem le o PGN gerado neste
    # programa nao ganha nada com a requebra, e ela muda TODA linha de comentario do
    # arquivo — um diff entre a saida de antes e a de depois fica ilegivel. Quem
    # entrega para editora liga.
    "wrap_columns": 0,
}


def read_output_settings(settings):
    """As opcoes de gravacao dos PGN gerados, validadas.

    Pura como `read_main_window_settings`, e pelo mesmo motivo: o arquivo e
    JSON editavel a mao, e um valor de tipo errado cai no padrao em vez de
    virar um comportamento que ninguem consegue explicar.
    """
    guardado = settings.get(OUTPUT_KEY)
    valores = dict(OUTPUT_DEFAULTS)
    if not isinstance(guardado, dict):
        return valores

    bom = guardado.get("utf8_bom")
    if isinstance(bom, bool):
        valores["utf8_bom"] = bom

    colunas = guardado.get("wrap_columns")
    # `bool` e subclasse de `int` em Python: sem a checagem, um `true` no arquivo
    # viraria requebra em 1 coluna — uma palavra por linha, que e o pior arquivo
    # possivel e nao se parece com nada que o usuario pediu. O piso de 20 recusa o
    # mesmo acidente escrito com numero.
    if isinstance(colunas, int) and not isinstance(colunas, bool):
        if colunas == 0 or colunas >= MIN_WRAP_COLUMNS:
            valores["wrap_columns"] = colunas
    return valores


MAIN_WINDOW_KEY = "main_window"

MAIN_WINDOW_DEFAULTS = {
    "source_language": "",
    "target_language": "pt",
    "process_subdirs": True,
    "source_path": "",
    # Tamanho e posicao (ROADMAP 22.12). Vazio quer dizer "nunca foi gravado", e
    # ai a janela maximiza — que e o que ela sempre fez, e o certo para a
    # primeira abertura. Os dois editores ja lembravam a geometria deles; a
    # principal era a unica que nao.
    "geometry": "",
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

    geometria = guardado.get("geometry")
    # Sem validar o FORMATO aqui: quem sabe o que e uma geometria valida (e o que
    # fazer com uma salva num monitor que nao existe mais) e `clamp_geometry`, e
    # duplicar a regra daria duas respostas para a mesma pergunta.
    if isinstance(geometria, str):
        valores["geometry"] = geometria

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
