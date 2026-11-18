# Restauração de curadoria respeitando filtros

**Objetivo:** restaurar decisões ignoradas correspondentes aos filtros atuais, mesmo quando distribuídas em várias páginas (RG-022).

**Abordagem:** calcular candidatos ignorados a partir da busca e do filtro de regra, sem depender da página nem da opção de exibição de ignoradas. O botão informa o escopo e fica desabilitado quando não há resultados.

**Validação:** testes de busca, filtros, paginação e ausência de escrita para candidatos fora da seleção.
