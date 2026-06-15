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

## Normalizacao de metadados PGN

O botao `Normalizar PGN` corrige apenas metadados PGN (`White`, `Black`, `Site`,
`Event` e `Round`) usando um arquivo externo opcional em
`spelling_ssp/spelling.ssp`. Comentarios, lances e variantes nao sao alterados.

Os arquivos corrigidos sao gravados ao lado do original com o sufixo
`-NORM.pgn`. O arquivo `spelling.ssp` nao e versionado neste repositorio.

## Arquivos principais

- `PGN_Tradutor_Pro.py`: ponto de entrada da aplicacao.
- `tradutor_pgn/`: pacote Python com os modulos da aplicacao.
- `tradutor_pgn/app.py`: classe principal e estado da aplicacao.
- `tradutor_pgn/app_actions.py`: acoes da interface, controle da traducao e atalhos para ferramentas.
- `tradutor_pgn/app_config.py`: constantes compartilhadas do projeto.
- `tradutor_pgn/database.py`: inicializacao, conexao e cache do SQLite.
- `tradutor_pgn/db_tools.py`: estatisticas e exportacao CSV.
- `tradutor_pgn/edit_window.py`: janela de revisao e edicao de traducoes.
- `tradutor_pgn/glossary_editor.py`: janela dedicada para manter o glossario persistente.
- `tradutor_pgn/main_window.py`: montagem da janela principal.
- `tradutor_pgn/pgn_spellcheck.py`: normalizacao opcional de metadados PGN com `spelling.ssp`.
- `tradutor_pgn/pgn_utils.py`: leitura, escrita, encoding e manipulacao de arquivos PGN.
- `tradutor_pgn/translation_api.py`: chamadas de traducao e divisao de comentarios longos.
- `tradutor_pgn/translation_worker.py`: orquestracao do processamento em segundo plano.
- `tradutor_pgn/glossario.py`: leitura e aplicacao do glossario.
- `Substituicoes.txt`: pares de substituicao usados na revisao.
- `glossario.db`: indice SQLite local do glossario, recriado/sincronizado a partir de `Substituicoes.txt`.
- `traducoes.db`: cache local de traducoes.
