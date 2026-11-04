# Task 9 — investigação dos dois misses e um FP restantes

2026-11-04, baseline `c097a64`, Windows, Python 3.13.2, Spylls/VERO local
e LanguageTool 6.6 preparado. Resultado: **nenhuma regra linguística nova foi
aceita**. A investigação explica os casos restantes e acrescenta controles
contra sugestões inventadas. Não entrega melhora de precisão/recall nem
aprova estabilidade, desempenho, distribuição ou licenças.

## Diagnóstico nominal com motor real

O replay independente anterior ao experimento confirmou TP=9, FP=1, misses=2,
precisão=90%, recall=81,82%, zero falhas e zero violações protegidas.
`nominal-plural` retorna zero matches tanto no original quanto na projeção.
Forçar exclusivamente `GENERAL_NUMBER_AGREEMENT_ERRORS` também retorna zero:
não é perda de offset, classificação do adapter ou regra simplesmente desligada.

O tagger real, via CLI, conserva para o token singular do caso as leituras
`NCFS000`, `VMM03S0`, `VMSP1S0` e `VMSP3S0`. Um segundo probe, habilitando
DEBUG apenas para `org.languagetool.AnalyzedTokenReadings`, registra que esse
token foi imunizado pelo antipattern da **linha 7277 do XML local**.

Esse antipattern aceita elemento plural, advérbio/adjetivo opcionais e um token
com leitura `V.+`. Exclui certas formas lexicalmente e particípios; a forma do
corpus não está nessa lista. O controle nominal com `vaca`, que está na lista
de exceções, produz um match no mesmo grupo e nenhuma imunização. A variante
com `casa` também não produz match. As formas corretas plurais e a ocorrência
verbal legítima de `peça` continuam sem alertas.

