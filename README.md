# PGN Tradutor Pro

Aplicacao CustomTkinter para traduzir comentarios de arquivos PGN, com cache em
SQLite e glossario de substituicoes.

O comportamento esperado do sistema e as garantias que os testes protegem estao
em [SPEC.md](SPEC.md). O [ROADMAP.md](ROADMAP.md) registra as melhorias, feitas e
pendentes, com o motivo de cada decisao e as medicoes que a sustentam.

## Requisitos

Python 3.13 (fixado em `.python-version`; o `uv` cria o ambiente na versao certa
automaticamente).

## Usando uv

Instale as dependencias e crie o ambiente virtual:

```powershell
uv sync
```

Execute a aplicacao:

```powershell
uv run python .\PGN_Tradutor_Pro.py
```

Verifique sintaxe dos modulos principais:

```powershell
uv run python -m compileall .\PGN_Tradutor_Pro.py .\tradutor_pgn
```

Execute os testes automatizados:

```powershell
uv run python -m unittest discover -s .\tests
```

Parte da suite abre as janelas de verdade e clica nos widgets (o editor de
traducoes, o de glossario e a janela principal). Onde nao houver display, essas
classes sao puladas e o restante roda normalmente.

> Se `uv run` reclamar de um Python inexistente (`No Python at ...`), o `.venv`
> ficou apontando para uma instalacao removida. Apague a pasta `.venv` e rode
> `uv sync` de novo.

## Executavel (rodar sem Python instalado)

