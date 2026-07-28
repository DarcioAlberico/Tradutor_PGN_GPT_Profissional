# -*- mode: python ; coding: utf-8 -*-
"""Receita do executavel para Windows.

    python -m PyInstaller PGN_Tradutor_Pro.spec

Sai em `dist/PGN_Tradutor_Pro/`. O que precisa ficar ao lado do `.exe` para o
programa funcionar esta no README, secao "Executavel" — em resumo, o
`Substituicoes.txt`. Ele **nao** e embutido de proposito: o glossario e editavel
pelo usuario e o programa grava backups ao lado dele, enquanto o conteudo
embutido pelo PyInstaller e descartavel (em `--onefile` ele vive numa pasta
temporaria que o Windows apaga). Dado de usuario mora junto do executavel; dado
de programa vai embutido.

Isso funciona porque `_default_substitutions_path()` deriva tudo de
`dirname(abspath(sys.argv[0]))`, e sob PyInstaller `sys.argv[0]` e o caminho do
proprio `.exe`, e nao a pasta de extracao. Verificado com uma sonda antes de
empacotar. Se algum dia deixar de valer, o sintoma e o programa abrir com o
glossario vazio e gravar os dados do usuario numa pasta temporaria.
"""

from PyInstaller.utils.hooks import collect_all

# O customtkinter carrega temas (`.json`) e assets em tempo de execucao, entao
# nao basta trazer o modulo: sem os dados a janela abre sem estilo, ou nem abre.
datas, binaries, hiddenimports = collect_all("customtkinter")

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
