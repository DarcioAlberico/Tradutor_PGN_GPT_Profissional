# Task 9 — sugestões ortográficas progressivas com recursos limitados

2026-11-04, Windows, Python 3.13.2, Spylls local. Corpus preservado:
`2d8055e72e0b351309d78bd41dd63ee21aa7e6d91168bc0aae646675f341afde`.
O relatório anterior de diagnóstico e seu probe não rastreados foram preservados.

## Comportamento entregue

O editor usa `analyze_initial`: detecção e gramática reutilizam os mesmos filtros,
proteções, normalização e cache existentes, sem avançar geradores ortográficos.
Ocorrências começam com sugestões `pending`. A ocorrência selecionada pede um
prefixo progressivo de até cinco opções únicas, na ordem original do Spylls.
`analyze()` permanece compatível para consumidores síncronos e replay; não é o
caminho interativo limitado. Não houve alteração de corpus, thresholds,
concordância, pipeline caching do LT ou regras linguísticas.

O painel distingue pendente, carregando, parcial, completo, timeout, falha e fila
ocupada. Um refresh preserva a escolha ainda válida. Aplicar captura a opção
exata e usa a operação editorial já existente. Timeout/falha deixam opções
parciais utilizáveis e oferecem tentativa explícita; nenhuma ação modifica texto
automaticamente. A seleção inicial visível solicita somente essa ocorrência.

Há um serviço compartilhado, um filho próprio com dicionário persistente e uma
fila FIFO de até oito proprietários pendentes, com substituição da pendência do
mesmo editor. Selecionar/navegar/fechar cancela somente o proprietário adequado;
outra janela ativa não é interrompida. Overflow retorna `busy`. A preparação no
controller também tem um trabalho ativo e uma pendência mais recente, sem uma
future por clique acumulada. Snapshots de resultado enfileirados são coalescidos.

O orçamento escolhido é **3 s de busca**, além de **10 s para inicialização**,
ambos por relógio monotônico. A primeira yield também está sujeita ao prazo.
Cancelamento, crash, protocolo inválido e timeout terminam/join somente o filho
próprio fora do Tk; a recriação é lazy. Um semáforo global impede sobreposição
de filhos mesmo durante shutdown assíncrono/recriação de serviço. Encerramento
do editor não encerra o serviço das demais janelas. O entrypoint executa
`multiprocessing.freeze_support()` antes dos imports GUI.
O prazo interrompe o cálculo; a publicação terminal também inclui o custo de
limpeza do processo/thread. Não é promessa de resposta completa em 3 s somando
fila, carga inicial e limpeza.

O IPC usa bytes JSON com esquema/nonce/tamanhos validados, sem `recv()` com
pickle. Só token NFC de até 128 caracteres e metadados fixos vão ao filho;
comentário, origem e glossário não atravessam essa fronteira. Há limite de cinco
opções, 512 caracteres por opção e 8192 bytes por mensagem. Uma única thread de
leitura e uma mailbox de tamanho um impedem que um frame incompleto bloqueie o
coordenador e burle o timeout. Se uma falha do SO impedir limpeza, o serviço
fecha e retém a exclusão global enquanto a leitura estiver presa. Tokens e
geradores finalizados são liberados; não há cache persistente, arquivo
temporário de usuário, log de payload ou transporte externo.

Identidade, versão, texto/digest, contexto e geração de seleção são revalidados
no controller. O assistant verifica proteções e repete a detecção sem sugestões
antes de enviar o token; alterações de vocabulário pessoal e revisões de cache
invalidam callbacks em voo. Só o polling principal entrega snapshots a widgets.

## Medições reproduzíveis

Os arquivos JSON em `build/reports/` contêm IDs, contagens e tempos, sem texto,
offsets ou sugestões. Comandos, executados serialmente:

```text
uv run python ferramentas/medir_sugestoes_progressivas.py --include-baseline --repeats 2
uv run python ferramentas/medir_sugestoes_progressivas.py --repeats 2 --budget-ms 350 --output build/reports/spelling-progressive-350-final.json
uv run python ferramentas/medir_sugestoes_progressivas.py --repeats 2 --budget-ms 3000 --output build/reports/spelling-progressive-3000-final.json
```

