# Task 9 — corpus real, desempenho e métricas locais

Data: 2026-10-30. Implementação no worktree `assistente-escrita-portugues`.
Concordância permanece **experimental**, default **false**. Os critérios de
qualidade e latência não foram atingidos; nenhuma aprovação de distribuição
foi concedida. A Task 8 continua bloqueada por licenças/fontes/notices e gates
de entregas reais, independentemente dos resultados desta tarefa.

## Escopo e invariantes

- Avaliador determinístico com baseline Spylls/VERO e baseline completo usando
  LanguageTool 6.6 real, runtime reduzido de `build/vendor`.
- Gabarito da Task 1 preservado, SHA-256
  `2d8055e72e0b351309d78bd41dd63ee21aa7e6d91168bc0aae646675f341afde`.
- Correspondência um a um exige span, original, categoria e pelo menos uma
  sugestão editorial exatos. Sugestão errada gera FP e miss; duplicata gera FP.
  Resultados indisponíveis/fallback ficam nos denominadores e são contados como
  falhas, nunca como sucesso vazio. Diagnósticos suprimidos não são apresentados.
- JSON/Markdown exportam apenas IDs de casos/regras, categorias, contagens e
  medidas agregadas. Nenhum texto, mensagem, sugestão, intervalo ou offset é
  exportado. Exceções de providers não entram nos relatórios.
- A ponte `_record_writing_action` de `edit_window.py` foi alterada conforme
  autorização. Nenhum outro módulo fora do brief foi necessário; este relatório
  é o artefato solicitado. Não houve alterações de licenças, settings ou corpus.

## Normalização e alternativas

O LanguageTool pode abranger contexto que não muda. A normalização usa prefixo
e sufixo comuns a **todas** as alternativas restantes e expande a fronteiras de
palavras Unicode, incluindo marcas combinantes. Ela só aceita o resultado se
cada substituição reconstruir exatamente a alternativa original do provider.
Spelling, repetições, pontuação, sugestões vazias e alternativas no-op preservam
tratamento conservador; não são convertidas em ocorrências vazias.

A versão, o texto projetado e todo o span do provider são validados **antes**
de estreitar. Um span que cruza proteção é descartado integralmente; retirar
contexto não o recupera. Depois da normalização, proteção e offsets são
revalidados e a ocorrência é validada contra o pedido real. Diagnósticos
`suppressed_by_glossary` mantêm seu estado e não recebem sublinhado.

Na avaliação real, o motor ofereceu também alternativas que apenas inseriam
pontuação em diagnósticos de concordância. A política geral remove uma
alternativa somente nas categorias nominal/verbal quando o conteúdo restante,
retirando pontuação Unicode e espaços, permanece exatamente igual, e a
sequência de pontuação muda. Acentos, caixa e símbolos permanecem significativos.
Alternativas que mudam pontuação **e** morfologia são preservadas.

Esse filtro descartou **2 alternativas de VERBAL_AGREEMENT** no replay de
qualidade. O assistente mantém apenas o contador agregado por categoria; cache
hits não contam novamente. O avaliador exporta o delta do replay, sem payload.
Nenhuma categoria ou regra inteira foi desativada para melhorar a pontuação.

## Baselines reais

Comandos executados com o ambiente `uv` do worktree:

```text
uv run python ferramentas/avaliar_corretor_portugues.py --mode spelling --benchmark-repeats 1
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --benchmark-repeats 1
```

Ambos terminaram com exit 0: conseguiram executar todos os providers e análises.
Exit 0 de replay significa execução, não aprovação de qualidade. O programa
retorna exit 1 se houver falha de provider, inclusive em benchmark, preservando
os relatórios. Baixa precisão/recall deixa `gate.stable=false` de modo explícito.

Saídas geradas (ignoradas pelo Git, sem payload):

- `build/reports/portuguese-writing-spelling.json` e `.md`;
- `build/reports/portuguese-writing-full.json` e `.md`.

Os baselines ignoram vocabulário pessoal e preferências do usuário; usam os
recursos locais fixados do checkout, sem download, provider remoto ou ajuste
de thresholds. O cache do assistente fica desabilitado para a medição.

