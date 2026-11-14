# Marco 0 — Publicação Segura Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar dependências TLS conhecidamente vulneráveis e garantir que um pacote traduzido só apareça como concluído quando original e tradução tiverem sido publicados integralmente.

**Architecture:** O worker continuará traduzindo e gerando PGN por streaming, mas publicará o pacote por um módulo profundo com diretório temporário no mesmo volume e renomeação atômica. Falhas de entrega impedem o estado `completed`; falhas parciais de comentários preservam o comportamento anterior de gerar uma saída revisável com aviso.

**Tech Stack:** Python 3.10+, SQLite, CustomTkinter, pytest/unittest, uv.

**Spec:** `REVISAO_GERAL_SPEC.md` — TR-002, TR-006, DS-004 e TA-002. O manifesto de TR-007 fica para o Marco 2.

## Global Constraints

- Preservar o conteúdo e a codificação do PGN original.
- Não sobrescrever pacotes anteriores.
- Não deixar arquivo final parcial nem pacote final incompleto.
- Cancelamento durante a geração não pode ser registrado como sucesso.
- Não fazer chamadas de rede reais nos testes.
- Preservar compatibilidade com Python 3.10 e Windows/PyInstaller.

## Review Focus

- Falha depois de o PGN temporário ter começado a ser escrito não altera o pacote final.
- Cancelamento na geração final produz execução cancelada, não concluída.
- Falha ao copiar/publicar o original produz falha de entrega visível e reprocessável.
- Duas traduções com o mesmo nome não se sobrescrevem.
- Um arquivo de origem alterado durante a execução não mistura snapshots silenciosamente.

---

### Task 1: Atualizar a cadeia TLS travada

**Files:**
- Modify: `uv.lock`
- Verify: `pyproject.toml`, `requirements.txt`, `PGN_Tradutor_Pro.spec`, `instalador/gerar-entregas.py`

**Interfaces:**
- Consumes: restrições existentes `requests>=2.32`.
- Produces: resolução com `certifi>=2026.10.19` e `urllib3>=2.8.0`.

- [x] Atualizar somente `certifi` e `urllib3` pelo `uv`.
- [x] Verificar versões resolvidas e executar os testes de API/LLM/log.
- [x] Registrar que artefatos existentes em `dist/` precisam ser reconstruídos e não são prova da nova resolução.

### Task 2: Especificar publicação transacional por testes

**Files:**
- Create: `tradutor_pgn/translation_output.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_pgn.py`

**Interfaces:**
- Consumes: `translated_bundle_paths(...)` e geração de PGN por streaming.
- Produces: `publish_translation_bundle(...) -> TranslationBundleResult`.

- [x] Escrever teste que injeta falha depois de escrita parcial e exige ausência do pacote final.
- [x] Executar e observar falha pelo comportamento ainda inexistente.
- [x] Escrever teste de publicação bem-sucedida contendo original e traduzido.
- [x] Executar e observar falha pelo comportamento ainda inexistente.

### Task 3: Implementar o publicador de pacote

**Files:**
- Create: `tradutor_pgn/translation_output.py`
- Modify: `tradutor_pgn/pgn_utils.py`
- Test: `tests/test_pgn.py`

**Interfaces:**
- Consumes: caminho de origem, raiz de saída, idioma e callback de geração.
- Produces: resultado tipado com caminhos finais ou falha/cancelamento.

- [x] Criar diretório temporário irmão com nome único.
- [x] Gerar a tradução e copiar o original somente dentro do temporário.
- [x] Publicar com `os.replace` apenas quando ambos estiverem completos.
- [x] Limpar somente o temporário em falha/cancelamento.
- [x] Rodar os testes focados até ficarem verdes.

### Task 4: Tornar o resultado do worker fiel à entrega

**Files:**
- Modify: `tradutor_pgn/translation_worker.py`
- Modify: `tradutor_pgn/failed_runs.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `TranslationBundleResult`.
- Produces: contagem separada de falhas de tradução e entrega; estado final coerente.

- [x] Escrever teste que força falha de publicação e espera execução `failed`, aviso e arquivo reprocessável.
- [x] Executar e observar o falso sucesso atual.
- [x] Escrever teste de cancelamento durante publicação e esperar `canceled`.
- [x] Executar e observar o falso sucesso atual.
- [x] Integrar o publicador e ajustar resumo, `last_run` e registro da execução.
- [x] Rodar os testes focados até ficarem verdes.

### Task 5: Verificação integrada

**Files:**
- Modify: `REVISAO_GERAL.md` somente para atualizar o estado dos itens entregues.

**Interfaces:**
- Consumes: tarefas 1–4.
- Produces: evidência de entrega do primeiro recorte do Marco 0.

- [x] Executar `uv run python -m pytest -q`.
- [x] Executar `uv run ruff check .`.
- [x] Executar `uv run mypy`.
- [x] Executar `git diff --check`.
- [x] Revisar o diff contra `REVISAO_GERAL_SPEC.md` e registrar pendências não incluídas neste recorte.
