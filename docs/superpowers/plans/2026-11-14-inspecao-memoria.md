# Inspeção de temporários com memória limitada

**Objetivo:** limitar a memória usada para exemplos durante a inspeção prevista no RG-000B e RG-043, preservando contagem e ordem.

**Abordagem:** manter apenas os exemplos mais antigos, com desempate pelo nome; não modificar arquivos. Validar contagem, ordenação e limite de objetos retidos, inclusive com limite zero.

**Arquivos:** `translation_library.py`, `test_staging_inspection.py` e `REVISAO_GERAL.md`.
