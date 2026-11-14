# Catálogo de Glossário V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar o glossário para um catálogo SQLite autoritativo com IDs estáveis, revisões, identidade canônica uniforme e operações concorrentes seguras.

**Architecture:** Um novo módulo profundo `GlossaryCatalog` concentra schema, migração, identidade, transações, concorrência, backup e espelho legado. `glossario.py` mantém adaptadores compatíveis para o pipeline de tradução; o editor passa a operar sobre snapshots com `stable_id` e `revision` em vez de índices e tuplas ambíguas.

**Tech Stack:** Python 3.10+, SQLite, `dataclasses`, `uuid`, CustomTkinter, pytest/unittest, uv.

**Spec:** `docs/superpowers/specs/2026-10-23-catalogo-glossario-design.md` e `REVISAO_GERAL_SPEC.md` GL-001/GL-002.

## Global Constraints

- `glossario-v2.db` é a única fonte autoritativa depois da migração.
- Identidade canônica: `(original_text, replacement_text, rule_type, scope)` normalizados; prioridade e posição ficam fora.
- `stable_id` é UUID textual imutável; `revision` começa em 1 e aumenta em cada update.
- Toda mutação usa transação curta `BEGIN IMMEDIATE`; conflito nunca escolhe a primeira entrada semelhante.
- `Substituicoes.txt` é espelho síncrono e formato explícito de importação, nunca fallback automático.
- Migração só começa após backups recuperáveis; falha em qualquer backup interrompe sem criar catálogo parcial.
- Preservar Python 3.10, Windows e empacotamento PyInstaller; nenhuma dependência nova.
- Preservar ordem e resultado das regras consumidas pelo pipeline de tradução.

## Review Focus

- Arquivo legado válido e banco-cache divergente: migrar do texto sem mesclar silenciosamente dados do cache.
- Falha entre commit SQLite e exportação do espelho: catálogo permanece íntegro e `mirror_pending` continua visível/reparável.
- Duas janelas alterando a mesma entrada: a segunda recebe conflito; entradas diferentes continuam editáveis.
- Migração interrompida e repetida: não troca IDs nem perde backups já produzidos.
- Versão antiga alterando `Substituicoes.txt` após a migração: V2 avisa divergência e não importa automaticamente.

---

### Task 1: Modelo, identidade e schema V2

**Files:**
- Create: `tradutor_pgn/glossary_types.py`
- Create: `tradutor_pgn/glossary_catalog.py`
- Modify: `tradutor_pgn/app_paths.py`
- Modify: `tradutor_pgn/glossario.py`
- Test: `tests/test_glossary_catalog.py`

**Interfaces:**
- Consumes: valores e aliases atuais de fase, prioridade e escopo extraídos de `tradutor_pgn.glossario`.
- Produces: `GlossaryEntry`, `CatalogSnapshot`, `MutationResult`, `GlossaryConflictError`, `GlossaryDuplicateError`, `canonical_identity(entry)`, `GlossaryCatalog.initialize()` e `GlossaryCatalog.list_entries()`.

- [ ] **Step 1: Escrever testes falhos do modelo e identidade**

Criar `GlossaryCatalogModelTests` provando que fase e escopo diferentes produzem identidades diferentes, prioridade/posição não alteram identidade, pontas dos textos são normalizadas e `stable_id`/`revision` aparecem no snapshot.

- [ ] **Step 2: Executar os testes e observar RED**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogModelTests -q`
Expected: FAIL porque `tradutor_pgn.glossary_catalog` ainda não existe.

- [ ] **Step 3: Implementar os tipos e a interface inicial**

Extrair constantes e normalizadores puros para `glossary_types.py`; `glossario.py` passa a importá-los e continua reexportando os nomes atuais. Criar dataclasses imutáveis e `canonical_identity(entry: GlossaryEntry | tuple) -> tuple[str, str, str, str]` usando esse módulo compartilhado, sem dependência circular.

- [ ] **Step 4: Escrever testes falhos do schema**

Testar `glossario-v2.db`, `stable_id TEXT NOT NULL UNIQUE`, `revision >= 1`, `catalog_revision=1`, WAL, `busy_timeout` e índice único da identidade completa.

- [ ] **Step 5: Implementar `GlossaryCatalog.initialize()` e `list_entries()`**

Assinaturas:

```python
class GlossaryCatalog:
    def __init__(self, db_path: str, mirror_path: str | None = None): ...
    def initialize(self) -> None: ...
    def list_entries(self) -> CatalogSnapshot: ...
