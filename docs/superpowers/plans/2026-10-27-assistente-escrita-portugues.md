# Assistente de Escrita em Português Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar um assistente pt-BR offline com ortografia acionável, concordância opcional via LanguageTool local, painel lateral produtivo e distribuição autocontida com Java reduzido.

**Architecture:** `PortugueseWritingAssistant` é o módulo profundo independente de Tk. Ele combina proteção de texto, `SpyllsAdapter`, `LanguageToolLocalAdapter`, vocabulário pessoal e supressões numa interface imutável versionada; um controlador assíncrono adapta essa interface ao editor. O LanguageTool 6.6 roda num processo auxiliar persistente preso a loopback sobre um runtime Temurin 17 reduzido e empacotado pelo projeto.

**Tech Stack:** Python 3.10+, Tk/CustomTkinter, spylls, LanguageTool 6.6, Eclipse Temurin 17.0.20.1+1, HTTP loopback, PyInstaller onedir, Inno Setup, pytest/unittest, Hypothesis.

**Spec:** `docs/superpowers/specs/2026-10-27-assistente-escrita-portugues-design.md`

## Global Constraints

- Nenhum texto do usuário sai da máquina; não implementar LanguageTool remoto.
- `grammar_enabled` começa `false`; `spelling_enabled` começa `true`.
- Nenhuma sugestão altera texto sem gesto explícito do usuário.
- Resultados só podem ser aplicados quando `text_version` e trecho original ainda coincidirem.
- SAN, NAGs, tags `[%...]`, URLs, nomes da origem e termos do glossário são protegidos.
- LanguageTool inicia sem `--public`, sem `--allow-origin` e com `language=pt-BR` explícito.
- Uma falha permite no máximo um reinício; depois a sessão fica em `spelling_only`.
- Logs, métricas e diagnósticos nunca guardam o texto analisado.
- O vocabulário pessoal é global e gravado atomicamente na pasta de dados.
- Ação em massa limita-se ao livro aberto, exige confirmação e é uma única ação de desfazer.
- Precisão ≥ 95% e recall ≥ 80% no corpus de alta confiança antes de chamar concordância de estável.
- Compatibilidade: Windows x64, execução do fonte e PyInstaller onedir/portátil/instalável.
- LanguageTool 6.6 é a última distribuição estável fixa e requer Java 17; snapshots diários não entram neste release reproduzível.
- O runtime base é Eclipse Temurin JDK 17.0.20.1+1 x64; downloads e arquivos derivados precisam de SHA-256 fixado.
- O checkout já contém mudanças do usuário; cada commit usa staging seletivo e nunca inclui/reverte hunks preexistentes fora desta feature.

## Review Focus

- Texto muda enquanto análise está em voo: resultado antigo é descartado e nenhum widget destruído é acessado — Task 5.
- Unicode com acentos, emoji e hífen: offsets protegidos e sugestões apontam para o trecho correto — Tasks 1 e 5.
- LanguageTool trava, demora ou morre no fechamento: uma reinicialização, fallback visível e nenhum processo órfão — Task 4.
- Aplicar todas encontra trecho já editado ou sobreposto: aborta atomicamente, sem alteração parcial — Task 6.
- Instalação limpa sem Java do sistema nem internet: ortografia, concordância e desligamento funcionam no artefato — Task 8.

---

### Task 1: Modelo imutável, corpus e proteção de texto