| Baseline | Esperados | Apresentados | TP | FP | Misses | Precisão | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| Spylls/VERO | 4 | 4 | 3 | 1 | 1 | 75,00% | 75,00% |
| Completo | 11 | 12 | 8 | 4 | 3 | 66,67% | 72,73% |

Resultado completo por categoria:

| Categoria | Esperados | Apresentados | TP | FP | Misses | Precisão | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| SPELLING | 4 | 4 | 3 | 1 | 1 | 75,00% | 75,00% |
| NOMINAL_AGREEMENT | 2 | 0 | 0 | 0 | 2 | n/a | 0,00% |
| VERBAL_AGREEMENT | 3 | 3 | 3 | 0 | 0 | 100,00% | 100,00% |
| GRAMMAR | 0 | 3 | 0 | 3 | 0 | 0,00% | n/a |
| PUNCTUATION | 1 | 1 | 1 | 0 | 0 | 100,00% | 100,00% |
| REPEATED_WORD | 1 | 1 | 1 | 0 | 0 | 100,00% | 100,00% |

Nos dois replays: **0 violações protegidas e 0 falhas de análise**. Sugestões
ortográficas presentes em **4/4** typos; sua presença não substitui o teste de
correção editorial. O aceite literal **TA-004 passou** no replay completo real.
Precisão mínima 95% e recall mínimo 80% permanecem iguais à spec: ambos falham.

### Triagem de todos os falsos positivos e misses

| Case ID | Rule ID | Julgamento / ação |
|---|---|---|
| spelling-hyphen | SPELLING_UNKNOWN_WORD | Span detectado, mas sem sugestão editorial do gabarito: FP + miss. Não inventar sugestão ausente no VERO. |
| nominal-gender | LIGACAO_ECG_V3 | Correção correspondente ao gabarito, mas classificada como GRAMMAR pelo adapter atual: FP + miss estritos. Mapeamento de categoria fica pendente. |
| source-names | UPPERCASE_SENTENCE_START | Alerta indevido após proteção de nome na origem. Exige tratamento do contexto mascarado; não foi desativada a regra inteira. |
| ambiguous-ellipsis | SPACE_BEFORE_PUNCTUATION2 | Alerta em elipse editorial deliberada. Um exemplo não justifica suprimir toda pontuação; regra mantida e gap registrado. |
| nominal-plural | nenhum diagnóstico apresentado | Miss do motor local com os filtros atuais; não contado como sucesso nem mascarado por threshold menor. |

Os 3 misses são `spelling-hyphen`, `nominal-gender` e `nominal-plural`. Os demais
casos corretos, protegidos e ambíguos estão identificados no relatório JSON; não
foram acrescentados casos artificiais para diluir os falsos positivos.

## Desempenho e background

Windows, Python 3.13.2, LanguageTool 6.6 real. Cada tamanho percorreu os 18 casos
uma vez; pequeno = 1 linha, médio = 10 e grande = 50 repetições da linha, no
mesmo comentário. Dicionário/JVM foram aquecidos pelo replay anterior, cache do
assistente = 0, cache de disco do Windows preservado. p95 usa nearest rank;
com **n=18**, corresponde ao máximo, sem intervalo de confiança populacional.
Houve verificações focadas no mesmo computador durante parte da campanha;
isto não representa medição em máquina dedicada ou garantia de release.

| Modo | Linhas/comentário | n | p95 ms/comentário | p95 ms/linha | Falhas |
|---|---:|---:|---:|---:|---:|
| Ortografia | 1 | 18 | 2656,37 | 2656,37 | 0 |
| Ortografia | 10 | 18 | 2650,10 | 265,01 | 0 |
| Ortografia | 50 | 18 | 2671,74 | 53,43 | 0 |
| Completo | 1 | 18 | 3041,09 | 3041,09 | 0 |
| Completo | 10 | 18 | 3084,70 | 308,47 | 0 |
| Completo | 50 | 18 | 3272,18 | 65,44 | 0 |

