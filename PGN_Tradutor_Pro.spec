# -*- mode: python ; coding: utf-8 -*-
"""Receita do executavel para Windows.

    python -m PyInstaller PGN_Tradutor_Pro.spec

Sai em `dist/PGN_Tradutor_Pro/`, e a pasta esta COMPLETA — nada precisa ser
copiado para dentro dela depois (ROADMAP 21). Ate a versao anterior era preciso
copiar o `Substituicoes.txt` a mao, e essa instrucao era uma armadilha: um
instalador que a seguisse sobrescreveria o glossario curado do usuario na
primeira atualizacao.

**Dados de usuario nao ficam mais ao lado do `.exe`.** O programa empacotado os
guarda em `%APPDATA%\\PGN Tradutor Pro\\` (ver `tradutor_pgn/app_paths.py`), o
que e o que permite substituir a pasta do programa inteira numa atualizacao sem
tocar em nada que seja dele.

O que vai DENTRO do pacote continua sendo dado de programa: o `spelling.ssp`, o
dicionario-semente, o `Termos-suspeitos.txt` — e agora o glossario INICIAL, uma
copia do `Substituicoes.txt` do projeto que a primeira execucao instala na pasta
de dados quando ainda nao ha nenhum la.
"""

import os
import re
import shutil

# A versao sai do codigo, e nao daqui. Lida por regex e nao por `import` porque o
# `.spec` roda no interpretador do PyInstaller, com o diretorio do projeto fora
# do `sys.path`: importar `tradutor_pgn` aqui funciona por acidente da pasta
# atual, e um dia deixaria de funcionar sem aviso.
VERSAO = re.search(
    r'^__version__ = "([^"]+)"',
    open(os.path.join("tradutor_pgn", "__init__.py"), encoding="utf-8").read(),
    re.MULTILINE,
).group(1)