Gera um `.exe` para Windows que roda em maquinas sem Python. A receita esta em
[PGN_Tradutor_Pro.spec](PGN_Tradutor_Pro.spec), com o motivo de cada decisao:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm .\PGN_Tradutor_Pro.spec
```

Sai em `dist\PGN_Tradutor_Pro\` (~77 MB), e **a pasta esta completa** — nao copie
nada para dentro dela. O glossario, o dicionario de grafias, a semente e a lista
de termos suspeitos ja vao embutidos em `_internal\`.

> Ate a versao anterior estas instrucoes mandavam copiar o `Substituicoes.txt`
> para dentro de `dist\`. Era uma armadilha: um instalador construido sobre
> aquela pasta levaria o glossario junto e o **sobrescreveria** a cada
> atualizacao — em silencio, e justamente o arquivo que representa meses de
> curadoria. Hoje o glossario vai no pacote com outro nome
> (`Substituicoes-inicial.txt`) e quem o instala e a primeira execucao, so quando
> ainda nao ha nenhum na pasta de dados.

Se o `spelling_ssp\spelling.ssp` nao existir na hora do build, o PyInstaller
avisa e segue: o executavel sai sem o dicionario e so o "Normalizar PGN" fica
sem funcionar. Estar embutido nao o congela — o build e onedir, entao da para
troca-lo por uma edicao mais nova das classificacoes sem reconstruir.

### Onde ficam os seus dados

**Nao e mais ao lado do `.exe`.** Quem decide e como o programa foi iniciado:

| inicio | pasta de dados |
|---|---|
| o `.exe` instalado | `%APPDATA%\PGN Tradutor Pro\` |
| `python PGN_Tradutor_Pro.py` | ao lado do script |
| com `PGN_TRADUTOR_DATA=<pasta>` | a pasta que voce disser |

Glossario, banco, configuracoes, `backups\` e `logs\` seguem essa pasta. E o que
faz uma atualizacao poder trocar o programa inteiro sem tocar no seu trabalho — e
o que permite ter o app instalado e o repositorio na mesma maquina sem que um
enxergue os dados do outro. O programa diz no log da abertura qual pasta esta
usando.

Quem ja usava a versao distribuida como pasta nao precisa fazer nada: na primeira
execucao o programa **copia** o que encontrar ao lado do `.exe` para a pasta de
dados. Copia, e nao move — voltar para a versao antiga continua funcionando.
`backups\` e `logs\` ficam onde estao (podem ter centenas de MB) e o log diz onde.

### Instalador

A receita esta em [instalador\PGN_Tradutor_Pro.iss](instalador/PGN_Tradutor_Pro.iss)
(Inno Setup 6). Depois de gerar o `dist\`:

```powershell
ISCC.exe .\instalador\PGN_Tradutor_Pro.iss
```

Sai em `instalador\saida\`. Ele instala por usuario (sem pedir administrador),
cria os atalhos, **nao distribui nenhum arquivo de dados** e, ao desinstalar,
pergunta antes de apagar a pasta de dados — com "Nao" como resposta padrao.

> **Ainda nao foi compilado nem testado.** O Inno Setup nao estava instalado na
> maquina onde isto foi escrito, entao o `.iss` e uma receita revisada, e nao um
> instalador verificado. O ciclo que falta esta no ROADMAP, secao 21.5.

### O que saber antes de distribuir

- **O executavel nao e assinado.** O SmartScreen do Windows vai avisar na
  primeira execucao ("Windows protegeu o computador" -> "Mais informacoes" ->
  "Executar assim mesmo"), e alguns antivirus marcam executaveis do PyInstaller
  por heuristica. Assinar exige um certificado de codigo pago.
- **E especifico de Windows x64**, porque o PyInstaller empacota para a
  plataforma em que roda. Para outra plataforma, o build tem de acontecer nela.

## Normalizacao de metadados PGN

O botao `Normalizar PGN` corrige apenas metadados PGN (`White`, `Black`, `Site`,
`Event` e `Round`) usando o dicionario em `spelling_ssp/spelling.ssp`.
Comentarios, lances e variantes nao sao alterados.

Os arquivos corrigidos sao gravados ao lado do original com o sufixo `-NORM.pgn`.
Um arquivo que falhar (permissao negada, arquivo aberto em outro programa) e
contado e informado; os demais do lote continuam sendo normalizados.

Para acrescentar nomes ao dicionario, basta abrir um segundo bloco `@PLAYER ""`
no fim do arquivo: blocos repetidos da mesma secao se somam, e o primeiro a
definir uma grafia vence.

**A primeira normalizacao cria um `spelling.db` na pasta de dados** e leva uns
2 segundos a mais para isso — sao 513 mil grafias indexadas. (Rodando do fonte, a
pasta de dados e a do projeto, entao ele cai ao lado do dicionario; instalado,
ele vai para o `%APPDATA%` junto com o resto — indice e escrita, e escrita nao
mora na pasta do programa.) Dali em diante o
botao abre o indice em milissegundos, em vez de reler os 30 MB do arquivo a cada
uso. Trocar o `spelling.ssp` por uma versao nova reconstroi o indice sozinho (ele
guarda o hash do arquivo de onde veio); apagar o `spelling.db` tambem e seguro, e
ele volta na normalizacao seguinte. E o mesmo desenho do `glossario.db`, e por
isso ele nao vai para o repositorio: e derivado.

O `spelling.ssp` **vem com o projeto** (29 MB, ~513 mil nomes de jogadores, mais
sedes, eventos e rodadas), e por isso o botao funciona sem preparo — inclusive no
executavel, onde ele vai embutido. E um arquivo de terceiros: o spellcheck do
Scid, com as classificacoes FIDE de abril de 2024. Trocar por uma edicao mais
nova e substituir o arquivo; carrega-lo custa ~1,1 s, uma vez por uso do botao.

## Glossario

`Substituicoes.txt` e a fonte de verdade; `glossario.db` e apenas um indice
derivado, reconstruido a partir dele. Cada regra tem um tipo:

- `cleanup`: aplicada ao comentario **antes** de enviar para a API.
- `automatic`: aplicada a resposta da API, sem revisao humana.
- `suggestion`: oferecida no editor de traducoes, aplicada a pedido.

Regras escritas inteiramente em minusculas casam sem diferenciar maiusculas;
qualquer maiuscula torna a regra sensivel a caixa. Na aplicacao em cascata, a
regra de padrao mais longo tem precedencia, para que uma regra generica nao
encubra uma especifica (garantia S3 na [SPEC.md](SPEC.md)).

Cada regra pode ainda declarar uma **prioridade** inteira, zero por padrao: a
maior e aplicada primeiro, e so entre prioridades iguais o comprimento volta a
decidir (garantia S10). Ela existe porque a especificidade e derivada do texto —
sem prioridade, adiantar uma regra exige alongar o padrao, isto e, mudar o que
ela casa para mudar quando ela roda.

No arquivo cada regra e uma tupla de dois a quatro campos, e cada campo so
aparece quando tem algo a dizer:

```python
escopo = 'pt'                              # padrao do arquivo (opcional)