**Files:**
- Create: `tradutor_pgn/writing_types.py`
- Create: `tradutor_pgn/writing_protection.py`
- Create: `tests/fixtures/portuguese_writing_corpus.json`
- Create: `tests/test_writing_types.py`
- Create: `tests/test_writing_protection.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: `annotation_mask` e normalizadores existentes, apenas como implementação interna.
- Produces: `WritingRequest`, `WritingIssue`, `WritingResult`, `AssistantStatus`, `ProtectedText`, `protect_text(request) -> ProtectedText` e `restore_issue_offsets(...)`.

- [ ] **Step 1: Escrever testes falhos dos tipos e invariantes**

Cobrir imutabilidade, categorias válidas, sugestões limitadas a cinco, spans dentro do texto, `issue_id` estável e rejeição de `text_version`/offset inválidos em `tests/test_writing_types.py`.

- [ ] **Step 2: Executar o RED do modelo**

Run: `uv run python -m pytest tests/test_writing_types.py -q`
Expected: FAIL porque `writing_types` não existe.

- [ ] **Step 3: Implementar os tipos públicos**

Implementar exatamente as dataclasses do design e `IssueCategory`, `AssistantMode`, `AssistantState` como `Literal`/enum serializável em `tradutor_pgn/writing_types.py`.

- [ ] **Step 4: Criar o corpus versionado e seus validadores**

Cada caso JSON contém `id`, `text`, `source_text`, `glossary_terms`, `expected_issues`, `forbidden_ranges` e `notes`; incluir TA-004, frases corretas, concordância nominal/verbal, repetição, pontuação, SAN/NAG/tags, nomes, termos do glossário, emoji e casos ambíguos.

- [ ] **Step 5: Escrever RED da proteção e offsets Unicode**

Testar `13.Cd4`, `[%eval +0.35]`, `$5`, roque, URLs, nomes vindos da origem, termos multi-palavra do glossário, acentos, emoji e issue cruzando intervalo protegido.

- [ ] **Step 6: Implementar proteção sem alterar comprimento lógico**

`ProtectedText` mantém texto projetado, mapa de índices e intervalos tipados; reusar parsers existentes onde a semântica coincide, sem duplicar regex de anotação.

- [ ] **Step 7: Adicionar property-based tests de round-trip**

Adicionar `hypothesis` ao grupo `dev`; gerar Unicode e intervalos válidos para provar que proteger/restaurar conserva offsets e nunca retorna span fora do original.

- [ ] **Step 8: Verificar e commitar**

Run: `uv run python -m pytest tests/test_writing_types.py tests/test_writing_protection.py -q`
Expected: PASS.

```bash
git add tradutor_pgn/writing_types.py tradutor_pgn/writing_protection.py tests/fixtures/portuguese_writing_corpus.json tests/test_writing_types.py tests/test_writing_protection.py pyproject.toml uv.lock
git commit -m "feat: define portuguese writing issue model"
```

### Task 2: Vocabulário pessoal global e preferências

**Files:**
- Create: `tradutor_pgn/personal_dictionary.py`
- Create: `tests/test_personal_dictionary.py`
- Modify: `tradutor_pgn/settings.py`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Consumes: `data_path`, `update_settings`, escrita atômica já usada em settings.
- Produces: `PersonalDictionary.load/add/remove/contains/list_words`, `WritingSettings`, `read_writing_settings()` e `write_writing_settings()`.

- [ ] **Step 1: Escrever testes falhos do vocabulário global**

Cobrir arquivo ausente, Unicode NFC, comparação sem caixa, preservação da grafia exibida, add idempotente, remove, duas instâncias concorrentes, corrupção recuperável e falha antes do replace preservando o anterior.

- [ ] **Step 2: Executar RED e implementar armazenamento versionado**

Run: `uv run python -m pytest tests/test_personal_dictionary.py -q`
Expected: FAIL por módulo ausente.

Criar `vocabulario-pessoal.json` na pasta de dados, com `schema_version=1`, lista ordenada e publicação por temporário + `os.replace` sob lock estável entre processos. Toda escrita relê sob lock antes de mutar para duas instâncias não perderem palavras.

- [ ] **Step 3: Escrever testes falhos das preferências**

Cobrir defaults (`spelling_enabled=True`, `grammar_enabled=False`), categorias, `disabled_rule_ids`, JSON antigo/malformado e escrita concorrente sem apagar outras seções.

- [ ] **Step 4: Implementar seção `writing_assistant` em settings**

Adicionar `WRITING_DEFAULTS`, `read_writing_settings(settings) -> dict` e persistência por `write_settings_sections`, sem guardar palavras pessoais dentro do settings.

- [ ] **Step 5: Verificar e commitar**

Run: `uv run python -m pytest tests/test_personal_dictionary.py tests/test_settings.py -q`
Expected: PASS.

```bash
git add tradutor_pgn/personal_dictionary.py tradutor_pgn/settings.py tests/test_personal_dictionary.py tests/test_settings.py
git commit -m "feat: persist writing assistant preferences"
```

### Task 3: Adaptar a ortografia existente à nova interface

**Files:**
- Create: `tradutor_pgn/writing_assistant.py`
- Create: `tests/test_writing_assistant.py`
- Modify: `tradutor_pgn/prose_spellcheck.py`
- Modify: `tests/test_corretor.py`

**Interfaces:**
- Consumes: Task 1 types/protection; Task 2 `PersonalDictionary`; `prose_spellcheck` existente.
- Produces: `SpyllsAdapter.analyze(request, protected) -> tuple[WritingIssue, ...]` e `PortugueseWritingAssistant.analyze(request) -> WritingResult` em modo ortográfico.

- [ ] **Step 1: Escrever contratos falhos do adapter ortográfico**

Cobrir typo com sugestões, ordem estável e limite cinco; source/glossary/personal/session ignored; notação protegida; idioma sem dicionário; exceção de lookup; estado `suppressed_by_glossary` para conflito terminológico.

- [ ] **Step 2: Executar RED e implementar `SpyllsAdapter`**

Run: `uv run python -m pytest tests/test_writing_assistant.py -q`
Expected: FAIL por interface ausente.

Extrair comportamento de `prose_spellcheck` sem quebrar callers antigos; a compatibilidade antiga vira adapter fino e será removida da UI na Task 6.

- [ ] **Step 3: Implementar o módulo profundo em modo `spelling_only`**

O construtor aceita adapters/dependências; `analyze` protege, consulta ortografia, filtra/sort/deduplica e retorna resultado imutável com o mesmo `text_version`.

- [ ] **Step 4: Rodar corpus ortográfico e regressões existentes**

Run: `uv run python -m pytest tests/test_corretor.py tests/test_writing_assistant.py -q`
Expected: PASS e nenhuma mudança nos 95/27 casos medidos pelo teste existente.

- [ ] **Step 5: Commit**

```bash
git add tradutor_pgn/writing_assistant.py tradutor_pgn/prose_spellcheck.py tests/test_writing_assistant.py tests/test_corretor.py
git commit -m "feat: expose actionable spelling issues"
```

### Task 4: Processo auxiliar LanguageTool e adapter gramatical

**Files:**
- Create: `tradutor_pgn/languagetool_process.py`
- Create: `tradutor_pgn/languagetool_client.py`
- Create: `tests/test_languagetool_process.py`
- Create: `tests/test_languagetool_client.py`
- Modify: `tradutor_pgn/writing_assistant.py`
- Modify: `tests/test_writing_assistant.py`

**Interfaces:**
- Consumes: Task 1 `WritingIssue`; Task 3 assistant.
- Produces: `LanguageToolProcess.start/status/restart_once/shutdown`, `LanguageToolLocalAdapter.check(text, disabled_rule_ids)`, normalização de resposta e modo `full`.

- [ ] **Step 1: Escrever testes falhos do cliente HTTP**

Usar servidor HTTP falso para provar POST `/v2/check`, `language=pt-BR`, timeout, JSON inválido, HTTP error, offsets, até cinco replacements, `rule.id`, categorias e ausência de texto nos logs.

- [ ] **Step 2: Implementar `LanguageToolLocalAdapter`**

Usar `requests.Session` injetável e URL somente `http://127.0.0.1:<port>`; rejeitar host não-loopback no construtor.