```

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogModelTests tests/test_glossary_catalog.py::GlossaryCatalogSchemaTests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_types.py tradutor_pgn/glossary_catalog.py tradutor_pgn/app_paths.py tradutor_pgn/glossario.py tests/test_glossary_catalog.py
git commit -m "feat: add authoritative glossary catalog model"
```

### Task 2: Migração transacional do legado

**Files:**
- Modify: `tradutor_pgn/glossary_catalog.py`
- Modify: `tradutor_pgn/glossario.py`
- Test: `tests/test_glossary_catalog.py`
- Test: `tests/test_glossario.py`

**Interfaces:**
- Consumes: `GlossaryCatalog.initialize()`, parser legado `_load_glossary_entry_details_from_file(..., deduplicate=False)` por callback/adaptador.
- Produces: `MigrationReport` e `GlossaryCatalog.migrate_legacy(load_entries, legacy_db_path=None) -> MigrationReport`.

- [ ] **Step 1: Escrever testes falhos da migração normal**

Provar preservação de ordem, fase, prioridade e escopo; regras iguais em `suggestion/pt`, `suggestion/it` e `cleanup/pt` sobrevivem; duplicatas da identidade completa conservam a primeira e aparecem no relatório.

- [ ] **Step 2: Executar e observar RED**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMigrationTests -q`
Expected: FAIL pela ausência de `migrate_legacy`.

- [ ] **Step 3: Implementar backups prévios e migração**

Assinatura:

```python
def migrate_legacy(
    self,
    load_entries: Callable[[], Sequence[LegacyGlossaryEntry]],
    legacy_db_path: str | None = None,
) -> MigrationReport: ...
```

Usar arquivos de backup timestampados sem sobrescrita, UUID4, `revision=1`, transação única e relatório de duplicatas. O marcador de migração concluída torna repetição idempotente.

- [ ] **Step 4: Escrever testes falhos de falha e repetição**

Cobrir backup impossível, texto ausente/inválido, exceção no meio da inserção, banco-cache divergente, repetição preservando IDs e catálogo parcial inexistente após rollback.

- [ ] **Step 5: Completar rollback e validação pré-commit**

Validar `integrity_check`, contagem, identidades únicas, posições densas e valores de fase/escopo antes do commit.

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMigrationTests tests/test_glossario.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_catalog.py tradutor_pgn/glossario.py tests/test_glossary_catalog.py tests/test_glossario.py
git commit -m "feat: migrate legacy glossary into catalog v2"
```

### Task 3: Mutações com concorrência otimista

**Files:**
- Modify: `tradutor_pgn/glossary_catalog.py`
- Test: `tests/test_glossary_catalog.py`

**Interfaces:**
- Consumes: `GlossaryEntry`, `CatalogSnapshot` e schema da Task 1.
- Produces: `add`, `update`, `delete`, `deduplicate` e incremento consistente de `catalog_revision`.

- [ ] **Step 1: Escrever testes falhos de add/update/delete**

Testar UUID/revisão iniciais, update por `stable_id + expected_revision`, incremento de revisão, delete por revisão e erro de duplicidade da identidade completa.

- [ ] **Step 2: Executar e observar RED**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMutationTests -q`
Expected: FAIL por métodos ausentes.

- [ ] **Step 3: Implementar mutações individuais**

Assinaturas:

```python
def add(self, draft: GlossaryEntryDraft, expected_catalog_revision: int) -> MutationResult: ...
def update(self, stable_id: str, expected_revision: int, changes: GlossaryEntryChanges) -> MutationResult: ...
def delete(self, stable_id: str, expected_revision: int) -> MutationResult: ...
```

Cada método usa `BEGIN IMMEDIATE`, valida revisão dentro da transação e incrementa `catalog_revision` uma vez.

- [ ] **Step 4: Escrever testes falhos de concorrência e deduplicação**

Provar que duas instâncias alteram entradas diferentes, conflito na mesma entrada não grava, revisão antiga no delete não remove, e deduplicação preserva combinações fase × escopo.

- [ ] **Step 5: Implementar erro tipado e operação em lote**

```python
def deduplicate(self, expected_catalog_revision: int) -> MutationResult: ...
```

Recusar snapshot antigo integralmente.

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMutationTests tests/test_glossary_catalog.py::GlossaryCatalogConcurrencyTests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_catalog.py tests/test_glossary_catalog.py
git commit -m "feat: add revision-safe glossary mutations"
```

