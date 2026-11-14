# Cancelamento da verificação de integridade

**Objetivo:** permitir interromper a leitura dos arquivos de um pacote na Biblioteca (RG-031 e RG-043).

**Abordagem:** conferir um sinal de cancelamento antes e entre blocos de leitura, retornar estado explícito e oferecer comando na janela. Fechar a janela também sinaliza o cancelamento. Não alterar arquivos nem apresentar resultado parcial como válido.

**Verificação:** testar cancelamento antes e durante a leitura, resultado normal, integridade modificada e jornada pela janela.
