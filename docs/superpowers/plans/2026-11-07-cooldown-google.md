# Cooldown Google compartilhado — plano

Objetivo: preservar o prazo de `Retry-After` em disco e compartilhá-lo entre
processos que usam a mesma pasta de dados. O estado contém somente prazo,
sem comentários, nomes ou chaves. A cota global por minuto/dia é outra etapa.

1. Criar repositório SQLite com atualização atômica pelo maior prazo e testes
   com processos independentes, dados temporários, falhas e cancelamento.
2. Integrar ao controlador de ritmo do worker e aos dois adaptadores Google;
   consultar antes de cada chamada HTTP e registrar 429/503 com `Retry-After`.
   Não liberar chamadas quando o estado compartilhado estiver inacessível.
3. Verificar o worker e os dois adaptadores sem rede real. Documentar que
   requisições já em voo não são interrompidas, que pastas de dados diferentes
   não compartilham o estado e que mudanças de relógio afetam prazos em disco.
