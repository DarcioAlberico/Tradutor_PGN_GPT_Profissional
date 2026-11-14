# Concorrência na curadoria

**Objetivo:** serializar a leitura da decisão e a gravação de uma regra com as
ações de ignorar/restaurar, usando o bloqueio já compartilhado das configurações.
Nenhuma operação deve segurar esse bloqueio durante diálogos ou varreduras.

**Verificação:** uma decisão ignorada impede a gravação; ignorar em outra thread
aguarda a conclusão da criação; erros não deixam o bloqueio preso e o catálogo
conserva suas verificações de revisão.