### Task 4: Espelho legado e adaptadores do pipeline

**Files:**
- Modify: `tradutor_pgn/glossary_catalog.py`
- Modify: `tradutor_pgn/glossario.py`
- Modify: `tradutor_pgn/app.py`
- Test: `tests/test_glossary_catalog.py`
- Test: `tests/test_glossario.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: snapshot e mutações das Tasks 1–3.
- Produces: `export_legacy`, recuperação de `mirror_pending` e projeções compatíveis para `load_glossary_entries`/`load_glossary_entry_details`.

- [ ] **Step 1: Escrever testes falhos do espelho**

Cobrir exportação atômica após mutação, falha pós-commit registrando `mirror_pending`, nova tentativa na inicialização e divergência externa apenas avisada.

- [ ] **Step 2: Executar e observar RED**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMirrorTests -q`
Expected: FAIL por exportação/estado pendente ausentes.

- [ ] **Step 3: Implementar exportação e reparo do espelho**

```python
def export_legacy(self, path: str | None = None) -> ExportResult: ...
def retry_pending_mirror(self) -> ExportResult | None: ...
```

Serializar snapshot confirmado em temporário no mesmo volume e usar `os.replace`; guardar erro sanitizado nos metadados.

- [ ] **Step 4: Escrever testes falhos de compatibilidade do pipeline**

Comparar, sobre o mesmo corpus, ordem e conteúdo das projeções antigas e V2; executar tradução com regras de todas as fases/escopos; provar que nenhum carregamento reconstrói V2 a partir do texto divergente.

- [ ] **Step 5: Adaptar `glossario.py` e inicialização da aplicação**

Manter funções públicas existentes como projeções do catálogo para consumidores não editoriais. Remover o caminho que chama `_glossary_database_needs_sync` no V2; migração só ocorre uma vez pelo inicializador explícito.

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_glossary_catalog.py::GlossaryCatalogMirrorTests tests/test_glossario.py tests/test_worker.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_catalog.py tradutor_pgn/glossario.py tradutor_pgn/app.py tests/test_glossary_catalog.py tests/test_glossario.py tests/test_worker.py
git commit -m "feat: serve glossary consumers from catalog v2"
```

### Task 5: Editor orientado por ID e revisão

**Files:**
- Modify: `tradutor_pgn/glossary_editor.py`
- Modify: `tradutor_pgn/edit_window.py`
- Modify: `tradutor_pgn/repeated_edits_window.py`
- Modify: `tests/test_editor_windows.py`
- Modify: `tests/test_editor.py`

**Interfaces:**
- Consumes: `CatalogSnapshot`, mutações e erros tipados das Tasks 1–3.
- Produces: seleção por `stable_id`, baseline com revisão e tratamento visível de concorrência.

- [ ] **Step 1: Escrever testes falhos do estado do editor**

Testar que seleção guarda `stable_id/revision/catalog_revision`, filtro e ordenação não alteram o alvo e save/delete enviam o ID da entrada selecionada.

- [ ] **Step 2: Executar e observar RED**

Run: `uv run python -m pytest tests/test_editor_windows.py::GlossaryEditorTests tests/test_editor_windows.py::GlossaryConflictEditorTests -q`
Expected: FAIL porque o editor ainda usa índice/tupla.

- [ ] **Step 3: Adaptar estado, seleção e mutações**

Substituir `current_baseline_entry()` e `find_glossary_entry_index` no fluxo editorial por identidade persistente. Índices ficam apenas como detalhe de apresentação.

- [ ] **Step 4: Escrever testes falhos de conflitos de duas janelas**

Simular snapshots simultâneos: alterações diferentes têm sucesso; mesma entrada mostra comparação, recarrega estado atual e nunca oferece sobrescrita forçada.

- [ ] **Step 5: Implementar a experiência de conflito e ações auxiliares**

Desabilitar ações sem registro completo, atualizar deduplicação para `catalog_revision` e adaptar inclusão pelo editor de traduções e candidatos de edições repetidas.

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_editor_windows.py tests/test_editor.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_editor.py tradutor_pgn/edit_window.py tradutor_pgn/repeated_edits_window.py tests/test_editor_windows.py tests/test_editor.py
git commit -m "feat: make glossary editor revision aware"
```

