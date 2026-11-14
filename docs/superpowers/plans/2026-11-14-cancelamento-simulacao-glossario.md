# Cancelamento durante simulação do glossário

**Objetivo:** tornar a comparação de regras responsiva ao cancelamento durante a aplicação em um comentário (RG-021 e RG-043).

**Abordagem:** verificar o sinal periodicamente nas regras usando a implementação existente, sem guardar offsets desnecessários no caminho de simulação. Propagar `SimulationCanceled` sem publicar resultados parciais.

**Verificação:** testar cancelamento dentro de um comentário e equivalência dos resultados com e sem sinal; executar os testes de simulação e aplicação do glossário.
