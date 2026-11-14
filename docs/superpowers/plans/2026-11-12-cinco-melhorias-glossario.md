# Cinco melhorias no editor de glossário — RG-024

1. Fazer a prévia da regra selecionada respeitar sua fase, inclusive normalização de espaços da limpeza.
2. Atualizar a prévia ao editar texto, tipo, prioridade ou escopo; alterações de escopo devem marcar o formulário como modificado.
3. Explicar os três tipos com exemplos em ajuda acessível no controle de tipo.
4. Oferecer atalhos opcionais de prioridade -1, 0 e +1, preservando o campo numérico avançado.
5. Oferecer atalhos de escopo global, destino e par atuais; sem idioma declarado, não substituir o campo e avisar o usuário.

Testar resultados do pipeline, atualização imediata, estados inválidos/sem idioma, ajuda e preservação de valores personalizados em janelas reais. Evitar gravar automaticamente ou alterar regras existentes; executar suíte focada nas duas cópias.
