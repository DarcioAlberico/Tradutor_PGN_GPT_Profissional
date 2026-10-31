# Task 10 — documentação, migração e validação integrada

Data: 2026-10-30. Worktree: `assistente-escrita-portugues`.
Integração original validada em `5754cb5`; evidências do fix round 1 no adendo
final. Task 10 parcial por entregas Windows e integração
dos documentos locais pendentes. **Release bloqueado**;
concordância **experimental**, `grammar_enabled=false` por padrão.

## Escopo e documentação

README atualizado com painel, F7/Shift+F7 e fallback para QA, aplicação
explícita/undo, lote confirmado por livro, vocabulário global, regras reversíveis,
modos, defaults, recuperação, dados, privacidade e diagnóstico sem payload.
Corrigidas as afirmações antigas de publicação automática em push/PR e tamanho
~79 MB: CI ordinário não publica executável; release manual exige aprovação.
ROADMAP preserva a distinção entre integração, estabilidade e distribuição.

Os arquivos `CONTEXT.md`, `REVISAO_GERAL.md` e `REVISAO_GERAL_SPEC.md` não existem
no worktree versionado, mas existem como material local no checkout principal.
Foram lidos, incluindo os contratos PT-001–PT-013, e preservados sem alterações.
Rascunhos novos desses nomes, inicialmente criados no worktree antes dessa
informação, foram removidos. Não entram no commit. Integrar suas atualizações
exige preservar o conteúdo local; este relatório e README/ROADMAP registram o
estado real sem substituir esses documentos. A spec aprovada em
`docs/superpowers/specs/2026-10-27-assistente-escrita-portugues-design.md` não mudou.

## Migração e correção determinística do teste

`test_old_settings_upgrade_and_legacy_write_preserve_user_data` caracteriza
settings antigos sem a seção: leitura com defaults não regrava bytes, a criação
explícita da seção preserva rascunhos/output/chaves aninhadas desconhecidas e a
escrita legada por seção permite reabertura sem perder as preferências novas.
Isso não executa binários históricos: uma versão externa que sobrescreva o JSON
inteiro pode perder campos, por isso o README exige backup para downgrade.

`test_legacy_settings_open_without_optional_engines_and_preserve_draft` abre a
janela real de configurações com settings antigos, loader sem dicionário e
resolver de runtime inexistente. Exercita diagnóstico de indisponibilidade,
salvamento e preservação de rascunhos/chaves. São caracterizações de contratos
existentes, sem mudança de comportamento do produto.

O minor da Task 9 foi corrigido no próprio teste. RED observado:

```text
uv run python -m pytest tests/test_writing_assistant.py::test_grammar_requested_without_adapter_has_visible_fallback -q
1 failed in 6.45s
modo real: full; esperado: spelling_only
```

Com vendor preparado, o adapter padrão funcionava corretamente. O teste agora
instancia `LanguageToolProcess(resource_resolver=...)` apontando para arquivos
ausentes, passado ao `LanguageToolLocalAdapter`, e mantém processo, lifecycle,
fallback, diagnóstico e análise ortográfica reais. Cleanup usa `finally`.
Nenhum monkeypatch global, fixture autouse ou alteração de produção foi usado.

```text
mesmo comando após o ajuste:
1 passed in 0.57s
```

Evidências locais: `task-10-red-fallback.log` e `task-10-green-fallback.log` em
`.superpowers/sdd/2026-10-27-assistente-escrita-portugues/` (demais logs citados
abaixo usam essa mesma pasta). O smoke real ficou separado do isolamento.

## Verificações estáticas e regressões

`tool.mypy.files` ampliado de 8 para 18 módulos: tipos/proteção/vocabulário,
assistente, client/processo, controller, métricas e duas ferramentas de avaliação/
preparação. O painel Tk permanece fora da lista porque não é módulo tipado;
não se adicionaram ignores nem se reduziram regras para obter sucesso.

```text
uv run ruff check .
All checks passed!
uv run mypy
Success: no issues found in 18 source files
```

Logs: `task-10-ruff.log`, `task-10-mypy.log`.

A seleção ampliada exigida no brief, mais métricas/packaging, foi executada
(`task-10-focused.log`; 975 testes coletados), mas **não passou**: após 89%,
Windows encerrou o Python com access violation, exit **-1073741819**. Stack:
`tkinter.update` → `CTkToplevel._windows_set_titlebar_color` → construção do editor
em `WritingFixtureIsolationTests.test_legacy_window_uses_injected_service_without_starting_real_engine`.
Não houve resumo final confiável; os pontos anteriores não equivalem a 975 passes.

