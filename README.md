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

## Normalizacao de metadados PGN

O botao `Normalizar PGN` corrige apenas metadados PGN (`White`, `Black`, `Site`,
`Event` e `Round`) usando um arquivo externo opcional em
`spelling_ssp/spelling.ssp`. Comentarios, lances e variantes nao sao alterados.

Os arquivos corrigidos sao gravados ao lado do original com o sufixo
`-NORM.pgn`. O arquivo `spelling.ssp` nao e versionado neste repositorio.

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
- `tradutor_pgn/database.py`: inicializacao, conexao e cache do SQLite.
- `tradutor_pgn/db_tools.py`: estatisticas, backup/restauracao, importacao/exportacao CSV e aplicacao das regras automaticas — todas em segundo plano.
- `tradutor_pgn/edit_window.py`: janela de revisao e edicao de traducoes.
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
- `traducoes.db`: cache local de traducoes.
- `backups/`, `logs/`: gerados em tempo de execucao, nao versionados.