O baseline desta sessão está em `spelling-progressive-baseline.json`; os comandos
acima permitem reproduzir tanto o baseline compatível quanto a nova etapa.
Dicionário do processo principal aquecido, cache do assistant zero, SO preservado,
18 casos × duas repetições por tamanho. p95 nearest-rank de 36 amostras:

| Linhas | Antes, análise completa ms/comentário | Depois, detecção inicial ms/comentário | Depois ms/linha | Falhas |
|---:|---:|---:|---:|---:|
| 1 | 2698,905 | 2,193 | 2,193 | 0 |
| 10 | 2747,933 | 4,285 | 0,429 | 0 |
| 50 | 2706,747 | 32,154 | 0,643 | 0 |

Essa comparação mostra o custo retirado do caminho inicial, **não equivalência
de resultados completos**: sugestões continuam chegando separadamente. São
tempos reais da API/motor, excluindo debounce de 280 ms e polling Tk de 60 ms já
existentes; a GUI acrescenta esse agendamento. Não é medição de concordância.

O primeiro `next()` local, para oito consultas aos mesmos quatro typos, teve
p95 **28,703 ms** direto e **29,010 ms** via thread. Thread não limita uma chamada
individual a `next()` nem oferece cancelamento rígido. O novo processo frio
levou **2654,811 ms** até a primeira opção de aquecimento e 2731,699 ms até cinco
opções. Esse custo é explícito e reaparece depois de cancelamento/timeout/crash.

Sequência fixa, duas passagens por TA-004, spelling-accent, spelling-hyphen e
unicode-emoji, após um aquecimento separado que fornece cinco opções:

| Orçamento de busca | Primeiro prefixo warm: n, mín/mediana/máx ms | Prefixo cold na sequência | Timeout | p95 terminal ms |
|---:|---|---|---:|---:|
| 350 ms | 3; 0,680 / 28,925 / 29,135 | 5; 2619,508 / 2676,127 / 2695,248 ms | 6/8 | 3067,141 |
| 3000 ms | 8; 0,482 / 0,695 / 29,539 | 0; aquecimento separado 2654,811 ms | 0/8 | 2685,194 |

Para 3 s, primeira opção de TA-004 chegou em 0,674 e 0,665 ms; a confirmação de
esgotamento levou 1347,891 e 1381,155 ms. Hífen ainda exige aproximadamente
29 ms antes da primeira opção e 2657–2685 ms para esgotar. O limite de 350 ms
mata o filho repetidamente e torna a próxima primeira opção dependente de nova
carga. Por isso o default é 3 s: preserva streaming imediato e dicionário warm
nessa amostra, mantendo trabalho total finito. Em máquina mais lenta poderá
haver mais timeout. Não há garantia de cinco opções nem de primeira opção em
20 ms; incluindo o arranque inicial, o p95 das nove primeiras opções da
sequência de 3 s é **2654,811 ms**. Com n=8/9, p95 é o máximo, não inferência
populacional. A busca não ficou mais rápida; a publicação foi desacoplada dela.

Duas janelas simuladas no mesmo serviço, primeira com TA-004 ativo e segunda com
30 submits substituindo a própria pendência: pico observado **um filho e uma
pendência** nas duas variantes. Com 350 ms a primeira janela recebeu uma opção,
depois timeout; a segunda esperou **3057,477 ms** após submit por timeout+carga.
Com 3 s ambas completaram; a segunda esperou **1382,136 ms** após submit, atrás
da cauda ativa da primeira. FIFO evita cancelar trabalho alheio e implica essa
espera. Nenhuma variante provou atendimento instantâneo de duas janelas.

## Validação e limites