Na investigação inicial, antes do fix abaixo, produto e `tests/test_editor_windows.py` eram idênticos a HEAD anterior
(`git diff --quiet HEAD -- tradutor_pgn tests/test_editor_windows.py`: exit 0).
O teste do crash isolado e os três testes novos/ajustados passaram juntos:

```text
uv run python -m pytest tests/test_editor_windows.py::WritingFixtureIsolationTests::test_legacy_window_uses_injected_service_without_starting_real_engine tests/test_main_window.py::SettingsWindowTests::test_legacy_settings_open_without_optional_engines_and_preserve_draft tests/test_settings.py::WritingSettingsTests::test_old_settings_upgrade_and_legacy_write_preserve_user_data tests/test_writing_assistant.py::test_grammar_requested_without_adapter_has_visible_fallback -q
4 passed in 3.54s
```

Comparação independente no HEAD **2ccfd1236881803c2fdc1bcec4b7b9ff845bef86**,
worktree detached `build/task10-baseline`, mesmo Python/dependências e vendor
preparado compartilhado por junction: o caso do crash isolado também passou,
**1 passed in 2.84s** (`task-10-baseline-isolated.log`). Não se atribui causa ao
Tk ou a esta tarefa apenas pela stack ou por essas execuções isoladas verdes.
As duas falhas intermitentes da Task 7 não foram observadas antes do crash;
isso não as resolve. A execução completa inicial também terminou com o mesmo
access violation no mesmo teste, após 31%, exit -1073741819
(`task-10-full.log`; `uv run python -m pytest -q -ra`, 2435 coletados).
Nenhum desses gates foi apresentado como verde.

### Diagnóstico causal e fix de lifecycle

O baseline detached reproduziu a falha em `WritingEditorTests` seguido de
`WritingFixtureIsolationTests`, com e sem `TextUndoHistoryTests`. Não foi
necessário esperar centenas de janelas. Bissecção sequencial de 12 braços
(`task-10-bisect.json`, seleções e logs `task-10-bisect-01.log` a `-12.log`)
reduziu a sequência a somente:

```text
tests/test_editor_windows.py::WritingEditorTests::test_vocabulary_commit_after_editor_close_notifies_remaining_windows
tests/test_editor_windows.py::WritingFixtureIsolationTests::test_legacy_window_uses_injected_service_without_starting_real_engine
baseline: exit 3221225477 (0xc0000005)
```

O primeiro teste fecha o diálogo transient enquanto a inclusão de vocabulário
está bloqueada e não executa outro ciclo de eventos antes da destruição. O
trabalho nativo de geometria desse diálogo sobrevive e a atualização da janela
seguinte dispara a falha. Resolver `dialog.update_idletasks()` **antes** de
destruí-lo fez o mesmo par passar, **2 passed in 3.27s**, em braço diagnóstico
sobre o baseline (`task-10-probe-drain-dialog.log`). Esse contraste localizou
o lifecycle que precisa ser preservado, sem alterar provider ou gabarito.
O par usa o serviço de análise controlado das fixtures e armazenamento real
isolado de vocabulário; não inicia Java. A falha nativa independe do sidecar.