- [ ] **Step 3: Escrever testes falhos do lifecycle**

Com executável filho falso: porta ocupada/retry, health check, startup timeout, processo que morre, uma reinicialização, segunda falha, shutdown idempotente, PID alheio não encerrado e stdout/stderr sem payload.

- [ ] **Step 4: Implementar `LanguageToolProcess`**

Localizar `runtime/bin/java.exe` e LanguageTool por `resource_path`; iniciar com lista de argumentos, `-Xms64m`, `-Xmx512m`, classpath, `HTTPServer`, `--config`, `--port`; omitir `--public` e `--allow-origin`. Gerar config privado sem logging de texto.

- [ ] **Step 5: Integrar gramática e classificação**

Mapear regras para categorias; preservar `rule_id`; suprimir spans protegidos/glossário; ordenar/deduplicar com ortografia; desligado não chama process/client.

- [ ] **Step 6: Verificar**

Run: `uv run python -m pytest tests/test_languagetool_process.py tests/test_languagetool_client.py tests/test_writing_assistant.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradutor_pgn/languagetool_process.py tradutor_pgn/languagetool_client.py tradutor_pgn/writing_assistant.py tests/test_languagetool_process.py tests/test_languagetool_client.py tests/test_writing_assistant.py
git commit -m "feat: add local languagetool grammar adapter"
```