Testes TDD observaram falhas antes das correções de etapa inicial/cache,
controller progressivo, preservação da escolha, retry com snapshot GUI anterior,
pendências de preparação sob bursts, vocabulário alterado antes da seleção e
leitura IPC incompleta. Os testes de processo cobrem ranking/deduplicação/cinco
opções, primeira yield bloqueante com CPU real, cauda bloqueante, startup/spawn
falho, crash, mensagens inválidas/grandes, FIFO/overflow, cancelamento,
shutdown não bloqueante e filho próprio encerrado. Uma prova com Spylls real
comparou sequências completas de acentos, composto e NFD ao caminho legado.

O editor real com Spylls roda em intérprete novo e mantém heartbeat Tk enquanto
carrega o processo e recebe opções; aplicação/dirty/undo continuam exercitados.
Outro teste mantém heartbeat real com primeiro `next()` CPU-bound no filho,
timeout sem opção e intervalo máximo observado exigido abaixo de 150 ms.
Testes de isolamento cobrem duas controllers, callbacks após fechamento,
proteções de origem/glossário/notação, versões stale e vocabulário externo.

O gate amplo focado terminou com **292 testes e 9 subtests verdes e uma falha**
no teste de reset/shutdown. O traceback mostrou um bootstrap Windows tentando
ler JSON no canal de arranque pickle após um alvo lambda não serializável.
Investigação da stdlib confirmou que Windows cria o filho antes de serializar
seu target; `Process.start()` pode falhar antes de publicar o handle. Um teste
RED adicional confirmou que esse alvo chegava ao start. O serviço agora faz
preflight de serialização do callable confiável antes de criar o filho; nenhum
token é incluído nessa serialização. A repetição do grupo afetado ficou verde:

```text
uv run pytest tests/test_spelling_suggestions_process.py tests/test_writing_progressive.py tests/test_writing_controller.py tests/test_writing_performance.py tests/test_editor_windows.py::WritingRealEngineTests -q
59 passed in 33.12s
```

Os testes verdes não relacionados não foram repetidos. Ruff passou nos quinze
arquivos Python novos/alterados, mypy passou nos cinco arquivos tipados
novos/alterados e `git diff --check` passou após a correção.
A suíte completa não foi executada por orientação da tarefa. Não houve smoke de
executável congelado/instalador nesta rodada; o desvio do entrypoint foi testado
em fonte. RAM do segundo dicionário não foi perfilada; o limite é de quantidade
de filhos/filas/tamanhos e de duração da busca, não de RSS em bytes. Concordância
continua experimental, e estes resultados não aprovam seus gates de qualidade,
distribuição ou licenças.

## Revisão de segurança editorial — fix round 1 (2026-11-04)

O defeito confirmado estava depois da publicação do prefixo: uma callback já
aceita podia ficar na fila enquanto outra instância alterava o vocabulário ou
uma revisão de cache mudava. A versão do texto permanecia igual e o editor
ainda podia exibir/aplicar a sugestão anterior. Também havia duas janelas no
lote: a confirmação podia mudar a revisão, e ela podia mudar depois dos UPDATEs
antes do commit.

Resultados, ocorrências e eventos agora transportam uma revisão composta pelo
epoch do cache e SHA-256 dos bytes do vocabulário. Arquivo ausente tem marcador
distinto de arquivo presente. O fingerprint não depende de tamanho/mtime:
testes fazem edição in-place e substituição atômica, preservando ambos. O
controller revalida no polling e no uso da ocorrência, remove snapshots velhos
e agenda nova análise. O painel limpa sublinhados e opções enquanto atualiza;
essa invalidação não edita rascunho, dirty, versão ou histórico de desfazer.

Aplicar uma ocorrência repete a validação depois de calcular a substituição e
adquire um guard antes da mutação. O lote repete a validação após a confirmação.
No worker, `apply_identical_replacements` aceita o argumento opcional keyword-only
`commit_guard`, mantido até o fim de `conn.commit()`. O guard verifica a revisão
depois de todos os UPDATEs e antes da persistência. Divergência, lock ocupado ou
falha de leitura passam pelo rollback existente: texto, `writing_revision`,
`comment_history` e `writing_bulk_rows` retornam juntos ao estado anterior.
Chamadas legadas de dois argumentos, análise síncrona e desfazer continuam
disponíveis. Não há mudança de schema, corpus, regras, ranking, orçamento ou IPC.

