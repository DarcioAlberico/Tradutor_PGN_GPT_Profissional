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

Sai em `dist\PGN_Tradutor_Pro\` (~77 MB). **A pasta ainda nao esta completa**: o
programa precisa do glossario ao lado do executavel.

```powershell
copy .\Substituicoes.txt .\dist\PGN_Tradutor_Pro\
copy .\glossario.db      .\dist\PGN_Tradutor_Pro\
```

O `Substituicoes.txt` e obrigatorio — sem ele o programa abre, avisa que esta sem
regras e traduz sem glossario (garantia S5). O `glossario.db` e opcional: e um
indice derivado, e sem ele a primeira carga o reconstroi (~110 ms em vez de
~16 ms).

O `spelling.ssp` **nao** entra nessa copia: ele ja vai embutido, em
`_internal\spelling_ssp\`, e o "Normalizar PGN" funciona sem preparo nenhum na
maquina de destino. A diferenca de tratamento nao e de tamanho, e de como cada
arquivo e localizado — o glossario sai de `sys.argv[0]` (ao lado do `.exe`) e o
dicionario sai de `__file__` (dentro do pacote). Estar embutido nao o congela: o
build e onedir, entao o arquivo esta em disco e da para troca-lo por uma edicao
mais nova das classificacoes sem reconstruir.

Se o `spelling_ssp\spelling.ssp` nao existir na hora do build, o PyInstaller
avisa e segue: o executavel sai sem o dicionario e so o "Normalizar PGN" fica
sem funcionar.

**Nao copie o `traducoes.db`.** Sao 80 MB de cache de traducoes desta maquina; o
programa cria o dele vazio na primeira execucao.

Distribua a pasta inteira, compactada. Para instalar noutra maquina, basta
descompactar e executar — nao ha instalador nem dependencia externa.

### O que saber antes de distribuir

- **Os dados ficam ao lado do `.exe`.** `traducoes.db`, `backups\` e `logs\` sao
  criados na pasta do executavel, entao ela precisa ser gravavel — instalar em
  `C:\Program Files` sem permissao de escrita quebra a gravacao. Uma pasta no
  perfil do usuario ou num pendrive funciona.
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
substituicoes = [
    ('rook', 'torre'),                     # sugestao, prioridade 0
    ('== EndSquare ==', '', 'cleanup'),    # outro tipo
    ('torre', 'castle', 'suggestion', 1),  # com prioridade
]
```

Um `Substituicoes.txt` de uma versao anterior continua valendo: o que faltar
assume o padrao. O mesmo vale para o CSV, cuja coluna `priority` e opcional na
leitura.

Quando duas regras disputam o mesmo padrao, o editor diz qual delas o programa
aplica e oferece duas saidas: **Priorizar esta**, que a poe na frente sem apagar
nada, e **Manter esta**, que remove as concorrentes do arquivo.

## Arquivos principais

- `PGN_Tradutor_Pro.py`: ponto de entrada da aplicacao.
- `SPEC.md`: especificacao do comportamento e das garantias do sistema.
- `tradutor_pgn/`: pacote Python com os modulos da aplicacao.
- `tradutor_pgn/app.py`: classe principal e estado da aplicacao.
- `tradutor_pgn/app_actions.py`: acoes da interface, controle da traducao e atalhos para ferramentas.
- `tradutor_pgn/app_config.py`: constantes compartilhadas do projeto.
- `tradutor_pgn/background_task.py`: executa operacoes longas fora da thread da interface, com progresso e cancelamento.
- `tradutor_pgn/backup_retention.py`: politica de retencao de `backups/` e `logs/`, com a decisao separada da remocao.
- `tradutor_pgn/chess_notation.py`: letras das pecas por idioma e correcao dos lances da traducao contra o comentario original.
- `tradutor_pgn/confirm_dialog.py`: confirmacao que exige digitar `delete`, usada pelas duas ferramentas que apagam trabalho do usuario.
- `tradutor_pgn/database.py`: inicializacao, conexao e cache do SQLite, indexado pelo par de idiomas (origem, destino).
- `tradutor_pgn/db_tools.py`: estatisticas, backup/restauracao, importacao/exportacao CSV, aplicacao das regras automaticas e as duas ferramentas de zerar — todas em segundo plano.
- `tradutor_pgn/edit_window.py`: janela de revisao e edicao de traducoes, com filtro por par de idiomas.
- `tradutor_pgn/editor_common.py`: logica pura compartilhada pelas duas janelas de edicao (geometria, paginacao, preview).
- `tradutor_pgn/editor_text.py`: busca e substituicao de texto no editor.
- `tradutor_pgn/editor_widgets.py`: pecas de interface compartilhadas pelas duas janelas (mensagens, linhas da lista, divisor, gravacao das configuracoes).
- `tradutor_pgn/failed_runs.py`: registro dos arquivos que ficaram devendo, para reprocessar so eles.
- `tradutor_pgn/glossario.py`: leitura e aplicacao do glossario.
- `tradutor_pgn/glossary_editor.py`: janela dedicada para manter o glossario persistente.
- `tradutor_pgn/history_window.py`: subjanela com o historico de alteracoes de uma traducao.
- `tradutor_pgn/main_window.py`: montagem da janela principal.
- `tradutor_pgn/pgn_spellcheck.py`: normalizacao opcional de metadados PGN com `spelling.ssp`.
- `tradutor_pgn/pgn_utils.py`: leitura, escrita, encoding e manipulacao de arquivos PGN.
- `tradutor_pgn/review_quality.py`: avisos de qualidade das traducoes.
- `tradutor_pgn/settings.py`: preferencias da interface e rascunhos de edicao.
- `tradutor_pgn/translation_api.py`: chamadas de traducao e divisao de comentarios longos.
- `tradutor_pgn/translation_worker.py`: orquestracao do processamento em segundo plano.
- `tradutor_pgn/window_utils.py`: utilitarios de janela.
- `tests/`: suite automatizada; `tests/gui_harness.py` traz o sandbox de caminhos e o silenciamento de dialogos que os testes de janela compartilham.
- `.claude/skills/run-tradutor-pgn/`: ferramenta para abrir e dirigir o app sem interacao manual (inclusive o worker de traducao, sem abrir janela) e capturar telas.
- `Substituicoes.txt`: as regras do glossario (original, substituicao e, quando ha, tipo e prioridade).
- `glossario.db`: indice SQLite do glossario, derivado do `Substituicoes.txt`. E versionado para que um clone ja abra com o indice pronto, e ele proprio guarda de qual arquivo veio (caminho relativo e hash do conteudo), de modo que reconstroi sozinho assim que as regras mudam.
- `traducoes.db`: cache local de traducoes, uma linha por (comentario, idioma de origem, idioma de destino).
- `backups/`, `logs/`: gerados em tempo de execucao, nao versionados.
