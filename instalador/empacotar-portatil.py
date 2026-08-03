# -*- coding: utf-8 -*-
"""Monta a entrega PORTATIL a partir do que o PyInstaller ja construiu.

    1. python -m PyInstaller PGN_Tradutor_Pro.spec
    2. python instalador/empacotar-portatil.py

Sai em `instalador/saida/PGN-Tradutor-Pro-<versao>-portatil.zip`.

**E o mesmo executavel da versao instalavel.** A diferenca inteira entre as duas
entregas e um arquivo de zero conteudo ao lado do `.exe`: o `portatil.txt` que
`app_paths.running_portable()` procura. Dois builds separados seriam duas coisas
para construir, testar e manter em dia por causa de uma linha de comportamento
(ROADMAP 27).

**O marcador nao entra em `dist/`**, e isso e o ponto: o `.iss` empacota
`dist\\*` inteiro com `recursesubdirs`, entao um `portatil.txt` esquecido la
viajaria para dentro do INSTALADOR e faria a versao instalada gravar o acervo
dentro de `Program Files` — exatamente o defeito que a secao 21 consertou. Aqui
ele e escrito direto no zip, e o disco nunca o ve.
"""
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from tradutor_pgn import __version__  # noqa: E402
from tradutor_pgn.app_paths import PORTABLE_DATA_FOLDER, PORTABLE_MARKER  # noqa: E402

DIST = os.path.join(RAIZ, "dist", "PGN_Tradutor_Pro")
SAIDA = os.path.join(RAIZ, "instalador", "saida")
NOME = f"PGN-Tradutor-Pro-{__version__}-portatil"

LEIAME = f"""PGN Tradutor Pro {__version__} — versao portatil
=================================================

Descompacte a pasta onde quiser (pendrive, disco externo, rede) e rode
PGN_Tradutor_Pro.exe. Nao ha instalacao e nao ha nada gravado no registro.

ONDE FICAM OS SEUS DADOS
------------------------
Nesta versao, dentro da propria pasta, em "{PORTABLE_DATA_FOLDER}\\":

    {PORTABLE_DATA_FOLDER}\\traducoes.db          o banco de traducoes
    {PORTABLE_DATA_FOLDER}\\Substituicoes.txt     o seu glossario
    {PORTABLE_DATA_FOLDER}\\backups\\              copias do glossario e do banco
    {PORTABLE_DATA_FOLDER}\\logs\\                 os registros de cada execucao

Copiar esta pasta inteira leva junto o programa E o seu acervo.

O que decide isso e o arquivo "{PORTABLE_MARKER}", aqui do lado do executavel.
APAGAR ESSE ARQUIVO faz o programa passar a gravar em
%APPDATA%\\PGN Tradutor Pro\\, que e o comportamento da versao instalada. Os
dados que ja estiverem em "{PORTABLE_DATA_FOLDER}\\" continuam la, intactos, mas
o programa deixa de olhar para eles.

ATUALIZAR
---------
Descompacte a versao nova numa pasta NOVA e copie para dentro dela a pasta
"{PORTABLE_DATA_FOLDER}\\" da versao antiga. O programa nunca sobrescreve o que
ja existe la.

APONTAR PARA OUTRO LUGAR
------------------------
A variavel de ambiente PGN_TRADUTOR_DATA vence tudo, inclusive esta versao:

    set PGN_TRADUTOR_DATA=D:\\meu-acervo
    PGN_Tradutor_Pro.exe

E o jeito de rodar o programa do pendrive sobre o acervo que esta no disco.
"""


def main():
    if not os.path.isdir(DIST):
        print(f"ERRO: {DIST} nao existe. Rode o PyInstaller antes:")
        print("    python -m PyInstaller PGN_Tradutor_Pro.spec")
        return 1

    solto = os.path.join(DIST, PORTABLE_MARKER)
    if os.path.exists(solto):
        print(f"ERRO: existe um {PORTABLE_MARKER} dentro de dist/.")
        print("     O instalador empacota dist/ inteiro e levaria o marcador")
        print("     junto, fazendo a versao INSTALADA gravar dentro de")
        print("     Program Files. Apague-o e rode de novo.")
        return 1

    os.makedirs(SAIDA, exist_ok=True)
    destino = os.path.join(SAIDA, NOME + ".zip")

    arquivos = 0
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for raiz, _dirs, nomes in os.walk(DIST):
            for nome in nomes:
                caminho = os.path.join(raiz, nome)
                dentro = os.path.join(NOME, os.path.relpath(caminho, DIST))
                z.write(caminho, dentro)
                arquivos += 1
        # O marcador e o LEIAME nascem AQUI, e nao em disco. Ver o docstring.
        z.writestr(
            os.path.join(NOME, PORTABLE_MARKER),
            "Este arquivo faz o programa gravar os dados na propria pasta.\r\n"
            "Ver LEIA-ME-PORTATIL.txt.\r\n",
        )
        z.writestr(os.path.join(NOME, "LEIA-ME-PORTATIL.txt"), LEIAME)
        arquivos += 2

    tamanho = os.path.getsize(destino)
    print(f"gravado: {destino}")
    print(f"{arquivos} arquivos, {tamanho / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