As metas de ortografia ≤20 ms/linha e análise completa com gramática ≤500
ms/comentário **não foram atingidas**. O caminho medido inclui proteção,
Spylls, geração das sugestões e, no modo completo, transporte/LanguageTool;
não é uma medida isolada da JVM. O padrão das medidas é consistente com custo
alto de sugestões ortográficas; a atribuição exata exige profiling adicional.
Não foi criada otimização sem evidência, nem ocultado esse custo com cache.

Os testes CI usam teto frouxo de 2000 ms para análise ortográfica warm de uma
linha correta, evitando transformar a máquina do runner em gate de release.
O benchmark de máquina inclui também typos, Unicode, regras e proteção.

Teste com Tk real: comentário de 2000 linhas, provider bloqueado por evento,
10 heartbeats da UI executados enquanto o worker segue bloqueado; 38 pedidos
adicionais substituem a pendência e somente o resultado mais novo é entregue.
As análises são comprovadamente executadas fora da thread Tk. Este teste é
determinístico com provider controlado, não é um benchmark JVM dentro de Tk.
O teste de cache percorre 80 pedidos com capacidade 4 e comprova evicção/reuso
por chamadas reais ao provider.

## Métricas globais

`writing-metrics.db` usa a pasta de dados global do aplicativo, nunca a conexão
ou o caminho de um banco por livro. SQLite `user_version=1`, tabela agregada
`daily_counts`, chave composta por dia/categoria/rule ID/ação e contador inteiro.
Não há tabela de eventos, IDs de livro, texto, palavras, sugestões, offsets,
timestamps de ação ou mensagens de provider. Metadados inválidos são descartados
antes de criar arquivo; IDs aceitam apenas o formato ASCII restrito de regras.

Cada incremento usa `BEGIN IMMEDIATE` e UPSERT. A UI envia somente os quatro
metadados para uma fila limitada a 256 entradas; um worker daemon exclusivo
cuida do I/O. A integração não captura a ocorrência, o texto ou o editor na fila.
Falha de schema, corrupção, falta de acesso, timeout, overflow ou desligamento
pode perder métricas e não altera o sucesso da correção/desfazer. Não há log de
exceção/payload. A saída normal tenta drenar a fila por até 200 ms; não é trilha
de auditoria durável.

Testes exercitaram agregação em dias/ações distintos, schema sem payload,
5 threads e 2 processos concorrentes com **84 incrementos preservados**,
schema futuro/coluna extra/arquivo corrupto/DB bloqueado/caminho diretório,
fila cheia e exceção de worker seguidas de recuperação. Ações reais do editor
produzem contagens de aplicação e ignorar uma vez; falha injetada da ponte
preserva alteração, dirty e desfazer. O banco do livro não recebe a tabela.

## RED/GREEN e verificações

RED observados nesta implementação:

- corpus/normalização inicial: **12 failed, 9 passed**, por spans contextuais e
  avaliador ausente; após implementação, 1 expectativa nova de índice NFD estava
  contada incorretamente e foi corrigida. O gabarito versionado não foi alterado;
- métricas: **14 failed**, módulo ausente, e 2 erros de import no fixture Tk;
  o import do harness foi corrigido antes do RED de integração;
- filtro de alternativa somente de pontuação: **2 failed**, contra o span amplo;
  alternativa com pontuação e morfologia foi coberta sem removê-la;
- ponte do editor: RED por integração ausente; GREEN com persistência e falha
  isolada em editor real;
- exit do benchmark com falha: **1 failed, 5 passed** antes da correção, depois
  exit não zero e relatório preservado.

As verificações de background/LRU/teto frouxo caracterizam contratos já
implementados nas tarefas anteriores; não são apresentadas como REDs novos.

```text
uv run python -m pytest tests/test_writing_corpus.py tests/test_writing_performance.py tests/test_writing_metrics.py -q
47 passed in 14.23s

uv run ruff check ferramentas/avaliar_corretor_portugues.py tradutor_pgn/writing_metrics.py tradutor_pgn/writing_assistant.py tradutor_pgn/edit_window.py tests/test_writing_corpus.py tests/test_writing_metrics.py tests/test_writing_performance.py
All checks passed!

uv run mypy ferramentas/avaliar_corretor_portugues.py tradutor_pgn/writing_metrics.py tradutor_pgn/writing_assistant.py
Success: no issues found in 3 source files

git diff --check
exit 0 (somente aviso de conversão LF/CRLF)
```