### Locks e limites de atomicidade

- Aplicação individual: lock reentrante do controller → lock de cache do
  assistant (aquisição sem espera) → lock permanente do vocabulário (timeout 0).
- Lote: reserva SQLite no worker → lock de cache sem espera → lock do
  vocabulário sem espera → validação/hash → commit → liberação dos guards.
  O worker não adquire lock do controller nem acessa widget nesse trecho.
- Escritores de vocabulário usam apenas o lock permanente; soltam-no antes de
  notificar/invalidate. Invalidação do cache não adquire SQLite. Os caminhos de
  aquisição dos guards recusam contenção; não existe espera em ordem inversa.
  Leituras de revisão e `status()` também recusam lock de cache ocupado, em vez
  de prender o polling de outra janela atrás do commit. A reserva SQLite e o
  trabalho SQL continuam fora do Tk.

O lock protege escritores cooperantes durante o commit/mutação. Um programa que
ignora esse lock pode mudar o arquivo imediatamente depois da leitura; não se
promete exclusão mútua ou linearizabilidade contra esse escritor. Alterações
anteriores à validação são detectadas pelos bytes, mesmo com size/mtime iguais.
Nenhum fingerprint é persistido em log ou métrica; erros do guard usam mensagens
fixas, sem conteúdo da exceção de I/O.

O hash completo custa O(bytes) por validação. O polling de 60 ms lê o arquivo
enquanto há resultado ativo, por editor, além das leituras no clique/guard.
Não há cache por metadata que pudesse ocultar uma substituição externa.
Medição local com 200 leituras por arquivo sintético, sem texto de usuário:

| Palavras | Bytes | Mediana ms | p95 ms (nearest-rank) | Máximo ms |
|---:|---:|---:|---:|---:|
| 0 | 34 | 0,0703 | 0,0763 | 0,1354 |
| 1000 | 14032 | 0,0788 | 0,0811 | 0,1059 |
| 10000 | 140032 | 0,2322 | 0,2531 | 0,2702 |

O probe criou JSON schema 1 com `word{index:06d}` em `TemporaryDirectory`, mediu
`PersonalDictionary.content_revision()` com `perf_counter` e ordenou 200 tempos
(p95 = posição 190). Não representa disco frio, pasta de rede ou arquivo enorme.
O guard elimina espera por lock; leitura de arquivo local ainda é I/O síncrono,
sem teto de duração imposto pelo Python. O lock de cache é mantido apenas no
commit do lote, não na preparação nem durante seus UPDATEs. Mutadores de cache
continuam sincronizados com esse commit.

### RED/GREEN e comandos

Nesta continuação, os dois testes GUI de lote foram executados antes da mudança
de produção: ambos falharam porque `errao errao!` virava `erro erro!` após a
revisão mudar. Dois testes novos do banco falharam por ausência de
`commit_guard`; após implementar o hook, os quatro casos e o restante de
`WritingBulkTests` passaram (12 testes, 6,61 s).

Um novo teste com duas controllers e guard pausado no worker demonstrou RED
porque a segunda janela aguardava o lock e aceitava a ocorrência depois da
espera. A leitura não bloqueante tornou-o GREEN. O mesmo teste revelou outra
espera em `status()` (1,007 s para limite de 0,1 s); a consulta agora retorna
estado transitório sem aguardar. Um teste de erro de leitura observou RED com
`PermissionError` escapando do guard e GREEN após converter em diagnóstico
fixo de revisão indisponível. Nenhum payload de usuário foi usado nas falhas.