# O recurso de versao do Windows: e ele que aparece nas propriedades do arquivo,
# e e dele que o instalador le a versao em vez de declarar a sua (ROADMAP 21.6).
# Quatro numeros porque o formato exige quatro; o quarto e sempre zero.
FILEVERS = tuple(int(p) for p in VERSAO.split(".")) + (0,)
VERSION_INFO = os.path.join("build", "version_info.txt")
os.makedirs("build", exist_ok=True)
with open(VERSION_INFO, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={FILEVERS}, prodvers={FILEVERS},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'DarcioAlberico'),
      StringStruct('FileDescription', 'PGN Tradutor Pro'),
      StringStruct('FileVersion', '{VERSAO}'),
      StringStruct('InternalName', 'PGN_Tradutor_Pro'),
      StringStruct('OriginalFilename', 'PGN_Tradutor_Pro.exe'),
      StringStruct('ProductName', 'PGN Tradutor Pro'),
      StringStruct('ProductVersion', '{VERSAO}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
""")
print(f"Versao embutida no executavel: {VERSAO}")

from PyInstaller.utils.hooks import collect_all

# O customtkinter carrega temas (`.json`) e assets em tempo de execucao, entao
# nao basta trazer o modulo: sem os dados a janela abre sem estilo, ou nem abre.
datas, binaries, hiddenimports = collect_all("customtkinter")

# O dicionario do "Normalizar PGN" (~29 MB), embutido para o botao funcionar sem
# preparo nenhum na maquina de destino.
#
# **Este vai para dentro do pacote, e o `Substituicoes.txt` nao** — a diferenca
# nao e de tamanho, e de como cada um e localizado. O glossario sai de
# `sys.argv[0]`, que aponta para o lado do `.exe`; o `spelling.ssp` sai de
# `__file__` (ver `DEFAULT_SPELLING_PATH`), que sob PyInstaller aponta para
# dentro do `_internal`. Cada arquivo vai aonde o programa de fato o procura, e
# isso foi verificado com uma sonda, e nao deduzido.
#
# Ficar em `_internal\spelling_ssp\` nao o torna intocavel: o build e onedir,
# entao o arquivo esta em disco e da para troca-lo por uma versao mais nova das
# classificacoes sem reconstruir nada.
# O dicionario-semente segue a MESMA regra do `spelling.ssp`, e pelo mesmo
# motivo: ele vem com o programa, e localizado por `__file__` (ver
# `_default_seed_path`), e por isso vai para dentro do pacote — ao lado do
# modulo, em `_internal\tradutor_pgn\`. O `Substituicoes.txt` do usuario
# continua fora, ao lado do `.exe`, onde ele pode edita-lo. Sao dois arquivos
# de glossario com donos diferentes, e mantê-los em pastas diferentes e o que
# impede a atualizacao do programa de tocar o trabalho de quem usa.
# O glossario INICIAL: uma copia do `Substituicoes.txt` do projeto, embutida com
# outro nome. O nome diferente nao e capricho — dentro do pacote ele e dado de
# programa, e um arquivo chamado `Substituicoes.txt` la dentro seria confundido
# com o do usuario justamente por quem estivesse procurando onde o dele foi
# parar. A primeira execucao o copia para a pasta de dados, e so quando nao ha
# glossario nenhum (ver `tradutor_pgn/first_run.py`).
#
# A copia sai para `build/`, e nao para dentro de `tradutor_pgn/`: gerar arquivo
# na arvore de fontes durante o build suja o `git status` e, mais cedo ou mais
# tarde, alguem commita a copia.
GLOSSARIO = "Substituicoes.txt"
if os.path.exists(GLOSSARIO):
    os.makedirs("build", exist_ok=True)
    INICIAL = os.path.join("build", "Substituicoes-inicial.txt")
    shutil.copyfile(GLOSSARIO, INICIAL)
    datas += [(INICIAL, "tradutor_pgn")]
else:
    print(
        "AVISO: Substituicoes.txt nao encontrado; o executavel sai sem glossario "
        "inicial e a primeira execucao abre sem regras (garantia S5)."
    )

# TODO `.txt` que mora ao lado do modulo, por varredura e nao por lista.
#
# A lista escrita a mao falhou: o `Termos-suspeitos.txt` entrou no programa na
# secao 16 e ninguem lembrou de acrescenta-lo aqui. No empacotado ele
# simplesmente nao existia, e `load_suspect_terms` devolve vazio **em silencio**
# quando o arquivo falta — o executavel perdia a heuristica de terminologia da
# garantia Q1 sem uma linha de aviso, e so um build examinado arquivo a arquivo
# mostraria isso.
#
# A varredura tem a propriedade que a lista nao tinha: acrescentar um dado de
# programa ao pacote passa a ser copiar o arquivo para `tradutor_pgn/`, e nao
# lembrar de dois lugares.
DADOS_DO_MODULO = sorted(
    os.path.join("tradutor_pgn", nome)
    for nome in os.listdir("tradutor_pgn")
    if nome.lower().endswith(".txt")
)
if DADOS_DO_MODULO:
    datas += [(caminho, "tradutor_pgn") for caminho in DADOS_DO_MODULO]
    print("Dados do modulo embutidos: " + ", ".join(
        os.path.basename(c) for c in DADOS_DO_MODULO
    ))
else:
    print(
        "AVISO: nenhum .txt em tradutor_pgn/; o executavel sai sem a terminologia "
        "embutida e sem a lista de termos suspeitos."
    )

SPELLING = os.path.join("spelling_ssp", "spelling.ssp")
if os.path.exists(SPELLING):
    datas += [(SPELLING, "spelling_ssp")]
else:
    # Nao aborta: o resto do programa nao depende do dicionario, e quem quiser
    # empacotar sem ele (ou tiver apagado os 30 MB da pasta) continua conseguindo
    # gerar o executavel. O aviso existe para que a ausencia seja uma decisao
    # vista, e nao um botao que falha na maquina do usuario final.
    #
    # A versao anterior deste comentario dizia que o `spelling.ssp` nao e
    # versionado, e ele **e** — esta no repositorio desde o commit que o
    # acrescentou, e um clone limpo o tem.
    print(
        f"AVISO: {SPELLING} nao encontrado. O executavel sai sem o dicionario, "
        'e o botao "Normalizar PGN" vai falhar dizendo que o arquivo nao existe.'
    )

# O unico import condicional do programa (`try: import chardet`, em pgn_utils).
# A analise estatica o encontra; fica declarado porque o modo de falha e
# silencioso — sem `chardet` a deteccao de codificacao cai para os ramos de
# fallback e continua correta (garantia E4), so que pior.
hiddenimports += ["chardet"]

# Excluidos por medicao, e nao por palpite: nenhum dos dois e carregado ao
# importar o programa, e juntos custavam 36 dos 85 MB do primeiro build. Eles
# entram como dependencias **opcionais** de quem o programa usa de verdade —
# numpy pelo PIL, cryptography pelo urllib3 — e as duas funcionam sem eles. O
# PIL fica: o customtkinter o importa na carga.
excludes = ["numpy", "cryptography"]


a = Analysis(
    ["PGN_Tradutor_Pro.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PGN_Tradutor_Pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX desligado. Ele reduz o pacote comprimindo os binarios e
    # descomprimindo na carga, e o preco e alto para o que economiza: antivirus
    # tratam executavel empacotado como suspeito, e um falso positivo num
    # programa distribuido por copia de pasta e pior do que 20 MB a mais.
    upx=False,
    # Sem console: e o mesmo ambiente do `pythonw` para o qual o programa foi
    # escrito. Por isso as falhas de carga do glossario vao para um dialogo
    # (garantia S5) e as excecoes de callback tem um relator proprio (C3) — um
    # `print` aqui nao apareceria em lugar nenhum.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # O recurso de versao gerado acima. Sem ele o `.exe` sai sem versao nenhuma
    # nas propriedades, e o instalador nao teria de onde ler a dele.
    version=VERSION_INFO,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PGN_Tradutor_Pro",
)
