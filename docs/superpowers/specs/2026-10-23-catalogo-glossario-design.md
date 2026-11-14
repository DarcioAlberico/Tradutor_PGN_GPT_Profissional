# Catálogo autoritativo do glossário

## Intenção

Eliminar o risco P0 de perda ou alteração da regra errada. O SQLite deixa de ser um índice descartável do `Substituicoes.txt` e passa a ser o catálogo autoritativo. Cada entrada recebe identidade persistente e revisão própria; toda alteração é transacional e rejeita estado obsoleto.

## Objetivos

- Usar uma única identidade canônica em deduplicação, diagnóstico, localização, edição, exclusão e importação.
- Preservar como distintas regras iguais em fases ou escopos diferentes.
- Editar e excluir por `id` e `revision`, nunca por posição nem pela primeira correspondência textual.
- Migrar instalações atuais sem perder ordem, fase, prioridade ou escopo.
- Manter `Substituicoes.txt` como representação legível e exportável, mas não como segunda fonte concorrente.
- Apresentar conflitos de concorrência na interface e permitir recarregar antes de tentar novamente.

## Não objetivos deste recorte

- Explicação completa de precedência de GL-003.
- Simulação de impacto de GL-004 além do fluxo automático já existente.
- Curadoria automática de GL-005.
- Redesenho visual geral do editor.
- Sincronização do catálogo entre computadores.

## Abordagens consideradas

1. Corrigir apenas comparações em tuplas. É pequena, mas não oferece identidade persistente nem concorrência otimista.
2. Manter o texto autoritativo e usar hash do arquivo como revisão. Reduz a migração, porém qualquer edição reescreve o catálogo inteiro e IDs continuam artificiais.
3. **Escolhida:** tornar SQLite autoritativo, com IDs e revisões persistentes. É a única que satisfaz integralmente GL-001 e GL-002 e concentra invariantes num módulo profundo.

## Modelo de domínio

Uma `GlossaryEntry` contém:

- `id`: UUID textual imutável;
- `revision`: inteiro positivo, iniciado em 1 e incrementado a cada update;
- `original_text` e `replacement_text` normalizados nas pontas;
- `rule_type` normalizado;
- `scope` normalizado;
- `priority`, mutável e fora da identidade canônica;
- `position`, mutável e fora da identidade canônica;
- timestamps de criação e atualização.

A identidade canônica é `(original_text, replacement_text, rule_type, scope)`. A comparação textual permanece sensível a caixa, preservando o comportamento atual. A normalização de fase e escopo ocorre antes de consultar ou gravar.

O catálogo também possui `catalog_revision`, incrementada uma vez por transação mutante. Ela protege operações em lote, reordenação, importação e deduplicação. A `revision` da entrada protege update e delete individuais.

## Módulo e interface

Criar um módulo profundo `GlossaryCatalog` na seam de persistência. A interface mínima será:

- `list_entries() -> CatalogSnapshot`
- `add(entry, expected_catalog_revision) -> MutationResult`
- `update(id, expected_revision, changes) -> MutationResult`
- `delete(id, expected_revision) -> MutationResult`
- `deduplicate(expected_catalog_revision) -> MutationResult`
- `import_entries(entries, mode, expected_catalog_revision) -> ImportResult`
- `export_legacy(path) -> ExportResult`
- `backup(path) -> BackupResult`
- `restore(backup_path, expected_catalog_revision) -> RestoreResult`

`CatalogSnapshot` contém entradas e `catalog_revision`. Chamadores de tradução recebem uma projeção imutável das regras, sem conhecer SQL, IDs ou migração. O editor usa os registros completos.

Conflitos têm erro tipado (`GlossaryConflictError`) com ID, revisão esperada, revisão atual e estado atual quando existir. Identidade duplicada tem erro separado (`GlossaryDuplicateError`). Nenhuma dessas condições escolhe uma linha implicitamente.

## Esquema e invariantes

O catálogo novo usa o caminho `glossario-v2.db`. Isso impede que versões antigas, que conhecem apenas `glossario.db`, reconstruam ou sobrescrevam o banco novo. O schema adiciona `stable_id TEXT NOT NULL`, `revision INTEGER NOT NULL DEFAULT 1` e mantém o `id` inteiro apenas como chave interna. Um índice único cobre os quatro campos da identidade canônica. `catalog_revision` fica em `glossary_metadata`.

Invariantes:

- `stable_id` nunca muda;
- `revision >= 1` e aumenta exatamente uma vez por update bem-sucedido;
- identidade canônica é única;
- posições são únicas e densas após operações em lote;
- toda mutação de dados e metadados ocorre numa única transação `BEGIN IMMEDIATE`;
- update/delete usam `WHERE stable_id = ? AND revision = ?` e exigem exatamente uma linha afetada;
- falha de persistência faz rollback integral;
- leitura nunca reconstrói silenciosamente o banco a partir do arquivo legado.

## Migração

