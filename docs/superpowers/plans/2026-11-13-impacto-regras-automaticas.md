# Impacto das alterações no glossário

**Objetivo:** avançar RG-021 e RG-024 protegendo alterações de regras automáticas.

**Implementação:** ao mudar texto, escopo ou prioridade de uma regra automática,
medir o impacto antes de salvar e explicar que a simulação aplica a regra
isoladamente. Alterações sem efeito semântico não devem pedir confirmação.

**Verificação:** testes para alterações de prioridade, escopo, texto, regra sem
alteração e recusa da confirmação; executar os testes existentes da promoção.
