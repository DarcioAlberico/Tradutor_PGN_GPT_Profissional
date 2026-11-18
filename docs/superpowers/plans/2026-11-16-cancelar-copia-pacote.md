# Cancelamento durante cópia de pacote

**Objetivo:** interromper cópias grandes ao cancelar a tradução (RG-000B).

**Abordagem:** verificar cancelamento entre blocos, sem publicar dados parciais; manter o comportamento existente para chamadores sem sinal de cancelamento.

**Validação:** simular cancelamento após início da cópia e confirmar preservação do original e ausência de pacote publicado.
