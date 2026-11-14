# Separação das esperas Google

Na mesma transação que calcula a reserva, identificar se cota, cooldown ou ambos bloqueiam o envio, sem alterar os prazos. A espera informa ao controlador o tempo real decorrido de cada pausa, inclusive cancelada; tempos simultâneos têm categoria própria, e a consulta ao SQLite continua no total geral. Contadores locais aparecem no resumo mesmo quando a execução é cancelada. Testar as combinações, prazo, cancelamento e compatibilidade da API de reserva; validar ambos os motores e os testes do worker.
