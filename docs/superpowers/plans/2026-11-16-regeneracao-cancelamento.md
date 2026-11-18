# Cancelamento ao localizar pacote de revisão

**Objetivo:** permitir interromper a verificação e a busca de correspondências antes da regeneração.

**Abordagem:** propagar o sinal para a verificação de integridade, hashes e enumeração de candidatos. A operação cancelada não gera saída nem informa uma falha de integridade.