Gate de regressão ampliado e confirmação do bloqueio de licenças registrados
no adendo final abaixo. A suíte completa fica para o gate integrado da branch,
conforme escopo recebido. Nenhum build, instalação, publicação ou aprovação
de componente real foi executado nesta tarefa.

### Adendo final — regressão do log e gates

O gate ampliado foi executado:

```text
uv run python -m pytest tests/test_writing_assistant.py tests/test_writing_types.py tests/test_writing_protection.py tests/test_writing_controller.py tests/test_editor_windows.py::WritingEditorTests -q
1 failed, 202 passed, 9 subtests passed in 123.28s
```

A falha foi
`WritingEditorTests::test_actions_log_metadata_without_the_comment`: a ponte
nova havia substituído o log de metadados pela persistência. O contrato
anterior foi preservado, sem mudar o teste: a ponte continua emitindo somente
categoria/rule ID/ação, agora validados, e enfileira a persistência. Um teste
adicional comprova que rule IDs contendo payload são descartados antes de
qualquer log ou I/O. A falha foi corrigida e o teste exato foi reexecutado com
todos os novos testes:

```text
uv run python -m pytest tests/test_writing_corpus.py tests/test_writing_performance.py tests/test_writing_metrics.py tests/test_editor_windows.py::WritingEditorTests::test_actions_log_metadata_without_the_comment -q
49 passed in 16.57s
```

Ruff (sete arquivos Python alterados) e mypy (três módulos de produção)
reexecutados depois desse reparo: ambos exit 0, sem achados. O gate ampliado
inteiro não foi repetido; seus 202 testes verdes são evidência da execução
anterior, e o reparo foi comprovado pelos 49 acima. A suíte completa permanece
pendente do gate integrado, não foi declarada verde nesta tarefa.

O validador real também foi reexecutado:

```text
uv run python ferramentas/preparar_languagetool.py validate
exit 1: ValueError: incomplete license audit; see license-audit.json
```

Essa é a recusa esperada da Task 8, preservada. Não foram alterados manifesto,
aprovação de redistribuição, evidências de licença ou recursos de vendor.
Nenhum dado métrico, banco ou binário entra no commit. Relatórios de máquina
ficam em `build/reports`; os resultados e limitações estão preservados neste
relatório versionado.

## Fix round 1 — validação de rule IDs na exportação

Achado Important confirmado sobre o commit `5520493`: o parser real do
LanguageTool aceita qualquer string não vazia como rule ID, e o avaliador
copiava esse valor para listas de regras em JSON/Markdown. Uma resposta com
payload no campo de ID atravessava parser, assistente e replay com
`failed_cases=0`, expondo o conteúdo no relatório.

A correção fica na fronteira de exportação: o avaliador valida **todos** os
rule IDs de cada resultado antes de agregar ocorrências, inclusive antes de
filtrar diagnósticos suprimidos. Foi extraído o validador já usado pelas
métricas (`is_valid_writing_rule_id`): ASCII, inicial maiúscula, demais caracteres
maiúsculos/dígitos/underscore e comprimento máximo de 128. Métricas e replay
compartilham a mesma política; não se alterou o parser ou a análise linguística.

Qualquer ID inválido descarta o resultado completo do caso, sem aproveitar uma
ocorrência válida anterior da mesma resposta. O caso permanece no denominador,
incrementa `failed_cases`, mantém os misses e produz exit 1 no replay. A exceção
interna usa uma mensagem fixa, é capturada e não entra em relatórios ou logs;
o ID inválido nunca é citado no diagnóstico.

O teste exercita `_issues` real (inclusive conversão UTF-16 após emoji),
`PortugueseWritingAssistant`, CLI do replay e arquivos JSON/Markdown. O controle
com ID ASCII válido é exportado normalmente. Os casos inválidos cobrem payload
igual ao comentário, acento Unicode, homóglifo grego, newline e ID acima do
limite. As verificações abrangem conteúdo dos dois formatos, stdout/logs,
ausência de sucesso parcial, falha registrada e exit não zero. As métricas
também ganharam variantes Unicode/comprimento contra criação de arquivo.

