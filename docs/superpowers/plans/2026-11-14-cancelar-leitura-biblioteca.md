# Cancelamento da leitura da Biblioteca

**Objetivo:** interromper a enumeração de pacotes quando a janela for fechada (RG-031 e RG-043).

**Abordagem:** sinal cooperativo na enumeração e na leitura de cada pacote, com exceção explícita para evitar resultado parcial. Ao fechar, sinalizar a tarefa; preservar carregadores injetados existentes.
