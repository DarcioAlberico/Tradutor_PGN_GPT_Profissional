# Progresso de revisão detalhado — RG-031 e RG-062

1. Contar comentários pendentes em dúvida.
2. Contar comentários pendentes rejeitados.
3. Contar pendentes com alerta de qualidade.
4. Mostrar pendentes sem alerta de qualidade, sem somar os subconjuntos ao total.
5. Permitir cancelar a consulta e descartar uma resposta recebida após o cancelamento.

Consultar o banco sem escrita, respeitar o vínculo e a verificação do pacote. Propagar cancelamento à leitura em blocos e conferir novamente após a consulta SQLite; uma operação de sistema ou SQL já iniciada pode precisar terminar. Evitar concorrência com a verificação individual e em lote, que compartilham o controle de cancelamento da janela.