### Task 6: Importação, backup e restauração

**Files:**
- Modify: `tradutor_pgn/glossary_catalog.py`
- Modify: `tradutor_pgn/glossario.py`
- Modify: `tradutor_pgn/glossary_editor.py`
- Test: `tests/test_glossary_catalog.py`
- Test: `tests/test_glossario.py`
- Test: `tests/test_editor_windows.py`

**Interfaces:**
- Consumes: catálogo e concorrência das Tasks 1–5.
- Produces: importação `append`, backup SQLite consistente e restauração validada.

- [ ] **Step 1: Escrever testes falhos da prévia/importação**

Classificar cada linha como `new`, `duplicate`, `conflict` ou `invalid`; provar identidade completa consistente e recusa integral quando `catalog_revision` mudou após a prévia.

- [ ] **Step 2: Implementar importação append**

```python
def preview_import(self, entries: Sequence[LegacyGlossaryEntry]) -> ImportPreview: ...
def import_entries(self, entries: Sequence[LegacyGlossaryEntry], mode: Literal["append"], expected_catalog_revision: int) -> ImportResult: ...
```

- [ ] **Step 3: Escrever testes falhos de backup/restauração**

Cobrir backup consistente com conexão ativa, backup corrompido/incompatível recusado, revisão global antiga recusada, restauração atômica e snapshots anteriores invalidados.

- [ ] **Step 4: Implementar backup e restauração**

```python
def backup(self, destination: str) -> BackupResult: ...
def restore(self, backup_path: str, expected_catalog_revision: int) -> RestoreResult: ...
```

Usar `sqlite3.Connection.backup`, `PRAGMA integrity_check`, validação de schema em temporário e substituição somente após fechar conexões próprias.

- [ ] **Step 5: Adaptar CSV e interface de arquivos**

Exibir prévia por linha antes da confirmação; restauração de `.txt` vira importação, e restauração integral aceita somente backup SQLite V2 validado.

- [ ] **Step 6: Verificar a tarefa**

Run: `uv run python -m pytest tests/test_glossary_catalog.py tests/test_glossario.py tests/test_editor_windows.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/glossary_catalog.py tradutor_pgn/glossario.py tradutor_pgn/glossary_editor.py tests/test_glossary_catalog.py tests/test_glossario.py tests/test_editor_windows.py
git commit -m "feat: add safe glossary import and recovery"
```

### Task 7: Validação integrada e atualização do roadmap

**Files:**
- Modify: `REVISAO_GERAL.md`
- Modify: `REVISAO_GERAL_SPEC.md` somente se a implementação exigir esclarecer um contrato sem alterar intenção.
- Modify: `README.md` para documentar fonte autoritativa, espelho e recuperação.
- Test: suíte completa.

**Interfaces:**
- Consumes: todas as interfaces produzidas nas Tasks 1–6.
- Produces: evidência de conclusão de RG-000, GL-001 e GL-002.

- [ ] **Step 1: Executar regressões focadas e corrigir somente falhas causadas pela migração**

Run: `uv run python -m pytest tests/test_glossary_catalog.py tests/test_glossario.py tests/test_editor_windows.py tests/test_editor.py tests/test_worker.py -q`
Expected: PASS.

- [ ] **Step 2: Executar verificações estáticas**

Run: `uv run ruff check .`
Expected: `All checks passed!`

Run: `uv run mypy`
Expected: `Success: no issues found`.

- [ ] **Step 3: Executar a suíte completa**

Run: `uv run python -m pytest -q`
Expected: PASS sem testes ignorados novos.

- [ ] **Step 4: Verificar integridade do diff e documentação**

Run: `git diff --check`
Expected: sem erros de whitespace.

Atualizar roadmap com migração, comportamento de compatibilidade, recuperação e evidências exatas dos testes.

- [ ] **Step 5: Commit**

```bash
git add README.md REVISAO_GERAL.md REVISAO_GERAL_SPEC.md
git commit -m "docs: record glossary catalog v2 delivery"
```
