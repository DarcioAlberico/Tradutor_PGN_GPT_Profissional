# Publicação atômica de PGN

**Objetivo:** avançar RG-000B sem alterar o formato ou a codificação de saída.

**Arquitetura:** `write_pgn_pieces` grava em arquivo temporário exclusivo no
mesmo diretório e substitui o destino somente após terminar; exceções removem o
temporário e preservam eventual destino anterior. A publicação de pacotes já
usa diretório de preparação e continua responsável pelo manifesto e original.

**Verificações:** falha ao produzir dados, falha ao publicar, destino inexistente,
destino preexistente, fallback de codificação, BOM e geração em fluxo.
