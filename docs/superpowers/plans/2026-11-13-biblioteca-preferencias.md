# Preferências da Biblioteca

**Roadmap:** RG-031. Guardar a ordenação e os filtros por situação, falhas,
idiomas e motor, sem guardar a busca textual. Restaurar apenas valores válidos
e disponíveis; se a leitura da biblioteca falhar ou ainda estiver em curso,
não substituir a preferência anterior. Gravar a seção por atualização
concorrente segura, sem sobrescrever rascunhos ou outras configurações.

**Teste:** validação de valores inválidos, reabertura, opções removidas,
proteção de dados concorrentes e falha da leitura da biblioteca.
