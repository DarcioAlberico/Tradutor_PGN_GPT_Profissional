# Simulação comparativa do glossário

**Objetivo:** avançar RG-021 medindo diferenças entre versões de regras sem escrita.

**Interface:** receber textos com idiomas de origem e destino e duas listas de
entradas do catálogo; avaliar as regras automáticas reais para cada par e
retornar contagens e exemplos limitados. Cancelamento interrompe a simulação
sem devolver um resultado parcial como completo. Regras são preparadas por par.

**Validação:** precedência, escopo, exemplos limitados, iterador de entrada,
cancelamento e ausência de alterações no catálogo ou nos textos originais.
