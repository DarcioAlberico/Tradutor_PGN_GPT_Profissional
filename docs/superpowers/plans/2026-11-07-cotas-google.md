# Cotas Google compartilhadas — plano

Objetivo: limitar tentativas de rede dos dois motores não oficiais entre
processos que usam a mesma pasta de dados, sem guardar textos ou chaves.

1. Implementar reservas atômicas em SQLite com janelas móveis de 60 segundos e
   24 horas; conservar cooldown, cancelamento e falha fechada. Testar com
   processos reais, horários controlados, falhas e limite alterado.
2. Expor limites configuráveis em Configurações usando o mesmo banco de controle,
   sem sobrescrever outras preferências e sem alterar contagens existentes.
3. Testar integração dos dois motores, interface e regressões. Documentar
   limites entre pastas de dados diferentes, relógio do sistema e requisições
   já em voo. Estimativa antecipada e API oficial permanecem etapas separadas.
