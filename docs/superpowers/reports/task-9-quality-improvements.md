# Task 9 — melhorias delimitadas de qualidade pt-BR

Data: 2026-11-04. Baseline medido em `a92db95`. Windows, Python 3.13.2,
Spylls/VERO local e LanguageTool 6.6 preparado em `build/vendor`.
Concordância continua experimental, com default false. Precisão de 90% ainda
reprova o mínimo de 95%; esta rodada não aprova estabilidade ou distribuição.

## Escopo e evidência da causa

Foram lidos a spec do assistente, `task-9-report.md`, o diagnóstico de qualidade
e desempenho, o corpus e os adapters/proteções atuais. Esta rodada altera
somente a normalização do adapter LanguageTool e seus testes.

O XML **do vendor local** em
`build/vendor/languagetool/org/languagetool/rules/pt/grammar.xml` tem SHA-256
`02636232d3fb2bd15adc9be26506ef6abf4d8ac2ab59e2dd23f99ed4f6f77407`.
Nele, `LIGACAO_ECG_V3` é uma regra individual com um pattern, sem subIDs:
determinante/pronome feminino, substantivo feminino opcional, ser/estar e
adjetivo masculino marcado; a sugestão transforma o gênero do adjetivo.
Por isso o mapeamento acrescenta **somente esse ID exato** à categoria
`NOMINAL_AGREEMENT`. Não infere categoria por prefixo `LIGACAO_ECG`.
As fronteiras V2/V30 continuam `GRAMMAR` nos testes de parser.

O teste real compara o caso `source-names` no original e na projeção: o alerta
`UPPERCASE_SENTENCE_START` existe apenas na projeção. A análise agora reconhece
essa premissa artificial somente quando todas as alternativas capitalizam
exclusivamente a primeira letra e o início lexical maiúsculo foi ocultado por
proteção de origem/glossário **na mesma sentença e linha originais**. Pontos,
interrogação, exclamação, reticência e quebras Unicode interrompem esse contexto.
Texto lexical visível, origem minúscula ou proteção técnica interveniente
impedem a supressão. Aspas e emoji podem decorar o início lexical.

`SPACE_BEFORE_PUNCTUATION2` também existe no original de `ambiguous-ellipsis`:
não é atribuído à máscara. O reconhecimento editorial aceita somente espaço
horizontal entre palavra e reticência isolada terminal, exatamente três pontos
ou U+2026, com eventual espaço horizontal final. Todas as alternativas devem
remover **só** aquele espaço. O match pode cobrir apenas o primeiro ponto, como
acontece no motor 6.6. Reticências internas/antes de aspas, quebras de linha,
outra pontuação, sequências de dois/quatro pontos e alternativas que mudam
conteúdo ficam fora desse reconhecimento conservador.

Nenhuma regra/categoria foi desativada globalmente. `check` e o parser continuam
retornando os diagnósticos brutos; apenas `analyze`, que conhece a projeção e o
original, aplica as duas decisões contextuais. O caminho normal continua
enviando exclusivamente texto projetado ao processo local. A comparação com
original ocorre somente no teste sintético explícito.

## TDD e controles

Antes do mapeamento, o teste exato V3 falhou por `GRAMMAR` em vez de
`NOMINAL_AGREEMENT`; os dois controles V2/V30 passaram. Depois: 3 passaram.

Antes do filtro de capitalização:

```text
uv run python -m pytest tests/test_languagetool_client.py -k masked_capitalization -q --tb=short
5 failed, 18 passed, 51 deselected in 12.40s
```

Depois, com controle adicional de outra regra:

```text
uv run python -m pytest tests/test_languagetool_client.py -k 'masked_capitalization or masked_context' -q
24 passed, 50 deselected in 12.71s
```

Antes do reconhecimento de reticência terminal:

```text
uv run python -m pytest tests/test_languagetool_client.py -k terminal_ellipsis -q --tb=short
5 failed, 18 passed, 74 deselected in 12.38s
```

Depois:

```text
uv run python -m pytest tests/test_languagetool_client.py -k terminal_ellipsis -q
23 passed, 74 deselected in 12.25s
```

Houve um primeiro rascunho desse teste com duas asserções equivocadas sobre o
texto original: `!`/`?` isolados são NAGs mascarados pelo protetor atual. Foram
corrigidas para conferir o span **projetado** antes de alterar produção; o RED
acima já contém essa correção, com só as cinco falhas comportamentais esperadas.

Os testes HTTP/normalização exercitam offsets UTF-16 após emoji, fonte em NFD,
acentos, NBSP, aspas, glossário, pontuação e CRLF/U+2028/U+2029. Os negativos
preservam alertas após ponto/quebra, no começo do comentário, após tag/NAG/lance,
com contexto incerto e com outras alternativas. Os testes existentes continuam
validando proteção contra spans cruzados/obsoletos e propriedades Unicode.