RED observado antes da correção (vazamento efetivamente constatado nos arquivos):

```text
uv run python -m pytest tests/test_writing_corpus.py -k real_parser_assistant_replay -q --tb=short
5 failed, 1 passed, 25 deselected in 0.67s
```

GREEN depois da correção:

```text
uv run python -m pytest tests/test_writing_corpus.py -k real_parser_assistant_replay -q
6 passed, 25 deselected in 0.56s
```

Não houve alteração de corpus, thresholds, preferência experimental/default,
recursos de vendor ou gate de licenças. As medições reais anteriores continuam
válidas como registro daquela campanha; não foram apresentadas como novas
medições nesta rodada. A suíte completa permanece para o gate integrado.

### Gates finais do fix round 1 e isolamento explícito de vendor

O gate focado inicial, sem isolamento, encontrou um pressuposto de ambiente no
teste legado `test_grammar_requested_without_adapter_has_visible_fallback`:

```text
uv run python -m pytest tests/test_writing_corpus.py tests/test_writing_metrics.py tests/test_languagetool_client.py tests/test_writing_assistant.py tests/test_writing_performance.py -q
1 failed, 175 passed in 66.15s

uv run python -m pytest tests/test_writing_assistant.py::test_grammar_requested_without_adapter_has_visible_fallback -q
1 failed in 8.14s
```

O teste pressupõe runtime indisponível ao construir o adapter padrão, mas o
vendor real deste worktree respondeu em modo `full`. O teste e
`writing_assistant.py` são idênticos ao HEAD (`git diff --quiet HEAD --` nesses
dois arquivos: exit 0). Não foi alterado nem excluído o teste, e os recursos
reais não foram movidos, removidos ou mascarados para a aplicação.

Conforme orientação do controlador, a mesma seleção foi repetida com fixture
diagnóstica explícita. O driver ignorado pelo Git
`.superpowers/sdd/2026-10-27-assistente-escrita-portugues/task9_missing_vendor.py`
registra uma fixture autouse que, **somente nesse teste**, envolve
`LanguageToolProcess.__init__` para fornecer o seam já existente
`resource_resolver=lambda relative: tmp_path / 'absent-vendor' / relative`.
Assim o teste exercita a indisponibilidade real de arquivos; não há stub de
análise ou fallback. O monkeypatch é desfeito ao final do teste, e todos os
demais testes mantêm seus recursos normais.

```text
uv run python .superpowers/sdd/2026-10-27-assistente-escrita-portugues/task9_missing_vendor.py tests/test_writing_corpus.py tests/test_writing_metrics.py tests/test_languagetool_client.py tests/test_writing_assistant.py tests/test_writing_performance.py -q
176 passed in 52.12s
```

O replay com LanguageTool real ficou separado desse isolamento:

```text
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --output-dir build/reports/task-9-fix-1-real
exit 0; expected=11, presented=12, true_positives=8, false_positives=4, misses=3
precision=0.6666666666666666; recall=0.7272727272727273
failed_cases=0; protected_violations=0; ta004_literal=true; stable=false
```

Ruff, incluindo o driver diagnóstico, e mypy dos dois módulos de produção
alterados passaram:

```text
uv run ruff check .superpowers/sdd/2026-10-27-assistente-escrita-portugues/task9_missing_vendor.py ferramentas/avaliar_corretor_portugues.py tradutor_pgn/writing_metrics.py tests/test_writing_corpus.py tests/test_writing_metrics.py
All checks passed!

uv run mypy ferramentas/avaliar_corretor_portugues.py tradutor_pgn/writing_metrics.py
Success: no issues found in 2 source files

git diff --check
exit 0 (avisos LF/CRLF, sem erros)
```

O commit seletivo inclui somente avaliador, validador compartilhado, testes de
corpus/métricas e este relatório. Não contém driver diagnóstico, payloads,
bancos, arquivos do vendor ou alterações dos testes legados. A execução sem
fixture continua documentada como falha de pressuposto de ambiente; o gate
integrado deve manter explícita essa distinção.
