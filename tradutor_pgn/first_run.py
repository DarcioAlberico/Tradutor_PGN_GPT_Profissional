"""A primeira execucao depois de instalar: de onde vem o glossario inicial.

Separado de `app_paths` de proposito: perguntar onde os dados ficam e uma
funcao pura, e isto aqui COPIA ARQUIVO. Misturar as duas faria toda consulta de
caminho carregar o risco de escrever em disco.

Duas situacoes, e a diferenca entre elas e o que este modulo resolve:

- **quem ja usava o programa** distribuido como pasta (o formato anterior ao
  instalador) tem os dados ao lado do `.exe`. Eles sao COPIADOS para a pasta de
  dados — copiados, e nao movidos, para que voltar a versao antiga continue
  encontrando o que ela espera;
- **quem instalou agora** nao tem nada. O glossario inicial vem de dentro do
  pacote, que e onde o instalador o poe.

**Nada e sobrescrito, em hipotese nenhuma.** Um arquivo que ja existe na pasta
de dados e do usuario, e a regra que governa este modulo inteiro e que uma
atualizacao nunca pode passar por cima do trabalho dele (ROADMAP 21). Por isso a
condicao e sempre "o destino nao existe", e nao "a origem e mais nova": data de
arquivo nao diz quem tem razao.
"""

import os
import shutil

from . import app_paths
from .app_paths import data_dir, ensure_data_dir, program_dir


# O glossario que vai DENTRO do pacote, ao lado do modulo — a mesma regra do
# dicionario-semente e do `Termos-suspeitos.txt`: dado de programa sai de
# `__file__`. Ele e a semente da primeira execucao, e nao o glossario do
# usuario; depois de copiado, quem manda e a copia na pasta de dados.
INITIAL_GLOSSARY_FILENAME = "Substituicoes-inicial.txt"

# O que e do usuario e viaja de uma instalacao anterior. `backups/` e `logs/`
# ficam de fora de proposito: sao centenas de MB, e copia-los faria a primeira
# abertura depois de instalar parecer travada. Eles continuam onde estao, e a
# migracao diz isso no log.
USER_FILES = (
    "Substituicoes.txt",
    "glossario.db",
    "traducoes.db",
    "pgn_tradutor_pro_settings.json",
)


def packaged_glossary_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), INITIAL_GLOSSARY_FILENAME
    )


def _copiar_se_faltar(origem, destino):
    """Copia so quando o destino nao existe. Devolve `True` se copiou."""
    if not os.path.exists(origem) or os.path.exists(destino):
        return False
    shutil.copy2(origem, destino)
    return True


def prepare_data_dir(log_message=None):
    """Garante a pasta de dados e o que ela precisa ter na primeira execucao.

    Devolve a lista do que foi copiado (nomes de arquivo), vazia quando nao
    havia o que fazer — que e o caso de toda execucao depois da primeira.

    Roda sempre, e nao so quando "parece" ser a primeira vez: a unica condicao
    que interessa e arquivo a arquivo, e um usuario que apagou o glossario para
    recomecar ganha o inicial de volta em vez de abrir o programa sem regras.
    """
    destino = ensure_data_dir()
    origem = program_dir()
    copiados = []

    # Uma instalacao anterior, com os dados ao lado do executavel. Nao acontece
    # quando os dois caminhos coincidem — que e o modo fonte, em que a pasta de
    # dados JA E a do programa e nao ha nada a migrar.
    if os.path.abspath(origem) != os.path.abspath(destino):
        for nome in USER_FILES:
            if _copiar_se_faltar(os.path.join(origem, nome), os.path.join(destino, nome)):
                copiados.append(nome)

        if copiados and log_message:
            log_message(
                f"Dados da instalacao anterior copiados para {destino}: "
                f"{', '.join(copiados)}."
            )
            for pasta in ("backups", "logs"):
                if os.path.isdir(os.path.join(origem, pasta)):
                    log_message(
                        f"  - A pasta '{pasta}' NAO foi copiada (pode ter centenas "
                        f"de MB) e continua em {origem}."
                    )

    # Sem glossario nenhum: o que vem no pacote. Depois desta copia ele e do
    # usuario, e nunca mais e tocado.
    glossario_do_usuario = os.path.join(destino, "Substituicoes.txt")
    if _copiar_se_faltar(packaged_glossary_path(), glossario_do_usuario):
        copiados.append("Substituicoes.txt")
        if log_message:
            log_message(f"Glossario inicial instalado em {glossario_do_usuario}.")

    return copiados


def describe_data_dir():
    """Uma linha dizendo onde os dados estao. Vai para o log na abertura.

    Existe porque a pasta passou a depender de como o programa foi iniciado, e
    uma pergunta que o usuario nao consegue responder olhando a tela ("onde esta
    meu glossario?") vira chamado de suporte.

    O modo e dito junto com a pasta. Sao tres, e o caminho sozinho nao distingue
    dois deles: um `.exe` portatil e um `.exe` instalado apontado por
    `PGN_TRADUTOR_DATA` podem gravar na MESMA pasta por motivos diferentes, e
    saber qual dos dois esta valendo e o que explica o que uma atualizacao vai
    fazer com aquele acervo (ROADMAP 27).
    """
    if os.environ.get(app_paths.DATA_DIR_ENV, "").strip():
        modo = f"por {app_paths.DATA_DIR_ENV}"
    elif app_paths.running_portable():
        modo = "portatil"
    elif app_paths.running_frozen():
        modo = "instalado"
    else:
        modo = "do fonte"
    return f"Pasta de dados ({modo}): {data_dir()}"
