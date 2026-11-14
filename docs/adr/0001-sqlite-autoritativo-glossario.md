# ADR 0001: SQLite autoritativo para o catálogo de glossário

## Status

Proposto em 23/10/2026.

## Contexto

O programa mantém as mesmas entradas em `Substituicoes.txt` e `glossario.db`, mas trata o texto como fonte e o banco como cache reconstruível. Essa escolha impede IDs estáveis, torna edições concorrentes ambíguas e permite que deduplicação, update e delete discordem sobre a identidade de uma entrada.

## Decisão

O SQLite será a fonte autoritativa do catálogo. Entradas terão UUID e revisão persistentes; o arquivo texto será um espelho legível e um formato explícito de importação/exportação. Mutações serão transacionais e usarão concorrência otimista.

## Alternativas rejeitadas

- Corrigir somente as comparações de tuplas: não resolve concorrência nem identidade persistente.
- Manter o texto autoritativo com hash de arquivo: qualquer alteração continua sendo uma regravação global e IDs não sobrevivem naturalmente.

## Consequências

- Edição e exclusão tornam-se determinísticas e resistentes a alterações concorrentes.
- A migração e a recuperação ficam mais complexas e exigem backups e validação explícitos.
- Edição externa direta do texto deixa de ser sincronizada automaticamente; passa a exigir importação consciente.
- Versões antigas do programa não devem reconstruir ou sobrescrever o catálogo novo.