1. Antes da primeira migração, criar cópia recuperável do banco existente e do `Substituicoes.txt`. Qualquer falha de backup interrompe a migração antes de escrever o catálogo novo. Os arquivos recebem timestamp e nunca são sobrescritos.
2. Abrir transação exclusiva de migração e acrescentar as novas colunas/tabelas.
3. Ler o arquivo legado com `deduplicate=False`, preservando ordem e detalhes. Como ele é a fonte autoritativa das versões anteriores, ele vence um cache antigo divergente. Se estiver ausente ou inválido, a migração aborta e oferece recuperação explícita pelo backup/banco antigo; nunca escolhe automaticamente uma fonte potencialmente incompleta.
4. Para identidades canônicas repetidas, conservar a primeira e registrar as demais num relatório de migração; regras que diferem em fase ou escopo permanecem.
5. Gerar UUID para cada entrada importada, iniciar `revision=1`, normalizar posições e gravar a versão do schema.
6. Validar contagem, unicidade, escopos conhecidos e leitura completa antes do commit.
7. Após o commit, exportar atomicamente uma representação compatível para `Substituicoes.txt`.

Se já existir catálogo no schema novo, a inicialização nunca o substitui pelo texto. Divergência externa do arquivo é informada; sua incorporação exige importação explícita com prévia. Assim, um editor externo não pode apagar IDs e revisões silenciosamente.

## Compatibilidade e exportação

`Substituicoes.txt` passa a ser um espelho/exportação legível, atualizado atomicamente e de forma síncrona após cada transação confirmada. Falha ao atualizar o espelho não desfaz uma transação SQLite já confirmada; a mutação retorna sucesso com aviso. `mirror_pending=1` e o erro sanitizado ficam em `glossary_metadata`; inicialização e mutações posteriores tentam exportar novamente o snapshot mais recente antes de limpar o aviso. A aplicação nunca lê esse espelho como fonte após a migração.

CSV continua sendo intercâmbio. Por padrão não exporta IDs internos. Neste recorte, `mode` aceita apenas `append`: entradas novas são acrescentadas, duplicatas de identidade completa são ignoradas e “conflitante” significa mesmo original/fase/escopo com substituição diferente. Substituição integral é feita somente pela restauração validada de um backup, não por CSV. A prévia mostra por linha `nova`, `duplicada`, `conflitante` ou `inválida` e só grava após confirmação.

Fase e escopo reutilizam exatamente os normalizadores e valores válidos atuais. Fase vazia continua significando `suggestion`; escopo vazio continua significando global. Valores legados desconhecidos não são reinterpretados: a migração aborta com relatório, evitando fundir identidades por coerção.

## Concorrência

SQLite usa WAL, `busy_timeout` e transações curtas. O editor guarda `stable_id`, `revision` e `catalog_revision` do snapshot exibido. Se outra janela alterar a mesma entrada, salvar/excluir recebe conflito, mostra os valores exibido e atual e oferece apenas recarregar ou cancelar. Não há sobrescrita forçada neste recorte.

Operações em lote exigem a mesma `catalog_revision` exibida. Se qualquer alteração ocorreu desde a prévia, a operação inteira é recusada e deve ser recalculada.

## Interface do usuário

- A seleção guarda ID e revisão, não índice nem tupla textual.
- Em conflito: “Esta entrada mudou desde que foi aberta”, com comparação entre versão exibida e atual.
- “Deduplicar” mostra somente duplicatas da identidade completa e exige snapshot atual.
- Ações legadas que não possuem identidade suficiente são desativadas até recarregar a entrada completa.
- O rodapé mostra estado do catálogo e falha de atualização do espelho, sem ocultar que o banco continua íntegro.

## Backup, restauração e rollback

Backups passam a usar a API de backup do SQLite para produzir cópia consistente. A restauração faz parte deste recorte: valida schema e integridade em arquivo temporário, exige a `catalog_revision` atual, substitui o catálogo apenas após validação e força todas as janelas a recarregar snapshots. O arquivo texto permanece exportável, mas restaurá-lo significa importação explícita, não substituição silenciosa.

Rollback de versão: a cópia pré-migração e o texto legado permitem voltar manualmente. Uma versão antiga continua isolada em `glossario.db`; não conhece nem modifica `glossario-v2.db`. Ao retornar à versão nova, divergência do espelho é avisada e nunca importada automaticamente.

## Testes de aceite

- Mesmos textos em `suggestion/pt`, `suggestion/it` e `cleanup/pt` sobrevivem à deduplicação.
- Prioridades diferentes da mesma identidade são duplicatas; a primeira é mantida na migração e o relatório registra a removida.
- Update e delete com revisão antiga não alteram nenhuma linha.
- Duas janelas alterando entradas diferentes têm sucesso; alterando a mesma, a segunda recebe conflito.
- Importação, diagnóstico e validação concordam sobre duplicidade.
- Migração preserva ordem e detalhes e pode ser repetida sem trocar IDs.
- Falha injetada em qualquer etapa da migração deixa o catálogo antigo utilizável.
- Falha ao exportar o espelho não corrompe nem reverte o catálogo.
- Tradução consome o mesmo conjunto e ordem de regras antes e depois da migração.

## Riscos e controles

- **Migração destrutiva:** backups prévios, transação única e validação antes do commit.
- **Dois autores persistentes:** texto vira explicitamente espelho, nunca fallback silencioso.
- **Grande raio de mudança:** compatibilidade por projeções e migração em etapas cobertas por testes.
- **Banco bloqueado:** transações curtas, timeout e mensagem específica.
- **Versão antiga:** schema incompatível falha de forma explícita e preserva os backups.
