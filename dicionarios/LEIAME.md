# Dicionarios de prosa

Aqui ficam os dicionarios hunspell do **idioma de destino**, usados pelo corretor
ortografico da janela de edicao (`tradutor_pgn/prose_spellcheck.py`, ROADMAP 26).

Nao confundir com `spelling_ssp/spelling.ssp`, que e outra coisa: aquele e um
dicionario de **nomes proprios** (jogadores, torneios, locais) e serve para
normalizar as tags do PGN, nao a prosa.

## O que esta aqui

| arquivo     | tamanho | o que e                              |
| ----------- | ------- | ------------------------------------ |
| `pt_BR.dic` | 4,58 MB | 307.374 radicais                     |
| `pt_BR.aff` | 0,97 MB | regras de flexao, em **ISO-8859-1**  |

**Procedencia.** Dicionario para corretor ortografico da lingua portuguesa
(variante brasileira) do projeto VERO / OpenOffice.org.br, de Raimundo Santos
Moura <raimundomoura@openoffice.org> e colaboradores, Brasil, setembro de 2010.
O aviso de copyright e a declaracao de licenca estao no cabecalho do proprio
`pt_BR.aff`, e viajam com o arquivo.

**Licenca: GNU Lesser General Public License (LGPL) versao 2.1**, como declarado
pelos autores no `pt_BR.aff`.

> **Pendente antes de distribuir o instalador:** o texto integral da LGPL 2.1
> nao esta neste repositorio. A licenca exige que ele acompanhe a
> redistribuicao. Acrescentar `LGPL-2.1.txt` aqui, e cita-lo no instalador,
> fecha isso.

## Acrescentar um idioma

O corretor so cobre os idiomas listados em `prose_spellcheck.DICTIONARY_NAMES`,
e **diz isso na janela** quando o par nao tem dicionario, em vez de ficar em
silencio. Para acrescentar um:

1. ponha o par `<base>.dic` e `<base>.aff` neste diretorio;
2. acrescente `"<idioma>": "<base>"` a `DICTIONARY_NAMES`;
3. registre aqui a procedencia e a licenca do arquivo novo.

O `PGN_Tradutor_Pro.spec` empacota o diretorio inteiro por varredura, entao o
passo de empacotamento nao existe — e proposital, e a licao do
`Termos-suspeitos.txt`, que entrou no programa e ninguem lembrou de acrescentar
a lista escrita a mao do `.spec`.

## Motor

O motor e o [`spylls`](https://pypi.org/project/spylls/) (`requirements.txt`),
implementacao do hunspell em Python puro, licenca MIT. Python puro de proposito:
nao precisa de compilador na maquina de quem instala e nao muda a forma do build
do PyInstaller, que e o que uma extensao em C mudaria.
