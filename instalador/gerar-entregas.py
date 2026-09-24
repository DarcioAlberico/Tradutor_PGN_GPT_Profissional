# -*- coding: utf-8 -*-
"""Gera as entregas do Windows num comando so.

    python instalador/gerar-entregas.py            # executavel, instalador e portatil
    python instalador/gerar-entregas.py --so-exe   # so o dist/ do PyInstaller

Tres passos, nesta ordem, parando no primeiro que falhar:

1. **O executavel**, pelo PyInstaller, num ambiente SO de execucao em
   `build/venv-exe`, montado do `uv.lock` com `--no-dev --extra llm`. O
   ambiente separado e a razao deste roteiro existir: o PyInstaller leva tudo o
   que o interpretador tiver e a analise alcancar. Construido do `.venv` de
   desenvolvimento o pacote levava o mypy e o pygments (86 MB contra 80 MB);
   construido de um Python global, qualquer coisa; e sem `--extra llm` saia sem
   o motor Claude, em silencio. A variavel `UV_PROJECT_ENVIRONMENT` vale so para
   o processo filho — no PowerShell, defini-la na sessao faria o `uv run` dos
   testes cair depois nesse ambiente sem pytest.
2. **O instalador**, pelo Inno Setup (`instalador/PGN_Tradutor_Pro.iss`).
3. **O zip portatil**, pelo `instalador/empacotar-portatil.py`.

Tudo sai em `instalador/saida/`. So usa a biblioteca padrao: roda com qualquer
Python 3, e o `uv` tem de estar no PATH.
"""
import os
import shutil
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMBIENTE = os.path.join(RAIZ, "build", "venv-exe")
SAIDA = os.path.join(RAIZ, "instalador", "saida")
EXE = os.path.join(RAIZ, "dist", "PGN_Tradutor_Pro", "PGN_Tradutor_Pro.exe")


def _iscc():
    """O compilador do Inno Setup, onde ele costuma estar.

    Instalado "so para mim", o Inno Setup 6 fica em `%LOCALAPPDATA%\\Programs` —
    e o caso desta maquina de desenvolvimento, e procurar so no PATH e em
    `Program Files` dizia que ele nao existia.
    """
    candidatos = [shutil.which("ISCC.exe") or ""]
    for base in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
        pasta = os.environ.get(base)
        if pasta:
            sub = ("Programs", "Inno Setup 6") if base == "LOCALAPPDATA" else ("Inno Setup 6",)
            candidatos.append(os.path.join(pasta, *sub, "ISCC.exe"))
    return next((c for c in candidatos if c and os.path.isfile(c)), None)


def _rodar(passo, comando, env=None):
    print(f"\n=== {passo} ===\n> {' '.join(comando)}", flush=True)
    resultado = subprocess.run(comando, cwd=RAIZ, env=env)
    if resultado.returncode != 0:
        raise SystemExit(f"\nFALHOU em: {passo} (codigo {resultado.returncode})")


def main(argv):
    inicio = time.time()
    uv = shutil.which("uv")
    if not uv:
        print("ERRO: `uv` nao esta no PATH (https://docs.astral.sh/uv/).")
        return 1

    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=AMBIENTE)
    # Um `.venv` ativado deixa o VIRTUAL_ENV apontando para ele, e o uv avisa
    # que vai ignora-lo. Tirar a variavel so tira o aviso.
    env.pop("VIRTUAL_ENV", None)
    _rodar(
        "executavel (PyInstaller)",
        [uv, "run", "--locked", "--no-dev", "--extra", "llm", "--with", "pyinstaller",
         "python", "-m", "PyInstaller", "--noconfirm", "--clean", "PGN_Tradutor_Pro.spec"],
        env=env,
    )
    if not os.path.isfile(EXE):
        raise SystemExit(f"\nFALHOU: o PyInstaller terminou sem gerar {EXE}")
    if "--so-exe" in argv:
        print(f"\nPronto: {os.path.dirname(EXE)}")
        return 0

    iscc = _iscc()
    if not iscc:
        print("ERRO: Inno Setup 6 (ISCC.exe) nao encontrado. Instale-o, ou rode")
        print("com --so-exe para gerar so o executavel.")
        return 1
    _rodar("instalador (Inno Setup)", [iscc, "/Q", os.path.join("instalador", "PGN_Tradutor_Pro.iss")])
    _rodar("portatil (zip)", [sys.executable, os.path.join("instalador", "empacotar-portatil.py")])

    # So o que ESTA rodada gravou: a pasta guarda as entregas de versoes
    # anteriores, e lista-las junto misturaria o novo com o velho.
    print("\nEntregas em instalador/saida/:")
    for nome in sorted(os.listdir(SAIDA)):
        caminho = os.path.join(SAIDA, nome)
        if os.path.getmtime(caminho) >= inicio:
            print(f"  {nome}  ({os.path.getsize(caminho) / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
