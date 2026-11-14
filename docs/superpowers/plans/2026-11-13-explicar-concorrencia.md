# Explicar concorrência entre regras do glossário

**Objetivo:** mostrar ocorrências candidatas que foram bloqueadas por uma
regra aplicada antes, com posição e critério de precedência.

**Abordagem:** preservar posições originais durante a aplicação existente;
somente quando solicitado, identificar candidatos que se sobrepõem a trechos
protegidos por regras anteriores. Limitar o relatório, permitir cancelamento e
informar que somente sobreposições identificadas no texto original são cobertas.

**Verificar:** prioridade, comprimento, empate por ordem, repetição, Unicode,
texto não alterado e equivalência com o motor sem explicação.
