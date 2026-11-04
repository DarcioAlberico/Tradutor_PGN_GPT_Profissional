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
