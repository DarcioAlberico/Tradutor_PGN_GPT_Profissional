import json
import os
import sys
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


# ============================================================================
# Canal de aviso das configuracoes (garantia M3)
#
# `load_settings` acima e tolerante de proposito: quem LE degrada para `{}`,
# porque uma janela que nao abre e pior do que uma janela sem preferencias. A
# GRAVACAO nao pode ter a mesma tolerancia — e o que este canal e a funcao
# `_read_settings_for_update` separam. Como o canal do glossario (S5), este
# modulo nao importa Tk: quem registra o handler decide como mostrar.
# ============================================================================

_settings_warning_handler = None


def set_settings_warning_handler(handler):
    """Registra quem exibe os avisos de gravacao. Devolve o handler anterior."""
    global _settings_warning_handler
    previous = _settings_warning_handler
    _settings_warning_handler = handler
    return previous


def _warn(message):
    """Publica um aviso. Nunca levanta: o chamador ja esta num caminho de erro."""
    if _settings_warning_handler is None:
        if sys.stdout is not None:
            try:
                print(f"[CONFIGURACOES] {message}")
            except Exception:  # pragma: no cover - stdout fechado
                pass
        return
    try:
        _settings_warning_handler(message)
    except Exception:  # pragma: no cover - defensivo
        pass


def _read_settings_for_update(path):
    """A leitura ESTRITA que antecede uma gravacao (garantia M3).

    `update_settings` lia com `load_settings`, que devolve `{}` para qualquer
    erro — inclusive um `PermissionError` de um antivirus tocando o arquivo por
    uma fracao de segundo. A gravacao seguinte escrevia por cima um arquivo so
    com a chave que estava mudando: rascunhos (R4), lista de falhas (T4) e
    preferencias (M1) sumiam de vez, sem aviso. Reproduzido com a funcao real
    (ROADMAP 28.1).

    Tres desfechos, e nenhum deles e "fingir que o arquivo nao existe":

    - nao existe: `{}`, e a gravacao cria o arquivo;
    - existe e nao da para ler (`OSError`): o aviso sai e o `OSError` sobe —
      todos os chamadores ja o tratam, e desistir de UMA gravacao e barato;
    - existe e nao e JSON (ou nao e um objeto): e renomeado para
      `.corrompido-<data>` ao lado, o aviso diz onde ficou, e a gravacao segue
      com `{}`. Renomear preserva o que der para recuperar a mao; seguir e o
      que impede o programa de ficar sem gravar preferencia nenhuma ate alguem
      consertar o arquivo.
    """
    # Em bytes, e nao em texto: um byte invalido no meio do arquivo e
    # "corrompido" (o ramo de baixo), e nao "ilegivel" — decodificar aqui o
    # confundiria com o `OSError`.
    try:
        with open(path, "rb") as file:
            raw = file.read()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _warn(
            f"Nao foi possivel ler {path} ({exc}); esta gravacao foi "
            f"descartada para nao apagar o que o arquivo ja tem."
        )
        raise

    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        data = None

    if isinstance(data, dict):
        return data

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = f"{path}.corrompido-{stamp}"
    try:
        os.replace(path, aside)
    except OSError as exc:
        _warn(
            f"{path} esta corrompido e nao pode ser renomeado ({exc}); esta "
            f"gravacao foi descartada."
        )
        raise
    _warn(
        f"{path} estava corrompido e foi renomeado para {aside}; as "
        f"configuracoes recomecam vazias. O que der para recuperar esta la."
    )
    return {}


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
    if path is None:
        path = default_settings_path()

    with _UPDATE_LOCK:
        # A leitura estrita, e nao `load_settings`: aqui `{}` por engano vira
        # um arquivo novo por cima do velho (garantia M3).
        settings = _read_settings_for_update(path)
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

# Os motores que o dialogo do "Iniciar tradução" oferece (ROADMAP 28.7).
# "google" e o de sempre; os outros sao os ids de `llm_providers.PROVIDERS`,
# escritos aqui tambem para o arquivo validar sem importar a camada de rede.
TRANSLATION_PROVIDER_GOOGLE = "google"
TRANSLATION_PROVIDER_IDS = (TRANSLATION_PROVIDER_GOOGLE, "anthropic", "openai", "deepseek")