substituicoes = [
    ('rook', 'torre'),                     # sugestao, prioridade 0, escopo 'pt'
    ('== EndSquare ==', '', 'cleanup'),    # outro tipo
    ('torre', 'castle', 'suggestion', 1),  # com prioridade
    ('×', 'x', 'automatic', 0, '*'),       # excecao: vale para todo idioma
    ('@casa@-torre', 'torre de @casa@'),   # vale pelas 64 casas
]
```

Um `Substituicoes.txt` de uma versao anterior continua valendo: o que faltar
assume o padrao. O mesmo vale para o CSV, cuja coluna `priority` e opcional na
leitura. Um tipo que o programa nao reconheca continua virando `suggestion`, mas
agora avisa qual valor nao foi entendido.

O `@casa@` no padrao vale pelas **64 casas do tabuleiro**: a linha acima e uma
no arquivo e 64 regras na aplicacao (`a1-torre`, ... `h8-torre`). As regras que
saem dela sao literais, exatamente as que voce escreveria a mao — nao ha
expressao regular envolvida. Quem manda e o padrao: sem `@casa@` nele, a regra
vale como esta. O editor de glossario mostra e edita a linha com o placeholder.

## Escopo de idioma

Uma regra que corrige portugues nao deve alcancar uma traducao para o italiano —
`('movimento', 'lance')` transformava `il movimento` em `il lance`. O **escopo**
resolve isso: ele nomeia o idioma de **destino** para o qual a regra vale
(`'pt'`), ou o par inteiro quando o erro e daquela traducao especifica
(`'en>pt'`).

Como o acervo inteiro costuma ter o mesmo escopo, ele e declarado **uma vez** no
alto do arquivo (`escopo = 'pt'`), e o quinto campo de cada regra existe apenas
para discordar: `'*'` quando a excecao e valer para todo idioma, um codigo
quando e outro. Um `Substituicoes.txt` sem a declaracao continua valendo como
sempre — sem escopo, toda regra vale para todo par.

O escopo aparece no editor de glossario, no campo `Idioma:`, e no rotulo de cada
regra que o declara. No CSV e a coluna `lang`, opcional na leitura.

## Dicionario-semente

O programa **vem com** terminologia enxadristica propria, em
`tradutor_pgn/Substituicoes-semente.txt`: 232 regras cobrindo 41 termos do
nucleo (pecas, xeque, mate, roque, cravada, garfo, coluna, fileira, fases,
estrutura de peoes) para os sete idiomas de destino.

Todas vao de **ingles para o destino**, porque essa e a direcao que nao pode
causar dano: um padrao em ingles nao casa texto portugues ou italiano. Elas
cobrem o caso mais comum de todos — o tradutor automatico simplesmente nao
traduziu o termo. E todas sao `suggestion`, oferecidas no editor e aplicadas a
pedido.

**O seu glossario sempre vence.** Uma regra sua com o mesmo texto encontrado, no
mesmo escopo (ou sem escopo nenhum), descarta a regra correspondente da semente.
Os dois arquivos tambem nao se misturam no disco: o seu fica ao lado do
executavel, a semente fica dentro do pacote do programa e e substituida quando
ele e atualizado — nunca o contrario.

Quando duas regras disputam o mesmo padrao, o editor diz qual delas o programa
aplica e oferece duas saidas: **Priorizar esta**, que a poe na frente sem apagar
nada, e **Manter esta**, que remove as concorrentes do arquivo.

## O editor como ferramenta de trabalho

O que o revisor ganhou para aguentar um livro inteiro:

- **lado a lado opcional** — um botao troca entre original acima da traducao e os
  dois em colunas, sem perder o que esta sendo digitado. A orientacao e a proporcao
  ficam lembradas, cada uma com a sua posicao de divisor;
- **`Ctrl+F` busca no texto aberto** e `Ctrl+L` na lista. Era o contrario, e o gesto
  universal caia no campo que troca a pagina — perdendo o lugar em que se estava;
- **`Alt+Backspace` volta** de onde a busca levou, com os filtros que estavam
  ativos e nao so a linha. E o que permite usar a busca como concordancia ("como
  traduzi *outpost* ate aqui?") e voltar ao trabalho;
- **a linha da lista diz o status, o aviso QA e o idioma de origem**, sem precisar
  abri-la;
- **"Rejeitada" e "Em dúvida", com nota do revisor** — "voltar aqui com o autor" nao
  cabia em pendente/verificada. Os dois sao filtros da lista, e verificar a linha
  limpa o status;
- **selecao em lote**: marcar a pagina (ou linhas de paginas diferentes), verificar
  so o que esta marcado ou exportar so isso;
- **previa com diff pintado** em "Aplicar todas": as faixas trocadas aparecem
  destacadas nos dois lados, com a contagem de trechos alterados.

## Contagem de palavras, estatisticas e TMX

**"Estatísticas do BD" passou a abrir numa janela propria**, copiavel e salvavel em
`.txt`, calculada em segundo plano com barra de progresso e cancelamento. Ela traz a
**contagem de palavras** — a metrica com que tradutor orca e cobra — do acervo
inteiro e por par de idiomas, separando original de traducao e verificada de
pendente, alem do progresso por obra e da atividade de revisao por dia.

**"Exportar TMX"** escreve o acervo como memoria de traducao TMX 1.4, que abre em
OmegaT, Trados e memoQ. Linhas sem traducao ficam fora (uma memoria com o destino
vazio nao serve para concordancia) e o `id` do banco vai como `tuid`. O CSV de
traducoes tambem passou a levar o `id` na primeira coluna, mais o status de revisao
e a nota.

## Requebra em 80 colunas (opcional)

O padrao PGN tem um *export format* de 80 colunas, que e o que editora espera
receber. Ligue com `"output": {"wrap_columns": 80}` no
`pgn_tradutor_pro_settings.json`; zero, o padrao, mantem cada comentario em linha
unica como sempre. A requebra muda **so o espaco em branco** — as palavras saem
identicas, as anotacoes `[%...]` nunca sao partidas e o fim de linha do arquivo e
respeitado.

## Revisar um livro na ordem em que ele se le

O banco guarda uma traducao por (comentario, origem, destino) — o mesmo
comentario em doze livros e uma linha, uma traducao e uma revisao. Ao lado dela, a
tabela `occurrences` guarda **onde cada comentario foi lido**: arquivo, partida,
indice e numero do lance, gravados pelo worker durante a traducao.

Com isso o editor ganhou um seletor **Arquivo**. Escolher uma obra filtra a lista
e a poe na ordem do livro, cada comentario aparecendo uma vez (um livro repete
"Diagram" dezenas de vezes); "Todos os arquivos" volta a ordem de insercao no
cache, que e a de sempre. O rodape do original diz de onde ele veio — e, quando a
traducao serve a varias posicoes, quantas sao: editar ali muda todas.

"Estatisticas do BD" passou a mostrar **progresso por obra**: posicoes,
comentarios distintos, verificadas com porcentagem, pendentes e avisos QA por
arquivo.

As traducoes gravadas antes desta versao nao tem procedencia — ela nao esta em
lugar nenhum do banco, e nada e inventado para elas. Elas aparecem em "Todos os
arquivos" e ganham a primeira ocorrencia quando o PGN delas for processado de
novo.

## Avisos de qualidade

O editor de traducoes marca linhas suspeitas e o filtro **Avisos QA** as isola.
Cinco avisos sao genericos de traducao (vazia, igual ao original, chaves perdidas,
curta demais, longa demais) e os demais sabem que o texto e xadrez:

- **lance perdido ou inventado** — os lances do original e da traducao sao
  comparados pela parte que nao muda de idioma (`f1`, `xe4+`), entao `Nf3` -> `Cf3`
  passa limpo e um lance que sumiu aparece;
- **anotacao `[%...]` rompida**, **NAG `$n`** e **simbolo de avaliacao** ausentes
  ou alterados;
- **`U+FFFD`** no texto (bytes perdidos na leitura) e **`|||`** vazado de um lote;
- **traducao quase identica** ao original;
- **terminologia suspeita**, pelo `Termos-suspeitos.txt`: "check" no original com
  "cheque" na traducao, "file" com "arquivo", "square" com "quadrado". Medido nas
  6.500 traducoes do banco de desenvolvimento, isto marca 347 linhas (5,3%) que
  antes passavam limpas.

O aviso e **cache**: fica materializado numa coluna para que contar e paginar por
"com aviso" seja uma consulta indexada. As heuristicas tem versao, e quando ela
muda o programa reavalia o banco na abertura, com barra de progresso e
cancelamento (~25 s em 200 mil traducoes, uma vez). O botao **Reavaliar QA** faz o
mesmo na hora — para quem cancelou, ou para quem editou o `Termos-suspeitos.txt` a
mao.

## Arquivos principais

- `PGN_Tradutor_Pro.py`: ponto de entrada da aplicacao.
- `SPEC.md`: especificacao do comportamento e das garantias do sistema.
- `tradutor_pgn/`: pacote Python com os modulos da aplicacao.
- `tradutor_pgn/app.py`: classe principal e estado da aplicacao.
- `tradutor_pgn/app_actions.py`: acoes da interface, controle da traducao e atalhos para ferramentas.
- `tradutor_pgn/app_config.py`: constantes compartilhadas do projeto.
- `tradutor_pgn/background_task.py`: executa operacoes longas fora da thread da interface, com progresso e cancelamento.
- `tradutor_pgn/backup_retention.py`: politica de retencao de `backups/` e `logs/`, com a decisao separada da remocao.
- `tradutor_pgn/chess_notation.py`: letras das pecas por idioma, correcao dos lances da traducao contra o comentario original e as ancoras que o aviso de qualidade compara.
- `tradutor_pgn/chess_terms.py`: leitura da lista de termos cuja traducao errada da para reconhecer pelo texto, escopada por idioma.
- `tradutor_pgn/confirm_dialog.py`: confirmacao que exige digitar `delete`, usada pelas duas ferramentas que apagam trabalho do usuario.
- `tradutor_pgn/database.py`: inicializacao, conexao e cache do SQLite, indexado pelo par de idiomas (origem, destino).
- `tradutor_pgn/db_tools.py`: estatisticas, backup/restauracao, importacao/exportacao CSV, regras automaticas, correcao dos lances do banco ja gravado e as duas ferramentas de zerar — todas em segundo plano.
- `tradutor_pgn/edit_window.py`: janela de revisao e edicao de traducoes, com filtro por par de idiomas e por arquivo de origem (que traz a obra em ordem de leitura).
- `tradutor_pgn/editor_common.py`: logica pura compartilhada pelas duas janelas de edicao (geometria, paginacao, preview).
- `tradutor_pgn/editor_text.py`: busca, substituicao e diff por palavra do texto no editor.
- `tradutor_pgn/stats_window.py`: janela copiavel das estatisticas do banco.
- `tradutor_pgn/word_count.py`: a definicao de "palavra" do programa, num lugar so.
- `tradutor_pgn/editor_widgets.py`: pecas de interface compartilhadas pelas duas janelas (mensagens, linhas da lista, divisor, gravacao das configuracoes).
- `tradutor_pgn/failed_runs.py`: registro dos arquivos que ficaram devendo, para reprocessar so eles.
- `tradutor_pgn/glossario.py`: leitura e aplicacao do glossario.
- `tradutor_pgn/glossary_editor.py`: janela dedicada para manter o glossario persistente.
- `tradutor_pgn/history_window.py`: subjanela com o historico de alteracoes de uma traducao.
- `tradutor_pgn/main_window.py`: montagem da janela principal.
- `tradutor_pgn/pgn_spellcheck.py`: normalizacao opcional de metadados PGN com `spelling.ssp`.
- `tradutor_pgn/pgn_utils.py`: leitura, escrita, encoding e manipulacao de arquivos PGN.
- `tradutor_pgn/review_quality.py`: avisos de qualidade das traducoes, genericos e de xadrez (lance perdido, anotacao rompida, NAG, terminologia), com a versao das heuristicas que decide quando reavaliar o banco.
- `tradutor_pgn/settings.py`: preferencias da interface e rascunhos de edicao.
- `tradutor_pgn/translation_api.py`: chamadas de traducao e divisao de comentarios longos.
- `tradutor_pgn/translation_worker.py`: orquestracao do processamento em segundo plano.
- `tradutor_pgn/window_utils.py`: utilitarios de janela.
- `tests/`: suite automatizada; `tests/gui_harness.py` traz o sandbox de caminhos e o silenciamento de dialogos que os testes de janela compartilham.
- `.claude/skills/run-tradutor-pgn/`: ferramenta para abrir e dirigir o app sem interacao manual (inclusive o worker de traducao, sem abrir janela) e capturar telas.
- `Substituicoes.txt`: as regras do glossario do usuario (original, substituicao e, quando ha, tipo, prioridade e escopo de idioma).
- `tradutor_pgn/Substituicoes-semente.txt`: a terminologia que vem com o programa, escopada por idioma de destino. Nunca sobrepoe o `Substituicoes.txt`.
- `tradutor_pgn/Termos-suspeitos.txt`: os pares "termo no original / forma errada na traducao" que geram aviso de qualidade. Vem com o programa, medido no banco de desenvolvimento, e nao corrige nada — leva o revisor ate a linha.
- `glossario.db`: indice SQLite do glossario, derivado do `Substituicoes.txt`. E versionado para que um clone ja abra com o indice pronto, e ele proprio guarda de qual arquivo veio (caminho relativo e hash do conteudo), de modo que reconstroi sozinho assim que as regras mudam.
- `traducoes.db`: cache local de traducoes, uma linha por (comentario, idioma de origem, idioma de destino). Ao lado dela, a tabela `occurrences` guarda onde cada comentario foi lido — arquivo, partida, indice e numero do lance —, que e o que da ordem de leitura da obra ao editor e progresso por livro as estatisticas. As traducoes gravadas antes desta versao nao tem essa procedencia e a ganham ao reprocessar o PGN.
- `backups/`, `logs/`: gerados em tempo de execucao, nao versionados.
