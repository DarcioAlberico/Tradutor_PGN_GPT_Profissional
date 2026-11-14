# Curadoria: ignorar e restaurar candidatos

**Objetivo:** avançar RG-022 permitindo ocultar candidatos rejeitados e
restaurá-los. A decisão pertence à obra, par de idiomas e troca; os textos e
caminhos não são escritos no arquivo de configurações. A atualização usa o
bloqueio transacional existente e não altera catálogo nem traduções.

**Verificação:** persistência, isolamento entre obras e idiomas, restauração,
concorrência e comportamento da janela quando os dados não podem ser gravados.