MAIN_WINDOW_DEFAULTS = {
    "source_language": "",
    "target_language": "pt",
    "process_subdirs": True,
    "source_path": "",
    # O motor escolhido no ultimo "Iniciar tradução" — o que o dialogo oferece
    # pre-selecionado na proxima vez. Nunca decide sozinho: sem chave para ele,
    # o dialogo cai no Google e diz por que (garantia M1, ROADMAP 28.7).
    "translation_provider": TRANSLATION_PROVIDER_GOOGLE,
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

    motor = guardado.get("translation_provider")
    if isinstance(motor, str) and motor in TRANSLATION_PROVIDER_IDS:
        valores["translation_provider"] = motor

    return valores


def write_settings_sections(sections, path=None):
    """Grava `{secao: {chave: valor}}` relendo o disco antes (garantia R4).

    As janelas de edicao guardam rascunhos no MESMO arquivo. Gravar o snapshot
    inteiro daqui apagaria o que elas escreveram desde que este processo abriu —
    que e exatamente o defeito que R4 existe para impedir. Varias secoes numa
    chamada so porque a tela de Configuracoes grava duas de uma vez, e duas
    releituras seriam duas escritas para um clique.
    """
    def mutator(settings):
        gravadas = {}
        for key, values in sections.items():
            guardado = settings.get(key)
            if not isinstance(guardado, dict):
                guardado = {}
                settings[key] = guardado
            guardado.update(values)
            gravadas[key] = guardado
        return gravadas

    return update_settings(mutator, path)


def write_main_window_settings(values, path=None):
    """As escolhas da janela principal, pela mesma porta (R4)."""
    gravadas = write_settings_sections({MAIN_WINDOW_KEY: values}, path)
    return gravadas[MAIN_WINDOW_KEY] if gravadas else gravadas


APPEARANCE_KEY = "appearance"

# Os tres valores que a tela oferece, e os nomes que o CustomTkinter entende.
# "system" e o comportamento de sempre: o programa nasceu em
# `set_appearance_mode("System")` e segue o Windows.
APPEARANCE_THEMES = ("system", "light", "dark")
CTK_APPEARANCE_MODES = {"system": "System", "light": "Light", "dark": "Dark"}

APPEARANCE_DEFAULTS = {
    "theme": "system",
}


def read_appearance_settings(settings):
    """O tema escolhido, validado: qualquer coisa fora dos tres cai em "system"."""
    guardado = settings.get(APPEARANCE_KEY)
    valores = dict(APPEARANCE_DEFAULTS)
    if not isinstance(guardado, dict):
        return valores
    tema = guardado.get("theme")
    if isinstance(tema, str) and tema in APPEARANCE_THEMES:
        valores["theme"] = tema
    return valores


def appearance_mode_from_settings(settings):
    """O argumento de `ctk.set_appearance_mode` para o que esta gravado."""
    return CTK_APPEARANCE_MODES[read_appearance_settings(settings)["theme"]]


BOARD_KEY = "board"

BOARD_DEFAULTS = {
    # Calcular a posicao (FEN) de cada comentario na vez do arquivo (ROADMAP
    # 28.8). Ligado por padrao: custa ~2 s por 800 KB de PGN e so acontece
    # quando o `python-chess` esta instalado; sem ele o worker avisa uma vez
    # por execucao e segue, e desligar aqui cala o aviso.
    "fen": True,
}


def read_board_settings(settings):
    guardado = settings.get(BOARD_KEY)
    valores = dict(BOARD_DEFAULTS)
    if isinstance(guardado, dict) and isinstance(guardado.get("fen"), bool):
        valores["fen"] = guardado["fen"]
    return valores


LLM_KEY = "llm"

# O modelo de cada provedor de linguagem (ROADMAP 28.7). Os nomes sao os que
# cada API aceita; o campo e livre porque os provedores trocam de modelo mais
# depressa do que este programa lanca versao — quem acompanha o nome e o
# usuario, e a tela diz onde conferir. As chaves NAO ficam aqui: vivem em
# `api_keys` (arquivo proprio, cifrado), e a tela as trata como campo a parte.
LLM_DEFAULTS = {
    "anthropic_model": "claude-opus-5",
    "openai_model": "gpt-5",
    "deepseek_model": "deepseek-chat",
}


def read_llm_settings(settings):
    """Os modelos gravados; um campo vazio ou de outro tipo volta ao padrao."""
    guardado = settings.get(LLM_KEY)
    valores = dict(LLM_DEFAULTS)
    if not isinstance(guardado, dict):
        return valores
    for chave in LLM_DEFAULTS:
        modelo = guardado.get(chave)
        if isinstance(modelo, str) and modelo.strip():
            valores[chave] = modelo.strip()
    return valores


# As opcoes que o USUARIO escolhe, por secao — e so elas. `main_window` e
# `editor_drafts` tambem vivem no arquivo, mas sao estado que a janela grava
# sozinha (o ultimo idioma, a geometria, um rascunho), nao uma escolha que se
# faz numa tela. A tela de Configuracoes e conferida contra isto (garantia M4):
# toda chave daqui tem um controle la, e um teste enumera.
USER_OPTION_SECTIONS = {
    OUTPUT_KEY: OUTPUT_DEFAULTS,
    APPEARANCE_KEY: APPEARANCE_DEFAULTS,
    BOARD_KEY: BOARD_DEFAULTS,
    LLM_KEY: LLM_DEFAULTS,
}


def parse_wrap_columns(text):
    """O que o usuario digitou no campo da requebra -> `(valor, erro)`.

    Vazio e `0` desligam. Um inteiro de `MIN_WRAP_COLUMNS` para cima e a
    largura. O resto volta com a razao, para o campo dizer e nao gravar: a
    regra e a mesma que `read_output_settings` aplica ao JSON editado a mao,
    escrita uma vez so — o piso mora em `MIN_WRAP_COLUMNS` para as duas.
    """
    digitado = (text or "").strip()
    if not digitado:
        return 0, None
    try:
        valor = int(digitado)
    except ValueError:
        return None, "Digite um número inteiro de colunas, ou 0 para desligar."
    if valor < 0:
        return None, "A largura não pode ser negativa; 0 desliga a requebra."
    if 0 < valor < MIN_WRAP_COLUMNS:
        return None, (
            f"O mínimo é {MIN_WRAP_COLUMNS} colunas; abaixo disso o PGN vira "
            f"uma palavra por linha. Use 0 para desligar."
        )
    return valor, None