### Task 5: Controlador assíncrono, cache e resultados obsoletos

**Files:**
- Create: `tradutor_pgn/writing_controller.py`
- Create: `tests/test_writing_controller.py`
- Modify: `tradutor_pgn/writing_assistant.py`

**Interfaces:**
- Consumes: `PortugueseWritingAssistant.analyze` e tipos da Task 1.
- Produces: `WritingController.submit(request)`, `poll()`, `cancel_context()`, `shutdown()`; eventos `status/result/error` sem Tk.

- [ ] **Step 1: Escrever testes falhos da fila latest-wins**

Provar uma análise ativa + uma pendente, descarte por versão/contexto, navegação, cancelamento lógico, shutdown durante análise e duas janelas compartilhando assistant sem misturar resultados.

- [ ] **Step 2: Implementar controlador com executor de um worker por contexto**

Nenhuma thread chama Tk; `poll()` é a única entrega. Chaves de contexto incluem janela/registro/idioma e versão.

- [ ] **Step 3: Escrever e implementar cache limitado**

Chave inclui texto/version-independent hash, idioma, grammar flag, glossário/vocabulário/rules revisions e versão dos adapters; LRU limitado, sem persistir texto em disco.

- [ ] **Step 4: Testar falha e fallback**

Erro do sidecar gera status/restart único; persistência do erro muda modo sem reenvio em loop; ortografia continua.

- [ ] **Step 5: Verificar e commitar**

Run: `uv run python -m pytest tests/test_writing_controller.py tests/test_writing_assistant.py -q`
Expected: PASS.

```bash
git add tradutor_pgn/writing_controller.py tradutor_pgn/writing_assistant.py tests/test_writing_controller.py tests/test_writing_assistant.py
git commit -m "feat: analyze portuguese writing asynchronously"
```

### Task 6: Painel lateral e ações editoriais

**Files:**
- Create: `tradutor_pgn/writing_panel.py`
- Create: `tests/test_writing_panel.py`
- Modify: `tradutor_pgn/edit_window.py`
- Modify: `tests/test_editor_windows.py`
- Modify: `tradutor_pgn/editor_common.py`
- Modify: `tradutor_pgn/database.py`
- Modify: `tests/test_banco.py`

**Interfaces:**
- Consumes: Task 5 controller/events; `WritingIssue`; operações de undo/draft do editor.
- Produces: painel, tags `writing_spelling`/`writing_grammar`, navegação F7/Shift+F7 e ações `apply_issue`, `apply_all_identical`, `ignore_once`, `ignore_session`, `add_personal_word`, `disable_rule`; operações transacionais `preview_identical_replacements(...)` e `apply_identical_replacements(...)` para o livro aberto.

- [ ] **Step 1: Escrever testes falhos do layout e estados**

Testar painel à direita, recolhimento manual/automático, cabeçalho/modos, lista ordenada, foco no span, tema, contraste não dependente só de cor e destruição sem callbacks tardias.

- [ ] **Step 2: Implementar `WritingPanel` sem lógica linguística**

Recebe snapshot de issues e callbacks; não instancia adapters nem lê settings diretamente.

- [ ] **Step 3: Escrever testes falhos de integração assíncrona**

Digitar incrementa versão/debounce; navegar cancela contexto; resultado velho não cria tags; fechar antes do resultado não toca widget; dicionário carregando e sidecar iniciando mantêm estado explícito.

- [ ] **Step 4: Integrar controller ao editor**

