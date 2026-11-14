# Benchmark de extração PGN

Execute na raiz do projeto, com as dependências instaladas:

```powershell
uv run --locked python -m benchmarks.pgn_extraction --sizes-mib 1 10 100 --samples 20
```

O comando gera e remove arquivos sintéticos em um diretório temporário. O JSON na saída registra a máquina, as amostras de tempo, a mediana, o p95 pelo método nearest-rank e o pico de alocações Python medido com `tracemalloc` em uma execução separada. O tamanho é aproximado, pois as partidas são mantidas completas. O padrão é medir 1 MiB com cinco amostras. Com poucas amostras, o p95 é pouco informativo: com cinco, equivale ao maior tempo. Use mais amostras ao comparar versões.

A medição inclui leitura e extração, com cache do sistema operacional possivelmente aquecido; não mede o uso total de memória do processo nem recursos nativos. A partida e o comentário são repetidos: o corpus serve para comparações controladas, mas não representa toda a diversidade de PGNs. Compare resultados na mesma máquina e condições. `baseline-local.json` registra uma medição ilustrativa; não é um limite de CI. Tamanhos maiores podem exigir muita memória e tempo.

## Aplicação do glossário

```powershell
uv run --locked python -m benchmarks.glossary_matching --rule-counts 6000 50000 --samples 20
```

O comando aplica regras automáticas sintéticas a um comentário curto e confere o resultado. A primeira medição começa com caches limpos; as demais usam o estado deixado pelas chamadas anteriores. O relatório inclui acertos e faltas no cache de padrões durante essas chamadas. Se o conjunto exceder a capacidade do cache, as chamadas seguintes podem continuar recompilando padrões. O pico de alocações Python é medido numa aplicação fria separada e não inclui a criação prévia das regras nem toda a memória do processo. O script limpa os caches apenas no processo de benchmark; não lê ou modifica o glossário do usuário.

Acrescente `--unicode-text` para medir um comentário com acento. As regras desse
cenário continuam sendo ASCII sintéticas; os resultados não medem regras com
acentos e não representam todos os glossários reais.

`baseline-glossario-local.json` é uma fotografia da máquina e de um caso sintético, não um limite de CI nem uma previsão para todos os glossários.

## Cache e busca no banco de traduções

```powershell
uv run --locked python -m benchmarks.translation_database --rows 10000 100000 1000000 --samples 20
```

O comando cria bancos SQLite sintéticos em diretório temporário e mede, separadamente, a carga integral do cache, a carga dos comentários solicitados (até 100) e a busca paginada por trecho. Cada operação confere seu resultado. O relatório inclui tempos, mediana, p95 nearest-rank e pico de alocações Python em execução separada; não inclui toda a memória do SQLite ou do processo. A criação exclusiva impede substituir um banco existente. As amostras podem usar cache aquecido do sistema; corpus real, resultados e uso de memória podem ser diferentes. Um milhão de linhas pode exigir bastante tempo e espaço. `baseline-banco-local.json` não é um limite de CI.

## Geração de PGN

```powershell
uv run --locked python -m benchmarks.pgn_generation --sizes-mib 1 10 100 --samples 20
```

O cenário gera partidas sintéticas UTF-8 com acentos e quebras CRLF em uma pasta temporária exclusiva. O tempo cobre a geração com texto e posições já preparados, sem requebra; a extração e a comparação com os bytes esperados ficam fora da cronometragem. Cada saída é conferida integralmente por tamanho e SHA-256. O pico de alocações Python é medido separadamente e não inclui a memória previamente ocupada pelo texto e pelas posições. O corpus repetitivo verifica este cenário, não todos os formatos de PGN. `baseline-geracao-pgn-local.json` é uma fotografia local, não um limite de CI.
