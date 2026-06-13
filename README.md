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
- `tradutor_pgn/database.py`: inicializacao, conexao e cache do SQLite.
- `tradutor_pgn/db_tools.py`: estatisticas e exportacao CSV.
- `tradutor_pgn/edit_window.py`: janela de revisao e edicao de traducoes.
- `tradutor_pgn/main_window.py`: montagem da janela principal.
- `tradutor_pgn/pgn_utils.py`: leitura, escrita, encoding e manipulacao de arquivos PGN.
- `tradutor_pgn/translation_api.py`: chamadas de traducao e divisao de comentarios longos.
- `tradutor_pgn/translation_worker.py`: orquestracao do processamento em segundo plano.
- `tradutor_pgn/glossario.py`: leitura e aplicacao do glossario.
- `Substituicoes.txt`: pares de substituicao usados na revisao.
- `traducoes.db`: cache local de traducoes.
