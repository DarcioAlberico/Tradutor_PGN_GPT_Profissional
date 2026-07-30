"""PGN Tradutor Pro.

`__version__` e a **unica** fonte da versao do programa (ROADMAP 21.6). Antes
havia tres numeros que nao se falavam: o `pyproject.toml` em `0.2.1` — parado
desde o import inicial, dez secoes atras —, o cabecalho TMX exportado dizendo
`1.0` e o instalador dizendo `1.0.0`. Nenhum derivava de outro, e o do TMX vai
dentro de arquivos que saem daqui para outras ferramentas.

Quem usa este valor, e por que nao ha copia em lugar nenhum:

- o titulo da janela, para o usuario saber o que esta rodando;
- o cabecalho `creationtoolversion` do TMX exportado;
- o recurso de versao gravado no `.exe` pelo PyInstaller (ver o `.spec`);
- o instalador, que **le a versao do proprio `.exe`** em vez de declarar a sua
  (ver `instalador/PGN_Tradutor_Pro.iss`), e a usa para recusar uma instalacao
  mais velha por cima de uma mais nova.

O `pyproject.toml` continua com o numero escrito a mao — o projeto nao e
empacotado como biblioteca (`package = false`), entao nao ha metadado dinamico
para derivar dele. O que impede os dois de divergirem e um teste.

Tres partes (`X.Y.Z`), sem sufixo: o recurso de versao do Windows e a comparacao
do instalador querem numeros, e um `0.3.0-beta` teria de ser traduzido em dois
lugares diferentes para caber.
"""

__version__ = "0.3.0"
