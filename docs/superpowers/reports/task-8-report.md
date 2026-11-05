# Task 8 — aquisicao, runtime e empacotamento LanguageTool

Data: 2026-10-29. Estado: **incremento parcial; release bloqueado**.

O prototipo passou o orcamento local de startup/RAM depois da correcao do health
check. A tarefa nao esta pronta: auditoria de redistribuicao/fontes/notices e o
aceite literal TA-004 continuam pendentes. Nenhum instalador ou portatil foi
publicado, e nenhum ZIP/JDK/runtime binario foi adicionado ao Git.

## Implementacao

- Lock fixa LanguageTool 6.6 e Temurin 17.0.20.1+1 Windows x64, fontes HTTPS
  oficiais, SHA-256 literal, arquivos esperados e licencas principais.
- `fetch` usa cache enderecado por hash, temporario `.part`, verificacao antes
  da extracao, orcamento de ZIP e rejeicao de traversal, dispositivos Windows,
  ADS, symlinks, colisoes e caminhos ambiguos. Publicacao usa rename/rollback.
- `runtime` verifica fontes preparadas, executa jdeps multi-release 17 e jlink
  com strip-debug/no-header-files/no-man-pages/compress=2. Smoke precede a
  publicacao. Medidas, SBOM, auditoria e modulos persistem mesmo em falha.
- Runtime reduzido, JARs/dados, configs, lock, SBOM, notices e manifesto de hashes
  entram no onedir. JDK/jmods/ferramentas de build ficam fora. Scripts e spec
  recusam recursos, checksums ou auditoria incompletos antes do build; o zip
  valida os recursos novamente. Inno inclui a arvore onedir e guarda recursos
  essenciais antes de compilar.
- CI unitario usa fakes. Job Windows prepara fontes/runtime, faz smoke sem Java
  no PATH, exige o gate e publica evidencias mesmo quando bloquear. Actions
  foram fixadas por SHAs conferidos na API oficial; permissoes: contents/read.
  O workflow remoto ainda nao foi executado. Apos o fix round 1, a suite
  ordinaria roda em push/PR sem executavel; o job de release autocontido exige
  workflow_dispatch e opt-in explicito. Esse job continua recusando release
  enquanto a aprovacao separada de redistribuicao estiver bloqueada.

## Fontes e hashes

| Entrada | Tamanho | SHA-256 |
|---|---:|---|
| LanguageTool-6.6.zip | 251.998.221 B | `53600506b399bb5ffe1e4c8dec794fd378212f14aaf38ccef9b6f89314d11631` |
| OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip | 190.817.615 B | `e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0` |

