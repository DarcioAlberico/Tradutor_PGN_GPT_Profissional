"""Onde ficam os dados do usuario — e por que nao e sempre a mesma pasta.

O programa sempre guardou tudo ao lado de `sys.argv[0]`: glossario, banco,
`backups/`, `logs/` e as configuracoes. Isso funciona rodando do fonte e falha
como instalador: atualizar significa trocar os arquivos do programa, e trocar
uma pasta que tem 350 MB de dados do usuario dentro e como se perde o trabalho
de meses (ROADMAP 21).

**Quem decide e como o programa foi iniciado:**

- **empacotado** (o `.exe` do PyInstaller): `%APPDATA%\\PGN Tradutor Pro\\`. A
  pasta do programa fica so com o programa, e o instalador pode substitui-la
  inteira sem tocar em nada que seja do usuario;
- **do fonte** (`python PGN_Tradutor_Pro.py`): ao lado do script, exatamente
  como sempre foi. O checkout continua sendo o ambiente de desenvolvimento, com
  os dados de desenvolvimento;
- **`PGN_TRADUTOR_DATA`** vence os dois. E a saida para um pendrive, para um
  teste, e para o caso de querer que o checkout leia o acervo de verdade.

A regra dos dois modos e o que permite ter o app instalado e o repositorio na
mesma maquina **sem que um veja os dados do outro**. Rodar a suite de testes nao
alcanca o acervo do usuario porque a suite roda do fonte; o `.exe` nao alcanca o
banco de desenvolvimento pelo mesmo motivo, invertido.

O que vem COM o programa continua saindo de `__file__`, e nao daqui: o
dicionario-semente, o `Termos-suspeitos.txt` e o `spelling.ssp` sao dados de
programa, viajam dentro do pacote e sao substituidos por uma atualizacao — que e
justamente o que **nao** pode acontecer com o que esta aqui.
"""

import os
import sys


# A variavel de ambiente que vence tudo. Nome com prefixo do programa de
# proposito: uma variavel chamada `DATA_DIR` seria roubada por qualquer outro
# programa da mesma maquina.
DATA_DIR_ENV = "PGN_TRADUTOR_DATA"

# O nome da pasta dentro do `%APPDATA%`. Com espacos e maiusculas porque e um
# nome que o usuario ve no Explorer, e nao um identificador.
APP_DATA_FOLDER = "PGN Tradutor Pro"


def running_frozen():
    """O programa esta rodando empacotado (PyInstaller)?

    `sys.frozen` e o que o proprio PyInstaller define, e e a unica pergunta
    confiavel: o nome do executavel nao serve (o `.exe` pode ser renomeado) e
    `sys.argv[0]` tampouco (ele muda com o jeito de invocar).
    """
    return bool(getattr(sys, "frozen", False))


def _roaming_dir():
    """`%APPDATA%`, ou o equivalente quando a variavel nao existe.

    O fallback nao e paranoia: `%APPDATA%` some em servicos, em contas de
    sistema e em ambientes de build. Sem ele, o programa empacotado escolheria
    o diretorio atual — que e a pasta do `.exe` — e desfaria em silencio a
    separacao que este modulo existe para garantir.
    """
    roaming = os.environ.get("APPDATA")
    if roaming:
        return roaming
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def program_dir():
    """A pasta do programa: onde o `.exe` (ou o script) esta.

    E o lugar dos dados no modo fonte, e o lugar de NADA do usuario no modo
    empacotado. Ela continua sendo consultada na migracao da primeira execucao,
    que procura ali os arquivos de uma instalacao anterior.
    """
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def data_dir():
    """A pasta dos dados do usuario. Nao cria nada — ver `ensure_data_dir`.

    Ordem: a variavel de ambiente, depois o modo (empacotado ou fonte). Um valor
    vazio na variavel e tratado como ausente, e nao como "a pasta atual": um
    `set PGN_TRADUTOR_DATA=` sem valor e o jeito natural de desligar a variavel,
    e interpreta-lo como caminho gravaria o acervo no diretorio de trabalho de
    quem chamou.
    """
    escolhida = os.environ.get(DATA_DIR_ENV, "").strip()
    if escolhida:
        return os.path.abspath(os.path.expanduser(escolhida))

    if running_frozen():
        return os.path.join(_roaming_dir(), APP_DATA_FOLDER)

    return program_dir()


def data_path(*partes):
    """Caminho de um arquivo dentro da pasta de dados."""
    return os.path.join(data_dir(), *partes)


def ensure_data_dir():
    """Garante que a pasta de dados existe, e devolve o caminho dela.

    Separada de `data_dir` porque perguntar onde os dados ficam nao pode ter o
    efeito colateral de criar pasta: metade das chamadas e para LER, inclusive
    a que decide se ha algo a migrar.
    """
    caminho = data_dir()
    os.makedirs(caminho, exist_ok=True)
    return caminho