Substituir `highlight_spelling()` pelo fluxo novo, mantendo compatibilidade visual ortográfica e polling exclusivamente na thread Tk.

- [ ] **Step 5: Escrever testes falhos das ações e desfazer**

Aplicar atual, trecho divergente, Ctrl+Z; aplicar todas com confirmação/contagem, todas as linhas do livro atual, concorrência, overlap e rollback atômico; ignore once/session; personal global; disable rule; nenhuma cria glossário.

- [ ] **Step 6: Implementar ações por uma operação editorial comum**

Prévia lê IDs, revisões/textos e contagem no banco do livro. Confirmação abre transação, revalida todas as linhas, grava histórico por linha sob um mesmo `bulk_operation_id` e aplica todas ou nenhuma. “Desfazer” reverte esse ID numa transação única; conflito preserva tudo e pede nova prévia.

- [ ] **Step 7: Reconciliar F7 existente**

F7 navega ocorrência linguística quando o painel tem item ativo; caso contrário mantém “próximo aviso QA”. Shift+F7 volta; F1 documenta prioridade e atalhos.

- [ ] **Step 8: Verificar e commitar**

Run: `uv run python -m pytest tests/test_writing_panel.py tests/test_editor_windows.py tests/test_corretor.py tests/test_banco.py -q`
Expected: PASS.

```bash
git add tradutor_pgn/writing_panel.py tradutor_pgn/edit_window.py tradutor_pgn/editor_common.py tradutor_pgn/database.py tests/test_writing_panel.py tests/test_editor_windows.py tests/test_corretor.py tests/test_banco.py
git commit -m "feat: add portuguese writing review panel"
```

### Task 7: Configurações, vocabulário e regras desativadas

**Files:**
- Modify: `tradutor_pgn/settings_window.py`
- Modify: `tradutor_pgn/settings.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_main_window.py`
- Modify: `tests/test_editor_windows.py`

**Interfaces:**
- Consumes: Task 2 settings/dictionary; Task 4 process status.
- Produces: seção “Revisão linguística” em Configurações e atualização viva das janelas.

- [ ] **Step 1: Escrever testes falhos da configuração**

Ortografia on, concordância off; ligar concordância persiste/inicia lazy; desligar não mata sidecar usado por outra janela, mas impede novas análises; listas de palavras/regras, remover/reativar; salvar não apaga outras seções.

- [ ] **Step 2: Implementar a seção de UI**

Mostrar estado `Não iniciado/Iniciando/Completo/Somente ortografia/Indisponível`, motivo e botão de testar; mudanças publicam evento de configuração sem reiniciar aplicação.

- [ ] **Step 3: Testar e implementar gestão do vocabulário**

Lista pesquisável, remover com confirmação, add duplicado informado; alteração invalida cache e reanalisa janelas abertas.

- [ ] **Step 4: Testar e implementar regras desativadas**

Exibir rule ID + nome, reativar individualmente/todas; LanguageTool recebe disabled rules e cache muda de revisão.

- [ ] **Step 5: Verificar e commitar**

Run: `uv run python -m pytest tests/test_settings.py tests/test_main_window.py tests/test_editor_windows.py -q`
Expected: PASS.

```bash
git add tradutor_pgn/settings_window.py tradutor_pgn/settings.py tests/test_settings.py tests/test_main_window.py tests/test_editor_windows.py
git commit -m "feat: configure portuguese writing checks"
```

### Task 8: Aquisição reproduzível, jlink e empacotamento autocontido

**Files:**
- Create: `recursos/languagetool-lock.json`
- Create: `ferramentas/preparar_languagetool.py`
- Create: `tests/test_languagetool_packaging.py`
- Create: `LICENSES/LanguageTool-LGPL-2.1.txt`
- Create: `LICENSES/Eclipse-Temurin-GPL2-Classpath.txt`
- Modify: `.gitignore`
- Modify: `PGN_Tradutor_Pro.spec`
- Modify: `instalador/gerar-entregas.py`
- Modify: `instalador/empacotar-portatil.py`
- Modify: `instalador/PGN_Tradutor_Pro.iss`
- Modify: `.github/workflows/testes.yml`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Consumes: Task 4 resource layout.
- Produces: `build/vendor/languagetool`, `build/vendor/jdk`, `build/vendor/runtime`, lock de fontes/checksums e artefatos contendo `runtime/` + `languagetool/`.

