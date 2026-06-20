# PGN Tradutor Pro

Aplicacao CustomTkinter para traduzir comentarios de arquivos PGN, com cache em SQLite e glossario de substituicoes.

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

## Arquivos principais

- `PGN_Tradutor_Pro.py`: ponto de entrada da aplicacao.
- `tradutor_pgn/`: pacote Python com os modulos da aplicacao.
- `tradutor_pgn/app.py`: classe principal e estado da aplicacao.
- `tradutor_pgn/app_actions.py`: acoes da interface, controle da traducao e atalhos para ferramentas.
- `tradutor_pgn/app_config.py`: constantes compartilhadas do projeto.
- `tradutor_pgn/database.py`: fachada dos modulos de banco.
- `tradutor_pgn/db_connection.py`: conexao, schema e migracoes SQLite.
- `tradutor_pgn/db_cache.py`: cache de traducoes.
- `tradutor_pgn/db_review.py`: consultas da fila de revisao.
- `tradutor_pgn/db_history.py`: historico de alteracoes.
- `tradutor_pgn/db_stats.py`: estatisticas e linhas de exportacao.
- `tradutor_pgn/db_translation_updates.py`: atualizacoes de traducao e status.
- `tradutor_pgn/db_tools.py`: fachada das ferramentas de banco.
- `tradutor_pgn/db_backup.py`: backup e restauracao do SQLite.
- `tradutor_pgn/db_csv.py`: analise/importacao de CSV.
- `tradutor_pgn/db_dialogs.py`: dialogs Tkinter de estatisticas, CSV e backup.
- `tradutor_pgn/edit_window/`: janela de revisao e edicao de traducoes (modular).
  - `editor.py`: classe principal `TranslationEditor` e ponto de entrada.
  - `ui.py`: agregador dos mixins de UI.
  - `ui_list_panel.py`: painel de lista, busca e salto por pagina/ID.
  - `ui_text_panel.py`: painel de textos, busca/substituicao e labels QA/historico.
  - `ui_glossary_panel.py`: painel de sugestoes do glossario.
  - `ui_footer.py`: barra de navegacao, filtros e acoes de edicao.
  - `list_navigation.py`: agregador dos mixins de lista, persistencia e QA.
  - `pagination.py`: agregador dos mixins de paginacao.
  - `list_page_data.py`: carregamento e renderizacao das linhas da pagina.
  - `list_filters.py`: filtros de status e busca.
  - `list_selection.py`: selecao e navegacao por pagina/ID.
  - `persistence.py`: carregamento, salvamento e marcacao de traducoes.
  - `quality_navigation.py`: navegacao e exportacao de avisos QA.
  - `drafts.py`: rascunhos, dirty state e settings do editor.
  - `find_replace.py`: busca e substituicao no texto da traducao.
  - `text_editing.py`: edicao do texto (fonte, undo/redo, QA inline).
  - `glossary.py`: painel de sugestoes do glossario.
  - `history_window.py`: popup de historico de alteracoes.
  - `shortcuts.py`: atalhos de teclado e wiring de eventos.
  - `helpers.py` / `constants.py`: utilitarios compartilhados.
- `tradutor_pgn/main_window.py`: montagem da janela principal.
- `tradutor_pgn/pgn_utils.py`: leitura, escrita, encoding e manipulacao de arquivos PGN.
- `tradutor_pgn/translation_api.py`: chamadas de traducao e divisao de comentarios longos.
- `tradutor_pgn/translation_worker.py`: orquestracao do processamento em segundo plano.
- `tradutor_pgn/glossario.py`: leitura e aplicacao do glossario.
- `Substituicoes.txt`: pares de substituicao usados na revisao.
- `traducoes.db`: cache local de traducoes.
