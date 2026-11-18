# Busca exata de falhas na Biblioteca

**Objetivo:** permitir filtrar a contagem exata de falhas da geração sem confundir números encontrados em outros campos (RG-031).

**Abordagem:** reconhecer o termo `falhas:N` para um inteiro não negativo; manter busca textual e filtros existentes, não presumir falhas de pacotes antigos. Documentar e testar combinações.