A documentação primária do LT explica a localização por DEBUG em
[Tips and Tricks](https://github.com/languagetool-org/languagetool-org.github.io/blob/master/tips-and-tricks.md).
O mesmo desenho do antipattern aparece na
[fonte pt do LT v6.6](https://github.com/languagetool-org/languagetool/blob/v6.6/languagetool-language-modules/pt/src/main/resources/org/languagetool/rules/pt/grammar.xml#L7005).
As linhas do arquivo upstream diferem das linhas do artefato local; a atribuição
acima vem do binário e XML efetivamente executados, não dessa numeração remota.

| Probe em memória | Original/projeção | Grupo nominal forçado |
|---|---:|---:|
| nominal-plural do corpus | 0/0 | 0 |
| variante sem adjetivo intermediário | 1/1 (`A_NOUN_VERB`) | 0 |
| substantivo na exceção lexical do antipattern | 1/1 (`A_NOUN_VERB`) | 1 |
| variante com substantivo/verbo homógrafo | 0/0 | 0 |
| controles corretos plural e verbo legítimo | 0/0 | 0 |

Não se acrescentou uma exceção lexical para satisfazer o corpus, não se removeu
o antipattern e não se implementou flexão Python por artigo + terminação. Uma
correção geral exige desambiguação de substantivo/verbo e síntese de número,
incluindo invariantes, plurais irregulares, coordenação e elipses. Aumentar a
lista lexical a partir do único exemplo seria sobreajuste sem essa evidência.

## Hífen: candidato produtivo rejeitado por contraprova

No `spelling-hyphen`, a consulta real confirma radical conhecido e forma
aglutinada desconhecida. O gerador se esgota com uma única alternativa, formada
pela separação dos componentes por espaço; não oferece a referência editorial.
Essa alternativa faz o caso ser simultaneamente FP e miss na avaliação estrita.
Não se suprimiu a ocorrência para aumentar precisão, nem se alterou o gabarito.

O `.aff` local contém oito famílias com quatro condições de prefixação:

| Prefixo | Flag VERO | Vogal que mantém hífen junto de h |
|---|---|---|
| anti | U+00C1 | i |
| ante | U+00CF | e |
| contra | U+00D3 | a |
| extra | U+00D4 | a |
| infra | U+00D5 | a |
| intra | U+00D6 | a |
| ultra | U+00E0 | a |
| supra | U+00F4 | a |

Para cada família, os outros ramos aglutinam sem h/r/s/vogal coincidente,
mantêm hífen junto de h/vogal coincidente e duplicam r ou s. O radical verbal
que permite a flexão já reconhecida pelo dicionário não tem a flag U+00D3;
não foi assumido que todo radical reconhecido suporta todo prefixo.

A [Base XVI do Acordo, publicada pela Câmara](https://www.camara.leg.br/internet/reformaortografica/decreto_e_texto_do_acordo.pdf)
regula a grafia **quando a formação é prefixal**. Inferir que qualquer token
com aparência de prefixo já tem essa análise morfológica é um passo adicional,
que a regra ortográfica não justifica.

Foi experimentado, sob TDD, acrescentar uma alternativa antes do gerador,
preservando todas as letras: prefixo de uma dessas famílias, uma só separação
ASCII, consoante inicial diferente de h/r/s, caixa regular, radical conhecido e
original desconhecido. O caminho síncrono e o worker compartilhavam a mesma
função; não se modificou o IPC, cancelamento ou prazo do serviço de `c097a64`.

Antes: 13 falhas comportamentais e 20 controles verdes. Depois: 33 verdes,
incluindo variante real do worker e 12 variantes fora do corpus, como outros
radicais, prefixos, inicial maiúscula e caixa alta. Esse recorte inicial **não
estabeleceu segurança**.

Seis contraprovas adicionais, com pronomes, uma forma verbal e preposições,
refutaram a hipótese: em `contra-quem`, `contra-tudo`, `contra-nós`,
`contra-você`, `ante-tudo` e `contra-votaram`, o VERO conhece o segundo
componente, desconhece original e aglutinado, e o protótipo acrescentava uma
nova forma não validada. Aqui uma opção de separação pode preservar a relação
prepositiva, enquanto a aglutinação pode inventar outro sentido.

Os seis testes falharam no protótipo; o probe real confirmou os seis conjuntos
de consultas e as seis alternativas indevidas, sem exportar comentário,
sugestão ou offset. O corpus provisório chegou a TP=10, FP=0, misses=1,
precisão=100% e recall=90,91%, mas esses números foram **rejeitados** diante dos
negativos independentes. Todos os três arquivos de produção foram restaurados;
o diff final não contém a regra experimental.

O serviço recebe só token NFC. A mesma sequência pode ter análise prefixal ou
prepositiva dependendo do contexto; o transporte de apenas token não resolve
essa ambiguidade. Não se ampliou o payload com comentário/origem/glossário.

## Controles entregues e próximas opções

`tests/test_portuguese_prefix_suggestions.py` preserva 32 controles: radicais
conhecidos não autorizam alternativa sintética, limites h/r/s/vogais, prefixos
de outra família, compostos de vários componentes, caixa irregular, formas
Unicode, desconhecidos, plurais e homógrafos, entrada com várias palavras,
origem/glossário/sessão protegidos, forma aceita pelo dicionário e tokens com
dígitos. Dois controles usam o worker real e deadline de 200 ms para exigir
que ele não publique aglutinação inventada. Não exigem esgotamento completo
do gerador e não aceitam falha do provider como êxito.

O seam síncrono usa uma implementação mínima do protocolo de dicionário para
isolar a garantia editorial; não fabrica respostas gramaticais. Os seis
negativos relevantes foram observados vermelhos no protótipo e verdes após
sua retirada. Os testes não fixam a ausência do gold do corpus como contrato:
uma futura fonte lexical confiável pode corrigir esse caso sem violá-los.

Opções para uma rodada futura, dependentes de evidência nova:

1. Investigar a desambiguação nominal upstream com positivos e negativos
   além do corpus; qualquer mudança no vendor requer replay próprio.
2. Avaliar recurso lexical local revisado que valide formas prefixais
   completas; preservar as obrigações de distribuição já existentes.
3. Manter escolha editorial explícita/vocabulário/glossário quando o motor
   não oferece a forma desejada, sem transformar essa preferência em regra
   automática para outras palavras.

Nenhuma dessas opções foi instalada, habilitada ou aprovada nesta rodada.

## Execuções e limites

As medições desta rodada usam cache do assistente zero e corpus intacto.
Artefatos em `build/reports/` são ignorados pelo Git e contêm só IDs/agregados.

```text
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --output-dir build/reports/task-9-remaining-before
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --output-dir build/reports/task-9-remaining-after
uv run python ferramentas/medir_sugestoes_progressivas.py --repeats 2 --budget-ms 3000 --output build/reports/task-9-remaining-progressive.json
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --benchmark-repeats 1 --output-dir build/reports/task-9-remaining-final
```

`remaining-after` é exclusivamente o protótipo rejeitado, não o produto final.
O benchmark progressivo foi executado após retirar o protótipo, separado do
benchmark completo e dos testes. Foram 36 amostras por tamanho na detecção
inicial e oito na sequência de sugestões, com dicionário aquecido, cache do SO
preservado e p95 nearest-rank:

| Medida preservada | Resultado |
|---|---:|
| Detecção inicial, 1 linha, p95 ms/comentário | 2,237 |
| Detecção inicial, 10 linhas, p95 ms/comentário | 4,397 |
| Detecção inicial, 50 linhas, p95 ms/comentário | 32,348 |
| Primeira opção warm, p95 ms | 28,827 |
| Terminal warm, p95 ms | 2640,390 |
| Primeira opção incluindo arranque inicial, p95 ms | 2672,620 |
| Timeouts na sequência, orçamento 3 s | 0/8 |
| Pico na sequência FIFO de duas janelas simuladas | 1 filho, 1 pendência |
| Espera da segunda janela após submit, ms | 1340,702 |

O replay final, após retirar o protótipo, terminou com exit 0 e confirmou
**TP=9, FP=1, misses=2; precisão=90%, recall=81,82%; stable=false**. Foram zero
falhas e zero violações protegidas, cobertura ortográfica com alternativas 4/4
e TA-004 literal verdadeiro. A decisão de não aceitar a regra não foi usada
para esconder os números abaixo do gate.

O benchmark completo síncrono usou 18 amostras por tamanho, uma repetição,
JVM aquecida e cache do assistente desativado. Com n=18, p95 nearest-rank é o
máximo observado:

| Linhas/comentário | p95 ms/comentário | Falhas | Meta de 500 ms |
|---|---:|---:|---|
| 1 | 2953,833 | 0 | não |
| 10 | 3049,784 | 0 | não |
| 50 | 3166,314 | 0 | não |

Essa API completa mantém a busca síncrona de sugestões por compatibilidade;
o editor usa a etapa inicial e solicita sugestões separadamente. Não se
comparam as duas latências como se produzissem o mesmo resultado no mesmo
instante. Não se somaram percentis de spelling e gramática.

Detecção inicial não inclui sugestões, debounce, polling Tk ou concordância.
Os tempos medidos não demonstram a meta de 20 ms para a primeira sugestão nem
uma garantia de terminal em 3 s incluindo fila/carga/limpeza. Não houve medição
de heartbeat Tk, UI real, RSS ou executável nesta investigação.

O tagger recebeu apenas material sintético via stdin; stdout/stderr do Java
foram capturados em memória e reduzidos a códigos POS/contagens/linhas antes
de saída. A configuração temporária do logger continha apenas configuração,
foi removida ao terminar e não alterou vendor/configuração compartilhada.
Não foram gravados comentários em temporários, logs ou dumps. Os probes
HTTP normais continuaram usando o processo local com projeção e sem pool.

Validação focada final, sem suíte completa:

```text
uv run python -m pytest tests/test_portuguese_prefix_suggestions.py tests/test_spelling_suggestions_process.py tests/test_writing_progressive.py tests/test_writing_corpus.py tests/test_corretor.py -q --tb=short
123 passed, 21 subtests passed in 38.55s

uv run ruff check tests/test_portuguese_prefix_suggestions.py
All checks passed!

uv run mypy tradutor_pgn/writing_assistant.py tradutor_pgn/spelling_suggestions_process.py tradutor_pgn/languagetool_client.py
Success: no issues found in 3 source files
```

Os módulos tipados acima foram conferidos no estado preservado; nenhum tem
diff final. Não foram necessários resets de vendor, mudanças de fixture para
ausência de vendor ou exclusões de testes nesse conjunto. Não há Java
remanescente após o benchmark completo e o teste real de worker encerra/join
seu serviço no cleanup.

Hashes preservados:

```text
corpus: 2d8055e72e0b351309d78bd41dd63ee21aa7e6d91168bc0aae646675f341afde
grammar.xml local: 02636232d3fb2bd15adc9be26506ef6abf4d8ac2ab59e2dd23f99ed4f6f77407
pt_BR.dic: bc9410b115fb717773585658dc14c0d98d0933db87ae175c160c2321f4a9c273
pt_BR.aff: 8427837d0ce374c628e8e90fbffab55f617f345d1774e9f9d1e2bef489b0508a
```

Corpus, denominadores, thresholds, preferências, pool LT, vendor e gate de
licença não foram alterados. Os três diagnósticos previamente não rastreados
foram preservados. Nenhum binário, artefato bruto ou payload entra no commit.