`tests/test_writing_quality_real.py` acrescenta 43 controles opt-in com LT 6.6
real, separados do corpus e dos seus denominadores: sete positivos de gênero,
sete controles corretos/ambíguos, capitalização original/projetado, fronteiras
técnicas, Unicode/proteções, reticência/pontuação e sequência de regra A/B/A.
O primeiro run real teve **42 passed, 1 failed in 24.84s**: o teste supunha
alerta para quatro pontos, mas o antipattern do próprio XML exclui essa forma.
A expectativa do controle foi corrigida para registrar explicitamente a
ausência no resultado bruto e exigir identidade bruto/integrado; nenhum filtro
de produto foi ampliado para ajustar esse caso.

## Replay real do corpus intacto

```text
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --output-dir build/reports/task-9-quality-before
uv run python ferramentas/avaliar_corretor_portugues.py --mode full --output-dir build/reports/task-9-quality-after
```

Ambos terminaram com exit 0, 18 casos analisados, cache do assistente desativado
e sem benchmark. São medições próprias desta rodada. Os JSON/Markdown de cada
execução ficam separados, ignorados pelo Git, e exportam apenas IDs/agregados.

| Medida | Antes | Depois |
|---|---:|---:|
| Esperados | 11 | 11 |
| Apresentados | 12 | 10 |
| TP | 8 | 9 |
| FP | 4 | 1 |
| Misses | 3 | 2 |
| Precisão | 66,67% | 90,00% |
| Recall | 72,73% | 81,82% |
| Falhas de análise | 0 | 0 |
| Violações protegidas | 0 | 0 |
| Typos com sugestões | 4/4 | 4/4 |
| TA-004 literal | true | true |
| Gate estável | false | false |

Só três IDs tiveram mudança: `nominal-gender` passou de FP+miss a TP com o mesmo
ID de regra; `source-names` e `ambiguous-ellipsis` deixaram de apresentar os
alertas cuja premissa foi verificada acima. Os demais 15 casos mantiveram o
julgamento. Nominal após a mudança: 2 esperados, 1 apresentado/TP, 0 FP e 1 miss.
Verbal: 3/3 TP; pontuação: 1/1 TP; repetição: 1/1 TP. Ortografia: 3 TP, 1 FP e
1 miss. O descarte preexistente de alternativas só de pontuação em concordância
verbal continuou em 2, sem mudança desse mecanismo.

O corpus manteve o SHA-256
`2d8055e72e0b351309d78bd41dd63ee21aa7e6d91168bc0aae646675f341afde`.
Gabarito, denominadores, thresholds e preferência não foram alterados.

## Validação final e limites

```text
$env:PGN_TEST_REAL_LANGUAGETOOL='1'
uv run python .superpowers/sdd/2026-10-27-assistente-escrita-portugues/task9_missing_vendor.py tests/test_languagetool_client.py tests/test_writing_quality_real.py tests/test_writing_protection.py tests/test_writing_corpus.py tests/test_writing_assistant.py -q --tb=short
298 passed in 97.22s (0:01:37)

uv run ruff check tradutor_pgn/languagetool_client.py tests/test_languagetool_client.py tests/test_writing_quality_real.py
All checks passed!

uv run mypy tradutor_pgn/languagetool_client.py
Success: no issues found in 1 source file

git diff --check
exit 0 (avisos LF/CRLF, sem erros)
```

O driver diagnóstico preexistente e ignorado pelo Git injeta o resolver de
arquivos ausentes **somente** em
`test_grammar_requested_without_adapter_has_visible_fallback`. Esse teste
legado pressupõe vendor ausente, embora o worktree tenha vendor real; a falha
sem isolamento já está documentada em `task-9-report.md`. A fixture exercita
ausência real de arquivos, não fabrica respostas de gramática e se desfaz ao
final desse teste. Não houve exclusões de testes nem movimentação/alteração
de vendor. Os 43 testes reais mantiveram o provider normal e passaram no mesmo
gate; os dois replays reais foram executados separadamente, sem esse driver.
A suíte completa não foi executada, conforme o escopo solicitado.

Ao terminar, a consulta de processos não encontrou `java.exe` remanescente
e o hash do corpus continuou igual ao fixado. O commit seletivo inclui somente
adapter, testes HTTP, testes reais opt-in e este relatório; artefatos brutos,
driver, probe exploratório e diagnósticos anteriores não entram no commit.

`nominal-plural` permanece sem match real; inventar flexão a partir de artigo
e substantivo sem desambiguação/morfologia suficiente não entra nesta rodada.
`spelling-hyphen` continua FP+miss porque a sugestão editorial não é fornecida
pelo dicionário. Não se criou alternativa por substituição textual nem se
alterou o gabarito para aceitar sugestão incorreta.

O reconhecimento de contexto é deliberadamente restrito; casos fora das
fronteiras comprovadas ainda podem produzir alertas inadequados. Os 18 casos
fixos e 43 controles sintéticos não estabelecem generalização populacional.
Não houve benchmark, teste UI/múltiplas janelas ou aprovação de distribuição.
`pipelineCaching=false` permanece: a retenção caracterizada em `a92db95`
continua impedindo habilitar o pool. Nenhum diagnóstico não rastreado de outra
rodada, arquivo de vendor ou configuração compartilhada foi alterado.