```text
uv run python -m pytest tests/test_banco.py::WritingBulkTests tests/test_editor_windows.py::WritingEditorTests::test_bulk_revision_change_at_confirmation_preserves_database_and_draft tests/test_editor_windows.py::WritingEditorTests::test_bulk_revision_change_after_sql_updates_rolls_back_every_row -q
12 passed in 6.61s

uv run python -m pytest tests/test_writing_controller.py tests/test_writing_progressive.py tests/test_writing_assistant.py tests/test_personal_dictionary.py tests/test_writing_types.py tests/test_banco.py::WritingBulkTests -q
172 passed in 16.48s

uv run python -m pytest tests/test_editor_windows.py::WritingEditorTests::test_bulk_revision_change_after_sql_updates_rolls_back_every_row tests/test_editor_windows.py::WritingEditorTests::test_bulk_busy_vocabulary_rolls_back_and_keeps_tk_responsive -q
2 passed, 4 subtests passed in 11.05s
```

A segunda execução acima precede os casos suplementares de status/I/O. A
execução de `uv run
pytest` sem `python -m` falhou na coleta por não incluir o pacote local no
sys.path deste worktree; os comandos de validação usam `python -m pytest`.

O gate ampliado com os mesmos seis grupos puros/banco e toda a classe
`WritingEditorTests` terminou com **227 passed, 17 subtests passed, 1 failed e
1 error** em 162,82 s. A falha foi
`test_book_operation_preserves_current_draft_when_only_other_rows_match`: sua
fixture fabricava uma ocorrência gramatical apenas no painel, enquanto o novo
guard exigia a ocorrência publicada pelo controller. A fixture foi ajustada
para o provider retornar a ocorrência através da análise real; não se relaxou
a validação de produção. O erro de teardown era `WinError 32` na conexão que o
traceback da assertiva conservou antes de alcançar `conn.close()`. Reexecução
isolada do caso corrigido: **1 passed in 3.22s**. Os 227 casos verdes desse gate
não foram repetidos integralmente após essa mudança exclusiva na fixture.

Gate final atualizado, com todos os casos novos e o caso ajustado:

```text
uv run python -m pytest tests/test_writing_controller.py tests/test_writing_progressive.py tests/test_writing_assistant.py tests/test_personal_dictionary.py tests/test_writing_types.py tests/test_banco.py::WritingBulkTests tests/test_editor_windows.py::WritingEditorTests::test_external_vocabulary_revokes_displayed_prefix_in_two_editors_without_editing_drafts tests/test_editor_windows.py::WritingEditorTests::test_revision_change_between_replacement_calculation_and_mutation_preserves_draft tests/test_editor_windows.py::WritingEditorTests::test_nonblocking_vocabulary_lock_refuses_apply_and_keeps_tk_responsive tests/test_editor_windows.py::WritingEditorTests::test_glossary_change_during_calculation_keeps_newly_protected_draft tests/test_editor_windows.py::WritingEditorTests::test_bulk_revision_change_at_confirmation_preserves_database_and_draft tests/test_editor_windows.py::WritingEditorTests::test_bulk_revision_change_after_sql_updates_rolls_back_every_row tests/test_editor_windows.py::WritingEditorTests::test_bulk_busy_vocabulary_rolls_back_and_keeps_tk_responsive tests/test_editor_windows.py::WritingEditorTests::test_book_operation_preserves_current_draft_when_only_other_rows_match -q
181 passed, 8 subtests passed in 50.06s

uv run ruff check tradutor_pgn/writing_types.py tradutor_pgn/personal_dictionary.py tradutor_pgn/writing_assistant.py tradutor_pgn/writing_controller.py tradutor_pgn/edit_window.py tradutor_pgn/database.py tests/test_writing_controller.py tests/test_writing_progressive.py tests/test_editor_windows.py tests/test_banco.py
All checks passed!

uv run mypy tradutor_pgn/writing_types.py tradutor_pgn/personal_dictionary.py tradutor_pgn/writing_assistant.py tradutor_pgn/writing_controller.py tradutor_pgn/database.py
Success: no issues found in 5 source files

git diff --check
exit 0 (somente avisos de conversão LF/CRLF do Git)
```

A suíte completa não foi executada por orientação explícita desta rodada.
Os três diagnósticos não rastreados de terceiros permaneceram fora do fix e do
commit. Não houve push, publicação ou alteração de dados de produção.
