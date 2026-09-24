# -*- coding: utf-8 -*-
"""Monta a entrega PORTATIL a partir do que o PyInstaller ja construiu.

    python instalador/gerar-entregas.py     # que chama este, depois do PyInstaller

Sai em `instalador/saida/PGN-Tradutor-Pro-<versao>-portatil.zip`. Antes de
escrever uma linha, confere que a pasta do programa so tem o `.exe` e o
`_internal` (ver `PASTA_DO_PROGRAMA`).

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

# O que a pasta do programa pode ter — e SO isto (garantia I11). O instalador e
# este zip levam `dist/PGN_Tradutor_Pro/` inteira, entao qualquer outra coisa
# ali viajaria junto: um `portatil.txt` faria a versao INSTALADA gravar dentro
# de `Program Files`, e uma `chaves-api.json`, um banco, um glossario ou uma
# pasta `dados/` entregariam as chaves de API e o acervo de quem construiu. As
# chaves sao de cada usuario, que grava a sua em Configuracoes. Uma lista do
# que PODE, e nao do que nao pode: um arquivo de dados que o programa ganhar
# amanha fica de fora sem ninguem lembrar de acrescenta-lo aqui.
PASTA_DO_PROGRAMA = {"PGN_Tradutor_Pro.exe", "_internal"}

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

CHAVES DE API (CLAUDE, CHATGPT, DEEPSEEK)
-----------------------------------------
O programa nao vem com chave nenhuma, e sem chave ele traduz pelo Google.
Para usar um modelo de linguagem, cada usuario grava a PROPRIA chave em
Configuracoes. Ela fica em "{PORTABLE_DATA_FOLDER}\\chaves-api.json", cifrada para a
conta do Windows de quem a gravou: levada para outra maquina ou outra conta,
ela nao abre, e o programa pede a chave de novo.

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


def sobras_na_pasta_do_programa(pasta=None):
    """O que a pasta do programa tem alem do `.exe` e do `_internal`."""
    return sorted(set(os.listdir(pasta or DIST)) - PASTA_DO_PROGRAMA)


def main():
    if not os.path.isdir(DIST):
        print(f"ERRO: {DIST} nao existe. Gere o executavel antes:")
        print("    python instalador/gerar-entregas.py --so-exe")
        return 1

    sobras = sobras_na_pasta_do_programa()
    if sobras:
        print(f"ERRO: {DIST} tem o que nao e do programa: {', '.join(sobras)}.")
        print("     O instalador e este zip levam a pasta inteira. Um")
        print(f"     {PORTABLE_MARKER} faria a versao INSTALADA gravar dentro de")
        print("     Program Files, e chaves de API, bancos ou uma pasta dados/")
        print("     iriam para quem recebe. Gere de novo, que o PyInstaller")
        print("     recria a pasta do zero: python instalador/gerar-entregas.py")
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