O EventLog (`task-10-native-events.log`) identifica `tk86t.dll` 8.6.15 e offset
0x24841 nas execuções. O disassembly nesse ponto dereferencia a estrutura do
window manager e limpa a flag de atualização pendente, compatível com
`UpdateGeometryInfo` na [fonte primária Tk 8.6.15](https://raw.githubusercontent.com/tcltk/tk/core-8-6-15/win/tkWinWm.c).
A identificação da função é inferência apoiada pela instrução/fonte e pelo
contraste acima; não houve minidump com símbolos para certificar o valor exato
do ponteiro ou atribuir um defeito genérico a todas as versões de Tk.

Hipóteses testadas e refutadas como correção suficiente, mantidas nos logs:

- Retenção global: o probe mediu 39 raízes, 42 callbacks de tema de editores e
  108 entradas DPI após fixtures destruídas; nenhum `Font.__del__` fora da main
  foi observado. Limpar somente entradas destruídas e coletar na main **não**
  evitou o crash (`task-10-probe-clean-trackers.log`). Esse cleanup não foi aplicado.
- Drenar idles apenas no teardown do harness também falhou, agora durante a
  drenagem (`task-10-probe-drain-idle.log`): o diálogo já havia sido destruído.
  Não se alterou o harness nem se desabilitou o título nativo do CustomTkinter.
- Uma execução baseline `-q` teve um `F` antes do crash, sem relatório da
  asserção devido ao encerramento nativo. Os replays instrumentados não o
  repetiram; não foi atribuído a um flake específico da Task 7 sem evidência.

Novo RED em subprocesso contra o produto intacto:

```text
uv run python -m pytest tests/test_editor_windows.py::WritingFixtureIsolationTests::test_closing_pending_vocabulary_dialog_allows_next_native_window -q
1 failed in 4.38s; filho encerrou com 0xc0000005
```

O teste executa o par real original, inalterado, em filho e verifica seu exit:
um crash deixa de matar o runner antes de emitir o relatório. O fix autorizado
limita-se a `_close_writing_dialog` em `edit_window.py`: destaca a referência
para permitir reentrada, libera o grab, resolve idles com a janela ainda viva e
garante a tentativa de `destroy` mesmo se o idle levantar `TclError`.
`update_idletasks` resolve tarefas idle do Tk (incluindo callbacks `after_idle`);
não espera JVM ou rede e não redefine as metas de responsividade da spec.

```text
uv run python -m pytest tests/test_editor_windows.py::WritingFixtureIsolationTests tests/test_editor_windows.py::WritingEditorTests::test_dialog_idle_error_still_destroys_window_and_preserves_vocabulary_commit tests/test_editor_windows.py::WritingEditorTests::test_dialog_idle_reentrant_close_preserves_window_cleanup_and_vocabulary_commit tests/test_editor_windows.py::WritingEditorTests::test_vocabulary_commit_after_editor_close_notifies_remaining_windows -q
5 passed in 9.99s
```

Logs: `task-10-red-native-dialog.log`, `task-10-green-native-dialog.log`.
Os testes de falha/reentrada usam o diálogo real e um commit real de vocabulário
segurado por Events; verificam destruição, palavra persistida, rascunho, dirty e
traduções do banco preservados. O erro de idle é injetado após assentar a janela
nativa para que a própria injeção não introduza um job inválido. Ruff global e
mypy 18 módulos foram repetidos após o fix, ambos exit 0.

O gate ampliado final terminou em `task-10-focused-final.log`: **978 passed,
68 subtests passed in 728.01s**. O log completo tem resumo de 100%; na retomada
não havia pytest anterior ativo. A seleção contém os arquivos do brief,
mais métricas e packaging, incluindo os três testes novos de lifecycle.
Não se reutilizou o gate inicial interrompido como evidência verde.

Na retomada, `uv run ruff check .`, `uv run mypy` e `git diff --check`
foram repetidos: exit 0, sem achados (mypy: 18 módulos; apenas avisos Git
de conversão LF/CRLF). Log: `task-10-static-resume.log`.
A suíte completa foi executada em processo novo, sem fixture diagnóstica de
vendor, com o comando `uv run python -m pytest -q -ra`:

```text
1 failed, 2425 passed, 12 skipped, 6761 subtests passed in 1131.23s
exit 1
```

Log: `task-10-full-final.log`. Não houve novo crash nativo. O único teste
com falha foi
`WritingEditorTests.test_busy_search_return_keeps_manual_draft_and_can_persist_it_after_delivery`:
o contexto e o rascunho permaneceram intactos, mas o label estava vazio, sem
“Aguarde”. Os 12 skips foram explícitos: um por falta de privilégio para
symlinks, cinco por SDK Anthropic ausente e seis por python-chess ausente.
Não se adicionou skip nem se desativou teste para obter sucesso.

### Diagnóstico da entrega de teclado no teste legado

O caso exato falhou em três processos novos do estado atual (**3.68s, 2.96s,
2.99s**) e no baseline detached **2ccfd12** (**2.99s**), sempre na mesma
asserção. Logs: `task-10-busy-search-replay.log` e
`task-10-busy-search-baseline.log`. A escrita append do primeiro log misturou
UTF-8/UTF-16 no PowerShell; a cópia `task-10-busy-search-replay-readable.log`
remove somente os bytes NUL, com essa transformação declarada, preservando o bruto.
Essa comparação confirma que o sintoma também existe antes deste incremento;
o caso já estava identificado como intermitente na Task 7.

O probe local `task10_focus_probe.py` observou o Tk real, sem substituir análise
ou eventos: o foco estava no `CTkToplevel` modal, em outro toplevel, e nenhum
dos dois eventos sintéticos chegou a `_writing_action_blocked`. Forçar foco
e depois executar `update()` não bastou: o modal reassumiu o foco. Ao forçar
o foco no alvo **imediatamente antes de cada evento**, sem um ciclo de eventos
intermediário, ambos os handlers reais executaram e recusaram a ação; o teste
inteiro passou, inclusive as asserções posteriores de rascunho/banco/persistência.
Logs: `task-10-focus-control.log`, `task-10-focus-forced.log` (contraste negativo)
e `task-10-focus-forced-immediate.log` (contraste positivo).

A correção limita-se a duas chamadas `focus_force()` no teste existente,
mantendo `event_generate`, bindings, handlers e todas as asserções. Não há
sleep, timeout maior, skip, retry de asserção ou mudança de produção para esse
sintoma. RED: reproduções acima. GREEN sem probe:

```text
uv run python -m pytest tests/test_editor_windows.py::WritingEditorTests::test_busy_search_return_keeps_manual_draft_and_can_persist_it_after_delivery tests/test_editor_windows.py::WritingFixtureIsolationTests tests/test_editor_windows.py::WritingEditorTests::test_dialog_idle_error_still_destroys_window_and_preserves_vocabulary_commit tests/test_editor_windows.py::WritingEditorTests::test_dialog_idle_reentrant_close_preserves_window_cleanup_and_vocabulary_commit tests/test_editor_windows.py::WritingEditorTests::test_vocabulary_commit_after_editor_close_notifies_remaining_windows -q
6 passed in 13.93s
```

Log: `task-10-green-focus-and-lifecycle.log`. Ruff global e mypy 18 módulos
foram repetidos após o ajuste: ambos exit 0, sem achados
(`task-10-ruff-after-focus.log`, `task-10-mypy-after-focus.log`);
`git diff --check` também exit 0. A suíte completa foi reiniciada em outro
processo, com log separado `task-10-full-after-focus.log`:

```text
uv run python -m pytest -q -ra
2426 passed, 12 skipped, 6761 subtests passed in 1040.81s (0:17:20)
exit 0
```

Não houve falha ou crash nativo nesta repetição integral. Os 12 skips são os
mesmos motivos listados acima; nenhum teste foi excluído do comando. O verde
final não apaga o full com falha nem os dois gates encerrados nativamente.
Nenhum probe, fixture diagnóstica de vendor ou monkeypatch externo foi usado
nessa execução final.

## Smoke real e sentinela de privacidade

```text
uv run python ferramentas/preparar_languagetool.py smoke
exit 0
startup_seconds=4.166070
first_analysis_seconds=1.777402
ready_for_first_result_seconds=5.943472
warm_analysis_seconds=0.451238
peak_rss_bytes=644329472
rule=GENERAL_NUMBER_AGREEMENT_ERRORS
```

PATH do filho vazio, proxies e opções injetáveis Java removidos; transporte
owned IPv4 loopback. Teste nominal exige regra/span/sugestão reais, não apenas
qualquer diagnóstico. Runtime 47.838.546 B e LanguageTool 405.072.337 B; a soma
452.910.883 B é de recursos, não tamanho de instalador/portátil.
Log: `task-10-real-smoke.log`. Houve regressão focada no mesmo computador durante
esse smoke: as medidas não são campanha de máquina dedicada ou garantia de p95.

O driver local `task10_privacy_smoke.py` gera uma sentinela aleatória somente
em memória, submete texto sintético ao assistente real e não imprime a sentinela,
texto, sugestões, spans ou PID. Verifica TA-004 literal (`tem` → `têm`) e sugestão
ortográfica, e depois confirma os handles dos filhos encerrados e diretórios de
configuração removidos. Nenhuma aprovação de licença é necessária para essa
análise local de desenvolvimento; ela não cria artefato distribuível.

```text
uv run python .superpowers/sdd/2026-10-27-assistente-escrita-portugues/task10_privacy_smoke.py
exit 0; mode=full; ta004_literal=true; spelling=true
sentinel_unprotected=true
owned_children_stopped=true; config_cleanup=true
sentinel_occurrences=0; files_scanned=8; scan_errors=0; concurrent_disappearances=0
```

Busca nos logs locais do aplicativo, `build/reports`, dados temporários isolados
do smoke, configurações vivas do sidecar, arquivos temporários de topo criados
na execução e stdout/stderr/logging capturados. Foram examinados bytes UTF-8 e
UTF-16LE. A busca tem esse escopo explícito: não é auditoria de toda a máquina
ou de arquivos privados de outras aplicações. Log final:
`task-10-privacy-smoke-final.log`.
O driver é evidência local ignorada, sem alteração do produto ou dado de usuário.

Tentativas anteriores foram preservadas: `task-10-privacy-smoke.log` passou,
mas a sentinela estava no glossário e não provava passagem pelo transporte.
A variante `task-10-privacy-smoke-unprotected.log`, executada com regressão Tk
concorrente e token aleatório longo, retornou `spelling_only`, TA-004 false,
zero sentinelas e dois erros de varredura. Essa tentativa **falhou**, sem causa
comprovada; o driver anterior não exportava o diagnóstico. A instrumentação
foi então reforçada para verificar presença na projeção, usar frase sintética
de palavras comuns, inspecionar apenas a configuração do filho próprio e
contar separadamente arquivos concorrentes que desapareçam. Nenhum timeout ou
comportamento do produto mudou. A execução final ocorreu sem outra suíte Tk,
incluiu a sentinela não protegida e não teve erro ou desaparecimento de arquivo.

## Gate legal e entregas Windows

```text
uv run python ferramentas/preparar_languagetool.py validate
exit 1: ValueError: incomplete license audit; see license-audit.json
```

Recusa real preservada (`task-10-license-gate.log`). O próprio comando de
entregas também foi executado para comprovar a barreira antes do PyInstaller:

```text
uv run python instalador/gerar-entregas.py
exit 1: ERRO: recursos offline indisponiveis: incomplete license audit; see license-audit.json
```

Log: `task-10-build-refusal.log`. O script retornou antes de criar ambiente
de build ou iniciar PyInstaller, ZIP ou Inno Setup.
`recursos/languagetool-release-approval.json` continua `status=blocked`, sem
componentes aprovados, responsável ou hash de candidato aprovado. Inventário,
SBOM, smoke e testes verdes não aprovam termos/fontes/notices. Nenhuma dessas
entradas foi alterada. **Não executado**, pois não há entrega aprovada para instalar:

```text
powershell -ExecutionPolicy Bypass -File instalador/verificar-ciclo.ps1
```

Sem build/instalação/publicação, smoke real instalado/portátil e incremento real
de tamanho continuam pendentes. Não houve PR, merge ou push.

## Bloqueios que permanecem

- Task 8 parcial: licenças, fontes correspondentes e notices aguardam aprovação
  real; depois executar as entregas e o ciclo instalado/portátil sem Java.
- Task 9: precisão 66,67% e recall 72,73% contra metas preservadas de 95%/80%;
  ortografia e análise completa excedem as metas de 20 ms/linha e 500 ms/comentário.
  TA-004 literal e zero violações protegidas não tornam concordância estável.
- Atualizações de CONTEXT/REVISAO devem ser integradas com os arquivos locais
  existentes. Outros minors do ledger não foram resolvidos por presunção.
  Os hashes SHA-256 dos três documentos locais do principal permaneceram
  iguais aos da retomada. O caso de teclado da Task 7 recebeu o diagnóstico
  acima; o timeout antigo do controller não reapareceu no full final, mas sua
  causa original não foi comprovada por esta rodada.
- O workflow herdado `.github/workflows/testes.yml` ainda usa
  `continue-on-error: true` em mypy e na suíte de janelas, apesar do prazo
  comentado de 2026-09-30. Não foi alterado neste incremento. Os resultados
  locais não comprovam que esses dois passos bloqueiam merge no CI; essa
  exceção permanece para a revisão final contra a spec.

Este incremento não declara projeto, concordância estável ou release concluídos.

## Fix round 1 — barreira durante entrega e callbacks idle

Achado Important confirmado contra `5754cb5`: `poll_writing` liberava
`_writing_busy` antes de fechar o diálogo. O `update_idletasks` necessário ao
fix nativo também executa callbacks Python `after_idle`. Com o lote já
comitado, mas o widget ainda antigo, salvar ou fechar nesse intervalo
regravava a primeira tradução como `errao errao`; depois a entrega mostrava
`erro erro` como salvo/limpo. Essa era perda real da correção no banco.

RED novo, sem alterar produto: dois testes com lote/SQLite/Tk reais e Events
para concluir o worker antes de agendar `after_idle(save_shortcut)` ou
`after_idle(close_editor)`. Ambos observaram banco `errao errao` onde deveria
estar `erro erro` (**2 failed, 41 deselected in 6.02s**;
`task-10-fix1-red-idle-delivery.log`). A seleção ampliada acrescentou entrega
reentrante e idle antes da reconciliação do widget:

```text
uv run python -m pytest tests/test_editor_windows.py::WritingEditorTests -k 'delivery_idle or delivery_stays or delivery_reentrant' -q
4 failed, 41 deselected in 8.17s
```

Log: `task-10-fix1-red-delivery-all.log`.

A barreira agora permanece ativa durante a drenagem, o consumo do Future e
o callback de reconciliação. Uma entrega em andamento rejeita polling
reentrante; `finally` restaura os flags e garante um único poll agendado.
Para preservar o fluxo normal, a confirmação devolve a continuação
prévia→aplicação ao poller, que a inicia ao liberar essa entrega. O refresh
interno das linhas usa `_reload_rows`, enquanto o comando público mantém seu
guard. O undo nativo interno recebe autorização para um único token esperado,
consumida na chamada e limpa em `finally`; o guard continua bloqueando ações
nativas externas enquanto a entrega está ocupada.

Sete testes novos exercitam salvar/fechar durante a drenagem e antes da
reconciliação, polling reentrante, tentativa de job de vocabulário concorrente
e falha do worker seguida de um novo lote. As asserções verificam banco,
widget, `saved_trans`, dirty, janela viva, um único timer, ausência de gravação
de vocabulário concorrente e undo real com restauração do banco. Os testes
nativos anteriores de crash/TclError/reentrada continuam na seleção.

Primeiro GREEN, incluindo confirmação/aplicação/undo real: **5 passed, 40
deselected in 10.65s** (`task-10-fix1-green-delivery.log`). Houve duas tentativas
de gate não aprovadas e preservadas: uma seleção apontava para o arquivo
inexistente `tests/test_database.py` (**exit 4, nenhum teste**, em
`task-10-fix1-focused.log`); a seleção corrigida terminou **1 failed, 262 passed,
60 subtests passed in 131.65s** (`task-10-fix1-focused-valid.log`). A falha era
do teste novo: consultava o recorder por `showwarning`, mas o harness registra
o tipo `warning`. A consulta foi corrigida sem alterar produto ou harness.

```text
uv run python -m pytest tests/test_editor_windows.py::WritingEditorTests -k delivery -q
9 passed, 39 deselected in 18.74s
```

Log: `task-10-fix1-green-delivery-all.log`. A repetição integral corrigida
(`task-10-fix1-focused-final.log`) passou nos 263 testes principais, mas teve
**7 subfalhas e 53 subtestes passando**, exit 1 em 139.93s, no teste legado
`test_minimum_height_review_actions_scroll_into_view_with_keyboard_focus`.
Cada botão permaneceu fora do limite vertical após `focus_set`; esse caso
havia passado na seleção anterior. O teste exato isolado passou tanto no
estado atual quanto no baseline detached `2ccfd12`: **1 passed, 7 subtests
passed in 3.08s** em cada processo (`task-10-fix1-focus-current.log` e
`task-10-fix1-focus-baseline.log`). Essa comparação não comprova a causa da
intermitência nem permite atribuí-la ou excluí-la como regressão. Painel,
foco e o teste legado não foram alterados neste fix. Uma última seleção
integral, sem exclusões, terminou com exit 0:

```text
uv run python -m pytest tests/test_editor_windows.py::WritingEditorTests tests/test_editor_windows.py::WritingFixtureIsolationTests tests/test_editor_windows.py::TextUndoHistoryTests tests/test_banco.py tests/test_editor.py -q
263 passed, 60 subtests passed in 214.89s (0:03:34)
```

Log: `task-10-fix1-focused-replay.log`. Esse resultado não resolve por
presunção a intermitência anterior. Outro job pytest também estava ativo no
computador ao fim da execução; não houve contraste que prove relação causal
com a falha de foco ou com a duração da seleção.

Ruff global, mypy em 18 módulos e `git diff --check` passaram nesta rodada
(`task-10-fix1-ruff-final.log`, `task-10-fix1-mypy-final.log`). A suíte completa **não foi
repetida neste fix round**, conforme escopo explícito da revisão; os 2426
passes acima pertencem ao commit anterior, não certificam o novo patch.

O minor do driver local de privacidade permanece deferred, fora deste loop:
o driver atual inclui a pasta de evidências, mas o log final anterior descreve
o escopo anterior. Não se atribui àquele log a ampliação posterior do driver.
Licenças, entregas Windows, preferência experimental, corpus e thresholds
permaneceram inalterados; este fix não aprova release.