- [ ] **Step 1: Escrever testes falhos do lock e download seguro**

O lock fixa LanguageTool 6.6 e Temurin 17.0.20.1+1 x64, URLs oficiais, SHA-256 literal, licenças e arquivos esperados. Testar URL não HTTPS, hash errado, ZIP traversal, cache válido e download parcial.

- [ ] **Step 2: Implementar aquisição reproduzível**

`preparar_languagetool.py fetch` baixa para temporário, verifica hash antes de extrair e publica em `build/vendor`; calcular e revisar os hashes oficiais na primeira execução e commitar os valores literais, nunca “latest”.

- [ ] **Step 3: Implementar runtime reduzido**

`preparar_languagetool.py runtime` usa `jdeps --ignore-missing-deps --multi-release 17` sobre o classpath e `jlink --strip-debug --no-header-files --no-man-pages --compress=2`; smoke test inicia o servidor e consulta pt-BR sem Java no PATH.

- [ ] **Step 4: Escrever testes falhos do conteúdo das entregas**

Exigir `runtime/bin/java.exe`, `languagetool-server.jar`, libs/dados pt-BR, config, lock, duas licenças; recusar chave, cache, logs, corpus do usuário ou JDK completo.

- [ ] **Step 5: Integrar PyInstaller, portátil e instalador**

O `.spec` coleta somente runtime reduzido/LanguageTool preparado; scripts falham antes do build se recursos/checksums/licenças faltarem; Inno inclui a árvore onedir sem depender de Java instalado.

- [ ] **Step 6: Integrar CI/release e SBOM**

CI unitário usa fakes; job Windows de release prepara vendor, gera runtime, smoke testa e publica SBOM/medidas. Fixar actions por SHA quando tocar o workflow.

- [ ] **Step 7: Medir e registrar o protótipo**

Registrar em `ROADMAP.md`: download, runtime final, aumento de `dist`/instalador, RSS cold/warm, startup e primeira análise. Se exceder 1 GB de RAM ou 10 s de startup no corpus de uma linha, parar a integração e revisar antes de declarar Task 8 pronta.

- [ ] **Step 8: Verificar e commitar**

Run: `uv run python -m pytest tests/test_languagetool_packaging.py tests/test_settings.py -q`
Run: `uv run python ferramentas/preparar_languagetool.py smoke`
Expected: PASS sem Java do sistema no PATH do subprocesso de smoke.

```bash
git add recursos/languagetool-lock.json ferramentas/preparar_languagetool.py tests/test_languagetool_packaging.py LICENSES PGN_Tradutor_Pro.spec instalador .github/workflows/testes.yml .gitignore tests/test_settings.py ROADMAP.md
git commit -m "build: bundle languagetool with reduced java runtime"
```

### Task 9: Corpus real, precisão, desempenho e métricas locais

**Files:**
- Create: `ferramentas/avaliar_corretor_portugues.py`
- Create: `tradutor_pgn/writing_metrics.py`
- Create: `tests/test_writing_corpus.py`
- Create: `tests/test_writing_performance.py`
- Create: `tests/test_writing_metrics.py`
- Modify: `tradutor_pgn/writing_assistant.py`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: assistant completo e corpus da Task 1.
- Produces: relatório JSON/Markdown agregado, métricas locais sem payload e gate de precisão/recall.

- [ ] **Step 1: Escrever avaliador determinístico do corpus**

Calcular precisão/recall por categoria, falsos positivos, misses, sugestões e intervalos protegidos; saída lista apenas IDs dos casos e rule IDs, não textos.

- [ ] **Step 2: Criar baseline Spylls e baseline LanguageTool**

Run: `uv run python ferramentas/avaliar_corretor_portugues.py --mode spelling`
Run: `uv run python ferramentas/avaliar_corretor_portugues.py --mode full`
Expected: arquivos em `build/reports/` com métricas reproduzíveis.

- [ ] **Step 3: Triar regras ruidosas por ID**