Os dois ZIPs locais foram recalculados. SHA do LanguageTool confere com o
[anuncio oficial 6.6](https://forum.languagetool.org/t/ann-languagetool-6-6/11206).
Temurin confere com o campo `digest` do asset na
[API oficial do release](https://api.github.com/repos/adoptium/temurin17-binaries/releases/tags/jdk-17.0.20.1%2B1)
e o checksum previamente coletado do
[asset oficial .sha256.txt](https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip.sha256.txt).
Houve timeouts nas conexoes GitHub diretas; a API voltou a responder e os dados
foram conferidos novamente, sem substituir fontes por espelhos desconhecidos.

Refs das actions foram consultadas em `git/ref/tags/v4` ou `v5` e o commit
resultante foi conferido, antes de alterar o workflow:

- [actions/checkout v4 — 11d5960a326750d5838078e36cf38b85af677262](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262)
- [astral-sh/setup-uv v5 — d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86](https://github.com/astral-sh/setup-uv/commit/d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86)
- [actions/upload-artifact v4 — ea165f8d65b6e75b540449e92b4886f43607fa02](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02)

## Licencas: evidencia, sem aprovacao presumida

[Inventario versionado](../../../LICENSES/LanguageTool-6.6-evidence.json):
141 JARs, 110 arquivos de dicionario (incluindo membros de JAR), 37 binarios
nativos dentro de Hunspell/JNA/Netty e 92 notices do runtime gerado. O gerador
exporta POMs e notices embutidos byte a byte e preserva o `runtime/legal/`
completo, os notices originais do LanguageTool e o NOTICE do Temurin.

Todos os 42 JARs sem POM embutido foram comparados por SHA-256 com o binario
oficial do Maven Central; somente apos identidade confirmada o POM da mesma
versao foi usado como evidencia. Tambem foram examinados 72 POMs ancestrais.
URLs, hashes, declaracoes e falhas de coleta/parse estao no JSON; entre as
pendencias embutidas ha `com.sun.istack:istack-commons:3.0.11` (ParseError).
Declaracoes de POM sem namespace XML tambem sao lidas. Licencas de componentes
sombreados permanecem ligadas ao componente, nao ao JAR inteiro. Declaracoes
multiplas nao foram convertidas em AND/OR por conjectura.

O README de third-party do ZIP lista versoes antigas, por exemplo bibliotecas
de 2021. O POM Maven atual `languagetool-parent:6.6` tambem nao pode substituir
a identidade dos JARs: declara logback 1.5.18, enquanto o ZIP fixado contem
1.5.8. A evidencia do binario/POM embutido tem precedencia.

Pendencias reais de redistribuicao incluem dicionario Asturiano com declaracao
GPL v3, Irlandes GPL v2 e declaracoes GPL/LGPL do Catalan; termos dos dados,
fontes correspondentes e notices de bibliotecas/nativos transitivos precisam
ser consolidados. JARs MyBatis/JAXB contem varias dependencias embutidas.
A LGPL do core nao foi atribuida automaticamente a esses dados/payloads.
Fontes de dicionarios pt: [repositorio oficial](https://github.com/languagetool-org/portuguese-pos-dict).
O release Temurin publica o asset de fontes com SHA
`21e2a065d244ab048e737f21af5d1fc74daaeb6707de36477ead8db1dca71214`;
sua existencia nao foi tratada como uma oferta de fontes deste distribuidor.

O extrator base sinaliza 99 lacunas de declaracoes ausentes/herdadas; isso nao
significa 99 pacotes sem licenca: o JSON suplementar fornece identificacoes e
ancestrais adicionais. O estado de redistribuicao continua incompleto. O gate
nao pode ser liberado apenas esvaziando a lista `unresolved`.

O SBOM final foi validado com o
[schema oficial CycloneDX 1.6](https://cyclonedx.org/schema/bom-1.6.schema.json),
usando jsonschema temporario via `uv run --with jsonschema`. O runtime gerado
tem componente proprio com SHA de `runtime/lib/modules`; hashes dos ZIPs sao
identificados como entradas de build. Validade estrutural nao equivale a uma
auditoria completa de licencas. [Contexto e pendencias](../../../LICENSES/README.md).

## Medicao e diagnostico

O smoke original `Os cavalo branco joga.` nao gera a concordancia esperada no
LT 6.6. O novo smoke exige a regra real `GENERAL_NUMBER_AGREEMENT_ERRORS`,
categoria nominal, span `cavalos branco` e sugestao `cavalos brancos`, para
`Os cavalos branco.`. Um alerta ortografico ou uma regra qualquer nao basta.
Tambem foi conferido `Eles joga xadrez.` / `GENERAL_VERB_AGREEMENT_ERRORS`.

Primeiro gate antes da otimizacao: **10,450070 s** de startup, **1,571683 s** de
primeira analise, **12,021753 s** ate o primeiro resultado e pico **606.773.248 B**.
Exit 1; staging descartado, runtime nao publicado. Esse resultado e todos os
ensaios desfavoraveis foram mantidos no
[arquivo de medidas](languagetool-startup-measurements.json).

Campanha fixa, sem parar em uma medicao favoravel: cinco JVMs novas por braco,
ordem rotativa, execucao sequencial. Cache de disco do Windows nao foi limpo.
P95 e nearest rank; n=5 implica maximo amostral, nao um limite de confianca
populacional. RSS mede working set da JVM, sem somar Python/Tk. O teto de 30 s
nos diagnosticos serve para observar configuracoes ruins; o gate continua
exigindo startup <=10 s e RSS <=1.000.000.000 B.

| Braco | n / falhas | Startup min / mediana / p95 (s) | Warm mediana (s) | Pico maximo (MB) |
|---|---:|---:|---:|---:|
| Original, health 0,5 s | 5 / 0 | 9,106 / 9,808 / 10,700 | 0,422 | 664,3 |
| SerialGC, health 0,5 s | 5 / 0 | 15,379 / 15,504 / 18,368 | 0,454 | 537,5 |
| C1, health 0,5 s | 5 / 5 | readiness indisponivel | — | nao certificado |
| Original, health 5 s | 5 / 0 | 3,948 / 4,006 / 4,835 | 0,434 | 683,5 |
| C1, health 5 s | 5 / 0 | 4,039 / 4,082 / 4,209 | 0,611 | 584,8 |

No baseline, listener owned fica pronto em mediana 1,422 s, mas o health pt-BR
consome mais 8,254 s. O primeiro check inicializa o pipeline; timeouts de 0,5 s
disparam novas requisicoes durante esse trabalho. Com health 5 s e a JVM
original, listener leva mediana 1,314 s e o restante cai a 2,694 s. O custo nao
foi movido para depois de readiness. SerialGC/C1 nao foram promovidos; somente
o health passou a 5 s, limitado em cada tentativa pelo deadline restante.

Todos os controles funcionais preservaram os mesmos diagnosticos nominais,
verbais e TA-004 e nao tocaram intervalos protegidos. TA-004 integrado retorna
`As pretas tem` → `As pretas têm` e `posiçao` → `posição`. O gabarito exige span
`tem` → `têm`: **esse aceite literal permanece false**. O corpus nao foi
afrouxado para declarar sucesso. Essa diferenca deve ser julgada/corrigida na
validacao linguistica, antes do aceite final.

O [script de replay](languagetool-startup-probe.py) usa as configuracoes
explicitamente (`--campaign jvm` ou `--campaign health`, `--runtime <pasta>`).
Os dados baseline foram coletados antes da correcao do processo; um replay no
checkout atual inclui tambem o novo limite por tentativa. O runtime diagnostico
usou os mesmos modulos jlink, JARs e regras do candidato; nao foi alterado o
classpath para suprimir regras/idiomas durante a comparacao.

Modulos: `java.base,java.compiler,java.desktop,java.instrument,java.naming,java.scripting,java.sql,jdk.attach,jdk.charsets,jdk.crypto.ec,jdk.httpserver,jdk.jdi,jdk.management,jdk.unsupported`.

Runtime real com a correcao: startup **4,671806 s**, primeira analise **1,747866 s**,
primeiro resultado **6,419671 s**, pico **604.426.240 B** (exit 0).
CLI smoke final: startup **4,033724 s**, primeira analise **1,597517 s**, primeiro
resultado **5,631241 s**, warm **0,450823 s**, RSS cold **491.880.448 B**, warm
**563.765.248 B**, pico **602.722.304 B** (exit 0). PATH vazio, proxies e injecao
de opcoes Java removidos do subprocesso, somente HTTP IPv4 loopback owned.

Tamanho: runtime **47.838.546 B**, LanguageTool **405.072.337 B**. A soma e
**452.910.883 B** antes dos metadados/notices. Aumento real de dist/instalador:
**nao medido**, pois o gate de licencas impede construir essas entregas. Nao foi
apresentado tamanho logico como se fosse uma entrega medida.

## RED/GREEN e verificacao final

Testes de aquisicao/ZIP/rollback basicos ja existiam nos arquivos nao rastreados
da retomada. Nao atribuo a esta retomada um RED anterior que nao foi observado.
Foram observados RED e GREEN nesta retomada para:

- smoke exigir concordancia, span e correcao reais;
- nao transferir licenca de dependencia sombreada ao JAR inteiro;
- bloquear auditoria incompleta e exportar somente recursos de entrega;
- recusar zip sem recursos offline;
- preservar `LICENSES-en.txt` de dicionarios e ler POM sem namespace;
- inventariar nativos internos e identificar o runtime pelo hash real;
- preservar medidas/SBOM/auditoria/modulos de prototipos rejeitados;
- servidor de health real que demora 0,75 s: antes falha com timeouts curtos,
  depois fica pronto com uma unica requisicao;
- deadline de 0,65 s: antes um retry terminava em 0,70 s, depois fica limitado
  ao orcamento restante e encerra o filho.

Verificacao final, sem suite completa conforme escopo recebido:

```text
uv run python -m pytest tests/test_languagetool_packaging.py tests/test_settings.py tests/test_languagetool_process.py -q
142 passed, 19 subtests passed in 8.53s
uv run ruff check <arquivos Python alterados e script de replay>
All checks passed!
uv run mypy ferramentas/preparar_languagetool.py tradutor_pgn/languagetool_process.py
Success: no issues found in 2 source files
git diff --check
exit 0
uv run python ferramentas/preparar_languagetool.py smoke
exit 0, metricas acima
uv run python ferramentas/preparar_languagetool.py validate
exit 1, incomplete license audit
uv run python instalador/gerar-entregas.py --so-exe
exit 1, incomplete license audit, antes de PyInstaller
```

SBOM schema: PASS. Gates de erro acima sao recusas esperadas, nao falhas ocultas.
Ruff/mypy e os testes focados passaram apos as correcoes. O diff-check do staging
identificou whitespace original nos textos de licenca dos fornecedores.
`.gitattributes` preserva esses `.txt` verbatim, sem autocrlf/whitespace lint;
os hashes do index foram comparados com os arquivos originais. Codigo continua
sob diff-check normal. Git avisou conversao LF/CRLF nos arquivos de processo.
Inno/PyInstaller
e as entregas completas nao foram executados sobre um candidato nao aprovado.

## Trabalho restante

1. Fechar termos e fontes correspondentes de todos os dados, nativos e
   dependencias distribuidos; consolidar as evidencias num gate auditado.
2. Resolver o aceite literal TA-004 sem reduzir criterios nem ocultar diferencas.
3. Executar CI Windows e smoke instalado/portatil, medir o incremento real de
   dist/instalador e os gates integrados de precisao/desempenho.

Commit deste incremento e informado pelo implementador apos staging seletivo.
Este relatorio nao marca a Task 8 como concluida nem autoriza publicacao.

## Fix round 1 — cinco Important da revisao

Estado: cinco correcoes implementadas; auditoria real continua **blocked**.

1. **Inventario nao aprova redistribuicao.** Ha uma decisao separada, controlada
   pelo repositorio, em `recursos/languagetool-release-approval.json`. O arquivo
   real esta bloqueado, sem componentes aprovados. A copia no candidato precisa
   ser identica a decisao confiavel, e o hash precisa cobrir a arvore completa
   de recursos, inventario/SBOM e evidencias. Cobertura e derivada dos bytes:
   JARs, POMs sombreados, dicionarios, nativos e agregados runtime/recursos. Cada
   componente exige decisao/hash e partes aprovadas separadamente para licenca
   (expressao/evidencias), fonte (HTTPS/hash/evidencias de disponibilidade) e
   notices (arquivos/hashes). Evidencia primaria `blocked` tambem recusa release.
   Nenhum comando gera aprovacao. Os testes de aprovacao usam apenas autoridade
   sintetica isolada, sem alterar a decisao real do projeto.
2. **Arvore inteira da entrega verificada.** A validacao inspeciona tambem os
   arquivos de aplicacao/dependencias de `_internal`, fora do namespace de hash
   do sidecar. Chaves, temporarios de chaves, bancos/SQLite WAL, logs, corpus e
   payloads privados sao recusados antes de abrir o ZIP. Codigo compilado e
   notices legitimos em pacotes chamados cache/logs nao sao confundidos com
   dados pessoais.
3. **Inventario de fontes completo.** Adicoes, remocoes e alteracoes sao
   comparadas antes de jdeps e de smoke. Saidas geradas conhecidas ficam fora
   desse conjunto; o staging novo copia somente as entradas verificadas. Saidas
   ou evidencias de uma rodada anterior nao viram entradas no novo candidato.
4. **Deadline absoluto do health.** Requests deixou de transportar o health
   de startup. O leitor HTTP aplica o deadline abaixo do buffering do parser,
   antes de cada recv, incluindo cabecalhos e chunks/body, com corpo limitado.
   O listener continua sendo atribuido ao filho antes de enviar a requisicao.
   Timeout fecha resposta/socket e o lifecycle termina e recolhe o proprio
   filho. Nao ha thread de watchdog ou worker abandonado. Analises comuns
   continuam usando o adapter existente; essa correcao e do startup.
5. **Inno direto executa a validacao real.** O preprocessador chama o validator
   ancorado em SourcePath usando o Python do ambiente de build, aguarda exit 0
   e valida o proprio DistDir. Ausencia do ambiente, decisao bloqueada, recursos
   adulterados ou dados privados recusam compilacao; nao ha marker de aprovacao.
   Em projeto isolado, o compilador real recusou os dois casos e compilou a
   fixture sintetica aprovada, comprovando que a guarda nao recusa tudo.

Assinatura/retorno do Exec e ancoragem SourcePath conferidos na documentacao
primaria do [ISPP Exec](https://jrsoftware.org/ispphelp/topic_exec.htm) e nas
[variaveis predefinidas](https://jrsoftware.org/ispphelp/topic_predefinedvars.htm).

**Decisao operacional de CI:** push/PR fazem verificacao ordinaria, sem gerar
ou publicar um executavel incompleto. A preparacao autocontida permanece um
release explicito/manual (`self_contained_release`, default false), com todos
os gates. O compromisso de produto de distribuir Java/LanguageTool juntos foi
preservado; nao foi criado um binario alternativo sem concordancia para passar
CI. A sintaxe YAML e a separacao de eventos foram conferidas localmente; nao
houve execucao remota do workflow nem publicacao.

RED/GREEN observados nesta rodada:

- limpar `unresolved`/manifesto e evidencia bloqueada: 2 falhas antes; depois
  recusados, com caminho positivo sintetico e decisoes por parte legal cobertos;
- portatil com chave/banco/log/cache em `_internal/application`: 4 falhas antes;
  variantes chave `.tmp` e SQLite WAL tambem tiveram RED/GREEN; 6 casos privados
  sao recusados sem criar ZIP, e dependencias de programa continuam aceitas;
- JAR extra entrou em jdeps antes da correcao; depois adicao/remocao/alteracao
  das fontes sao recusadas antes das ferramentas;
- servidor owned gotejando: antes cabecalhos **1,790 s** e body **2,221 s**
  ultrapassaram budget **0,65 s**. Depois ambos passam o teste de retorno/cleanup
  (<1,25 s incluindo lancamento e recolhimento), PID limpo e nenhum filho vivo;
  pipeline normal de 0,75 s segue completando numa unica requisicao;
- Inno direto gerou instalador sintetico com decisao bloqueada e com runtime
  adulterado antes do fix (exit 0). Depois ambos sao recusados (sem saida),
  enquanto o candidato sintetico aprovado compila.

Verificacao final do round:

```text
uv run python -m pytest tests/test_languagetool_packaging.py tests/test_languagetool_process.py tests/test_settings.py -q
162 passed, 19 subtests passed in 15.72s
uv run ruff check <arquivos Python alterados>
All checks passed!
uv run mypy ferramentas/preparar_languagetool.py tradutor_pgn/languagetool_process.py
Success: no issues found in 2 source files
git diff --check
exit 0 (avisos de conversao LF/CRLF, sem erros)
Workflow parse/manual release separation: PASS
```

Fetch/runtime reais passaram com o inventario completo. Runtime com o novo
transporte: startup **4,244975 s**, primeiro resultado **5,952508 s**, pico JVM
**632.750.080 B**. CLI smoke final: startup **4,469914 s**, primeira analise
**1,920256 s**, primeiro resultado **6,390170 s**, warm **0,531655 s**, pico
**592.023.552 B**, sem Java no PATH. A regra nominal exigida permaneceu presente.

Os bloqueios anteriores de termos/fontes/notices, TA-004 literal e entregas
reais permanecem. Nenhum componente real foi aprovado nesta rodada. Nenhuma
suite completa foi rodada, conforme o escopo recebido; nenhum binario de teste
ou de vendor entra no commit.
