# Cancelamento da escrita do PGN

**Objetivo:** interromper a gravação do PGN entre trechos sem substituir um destino existente (RG-000B).

**Abordagem:** verificar cancelamento durante cada tentativa de codificação e antes da troca atômica; remover temporário e informar cancelamento ao gerador.