Somente suprimir casos documentados no corpus. Não ajustar thresholds para “passar” sem revisar cada falso positivo.

- [ ] **Step 4: Escrever testes de desempenho**

Ortografia p95 ≤ 20 ms/linha; gramática warm p95 ≤ 500 ms/comentário; corpus grande não bloqueia Tk e cache é limitado. Marcar benchmarks de máquina como relatório, mantendo testes CI com teto frouxo contra regressão catastrófica.

- [ ] **Step 5: Persistir métricas agregadas locais**

Criar `writing-metrics.db` global na pasta de dados, com schema/versionamento para contagens por categoria/ação/rule ID e data; proibir coluna de texto/span/sugestão. Não usar o banco por livro. Falha métrica nunca impede correção.

- [ ] **Step 6: Aplicar gate de produto**

Se precisão/recall não atingirem 95%/80%, manter `grammar_enabled` rotulada “Experimental” e registrar gaps; nunca mudar o default false.

- [ ] **Step 7: Verificar e commitar**

Run: `uv run python -m pytest tests/test_writing_corpus.py tests/test_writing_performance.py tests/test_writing_metrics.py -q`
Expected: PASS.

```bash
git add ferramentas/avaliar_corretor_portugues.py tradutor_pgn/writing_metrics.py tests/test_writing_corpus.py tests/test_writing_performance.py tests/test_writing_metrics.py tradutor_pgn/writing_assistant.py ROADMAP.md
git commit -m "test: gate portuguese writing quality"
```

### Task 10: Documentação, migração e validação integrada

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `REVISAO_GERAL.md`
- Modify: `REVISAO_GERAL_SPEC.md` somente para esclarecer contratos, sem reduzir critérios.
- Modify: `CONTEXT.md`
- Test: suíte completa e artefatos.

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: release verificável e documentação operacional.

- [ ] **Step 1: Documentar uso e recuperação**

Explicar painel/atalhos, defaults, vocabulário global, regras, privacidade, modos, fallback, localização de dados, tamanho esperado e como diagnosticar sidecar sem expor texto.

- [ ] **Step 2: Testar migração de configuração existente**

Abrir settings antigos sem seção, preservar todas as chaves, criar defaults, atualizar/voltar versão sem crash e remover recursos opcionais sem impedir abertura.

- [ ] **Step 3: Rodar regressões focadas**

Run: `uv run python -m pytest tests/test_corretor.py tests/test_writing_types.py tests/test_writing_protection.py tests/test_personal_dictionary.py tests/test_writing_assistant.py tests/test_languagetool_process.py tests/test_languagetool_client.py tests/test_writing_controller.py tests/test_writing_panel.py tests/test_writing_corpus.py tests/test_writing_performance.py tests/test_settings.py tests/test_editor_windows.py -q`
Expected: PASS.

- [ ] **Step 4: Rodar verificações estáticas**

Run: `uv run ruff check .`
Expected: `All checks passed!`.

Run: `uv run mypy`
Expected: `Success: no issues found`; incluir os novos módulos tipados na lista `tool.mypy.files`.

- [ ] **Step 5: Rodar suíte completa**

Run: `uv run python -m pytest -q`
Expected: PASS sem novos skips fora dos explicitamente documentados.

- [ ] **Step 6: Validar entregas Windows**

Run: `uv run python instalador/gerar-entregas.py`
Run: `powershell -ExecutionPolicy Bypass -File instalador/verificar-ciclo.ps1`
Expected: portátil e instalável abrem sem Java do sistema, detectam TA-004, desligam sidecar no fechamento e contêm licenças/SBOM.

- [ ] **Step 7: Verificar privacidade e integridade**

Buscar no log/temporários/relatórios o texto-sentinela do smoke; esperar zero ocorrências. Rodar `git diff --check` e confirmar ausência de JDK completo, ZIPs, corpus protegido, caches, PIDs e logs no commit.

- [ ] **Step 8: Commit**

```bash
git add README.md ROADMAP.md REVISAO_GERAL.md REVISAO_GERAL_SPEC.md CONTEXT.md pyproject.toml
git commit -m "docs: ship portuguese writing assistant"
```
