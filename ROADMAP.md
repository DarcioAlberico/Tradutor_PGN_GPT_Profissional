# Roadmap — PGN Tradutor Pro

Registro das melhorias do programa. Cada item traz o motivo, o impacto medido
(quando ha medicao) e como a correcao foi verificada — inclusive quando a
verificacao mostrou que a analise estava errada, caso em que o erro fica no
proprio item.

**Nada pendente.** O item 19.11 (corretor ortografico de prosa), que era o
unico nao entregue do registro inteiro, saiu na secao 26 em 2026-08-03. A secao
22 (revisao de UI) foi concluida nos itens 22.1 a 22.14, em 2026-07-31 e
2026-08-01. As secoes 18 a 20 — que ficaram
registradas aqui como pendentes — foram concluidas em 2026-07-30, junto com a 21
(instalador). As garantias que os testes ja protegem estao na
[SPEC.md](SPEC.md), secao 9 — inclusive as nove da secao 22, que nasceram e
migraram para la no mesmo dia: **F12** (22.1), **Q3** (22.2), **F13** (22.3),
**F14** (22.4), **F15** (22.5), **F16** (22.6), **F17** (22.7), **F18** (22.8) e
**F19** (22.9). A secao 11 continua vazia.

A frase que ficava aqui — "nada pendente no momento" — ja tinha ficado **falsa
por um dia** uma vez, e vale manter o registro: a secao 10 conserta os lances na
hora da traducao, e a medicao que fechou aquele item mostrou 4.144 traducoes ja
gravadas com a letra errada — um pendente que nasceu junto com a correcao e nao
foi registrado aqui. A secao 11 e ele.

**Revisao de 2026-07-31 (secao 22).** Pedido do usuario: uma analise detalhada
do programa com olhos de especialista em UI, com foco na janela "Editar
traduções". O metodo foi o das revisoes anteriores, em seis varreduras paralelas
e independentes (hierarquia visual e descoberta; custo em gestos; estado e perda
de dados; acessibilidade por medicao; as demais janelas; pipeline e indices),
com uma diferenca de evidencia: alem das funcoes reais headless e do banco de
dev em modo somente-leitura, os achados de estado foram confirmados **abrindo a
janela de verdade em sandbox** — o harness da suite GUI, sem tocar dados reais.

As tres descobertas que doem: **tres trocas de lista descartam texto digitado
sem gravar nem avisar** (o filtro de status, o "Limpar" da busca e o proprio
"Rejeitar" — demonstrado em janela real, 22.1, **ja corrigido**, e a correcao
achou um segundo bug dentro dela: a versao obvia grava o status na linha
errada); **o rotulo de QA da tela avaliava sem o par de idiomas** e dizia "sem
avisos" em verde numa linha que o filtro "Avisos QA" mostra (22.2, **ja
corrigido**, e esta correcao tambem achou um segundo defeito no mesmo metodo:
com o editor vazio o rotulo anunciava "traducao vazia"); e **o resumo por status
perdeu o indice de cobertura quando o 19.12 acrescentou `review_status` a
agregada** — a consulta de toda
recarga da lista voltou a tocar a tabela, 118,8 ms contra 60,8 ms em 204 mil
linhas sinteticas (22.13). E a camada visual, medida pela primeira vez: as
quatro cores semanticas de rotulo reprovam no contraste WCAG em pelo menos um
tema, com o ambar dos avisos a 1,55:1 no tema claro (22.9).

**Revisao de 2026-07-29 (secoes 13 a 20).** Pedido do usuario: uma analise do
programa inteiro com os olhos de um tradutor profissional de livros e arquivos
de xadrez — falhas, melhorias e dicionarios. O metodo foi o da revisao de
2026-07-27, em maior escala: tres varreduras paralelas e independentes (o
glossario real regra a regra; o pipeline de traducao e o banco; a interface e o
fluxo de revisao), cruzadas com duas fontes de evidencia desta maquina — o banco
de desenvolvimento (6.500 traducoes en -> pt, uma amostra real de livro de
xadrez) e reproducoes das corrupcoes com as funcoes reais do programa, nao com a
API. Onde um achado veio de analise estatica e nao pode ser reproduzido, isso
esta dito no proprio item.

O tema que domina esta revisao: **o programa protege com rigor o que esta FORA
de `{...}` e trata tudo que esta DENTRO como prosa.** Lances, variantes, NAG e
tags saem byte a byte identicos — e sempre foi o acerto central do desenho. Mas
dentro do comentario vivem coisas que tambem nao sao prosa: as anotacoes de
maquina (`[%cal]`, `[%eval]`, `[%clk]`) do Lichess e do ChessBase, simbolos de
avaliacao, numeros de lance. Nada as protege, e duas corrupcoes deterministicas
foram confirmadas em execucao (secao 13).

As tres descobertas que doem:

- **A correcao de lances reescreve as setas do Lichess.** `[%cal Ra1h8]` (seta
  vermelha de a1 a h8) vira `[%cal Ta1h8]` — o codigo de cor `R` colide com a
  letra da Torre. Confirmado com a funcao real; e deterministico; e a ferramenta
  "Corrigir Lances" faz o mesmo em massa, sobre linhas ja verificadas (13.1).
- **401 das 6.500 traducoes do banco de desenvolvimento tem erro de terminologia
  enxadristica** detectavel por padrao simples — "White" sem traduzir, "check"
  como "cheque", "file" como "arquivo" — e o `quality_warning` marca 11 linhas,
  **nenhuma das 401**. O glossario do usuario ja sabe corrigir praticamente
  todas: o conhecimento existe, esta preso no tipo `suggestion`, aplicado um a
  um, a mao (16).
- **O dicionario tem um erro factual de xadrez**: `=/+` — vantagem das pretas —
  esta traduzido como "com leve superioridade para as brancas". Uma regra
  automatica que inverte a avaliacao do comentario (14.1).

E o quadro geral do dicionario, medido regra a regra: 7.105 regras, das quais
6.958 `suggestion`, 147 `automatic`, **zero** `cleanup` e zero com prioridade;
210 mortas por colisao de caixa que o detector de conflitos nao enxerga; 1.235
enumerando casas do tabuleiro a mao; cobertura real de 1,5 idioma dos 7
anunciados (fr/de/it/ru: nenhuma regra). O glossario e a maior forca do programa
e o lugar onde ha mais o que consertar — as secoes 14 e 15 sao o plano.

**A secao 14 foi feita no mesmo dia, e ela corrigiu duas afirmacoes do
diagnostico acima** (o `=/+` e sugestao e nao automatica; das 210 mortas, 166 nao
fazem falta). O detalhe esta la; o que fica registrado aqui e o metodo: a
diferenca saiu de medir cada afirmacao contra o glossario real, uma por uma, em
vez de aceitar a lista.

**As secoes 16 e 17 foram feitas no mesmo dia, e as duas repetiram o padrao.** Na
17, tres das dez afirmacoes nao sobreviveram a tentativa de implementa-las: 17.4
falava de uma confirmacao que nao existia, 17.5 dizia que o dado ja estava
calculado e ele nao estava, e 17.10 inflava em 92% o tamanho do dicionario que
estava sendo apagado. Na 16, **duas das oito heuristicas planejadas morreram na
medicao** — o multiconjunto de digitos marcava 3 linhas e as 3 eram formatacao
correta em portugues; `exchange` -> `troca` marcava 178 e a maioria estava certa.

E cada uma das duas secoes tem um tema proprio que vale destacar:

- **17:** as seis ferramentas de escrita em massa tinham tres guardas iguais
  escritas tres vezes, e as outras tres nao tinham nenhuma. A correcao nao foi
  acrescentar tres copias — foi tirar as tres que existiam de onde estavam.
- **16:** o conhecimento que faltava ao aviso de qualidade **ja estava no
  programa**. As ancoras de lance vieram da secao 10, o padrao de anotacao da 13, a
  terminologia da 14 — e o item foi quase todo ligar uma coisa na outra. O que
  precisou ser escrito de novo foi o mecanismo de VERSAO (16.2), que e o que impede
  a melhoria de violar a garantia R6 nas 200 mil linhas ja avaliadas.

**Revisao de 2026-07-28 (secoes 9 e 10).** Quatro pedidos do usuario, e o que os
une nao e o tema — e o fato de todos serem **decisoes dele que o codigo nao tinha
como tomar sozinho**. Qual e a lingua do PGN, qual par revisar agora, e quando o
trabalho acumulado deixou de servir. Ate aqui o programa adivinhava a primeira
(`sl=auto`), ignorava a segunda e nao oferecia a terceira.

O quarto (secao 10) e o unico que nao foi pedido como funcionalidade: veio como
diagnostico, e um diagnostico quase certo. A queixa era que converter `K` e `R`
em portugues depende da ordem; medindo, o problema nao e a ordem — e a
**sequencia**, e inverte-la so troca qual peca e destruida. A secao 10 depende da
9: so da para ler os lances do comentario original porque o idioma de origem
passou a ser declarado.

**Revisao de 2026-07-27.** Os itens 1.4, 1.5, 2.7 a 2.10 e as secoes 6, 7 e 8
sao novos. Sairam de uma analise do codigo inteiro com o banco real (195.607
traducoes, 80 MB) e o glossario real (7.065 regras: 7.008 de sugestao e 57
automaticas). Os numeros abaixo foram medidos nesta maquina, nao estimados; o
metodo esta descrito em cada item para poder ser refeito.

O tema que domina esta revisao e novo: ate aqui as medicoes olharam para uma
janela de cada vez. **As tres piores descobertas aparecem quando duas partes do
programa funcionam ao mesmo tempo** — o editor gravando enquanto o worker segura
o banco (6), o botao "Aplicar automaticas" segurando a interface por 38 s (2.7)
e o lote que cai no modo individual quando a rede falha (7.1).

A secao 6 traz tambem a correcao de uma analise errada minha: o item nasceu
culpando a leitura do editor, com medicao e tudo, e a medicao era de um cenario
que o programa nao produz. Quem descobriu foi a tentativa de transformar a
medicao em teste — ela nao reproduziu. O relato do erro ficou no proprio item,
porque a conclusao certa (o que trava e a escrita) so faz sentido ao lado da
errada.

**Segunda rodada do mesmo dia.** Entraram 3.5, 2.11, 5.1 e a parte 2 do 1.5.
**Os quatro ja estavam anotados em algum lugar** — nenhum foi descoberto agora —,
e o tema da rodada e o que aconteceu com essas anotacoes. Em tres, a nota existia
e **dizia menos do que o problema era**:

| o que a nota dizia                                                        | o que era                                                                                               |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| "11 de 25 funcoes de`app_actions` aparecem em algum teste" (5.1)        | aparecer nao e ser exercitada:**cinco** eram chamadas                                             |
| "agora que`background_task` existe, migra-los e mecanico" (2.7 -> 2.11) | cada operacao deixa um lixo diferente ao ser cancelada, e ligar as tres expos um defeito do proprio 2.7 |
| a assimetria dos dois editores, anotada na skill como armadilha de uso    | era divida estrutural — o item 3.1 inteiro, no outro editor, e sem estar no ROADMAP                    |

No quarto (1.5 parte 2) a nota estava certa e foi **ignorada**: ela dizia "so
depois que mostrar o vencedor estiver em uso e ficar claro que nao basta", e esse
periodo de uso nao houve. Foi feito por decisao de seguir adiante. Isso esta dito
no item, e nao dissolvido no meio do relato.

**Trinta e sete mutacoes nesta rodada, e tres delas nao quebraram nada** — ou
seja, tres testes meus nao testavam nada. Os tres pelo mesmo motivo de fundo, que
so ficou obvio depois de aparecer duas vezes: **o cenario do teste usava o valor
padrao, e com ele a producao quebrada e indistinguivel da correta.**

- Afirmar que um botao esta habilitado **sem nunca te-lo desabilitado** (5.1):
  remover o `reset_buttons` nao muda nada, porque ele ja estava habilitado.
- Digitar uma prioridade invalida numa regra que ja valia **zero** (1.5): gravar
  "zero por engano" reproduz o arquivo anterior.
- Atualizar uma entrada de prioridade **zero** tendo a linha-base tambem em zero
  (1.5): comparar a prioridade acerta por coincidencia.

Em todos, o teste passava com a producao certa e com a errada — que e a
definicao de nao proteger nada. A correcao foi a mesma nos tres: partir de um
valor que nao seja o padrao.

**Quarta rodada: o 3.7**, e ele veio de uma decisao do usuario — versionar o
`glossario.db` — que **nao funcionava sozinha**. As marcas que dizem de onde o
banco veio eram um caminho absoluto e um `mtime`, e as duas divergem em qualquer
clone: o indice versionado seria descartado e reconstruido em toda maquina. O
item e o que faltava para a decisao valer, e o tema dele e esse: uma mudanca de
configuracao que so tem efeito depois que o codigo aceita a nova situacao.

**Terceira rodada do mesmo dia: so o 3.6**, e ele nao saiu de uma medicao nem de
um bug — saiu de ler a secao 9 da SPEC procurando o que ainda descrevia um
defeito em vez de uma escolha. Sobrou um: o vencedor do conflito calculado em
dois lugares. **O item nao muda comportamento nenhum** (conferido em 19.667
grupos sorteados, zero divergencias), e por isso ele so existe se o teste que o
acompanha souber distinguir "os dois concordam" de "os dois sao o mesmo" — que e
a distincao que o teste antigo nao fazia, e a razao de o problema ter
sobrevivido a duas rodadas de revisao com a suite verde.

---

## 1. Higiene do glossario

### 1.1 Espacos nas pontas das entradas — CONCLUIDO (2026-07-25)

100 das 7070 entradas tinham espaco no inicio ou fim do padrao ou da
substituicao. Destas, **48 eram assimetricas**: o padrao consumia um espaco que
a substituicao nao devolvia, colando palavras no texto final.

```
' a-coluna ' -> ' coluna a'     "antes a-coluna depois" => "antes coluna adepois"
'em a '      -> 'na'            "antes em a depois"     => "antes nadepois"
' -cavalo'   -> '-cavalo'       "antes -cavalo depois"  => "antes-cavalo depois"
```

Resultado da migracao: 7070 -> 7050 entradas (100 normalizadas, 20 duplicatas
exatas eliminadas, 0 padroes vazios). Os 48 casos de colagem foram a zero.
`add_glossary_entry` e `update_glossary_entry` passaram a normalizar na
gravacao, entao o problema nao volta (garantia S7).

Ficaram 2 conflitos em que o mesmo padrao aponta para substituicoes diferentes.
As duas regras foram mantidas — a ordem decide qual vence — e precisam de
decisao manual:

```
'e e f'     -> ["'e' e 'f'", "'e' e f"]
'as Pretas' -> ['as pretas', 'das pretas']
```

### 1.2 Retencao de backups — CONCLUIDO (2026-07-25)

`backups/` acumulou **663 arquivos e 236,8 MB** (medido hoje; eram 213 e 68 MB
quando este item foi aberto) — um snapshot completo do glossario a cada
salvamento, sem politica de descarte.

Criado `tradutor_pgn/backup_retention.py`, com a decisao separada da remocao
(`select_backups_to_delete` e uma funcao pura, testada sem tocar no disco).
Duas regras, aplicadas apos cada backup criado:

1. **Quantidade** — sobrevivem os `keep_count` mais novos (30 para o glossario,
   10 para o banco, que e bem maior por copia). E esta que segura o
   crescimento: o volume vem da frequencia de gravacao, nao do tempo.
2. **Idade** — dos restantes, sai quem passar de `BACKUP_MAX_AGE_DAYS` (60),
   exceto os `BACKUP_KEEP_MINIMUM` (3) mais novos. Sem esse piso, abrir o
   programa depois de um ano sem uso apagaria todos os backups antes de criar
   o primeiro novo.

Aplicada a pasta atual, a politica libera **210,3 MB** e mantem os 30 backups
mais recentes do glossario e os 2 do banco. Tres decisoes de projeto que os
testes protegem:

- **Familias separadas.** `backups/` guarda as duas especies juntas. Sem o
  filtro por prefixo + extensao, salvar o glossario 30 vezes levaria junto
  todos os backups do banco.
- **Ordem vem do nome, nao do `mtime`.** `create_glossary_backup` usa
  `shutil.copy2`, que preserva o mtime da origem: todas as copias herdam a data
  do `Substituicoes.txt` e ordenar por mtime daria uma ordem arbitraria — e a
  ordem e o que decide quem morre. O desempate de arquivos do mesmo segundo le
  o sufixo `-1`/`-2` como numero: comparado como texto, `.` (0x2E) e maior que
  `-` (0x2D), e o arquivo sem sufixo (o mais antigo) passaria por mais novo.
- **Nada fora do padrao e apagado.** Um arquivo sem carimbo de data no nome
  nunca entra na lista — o que o usuario tiver colocado ali fica. E a
  restauracao protege explicitamente o backup escolhido, que senao poderia ser
  removido pela limpeza no instante entre o backup de seguranca e a leitura.

### 1.3 Falha de carga do glossario e silenciosa (garantia S5) — CONCLUIDO (2026-07-25)

`load_substitutions` capturava a excecao, imprimia em `stdout` e devolvia `[]`.
Num app Tkinter — e principalmente empacotado com `pythonw`, que nao tem
console — esse `print` nao aparece em lugar nenhum: um `Substituicoes.txt`
malformado desativava as 7 mil regras sem um unico aviso, e a traducao saia com
a terminologia errada como se estivesse tudo certo.

Criado um canal de erro em `glossario.py` (`set_glossary_error_handler` /
`report_glossary_error`). O modulo nao importa Tk: quem registra o handler e que
decide como exibir. A janela principal registra o dela **antes** da primeira
carga, que e justamente a que pode falhar.

Passaram a reportar por ele: o `load_substitutions`, o arquivo inexistente e a
falha ao usar o `glossario.db`. O handler da interface escreve no log da janela
e abre um dialogo — pela fila do Tk, porque a chamada pode vir da thread do
worker (garantia C1). A mesma mensagem so abre um dialogo; as repeticoes ficam
so no log, senao um erro de carga interromperia a traducao a cada recarga.

Corrigido junto um efeito colateral do mesmo problema: a carga do glossario na
construcao da janela propagava o erro de parse, entao um arquivo quebrado fazia
o programa **nao abrir** — sem mensagem alguma sob `pythonw`. Agora degrada para
"sem sugestoes" e diz por que.

### 1.4 A retencao nunca alcancou o passivo — CONCLUIDO (2026-07-27)

Medido hoje, dois dias depois de 1.2 ficar pronto:

```
backups/  663 arquivos, 228 MB   (661 do glossario, 2 do banco)
logs/       4 arquivos, 808 KB
```

Ou seja: **os 210 MB que 1.2 prometeu liberar ainda estao no disco.** Nao e um
defeito da politica — e uma consequencia de onde ela e chamada.
`prune_glossary_backups` roda dentro de `create_glossary_backup`, isto e, como
efeito secundario de criar um backup novo. Enquanto ninguem salvar o glossario,
nada e avaliado. Quem parar de editar o glossario fica com a pilha inteira para
sempre, que e exatamente o cenario em que ela mais incomoda.

O acoplamento tambem foi util (a limpeza so acontece quando ja existe uma copia
nova, entao nunca esvazia a pasta), entao a correcao nao e mover a chamada e sim
acrescentar uma: rodar a politica **uma vez na abertura do programa**, para as
duas familias, fora da thread da interface. Os limites e as protecoes ja estao
todos em `select_backups_to_delete`; falta so o gatilho.

`logs/` nunca teve politica nenhuma (esta em "Limites conhecidos" da SPEC desde
o inicio). Sao ~200 KB por execucao de traducao — nada perto dos backups, mas
cresce sem teto. O `prune_backups` quase serve: falta que o carimbo dos logs
(`traducao_20260725_143012.log`, com **underscore**) case com o
`_TIMESTAMP_RE = (\d{8}-\d{6})`, que espera hifen. Duas opcoes, e a segunda e
melhor: mudar o nome dos logs novos para o mesmo formato dos backups (os antigos
deixam de casar e, pela regra "nada fora do padrao e apagado", sobrevivem — o
que e o comportamento certo), ou parametrizar o separador.

**Feito.** `prune_generated_files` aplica a politica das tres familias e
`run_startup_cleanup` a chama na abertura, numa thread — numa pasta com meses de
uso sao centenas de arquivos, e nada disso interessa a quem esta abrindo o
programa. O resultado vai so para o log da janela, e uma falha ali nunca impede o
programa de abrir: a limpeza e conveniencia, nao funcionalidade.

A chamada de dentro de `create_glossary_backup` **continua existindo**. Ela tinha
razao de ser (a limpeza so acontece quando ja ha copia nova, entao nunca esvazia
a pasta); a do arranque e adicional.

Os logs adotaram o formato de carimbo dos backups
(`traducao-20260727-143012.log`, com hifen). Como escolher entre mudar o nome ou
parametrizar o separador do `_TIMESTAMP_RE`, mudar o nome e melhor por um efeito
colateral: os logs antigos, com underscore, deixam de casar com o padrao e — pela
regra "nada fora do padrao e apagado" — **sobrevivem**. Uma politica de retencao
nova nao deve estrear apagando o passado do usuario. Ha teste para isso, e
tambem para o modo de falha mais chato possivel: se o formato do nome e o do
padrao divergirem, a retencao de logs vira um no-op silencioso e tudo continua
parecendo funcionar.

### 1.6 A retencao conta arquivos, e o banco cresce — CONCLUIDO (2026-07-28)

Medido hoje, um dia depois de 1.4 fazer a limpeza rodar na abertura. Ela
funcionou: **663 -> 34 arquivos**. Mas 34 arquivos ocupam 237 MB, e vale olhar
de onde eles vem:

| familia   | copias | espaco           | limite    | teto real         |
| --------- | ------ | ---------------- | --------- | ----------------- |
| glossario | 30     | 9,7 MB           | 30 copias | ~10 MB            |
| banco     | 4      | **227 MB** | 10 copias | **~1,1 GB** |

As duas copias mais antigas do banco tem 7,0 e 8,7 MB (junho); as duas recentes,
103,9 e 107,1 MB (julho). O banco passou de ~8 MB para 110 MB no periodo.

**A politica esta correta; o que envelheceu foi a premissa.** Contar arquivos so
limita disco quando os arquivos tem tamanho parecido — verdade para o glossario,
que e um texto de ~334 KB por copia, e falso para o banco. `DATABASE_BACKUP_ KEEP_COUNT = 10` foi escolhido em 1.2 justamente por "cada copia e o banco
inteiro", mas o numero nao acompanha o banco: as mesmas 10 copias que valiam
70 MB em junho valem mais de 1 GB agora, **sem nenhum limite ter mudado**. E a
pasta enche sozinha: backups do banco nascem em quatro operacoes comuns (botao
"Backup BD", importar CSV, aplicar automaticas e o backup de seguranca da
restauracao).

**Correcao.** Terceira regra em `select_backups_to_delete`: teto de espaco
(`max_total_bytes`), aplicada depois da contagem e da idade. Percorre os
sobreviventes do mais novo para o mais velho somando o tamanho e guarda o maior
conjunto de copias RECENTES que cabe — que e o que interessa numa restauracao.
Sofre o mesmo piso `keep_minimum` da regra de idade: um banco maior que o teto
nao pode deixar o usuario sem backup nenhum.

A funcao continua pura — quem le o disco e o `prune_backups`, que passa os
tamanhos prontos. So a familia do banco tem teto (`DATABASE_BACKUP_MAX_TOTAL_MB = 400`); no glossario a contagem continua sendo um bom proxy.

Efeito na pasta real, simulado sem apagar nada: **hoje nao remove nada** (227 MB
de 400) — uma politica nova nao deve estrear apagando o passado do usuario, o
mesmo criterio de 1.4. Depois de mais quatro backups do tamanho atual, mantem 3
copias e 330 MB, contra os 666 MB que as oito ocupariam sem o teto.

**Uma das tres mutacoes nao quebrou nada, e o motivo ja tinha nome.** Remover o
`setdefault` que aplica o teto na familia do banco passou na suite inteira: o
`test_the_default_budget_is_applied` so conferia que a constante era positiva e
que uma pasta vazia nao removia nada. E o mesmo padrao registrado na revisao de
27/07 — **o cenario do teste usava o valor padrao, e com ele a producao quebrada
e indistinguivel da correta**. Encher 400 MB de arquivo e inviavel, entao a
correcao foi descer o teto ate o cenario em vez de subir o cenario ate o teto.
Com isso, as tres mutacoes quebram.

### 1.5 Os conflitos de 1.1 eram decididos por acidente — CONCLUIDO (2026-07-27)

1.1 deixou registrado que sobraram duas regras em que o mesmo padrao aponta para
substituicoes diferentes:

```
'e e f'     -> ["'e' e 'f'", "'e' e f"]
'as Pretas' -> ['as pretas', 'das pretas']
```

(A lista acima e a de 1.1. Medindo hoje sao quatro — ver o fecho do item.)

A anotacao dizia "a ordem decide qual vence". Vale a pena ser mais preciso,
porque a frase esconde o problema: a ordem que decide e a de
`order_rules_by_specificity`, que ordena por **comprimento do padrao** e desempata
pela posicao no arquivo (garantia S3). Como os padroes em conflito sao identicos
por definicao, o comprimento empata sempre, e o vencedor e simplesmente **quem
foi digitado primeiro**. Nao ha nada na interface que mostre isso: as duas
regras aparecem lado a lado no editor, com o mesmo aspecto, e a de baixo nunca
dispara.

O editor ja sabe apontar o caso ("Mesmo original com substituicao diferente." e
o filtro "Conflitos"), mas nao diz qual das duas esta valendo — que e a unica
informacao que o usuario precisa para decidir.

Duas melhorias, na ordem:

1. **Mostrar o vencedor.** No aviso de conflito, dizer qual regra sera aplicada
   e oferecer "manter esta" (que remove as outras do mesmo padrao). Resolve os
   dois casos reais sem mudar o formato do arquivo.
2. **Prioridade explicita** (maior). Hoje a especificidade e a unica forma de
   priorizar, e ela e derivada do texto: para adiantar uma regra e preciso
   alongar o padrao. Um campo de prioridade separado tornaria a intencao
   explicita — mas muda `Substituicoes.txt`, o `glossario.db` e o CSV, entao so
   depois que 1 estiver em uso e ficar claro que nao basta.

**Feito o item 1.** `glossary_conflicts` agrupa as regras que disputam o mesmo
padrao e aponta a vencedora; `describe_glossary_conflict` monta a frase; e
`resolve_glossary_conflict` devolve o glossario com so a escolhida. As tres sao
puras e vivem em `glossario.py`, que nao importa Tk. O editor mostra a frase na
regra selecionada e tem o botao "Manter esta", que lista o que vai remover antes
de gravar.

**Sao quatro conflitos, nao dois.** A anotacao de 1.1 listava dois; medindo hoje
o `Substituicoes.txt` versionado da quatro. Dois entraram depois — nao ha de que
se queixar, e o que uma lista de 7 mil regras editada a mao faz. Por isso entrou
`test_the_real_glossary_conflicts_are_all_reported`, que fixa os quatro padroes:
o proximo conflito quebra a suite pedindo decisao, em vez de aparecer numa
medicao futura.

```
'brancas para jogar'  #1070 'brancas jogam'      vs #7043 'brancas de jogar'
'e e f'               #2621 "'e' e f"            vs #6115 "'e' e 'f'"
'as Pretas'           #5757 'das pretas'         vs #6996 'as pretas'
'/\'                  #6103 'com a idéia de'     vs #7015 'Com a ideia de'
```

**O vencedor e por contexto, e a primeira versao desta mensagem errava nisso.**
`Substituicoes.txt` e uma lista so, mas o programa carrega tres recortes dela
(limpeza; automaticas; sugestoes do editor, que leva sugestoes **e**
automaticas). Duas regras so disputam dentro de um recorte.

O quarto conflito e justamente o caso que expoe isso: `'/\'` tem uma regra de
sugestao (#6103) e uma automatica (#7015). No editor as duas convivem e a de
sugestao vence, por vir antes. Mas na aplicacao das regras automaticas a #7015 e
a unica daquele padrao — e la ela e aplicada. A primeira versao so olhava para os
contextos em disputa e por isso anunciava "esta regra nunca e aplicada" para a
#7015, que e **falso**. Agora a mensagem nomeia os dois contextos:

```
Conflito em '/\': em regras automáticas vence esta regra;
                  em sugestões do editor vence a regra #6103 -> 'com a idéia de'.
```

Pelo mesmo motivo, uma regra de limpeza e uma de sugestao com o mesmo padrao
deixaram de contar como conflito — elas nunca sao aplicadas ao mesmo texto. O
filtro "Conflitos" e a contagem do rodape passaram a usar a mesma avaliacao da
mensagem, senao a lista acusaria disputas que a janela nao sabe explicar.

**Conferido por mutacao**, nas duas camadas. Na logica pura, quatro maneiras de
errar, cada uma pega pelo teste especifico:

```
vencedor vira o ultimo do arquivo              -> 4 falhas
so contextos disputados entram na mensagem     -> 1 falha (o caso '/\')
duplicata exata volta a contar como disputa    -> 1 falha
"manter esta" remove todo padrao igual         -> 1 falha (leva a regra de limpeza junto)
```

E pelos widgets, com a janela aberta de verdade: nao chamar `refresh_conflict` ao
selecionar uma linha, manter o vencedor em vez da regra selecionada, e nunca
tirar a barra da tela — as tres acusam.

O teste que importa e `test_the_announced_winner_is_the_one_actually_applied`:
ele confere o vencedor anunciado contra o que `apply_all_substitutions` produz no
texto, e nao contra outra copia da regra de ordenacao. Anunciar um vencedor
errado seria pior do que nao anunciar nada.

**Os quatro foram decididos** (2026-07-27), pelo mesmo caminho do botao
"Manter esta". 7065 -> 7061 entradas, com backup em
`backups/Substituicoes-20260727-150630.txt`:

| padrao                 | fica                                 | sai                             |
| ---------------------- | ------------------------------------ | ------------------------------- |
| `brancas para jogar` | #1070 `brancas jogam`              | `brancas de jogar`            |
| `e e f`              | #6115 `'e' e 'f'`                  | `'e' e f`                     |
| `as Pretas`          | #6996 `as pretas`                  | `das pretas`                  |
| `/\`                 | #6103 `com a idéia de` (sugestao) | `Com a ideia de` (automatica) |

Tres das quatro decisoes **inverteram** o que estava valendo. Nao e coincidencia:
a regra que vencia era so a que tinha sido digitada primeiro, e nao ha razao para
a primeira versao de uma regra ser a melhor. Era exatamente a queixa do item —
o criterio existia, mas nao era o criterio de ninguem.

A quarta decisao tem uma consequencia declarada: manter a regra de sugestao
remove a automatica, entao a aplicacao das regras automaticas fica **sem** regra
para `/\`. A substituicao continua sendo oferecida no editor, onde ha revisao
humana.

O teste do glossario real virou `test_the_real_glossary_has_no_undecided_conflict`:
em vez de fixar a lista dos quatro, exige que nao haja nenhum. Conferido
introduzindo um conflito novo no arquivo — ele falha imprimindo qual e o padrao e
qual regra esta vencendo, que e a informacao necessaria para decidir.

**Feito o item 2 (2026-07-27): prioridade explicita.**

**A precondicao declarada nao foi cumprida, e vale registrar.** Este item dizia
"so depois que 1 estiver em uso e ficar claro que nao basta". Nao houve esse
periodo de uso: mostrar o vencedor ficou pronto no mesmo dia, e os quatro
conflitos reais foram todos decididos por "Manter esta". A prioridade foi feita
por decisao de seguir adiante, e nao porque a evidencia chegou. O que se sabe
sobre ela e o que o proprio item argumentava; o que ainda nao se sabe e se, na
pratica, alguem prefere priorizar a apagar.

**O que ela e.** Um inteiro por regra, zero por padrao. `order_rules_by_specificity`
passou a ordenar por `(-prioridade, -comprimento, posicao)`: a prioridade decide
antes do comprimento, e entre prioridades iguais **nada muda** — que e o caso de
todas as 7.061 regras de hoje. Garantia S10.

**A resposta nao destrutiva ao conflito, que e o ganho real.** O item 1 resolveu
a disputa apagando: "Manter esta" remove as concorrentes do arquivo, e o que foi
descartado nao volta. A prioridade resolve a mesma disputa com um numero, e as
duas regras continuam la — a decisao e visivel no glossario e reversivel
priorizando a outra. A barra de conflito ganhou "Priorizar esta" ao lado de
"Manter esta", nessa ordem, que e a ordem em que convem tenta-las.

A prioridade nova e "a maior entre as concorrentes mais um", e nao um valor
fixo: priorizar duas vezes a mesma regra e um no-op, e priorizar a outra depois
inverte a decisao — que e o que "priorizar" promete.

**Tres formatos mudaram, e nenhum quebrou.**

| onde                  | como                 | compatibilidade                |
| --------------------- | -------------------- | ------------------------------ |
| `Substituicoes.txt` | 4o elemento da tupla | so escrito quando != 0         |
| `glossario.db`      | coluna`priority`   | `ALTER TABLE` + reconstrucao |
| CSV                   | coluna`priority`   | opcional na leitura            |

O arquivo so ganha o campo quando ha o que dizer. Nao e economia de bytes: sao
7 mil linhas versionadas, e escrever `, 0` em todas transformaria uma decisao
tomada em quatro regras num diff de 7 mil linhas.

**O `glossario.db` precisou de mais do que um `ALTER TABLE`,** e este e o tipo de
detalhe que passa despercebido ate estragar algo. A coluna nova entra com o
padrao para todas as regras, e o `mtime` do `Substituicoes.txt` **nao mudou** —
entao o cache continuaria valendo e as prioridades do arquivo seriam lidas como
zero. Entrou `GLOSSARY_DB_SCHEMA_VERSION` nos metadados: banco de esquema antigo
e reconstruido a partir do arquivo. Tem teste, montando exatamente esse cenario.

**Duas decisoes de forma, e o motivo de cada uma:**

- **A entrada detalhada virou uma 4-tupla** `(orig, novo, tipo, prioridade)`, e
  nao uma 3-tupla com a prioridade pendurada como atributo. A segunda forma
  custaria zero alteracoes nos testes — e por isso mesmo seria errada: `==`
  ignoraria a prioridade, e qualquer reconstrucao da tupla a perderia **em
  silencio**. Custou 25 assercoes atualizadas, com o helper `com_prioridade`
  onde a prioridade nao e o assunto do teste.
- **A regra continua sendo um par**, e so ganha o terceiro elemento quando
  carrega prioridade. As listas de regras circulam por todo o programa e sao
  comparadas com pares literais em dezenas de lugares; acrescentar um `0` a
  todas mudaria a forma de tudo para representar a ausencia de uma decisao. Os
  tres pontos que faziam `for orig, new in rules` passaram a indexar.

**A prioridade nao entra na identidade da entrada.** `find_glossary_entry_index`
compara `(orig, novo, tipo)`: o editor localiza a linha pelo estado que exibiu
quando ela foi selecionada, e mudar a prioridade e justamente uma das coisas que
"Salvar" faz. Se ela contasse ali, salvar uma prioridade nova nunca acharia a
entrada a atualizar.

**O criterio do vencedor esta em dois lugares, e isso e um risco declarado.**
`glossary_conflicts` decide por conta propria quem vence (os padroes sao
identicos, entao ele compara prioridade e posicao) enquanto quem aplica e
`order_rules_by_specificity`. Se os dois divergirem, a janela anuncia uma regra e
o texto recebe outra — pior do que nao anunciar nada. Por isso
`test_the_announced_winner_follows_the_priority_too` continua conferindo contra
`apply_all_substitutions`, e nao contra outra copia da regra de ordenacao.

**O campo e de texto, e nao um seletor.** A prioridade e um inteiro qualquer no
arquivo, e um `Substituicoes.txt` editado a mao pode trazer um valor fora de
qualquer faixa que a janela oferecesse — um seletor teria de escolher entre
esconder esse valor ou troca-lo. O que nao for inteiro vira aviso de validacao e
**bloqueia** a gravacao: cair para zero em silencio gravaria uma decisao que o
usuario nao tomou.

**Conferido por mutacao**, treze maneiras de errar: a prioridade fora da
ordenacao, a prioridade valendo menos que o comprimento, a chave do cache sem
ela, o conflito voltando a decidir so pela ordem do arquivo, o arquivo deixando
de grava-la, as regras carregadas perdendo-a, o banco de esquema antigo
continuando a valer como cache, promover sem subir acima das concorrentes,
promover apagando-as, a identidade da entrada passando a inclui-la, atualizar sem
opinar zerando-a, o CSV deixando de ler a coluna, e a prioridade invalida virando
zero em silencio.

**Onze foram pegas de primeira, e as duas restantes eram testes meus que nao
testavam nada** — os dois pelo mesmo motivo, que vale registrar porque nao e
obvio: **a mutacao produzia o mesmo arquivo que ja estava la.**

1. *Identidade incluindo a prioridade.* O teste atualizava uma entrada de
   prioridade **zero**, e a linha-base tambem vale zero: comparar a prioridade
   acertava por coincidencia. Refeito sobre uma entrada que ja tem prioridade 3.
2. *Prioridade invalida virando zero.* O teste digitava lixo numa regra de
   prioridade **zero**, entao "gravar zero por engano" reproduzia exatamente o
   arquivo anterior e a falha era invisivel. Refeito partindo de prioridade 5.

A primeira mutacao apontou um caminho de producao que faltava cobrir, e nao so
um teste fraco: depois de "Priorizar esta" a regra fica com prioridade 1 e a
janela precisa reencontra-la **pelo par e pelo tipo** para manter a selecao. Com
a prioridade na comparacao, a busca falha e o formulario e limpo — o usuario
perde de vista a regra sobre a qual acabou de decidir. Entrou
`test_promoting_keeps_the_rule_selected`.

**Verificado na janela de verdade**, que e onde o item se paga: com `'torre'`
disputado por `'rook'` e `'castle'`, selecionar a perdedora mostra "Esta regra
nunca é aplicada"; um clique em "Priorizar esta" troca a mensagem para "vence
esta regra", a linha passa a exibir `P+1`, a regra continua selecionada com o
campo em 1, **as tres regras continuam no arquivo** e o texto passa de
`a rook` para `a castle`. No `Substituicoes.txt`, so a regra promovida ganhou o
quarto campo:

```
substituicoes = [
    ('torre', 'rook'),
    ('dama', 'queen'),
    ('torre', 'castle', 'suggestion', 1),
]
```

---

## 2. Performance

### 2.1 Paginacao anulada por varredura completa — CONCLUIDO (2026-07-25)

`fetch_quality_warning_rows` chamava `fetch_review_rows` sem `LIMIT` a cada
troca de pagina, busca e mudanca de filtro, anulando o `PAGE_SIZE = 100`.

Solucao: coluna materializada `quality_warning`, mantida em toda escrita de
traducao e com indice `(target_language, quality_warning, id)`. O filtro
"Avisos QA" virou o status `warnings`, entao usa o mesmo caminho paginado dos
demais filtros.

Medido em 200 mil linhas:

| operacao                             | antes  | agora            |
| ------------------------------------ | ------ | ---------------- |
| troca de pagina (filtro "todas")     | 559 ms | **47 ms**  |
| troca de pagina (filtro "Avisos QA") | 544 ms | **38 ms**  |
| contagem de avisos                   | 491 ms | **1,3 ms** |

As paginas retornadas sao identicas as de antes, e a contagem em SQL bate
exatamente com a avaliacao em Python (garantias R5/R6).

### 2.2 `initialize_database()` a cada clique — CONCLUIDO (2026-07-25)

Cada chamada executava 2 `CREATE TABLE`, 3 `CREATE INDEX`, um `UPDATE` de tabela
inteira e um `commit`. Agora a migracao so roda quando `PRAGMA user_version`
esta desatualizado; no caminho comum sobra apenas o connect.

**53,2 ms -> 0,2 ms** por chamada. A migracao completa (com backfill da coluna
nova) leva ~3 s uma unica vez, na primeira abertura apos a atualizacao.

### 2.3 Estatisticas do banco carregam tudo na thread da UI — CONCLUIDO (2026-07-25)

O resumo exibido conta apenas linhas COM aviso, entao carregar a tabela inteira
era desperdicio. Passou a buscar so as linhas marcadas.

**542 ms -> 123 ms** em 200 mil linhas, com saida byte a byte identica.

### 2.4 Editor de glossario reconstroi a lista a cada selecao — CONCLUIDO (2026-07-25)

`select_entry` destruia e recriava ate 150 botoes so para mover o destaque.
Passou a usar `update_row_selection`, que troca apenas as cores dos botoes
afetados — o mesmo que o editor de traducoes ja fazia.

Aproveitou-se para corrigir a selecao apos exclusao: `filtered_indices[index]`
usava uma posicao de `entries` como posicao dentro da lista filtrada, o que com
filtro ou ordenacao ativos selecionava uma entrada arbitraria.

### 2.5 Validacao O(n) a cada tecla digitada — CONCLUIDO (2026-07-25)

`validate_glossary_entry` renormalizava as 7 mil entradas a cada caractere.
Como as duas checagens de conflito exigem `orig` igual, indexar por `orig`
(`build_glossary_lookup`) da o mesmo resultado.

**2,11 ms -> 0,00 ms** por tecla; o indice custa 3,56 ms e e montado uma vez,
invalidado quando o glossario recarrega. Comparado com a varredura antiga em
402 amostras: **0 divergencias**.

### 2.6 `analyze_glossary_csv_import` e O(n²) — CONCLUIDO (2026-07-25)

`pair in _normalize_entries(to_insert)` reconstruia a lista de candidatos a cada
linha do CSV e fazia busca linear nela. Trocado por um `set`.

**2445 ms -> 18 ms** para 4.000 linhas (134x), com resultado identico.

### 2.7 "Aplicar automaticas" recomputa tudo tres vezes — CONCLUIDO (2026-07-27)

O item mais caro do programa hoje. Medido no banco real (195.607 traducoes, 57
regras automaticas), sobre uma **copia** do `traducoes.db`:

| etapa                                         | tempo            |
| --------------------------------------------- | ---------------- |
| previa (`analyze_database_automatic_rules`) | 12,4 s           |
| aplicar (`apply_database_automatic_rules`)  | 25,7 s           |
| **total de um clique no botao**         | **38,1 s** |

As tres passagens estao no codigo, nao na medicao:

1. `apply_automatic_rules_to_database` chama `analyze_...` para montar o dialogo
   de confirmacao (quantas mudam, exemplos).
2. Confirmado, chama `apply_database_automatic_rules`, que chama
   `apply_automatic_translation_updates`, cuja **primeira linha e outro
   `analyze_...`** — recalculando exatamente o que acabou de ser mostrado.
3. Se `changed != 0`, ele reexecuta o mesmo `SELECT` e aplica as regras de novo,
   agora para gravar.

A terceira passagem e inevitavel? Nao: `analyze_automatic_translation_updates` ja
calcula `updated_translation` para cada linha e joga fora tudo menos os 10
primeiros exemplos. Se devolvesse os pares `(id, texto_novo)` que encontrou, a
escrita seria um `executemany` sobre eles — uma passagem no lugar de tres.

Duas outras coisas pioram a experiencia mais do que o tempo em si:

- **Nao ha thread.** `app.apply_automatic_rules` chama o fluxo inteiro
  direto no callback do Tk. Sao 38 s de janela branca, sem barra de progresso,
  sem cancelamento e sem sinal de vida — o Windows chega a marcar a janela como
  "nao esta respondendo". A normalizacao de PGN, que e mais recente, ja usa uma
  thread com `progress_callback`; e o molde a seguir.
- **A leitura e um `fetchall`.** 195.607 linhas de texto de uma vez, 80 MB de
  pico so nessa lista, tres vezes. Iterar o cursor custa o mesmo tempo e memoria
  constante.

**Resultado.** A segunda passagem saiu:
`apply_automatic_translation_updates` calcula e grava no mesmo laco, com um
cursor proprio para o `UPDATE` (escrever no cursor que esta iterando o `SELECT`
invalidaria a iteracao). A previa continua existindo — o usuario precisa
confirmar sabendo quantas linhas mudam —, entao sao duas passagens, nao uma.

|                 | antes   | agora                                |
| --------------- | ------- | ------------------------------------ |
| tempo do clique | 38,1 s  | **26,0 s**                     |
| pico de memoria | 80 MB   | **1 MB**                       |
| janela          | travada | responde, com progresso e "Cancelar" |

Criado `tradutor_pgn/background_task.py`, que nao conhece tarefa nenhuma: recebe
uma funcao que roda na thread de trabalho e devolve o resultado por callback na
thread do Tk (garantia C1). Serve para as outras operacoes que ainda travam a
interface — backup, restauracao, importacao de CSV.

Cancelar faz `rollback`: o banco fica como estava, e nao com metade das
traducoes alteradas. Isso esta fixado em teste.

Como a operacao virou assincrona, `apply_automatic_rules_to_database` nao pode
mais devolver o resultado — quem precisa dele (o editor de traducoes, para
recarregar a lista) passa `on_finish`. O callback confere `win.winfo_exists()`
antes de tocar na janela: a operacao dura dezenas de segundos e o editor pode ter
sido fechado nesse meio-tempo.

**Conferido por mutacao.** Reinserindo a chamada de analise dentro da funcao de
escrita, o teste que conta quantas vezes as regras sao aplicadas acusa:

```
AssertionError: 80 != 40 : as regras foram aplicadas mais de uma vez por linha
```

**Uma correcao de medicao.** A primeira analise registrou "48,8 s" para uma
passagem de `analyze`, numero que nunca bateu com os 12,4 s medidos depois. A
diferenca era o `tracemalloc` ligado, que multiplica o tempo por ~4. Os numeros
de tempo desta revisao foram todos medidos sem ele; os de memoria, com ele. Os
dois nao podem sair da mesma execucao.

**O que ainda trava a interface:** backup, restauracao e importacao de CSV. Sao
mais rapidos (o backup do banco de 80 MB leva 0,4 s), mas usam o mesmo callback
sincrono; agora que `background_task` existe, migra-los e mecanico.
**Feito no item 2.11** — e nao era so mecanico: cada uma deixa um lixo diferente
ao ser cancelada, e ligar as tres expos um defeito deste item aqui (o
cancelamento chegava a interface como erro).

### 2.8 Com busca ativa, cada interacao do editor varre a tabela inteira — CONCLUIDO (2026-07-27)

A garantia R5 diz que navegar custa O(tamanho da pagina). **Isso so vale sem
busca.** Com um texto na busca, `reload_rows` dispara tres consultas e nenhuma
delas usa indice, porque `LIKE '%termo%'` com curinga a esquerda nao e
indexavel:

| consulta                     | sem busca | com busca         |
| ---------------------------- | --------- | ----------------- |
| `count_review_rows`        | 9,7 ms    | **~100 ms** |
| `get_review_status_counts` | 35,1 ms   | **~110 ms** |
| `fetch_review_rows_page`   | 8,4 ms    | 1,3 ms a 105 ms   |

O tempo da pagina depende de onde os resultados estao: buscar "bispo" (11.075
ocorrencias) devolve a primeira pagina em 1,3 ms porque o `LIMIT` corta cedo,
mas a ultima pagina custa 105 ms, e um termo sem nenhum resultado custa 98 ms
sempre. Somando, **cada troca de pagina, cada mudanca de filtro e cada nova
busca custam ~200 a 300 ms contra ~50 ms sem busca** — e o custo cresce
linearmente com a tabela, que e justamente o que R5 existia para impedir.

A saida natural e um indice FTS5 sobre `original_comment` e
`translated_comment`, mantido por gatilhos, com a busca por termos passando a
usa-lo (o `LIKE` continua para busca por trecho literal). Isso muda a semantica
da busca — "bisp" deixa de casar "bispo" a menos que se use `bisp*` —, entao a
decisao precisa ser deliberada e nao um efeito colateral da otimizacao.

**Feita a economia de graca.** `get_review_status_counts` e `count_review_rows`
varriam a mesma tabela com o mesmo `WHERE`, e a segunda pedia um numero que a
primeira ja tinha separado por status — para **os quatro** filtros, nao tres:
`all`->`total`, `pending`->`pending`, `verified`->`verified`,
`warnings`->`warnings`. Como `selected_status_filter()` so devolve esses quatro,
a segunda consulta saiu inteira do caminho comum.

Medido no banco real (195.607 linhas), somando as duas consultas por interacao:

| cenario                            | antes    | agora              |
| ---------------------------------- | -------- | ------------------ |
| sem busca, filtro "todas"          | 43,7 ms  | **33,4 ms**  |
| busca`bispo`, filtro "todas"     | 217,3 ms | **109,0 ms** |
| busca sem nenhum resultado         | 264,3 ms | **131,0 ms** |
| busca`bispo`, filtro "Avisos QA" | 121,6 ms | 108,7 ms           |

Com busca ativa o custo cai pela metade — as duas varreduras viraram uma. O
filtro "Avisos QA" quase nao muda porque `quality_warning = 1` ja usa indice: ali
a consulta descartada era a barata.

O reaproveitamento e mais arriscado do que parece, e por isso a correspondencia
ficou em `STATUS_COUNT_KEYS`, num lugar so, em vez de espalhada pelo editor. Os
dois criterios vivem em codigos diferentes (`_review_where` e os `CASE` da
agregada) e podem divergir **sem quebrar nada na tela**: a lista simplesmente
passa a paginar por um numero errado. O teste compara os dois caminhos para os
quatro filtros, com busca que acha, busca que nao acha e sem busca — e um segundo
teste exige que cada filtro tenha linha no dataset, senao o primeiro passaria
comparando zeros.

Conferido por mutacao: mapear `warnings` para o total, trocar pendentes por
verificadas na agregada e devolver `0` em vez de `None` para filtro desconhecido
sao os tres jeitos de errar, e os tres falham.

`count_from_status_counts` devolve `None` — e nao zero — quando o resumo nao
cobre o filtro, e o editor cai no `count_review_rows`. Um zero devolvido por
engano esvaziaria a lista sem erro nenhum.

**Feito o principal: indice FTS5, com o `LIKE` preservado.** A decisao de manter
os dois foi do usuario, e e a certa — o indice muda a semantica, e nenhuma das
duas serve para tudo:

| modo                        | casa                                    | custo     |
| --------------------------- | --------------------------------------- | --------- |
| **Termos** (FTS5)     | palavra inteira;`bisp*` para prefixo  | O(pagina) |
| **Trecho** (`LIKE`) | qualquer pedaco, ate no meio de palavra | O(tabela) |

Um seletor no topo da lista decide qual vale, a escolha e lembrada entre sessoes,
e trocar o modo refaz a busca na hora — deixar o resultado antigo na tela com o
seletor novo faria a lista mentir sobre o que esta mostrando. O padrao e
"Termos", que e o caminho rapido.

Medido no banco real (195.607 linhas), somando o resumo de status e a pagina:

| cenario                    | Trecho   | Termos            |
| -------------------------- | -------- | ----------------- |
| sem busca                  | 33,9 ms  | 33,4 ms           |
| `bispo`, 1a pagina       | 109,4 ms | **39,1 ms** |
| `bispo`, pagina 100      | 205,7 ms | **45,8 ms** |
| termo sem nenhum resultado | 196,5 ms | **18,6 ms** |
| dois termos                | 215,3 ms | **28,0 ms** |

Buscar passou a custar o mesmo que nao buscar, e o custo parou de crescer com a
profundidade da pagina — que era exatamente o que R5 existia para impedir. O
indice custa 1,8 s para ser criado (uma vez, na primeira abertura) e ~25 MB sobre
os 81 MB do banco, porque e `external content`: guarda os termos, nao o texto.

Tres detalhes que os testes protegem, todos com o mesmo tipo de falha — **errado
em silencio**, nunca um erro:

- **A remocao precisa do comando `'delete'` com os valores antigos.** Sem ele os
  termos de uma linha apagada ficam no indice para sempre.
- **O texto digitado nunca vai cru para o `MATCH`.** `AND`, `-`, `*`, `:`, `(` e
  aspas sao operadores: `bispo (branco)` viraria erro de sintaxe no meio da
  navegacao.
- **`remove_diacritics 2`**, senao "traducao" nao acha "tradução".

E a degradacao: sem FTS5 no SQLite, sem o indice no arquivo, ou com uma expressao
que nao sobra termo nenhum, a busca cai no `LIKE` sozinha. Um resultado correto e
lento e melhor que um erro.

**A verificacao por mutacao achou tres testes meus que nao testavam nada.** Todos
passavam com a producao quebrada, e cada um por um motivo diferente:

1. **O gatilho de DELETE.** O teste apagava a linha e conferia que a busca nao a
   devolvia — mas a consulta cruza com `comments`, entao a entrada orfa fica
   invisivel por ali. E o `integrity-check` do proprio FTS5 **nao acusa** este
   caso (verificado). So inspecionando o indice direto da para ver.
2. **A dobra de acentos.** A linha de teste tinha "proximo" sem acento numa
   coluna e "próximo" na outra, entao a busca achava de qualquer jeito. Passou a
   usar uma palavra que so existe acentuada.
3. **O modo chegando as tres consultas.** O termo era `torre`, em que os dois
   modos concordam — ignorar o modo nao mudava nada. Passou a ser `torr`, que por
   termo nao casa e por trecho casa.

Corrigidos, as oito mutacoes sao pegas: os dois gatilhos (DELETE e UPDATE), o
texto cru no `MATCH`, a falta de fallback, o `remove_diacritics`, a migracao que
nao popula o indice, e o modo ignorado em `count_review_rows` e
`get_review_status_counts`.

**Um teste antigo precisou mudar**, e vale registrar por que: `use_qa_filter`
pegava o seletor de filtro como "o primeiro `CTkSegmentedButton` da arvore". Com
o seletor de modo novo, ele passou a mexer no widget errado — e o filtro "Avisos
QA" deixava de ser exercitado, sem que nada acusasse. Agora escolhe pelo
conteudo.

**Garantia R8 (nova):** *navegar custa O(pagina) tambem com busca ativa.*

### 2.9 Operacoes que carregam a tabela inteira na memoria — CONCLUIDO (2026-07-27)

Tres lugares constroem uma lista com o conteudo completo do banco. Medido:

| operacao                                             | tempo  | memoria          |
| ---------------------------------------------------- | ------ | ---------------- |
| `load_translation_cache` (inicio de cada traducao) | 0,75 s | **58 MB**  |
| `fetch_export_rows` (Exportar CSV)                 | 1,0 s  | **102 MB** |
| `analyze_automatic_translation_updates`            | 12,4 s | **80 MB**  |

Nenhuma e um defeito hoje — o computador aguenta —, mas as tres crescem com o
banco e duas nao precisam da lista:

- **Exportar CSV** so escreve linha a linha. `csv.writerows(cursor)` aceita o
  proprio cursor: memoria constante e o arquivo comeca a sair na hora.
- **Regras automaticas**: ver 2.7.
- **Cache de traducao** e o caso legitimo: e um dicionario de consulta usado o
  tempo todo pelo worker. Vale registrar o custo (58 MB por idioma, hoje) e o
  ponto de virada: se o banco dobrar, cabe carregar so os comentarios dos
  arquivos que vao ser processados, que e um `SELECT ... WHERE original_comment IN (...)` sobre uma lista que o worker ja tem em maos.

**Feito:** as regras automaticas (junto com 2.7, 80 MB -> 1 MB) e a exportacao de
CSV. `fetch_export_rows` devolve o cursor em vez de `fetchall`, e o
`csv.writerows` consome direto:

|                                      | antes                   | agora                  |
| ------------------------------------ | ----------------------- | ---------------------- |
| exportar CSV (195.607 linhas, 41 MB) | 1,7 s /**102 MB** | 1,1 s /**~0 MB** |

**Feito tambem o cache de traducao.** A previsao era esperar o banco dobrar; nao
foi preciso, porque a mudanca e menor do que parecia: o worker ja extraia todos
os comentarios para `info_by_file` **antes** de usar o cache. Bastou mover a carga
para depois da extracao e passar a lista que ele ja tinha em maos.

| cenario                      | antes          | agora                     |
| ---------------------------- | -------------- | ------------------------- |
| pasta com 200 comentarios    | 306 ms / 74 MB | **4 ms / 0,1 MB**   |
| pasta com 2.000              | 306 ms / 74 MB | **40 ms / 0,6 MB**  |
| 20.000 (10% da tabela)       | 306 ms / 74 MB | **304 ms / 5,7 MB** |
| a tabela inteira (pior caso) | 306 ms / 74 MB | 333 ms / 75 MB            |

**O limite de 50% saiu de uma medicao, e a primeira que fiz respondia a pergunta
errada.** Procurar comentario a comentario e mais barato ate certo ponto; passado
ele, ler tudo de uma vez ganha. Medi onde as duas se cruzam em TEMPO (~10% da
tabela) e usei isso como limite — mas o item e sobre MEMORIA, e a 10% eu estava
voltando a gastar 74 MB para poupar 74 ms. Refeita a medicao sobre a troca real:

```
fracao pedida   tempo extra   memoria poupada   MB por 100 ms
     10%           -34 ms          68 MB          (de graca)
     25%           443 ms          59 MB             13,3
     50%          1208 ms          44 MB              3,7
     75%          1872 ms          32 MB              1,7
```

A troca piora sem parar: quanto maior a fatia, menos memoria se poupa e mais
tempo se paga. Em 50% ainda se trocam 44 MB por 1,2 s, o que e barato numa
operacao que depois passa minutos na rede. Dali para cima, nao.

Duas consequencias que precisaram de cuidado:

- **A carga completa devolve um superconjunto.** O contrato passou a ser "contem
  os pedidos que existem", e nao "contem so os pedidos". Isso invalidou o log que
  eu tinha acabado de escrever (`len(cache)` diria "195.603 reaproveitaveis" para
  uma pasta de 40 comentarios), entao a contagem passou a ser feita sobre a
  propria lista.
- **Os lotes.** O `IN` esbarra no limite de parametros do SQLite — 32.766 nas
  versoes novas, 999 nas antigas. `CACHE_LOOKUP_CHUNK = 900` cabe nas duas.

**A verificacao por mutacao encontrou tres testes ausentes e um defeito na
suite.** As tres ausencias: nada exigia os lotes (2.707 numa consulta so passa no
SQLite moderno — corrigido contando as consultas), nada provava que a carga
completa era usada acima do limite (agora se exige que ela traga o que **nao** foi
pedido), e nada verificava que o worker carrega so o necessario (agora se olha o
conteudo do `translation_cache`, e nao a saida da traducao).

O defeito na suite era pior: quebrado o cache, o teste "sem chamada de API"
levantava `AssertionError`, o `except Exception` de `run_translation` chamava
`messagebox.showerror` — **que nenhum teste silenciava** — e a suite **travava em
vez de falhar**, porque o `FakeRoot.after` executa o callback na hora. Um teste
que trava esconde a falha por completo. `TranslationWorkerTests` passou a
silenciar o `messagebox` inteiro no `setUp`; a mesma mutacao agora falha em menos
de um segundo, apontando o teste certo.

### 2.10 Reordenacao e releitura repetidas — CONCLUIDO (2026-07-27)

Tres desperdicios pequenos, todos com correcao de uma linha, listados porque
aparecem em caminhos quentes:

- **`order_rules_by_specificity` reordena a cada chamada.** As regras nao mudam
  entre chamadas. Em `apply_all_substitutions` sao 0,017 ms para 57 regras — que
  viram **10,2 s** ao longo das tres passagens de 2.7. Em
  `find_glossary_suggestions` sao 3,3 ms das 12,5 ms que cada linha do editor
  custa para montar as sugestoes (7.008 regras). A ordem so depende da lista;
  cabe calcular na carga do glossario, junto com `build_glossary_lookup`.
- **`highlight_glossary_hits` le o texto inteiro do widget dentro do laco.**
  `text = trans_text.get("1.0", tk.END)` esta *dentro* do `for` das sugestoes:
  ate 80 travessias Tk->Python do mesmo texto, para pintar a mesma coisa. Basta
  subir a linha.
- **`import_translations_from_csv` le o CSV duas vezes**, uma na previa e outra
  na aplicacao, sem reaproveitar. Igual ao caso 2.7, em menor escala.

**Feito** os dois primeiros:

|                                              | antes     | agora               |
| -------------------------------------------- | --------- | ------------------- |
| `order_rules_by_specificity` (57 regras)   | 0,0174 ms | **0,0072 ms** |
| `find_glossary_suggestions` (7.008 regras) | 12,5 ms   | **10,7 ms**   |

A ordenacao passou a ser memorizada por **conteudo** das regras — a lista nao e
hashavel e o `id()` dela nao serve (uma lista nova pode reaproveitar o endereco
de uma coletada), entao a chave e a tupla dos pares.

> A chave por conteudo saiu em 2026-07-30: montar uma tupla de 7.334 elementos e
> hashea-la era 1,75 ms dos 9,15 ms de cada tecla. A lista carregada passou a
> trazer um numero de versao, e a chave e ele (garantia D7, ROADMAP 20.6). O
> `test_ordering_cache_never_changes_the_result` continua sendo o forcante: os
> quatro jeitos de errar sao os mesmos, e o quarto — mutacao que precisa mudar a
> ordem — e o que exige renovar a versao a cada mutacao da lista.

Um cache aqui e delicado: S3 depende inteiramente desta ordem, e um cache que
devolva a lista errada quebra a garantia sem quebrar nada visivel — as regras
continuam sendo aplicadas, so que na ordem errada. O teste
`test_ordering_cache_never_changes_the_result` cobre os quatro jeitos de errar:
listas diferentes recebendo o resultado uma da outra, mutacao do valor devolvido
contaminando o cache, listas com o mesmo conteudo mas objetos diferentes, e
mudanca de conteudo que precisa mudar a ordem. Por isso a funcao devolve sempre
uma lista nova.

Escrevendo esse teste eu errei a expectativa uma vez: afirmei que
`"torre muito comprida demais"` assumiria o primeiro lugar, mas ela tem 27
caracteres contra os 28 de `"da verificacao intermediaria"`. O codigo estava
certo e o teste, errado — corrigido no teste, que agora afirma explicitamente
que o padrao novo e mais longo antes de exigir o primeiro lugar.

**Feito tambem o terceiro** (2026-07-27), e ele nao era so economia. A previa e a
aplicacao liam o arquivo separadamente, entao o usuario confirmava numeros
calculados sobre um arquivo e a gravacao acontecia sobre outro, se ele mudasse no
intervalo. Agora as linhas sao lidas uma vez e passadas adiante
(`csv_rows` em `analyze_translations_csv_import`/`import_translations_from_csv`).

O mesmo padrao existia no glossario e nao estava anotado aqui:
`import_glossary_csv` rechamava `analyze_glossary_csv_import`, relendo o CSV
depois da confirmacao. Ganhou `analysis=`, pela mesma razao.

Os testes trocam o CSV **entre** a previa e a aplicacao e exigem que o gravado
seja o que foi confirmado; um terceiro conta as leituras no fluxo real da
interface. Conferido por mutacao nas quatro formas de regredir.

### 2.11 Backup, restauracao e CSV ainda travavam a interface — CONCLUIDO (2026-07-27)

O `background_task.py` foi criado em 2.7 exatamente para isto, e ficou dois dias
servindo so a aplicacao de regras automaticas. O proprio 2.7 fechou dizendo que
migrar as outras "e mecanico", e a SPEC listava a pendencia em "Limites
conhecidos". As quatro continuavam rodando dentro do callback do botao:
`backup_database`, `restore_database`, `import_csv` e `export_csv`.

**O tempo nunca foi o argumento principal**, e vale ser preciso porque ele e
pequeno. Medido no banco real (195.607 traducoes, 81 MB), sobre uma copia:

| operacao             | antes   | agora   | atualizacoes de progresso |
| -------------------- | ------- | ------- | ------------------------- |
| backup do banco      | 396 ms  | 397 ms  | 13                        |
| exportar CSV (41 MB) | 1079 ms | 1062 ms | 41                        |

O ganho e o outro: durante esse tempo a janela ficava parada, sem dizer o que
estava acontecendo e sem forma de desistir — e a importacao de um CSV grande nao
tem teto nenhum. Os arquivos gerados sao **identicos** aos de antes (conferido
byte a byte pelo tamanho e pelo conteudo em teste).

**A copia do SQLite passou a ser em blocos.** `Connection.backup(..., pages=, progress=)` existe justamente para isso: sem `pages` a copia e uma chamada so
que retorna no fim, sem lugar para reportar nem para desistir. `BACKUP_PAGES_PER_STEP = 2048` (~8 MB) da 13 atualizacoes num banco de 81 MB e custa 1 ms no total.

**A exportacao continua entregando blocos inteiros ao `csv.writerows`.** Trocar
por um laco Python linha a linha — que seria o jeito obvio de ter onde checar o
cancelamento — devolveria o custo que o item 2.9 tirou. O bloco e o lugar de
checar. O preco medido disso e 5,7 MB de pico contra ~0,3 MB do `writerows`
direto: e um bloco de 5.000 linhas residente, constante, e nao a tabela inteira
que 2.9 removeu (102 MB).

**Desistir nao pode deixar lixo, e cada operacao deixa um lixo diferente:**

- **Backup cancelado** apaga a copia parcial. Um `.db` cortado no meio e um banco
  incompleto com cara de backup — o proximo "Restaurar backup" o ofereceria na
  lista como qualquer outro.
- **Exportacao cancelada** apaga o CSV parcial. Ele abre, tem cabecalho e linhas
  validas: nada nele denuncia que esta pela metade.
- **Importacao cancelada** faz `rollback` (o mesmo que 2.7 ja fazia). O backup
  criado antes da importacao **permanece** — e uma copia valida, e apaga-lo seria
  destruir o unico registro de que a operacao chegou a comecar.
- **Restauracao nao oferece cancelamento** (`allow_cancel=False`). Aqui nao ha o
  recurso dos outros tres: o destino da copia e o banco de trabalho, e
  interrompe-la no meio o deixaria incompleto. Oferecer o botao e ignora-lo seria
  pior do que nao oferecer — o usuario clicaria achando que parou. A confirmacao
  passou a dizer isso antes de comecar.

**Um defeito do proprio 2.7 apareceu ao ligar as outras tres.** `database.py`
sinaliza desistencia com `AutomaticRulesCanceled` e nao pode conhecer o
`background_task` — aquele modulo importa Tk, e e essa separacao que permite
testar o banco sem display. So que ninguem traduzia uma coisa na outra: a excecao
chegava ao `run_with_progress` como uma falha qualquer, e **quem clicava em
"Cancelar" durante "Aplicar automaticas" recebia um dialogo de ERRO** dizendo que
a operacao falhou, em vez da confirmacao de que nada foi alterado. Corrigido com
`_cancelable`, uma linha em cada um dos dois pontos de entrada.

**Conferido por mutacao**, sete maneiras de desfazer o item, cada uma pega pelo
teste correspondente: a copia voltando a ser uma chamada so, o CSV pela metade
ficando em disco, o backup pela metade ficando em disco, a restauracao voltando a
oferecer "Cancelar", o cancelamento das regras automaticas voltando a virar erro,
a importacao parando de olhar o cancelamento, e a exportacao voltando para dentro
do callback do Tk.

O teste que segura o item inteiro e
`test_the_four_operations_go_through_the_worker_thread`: devolver qualquer uma
delas para o callback do Tk nao quebra nada visivel — ela continua funcionando, so
que travando a janela —, entao a exigencia precisa ser explicita.

**Verificado tambem na janela de verdade**, que e o unico lugar onde a barra
existe: exportar o banco real mostra "115.000 de 195.607" com barra determinada e
o botao "Cancelar"; clicar nele produz "Operacao cancelada." e **nenhum CSV em
disco**.

**Uma ressalva medida, e nao suposta.** Em operacoes limitadas por CPU a barra
demora a sair do lugar: a thread de trabalho segura o GIL entre dois relatos, e a
atualizacao so aparece quando a thread da interface e escalonada. Amostrando a
barra a cada 80 ms durante a exportacao, ela ficou indeterminada por ~1,8 s e
depois subiu de 0 a 0,92 normalmente. O laco de eventos rodou o tempo todo (35
voltas em 3 s), entao a janela responde e o "Cancelar" funciona desde o primeiro
instante; o que atrasa e o numero. Isso vale igualmente para o 2.7, que ja estava
assim. Ficou registrado em "Limites conhecidos".

---

## 3. Estrutura

### 3.1 `edit_window.py`: funcao gigante — CONCLUIDO (2026-07-27)

> Este item foi escrito so para o `edit_window.py`. O mesmo problema existia no
> editor de glossario e nao estava registrado em lugar nenhum — virou o item
> 3.5, feito pela receita que este deixou pronta.

`open_translation_editor` concentra dezenas de funcoes aninhadas num so escopo,
com todo o estado em dicts-celula (`{"value": ...}`) para contornar o escopo de
closure. E o principal debito tecnico do projeto: qualquer alteracao exige ler o
arquivo inteiro para entender o que esta no escopo.

Estrategia adotada: extrair primeiro a logica pura para modulos testaveis
(feito em 3.2, que criou a rede de testes que nao existia), e so depois
converter o restante em classe. Sem essa ordem a conversao seria feita sem
nenhuma protecao — `open_translation_editor` nao tinha um unico teste.

**Rede de protecao — FEITA.** `tests/test_editor_windows.py` abre a janela de
verdade e exercita clique em linha, navegacao, "Marcar como verificada" e o
filtro "Avisos QA". Alem disso, `click_every_button` aciona **45 botoes** do
editor de traducoes (incluindo a subjanela de historico) e **20** do editor de
glossario, exigindo que nenhum levante excecao. E cobertura de crash barata
sobre as 86 funcoes aninhadas: nao afirma o que cada botao faz, mas uma
variavel esquecida no meio da conversao aparece ali.

**Etapa 1 — estado em atributos: FEITA (2026-07-25).** Criada a classe
`EditorState`. As onze celulas `{"value": ...}` espalhadas pela construcao da
interface viraram atributos declarados num lugar so, e `rows` foi junto — era o
ultimo nome que ainda exigia `nonlocal`.

O dict-celula nao era mania: uma atribuicao dentro de funcao aninhada cria uma
variavel local em vez de alterar a de fora, e mutar um dict contornava isso.
Um objeto com atributos resolve o mesmo problema sem o ruido do indice.

Sobrou uma celula, de proposito: `selected_history` pertence ao escopo da
subjanela de historico, nao ao estado do editor.

**Etapa 2 — FEITA (2026-07-27).** `open_translation_editor` virou a classe
`TranslationEditor`: 86 funcoes aninhadas viraram metodos e 186 nomes viraram
atributos, em 1.145 referencias reescritas.

**Feita por script, e essa foi a decisao que importou.** Transcrever 2.400 linhas
a mao erra em algum lugar, e o erro tipico — um nome que ficou para tras — e um
`NameError` num caminho pouco usado, que sob `pythonw` some sem deixar rastro. O
script usa `tokenize`, e nao regex sobre o texto: so assim um nome dentro de
string ou comentario nao e reescrito por engano. Tres guardas evitaram os erros
que uma substituicao ingenua cometeria:

- `obj.nome` nao e o nosso `nome` (o token anterior e um ponto);
- `f(nome=...)` e argumento nomeado, nao referencia — `configure(state="normal")`
  aparece dezenas de vezes e viraria `configure(self.state="normal")`;
- uma atribuicao a um nome do conjunto **dentro** de um metodo e uma variavel
  local sendo promovida a atributo por engano. O script para com erro, exceto
  nos tres casos que eram `nonlocal` e queriam mesmo escrever no estado.

Essa ultima guarda pegou o unico conflito real: `set_restore_buttons` tinha um
local chamado `state`, que viraria `self.state` e destruiria o estado da janela
sem erro nenhum. Renomeado antes da conversao.

**Conferido de tres formas independentes**, porque "os testes passam" nao basta
para uma mudanca desse tamanho:

1. **`symtable`** — a analise de escopo do proprio compilador — confirma que
   nenhum nome ficou livre. Um `NameError` latente nao passa por ali.
2. **Diff linha a linha contra o original**, normalizando `self.` e a
   indentacao: das 1.978 linhas de codigo, **nenhuma linha de corpo mudou**. As
   unicas diferencas sao o andaime (a classe, as docstrings, os sete metodos de
   construcao) e os tres `nonlocal` que sairam.
3. **Cobertura por metodo.** Instrumentando a classe, `click_every_button`
   alcancava 71 dos 94 metodos. Os 23 restantes — atalhos de teclado, busca no
   texto, sugestoes, auxiliares puros — eram exatamente onde um `NameError`
   sobreviveria, entao ganharam testes. Hoje sao **94 de 94**.

O `__init__` tem 9 linhas e chama sete etapas nomeadas (`build_state`,
`build_list_pane`, `build_editor_pane`, `build_suggestion_pane`,
`build_status_bar`, `connect_events`, `load_first_page`). Trocar uma funcao de
2.200 linhas por um `__init__` de 500 nao teria resolvido nada.

`EditorState` continua existindo, e de proposito: separa o estado que muda em
tempo de execucao (`self.state.dirty`) da arvore de widgets
(`self.dirty_label`). Sao coisas diferentes e ler `self.state.X` diz qual e qual.

**Dois achados dos testes novos**, ambos do tipo "passa sem testar nada":

- `event_generate("<Control-f>")` **nao e entregue** sem um widget com foco,
  enquanto `<Control-s>` e. Sem o `focus_set`, o teste de atalhos passaria
  exercitando metade dos atalhos.
- `tk_popup` e modal: chamado de verdade, ele espera alguem clicar, e a suite
  ficava 40 s parada nele. Substituido so ele, o metodo continua sendo
  exercitado inteiro.

**Conferido por mutacao**, simulando conversoes incompletas: `self.` esquecido em
`text_index_for_offset`, `select_find_match`, `history_action_label`, `go_to_id`
e `on_glossary_editor_change`. As cinco falham, cada uma no teste que a cobre.

**A subjanela de historico tambem saiu (2026-07-27).** `open_history_window`
tinha 245 linhas e seis funcoes aninhadas proprias; virou a classe
`HistoryWindow`, em `tradutor_pgn/history_window.py`. O metodo que restou tem
seis linhas e existe so para fixar o item antes de abrir a janela.

`history_action_label` e `history_status_label` foram junto, como funcoes de
modulo: so a subjanela as usava, e ficavam no editor por acidente de escopo. A
listagem do historico passou a usar o mesmo `render_row_buttons` dos outros dois.

**Isso rendeu o teste que faltava para a garantia R3.** Ela estava na tabela de
invariantes da SPEC **sem teste proprio** desde o inicio — a janela e modeless, e
o defeito so aparece quando o usuario clica em outra linha com ela aberta.
Enquanto tudo era closure, montar esse cenario exigia alcancar variaveis presas
no escopo; com a classe, o teste abre o historico do item A, seleciona o item B na
lista principal e restaura. Conferido por mutacao: fazendo a janela reler o item
do editor em vez de usar o que declarou, ele acusa.

**As oito mutacoes desta rodada sao pegas**, cada uma pelo teste correspondente:
o snapshot inteiro gravado por cima (R4), a secao corrompida mesclada, a falha de
disco propagando, o divisor sem teto, o divisor sem piso, a lista nao limpando os
botoes antigos, o historico relendo o item (R3) e a acao desconhecida virando
rotulo generico.

### 3.2 Duplicacao entre os dois editores — CONCLUIDO (2026-07-27)

Criado `tradutor_pgn/editor_common.py`, que nao importa Tk nem recebe widget:
tudo nele e funcao pura e testavel sem abrir janela. Ja migrados:

- `clamp_geometry` (as duas copias de `safe_geometry` diferiam so no tamanho
  minimo; agora sao dois wrappers de uma linha sobre a mesma logica)
- `preview` (diferia so no limite padrao)
- constantes de cor das linhas
- `page_count`, `clamp_page`, `page_offset`, `page_of_offset` e
  `local_index_for_offset`, que substituiram a aritmetica `// PAGE_SIZE` e
  `% PAGE_SIZE` espalhada por 10 pontos dos dois arquivos

`local_index_for_offset` embute o clamp que faltava: converter um deslocamento
absoluto em posicao dentro da pagina agora respeita o tamanho real da pagina
recebida, eliminando a familia de `IndexError` que aparecia quando a lista
encolhia entre o calculo e a leitura.

Depois entrou tambem `row_index_for_id`, que reencontra uma linha pelo id apos a
lista ser recarregada — a peca que faltava para fechar o 3.3.

**Feito o resto (2026-07-27).** Os quatro que faltavam dependiam de widgets, e
por isso nao cabiam em `editor_common.py` — aquele modulo nao importa Tk, e e
essa restricao que o mantem testavel sem abrir janela. Criado
`tradutor_pgn/editor_widgets.py` para as pecas que precisam mesmo de um widget:

| era                               | virou                                                       |
| --------------------------------- | ----------------------------------------------------------- |
| `show_message` (x2)             | `flash_message`                                           |
| `save_editor_settings` (x2)     | `save_window_section`                                     |
| `restore_pane_position(s)` (x2) | `restore_sash` + `collect_sash_positions`               |
| `render_rows` (x2)              | `render_row_buttons` + um `build_row_button` por editor |

**`save_window_section` era a copia perigosa**, e vale dizer por que. Ela
implementa a garantia R4: gravar **so** a secao desta janela, relendo o disco
imediatamente antes. Com duas copias, corrigir uma e esquecer a outra reproduz
exatamente o defeito que R4 existe para impedir — e nao quebra nada na hora; o
usuario e que perde um rascunho depois. Agora ha um lugar so, e ele tem teste
proprio: escreve so a sua secao, rele o disco antes de gravar, troca (nao mescla)
uma secao corrompida, mantem o snapshot local coerente e nao propaga falha de
disco.

`render_row_buttons` ficou com a moldura (limpar os filhos, tratar lista vazia,
empacotar) e devolveu a cada editor o que neles e realmente diferente: o rotulo,
as cores e o comando de cada botao. Forcar mais que isso para dentro do modulo
comum daria uma funcao com mais parametros do que corpo.

Duas coisas saltaram durante a migracao e foram junto:

- **`format_timestamp`** era um metodo do editor de traducoes e e puro. Foi para
  `editor_common.py`.
- **O limite do divisor** (`max(360, min(520, x))`) estava dentro da funcao que
  fala com o Tk, entao so dava para testa-lo abrindo janela — e o teste ficava
  fragil, porque o Tk limita o divisor ao tamanho real do painel e a coordenada
  final depende da tela. Virou `clamped_sash_position`, pura, em
  `editor_common.py`; ao `restore_sash` sobrou colocar o divisor onde ela mandar.
  A decisao passou a ser testavel sem display, e o teste de widget so afirma o
  que e do Tk.

### 3.3 Reentrancia em `select_index` — CONCLUIDO (2026-07-25)

O `IndexError` latente em `go_to_next_quality_warning` ja tinha sido corrigido
com clamp. A raiz era `save_changes` chamar `reload_rows()` + `select_index()`
no meio de um `select_index` externo, que entao aplicava o indice do clique a
uma lista ja trocada.

Reproduzido clicando nos widgets de verdade, com o filtro "Avisos QA" ativo e
tres linhas com aviso: corrigir a linha A e clicar em B **carregava C**. A
gravacao tira A da lista, B sobe para a posicao 0, e a posicao 1 — que o clique
carregava — passa a ser C.

A correcao troca a posicao pelo id: `select_index` guarda o id da linha alvo
antes de gravar e o reencontra depois, com `row_index_for_id` (novo em
`editor_common.py`, funcao pura). Se a linha saiu da lista, o `fallback`
limitado aponta para quem ocupou o lugar dela.

`mark_and_next` ("Marcar como verificada") tinha a mesma raiz e nao estava
registrada aqui: calculava `posicao + 1` sobre uma lista que a gravacao ja tinha
encolhido. No mesmo cenario, **pulava a traducao seguinte** — verificar A saltava
direto para C. Agora, quando a linha atual sai da lista, quem ocupou o lugar
dela ja e a proxima.

Os dois casos foram verificados nos dois sentidos: com a correcao desligada o
comportamento errado reaparece exatamente como descrito.

Aproveitou-se para trocar por `row_index_for_id` os dois lacos manuais de
"procurar a linha pelo id" que existiam em `save_changes` e em
`apply_automatic_rules_for_current_language`.

### 3.4 Indice posicional do editor de glossario — CONCLUIDO (2026-07-25)

`selected["index"]` era uma posicao no arquivo capturada no carregamento, e a
janela nao e notificada de alteracoes externas. Editar pelo outro editor com
esta janela aberta fazia "Salvar" gravar na entrada vizinha.

A correcao de 1.1/S6 tinha criado `delete_glossary_entry_by_pair`, mas ela so
havia sido ligada no `edit_window.py`. **O proprio editor de glossario continuava
excluindo por posicao** — o mesmo bug, no lugar mais obvio para ele acontecer.
Agora as tres operacoes vao pelo conteudo:

- `find_glossary_entry_index` localiza a entrada pelo estado que o editor
  exibiu. A posicao guardada virou apenas um palpite (`index_hint`): se ela
  ainda contiver a entrada esperada, e ela que vale — assim, havendo duplicatas
  exatas, a operacao atinge a que estava na tela e nao a primeira do arquivo.
- `update_glossary_entry_by_entry` grava por essa localizacao, e devolve `None`
  se a entrada nao existir mais. Nesse caso nada e escrito: a janela recarrega e
  avisa. Antes, gravava por cima da vizinha em silencio.
- `delete_glossary_entry_by_pair` ganhou `rule_type` e `index_hint`, para quem
  conhece a entrada inteira. Sem eles o comportamento antigo continua valendo.

Dois erros menores caíram junto: `save_as_new` usava `len(entries) - 1` para
localizar o que acabou de gravar, o que so acertava quando a insercao de fato
acontecia (com "Entrada ja existia" selecionava a ultima linha, errada); e a
selecao da vizinha apos excluir usava a posicao da tela em vez da posicao real
da entrada removida.

Verificado ponta a ponta clicando nos widgets de verdade: com uma entrada
inserida por fora no inicio do arquivo, salvar e excluir atingem a entrada certa
e a vizinha sobrevive; com a entrada removida por fora, nada e gravado e o aviso
aparece. A contraprova com a funcao posicional antiga, no mesmo cenario,
destroi a vizinha — e esta fixada em teste.

### 3.5 O editor de glossario nunca recebeu o tratamento do 3.1 — CONCLUIDO (2026-07-27)

O item 3.1 foi escrito so para o `edit_window.py`, entao isto nao estava
registrado em lugar nenhum: `open_glossary_editor` tinha **985 linhas e 49
funcoes aninhadas**, e o modulo nao tinha uma classe. E exatamente o problema que
3.1 descreve, no outro editor — inclusive o estado em dicts-celula.

**A assimetria aparecia de fora, e foi por fora que ela apareceu.** Escrevendo a
skill de execucao ficou registrado como armadilha que o editor de traducoes
devolve a instancia e o de glossario devolve `None`, obrigando quem dirige a
janela a andar na arvore de widgets. A assimetria estava descrita; que ela era
divida, nao.

**Feito pela receita que a outra conversao deixou pronta**, e ela se pagou: o
script veio de la, e as tres verificacoes tambem.

**Nem todo local do escopo externo virou atributo — e essa foi a diferenca.**
Em 3.1 a promocao foi indiscriminada. Aqui o script classifica: um nome lido por
alguma funcao aninhada nao tem escolha (perderia o acesso), e o resto so vira
atributo se cruzar mais de uma etapa de construcao. `self.pane_bg` seria ruido.
Deu **95 atributos** — 49 metodos e 46 nomes de estado e widget — e **24 nomes
que continuam locais** do trecho onde nascem.

**Contar ocorrencias por posicao no texto nao funciona**, e isto custou uma
rodada. A primeira versao do script acusou dez conflitos de nome, entre eles
`rule_type` — que aparece na compreensao de `type_menu` e tambem como variavel
em seis metodos. Desde a **PEP 709**, que embutiu as compreensoes no escopo de
fora, aquele `rule_type` e um local da funcao externa, e um scanner de tokens nao
distingue um do outro. Quem responde isso e o escopo: `symtable` para os nomes
lidos por closure, e uma passagem de AST que percorre o corpo **sem entrar** nas
funcoes aninhadas para o resto.

As tres guardas do 3.1 continuam valendo (`obj.nome`, `f(nome=...)`, atribuicao
local a um nome promovido). Desta vez a terceira nao achou nenhum conflito real
— o `state` do outro editor nao tem equivalente aqui.

**Conferido das mesmas tres formas:**

1. **`symtable`** — nenhum metodo tem nome livre, e todo global que eles usam
   existe no modulo. Um `NameError` latente nao passa por ali.
2. **Diff linha a linha contra o original**, normalizando `self.` e a
   indentacao: das **874 linhas de codigo, nenhuma linha de corpo mudou**. As
   unicas diferencas sao o andaime (a classe, o `__init__`, as seis etapas de
   construcao) e os dois `nonlocal` que sairam. O diff e feito **regiao a
   regiao**: as etapas de construcao saem na ordem em que o `__init__` as chama,
   que nao e a ordem em que estavam no corpo, e um diff plano acusaria 72 linhas
   mudadas onde nao mudou nenhuma.
3. **Cobertura por metodo.** Instrumentando a classe, os testes existentes
   alcancavam **51 dos 56** metodos. Os cinco restantes — paginacao, fechamento,
   confirmacao de descarte, entrada pre-preenchida e a localizacao do que acabou
   de ser gravado — ganharam testes. Hoje sao **56 de 56**.

O `__init__` tem 8 linhas e chama seis etapas nomeadas (`build_state`,
`build_list_pane`, `build_detail_pane`, `build_footer`, `connect_events`,
`load_first_entry`).

**A etapa 1 foi junto, porque numa classe ela e subtracao.** As cinco celulas
(`dirty["value"]`, `selected["index"]`, `page_index["value"]`,
`validation_lookup["value"]`, e mais o `loading`) viraram `GlossaryEditorState`,
espelho do `EditorState`: 125 referencias reescritas. O dict-celula existia
porque atribuir dentro de funcao aninhada cria variavel local em vez de alterar a
de fora; com metodos, `self.x = ...` ja faz isso. `form_baseline` ficou como
dict, que e um registro de tres campos e nao uma celula — o mesmo tratamento que
`self.current` tem no outro editor.

Um efeito colateral util: os dois `lambda` com `page_index.update({"value": 0})`
embutido — a unica forma de atribuir dentro de uma expressao — viraram o metodo
`restart_at_first_page`, como o `toggle_filter` de la.

**A cobertura por metodo encontrou um defeito de verdade**, e do tipo que so
aparece quando alguem escreve o teste. `locate_saved_entry` afirma na propria
docstring que `find_glossary_entry_index` "normaliza os dois lados antes de
comparar" — e nao normalizava. A gravacao tira os espacos das pontas (garantia
S7), entao salvar `"  bishop  "` gravava `"bishop"` e a busca pelo texto digitado
**nao achava nada**: a entrada recem gravada ficava sem selecao, sem erro nenhum.
Corrigido em `find_glossary_entry_index`, que passou a normalizar os dois lados —
para as entradas ja em disco e um no-op, porque elas ja estao normalizadas.

**Conferido por mutacao**, simulando conversoes incompletas — um `self.` que
ficou para tras em cada um dos cinco metodos que ninguem exercitava:
`change_page`, `restart_at_first_page`, `locate_saved_entry`,
`start_prefilled_entry` e `close_editor`. As cinco falham, cada uma no teste que
a cobre. A correcao da normalizacao tambem: desligando-a, falham exatamente os
dois testes novos que a cobrem, e mais nenhum.

**A skill foi atualizada junto.** `open_glossary_editor` devolve a instancia, o
driver devolve `GlossaryEditor` em vez do `Toplevel`, e a secao "e diferente, e
mais dificil" saiu. Os helpers de arvore ficaram, com o motivo dito: eles servem
para conferir o que esta na **tela**, e nao para alcancar um metodo — um metodo
diz o que o programa acha, um widget diz o que o usuario ve.

### 3.6 O vencedor do conflito era decidido em dois lugares — CONCLUIDO (2026-07-27)

Ultimo item da secao 9 da SPEC que descrevia um defeito latente em vez de uma
escolha. Quem vence uma disputa de glossario era calculado duas vezes:
`order_rules_by_specificity` ordenava por `(-prioridade, -comprimento, posicao)`
para **aplicar**, e `glossary_conflicts` tinha a sua propria linha,
`min(members, key=(-prioridade, indice))`, para **anunciar**. Divergir ali nao da
erro: a janela aponta uma regra e o texto recebe outra, e a mensagem errada e
crivel porque tem a mesma cara da certa.

**O item nao corrige comportamento nenhum, e isso precisa ficar dito.** As duas
copias concordam hoje, e concordam por um motivo real: `glossary_conflicts`
agrupa por `orig` exato, entao os padroes de um grupo sao identicos, o termo do
comprimento empata sempre e as duas expressoes se reduzem a mesma. Conferido em
19.667 grupos gerados com prioridades, tipos e tamanhos sorteados — **zero
divergencias**. O que muda e que a coincidencia deixou de depender desse
argumento.

**A correcao.** `_rule_sort_key` passou a ser o criterio, uma vez so, e
`_specificity_order` devolve as posicoes na ordem da disputa. `glossary_conflicts`
nao imita mais a aplicacao: converte as entradas com `_as_rule` — a mesma
conversao que `filter_glossary_entries_by_type` faz ao carregar — e pergunta a
`_specificity_order` quem vem primeiro. Os dois passos passaram a ser os da
producao, e nao imitacoes deles.

Devolver **posicoes**, e nao as regras ordenadas, e o que torna isso possivel:
duas regras podem ser identicas em conteudo (uma duplicata exata ao lado de uma
terceira que diverge), e o anuncio precisa saber qual **entrada** venceu.

**O teste antigo nao servia para este item, e vale entender por que.**
`test_the_announced_winner_is_the_one_actually_applied` compara o vencedor
anunciado com o que `apply_all_substitutions` produz — e passa igualmente com
duas copias corretas do criterio, que era o estado anterior. Ele protege o
resultado, nao a unificacao.

O teste novo mexe no criterio **uma vez** e exige que os dois lados virem juntos:
troca `_rule_sort_key` por uma versao com o desempate de posicao invertido e
afirma que o anuncio e o texto passam a apontar a segunda regra. Ele precisa
limpar `_ordered_rules_cache`, porque o cache guarda a ordem e nao o criterio —
sem isso passaria pelo motivo errado.

Conferido por mutacao, que aqui e literalmente desfazer o item: reintroduzindo o
`min(...)` dentro de `glossary_conflicts`, dos 10 testes da classe **so o novo
falha**, dizendo o que houve.

```
AssertionError: Items in the first set but not the second: 0
Items in the second set but not the first: 1
  : o anuncio nao seguiu o criterio da aplicacao: ha uma copia dele
```

Os outros nove passando e a medida exata do que faltava: a concordancia estava
protegida, a origem unica nao estava.

Uma segunda mutacao cobre a outra metade, a conversao: trocando `_as_rule` por
`(orig, new)` — que descarta a prioridade — quem acusa e o teste de S10 que ja
existia.

**Nao houve custo, houve ganho.** A ordenacao das 7.006 regras de sugestao
reais, com o cache frio, medida 20 vezes:

|                                                    | mediana           | min     |
| -------------------------------------------------- | ----------------- | ------- |
| antes (chave montada inline, com a regra na tupla) | 4,48 ms           | 4,40 ms |
| depois (`sorted` sobre as posicoes)              | **3,62 ms** | 3,57 ms |

A versao antiga montava tuplas de quatro elementos carregando a propria regra e
depois reordenava por uma fatia delas; a nova ordena inteiros. O caminho do
editor tambem nao piorou: `glossary_conflicts` sobre o glossario real custa
13,1 ms, e com 200 disputas de tres regras injetadas (600 indices em disputa)
vai a 15,5 ms — a diferenca acompanha as 600 entradas a mais, e nao o numero de
grupos ordenados.

**Garantia S9 (reforcada):** *a interface diz qual regra do conflito vence, pelo
mesmo criterio que a aplica.* Nao ha mais um segundo lugar onde "prioridade e
ordem do arquivo" sao interpretadas.

### 3.7 O `glossario.db` versionado nao sobrevivia ao clone — CONCLUIDO (2026-07-27)

O `glossario.db` passou a ser versionado (antes o `.gitignore` o excluia junto
com o `traducoes.db`, pelo padrao `*.db`). A ideia e que um clone ja abra com o
indice pronto, em vez de reconstrui-lo do `Substituicoes.txt` na primeira carga.

**Versiona-lo sozinho nao entregava isso**, e o motivo estava nas duas marcas que
o banco guarda para dizer de onde veio:

| marca            | o que era                                  | por que nao sobrevive                                               |
| ---------------- | ------------------------------------------ | ------------------------------------------------------------------- |
| `source_path`  | `C:\Python Course\...\Substituicoes.txt` | absoluto: outra pasta ja diverge                                    |
| `source_mtime` | `1785184475.31`                          | o git nao guarda`mtime`; o arquivo clonado tem a hora do checkout |

`_glossary_database_needs_sync` compara as duas, e **as duas divergiam em
qualquer clone**. O cache versionado era descartado e reconstruido em toda
maquina — exatamente o que versiona-lo pretendia evitar. Medido copiando os dois
arquivos para outra pasta e dando ao `.txt` uma data nova, que e o que um
checkout faz:

```
clone em outra pasta, mtime novo -> reconstruir? True
carga no clone: 113 ms
```

**A correcao.** `source_path` passou a ser relativo ao proprio banco
(`_relative_source_path`), com `/` como separador porque o arquivo e versionado e
pode ser lido em outro sistema; e o `source_mtime` deu lugar a `source_hash`, o
sha256 do conteudo (`_source_fingerprint`). As duas respondem a mesma pergunta —
"este banco foi construido a partir deste arquivo?" — de um jeito que vale em
qualquer maquina. O `schema_version` subiu para 3, porque o significado das
marcas mudou e um banco antigo tem de ser reconstruido.

```
clone em outra pasta, mtime novo -> reconstruir? False
carga no clone: 16 ms
```

**7x mais rapido na primeira carga de um clone**, que era o ponto.

**O hash tambem e mais exato que o `mtime` no sentido oposto.** A gravacao do
glossario e atomica (arquivo temporario + troca), entao o `mtime` mudava mesmo
quando o conteudo era identico, e o cache era refeito por nada. Tem teste
proprio.

**Custo.** Ler 324 KB a cada checagem em vez de um `stat`: 0,277 ms contra
0,028 ms, medianas de 50 medicoes. A checagem inteira custa ~1,3 ms, e a carga
que ela evita custa 113 ms.

**Conferido por mutacao, uma marca de cada vez** — o que importava era que cada
metade fosse protegida sozinha, e nao que "algum teste falha":

| mutacao                                     | quem acusa                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------ |
| `source_path` volta a ser absoluto        | `..._survives_a_clone`: "o cache clonado foi descartado"                           |
| `source_hash` volta a ser o `mtime`     | o mesmo,**e** `..._rewriting_the_same_content...`                            |
| o hash vira constante ("nunca reconstruir") | `..._still_invalidates_the_cache`: "o glossario mudou e o cache continuou valendo" |

A terceira e a que impede a correcao de virar um cache que nunca expira — sem
ela, "sempre valido" passaria no teste do clone.

**Um tropeco meu no meio, que custou refazer o trabalho.** Para reverter a
segunda mutacao usei `git checkout tradutor_pgn/glossario.py`, e o arquivo tinha
as mudancas deste item ainda nao commitadas: o comando desfez a mutacao **e** o
item. Reverter mutacao com o mesmo comando que descarta trabalho nao commitado so
e seguro depois do commit; antes dele, o certo e desfazer a edicao pelo caminho
inverso.

---

## 4. Isolamento dos testes — CONCLUIDO (2026-07-25)

`_default_substitutions_path()` deriva o caminho de `sys.argv[0]`. Sob
`python -m unittest`, `sys.argv[0]` e a string `'python.exe -m unittest'` — sem
nenhuma barra —, entao `os.path.dirname(os.path.abspath(...))` resolve para o
DIRETORIO ATUAL. Rodando a suite da raiz do projeto, o caminho padrao aponta
para o `Substituicoes.txt` real, com as milhares de regras do usuario.

Nenhum teste chamava essas funcoes sem caminho explicito (verificado: a suite
nao altera o arquivo), mas bastava um esquecimento para uma execucao de testes
apagar entradas do glossario de verdade, sem relacao aparente com o teste que
falhasse. `setUpModule` agora redireciona o caminho padrao do glossario e das
configuracoes para um diretorio temporario, e `DefaultPathSafetyTests` falha se
essa protecao cair.

---

## 4.1 Negrito por selecao, perdido e restaurado — CONCLUIDO (2026-07-27)

Comparando esta branch com a `origin/main` (que refatorou o mesmo codigo por
outro caminho) apareceu a unica diferenca de comportamento entre as duas: o
projeto original tinha `toggle_bold_selection`, que marcava em negrito o trecho
selecionado da traducao. Em algum ponto o botao "B" passou a alternar a fonte do
editor inteiro (`toggle_bold_view`) e o recurso antigo sumiu junto.

Nao e o mesmo recurso: um e leitura (a fonte toda), o outro e marcacao (um
trecho). Os dois voltaram a existir. O botao ficou com o alternador de fonte,
onde ele pertence — ao lado dos controles A-/A+ —, e a marcacao voltou no
`Ctrl+B`, que estava livre e e o gesto universal para "negrito no que esta
selecionado".

Ficou registrado no codigo o que a marca **nao** e: a tag do Tk nao vai para o
banco e recarregar a traducao a desfaz. Era assim no original e faz sentido — o
que se grava e o texto do comentario, nao a formatacao de quem revisa.

Tinha sobrado plumbing morto: a tag `bold` continuava sendo configurada em dois
pontos sem que nada a aplicasse. Voltou a ter uso.

Conferido por mutacao: nao ligar o `Ctrl+B`, marcar sem nunca desmarcar, marcar
mesmo sem selecao, e o alternador de fonte apagando a marcacao — as quatro
falham.

---

## 5. Cobertura de testes — CONCLUIDO (72 -> 396 testes)

**A premissa deste item estava errada.** Ele dizia que testar
`open_translation_editor` / `open_glossary_editor` "so e viavel depois de 3.1".
Nao e: o Tk expoe a arvore de widgets, e `invoke()` dispara o mesmo `command`
que um clique. As duas janelas sao testaveis hoje, do jeito que estao.

Isso inverte a ordem prevista — a rede de testes vem ANTES da refatoracao, que
e exatamente o que ela precisa para nao ser feita as cegas. `tests/ test_editor_windows.py` abre as janelas de verdade, clica nos botoes e confere
o disco. Onde nao houver display, a classe inteira e pulada.

Cobertos nesta rodada:

- `translate_text_chunk` — retry/backoff completo, com a sessao HTTP injetada
  (nenhum teste toca a rede): quais status repetem, quais falham na hora,
  quantas vezes dorme, erro de rede, resposta 200 ilegivel.
- `case_adjusted_replacement` — propagacao de caixa, incluindo texto sem letras
  (`1-0`) e simbolo antes da primeira letra.
- `read_glossary_csv` — cabecalhos alternativos, BOM, acentos, coluna
  obrigatoria ausente, ida e volta com o exportador.
- **Fallback individual do worker (garantia B2)** — era o ultimo caminho do
  worker sem teste, e o que impede o pior defeito possivel do programa: dar a
  traducao de um comentario a outro.
- Os tres bugs corrigidos em 3.3 e 3.4, agora como testes de regressao pelos
  widgets.

Todos os testes novos de rede, de B2 e de regressao foram conferidos por
mutacao: quebrando a producao de proposito, eles falham. Um teste que passa dos
dois jeitos nao protege nada.

### 5.2 O despachante de tarefas nao tinha teste — CONCLUIDO (2026-07-28)

Medida a cobertura do pacote inteiro, um modulo destoava de todos os outros:

```
background_task.py    95 stmts   79 sem cobertura    17%
(o segundo pior)      80 stmts   19 sem cobertura    76%
```

E o `run_with_progress`, que tira backup, restauracao, importacao de CSV e
"Aplicar automaticas" da thread da interface (2.11). Sao **sete pontos de
chamada** em `db_tools`, e o corpo inteiro da funcao (linhas 73-173) nunca era
executado por teste nenhum.

**O motivo era razoavel, e e justamente o que torna o buraco perigoso.** Os
testes dos chamadores usam o `SynchronousProgress`, que roda o trabalho na hora,
porque o que eles verificam e a orquestracao das operacoes de banco e nao a
thread — decisao correta. O efeito colateral e que **o dublê reimplementa o
criterio de despacho do original**: se o de verdade mudasse, o dublê manteria o
comportamento antigo e os sete chamadores continuariam passando. A suite ficaria
verde testando uma copia da regra em vez da regra.

Criado `tests/test_background_task.py`, que exercita a coisa real. **17% -> 88%**;
as 11 linhas que sobram sao todas ramos defensivos de `except`. O que os testes
fixam e a garantia C1 nas duas direcoes — o trabalho roda fora da thread do Tk, e
tudo o que volta chega na thread do Tk (conferido comparando `get_ident()`) — mais
o despacho: excecao vai para `on_error`, `TaskCanceled` vai para `on_cancel`, e
**trabalho que devolve normalmente depois de `cancel()` conta como cancelado**.
Esse ultimo e o mais facil de quebrar sem perceber: varias operacoes de
`db_tools` desistem devolvendo o que deu tempo de fazer, e trata-lo como sucesso
anunciaria "importacao concluida" para uma importacao interrompida.

Cinco mutacoes, todas pegas.

**O teste caiu numa armadilha que vale registrar, porque parece um bug de
producao e nao e.** A primeira versao usava um laco de `root.update()` para
processar os eventos, e **12 dos 17 testes falharam identicos**: "a tarefa nunca
devolveu o controle". O Tk so aceita `after` vindo de outra thread enquanto a
principal esta DENTRO do `mainloop()`; fora dele levanta
`RuntimeError: main thread is not in main loop`, e o `run_with_progress` engole
essa excecao de proposito (nesse ponto nao ha mais a quem avisar). Resultado: o
trabalho roda ate o fim e a resposta some, sem nada acusar. Em producao nao
acontece — a janela vive sob `mainloop()` —, entao o defeito era do teste. A
correcao foi rodar o `mainloop()` de verdade e conferir a condicao de dentro
dele, por um `after` encadeado.

**Uma suspeita minha que a medicao derrubou.** A saida dos testes trazia um
`bad window path name ".!ctktoplevel"`, e a hipotese foi que o `after(200)` de
`bring_window_to_front` — o unico agendamento sem guarda no modulo — disparava
contra janela destruida e, com o relator de erros da C3 instalado, virava um
dialogo "Erro inesperado" para o usuario. **Nao vira.** Reproduzido com a janela
destruida dentro da janela de tempo exata: zero dialogos. Destruir um widget
apaga os comandos Tcl registrados nele, entao o timer dispara sem callback e a
mensagem sai do Tcl — nunca chega ao `report_callback_exception`, que so ve
excecao Python. E ruido cosmetico, e o item nao existe.

### 5.3 "Normalizar PGN" sem teste, e a lista de tags em dois lugares — CONCLUIDO (2026-07-28)

Depois do 5.2, o maior bloco continuo sem cobertura do pacote era
`pgn_spellcheck.py:254-298`: **a funcao inteira** `normalize_pgn_metadata_path`,
que e o que o botao "Normalizar PGN" chama. Os testes que existiam paravam uma
camada abaixo — no conteudo e no arquivo unico —, entao a orquestracao (carregar
o dicionario, coletar os arquivos, pular os ja normalizados, somar as
estatisticas) nunca rodava.

**A garantia N1 tambem nao estava na tabela da secao 8 da SPEC**, e com razao: o
que havia era um teste de conteudo conferindo que um comentario sobrevivia. N1
diz mais do que isso — comentarios, lances **e variantes** — e nao havia nada
sobre variantes nem sobre o arquivo gerado.

Doze testes novos para o orquestrador, com um PGN de teste construido para
atrapalhar: variantes aninhadas, NAGs, avaliacoes, os mesmos nomes DENTRO de
comentarios e uma tag `Annotator` com o nome que o dicionario corrigiria se ela
fosse suportada. N1 passa a ser verificada onde importa — o movetext do arquivo
gerado tem de sair identico linha a linha, e so as cinco tags mudam.

**O achado veio de uma mutacao que NAO quebrou nada, e a investigacao do porque.**
Duas mutacoes contra a N1 passaram na suite inteira. Nao era fraqueza dos
testes: as duas eram no-ops, e o motivo de uma delas e o problema de verdade.

Acrescentar `"Annotator"` a `SUPPORTED_TAGS` nao mudava comportamento nenhum
porque **a lista de tags estava escrita duas vezes** — no dicionario e a mao
dentro do `PGN_TAG_RE`. As duas copias falhavam em silencio ao divergir, cada
uma de um jeito oposto, e nenhum dos dois erros e visivel lendo so um dos lados:

| divergencia                 | efeito                                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| tag so em`SUPPORTED_TAGS` | nada acontece: o regex nunca casa a linha, a tag nao e corrigida, sem erro nem aviso                                  |
| tag so no`PGN_TAG_RE`     | `KeyError` em `SUPPORTED_TAGS[tag_name]` — derruba a normalizacao de **qualquer** PGN que tenha aquela tag |

E a mesma classe do item 3.6 (a mesma decisao em dois lugares), e foi encontrada
pelo mesmo caminho: uma verificacao que nao distinguia "os dois concordam" de
"os dois sao o mesmo".

Correcao: `PGN_TAG_RE` passa a ser **derivado** de `SUPPORTED_TAGS`, e ha teste
que compara o que o regex ACEITA com o que o dicionario declara — e nao o texto
do padrao, que continuaria passando com as duas copias. Os dois sentidos da
divergencia foram reintroduzidos de proposito: o primeiro quebra dois testes, o
segundo quebra cinco.

**E um teste meu que nao testava nada, de novo.** O de dicionario ausente
conferia so o TIPO da excecao, e `FileNotFoundError` e o que o `open()` levanta
sozinho quando a guarda explicita e removida — passava dos dois jeitos. Agora
exige a mensagem, que e o unico sinal que distingue a guarda do erro cru.

Cobertura do pacote: 87% -> 88%; `pgn_spellcheck` saiu da lista dos piores.

### 5.4 O fluxo de "Aplicar automaticas", e um banco corrompido que trancava o arquivo — CONCLUIDO (2026-07-28)

Depois do 5.3 a maior lacuna restante era `db_tools.py`, com dois blocos:
`apply_automatic_rules_to_database` (56 linhas) e `show_db_stats` (39, a funcao
inteira).

**"Aplicar automaticas" so tinha teste no ramo de CANCELAMENTO.** O fluxo
principal — analisar, confirmar, aplicar, relatar — nunca rodava, justamente na
operacao em que os itens 2.7 e 2.11 mais mexeram. Ela tem quatro saidas e cada
uma decide coisas diferentes, inclusive uma assimetria que so aparece lendo com
atencao: em "nada a mudar" o `on_finish` recebe a **previa**, e nao `None`,
porque nada a fazer e um resultado e nao uma desistencia.

Oito testes, entre eles o que fixa a limpeza do `translation_cache`: depois de
reescrever as traducoes no banco, o que esta em memoria e a versao anterior as
regras — e o cache tem precedencia sobre o banco. Quatro mutacoes, todas pegas.

**A primeira mutacao nao chegou a ser aplicada, e o "OK" era falso.** A ancora
`app.translation_cache.clear()` aparece tres vezes no arquivo; o script abortou
por ambiguidade e o teste rodou contra o codigo intacto. Refeita por numero de
linha, ela quebra. Vale como lembrete de que uma mutacao que "passa" so conta
depois de confirmado que ela foi aplicada.

**O achado veio de um teste que nao conseguia limpar o proprio diretorio
temporario.** O caso "banco corrompido" deixava o arquivo preso com
`PermissionError: [WinError 32]`. A causa esta em `initialize_database`, e nao
no teste: ela abre a conexao e so depois roda o `PRAGMA user_version`. Num
arquivo corrompido o PRAGMA levanta, a excecao sobe **sem a conexao nunca ter
sido devolvida** — quem chamou nao tem o que fechar — e o arquivo fica preso ate
o coletor de lixo passar.

Reproduzido: uma conexao viva, arquivo intocavel, e liberado por um
`gc.collect()` explicito. O efeito para o usuario e o pior possivel: o programa
avisa que nao conseguiu ler o banco e, **ao mesmo tempo, impede que ele seja
substituido pelo backup**. E atinge todo chamador de `initialize_database` — que
e quase toda a interface —, e nao so o "Estatisticas" por onde apareceu.

Correcao: fechar a conexao antes de deixar a excecao subir. A mutacao que remove
esse `close()` reproduz o `WinError 32` nos testes.

`db_tools`: 81% -> 88%. Pacote: 88%.

### 5.1 `app_actions.py`, o modulo menos coberto — CONCLUIDO (2026-07-27)

**A medicao inicial estava otimista.** A anotacao dizia "11 de 25 funcoes
aparecem em algum teste", e aparecer nao e ser exercitada: instrumentando as 25 e
rodando a suite inteira, **cinco** eram chamadas. As outras vinte sao justamente
o caminho por onde o usuario comeca tudo — iniciar, pausar, cancelar,
reprocessar o que falhou, abrir os dois editores e as ferramentas de banco.

Criado `tests/test_main_window.py`, que abre a **janela principal de verdade**
(`PGNTranslatorApp`) e clica nos botoes dela. Nao e capricho: quase tudo o que
estas funcoes fazem e estado de botao, e um botao habilitado quando nao devia so
aparece na tela. Um app falso com atributos soltos passaria por cima exatamente
do que ha para verificar. **25 de 25** agora sao exercitadas.

O harness comum saiu para `tests/gui_harness.py` — o gate de display, o
silenciamento dos dialogos e o sandbox de caminhos. Uma segunda copia de
`SilentDialogs` seria a armadilha que o item 3.2 descreve nos editores: corrigir
uma e esquecer a outra. O sandbox ganhou tambem o `sys.argv[0]`, que nao e
detalhe — e dele que saem `output_db`, `backups/` e `logs/`, e a abertura do
programa roda a retencao de `backups/`: um teste que abra o app sobre o diretorio
do projeto **apaga backups de verdade**.

O teste que mais rende e
`test_the_run_log_is_named_so_the_retention_can_find_it`, e ele fecha uma ponta
solta do item 1.4. Aquele item registrou o modo de falha mais chato possivel — se
o formato do nome divergir do que `prune_log_files` procura, a retencao de `logs/`
vira um **no-op silencioso** — mas o teste que ficou usava nomes escritos a mao.
Agora o produtor de verdade (`_begin_translation_run`, com o relogio fixado) gera
dois logs e o consumidor de verdade (`prune_log_files`) remove o mais antigo.

**Conferido por mutacao**, doze maneiras de errar em `app_actions.py`: pausar sem
execucao, cancelar deixando a execucao pausada, o carimbo do log voltando ao
underscore, reprocessar pelo idioma do seletor em vez do idioma do registro,
reprocessar mandando junto os arquivos que sumiram do disco, o handle do log nao
sendo zerado, comecar sem zerar o `cancel_flag`, as regras automaticas perdendo o
idioma, o seletor de arquivo gravando o cancelamento por cima do caminho
anterior, o fim da normalizacao nao liberando os botoes, a limpeza da abertura
propagando a falha, e iniciar aceitando um caminho que nao existe.

**Onze foram pegas de primeira; a decima segunda expos um teste meu que nao
testava nada.** Remover o `reset_buttons` do fim da normalizacao nao quebrava
coisa alguma, porque o teste afirmava que os botoes estavam habilitados **sem
nunca te-los desabilitado**. Os dois testes passaram a montar antes o estado que
`normalize_pgn_metadata` deixa de verdade; a mesma mutacao agora falha nos dois.

**As tres lacunas que este item listava, e o que aconteceu com elas:**

- ~~Nenhum teste exercita duas partes do programa ao mesmo tempo.~~ **FEITO**
  (2026-07-27): `ConcurrentDatabaseAccessTests` e `FallbackTransactionTests`
  sobem uma thread com transacao de escrita aberta no `traducoes.db` e checam,
  da thread principal, o que o editor conseguiria fazer. Foram esses testes que
  mostraram que a analise inicial da secao 6 acusava o lock errado. Nenhum deles
  precisa de rede.
  O harness do worker virou `WorkerFallbackHarness` (uma classe simples, nao um
  `TestCase`) para que as duas classes o usem sem que herdar de uma faca os
  testes da outra rodarem duas vezes.
- ~~Falta um teste que fixe a codificacao de entrada UTF-16 (secao 8).~~ **FEITO**
  junto com a secao 8: as sete codificacoes sao exercitadas com e sem `chardet`,
  incluindo UTF-16-LE sem BOM, que era o caso que escapava de E1/E2/E3.

Nada mais pendente aqui: com 5.1, `app_actions.py` deixou de ser o modulo menos
coberto. O que nao tem teste hoje sao os dois modulos que so montam widgets
(`main_window.py` e as etapas de construcao dos editores), exercitados de fora —
pela abertura das janelas e pelos cliques — e nao afirmados peca a peca.

---

## 6. O editor e o worker disputam o mesmo banco — CONCLUIDO (2026-07-27)

**Correcao da analise inicial.** A primeira versao deste item dizia que o
problema era a **leitura** do editor, apoiada nesta medicao:

```
journal_mode=delete   leitura durante a escrita:  7334,7 ms -> database is locked
journal_mode=wal      leitura durante a escrita:     11,5 ms -> ok
```

O numero e real, mas o cenario nao era o do programa: o escritor daquele teste
inseria 20.000 linhas numa transacao so, o que estoura o cache de paginas e faz o
SQLite escalar para o lock EXCLUSIVE. **O worker nunca escreve assim** — sao
~40 linhas por lote. Com transacoes desse tamanho o escritor fica em RESERVED, e
em RESERVED o SQLite deixa os leitores passarem. Tentei transformar a medicao num
teste de regressao e ele nao reproduziu; foi assim que o erro apareceu.

O defeito e real, mas e outro, e e pior de um jeito diferente: **o que trava e a
escrita.** Duas conexoes nunca escrevem ao mesmo tempo, nem em WAL. Enquanto o
worker mantiver transacao aberta, o "Salvar" do editor espera o `busy_timeout`
(30 s) e depois falha — e as consultas do editor estao todas em
`with closing(initialize_database(...))` sem `try`, num callback do Tk, entao o
`sqlite3.OperationalError` vira traceback no console (invisivel sob `pythonw`) e
a gravacao simplesmente nao acontece.

E o worker mantinha essa transacao aberta por muito tempo — ver 6.1.

### 6.1 A transacao de escrita fica aberta durante as chamadas de rede

O worker piora muito o proprio caso, e so no caminho de fallback — que e o que
roda justamente quando a rede esta ruim. Em `run_translation`, a traducao
individual faz, dentro do mesmo `for`:

```
translated = translate_text(...)     # rede: ate 30 s de timeout, ate 3 tentativas
save_translation(cursor, ...)        # <- abre a transacao de escrita
time.sleep(...)
                                     # ...e o proximo comentario, e o proximo...
conn.commit()                        # <- so aqui, no fim do lote
```

O primeiro `save_translation` abre a transacao e ela so fecha no `commit` do fim
do lote. Entre os dois ha **todas as chamadas de rede restantes do lote**. Num
lote de 40 comentarios a ~1 s por requisicao, o lock de escrita fica retido mais
de 40 s — mais do que o `busy_timeout` do editor. No caminho normal (lote
alinhado) as gravacoes acontecem todas depois da unica chamada de API, e a
transacao dura milissegundos; por isso o problema nao aparece sempre, e sim
justamente quando a rede esta ruim.

### 6.2 Correcao — FEITA

**Commit por comentario no fallback** (`translation_worker.py`). E a correcao de
verdade: devolve o lock entre uma requisicao e a seguinte.

Conferido por mutacao, que e o que separa este item de uma suposicao. O teste
`FallbackTransactionTests` sonda, de outra conexao e no exato instante da chamada
de rede, se o lock de escrita esta livre. Com a correcao ligada, todas as sondas
passam; removendo so a linha do `conn.commit()`:

```
- ['Second comment here', 'Third comment here']
+ [] : o banco estava travado durante a chamada de rede destes comentarios
```

Os dois comentarios acusados sao exatamente os que vem **depois** da primeira
gravacao — ou seja, os que ja encontram a transacao aberta. O primeiro nao
acusa porque nada foi gravado ainda. O padrao bate com a explicacao, e nao so
com "falhou".

**`PRAGMA journal_mode=WAL` + `synchronous=NORMAL`** em `open_database`. Nao e o
que conserta o travamento — e o que torna a correcao acima barata. A troca de
1 commit por lote para 1 commit por traducao multiplica os commits por ~40, e o
custo de um commit depende do modo. Medido inserindo 300 linhas no banco real:

| modo                                         | commit por traducao | commit por lote |
| -------------------------------------------- | ------------------- | --------------- |
| `delete` + `synchronous=FULL` (o antigo) | 3,45 ms             | 0,11 ms         |
| `wal` + `synchronous=NORMAL` (o novo)    | **0,14 ms**   | 0,01 ms         |

25x mais barato por traducao. De quebra, em WAL o leitor nunca espera nem
durante o commit, que era o unico momento em que a leitura realmente parava.

O risco de `synchronous=NORMAL` esta declarado no codigo: uma queda do **sistema**
pode custar as ultimas transacoes; uma queda do **programa**, nao. Para um cache
que se reconstroi reexecutando a traducao, e a troca certa.

Entraram junto `*.db-wal` e `*.db-shm` no `.gitignore`. Backup e restauracao ja
usavam `Connection.backup` (a API de backup online do SQLite), que lida com o WAL
corretamente — se usassem `shutil.copy`, copiariam um banco sem as transacoes que
ainda estivessem no `-wal`.

### 6.3 O lock invisivel — CONCLUIDO (2026-07-27)

Faltava a outra metade de C3: o editor nao tratava `sqlite3.OperationalError`.
Com a transacao do worker curta a colisao ficou improvavel, mas "improvavel" nao
e "impossivel", e o resultado seria um traceback invisivel sob `pythonw`.

**A previsao de que isso dependia de 3.1 etapa 2 estava errada**, e por um motivo
que so apareceu ao tentar implementar. O plano era reunir os acessos ao banco em
metodos e envolver cada um num `try`. Fui fazer isso e os nove sitios de
`with closing(initialize_database(...))` mostraram o contrario: **capturar em cada
um seria pior do que nao capturar.** `save_changes` e chamada por doze funcoes,
varias das quais navegam logo depois. Hoje a excecao sobe e aborta o fluxo — a
edicao do usuario fica no widget. Capturando e devolvendo `None`, `select_index`
seguiria em frente e carregaria outra linha, **descartando a edicao em silencio**.
Trocar um erro invisivel por perda de dados silenciosa nao e conserto.

O que o problema pedia era o oposto: deixar a excecao subir como ja sobe, e so
garantir que ela seja **vista**. O Tk tem o gancho exato para isso —
`Misc._report_exception` chama `self._root().report_callback_exception(...)`.
`install_callback_error_reporter` instala o handler na raiz na abertura do
programa, e como as janelas de edicao sao `Toplevel` dessa raiz, uma instalacao
cobre as tres.

O buraco tambem nunca foi so do lock: sob `pythonw` **qualquer** excecao que
escape de um callback desaparece. A correcao vale para todas; o lock so tem texto
proprio, porque e o unico caso previsto e com causa conhecida (diz que ha uma
traducao em andamento, que nada foi gravado, e que basta tentar de novo).

A mesma mensagem nao reabre o dialogo por 2 s — um callback periodico que falhe
sempre encheria a tela. Passada a janela, quem tentar de novo e avisado de novo:
a supressao existe para conter rajada, nao para calar o erro.

**A verificacao por mutacao encontrou duas falhas nos meus proprios testes**, e
as duas eram do tipo pior — o codigo parecia protegido e nao estava:

1. Apagar a chamada de `app.py` nao quebrava **nada**. Sete testes verdes sobre
   um relator que ninguem ligava. Entrou `test_the_real_app_installs_it`, que
   abre o programa de verdade e confere que o dialogo aparece.
2. Escrevendo esse teste, passei um `Toplevel` no lugar da raiz e ele falhou —
   corretamente. Isso expos um modo de falha da propria funcao: instalada na
   janela errada, ela nunca dispararia, e tudo pareceria configurado. O
   instalador passou a resolver `_root()`, com teste proprio.

O resto das mutacoes (handler nao ligado, lock tratado como erro generico,
supressao permanente, supressao ausente) ja era pego.

**Garantia C3 (completa):** *o worker nao segura o banco, e um lock nunca some.*
Nenhuma transacao de escrita permanece aberta atravessando uma chamada de rede,
entao gravar no editor durante uma traducao espera no maximo o tempo de uma
gravacao. E se ainda assim houver colisao, o usuario recebe uma mensagem que diz
o que fazer, em vez de nada.

---

## 7. Robustez da traducao

### 7.1 Uma falha de rede vira uma tempestade de requisicoes — CONCLUIDO (2026-07-27)

Em `run_translation`, o fallback individual e acionado por duas condicoes
diferentes que exigem respostas diferentes:

```python
parts = None
if translated_joined:
    parts = split_batch_translation(translated_joined, len(originals))

if parts:
    ...
else:
    if translated_joined:
        app.log_message("  - Aviso: divisao do lote falhou ...")
    for original, cleaned in to_translate:   # <- roda nos DOIS casos
```

- **Desalinhamento** (`translated_joined` veio, mas nao deu para separar): o
  fallback e a resposta certa. E a garantia B2, e ela esta coberta por teste.
- **Falha da API** (`translated_joined is None`): o lote acabou de gastar 3
  tentativas contra o endpoint. O fallback entao repete **cada** comentario, e
  cada um gasta outras 3 tentativas. Repare que nesse caso nem log ha — o `if translated_joined` deixa a mensagem de fora justamente quando a causa e a pior.

A conta do pior caso, com o `timeout=30` de `translate_text_chunk`: um lote de
40 comentarios contra um endpoint que pendura a conexao gasta 3 x 30 s no lote e
depois 40 x 3 x 30 s no fallback — **cerca de uma hora para um lote**, terminando
com todos os 40 comentarios contados como falha. E o comportamento observavel e
"o programa travou".

Os dois casos passaram a ser ramos separados. Lote sem resposta: as falhas sao
contadas de uma vez (T2/T3 continuam valendo — o texto fica no idioma original) e
o log **agora existe**, dizendo que a API nao respondeu. Lote desalinhado: nada
mudou, o fallback individual continua sendo a resposta certa, que e a B2.

Entrou tambem um disjuntor: `MAX_CONSECUTIVE_FAILED_BATCHES = 3` lotes seguidos
sem nenhuma resposta interrompem a execucao. O contador zera assim que a API
responde qualquer coisa — inclusive uma resposta desalinhada, que e problema do
conteudo e nao da conexao.

Conferido por mutacao. Voltando o comportamento antigo (todo lote sem `parts`
cai no individual):

```
AssertionError: 4 != 1  : a API foi chamada 4 vezes; devia ser so a do lote
AssertionError: 24 != 3 : parou depois do limite, e nao no fim da lista
```

Com 3 comentarios o antigo ja fazia 4x mais requisicoes; a proporcao e a mesma
para 40. No teste do disjuntor, 24 chamadas contra 3.

Dois efeitos colaterais tratados junto:

- **O arquivo de saida nao e gerado quando a execucao aborta.** Com a API fora
  ele sairia quase todo no idioma original e pareceria pronto. O que ja foi
  traduzido continua no banco, entao reexecutar so paga o que falta — a mesma
  logica de C2.
- **A instrucao final deixou de mentir.** "Reprocesse os arquivos gerados" so
  aparece quando algum arquivo foi gerado; caso contrario o texto manda
  reprocessar os arquivos de origem. Antes, com todos os comentarios falhando,
  ela apontava para um arquivo que nao existia (era a queixa registrada em 7.3).

**Um teste antigo precisou mudar**, e vale registrar por que.
`test_run_translation_reports_failed_comments_instead_of_silent_success` (T2)
usava `return None` no lote para **forcar** o fallback individual. Isso funcionava
justamente por causa do defeito: `None` caia no individual. Com B3 nao cai mais,
entao o teste passou a provocar o fallback com uma resposta desalinhada de
verdade. O que ele verifica — falha parcial nao vira "Concluido" limpo — nao
mudou.

**Garantia B3 (nova):** *falha de API e desalinhamento sao tratados de forma
diferente.* Um lote que nao obteve resposta nao e reprocessado comentario a
comentario, e uma sequencia de lotes sem resposta interrompe a execucao com
mensagem em vez de arrastar por horas.

### 7.2 A espera entre tentativas nao reage a 429 — CONCLUIDO (2026-07-27)

`translate_text_chunk` repete 429/500/502/503/504 tres vezes, com
`random.uniform(0.3, 2.2)` entre elas. Duas observacoes:

- A espera e **constante com jitter, nao exponencial**. Contra 429 (limite de
  taxa), tres tentativas rapidas sao praticamente uma so: se o servidor pediu
  para desacelerar, a terceira chega tao cedo quanto a primeira.
- O `TRANSLATION_REQUEST_DELAY_SECONDS` foi reduzido de forma agressiva nos
  ultimos commits (`(0.04, 0.12)` hoje). Isso aumenta o rendimento e tambem a
  chance de 429 — e o retry, que e a defesa contra essa consequencia, ficou como
  estava. As duas coisas deveriam se mover juntas.

Correcao: backoff exponencial com jitter, e o intervalo normal entre requisicoes
reagindo ao que a API responde (aumenta ao ver 429, volta a diminuir depois de
uma sequencia limpa). O endpoint e publico e nao oficial, entao a politica
conservadora e o que mantem o programa utilizavel.

**Feito, e sao duas correcoes separadas** — a distincao importa porque cada uma
resolve uma coisa que a outra nao alcanca.

**1. A espera entre tentativas** (`retry_delay_seconds`, funcao pura). Dobra a
cada tentativa, com teto de 20 s, e 429 parte de uma base maior que 5xx: um 429 e
o servidor dizendo que o ritmo esta alto demais, um 503 e problema passageiro
dele.

|                         | 1a espera       | 2a espera       |
| ----------------------- | --------------- | --------------- |
| antes (qualquer status) | 0,3–2,2 s      | 0,3–2,2 s      |
| agora, 5xx              | 0,6 s           | 1,2 s           |
| agora, 429              | **2,0 s** | **4,0 s** |

O jitter e multiplicativo (0,5x a 1,5x), nao aditivo: duas execucoes que tomem
429 ao mesmo tempo precisam se espalhar em proporcao a espera. Somar fracoes de
segundo nao separa esperas de 8 s.

**2. O intervalo normal** (`RequestPacer`). O retry sozinho nunca ia resolver
isto, e vale registrar por que: ele conserta a requisicao que falhou, nao a causa
— esgotadas as tres tentativas o comentario falha igual, e a requisicao seguinte
sai no mesmo ritmo que provocou o 429. Um 429 e o unico sinal confiavel de que o
ritmo esta alto demais, e o unico lugar util para esse sinal e o intervalo das
requisicoes **seguintes**.

O pacer multiplica `TRANSLATION_REQUEST_DELAY_SECONDS`. Em repouso o
multiplicador e 1 e o comportamento e identico ao de antes:

```
repouso      1,0x     80 ms        +25 limpas   30,0x   2400 ms
1o 429       6,0x    480 ms        +50 limpas   15,0x   1200 ms
2o 429      30,0x   2400 ms        +75 limpas    7,5x    600 ms
3o 429      60,0x   4800 ms       +100 limpas    3,8x    300 ms
```

Sobe rapido e desce devagar, de proposito: o custo de insistir rapido demais e um
comentario perdido depois de tres tentativas; o custo de esperar demais e so
tempo. A assimetria e a escolha entre os dois. O teto existe porque sem ele um
endpoint que responda 429 sempre levaria o intervalo a minutos.

Um 5xx **nao** mexe no ritmo, e ha teste so para isso. Tratar os dois igual seria
desacelerar a traducao inteira por causa de uma instabilidade do servidor, que e
justamente o que o retry ja resolve.

**Conferido por mutacao**, nove maneiras de errar, cada uma pega pelo teste
correspondente: espera constante em vez de exponencial, 429 esperando o mesmo que
5xx, espera sem teto, qualquer status repetivel desacelerando o ritmo, o 429 nao
chegando ao pacer, acelerar de volta sem a sequencia limpa, a recuperacao passando
por baixo do intervalo original, multiplicador sem teto, e o 429 nao zerando a
sequencia limpa.

Uma armadilha de teste que vale registrar: o jitter e sorteado e as faixas de
tentativas vizinhas **se sobrepoem** (5xx da 0,3–0,9 s e 0,6–1,8 s). Afirmar que
a segunda espera e maior que a primeira daria um teste que falha sozinho de vez
em quando. Por isso a progressao e verificada na funcao pura, com o fator fixado,
e a integracao so exige que cada espera real caia dentro da faixa da sua
tentativa.

### 7.3 Nao ha como reprocessar so as falhas — CONCLUIDO (2026-07-27)

Hoje, terminada uma execucao com falhas, o resumo diz:

> "Reprocesse os arquivos gerados para completar a traducao."

Isso funciona, mas custa uma passagem inteira: os comentarios que deram certo
voltam pelo cache (rapido, mas nao de graca), e os que falharam sao reencontrados
por varredura. Pior, quando **todos** os comentarios de um arquivo falham,
`translated_map` fica vazio, nenhum arquivo de saida e gerado — e a instrucao
manda reprocessar um arquivo que nao existe.

O worker ja sabe exatamente quem falhou (`failed_count`, `failed_files`).
Guardar a lista e oferecer "reprocessar apenas as falhas" transforma uma
reexecucao de horas numa de minutos. Corrigir a mensagem para o caso de arquivo
nao gerado e independente e imediato.

**Feito.** Criado `tradutor_pgn/failed_runs.py`, que nao importa Tk: decidir o
que reprocessar e separado de perguntar. O worker anota a lista ao terminar,
`run_translation` ganhou `only_files=` e o botao "Reprocessar Falhas" ficou ao
lado dos controles de execucao — e uma forma de iniciar uma traducao, so que
restrita, e nao uma ferramenta de banco.

**Arquivos, e nao comentarios.** Seria possivel guardar cada comentario que
falhou, e nao adiantaria: o worker reextrai os comentarios do arquivo de qualquer
jeito, e os que deram certo saem do cache sem tocar a rede. O ganho real vem de
**nao abrir os arquivos que nao devem nada** — e para isso a lista de arquivos
basta. Menos estado persistido, menos coisa para ficar obsoleta.

Quatro decisoes que os testes protegem:

- **O idioma vem do registro, nao do seletor.** A lista foi montada traduzindo
  para aquele idioma; reaproveita-la com outro selecionado produziria um arquivo
  misturado sem que ninguem tivesse pedido.
- **A lista explicita nao passa por `collect_pgn_files`.** Aquela funcao descarta
  nomes com sufixo de idioma, entao um PGN de origem chamado `estudo-BR.pgn`
  sairia da lista justamente por ter falhado antes.
- **Execucao limpa apaga o registro.** Sem isso o botao ofereceria para sempre
  uma lista ja resolvida.
- **Execucao cancelada nao mexe no registro.** Os arquivos ainda nao visitados
  nao foram avaliados, e gravar a lista parcial por cima da anterior perderia o
  que ela ja sabia.

Arquivos que sumiram do disco entre uma execucao e outra sao filtrados e
contados no dialogo, e uma lista que ficou inteiramente obsoleta oferece ser
descartada. `save_failed_run` passa por `update_settings`, entao anotar as falhas
nao apaga os rascunhos de traducao que vivem no mesmo arquivo (garantia R4).

**A verificacao por mutacao corrigiu um teste meu que nao testava nada.** A
primeira versao de `test_a_canceled_run_...` ligava o `cancel_flag` **antes** de
comecar. Cancelar ali nao exerce coisa alguma: o worker retorna na primeira
checagem e nao chega perto do registro, entao o teste passava com ou sem a
protecao.

Investigando, apareceu um erro meu maior: eu tinha escrito que o guarda
`if not canceled` era o que protegia o invariante, e ele e **inalcancavel** — os
seis pontos de cancelamento fazem `return` imediato. Quem protege hoje e o
`return`. O guarda ficou (uma linha, e impede que mudar aquela estrutura passe a
sobrescrever a lista em silencio), mas com o comentario dizendo a verdade.

O teste foi refeito para cancelar **no meio**, com um arquivo ja traduzido, e
para fixar o invariante em vez do mecanismo. O resultado agora e o esperado de um
teste assim:

```
so o `return` vira `break`        -> OK   (o guarda segura)
so o guarda `if not canceled` some -> OK   (o `return` segura)
os DOIS quebrados                  -> FALHA
```

As demais mutacoes ja eram pegas: execucao limpa nao apagando o registro,
`only_files` voltando a passar pelo filtro de sufixo, registro truncado sendo
aceito, e o worker nao anotando nada.

Continua valendo o que 7.1 ja corrigiu: a instrucao final so manda reprocessar os
arquivos gerados quando algum foi gerado.

---

## 8. Codificacao de entrada: UTF-16 nao e tratado — CONCLUIDO (2026-07-27)

As garantias E1/E2/E3 foram escritas para arquivos de byte unico e resolvem bem
esse mundo. **UTF-16 escapa das tres.** Reproduzido com um PGN de duas linhas:

```
utf16le_sem_bom  detectado=utf-8   comentarios=['\x00O\x00 \x00b\x00i\x00s\x00p\x00o ...']
utf16_com_bom    detectado=utf-16  comentarios=['O bispo domina a diagonal.']      (ok)
utf8             detectado=utf-8   comentarios=['O bispo domina a diagonal.']      (ok)
```

O caso sem BOM falha por causa da propria E2. Texto ASCII em UTF-16-LE e uma
letra e um `\x00` alternados — e `\x00` **e** ASCII valido. Entao
`raw.decode('ascii')` passa, `detect_encoding` conclui "conteudo integralmente
ASCII, adoto UTF-8" e cada comentario sai com um NUL entre cada letra. Esse
texto vira a **chave de cache**, e a chave envenenada e gravada no
`traducoes.db` para sempre.

O caso com BOM so funciona por sorte: quem acerta e o `chardet`, que e importado
dentro de um `try/except ImportError`. Com ele ausente o mesmo arquivo cai no
`cp1252` e produz o mesmo lixo — confirmado forcando `chardet = None`:

```
utf16_com_bom    detectado=cp1252  comentarios=['\x00O\x00 \x00b\x00i\x00s\x00p\x00o ...']
```

Ha ainda uma assimetria menor no mesmo `detect_encoding`: o palpite do `chardet`
e devolvido **sem verificar que ele decodifica o arquivo**, enquanto o fallback
logo abaixo (`cp1252`, `latin-1`) so aceita o que decodificou. Quando o palpite
erra, `errors='replace'` na leitura injeta `U+FFFD` no conteudo — e esse
conteudo e o que `generate_translated_pgn` grava de volta, o que contraria G2 na
letra. Nas amostras que montei (turco, grego, russo, hebraico, shift-jis, big5) o
`chardet` nunca passou de 0,54 de confianca e o fallback salvou todas, entao nao
consegui disparar o caso — mas a protecao existir no ramo de baixo e faltar no de
cima nao tem justificativa.

Tres correcoes, todas em `detect_encoding`:

1. **BOMs de UTF-16/UTF-32 junto com a de UTF-8**, antes de tudo. Resolve o caso
   comum (Bloco de Notas do Windows salvando como "Unicode") sem depender do
   `chardet`. A ordem da tabela importa: `FF FE` (UTF-16-LE) e **prefixo** de
   `FF FE 00 00` (UTF-32-LE), entao a BOM longa e testada primeiro — na ordem
   ingenua, todo UTF-32-LE seria classificado como UTF-16.
2. **UTF-16 sem BOM pelos NUL intercalados**, antes do teste de ASCII puro (que
   ele passaria). O lado em que os NUL caem decide a variante: nas posicoes
   impares e little-endian, nas pares e big-endian. O limiar e 90%, e nao 100%,
   porque um PGN em UTF-16 com acentos tem alguns pares fora do bloco ASCII; a
   contagem do lado oposto precisa ser **zero**, o que impede confundir com um
   arquivo de byte unico que por acaso tenha um NUL.
3. **Verificar antes de aceitar.** Nenhum ramo devolve codificacao sem que
   `_decodes_completely` confirme o arquivo inteiro — inclusive a BOM, que e uma
   declaracao de quem gravou mas pode ser desmentida pelo conteudo.

Verificado nas sete codificacoes (UTF-8, UTF-8 com BOM, cp1252, UTF-16 LE/BE sem
BOM, UTF-16 com BOM, UTF-32), com texto acentuado, **com e sem `chardet`**: os 14
casos devolvem os mesmos comentarios.

Conferido por mutacao. Desligando as duas protecoes principais:

```
utf-16-le (sem chardet) foi lido como cp1252
  ['\x00O\x00 \x00b\x00i\x00s\x00p\x00o ...'] != ['O bispo domina a diagonal', ...]
AssertionError: 'cp1254' == 'cp1254'
```

A segunda linha e do teste do palpite nao verificado, que usa um `chardet` falso
respondendo `cp1254` com 0,99 de confianca para um arquivo que o cp1254 nao
decodifica. Foi a forma de disparar o caso que as amostras reais nao
disparavam — na analise, seis idiomas testados e o `chardet` nunca passou de
0,54 de confianca, entao o fallback sempre salvava.

**Garantia E4 (nova):** *a codificacao escolhida decodifica o arquivo inteiro.*
Nenhuma codificacao e adotada sem que a decodificacao completa tenha sido
verificada, e nenhum `U+FFFD` entra no texto lido por escolha errada de
codificacao. Fecha a lacuna que E1/E2/E3 deixavam para conteudo multibyte.

---

## 9. Idioma de origem e ferramentas destrutivas — CONCLUIDO (2026-07-28)

Tres pedidos do usuario, numa rodada so. Vale registrar a ordem em que foram
feitos, porque ela nao e a ordem em que aparecem aqui e explica uma decisao:
o pedido do filtro do editor (9.3) veio junto com o de declarar o idioma (9.2),
e foi ele que decidiu a forma do outro. Declarar o idioma so para mandar `sl=`
a API teria sido metade do trabalho e nao resolveria a queixa — que era **nao
misturar linguas na hora de revisar**.

### 9.1 Nao havia como zerar o banco nem o glossario

O programa tinha backup, restauracao, importacao e exportacao, e nenhuma forma de
recomecar do zero. Quem quisesse limpar o banco tinha de fechar o programa e
apagar o `traducoes.db` na mao — o que tambem apaga o `-wal` e o `-shm` se souber
que eles existem, e deixa o `pgn_tradutor_pro_settings.json` com rascunhos
apontando para ids que nao existem mais.

**A dificuldade nao e apagar, e perguntar.** As confirmacoes que o programa ja
tinha sao `messagebox.askyesno`, e elas bastam para o que e reversivel:
restaurar, importar, aplicar automaticas — todas tiram backup antes e podem ser
desfeitas voltando a ele. Zerar nao e dessa familia: o que se perde sao 201.607
traducoes ou 7.061 regras, e um "Sim" fica a um pixel do "Nao".

Por isso a confirmacao e **digitada** (`confirm_dialog.py`): o usuario escreve
`delete`, e ate entao o botao de apagar nao funciona. Nao ha como fazer isso por
engano, nem por um duplo clique que pegou o dialogo no caminho. Aceita-se
qualquer caixa e espaco nas pontas — quem digitou `DELETE ` decidiu tanto quanto
quem digitou `delete`, e recusar isso so daria um dialogo que diz nao sem
explicar por que.

**A regra e uma funcao pura**, `confirmation_accepted`, separada da janela: e ela
que decide se algo e apagado, e querer testa-la nao pode exigir abrir um
`Toplevel`.

**Tres decisoes que os testes protegem:**

- **O backup vem antes da pergunta**, e o caminho dele aparece na propria
  confirmacao. Custa 0,4 s e e a unica volta atras; deixa-lo para depois do
  "Apagar" significaria que uma falha entre a confirmacao e a copia apaga tudo
  sem rede. O pior caso desta ordem e uma copia a mais para quem desistiu, e a
  retencao S8 cuida dela.
- **Sem cancelamento no meio** (`allow_cancel=False`), pela mesma razao da
  restauracao: depois do `DROP TABLE` nao ha estado anterior para voltar, e um
  botao que nao pode ser honrado e pior do que nenhum botao.
- **O cache em memoria vai junto.** Ele tem precedencia sobre o banco: deixado
  como estava, a proxima traducao reaproveitaria exatamente o que o usuario
  acabou de mandar apagar — sem tocar no banco, entao nada apareceria como erro.

**Zerar as traducoes derruba as tabelas em vez de apagar as linhas.** Nao e
preferencia de estilo: cada `DELETE` dispara o gatilho que tira os termos daquela
linha do `comments_fts`, e seriam 201.607 gatilhos para produzir uma tabela
vazia. Derrubando a tabela, o `rebuild` do indice roda uma vez so, sobre nada. O
`VACUUM` no fim e o que devolve os 115 MB ao disco — "zerar o banco" que nao
libera um byte parece nao ter funcionado.

**Zerar o glossario e sincrono, e a assimetria e de escala.** Gravar uma lista
vazia num arquivo de 334 KB e reconstruir um indice sem regra nenhuma custa
milissegundos; uma barra de progresso para isso seria um piscar de janela. Ele
usa a mesma `save_glossary_entries` que salvar uma regra usa — nao ha caminho
especial —, com `create_backup=False` porque a copia ja foi feita antes de
perguntar. Duas copias identicas na pasta fariam a retencao descartar uma versao
mais antiga de verdade para caber.

Os dois botoes ficam em "Ferramentas", **em vermelho**, e nenhum roda com uma
traducao em andamento. A cor e o aviso; a confirmacao digitada e a defesa.

**Um achado da janela de verdade, que nenhum teste teria dado.** O `state= "disabled"` do CustomTkinter escurece o fundo padrao, mas sobre o vermelho
saturado do botao "Apagar" o resultado e quase o mesmo tom: as duas capturas —
com a palavra errada e com a certa — ficaram **indistinguiveis**. O botao
continuava inerte de verdade, entao nada estava quebrado; o problema e o que ele
comunica. Um botao que parece clicavel e nao faz nada le-se como "o programa
quebrou", e nao como "falta digitar a palavra". Passou a trocar de cor
explicitamente, e o teste afirma a cor alem do `state`.

**Conferido por mutacao**, doze maneiras de errar, todas pegas: o backup indo
para depois da confirmacao, a recusa apagando do mesmo jeito (nas duas
ferramentas), o cache sobrevivendo, o historico ficando para tras, as janelas
abertas nao sendo avisadas, a segunda copia em `backups/`, os dois botoes
trocados de lugar, zerar rodando durante uma traducao, o dialogo aceitando
qualquer texto, o botao nascendo habilitado, o botao parando de mudar de cor, e
o `command` confiando no estado do botao em vez de reconferir a palavra.

**Um teste meu que passava pelo motivo errado, e o motivo e do Tk.** O de
"fechar a janela e nao" chamava `destroy()` — que **nao** dispara o
`WM_DELETE_WINDOW`; so o gerenciador de janelas dispara. O dialogo entao devolvia
o `False` que ja era o padrao, e trocar o handler por um que respondesse "sim"
continuava passando. Refeito executando o script registrado no protocolo, como o
X da janela o executaria; entrou junto o `Esc`, que tinha o mesmo buraco.

**Verificado na janela de verdade**: com `apagar` digitado o botao fica cinza e o
banco continua com as 5 linhas; com `delete` ele fica vermelho, o banco vai a 0,
o cache em memoria esvazia e o backup esta em `backups/`. O mesmo para o
glossario, de 2 regras a 0.

### 9.2 A traducao adivinhava o idioma de origem, e o banco nao o guardava

`translate_text_chunk` mandava `sl=auto` desde sempre. Para um texto corrido isso
funciona; para um comentario de xadrez, que muitas vezes tem tres palavras
(`"Bien jugado"`, `"Ng5!"`, `"Nada"`), e pouco texto para adivinhar — e o palpite
errado produz uma traducao errada sem erro nenhum.

O problema maior, porem, e o que ficava no banco. A chave era `(comentario original, idioma de destino)`, entao **o mesmo texto vindo de duas linguas era
uma linha so**. `"Nada"` existe em espanhol e em portugues com sentidos
diferentes; traduzido uma vez a partir do espanhol, o italiano recebia aquela
traducao de volta pelo cache.

**Feito: o idioma de origem e declarado e entra na chave.** Um seletor na janela
principal, acima do de destino — a origem e a escolha que muda a cada pasta,
enquanto o destino costuma ser sempre o mesmo, e deixa-la embaixo de sete botoes
e o desenho que faz alguem traduzir um PGN italiano declarando espanhol.
"Detectar" e o primeiro e o padrao: quem nao mexer no seletor continua
exatamente onde estava. Garantia P1.

**A escolha entre "so metadado" e "entra na chave" foi do usuario**, e a segunda
e mais cara: exige reconstruir a tabela. Vale registrar o que isso significou.

**O SQLite nao remove restricao de tabela.** `UNIQUE(original_comment, target_language)` esta declarada NA tabela, e a unica saida e o procedimento que
a documentacao dele chama de "12 passos" — criar a tabela nova, copiar, derrubar
a antiga, renomear. Medido no `traducoes.db` real (201.607 linhas, 115 MB):

| etapa                                    | tempo           |
| ---------------------------------------- | --------------- |
| reconstruir a tabela                     | 3,4 s           |
| recriar os indices                       | 0,8 s           |
| `VACUUM`                               | 1,4 s           |
| **migracao completa, com o resto** | **7,0 s** |

Uma vez, na primeira abertura apos a atualizacao; a segunda leva 8,8 ms. O
`VACUUM` existe porque as paginas da tabela antiga ficam livres **no arquivo**:
sem ele o banco salta de 115 MB para 183 MB e so encolhe de volta com o uso.

**Os ids sao preservados de proposito, e e isso que paga o passo mais caro.**
`comments_fts` e um indice `external content` indexado por `rowid`. Se a copia
renumerasse as linhas, cada entrada do indice passaria a apontar para o texto de
outra — e a busca devolveria resultados errados, sem erro nem aviso. Copiando o
`id` explicitamente, o indice continua valendo como estava: os 8.409 acertos de
`"bispo"` antes e depois sao os mesmos, e cruzam com as mesmas linhas.

**"Nao informado" e uma string vazia, e nao `NULL`**, e isto e o tipo de detalhe
que so aparece quando alguem pergunta: **num indice UNIQUE o SQLite considera
todo `NULL` diferente de qualquer outro, inclusive de outro `NULL`**. Com `NULL`
ali, a chave deixaria de valer justamente para as 201.607 linhas legadas — cada
execucao inseriria de novo os mesmos comentarios, sem nada acusar. Ha teste so
para isso.

**A adocao e o que impede a mudanca de cobrar o cache inteiro de novo.** As
linhas existentes ficaram sem idioma de origem. Sem mais nada, a primeira
execucao que dissesse "estes PGN estao em espanhol" nao acharia nenhuma delas e
mandaria as 201.607 traducoes de volta para a API. `adopt_unknown_source_language`
rotula, antes de carregar o cache, as linhas **daqueles comentarios** que ainda
nao tem origem. Garantia P2.

Uma linha sem idioma de origem nao contradiz o que o usuario acabou de declarar:
ela so nao sabia. Tres limites que os testes fixam:

- **so alcanca quem nao tinha idioma nenhum** — reetiquetar uma linha que ja diz
  "veio do espanhol" seria apagar uma declaracao do usuario com outra;
- **`UPDATE OR IGNORE`**, porque a adocao pode esbarrar na propria chave: se ja
  existe uma linha no par de destino, a sem rotulo permanece como esta em vez de
  derrubar a execucao com um `IntegrityError`;
- **"Detectar" nao adota nada** — nao e uma declaracao.

Custa 74 ms para uma pasta de 2.000 comentarios, contra minutos de rede na mesma
execucao.

**Antes da carga do cache, e nao depois**, e a ordem e o item inteiro: depois, a
adocao chegaria tarde — o cache ja teria vindo vazio e a execucao ja teria
decidido pagar tudo de novo.

**O par vai junto para o resto do programa:** o CSV ganhou a coluna
`source_language` (opcional na leitura, como a `priority` do glossario em 1.5),
as estatisticas passaram a agrupar por par — `"pt: 12.000"` esconde justamente a
informacao que o usuario passou a pedir —, e o registro de falhas guarda o par
inteiro, porque reprocessar com outra origem gravaria as traducoes que faltam
numa gaveta diferente da dos comentarios que ja deram certo.

**Uma mutacao sobreviveu, e ela apontou um teste meu que nao testava nada.**
"a API volta a receber `sl=auto` sempre" passava na suite inteira. O motivo: os
testes do worker substituem `translate_text`, entao nunca chegam a
`translate_text_chunk`, que e onde o `sl` e montado. Eu tinha verificado que o
worker **passa** o idioma adiante e nada verificava que a camada de rede **o
usa**. Entraram tres testes na camada certa, incluindo um que exige que o idioma
sobreviva a divisao de um comentario longo em varias requisicoes — perde-lo entre
a primeira e a segunda daria metade da traducao declarada e metade adivinhada.

### 9.3 O editor misturava os pares de idiomas na mesma lista

A queixa que originou o 9.2, e a que decidiu a forma dele. O editor lista por
idioma de **destino**, herdado da janela principal, e dentro dele convivem as
traducoes vindas de todas as linguas. Revisar uma traducao do espanhol achando
que e do italiano nao produz erro nenhum — produz uma revisao errada, e nada na
tela ajuda a perceber.

**Feito: dois seletores proprios, origem e destino.** Garantia R9. Sao menus, e
nao botoes segmentados como o filtro de status: oito idiomas lado a lado nao
cabem na largura do painel, e a forma segmentada so se paga quando todas as
opcoes ficam visiveis de uma vez.

**Os dois nao sao simetricos, e cada assimetria tem razao:**

|                   | opcoes                                    | lembrado |
| ----------------- | ----------------------------------------- | -------- |
| **Origem**  | Todos · Nao informado · os sete idiomas | sim      |
| **Destino** | os sete idiomas                           | nao      |

"Todos" so existe na origem porque a janela edita as traducoes de **um** destino:
o rascunho, o titulo e a aplicacao das regras automaticas sao todos por destino.
E o destino nao e lembrado de proposito — guarda-lo faria quem marcasse "Ingles"
na janela principal abrir o editor em portugues, sem nada na tela explicando de
onde aquilo veio.

**"Nao informado" nao pode ser sinonimo de "Todos"**, e a distincao e a coisa
mais facil de errar aqui: `None` nao filtra, `""` filtra pelas linhas cuja origem
ninguem declarou. Confundi-los faz "Nao informado" mostrar a tabela inteira — e
num banco em que 201.607 de 201.607 linhas estao nesse balde, isso pareceria
funcionar por muito tempo. Ha teste so para a diferenca, nas tres camadas.

**Trocar de par grava a edicao aberta antes**, e nao depois: a linha pertence ao
par antigo e sai da lista na troca, entao gravar depois seria gravar contra um
item que a janela nao mostra mais. E volta para a primeira pagina — a pagina 40
do par anterior nao quer dizer nada no novo.

**"Aplicar automaticas" ficou restrito ao filtro ativo.** Com "Origem: Espanhol"
na tela, reescrever tambem as traducoes das outras linguas seria uma alteracao em
massa que o usuario nao pediu nem consegue ver.

**Um custo que a medicao pegou, e que teria sido uma regressao silenciosa da
garantia R5.** Com o filtro de origem ativo, o resumo de status subiu de 34,9 ms
para **78,7 ms** no banco real: o indice de cobertura
`(target_language, verified, quality_warning)` deixa de cobrir a consulta quando
`source_language` entra no `WHERE`, e a agregada volta a tocar a tabela. Entrou
`idx_comments_pair_counts`, com a origem dentro:

|                                               | antes do indice   | depois            |
| --------------------------------------------- | ----------------- | ----------------- |
| resumo, sem filtro de origem                  | 34,9 ms           | 34,5 ms           |
| resumo, origem = "nao informado" (as 201.607) | **78,7 ms** | **35,9 ms** |
| resumo, um par sem nenhuma linha              | —                | 0,0 ms            |
| pagina 1000, com filtro de origem             | —                | 6,1 ms            |

Filtrar voltou a custar o mesmo que nao filtrar, que era o ponto de R5.

**Um teste meu que passava pelo motivo errado, e e o mesmo padrao que esta
revisao ja registrou tres vezes.** O de "trocar de par volta para a primeira
pagina" montava quatro linhas ao todo — com uma pagina so, `clamp_page` ja
devolvia zero sozinho, e **remover a linha que zera a pagina nao mudava nada**.
Refeito com mais de uma pagina em cada par: agora a mutacao quebra, e o teste
exige tambem que a lista nao traga linha do par anterior.

**Conferido por mutacao**, quinze maneiras de errar entre 9.2 e 9.3, todas pegas:
a origem desconhecida virando `NULL`, a migracao so acrescentando a coluna, a
reconstrucao renumerando os ids, `save_translation` voltando a procurar so por
`(original, destino)`, o filtro tratando `""` como ausencia de filtro, a adocao
alcancando outra origem, a adocao sem `OR IGNORE`, "detectar" adotando tudo, o
cache ignorando a origem, verificar iguais atravessando origens, a API voltando
ao `sl=auto`, o worker nao adotando e nao gravando a origem, o registro de falhas
perdendo o par, o editor nao passando o filtro adiante, trocar de par nao
gravando a edicao aberta nem voltando a primeira pagina, e o filtro deixando de
ser lembrado entre sessoes.

**Uma "sobrevivente" que nao era, e a causa vale mais que o caso.** A mutacao
"verificar iguais volta a atravessar origens" passava na rodada completa e
falhava quando rodada sozinha — o oposto do que uma flutuacao de teste costuma
parecer. Nao era o teste: era o **`.pyc`**. O script mutava `database.py` varias
vezes em sequencia, e o interpretador do subprocesso reaproveitava o bytecode
compilado da versao anterior, entao a mutacao nunca chegava a rodar. Com
`PYTHONDONTWRITEBYTECODE=1` e uma conferencia de que o arquivo mutado esta mesmo
em disco, as 31 mutacoes sao pegas de forma deterministica.

E o mesmo aviso que o item 5.4 registrou por outro caminho: **uma mutacao que
"passa" so conta depois de confirmado que ela foi aplicada.** La o script abortou
por ancora ambigua; aqui ele aplicou e o Python ignorou.

**Verificado na janela de verdade**, com cinco traducoes semeadas em quatro
pares:

```
ao abrir (Origem=Todos, Destino=Portugues) : 4 linhas
Origem=Ingles                              : 2 linhas  · "Pagina 1/1 · 2 traducoes"
Origem=Nao informado                       : 1 linha
Origem=Espanhol                            : 1 linha
Destino=Frances, Origem=Todos              : 1 linha   · titulo "Editar traducoes (fr)"
```

---

## 10. As letras das pecas trocavam de peca na traducao — CONCLUIDO (2026-07-28)

Pedido do usuario, e ele veio com o diagnostico junto: em portugues e espanhol
converter `K` e `R` **em sequencia** nao funciona. Vale escrever o mecanismo,
porque a formulacao exata muda a solucao.

| peca   | en | pt | es | fr | it | de | ru   |
| ------ | -- | -- | -- | -- | -- | -- | ---- |
| Rei    | K  | R  | R  | R  | R  | K  | Кр |
| Dama   | Q  | D  | D  | D  | D  | D  | Ф   |
| Torre  | R  | T  | T  | T  | T  | T  | Л   |
| Bispo  | B  | B  | A  | F  | A  | L  | С   |
| Cavalo | N  | C  | C  | C  | C  | S  | К   |

O `R` do ingles e Torre e o `R` do portugues e Rei. Aplicando `K -> R` e depois
`R -> T`, a primeira regra produz `R` a partir de `K`, e a segunda **nao tem como
distinguir** esses `R` dos que ja eram `R`: transforma os dois em `T`. O usuario
descreveu isso como um problema de ordem; nao e — inverter a ordem so troca qual
peca e destruida. **O problema e a sequencia.** Numa passagem so, `Kf1` vira
`Rf1` e `Rf1` vira `Tf1`, e nao ha ambiguidade nenhuma.

E o mesmo mecanismo da garantia S4 do glossario ("texto substituido e final"), o
que explica por que isto nao podia ser resolvido com regras: S4 congela o trecho
ja substituido dentro de UMA aplicacao, mas um glossario nao sabe que `Kf1` e
`Rf1` sao a mesma decisao tomada duas vezes.

### 10.1 A metade que o mapeamento nao resolve

Feito o mapeamento numa passagem, sobra o que o usuario tambem anotou: **o
tradutor e inconstante**. As vezes traduz o lance, as vezes deixa, as vezes erra.
Medido no endpoint real, ingles para portugues, com o idioma de origem declarado:

```
EN      White must play Kf1 here. After Rxe4+ Nf3 the rook is lost, and e8=Q wins.
Google  As brancas devem jogar Rf1 aqui. Depois de Txe4+ Cf3 a torre e perdida e e8=Q vence.

EN      The move Rd1 doubles the rooks; Kg2 is slow.
Google  O movimento Rd1 dobra as torres; Kg2 e lento.
```

A primeira amostra sai quase certa e erra so a promocao. A segunda erra as duas,
e a primeira delas do pior jeito possivel: `Rd1` **parece** notacao portuguesa
valida e nomeia a peca errada — uma Torre lida como Rei. Nada na traducao
denuncia, e o proximo leitor e um enxadrista confiando no texto.

Olhando so a traducao, `Rd1` (Torre que ficou para tras) e `Rf1` (Rei ja
traduzido) tem exatamente a mesma cara. **Quem distingue e o comentario
original**, e ele so e legivel porque o idioma de origem passou a ser declarado
(secao 9.2). Os dois itens sao do mesmo dia por acaso; que o segundo dependa do
primeiro, nao.

### 10.2 A ancora, que e o que torna isto possivel

Um lance tem uma parte que **nao muda de idioma**: casa, captura, desempate,
xeque, o `=` da promocao. `Kf1` e `Rf1` diferem so na letra; `f1` e `f1` em toda
lingua. Entao um lance do original e um lance da traducao com a mesma ancora sao
o mesmo lance, e a letra e exatamente o que se corrige.

Isso mantem o escopo minusculo, e o escopo e a seguranca do item: **a funcao so
reescreve a letra da peca de um lance que ja estava la**. Nunca insere um lance,
nunca apaga um, nunca mexe em lance de peao (`e4`, `exd5`) nem em roque
(`O-O`) — que nao tem letra para trocar. O pior resultado possivel dela e deixar
um lance como o tradutor escreveu.

**Quando a ancora empata**, o desempate e a ordem: `"Rf1 ou Kf1"` da dois lances
para a casa `f1`, e o tradutor preserva a ordem porque traduz o texto sem
reordena-lo. Se nem a ordem resolver — contagens diferentes dos dois lados —,
**nada e tocado**. Corrigir para o lance errado e pior do que nao corrigir.

**A leitura dos dois lados e assimetrica, de proposito.** O original e lido so no
alfabeto declarado: ali a letra e a informacao, e aceitar mais alfabetos
devolveria a ambiguidade que declarar o idioma veio resolver. A traducao e
varrida com **todas** as letras conhecidas: ali a letra e ruido, e o tradutor
chega a devolver notacao inglesa num par que nao passa pelo ingles — um `Kf1`
numa traducao es -> pt nem seria reconhecido como lance por um alfabeto restrito
aos dois idiomas.

Sem idioma de origem declarado a correcao nao roda, e o log diz isso. Corrigir a
partir de um palpite seria trocar um erro do tradutor por um erro do programa.

### 10.3 A tabela do usuario tinha um erro, e ele era fatal para o russo

A tabela que veio com o pedido dava `К` para o Rei e `К` para o Cavalo — a mesma
letra. A notacao russa usa **`Кр`** no rei (Король) justamente porque Rei e
Cavalo (Конь) comecam igual. Com a tabela como veio, a inversao `letra -> peca`
deixaria de ser uma bijecao e **todo lance de rei seria lido como lance de
cavalo**. Ha teste que exige que nenhum idioma repita uma letra, entao um erro
desses numa lingua futura quebra a suite em vez de aparecer numa traducao.

O `Кр` e a unica letra de duas posicoes da tabela, e ele obrigou a alternancia do
regex a ir da mais longa para a mais curta.

### 10.4 O que a verificacao por mutacao mostrou

Treze mutacoes, e **quatro sobreviveram na primeira rodada**. Nenhuma das quatro
era "esqueci de testar": as quatro diziam alguma coisa sobre o codigo.

**Duas eram testes meus que nao testavam nada**, e as duas pelo mesmo motivo — o
cenario nao continha o caso que a guarda protege:

- *Lances de peao entrando como candidatos.* Todos os meus cenarios tinham uma
  ancora por lance, entao "corrigir" um peao o substituia por ele mesmo. O caso
  que expoe a guarda e outro: o original tem so `Kf1`, a traducao tem `Kf1` **e**
  um `f1` solto — com peoes como candidatos, os dois casam a ancora `f1`, o `f1`
  solto recebe `Rf1` e **o texto ganha uma peca que nao estava la**.
- *A fronteira de palavra da esquerda.* A palavra que eu tinha escolhido
  (`Rebe5x`) ja era rejeitada pelo resto do padrao, entao a fronteira nunca era
  exercitada. Refeito com um lance colado no fim de uma palavra, que e
  sintetico e esta dito no teste: o texto real que dispara isso — um erro de
  digitacao, uma colagem na importacao — e justamente o que nao da para
  enumerar.

**Uma era redundancia no codigo, e nao no teste.** "O original passa a ser lido
com todos os alfabetos" nao quebrava nada porque havia **duas** guardas para a
mesma decisao: um regex restrito ao alfabeto de origem e uma checagem na
conversao. As duas eram equivalentes, ou seja, uma delas nao estava protegida por
nada — a situacao que o item 3.6 corrigiu no glossario. Agora a decisao mora em
`_explained_by`, num lugar so, e mexer nela quebra.

**Uma era um comentario meu que estava errado.** Eu tinha escrito que a
alternancia do regex ir da letra mais longa para a mais curta e o que faz o `Кр`
funcionar. Nao e: com a ordem ingenua o regex casa `К`, tenta seguir com `рf1` no
lugar da casa, falha e **retrocede** para `Кр`. A ordem so passaria a decidir se a
tabela ganhasse duas letras em que a mais curta tambem levasse a um lance valido.
A ordenacao ficou — e barata e protege esse futuro —, mas o comentario passou a
dizer o que ela e: precaucao, e nao o mecanismo.

### 10.5 O que a medicao no banco real acrescentou

Perguntado se faltava algo, medi a correcao contra as 201.607 traducoes ja
gravadas (sobre o backup, em modo somente leitura — abrir o banco de trabalho
dispararia a migracao, e isso nao e coisa de uma medicao):

|                                  |                        |
| -------------------------------- | ---------------------- |
| traducoes com destino`pt`      | 201.603                |
| com lance de peca no original    | 26.691 (13,2%)         |
| **que a correcao mudaria** | **4.144 (2,1%)** |

Duas coisas sairam dai.

**A primeira e um defeito que a medicao expos.** O glossario do usuario tem uma
regra automatica `('×', 'x')`, entao o original guarda `N×d4` e a traducao chega
com `Nxd4`. O regex so entendia `x`: aqueles lances **nem eram reconhecidos como
lance**, e passavam sem correcao — o modo de falha mais silencioso possivel,
porque nao havia lance nenhum para a funcao ver. Sao 198 capturas com `×` e 7 com
`:` contra 4.316 com `x`. Aceitos os tres e normalizada a ancora, a contagem foi
de 4.108 para 4.144.

**A segunda e uma simplificacao que o `×` obrigou.** A versao anterior reescrevia
o lance com o corpo do ORIGINAL, o que devolveria o `×` ao texto — desfazendo em
silencio a regra do glossario. Agora o corpo sai da TRADUCAO e so as letras sao
trocadas, que e o que a garantia P3 sempre disse em palavras. Ficou mais simples
e mais fiel ao que estava escrito.

**Uma mutacao voltou a sobreviver depois dessa mudanca**, e o motivo e o de
sempre: a guarda de forma nova (um lado com letra, o outro sem) passou a cobrir o
cenario do teste que protegia a exclusao dos peoes, e os dois deixaram de ser
distinguiveis. O caso que os separa e outro — ancora disputada por duas pecas
mais um peao solto na traducao, tres candidatos contra dois esperados, e ai
**nada** e corrigido. Refeito assim, as dezesseis mutacoes sao pegas.

Corrigidos os quatro, as treze mutacoes sao pegas, incluindo as duas do worker
que importam mais: gravar o texto de antes da correcao, e corrigir so no caminho
do lote e nao no fallback individual — essa ultima daria uma execucao cujo
resultado depende de a rede ter respondido alinhada, que e o pior tipo de
inconsistencia porque aparece so as vezes.

---

## 11. A correcao de lances nao alcancava o banco ja gravado — CONCLUIDO (2026-07-29)

A secao 10 conserta os lances **na hora da traducao**. Perguntado se faltava algo,
medi a mesma correcao contra as 201.607 traducoes que ja estavam no banco:

|                               |                        |
| ----------------------------- | ---------------------- |
| traducoes com destino`pt`   | 201.603                |
| com lance de peca no original | 26.691 (13,2%)         |
| **com a letra errada**  | **4.144 (2,1%)** |

Ou seja: o trabalho da secao 10 valia so para o que viesse dali em diante. Para o
acervo existente a escolha era ruim dos dois lados — restaurar o backup traz os
4.144 erros de volta, nao restaurar significa repagar a API por 201.607
traducoes.

**Nao dava para corrigir sem antes rotular.** A correcao le os lances do
comentario original, e para isso precisa saber em que alfabeto ele esta. As
linhas legadas estavam como "origem nao informada", e a adocao (P2) so acontecia
dentro de uma execucao de traducao — uma linha so seria rotulada quando o
comentario dela reaparecesse num PGN, o que para a maioria significa nunca.

Por isso a ferramenta faz as duas coisas, e na mesma transacao: **rotular e
corrigir sao a mesma decisao do usuario, tomada uma vez**. Desistir desfaz as
duas; uma metade aplicada — linhas rotuladas com os lances ainda errados — seria
um estado que ninguem pediu e que nao se distingue do correto.

**O idioma sai dos seletores da janela principal**, e nao de um dialogo proprio.
Nao ha uma segunda pergunta a fazer: "de que idioma vieram estas traducoes" e
exatamente o que aqueles controles significam no resto do programa. "Detectar" e
recusado com o motivo dito — sem saber se o `R` do original e Rei ou Torre,
corrigir seria chutar.

Medido sobre uma copia do banco real:

| etapa                   | tempo  |
| ----------------------- | ------ |
| previa (201.603 linhas) | 4,4 s  |
| aplicacao               | 14,6 s |

201.607 linhas rotuladas, 4.144 traducoes alteradas, **4.800 lances corrigidos**,
4.144 registros de historico, e as 1.372 verificadas continuaram verificadas.
Rodar de novo encontra zero.

### 11.1 O defeito que os testes acharam antes do usuario

A primeira versao tinha **previa e aplicacao discordando do escopo**. A previa
analisava o par declarado — `(en, pt)` —, mas as linhas legadas ainda estavam
como "origem nao informada" e so entravam nesse par durante a aplicacao.
Resultado: a previa dizia *"nenhuma traducao precisa de correcao"* exatamente no
caso para o qual a ferramenta existe, e o usuario nunca chegaria a ver o botao
funcionar.

E a terceira aparicao da mesma classe nesta ROADMAP — dois criterios em dois
lugares, como nos itens 2.8 e 3.6 — e a correcao foi a mesma: um `WHERE` so,
montado num lugar, usado pelas duas.

O que o encontrou foi um teste que exercita a ferramenta inteira sobre linhas sem
rotulo, que e o estado real do banco. Testando so as funcoes de banco com linhas
ja rotuladas, ele nao apareceria.

### 11.2 Quatro mutacoes sobreviveram, e cada uma disse uma coisa diferente

**Duas eram lacunas nos testes:**

- *A aplicacao ignorando as linhas sem rotulo.* Ela rotula antes de corrigir,
  entao no caminho normal o escopo mais largo nao muda nada. O caso em que muda e
  a linha que **nao pode** ser rotulada: a rotulagem usa `UPDATE OR IGNORE`, e
  uma linha cujo par de destino ja esta ocupado permanece sem rotulo. Sem o
  escopo largo ela ficaria com os lances errados para sempre, indistinguivel das
  outras na tela.
- *O editor voltando a nao dizer de que idioma a linha veio.* Nenhum teste olhava
  o texto da barra de status.

**Uma era um erro de ordem no proprio codigo**, e so apareceu porque o teste novo
olha a **tela** e nao o estado: `select_index` pinta a selecao — o que ja atualiza
o rotulo — e so depois chama `load_item`, entao a barra anunciava o par da linha
ANTERIOR. Informacao errada com cara de certa, que e o pior tipo.

**Uma nao era um defeito, e vale registrar em vez de contornar.** Trocar
`analyze_...` por `apply_...` dentro da previa nao quebra nada — porque quem
garante que a previa nao grava nao e o nome da funcao, e sim o chamador nao
comitar. E uma propriedade real, so que de outro lugar; forcar um teste para ela
afirmaria implementacao em vez de comportamento.

Corrigidas as tres primeiras, as catorze mutacoes sao pegas.

### 11.3 O cabo solto que sobrou da secao 9

O editor buscava `source_language` e `target_language` em `fetch_translation_by_id`
— com um comentario dizendo que era "para o editor mostrar o par" — e nunca
exibia. Com "Origem: Todos" ativo a lista mistura pares de proposito, e nada na
tela dizia de qual deles vinha o texto em revisao. A barra de status passou a
nomea-lo, e o dado que ja estava sendo lido finalmente chega a algum lugar.

---

## 12. A janela principal esquecia a escolha que mais importa — CONCLUIDO (2026-07-29)

Nada na janela principal era lembrado: idioma de origem, idioma de destino,
caminho e "processar subdiretorios" voltavam ao padrao a cada abertura.

Para tres deles isso e so incomodo. Para o **idioma de origem** e outra coisa, e a
assimetria e o item: ele decide o `sl=` da API e **liga a correcao das letras dos
lances** (P3), e o padrao dele — "Detectar" — e exatamente o valor que deixa as
duas desligadas. Ou seja, o campo que mais muda o resultado voltava sozinho para
a posicao que desliga a qualidade.

E o modo de falha e silencioso: uma execucao feita assim nao acusa nada. O PGN
sai, o banco enche, e o `Rd1` que devia ser `Td1` so aparece para quem for ler o
comentario mais tarde — provavelmente jogando.

O gatilho foi o usuario dizer que ia recomecar o banco do zero. Uma retraducao de
201 mil comentarios com o seletor no padrao produziria de novo, de uma vez, todo o
problema que as secoes 10 e 11 acabaram de resolver.

**Grava no clique, e nao ao iniciar a traducao.** Quem escolhe o idioma e fecha o
programa sem traduzir escolheu do mesmo jeito, e perder isso reproduziria o mesmo
problema em menor escala. A gravacao passa por `update_settings` (rele o disco
antes de escrever) porque os rascunhos das janelas de edicao vivem no mesmo
arquivo — garantia R4, e o defeito que ela impede e o usuario perder uma edicao
por ter clicado num radio na outra janela.

A validacao da leitura e a parte que da para errar, e por isso ela e uma funcao
pura: o arquivo e JSON editavel a mao e sobrevive a versoes do programa. Um idioma
que saiu da lista, um tipo errado ou a secao inteira corrompida caem no padrao, em
vez de deixar um seletor num estado que ele nao sabe exibir.

**Duas das dez mutacoes sobreviveram, e as duas eram comentarios meus que
afirmavam demais** — nenhuma era teste faltando:

- *Ligar a gravacao antes da restauracao.* Eu tinha escrito que a ordem evita o
  programa escrever de volta o que acabou de ler. Evita — e isso hoje **nao muda
  nada**, porque o que seria escrito e identico ao que foi lido. A ordem vale para
  o dia em que a leitura ganhar qualquer normalizacao.
- *A string vazia como valor valido.* O `origem == ""` e explicito de proposito,
  mas o padrao tambem e vazio: recusar a string vazia cairia no mesmo lugar. Ele
  vale pelo dia em que o padrao mudar, e porque sem ele um leitor conclui, errado,
  que "Detectar" nao pode ser lembrado.

Nos dois casos a guarda ficou — sao baratas e protegem um futuro — e o comentario
passou a dizer o que ela e: precaucao, e nao mecanismo. E a terceira vez nesta
ROADMAP que uma mutacao sobrevivente acusa um comentario em vez de um teste, e
vale como criterio: **quando a mutacao passa, a primeira suspeita e o que o codigo
diz de si mesmo.**

**Garantia M1 (nova):** *a janela principal reabre no que foi escolhido.*

### 12.1 Um caractere invisivel apagava a memoria do programa — CONCLUIDO (2026-07-29)

Achado **conferindo o executavel antes de publicar a v0.2.1**, e nao pelos
testes. Semeei um `pgn_tradutor_pro_settings.json` ao lado do `.exe` para
verificar a garantia M1 no binario empacotado, reabri, e a janela veio com os
padroes. A primeira suspeita foi a M1; a causa era outra e bem pior.

O arquivo que eu escrevi saiu do PowerShell com `Out-File -Encoding utf8`, que no
Windows PowerShell 5.1 grava UTF-8 **com BOM**. E `load_settings` abria com
`encoding="utf-8"`:

```
tem BOM utf-8: True
json.loads(...)  -> JSONDecodeError: Unexpected UTF-8 BOM
load_settings()  -> {}
```

O `except (FileNotFoundError, json.JSONDecodeError, OSError)` capturava e devolvia
`{}`, e o programa seguia como se nao houvesse configuracao nenhuma. **Tres bytes
invisiveis no inicio do arquivo apagavam de uma vez** os rascunhos nao salvos das
janelas de edicao (garantia R4), a lista de arquivos que ficaram devendo (T4), o
modo de busca, o tamanho da fonte, a posicao dos divisores e as escolhas da
janela principal (M1).

**E a perda era definitiva.** Nada avisa — a degradacao para `{}` e exatamente o
comportamento certo para um arquivo ausente —, e a proxima gravacao escreve um
arquivo novo sem nada daquilo. O usuario descobriria ao perder uma edicao que
achava salva.

O acidente do PowerShell nao e o cenario; e so o que o reproduziu. O arquivo e
JSON e existe para ser editavel a mao, e o Bloco de Notas do Windows grava UTF-8
com BOM. Qualquer edicao manual das configuracoes zerava as configuracoes.

**A correcao e uma palavra**: `utf-8-sig` na leitura, `utf-8` na gravacao —
aceita-se o BOM, nao se escreve um. E a mesma assimetria que a leitura de CSV
deste programa ja usava, e o mesmo principio das garantias E3/E4 para os PGN. O
`UnicodeDecodeError` entrou junto no `except`: um arquivo que nem seja texto
levanta ele, e nao `JSONDecodeError`.

**Duas licoes, e a segunda vale mais que o bug:**

- Um `except` largo com uma degradacao razoavel esconde a diferenca entre "nao ha
  arquivo" e "ha um arquivo e eu nao sei le-lo". As duas viram `{}`. E o mesmo
  desenho que a garantia S5 corrigiu no glossario, e que E4 corrigiu na deteccao
  de codificacao; aqui ele sobreviveu porque o caminho parecia trivial demais
  para ter modo de falha.
- **Foi a verificacao do binario que achou.** Os 619 testes passavam, e passariam
  para sempre: nenhum deles escrevia um arquivo de configuracoes que nao tivesse
  sido escrito pelo proprio programa. Conferir o executavel antes de publicar
  deixou de ser cerimonia duas vezes seguidas — na v0.2.0 achou o botao
  indistinguivel, aqui achou isto.

**Garantia M2 (nova):** *um BOM no arquivo de configuracoes nao apaga nada.*

---

## 13. A traducao corrompe o que nao e prosa — CONCLUIDO (2026-07-29)

O desenho do programa divide o PGN em dois mundos: fora de `{...}` nada e
tocado (e a garantia N1 e a base de tudo), dentro de `{...}` tudo era texto a
traduzir. So que dentro do comentario vivem coisas que nao sao texto: as
anotacoes de maquina do Lichess e do ChessBase (`[%clk 0:05:30]`,
`[%eval +0.35]`, `[%cal Ra1h8]`, `[%csl Gd4]`), NAGs (`$14`), simbolos de
avaliacao (`+-`, `?!`, `∞`) e numeros de lance. O pipeline nao tinha o conceito
de "token que nao se traduz" — nenhuma mascara, protecao ou verificacao — e
dois desses tokens eram corrompidos de forma deterministica, **antes mesmo de a
API entrar**.

O banco de desenvolvimento nao tem nenhum `[%...]` (a amostra veio de livro), e
por isso o problema nunca apareceu em uso. Mas PGN de Lichess e chess.com — a
fonte mais comum de material hoje — carrega essas anotacoes em quase todo
comentario, e a primeira pasta vinda de la seria corrompida em silencio.

O item entrou pendente e foi concluido no mesmo dia. O que cada metade ganhou
esta nas subsecoes; a verificacao esta na 13.7.

### 13.1 A correcao de lances reescreve as setas coloridas

`_move_pattern` casa `Ra1h8` como um lance de Torre: `R` + `a1` + `h8` formam
`peca + casa + casa`, e o `]` seguinte nao e `\w`, entao a fronteira fecha. Mas
em `[%cal Ra1h8]` o `R` e o codigo da cor **vermelha** (Red), nao uma peca. Os
codigos de cor do Lichess sao `R`, `G`, `Y`, `B` — e `R` e `B` colidem com
Torre e Bispo do ingles.

Confirmado nesta maquina com a funcao real, en -> pt:

```
fix_move_notation('[%cal Ra1h8] good plan', '[%cal Ra1h8] bom plano', 'en', 'pt')
  -> ('[%cal Ta1h8] bom plano', 1)      # seta vermelha destruida
fix_move_notation('[%csl Rd4] weak square', '[%csl Rd4] casa fraca', 'en', 'pt')
  -> ('[%csl Td4] casa fraca', 1)       # circulo vermelho destruido
```

Nao e caso de borda probabilistico: o original e a fonte da ancora, entao o
pareamento e sempre 1 para 1 e a troca **sempre** acontece. `G` e `Y` escapam
por sorte — nao sao letra de peca em idioma nenhum da tabela.

Isso feria o que a garantia P3 diz de si mesma — "o pior resultado possivel
dela e deixar um lance como o tradutor escreveu" — porque aqui o pior resultado
era outro: reescrever uma anotacao que nunca foi lance. E a ferramenta
"Corrigir Lances" (P4) aplicava a mesma corrupcao **em massa e
retroativamente**, inclusive sobre linhas que o usuario ja verificou (o
`verified` nao e rebaixado, de proposito — a decisao certa para lances virava a
errada para setas).

**Feito:** `chess_notation` ganhou a exclusao dos spans `[%...]`
(`COMMAND_TAG_RE`), aplicada **nos dois lados e pelo mesmo motivo em cada um**:
no original, um `[%cal Rd4d8]` viraria uma ancora esperada falsa
(`extract_moves`); na traducao, e o proprio texto que era reescrito (o filtro
de candidatos em `fix_move_notation`). Como a ferramenta em massa do banco
passa por estas mesmas funcoes, as duas portas fecham juntas — e um lance de
verdade que divida o comentario com uma anotacao continua sendo corrigido, o
que tem teste proprio.

### 13.2 O achatamento quebra `[%eval]` e todo decimal

`flatten_comment` insere espaco depois de `.`, `!` e `?` quando o proximo
caractere e `\w` — **e digito e `\w`**. Confirmado nesta maquina:

```
'[%eval +0.35]'   -> '[%eval +0. 35]'
'2.5 pawns up'    -> '2. 5 pawns up'
'14.Bxf7+ wins'   -> '14. Bxf7+ wins'
```

O `[%eval +0.35]` era destruido **antes de qualquer traducao**, e o texto
corrompido era tres coisas ao mesmo tempo: a chave do cache, o que ia para a
API e o que voltava para o PGN gerado. Nao havia como recuperar depois.

**Feito, nas duas metades.** O achatamento deixou de inserir espaco quando o
ponto esta **entre digitos** — e so nesse caso: `14.Bxf7` continua ganhando o
espaco de sempre (o que segue o ponto e letra), `End.Next` idem, e ha teste
fixando que o comportamento antigo continua onde ele estava certo.

A outra metade e que a correcao **muda a chave de cache**: um comentario com
decimal reachatado deixaria de casar com a linha ja gravada e seria pago de
novo a API. A migracao de dados entrou como **schema 5** — a primeira versao do
schema que nao muda coluna nenhuma — e colapsa `digito. digito` nas chaves
existentes, uma vez, na primeira abertura:

- **So na transicao 4 -> 5, nunca de novo.** Corrigido o achatamento, o espaco
  deixa de ser assinatura dele: um `0. 5` gravado dali em diante e um espaco
  que estava no PGN do usuario, e colapsa-lo seria reescrever texto dele. Ha
  teste para os dois lados — a chave antiga colapsa no upgrade, a nova
  sobrevive a reaberturas.
- **Conflito deixa a linha antiga como esta.** Se a chave colapsada ja existe
  no par, fundir seria destruir uma traducao (possivelmente revisada) para
  desduplicar um cache. O preco e uma linha que nunca mais casa com arquivo
  nenhum — peso morto, nao erro.
- O `quality_warning` da linha alterada e reavaliado (R6), os gatilhos do FTS
  mantem o indice em dia (a migracao roda depois deles de proposito), e
  `updated_at` nao e tocado — nada aqui e edicao de traducao.

### 13.3 Tudo dentro do comentario ia cru para a API

`[%clk]`, NAGs, simbolos: nenhum filtro antes do envio. O Google pode traduzir
`eval`, quebrar um colchete, reformatar `+-` como `+ -` ou absorver `?!` na
pontuacao. Nada conferia a volta.

**Feito: mascara com restauracao verificada** (`annotation_mask.py`, puro como
`chess_notation` — sem Tk, sem banco). Cada anotacao `[%...]` vira um sentinela
`⟦n⟧` antes do envio e volta byte a byte depois — os bytes voltam identicos por
construcao, porque o texto original do span nunca saiu da maquina; o que a
verificacao confere e que **cada sentinela voltou exatamente uma vez**. Sumiu,
duplicou, ou apareceu um indice que o comentario nunca teve (vazamento do
vizinho de lote, o rastro de um separador comido): o comentario e tratado como
falha (T2/T3) e fica no idioma original — melhor do que gravar uma anotacao
corrompida com cara de certa. A leitura tolera espacos que o tradutor insira
em volta do numero (`⟦ 1 ⟧`); qualquer mutacao alem disso e exatamente o que a
verificacao existe para pegar.

A posicao da mascara no pipeline e uma decisao, nao um acaso: **depois** da
limpeza (uma regra de limpeza ainda pode remover uma anotacao inteira, se o
usuario quiser) e a restauracao e o **ultimo** passo antes de gravar — as
regras automaticas e a correcao de lances rodam sobre o texto ainda mascarado,
entao nem elas alcancam uma anotacao escondida. A verificacao roda **nos dois
caminhos** (lote e fallback individual), pela licao da secao 10.4: uma guarda
que existisse so num deles daria uma execucao cujo resultado depende de a rede
ter respondido alinhada.

Duas escolhas de escopo, ditas para nao parecerem esquecimento:

- **NAGs `$n` nao sao mascarados.** Dentro de comentario eles sao raros (NAG
  vive no movetext, que nunca e tocado), e mascarar cada `$14` de prosa
  encareceria a leitura do que e enviado sem um caso real medido. Se o QA da
  secao 16 mostrar NAGs mutilados em uso, a mascara ja tem onde crescer.
- **A exclusao de 13.1 fica mesmo com a mascara existindo.** A ferramenta em
  massa do banco (P4) opera sobre texto ja gravado, onde a mascara nao passou —
  e defesa em profundidade contra o dia em que um caminho novo esquecer de
  mascarar.

**Garantia X1 (nova)** — *anotacoes `[%...]` atravessam a traducao byte a byte,
ou o comentario conta como falha.*

### 13.4 Comentario esvaziado pela limpeza virava `{}` no arquivo

Quando as regras de limpeza esvaziam um comentario (`{== StartFEN ==}` e lixo
de conversao mesmo), o worker grava `translated_map[comment] = ""` e a geracao
montava `"{" + "" + "}"`: o PGN de saida ficava pontilhado de `{}`. Parsers
tolerantes aceitam; os estritos reclamam; e visualmente e sujeira.

**Feito na geracao, sem marca nova no mapa.** O `""` do mapa ja significava uma
coisa so: `load_translation_cache` filtra traducoes vazias e uma falha nunca
entra no mapa (T3), entao o unico `""` possivel e o da limpeza — e a geracao
passou a remover o span inteiro ao ve-lo, levando junto **um** espaco vizinho
(o seguinte, ou o anterior; nunca uma quebra de linha, que estrutura o resto do
arquivo, e nunca o comeco do span colado seguinte — `{a}{b}` tem teste). O
unico teste que ancorava o `{}` na saida afirmava o comportamento antigo de
proposito e foi trocado junto, com o motivo escrito nele.

**Garantia X2 (nova)** — *comentario esvaziado pela limpeza sai do arquivo sem
deixar `{}` para tras.*

### 13.5 Comentarios `;` nao existiam para o programa

O padrao PGN tem duas formas de comentario: `{...}` e `;` ate o fim da linha. O
extrator so ve a primeira. Um PGN anotado no estilo `1. e4 ; melhor lance` saia
com "Nenhum comentario encontrado" e o usuario concluia que o programa falhou —
o modo de erro mais confuso possivel, porque nada esta errado e nada e dito.

Traduzir `;` e desejavel mas nao era o primeiro passo; **anunciar** era.

**Feito: contar e anunciar.** A extracao conta as linhas com `;` fora de
`{...}` e fora das linhas de tag (um `;` dentro de chaves e texto do
comentario; um numa tag e parte do valor — e as chaves sao removidas
preservando as quebras de linha, para a contagem por linha nao juntar
vizinhas). O worker anuncia por arquivo, no resumo final e no dialogo — e um
PGN **so** com `;` agora termina com a frase que explica: "nenhum comentario
`{...}` encontrado, mas ha N comentario(s) no formato `;`, que o programa nao
traduz". As linhas do resumo so aparecem quando a contagem nao e zero, pelo
criterio da linha de lances da secao 10: um "0 ignorados" fixo faria o usuario
procurar um problema que nao ha.

**Garantia X3 (nova)** — *o que o pipeline ignora e contado e anunciado.*

### 13.6 A saida nao respeitava quem vai ler o arquivo

Tres achados menores da mesma familia — o arquivo gerado e correto, mas hostil
ao consumidor. Dois entraram; o terceiro mudou de lugar, e esta dito.

- **O fim de linha deixou de ser reescrito.** `newline=''` em todas as
  leituras e gravacoes de PGN: um arquivo CRLF sai CRLF, um LF sai LF, byte a
  byte fora dos spans traduzidos — ha teste com os bytes exatos dos dois
  casos. Antes, `\r\n` virava `\n` na leitura e `os.linesep` na escrita, e
  todo acervo versionado ou comparado por hash mudava inteiro. De quebra, o
  tratamento de `\r\n` do normalizador de metadados — que era codigo morto por
  causa do universal newlines — passou a ser real, e ganhou o mesmo
  `newline=''` na leitura.
- **UTF-8 com BOM virou opcao**: `output.utf8_bom` no
  `pgn_tradutor_pro_settings.json`, desligada por padrao (o comportamento de
  sempre; um BOM que ninguem pediu tambem incomoda — git, diff, parsers
  estritos). Ligada, um PGN ASCII cuja traducao introduz acentos sai
  `utf-8-sig` e o ChessBase do Windows para de ler ANSI e exibir mojibake. So
  mexe em UTF-8: um BOM nao significa nada em cp1252. E opcao de arquivo, sem
  interface — o dia em que merecer um checkbox e o dia em que a janela
  principal ganhar uma secao de opcoes de saida.
- **A requebra em 80 colunas (export format) NAO foi feita** e mudou de lugar:
  e formatacao para editora, nao correcao de corrupcao, e envolve decidir onde
  quebrar dentro de comentario traduzido. Esta na secao 19 (fluxo do tradutor
  profissional), item 13 — registrado la para nao se perder.

### 13.7 O que a verificacao fixou

Vinte e oito testes novos, todos escritos para falhar sem a correcao — e os
dois centrais **provados** contra o comportamento antigo, simulando-o com as
funcoes reais: sem a exclusao, `[%cal Ra1h8]` volta a virar `[%cal Ta1h8]`
(corrigidos = 1); sem a correcao do achatamento, `[%eval +0.35]` volta a virar
`[%eval +0. 35]`. A suite inteira (655 testes, GUI inclusive) passou depois das
mudancas.

**Um unico teste existente precisou mudar, e essa mudanca e o item 13.4**: ele
afirmava `assertIn("{}")` — protegia o comportamento antigo de proposito, como
devia. Trocado por `assertNotIn`, com o motivo escrito no proprio teste.

O que fica de fora, dito para o proximo leitor nao supor o contrario:

- A mascara protege a traducao **nova**. Uma anotacao ja corrompida no banco
  por uma execucao anterior continua la — acha-la e trabalho do QA da secao
  16, e corrigi-la em massa seria uma ferramenta irma da "Corrigir Lances".
- O sentinela `⟦n⟧` foi validado contra o endpoint por raciocinio e teste de
  unidade, nao por medicao em volume no endpoint real. Se o Google mutilar
  sentinelas com frequencia, isso aparece como falhas T2 contadas — visivel,
  nunca silencioso — e o formato do sentinela e um lugar so para trocar.

---

## 14. O dicionario tem erros de xadrez, regras mortas e lacunas — CONCLUIDO (2026-07-29)

O `Substituicoes.txt` foi lido regra a regra (7.105), com demonstracoes ao vivo
usando o glossario real. E o maior ativo do programa — 7.105 decisoes tomadas
uma a uma — e e tambem onde um tradutor profissional encontra mais o que
consertar. Este item e a curadoria; o 15 e a estrutura.

O arquivo saiu de **7.105 para 5.919 regras**, e quase toda a diferenca e
colapso, nao remocao: 1.203 regras que enumeravam casas do tabuleiro a mao
viraram 20 (14.7). O que de fato saiu foram 5 regras que corrompiam portugues
(14.3), 42 que nunca disparavam (14.4) e 5 miudezas; entraram 49 termos e 8
regras precisas de coluna. O conjunto de regras **aplicadas** mudou pouco e de
proposito — a verificacao esta em 14.10.

**Duas correcoes ao diagnostico da revisao, e as duas importam.** A analise que
abriu esta secao errou em dois pontos, e o que os descobriu foi medir em vez de
supor:

| o que a analise dizia                            | o que a medicao mostrou                                                                                                                 |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `=/+` invertido e regra **automatica**   | e`suggestion` — aplicada a pedido, nao no escuro. O erro e o mesmo, a gravidade e menor                                              |
| 9 regras de palavra comum sao de altissimo risco | **4 nao corrompem nada**: `the`, `if`, `with`, `by` nao sao palavras portuguesas e a fronteira de palavra as protege      |
| —                                               | **faltava a pior de todas**: `('por', 'com')`, que estraga "venceram **por** abandono" e "vale **por** dois peões" |
| "210 regras nunca disparam"                      | 210 nunca disparam, mas**166 sao inofensivas** e 44 perdem algo                                                                   |
| "`pin` (palavra inglesa): zero regras"         | `('pin', 'cravada')` existe desde sempre                                                                                              |

### 14.1 Um erro factual de xadrez

```
('=/+', 'com leve superioridade para as brancas')     # ERRADO
('+/=', 'as brancas tem leve superioridade')          # certo, mas "tem" -> "têm"
```

`=/+` (⩱) significa **as pretas** ligeiramente melhores. O arquivo dava a mesma
leitura para os dois simbolos, entao toda avaliacao `=/+` saia **invertida** —
dizia o contrario do que o autor do livro escreveu, que e o pior tipo de erro de
traducao possivel: nao parece erro nenhum.

**A regra e `suggestion`, e nao `automatic`** — a analise inicial disse
automatica e a medicao corrigiu. Muda a gravidade, nao o erro: o revisor
continua vendo a sugestao errada oferecida, e "Aplicar todas" a aplica.

Corrigidas as quatro da familia: `=/+` passa a nomear as pretas, `-+` troca
"negras" pela norma "pretas" do proprio arquivo (o congelamento de S4 impedia a
normalizacao posterior), e `+/=` ganha a concordancia ("as brancas **têm**").
As duas que ja estavam certas — `+/-` e `-/+` — ficaram como estavam, e ha teste
fixando as quatro.

### 14.2 Terminologia errada codificada

- `('castling', 'rocado')` -> **`'roque'`**: particibio onde o portugues pede o
  substantivo. A regra irma `('Castling', 'Roque')` estava certa, mas por caixa
  quem pegava o texto minusculo — quase todo — era a errada.
- `('back rank', 'primeira fila')` -> **`'última fila'`**, e a mesma na versao
  com hifen. *Back rank* e a ultima fileira de quem defende; "primeira fila" so
  vale olhando do lado das brancas, e o proprio arquivo se contradizia noutra
  regra ("ultima fila").
- `('Zwischenzug', 'Lance intermediario ganhador')` -> **`'Lance intermediário'`**: um Zwischenzug nao e necessariamente ganhador, e a
  sobretraducao poe no texto uma avaliacao que o autor nao fez.
- `('-fileira', '-coluna')` e `('fileira-', 'coluna-')` **removidas, e
  substituidas por oito precisas**. As duas existiam por um motivo legitimo — o
  Google verte *file* como "fileira" —, mas o padrao delas casa qualquer coisa
  antes do hifen: `"sétima-fileira"`, que e uma fileira de verdade, virava
  `"sétima-coluna"`. Quem distingue e o que vem antes: uma **letra** de coluna e
  *file*, um ordinal e *rank*. Entraram `('a-fileira', 'coluna a')` ate
  `('h-fileira', 'coluna h')`, que fazem o que as genericas queriam sem alcancar
  fileira nenhuma. Remover sem repor teria trocado um erro por uma lacuna.

### 14.3 Regras de altissimo risco em palavras comuns

Nove regras casam palavras funcionais ou siglas curtas e destroem portugues
legitimo — confirmado ao vivo:

```
('for', 'para')      "Se for melhor..."  -> "Se para melhor..."
('negro', 'negras')  "O bispo negro"     -> "O bispo negras"
```

**A lista da analise estava errada nas duas pontas, e o que decidiu foi medir.**
Em vez de julgar cada padrao pela aparencia, apliquei o glossario real a treze
frases de portugues enxadristico legitimo e vi quais regras estragavam quais
frases. Resultado:

| regra                                                                    | veredito                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `('for', 'para')`                                                      | **removida** — "Se **for** melhor" -> "Se **para** melhor"                                                                                                                                                                                              |
| `('por', 'com')`                                                       | **removida** — "venceram **por** abandono" -> "**com** abandono"; "vale **por** dois peões". A analise nao a tinha visto, e e a pior de todas: `por` e uma das preposicoes mais comuns do portugues                                            |
| `('#', 'mate')`                                                        | **removida** — `#` e o sinal de mate do PGN, e o padrao nao tem fronteira de palavra: `Dh7#` virava `Dh7mate`. E o tema da secao 13 aparecendo no glossario                                                                                                   |
| `('luz', 'clara')`                                                     | **removida** — "a **luz** do sol" -> "a **clara** do sol". As sete regras especificas (`'de luz'`, `'praças de luz'`, `'quadrado luz'`...) cobrem o sentido enxadristico                                                                         |
| `('negro', 'negras')`                                                  | **removida** — "o bispo **negro**" (casas escuras) -> "o bispo **negras**". As especificas cobrem o jogador (`'o negro'`, `'os negros'`, `'rei negro'`), e a remocao **revive** `('Negro', 'as pretas')`, que estava morta por causa dela |
| `('the','o')`, `('if','se')`, `('with','com')`, `('by','pelas')` | **ficaram** — nao corromperam frase nenhuma. Nenhuma delas e palavra portuguesa, e a checagem de fronteira exige a palavra inteira: elas so alcancam ingles que o tradutor deixou para tras, que e para o que foram escritas                                        |
| `('Quote','')`, `('AD','BD')`, `('AR','BR')`                       | **ficaram** — mesmo motivo, e as duas ultimas sao sensiveis a caixa por terem maiuscula                                                                                                                                                                             |
| `('asa', 'ala')`                                                       | **ficou**, com ressalva registrada: ela estraga "a **asa** do avião", mas isso nao aparece em livro de xadrez, e "asa" ali e sempre o *wing* mal traduzido                                                                                                  |

Cinco removidas, quatro absolvidas por medicao. **O criterio ficou explicito**:
sai a regra cujo padrao e palavra portuguesa comum usada fora do sentido
enxadristico. Isso e o que separa `for` e `por` — que qualquer texto em
portugues contem — de `the` e `if`, que so aparecem quando a traducao falhou.

### 14.4 210 regras mortas por colisao de caixa, invisiveis ao detector

Uma regra toda minuscula casa sem diferenciar caixa. Entao `('black','pretas')`
tambem casa `Black`, e `('Black','as pretas')` — digitada depois, com a
substituicao **diferente** — nunca dispara: por posicao a minuscula vem antes,
e o congelamento (S4) impede a segunda de rever o trecho. Confirmado ao vivo
com o glossario real:

```
IN : Black wins the pawn.
OUT: Pretas wins o peão.        # e nao "as pretas", como a regra de cima pedia
```

Medido no arquivo inteiro: **210 regras nunca disparavam por isso.** E
`glossary_conflicts` agrupava por texto **exato**, entao a garantia S9 — "a
interface diz qual regra do conflito esta valendo" — era cega para 100% desses
casos: a janela mostrava as duas regras lado a lado sem dizer que uma estava
morta.

**Mas 166 das 210 nao fazem falta**, e essa e a parte que a analise nao viu. A
substituicao propaga a capitalizacao do texto encontrado, entao
`('as pretas deve', 'as pretas devem')` aplicada a `"As pretas deve"` produz
`"As pretas devem"` — exatamente o que a regra capitalizada ao lado dela queria.
Ela esta morta e ninguem perde nada: e redundancia, e a redundancia ja tem aviso
proprio ("Entrada duplicada").

Isso mudou o desenho do detector. A pergunta certa nao e "as substituicoes sao
diferentes como texto", e sim **"o que a vencedora PRODUZ aqui e diferente do
que esta regra queria"** — e quem responde e `case_adjusted_replacement`, a
mesma funcao que a aplicacao usa. Com esse criterio sobram **44** conflitos
reais, que e um numero que cabe numa tela.

Duas consequencias que os testes existentes acusaram, e as duas foram
esclarecedoras:

- **A duplicata exata saiu do filtro "Conflitos".** Um teste esperava 3 e passou
  a ver 2, porque a avaliacao antiga bastava "ha duas substituicoes distintas no
  grupo" e arrastava a duplicata junto — contra o que a propria S9 dizia. O
  teste mudou, com o motivo escrito nele.
- **`group` deixou de ser o conjunto em disputa.** "Manter esta" remove o
  `group`, e se a duplicata exata ficasse fora dele a regra escolhida
  continuaria morta depois do clique — agora sem nada na tela explicando. O
  `group` passou a ser "quem casa o mesmo texto nos contextos em disputa", que e
  o que faz o botao honrar o nome. Ha teste para isso, e ele falha com a versao
  ingenua.

**A curadoria das 44.** Removidas 42 — e **remover uma regra que nunca dispara
nao muda comportamento nenhum**; o que muda e o arquivo parar de prometer um
resultado que nao entrega. As duas restantes eram outra coisa:

- `('as pretas possui', 'as bpretas possuem')` — **um typo na regra que estava
  valendo**, achado justamente porque a morta ao lado dela estava certa. Sem o
  detector, "as bpretas" continuaria saindo em toda traducao que casasse esse
  padrao. Corrigido na regra viva.
- `('nimzo-indianos', 'Nimzo-india')` — nome proprio com minuscula. Corrigido
  para `'Nimzo-Índia'`.

E uma ganhou **prioridade** em vez de sair: `('Black', 'as pretas')`. O artigo
nao e preferencia, e gramatica — "Black is better" pede "**As** pretas estão
melhores", e a vencedora `('black', 'pretas')` produzia "Pretas". Priorizar poe
a capitalizada na frente sem apagar ninguem: `Black` -> "As pretas", `black` ->
"pretas", as duas vivas. **E a primeira regra do glossario a usar a prioridade**
— o campo existia desde o item 1.5 e estava em zero nas 7.105.

As que sairam levaram junto alternativas de terminologia que nunca dispararam, e
vale registrar quais, porque a decisao foi deliberada e e reversivel por aqui:
`'As brancas empurra' -> 'avançam'` (contra `'empurram'`), `'Cheapo' -> 'Truque sujo'` (contra `'Truque'`), `'Impasse' -> 'Empate por Afogamento'` (contra
`'Afogamento'`), `'As pretas venceu' -> 'venceram'` (contra `'ganharam'`),
`'teve' -> 'tiveram'` (contra `'tinham'`), `'acabou' -> 'acabaram'` (contra
`'acabam'`). Nenhuma delas era **erro** da regra viva, e reescrever a escolha de
palavra do usuario nao e trabalho de curadoria; quem quiser qualquer uma de volta
a redigita e clica em "Priorizar esta" — que agora funciona e diz o que faz.

**Garantia S12 (nova)** — *conflito por diferenca de caixa e anunciado como o
exato, e so quando a vencedora produz outra coisa.*

### 14.5 As 50 regras de delecao estao no tipo errado, e o CSV as perde

Ha 50 regras que apagam lixo de conversao (`'== StartFEN =='`, `'@@'`,
`'îîEndBracketîî'`) — trabalho de **limpeza** por definicao, que deveria rodar
**antes** da API (nao pagar para traduzir lixo). Todas estavam tipadas
`suggestion`, o tipo `cleanup` estava **vazio** (zero regras), e tres defeitos se
somavam:

- elas so rodavam se o revisor aplicasse a mao, uma a uma;
- `validate_glossary_entry` so tolera substituicao vazia em `cleanup`, entao o
  editor as marcava **invalidas** — 50 avisos permanentes na lista;
- `analyze_glossary_csv_import` descartava linha com substituicao vazia, entao
  **exportar e reimportar o glossario perdia as 50**, em silencio.

**Feito: as 50 retipadas para `cleanup`, e o CSV passou a aceitar substituicao
vazia quando o tipo e `cleanup`.** O criterio agora e o mesmo nos dois lugares —
era exatamente a divergencia de dois validadores que fazia o round-trip comer as
regras.

**Uma consequencia, medida antes de aceitar:** regra de limpeza nao e oferecida
no editor (o contexto interativo carrega sugestoes e automaticas), entao as 50
deixam de aparecer como sugestao. Isso importaria se o lixo estivesse nas
traducoes ja gravadas — e nao esta: procurei os 50 padroes nas 6.500 traducoes do
banco de desenvolvimento e o resultado foi **zero ocorrencias, no original e na
traducao**. Sao artefatos do PGN de origem, e e la que a limpeza age. Em troca, as
50 pararam de ser marcadas invalidas e passaram a rodar antes da API.

**Garantia S14 (nova)** — *exportar e reimportar o glossario preserva as regras
de delecao.*

### 14.6 Um tipo mal escrito degrada em silencio

`_normalize_rule_type` converte qualquer valor irreconhecivel em `suggestion`.
A tabela de aliases tinha `automatica`/`automática` mas nao `automatico`/
`automático` (masculino) nem `auto` — entao `('x','y','automático')` virava
sugestao, deixava de rodar depois da API, e nada avisava. O arquivo e editavel a
mao e sobrevive a versoes; degradar sem derrubar esta certo (mesmo principio de
S5), **degradar sem avisar** nao.

**Feito nas duas metades.** Os aliases que faltavam entraram (`automatico`,
`automático`, `auto`, `clean`, `limpar`, `sugestões`), e a carga do arquivo passa
a avisar pelo handler que a garantia S5 ja instalou.

Duas decisoes de desenho valem registro:

- **O aviso e um, nao um por regra.** Um arquivo com cem tipos tortos precisa de
  um aviso; cem dialogos seriam pior que o silencio. A funcao junta os valores
  distintos e nomeia ate cinco.
- **O aviso mora na leitura do ARQUIVO, nao no `glossario.db`.** O banco guarda
  tipos ja normalizados: quando ele e lido, a grafia errada nao existe mais. Quem
  ve `'automático'` escrito e so quem le o texto.

E a pergunta ficou separada em duas funcoes, porque sao duas: `_rule_type_alias`
responde "isto e um tipo que eu conheco" (devolve `None` quando nao) e
`_normalize_rule_type` responde "com que tipo eu sigo em frente". Antes as duas
eram a mesma expressao, e por isso nao havia como avisar.

**Garantia S13 (nova)** — *tipo de regra desconhecido avisa em vez de degradar em
silencio.*

### 14.7 1.235 regras enumeram casas a mao, com buracos

17,4% do glossario (1.235 regras) continha uma casa literal (`a1`..`h8`):
familias como `a1-peao -> peao de a1` escritas casa a casa, em 20 familias
uniformes. O levantamento exaustivo mostrou o preco da enumeracao manual:

- **sete familias paravam em 56 regras** — faltava a fileira 3 inteira
  (`a3-torre`, `e3-dama`, `d3-peao`...);
- `<casa>-peao` estava partida sem criterio: `suggestion` e `automatic`
  misturadas, com as automaticas indo de `a1` a `b8` em ordem alfabetica — a
  marca de uma passagem manual que parou no meio, e nao de um criterio.

**Feito: o placeholder `@casa@`, expandido na carga para as 64 casas.** Uma
linha no arquivo, 64 regras na aplicacao. As 1.203 regras das familias uniformes
viraram 20, e a expansao **nao tem como esquecer uma casa**: a fileira 3 passou a
funcionar sem ninguem digitar nada (`'e3-torre'` -> `'torre de e3'`, verificado).

Nao e regex, e a promessa da SPEC continua de pe: as regras que saem da expansao
sao literais, exatamente as que o usuario escreveria a mao. O que muda e quem as
escreve. Tres decisoes de escopo:

- **O ORIGINAL manda.** Sem placeholder no padrao, a regra sai intacta mesmo que
  a substituicao tenha um — inventar 64 regras iguais para um padrao unico
  mudaria o que a regra casa.
- **A expansao e na conversao entrada -> regra, nao na leitura do arquivo.** O
  editor de glossario continua mostrando **uma** linha com o placeholder, que e o
  que da para editar; a ordenacao por comprimento (S3) ve o padrao ja expandido,
  com o tamanho real que ele tem no texto.
- **As familias partidas por tipo foram colapsadas por tipo**, e nao unificadas.
  Unificar era tentador — o tipo coerente para uma normalizacao de notacao e
  `automatic` — mas mudaria o comportamento de 91 padroes: 49 passariam a ser
  aplicados sem revisao, ou 14 deixariam de ser. Colapsando cada tipo separado,
  as 28 automaticas ficam literais e o resto vira placeholder de sugestao;
  **nada muda de comportamento**. Quem quiser a familia inteira automatica
  agora troca uma linha, e nao 64.

De quebra, `find_glossary_suggestions` passou a nao repetir o mesmo par: uma
regra literal e a expansao de um `@casa@` podem chegar como a mesma sugestao, e
oferece-la duas vezes nunca ajudou ninguem.

### 14.8 O nucleo terminologico do xadrez tem ~30 ausencias

Varredura por termo, contra o vocabulario basico de anotacao em ingles. Zero
regras para: *zugzwang*, *en passant*, *skewer* (espeto), *pin* como palavra
inglesa (so ha `alfinete`, o erro do Google — se o tradutor deixar *pin* em
ingles, nada corrige), *blunder*, *outpost* (posto avancado), *smothered mate*
(mate sufocado), *open file* como expressao (coluna aberta), *exchange
sacrifice* (sacrificio de qualidade — as 83 regras de `qualidade` existentes
cobrem outra direcao), *hanging pawns* (peoes pendurados), *minority attack*
(ataque de minorias), *threefold repetition* (triplice repeticao), *fifty-move
rule*, *insufficient material*, *fortress* (fortaleza), *prophylaxis*
(profilaxia), *opposition*, *triangulation*, *windmill* (moinho),
*underpromotion* (subpromocao), *deflection* (desvio), *decoy* (atracao),
*overloading* (sobrecarga), *interference*, *clearance*, *novelty*, *luft*,
*time trouble*/*Zeitnot*, *king safety*, *pawn chain*. E os simbolos `!`,
`?!`, `∞`, `⩲`, `⩱` nao tem regra nenhuma (a familia `+-`/`-+`/`+/=`/`=/+`
tem — com o erro do 14.1).

Uma correcao a varredura: **`('pin', 'cravada')` existe** — a analise disse que
nao. `('alfinete', 'cravada')` cobre o erro do Google e `pin` cobre o ingles que
sobrou; as duas estavam la.

**Feito: 49 termos acrescentados, so na direcao ingles -> portugues.** E a
direcao segura, e a escolha tem razao medida: um padrao em ingles nao casa texto
portugues, entao nenhum deles pode corromper o que ja funciona — que e
exatamente o defeito das cinco regras removidas em 14.3. E o modo de falha que
eles cobrem **foi medido**: no banco de desenvolvimento ha 263 traducoes em que o
tradutor deixou "White"/"Black" em ingles, ou seja, "o tradutor nao traduziu" e
um caso real e frequente, nao hipotetico.

Entraram os nucleos que faltavam: *skewer*, *outpost*, *blunder*, *smothered
mate*, *open file*, *half-open file*, *exchange sacrifice*, *minority attack*,
*hanging pawns*, *backward pawn*, *threefold repetition*, *fifty-move rule*,
*insufficient material*, *fortress*, *prophylaxis*, *triangulation*,
*underpromotion*, *deflection*, *decoy*, *overloading*, *interference*,
*clearance*, *windmill*, *time trouble*/*Zeitnot*, *king safety*, *pawn
structure*, *pawn chain*, *discovered attack*, *long diagonal*, *minor/major
piece*, *good/bad bishop*, *opposite-colo(u)red bishops* — com os plurais onde
eles mudam a forma portuguesa.

**O que NAO entrou, e por que:** as correcoes do lado **portugues** (o que fazer
quando o Google escreve "garfo" ou "impasse"). Elas exigem saber o que o tradutor
produz de fato, e as 7.105 regras do usuario existem porque ele observou saida
real — adivinhar aqui produziria justamente um `('for', 'para')`. Isso vai com a
semente por idioma da secao 15, onde cada termo tem traducao consagrada em pt,
es, fr, de, it e ru e o escopo impede que uma regra portuguesa alcance texto
italiano. `zugzwang` e `en passant` tambem ficaram fora: sao as formas que o
tradutor **deixa como estao**, e uma regra `('zugzwang', 'zugzwang')` seria um
no-op — a especie que a 14.9 acabou de remover.

### 14.9 Miudezas que a curadoria levou junto

- **Tres no-ops removidas** (`('coluna a', 'coluna a')` e irmas): uma regra que
  devolve o que encontrou. Ha teste garantindo que nao volte nenhuma.
- `('roqueemos', 'rocamos')` -> **`'roquemos'`**: subjuntivo por indicativo, e
  coerente com `('roqueiem', 'roquem')`, que o arquivo ja tinha certo.
- `('companheiros', 'mate')` -> **`'mates'`**: o plural desaparecia.
- `('checkmates', 'xeque mates')` -> **`'xeques-mate'`**; `('middlegames', 'meio jogos')` -> **`'meios-jogos'`** e o singular -> **`'meio-jogo'`**:
  hifenizacao e plural de composto.
- `('semi-aberta coluna', 'coluna semi-aberta')` -> **`'coluna semiaberta'`**:
  ortografia pos-2009.
- Docstrings do `glossario.py` citando 7.008 regras onde ha outro numero — o
  proprio texto passou a nao depender de contagem que envelhece.

Ficou de fora, de proposito: os **tres estilos de aspas** para a coluna "e"
(`'peão "e"'`, `"coluna 'e'"`, `'coluna e'`). Padronizar exige escolher qual
aparece no texto publicado, e isso e decisao editorial do usuario, nao correcao.

### 14.10 O que a verificacao fixou

Vinte e tres testes novos. Os que valem mais nao testam funcao, e sim **decisao
de xadrez sobre o arquivo real**: que `=/+` nomeia as pretas, que `castling` e
substantivo, que `back rank` e a ultima fila, que as cinco regras que corrompiam
portugues nao voltaram, que nenhuma regra devolve o que encontrou, que toda
regra de delecao e `cleanup`, e que o glossario continua sem enumerar casas. Sem
eles, a proxima edicao do glossario desfaz a curadoria sem que nada acuse.

**A verificacao de que a curadoria nao quebrou nada foi feita sobre as regras
APLICADAS, e nao sobre o arquivo.** O arquivo encolheu 1.322 linhas, o que nao
diz nada sozinho; o que importa e o conjunto de regras que chega ao texto,
comparado com o do commit anterior:

| contexto    | antes | depois | o que mudou                                                                                                                            |
| ----------- | ----- | ------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| limpeza     | 0     | 50     | as 50 retipadas (14.5)                                                                                                                 |
| automaticas | 147   | 146    | uma morta removida, e`companheiros` -> `mates`                                                                                     |
| editor      | 7.105 | 7.101  | 118 saem, 114 entram — as 5 nocivas, as 42 mortas, as 50 que viraram limpeza; entram 49 termos, 8 colunas, a fileira 3 e as correcoes |

Nenhuma colisao entre regras expandidas nos tres contextos, e **zero conflitos**
no glossario curado — o que devolve `test_the_real_glossary_has_no_undecided _conflict` ao verde. Esse teste, a proposito, foi o que **forcou** a curadoria: ele
exige que o glossario versionado nao tenha disputa pendente, entao ligar o
detector de S12 o deixou vermelho e ele so voltou ao verde quando as 44 foram de
fato decididas. Um teste que obriga a decisao em vez de registrar a ausencia
dela.

Dois testes existentes mudaram, os dois no mesmo caso e pelo mesmo motivo (a
duplicata exata saindo do filtro "Conflitos"), com a razao escrita neles. A suite
inteira passou: **678 testes**.

O que fica de fora desta secao, dito para nao ser lido como pronto:

- **O glossario continua global.** Nada aqui o torna por par de idiomas, e as
  regras portuguesas continuam alcancando uma traducao para o italiano. E a
  secao 15, e ela nao foi feita.
- **A curadoria olhou o que a medicao alcanca.** Treze frases de teste e 7.105
  regras: as que corrompem construcoes que eu nao escrevi continuam la. O que
  mudou e que o programa passou a ter como acusa-las — o detector de caixa, o
  aviso de tipo, o QA da secao 16 quando existir.
- **As 166 mortas inofensivas ficaram no arquivo.** Removê-las nao mudaria
  comportamento nenhum, mas tambem nao ganharia nada, e sao 166 decisoes do
  usuario cuja intencao esta cumprida. O detector corretamente nao as aponta.

---

## 15. O glossario nao sabe para que lingua traduz — CONCLUIDO (2026-07-29)

A SPEC sempre declarou o limite ("o glossario nao e por par de idiomas", secao
10); o que a revisao acrescentou e a **prova de que ele ja custa caro**. As 147
regras automaticas rodam sobre a resposta da API seja qual for o destino, e o
dano foi confirmado ao vivo com o glossario real:

```
IT  'Il movimento della torre'      -> 'Il lance della torre'      # italiano corrompido
ES  'El alfil negro domina'         -> 'El bispo negras domina'    # espanhol, duas vezes
EN  'O-O is castling'               -> '0-0 is castling'           # ingles alterado
```

`('movimento','lance')`, `('alfil','bispo')`, `('negro','negras')`,
`('black','pretas')` — cada uma esta **certa** para o destino portugues e
**errada** para os outros seis. Hoje traduzir para qualquer lingua que nao o
portugues passa o texto por um filtro portugues.

E a composicao medida do arquivo mostra que nao e acidente, e historia: ~98%
das regras corrigem saida do Google **em portugues**, ~101 sao ingles -> pt,
**uma** e espanhol -> pt, e fr/de/it/ru tem zero. O programa anuncia 7 idiomas
e o glossario atende 1,5.

### 15.1 Escopo de idioma como quinto campo

Cada regra ganha um escopo opcional — o idioma de **destino** a que ela se
aplica (`'pt'`), ou o par completo quando o erro e daquela traducao especifica
(`'en>pt'`) —, quinto campo da tupla. No CSV, coluna `lang`, opcional na
leitura. A aplicacao filtra pelo par ativo da execucao (worker) ou da janela
(editor); o editor de glossario mostra, edita e valida o campo.

**O plano dizia "ausente = vale para todos", e implementar mostrou que isso nao
bastava.** Escopar as 5.900 regras portuguesas exigiria escrever `, 'pt'` em
cada uma — um diff do arquivo inteiro, que e exatamente o que o formato foi
desenhado para evitar. O argumento esta escrito no proprio serializador desde o
item 1.5: *"o arquivo tem milhares de linhas e e versionado, e escrever `, 0` em
todas transformaria a decisao tomada em quatro regras num diff de milhares de
linhas."* Aqui ele pesa mais, porque o acervo inteiro tem o mesmo escopo e as
excecoes sao dezenove regras de notacao.

Entao o arquivo passou a poder **declarar o escopo uma vez**:

```python
escopo = 'pt'
substituicoes = [
    ('movimento', 'lance', 'automatic'),        # herda 'pt'
    ('×', 'x', 'automatic', 0, '*'),            # excecao: todo par
    ('bishop', 'alfiere', 'suggestion', 0, 'it'),
]
```

O campo por regra continua existindo e passa a significar **discordar do
padrao** — `'*'` quando a excecao e valer para todo par, um codigo quando e outro
idioma. A ausencia deixou de ser "todos" e virou "herda"; num arquivo sem a
declaracao, herdar e justamente "todos", entao **um `Substituicoes.txt` de antes
desta versao continua valendo sem uma linha alterada** (ha teste). O `'*'` existe
por causa dessa mudanca: sem ele nao haveria como escrever a excecao global.

**A migracao do acervo custou 23 insercoes e 19 remocoes** num arquivo de 5.921
linhas: uma linha de declaracao e o `'*'` nas dezenove regras que sao notacao e
nao lingua (`('×','x')`, `('O-O','0-0')`, `('OO','0-0')`, as correcoes de caixa
de lance como `('NH5','Nh5')`). Medido depois:

| destino | regras carregadas                          | `'Il movimento della torre'`           |
| ------- | ------------------------------------------ | ---------------------------------------- |
| it      | 19 ->**60** (as globais + a semente) | intacto (antes:`Il lance della torre`) |
| es      | 19 -> 60                                   | intacto                                  |
| pt      | 7.144                                      | `O lance da torre`, como sempre        |

**Uma armadilha que quase entrou, e vale mais que o item.** Meu primeiro desenho
fazia o escopo nomear *"o idioma do texto que a regra le"* — origem para as
regras de limpeza (que leem o comentario original), destino para as demais. E
mais elegante e teria sido um defeito silencioso grave: um arquivo que declara
`escopo = 'pt'` desligaria **todas as 50 regras de limpeza** numa execucao
en -> pt, porque a origem nao e portuguesa. O escopo nomeia o destino, sem
excecao por tipo, e o preco declarado e que nao ha como escopar uma limpeza por
idioma de origem — nenhuma das 50 precisa, porque lixo de conversao nao tem
lingua.

**Garantia S11 (nova)** — *regra com escopo de idioma so e aplicada no seu par.*
Sem escopo, comportamento de sempre; sem par declarado no chamador, nada e
filtrado.

### 15.1.1 O que o escopo mudou no detector de conflitos

Duas regras para destinos diferentes **nunca sao carregadas juntas**, entao
acusa-las de conflito seria descrever uma briga que nao acontece. `scopes_overlap`
entrou como o irmao de `GLOSSARY_RULE_CONTEXTS`: aquele separa por tipo, este por
idioma, e o raciocinio e o mesmo. Escopo vazio cruza com todos, e ai o conflito
volta a valer — uma regra global de fato alcanca o par da outra.

Isso importa mais do que parece agora: sem ele, a semente da 15.2 acusaria 232
conflitos falsos no primeiro dia, um por termo em cada idioma.

### 15.2 Dicionarios-semente por idioma

Com o escopo existindo, o programa passou a **vir com** terminologia:
`tradutor_pgn/Substituicoes-semente.txt`, **232 regras** cobrindo 41 termos do
nucleo enxadristico — pecas, os dois lados, xeque/mate/afogado/roque/empate,
geografia do tabuleiro (casa, coluna, fileira, alas), taticas (cravada, garfo,
espeto, sacrificio, xeque descoberto), fases, estrutura de peoes e avaliacao.

| destino        | regras da semente |
| -------------- | ----------------- |
| pt, es, de, it | 41 cada           |
| fr             | 38                |
| ru             | 30                |

**Todas vao de INGLES para o destino**, e a escolha nao e de conveniencia: um
padrao em ingles nao casa texto portugues, italiano ou russo, entao nenhuma
regra da semente pode corromper o que ja funciona — que e exatamente o defeito
das cinco regras removidas em 14.3. E o caso que elas resolvem foi **medido**: no
banco real ha 263 traducoes em que o tradutor simplesmente nao traduziu
"White"/"Black". "O tradutor deixou em ingles" e o modo de falha mais comum que
existe, e o unico que da para cobrir sem observar a saida de cada par.

**Todas sao `suggestion`**, oferecidas no editor e aplicadas a pedido. A semente
e um palpite generico sobre a terminologia de quem usa, e aplicar palpite sem
ninguem ver e o que a secao 14 passou uma revisao inteira consertando. O preco
declarado: para quem traduz para o italiano, a semente ajuda na revisao e nao na
passagem automatica.

**Faltam termos de proposito.** As lacunas do russo e do frances sao onde eu nao
tinha certeza da forma consagrada (*skewer* em russo, *outpost* em frances). Uma
lacuna e melhor do que uma regra errada, e a secao 14 acabou de medir o preco de
adivinhar — o glossario do usuario e o lugar de corrigir, e ele sempre vence.

Tres decisoes de seguranca, as duas primeiras do plano e a terceira que
implementar acrescentou:

- **A semente nunca vence uma regra do usuario** para o mesmo padrao no mesmo
  escopo. A comparacao e por `casefold`, e nao por texto exato, pela licao de
  S12: uma semente em minusculas engoliria a versao capitalizada do usuario sem
  que nada dissesse. E uma regra dele **sem escopo** tambem vence a semente do
  par especifico — quem escreveu "sempre assim" decidiu mais do que a semente
  palpita. As que sobram entram **depois** das dele, entao entre padroes de
  mesmo comprimento a ordem do arquivo continua dando a ele a palavra final.
- **Os dois arquivos nao se misturam no disco.** O `Substituicoes.txt` sai de
  `sys.argv[0]` (ao lado do executavel, onde o usuario edita); a semente sai de
  `__file__` (dentro do pacote, em `_internal\tradutor_pgn\` no build). E a
  mesma distincao do `spelling.ssp`, pelo mesmo motivo, e o `.spec` foi
  atualizado junto. Atualizar o programa troca a semente e nao toca no
  glossario de quem usa.
- **Um defeito na semente nao desliga o glossario do usuario.** A leitura dela
  degrada para "sem semente" e **avisa** pelo canal de S5 — ela vem com o
  programa, entao o defeito e nosso, e o silencio seria pior. Ha teste com uma
  semente ilegivel.

**Garantia S15 (nova)** — *a semente nunca sobrepoe uma regra do usuario.*

### 15.3 O que a verificacao fixou

Vinte e quatro testes novos. Os que mais importam sao os dois que fixam a razao
da secao existir: a regra portuguesa **nao alcanca mais o italiano**, e um
`Substituicoes.txt` sem a declaracao de escopo continua valendo sem uma linha
alterada. Junto: o round-trip do escopo pelo arquivo, pelo banco e pelo CSV; que
gravar uma entrada preserva o `escopo = 'pt'` do arquivo (sem isso a primeira
gravacao pela janela devolveria todas as regras ao estado global); que uma
entrada nova herda o padrao; que um idioma de escopo desconhecido avisa e deixa a
regra muda em vez de espalha-la; e as cinco de S15.

**O alargamento da entrada de quatro para cinco campos custou ~45 ajustes de
teste**, e vale registrar por que eles nao foram escondidos atras de um
adaptador: a entrada detalhada e uma tupla de largura fixa desde que ela existe,
e foi assim que o quarto campo (prioridade) entrou no item 1.5. Um quinto campo
opcional em algum canal paralelo deixaria a "entrada normalizada" sem parte dos
dados dela, que e pior do que a churn.

O helper `com_prioridade` dos testes ganhou o escopo junto, com o mesmo
argumento que o criou: nos testes cujo assunto nao e escopo, escrever `, ""` em
cada tupla so acrescenta ruido — mas apagar o campo da comparacao esconderia um
escopo mexido por engano.

**Um sandbox novo no `setUpModule`:** o caminho da semente. Ela **existe** no
repositorio e e mesclada em toda carga de regras, entao sem desliga-la qualquer
teste que compare a lista exata de regras veria a terminologia embutida junto —
uma falha que nao tem nada a ver com o que o teste afirma. Quem exercita a
semente passa `seed_path` explicitamente. E o mesmo padrao do sandbox do
glossario, criado no item 4 pela mesma razao.

O que fica de fora, dito para nao ser lido como pronto:

- **O escopo nao alcanca o idioma de ORIGEM numa regra de limpeza** — ver a
  armadilha em 15.1. Nenhuma das 50 precisa; se um dia precisar, a forma
  `'en>'` ja existe no parser e o que falta e decidir o que ela significa para
  `cleanup`.
- **A semente nao aparece no editor de glossario.** Ele edita o arquivo do
  usuario, e a semente nao esta la — entao as regras dela chegam como sugestao
  sem linha correspondente na lista, e "Excluir do glossario" numa delas cai no
  caminho de "entrada nao encontrada" (garantia S6: nada e gravado, e o usuario
  e avisado). Mostra-la como leitura apenas, marcada, e trabalho de interface
  que esta secao nao fez.
- **O `filtro por escopo` na lista do editor nao entrou.** O idioma aparece no
  rotulo de cada regra que o declara, o que resolve ver; filtrar por ele e um
  segmento novo na barra e ficou para quando um glossario de verdade tiver mais
  de um idioma dentro.

---

## 16. O aviso de qualidade nao conhece xadrez — CONCLUIDO (2026-07-29)

As cinco heuristicas de `review_quality.py` sao genericas de traducao: vazia,
igual ao original, chaves perdidas, curta demais, longa demais. Nenhuma sabe
que o texto e xadrez. A medicao no banco de desenvolvimento (6.500 traducoes
en -> pt, reais, de livro) dimensiona o buraco:

|                                                               |                      |
| ------------------------------------------------------------- | -------------------- |
| linhas com erro de terminologia detectavel por padrao simples | **401 (6,2%)** |
| linhas que o`quality_warning` marca (banco todo)            | 11                   |
| intersecao entre os dois conjuntos                            | **0**          |

Os padroes foram estreitos de proposito (subcontar, nunca inflar): "White"/
"Black" nao traduzidos (263), *check* -> "cheque"/"verificar" (44), *exchange*
como qualidade -> "troca" (31), *file* -> "arquivo" (18), *tempo* ->
"andamento"/"ritmo" (11), *square* -> "quadrado" (10), *pin* -> "alfinete"/
"fixado" (4), *piece* -> "pedaco" (3), *rank* -> "classificacao" (2), *sound*
-> "som" (1), *castle* -> "castelo" (1). Cada um desses erros esta numa linha
que o filtro "Avisos QA" **nao mostra** — e o glossario do usuario ja tem a
correcao de quase todos, como sugestao, esperando alguem abrir a linha certa.

**Os numeros deste paragrafo sao do diagnostico, e a implementacao mediu de novo:
o item 16.3 tem a lista final e diz o que mudou.** O total foi de 401 para 347
(com heuristica a mais e dois candidatos a menos), e a maior divergencia individual
esta em *exchange*: o diagnostico afirmou 31 linhas com ele "como qualidade", e
"como qualidade" e uma leitura de sentido, nao um padrao de texto. O padrao que da
para escrever — o termo no original e "troca" na traducao — marca **178**, e a
maioria delas esta certa.

### 16.1 Heuristicas de xadrez — CONCLUIDO

A materia-prima ja existe no programa; e questao de liga-la ao aviso:

1. **Lance perdido ou inventado** — as ancoras de `extract_moves` (secao 10)
   comparadas entre original e traducao. O original tem `Bxf7+`, `Qd5+`, `Kxf7`
   e a traducao tem duas ancoras? O tradutor comeu um lance. E o aviso de maior
   valor por linha de codigo do projeto inteiro.
2. **Anotacao rompida** — os spans `[%...]` do original presentes e identicos
   na traducao (enquanto a mascara da secao 13 nao existe, este aviso e a rede;
   depois dela, e a prova de que a mascara funcionou).
3. **NAGs e simbolos de avaliacao** — multiconjunto de `$n`, `!`, `?`, `+-`,
   `∞` etc. igual dos dois lados.
4. **Digitos** — multiconjunto dos numeros igual dos dois lados; pega
   `0. 35`, `14` sumido e numeral por extenso.
5. **`U+FFFD`** — o sinal direto de que `errors='replace'` engoliu bytes
   (E4/G2 impedem na leitura nova; isto detecta o legado).
6. **Separador vazado** — `|||` no texto gravado e evidencia de desalinhamento
   que a contagem nao pegou.
7. **Quase-igualdade** — hoje so igualdade exata conta; uma traducao 95%
   identica ao original (o Google desistiu) passa limpa.
8. **Terminologia por par** — a lista de termos suspeitos do paragrafo acima,
   com escopo de idioma (secao 15), mantida junto do glossario: *o termo X no
   original com a forma errada Y na traducao* gera aviso. E o que transforma as
   6.958 sugestoes de reativas em localizaveis.

**Garantia Q1** — *lance perdido e anotacao rompida geram aviso.* As oito
candidatas foram medidas uma por uma nas 6.500 linhas reais antes de virarem
codigo, e **duas nao sobreviveram a medicao** — os numeros estao em 16.3. As que
entraram marcam **347 linhas (5,3%)**, contra as 11 de antes, e nenhuma das 11
deixou de ser marcada.

Tres decisoes de desenho que a implementacao obrigou a tomar, e que o plano nao
previa:

- **A ancora nao precisa de idioma, e por isso o aviso vale nas linhas
  legadas.** A ancora e exatamente a parte do lance que nao muda de lingua, entao
  comparar as dos dois lados dispensa saber a origem. O plano falava de "as
  ancoras de `extract_moves`", e aquela funcao filtra por alfabeto declarado — usa-la
  como esta deixaria de fora justamente o acervo antigo, que e a maior parte do
  banco. `move_anchors` reusa a MESMA `_anchor` (duas definicoes divergindo seria a
  armadilha dos itens 2.8 e 3.6) e dispensa o filtro.
- **A ancora do QA inclui lance de peao; a da correcao nao.** `extract_moves`
  descarta `e4` porque nao ha letra para corrigir; aqui um `h5` que sumiu importa
  tanto quanto um `Nf3` — e sao 2 dos 6 casos reais.
- **O par de idiomas teve de ser levado ate a avaliacao**, porque a heuristica de
  terminologia depende dele. Isso e uma mudanca em R6, e nao um detalhe: as linhas
  do editor ganharam origem e destino nas duas ULTIMAS posicoes (o editor le as
  sete primeiras por posicao), e todo ponto que grava a coluna passou a ler o par
  da propria linha. Um caminho avaliando com par e o outro sem faria a contagem do
  rodape parar de bater com a lista, sem erro nenhum.

### 16.2 As heuristicas precisam de versao — CONCLUIDO

`quality_warning` e materializada (R5/R6) e o backfill so preenche `NULL` —
correto para a coluna nova, insuficiente para heuristica nova: qualquer regra
acrescentada deixa as 200 mil linhas ja avaliadas com o veredito velho, e a
garantia R6 ("o cache de avisos nunca diverge") passa a ser violada exatamente
pela melhoria. Falta o mecanismo: gravar a **versao** das heuristicas
(`PRAGMA user_version` proprio ou metadado) e reavaliar o banco quando ela
sobe — em segundo plano, com progresso e cancelamento, como toda escrita em
massa.

**Garantia Q2** — *as heuristicas de QA tem versao, e muda-las reavalia o
banco.* A marca vive em `db_metadata`, tabela nova da migracao 6 — e nao num
PRAGMA: o `user_version` ja e do schema, e um `application_id` com numero de
versao seria usar um campo que significa outra coisa. Uma tabela de chave/valor
tambem aceita a proxima marca sem migracao nenhuma, que e o desenho que o
`glossario.db` ja usava.

Medido: a migracao 5 -> 6 custa 0,04 s (e so a tabela) e a reavaliacao custa
0,127 ms por linha — 0,89 s nas 6.500 do banco de desenvolvimento, ~25 s nas 200
mil do real, uma vez por mudanca de heuristica. Roda na abertura, com barra de
progresso e cancelamento, como toda escrita em massa.

**Tres decisoes que o plano nao tinha, e a terceira saiu de um defeito que os
testes acharam:**

- **A versao so e gravada quando a reavaliacao TERMINA.** Cancelar deixa a marca
  antiga de proposito: o banco esta metade reavaliado, e dizer que ele esta em dia
  seria mentir de um jeito que ninguem descobre depois — a coluna nao tem como
  acusar que esta velha.
- **E a unica escrita em massa sem backup.** `quality_warning` nao guarda nada que
  o usuario escreveu e e recomputavel a partir do texto, que e exatamente o que a
  operacao faz. Um backup de 115 MB para proteger um bit derivado por linha seria
  custo sem risco correspondente.
- **Banco vazio nao abre janela de progresso.** A primeira versao abria: com a
  marca ausente num banco novo, a abertura montava um dialogo modal para varrer
  zero linha. Quem mostrou foi a suite de janela, que passou de 2 minutos para
  mais de 10 e teve de ser interrompida — o caminho mais comum de todos (banco
  recem-criado) era o unico que ninguem tinha em mente ao escrever a condicao.

### 16.3 O que a medicao mostrou, e as duas candidatas que ela derrubou

**O metodo foi o da secao 14: rodar cada candidata no banco real e LER o que ela
marcava.** Nao contar — ler. Duas das oito passavam por qualquer contagem e
morrem na leitura.

| candidata                          | marcava    | veredito                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **multiconjunto de DIGITOS** | 3 linhas   | **fora.** As 3 sao formatacao correta em portugues: `2500` -> `2.500` (separador de milhar) e "19th and early 20th centuries" -> "seculo XIX e inicio do seculo XX" (numeral romano). O caso que o plano citava, `0. 35`, foi corrigido na origem pela secao 13 e migrado do banco pelo schema 5 — nao ha mais nenhum, e o que sobra da heuristica e ruido                                                                                                            |
| `exchange` -> `troca`          | 178 linhas | **fora.** A maioria esta CERTA: "to exchange the knight" -> "troca o cavalo" e a traducao boa do VERBO. So o substantivo "the exchange" (a qualidade: torre por peca menor) e erro, e separar um do outro exige o CONTEXTO, nao o termo. O diagnostico dizia 31 porque contava so o sentido de qualidade — que e uma leitura, e nao algo que um padrao de texto alcance. Este e o unico ponto em que a medicao achou MAIS do que o diagnostico previa, e o "mais" era ruido |
| `rank` -> `classificacao`      | 2 linhas   | **estreitada para `back rank`.** Uma das duas estava certa: "reached the rank of master player" e o sentido de titulo. "back rank" e sempre a ultima fila                                                                                                                                                                                                                                                                                                                  |

As que ficaram, com o numero de linhas de cada uma no banco de desenvolvimento:

| aviso                                                                                           | linhas |
| ----------------------------------------------------------------------------------------------- | ------ |
| terminologia`Black` -> `Black` (nao traduzido)                                              | 153    |
| terminologia`White` -> `White`                                                              | 107    |
| terminologia`check` -> `cheque`                                                             | 32     |
| terminologia`file` -> `arquivo`                                                             | 18     |
| traducao igual ao original (das cinco antigas)                                                  | 11     |
| terminologia`tempo` -> `ritmo` / `andamento`                                              | 11     |
| terminologia`square` -> `quadrado`                                                          | 8      |
| **lance perdido ou inventado**                                                            | 6      |
| terminologia`piece` -> `pedaco`, `pin` -> `alfinete`                                    | 6      |
| terminologia`castle` -> `castelo`, `sound` -> `som`, `back rank` -> `classificacao` | 3      |
| anotacao rompida, NAG, simbolo,`U+FFFD`, `\|\|\|`, quase-igualdade                             | 0      |

**Os seis zeros nao sao heuristicas inuteis** — sao a medida de que este banco nao
tem essas corrupcoes, o que era o esperado depois da secao 13. Elas existem para o
que vier, e a de anotacao rompida e a unica forma de achar o que execucoes
anteriores a X1 deixaram gravado.

**Duas correcoes de curso durante a implementacao**, as duas achadas por teste:

- **O termo em ingles precisava aceitar plural.** Escrito com `termo`, ele
  perdia "squares", "checks", "files" — e a medicao inicial, feita com o mesmo
  padrao, subcontava. Corrigido com um `s?` opcional, `square` -> `quadrado` saltou
  de 2 para 8 linhas, `check` de 30 para 32, `file` de 16 para 18 e `castle` de 0
  para 1. **Todas as 12 novas foram lidas, e as 12 sao erro de verdade** ("dark
  squares" -> "quadrados escuros", "perpetual checks" -> "cheques perpetuos",
  "switches files" -> "troca de arquivos", "castles queenside" -> "fazem o
  castelo").
- **Nao foi `\w*` generico, e essa e a parte que importa.** Um sufixo livre no
  termo ingles pareceria mais completo e traria um erro caro: `tempo` passaria a
  casar "temporary". O `s?` cobre o que existe (plural) sem abrir a porta para o
  que nao existe.

**A quase-igualdade precisou de duas contas, e a primeira sozinha dava falso
positivo.** `quick_ratio` compara multiconjuntos de caracteres: barato, e nunca
subestima. A unica linha que ele marcava era `is about equal, Z. Hracek-G. Jones, Porto Carras 2011.` -> `é quase igual, ...` — e a prosa FOI traduzida; os 40
caracteres de citacao e que dominam a contagem. O `ratio`, que compara sequencias,
ve o bloco comum e responde 0,822. Encadeados (o barato filtrando o caro, que e a
forma documentada de usar `difflib`), a heuristica marca zero falso positivo e o
custo fica no do barato: 0,027 ms por linha.

**O que a secao 16 NAO fez**, dito para nao ser lido como mais amplo do que e:

- **`!` e `?` sozinhos ficaram fora dos simbolos de avaliacao.** Sao pontuacao:
  "Is this sound?" -> "Isso e correto?" tem um `?` de cada lado por acidente, e uma
  frase que ganha ou perde um ponto de interrogacao na traducao e prosa normal.
- **A terminologia de es/fr/de/it/ru tem so `White`/`Black`.** Aquele caso nao
  depende de saber a forma consagrada de cada lingua — o que se detecta e o termo
  ter ficado em ingles. Os demais estao ausentes de proposito: nao ha medicao
  deles nesta maquina, e a licao da secao 14 e que uma lacuna e melhor do que uma
  regra errada.
- **A versao das heuristicas e uma constante, e nao um hash do arquivo de
  termos.** Um hash pareceria mais automatico e reavaliaria 200 mil linhas a cada
  atualizacao que mexesse num comentario do `Termos-suspeitos.txt`. Quem editar a
  lista a mao sobe a constante ou clica em "Reavaliar QA".
- **Nada aqui corrige nada.** As 347 linhas passam a aparecer no filtro "Avisos
  QA"; corrigi-las continua sendo trabalho de quem revisa, uma linha por vez — com
  o glossario ao lado, que e onde as sugestoes ja estavam.

### 16.4 O que a verificacao fixou

**65 testes novos** (649 -> 706 em `test_core.py`, 69 -> 77 na janela principal) e
**27 mutacoes**, uma por heuristica e uma por decisao do mecanismo de versao. Duas
sobreviveram na primeira rodada, e as duas por motivos que valem registro porque
sao diferentes entre si:

| mutacao                           | por que ela sobreviveu                                                                                                                                                                                                                                     |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| o termo casar no meio de palavra  | **O exemplo do teste nao continha o termo.** Ele afirmava que `pin` nao casa "opening" — e "opening" nao tem "pin" nenhum (o-p-e-n-i-n-g). O teste passava com a fronteira de palavra e sem ela. Corrigido para "opinion" e "spinning", que a tem |
| banco vazio abrir progresso modal | **O script de mutacao errou o alvo.** `if total == 0:` aparece DUAS vezes em `db_tools.py`, e a primeira e do "Zerar Traducoes"; a substituicao pegou aquela. O teste estava certo desde o inicio — o que falhou foi a verificacao dele         |

A segunda e a mais util das duas, e nao pelo codigo: **uma mutacao que sobrevive
tambem pode significar que a mutacao esta errada, e nao o teste.** Distinguir os
dois casos exigiu aplicar a mutacao a mao e rodar o teste sozinho. Sem isso, a
conclusao teria sido "falta um teste" e o teste que ja existia teria ganhado um
irmao inutil.

O primeiro caso e o mesmo padrao que a secao 17 encontrou duas vezes (17.11): o
teste partia de um cenario em que a producao quebrada e a correta produzem o mesmo
observavel. Aqui a forma foi nova — nao um valor padrao, e um **exemplo que nao
exercitava a regra**.

---

## 17. Guardas e navegacao: onde o programa erra em silencio — CONCLUIDO (2026-07-29)

Itens pontuais de correcao, agrupados porque compartilham o modo de falha: a
acao acontece (ou nao acontece) sem nenhuma mensagem, e o usuario segue
confiando no resultado. Origem: varredura da interface e do worker na revisao
de 2026-07-29. Cada um foi conferido no codigo; nenhum tinha teste.

**Entregue: as tres garantias planejadas (R10, T5, V1) e os dez itens.** As
garantias estao na secao 9 da SPEC; o que a verificacao mostrou esta em 17.11, e
inclui duas correcoes ao proprio diagnostico deste item.

### 17.1 "Ir para ID" e "Proximo aviso QA" ignoram o filtro de origem — CONCLUIDO

Os dois caminhos consultam o banco **sem** `source_language`, embora as funcoes
aceitem o parametro e `reload_rows` o passe. Com "Origem: Espanhol" ativo,
digitar um ID ingles calcula o offset na lista **nao filtrada** e seleciona uma
linha espanhola arbitraria — sem mensagem; F7 varre as primeiras N linhas da
tabela inteira usando o total **filtrado** como limite e anuncia o aviso de uma
linha que nao esta na tela. "Exportar QA" passa o filtro corretamente — a
inconsistencia entre caminhos vizinhos e a prova do esquecimento. E a mesma
classe do bug que a garantia R7 fechou: navegar pela posicao errada.

**Garantia R10** — *"Ir para ID" e "Proximo aviso" respeitam o filtro de
origem.* Uma linha em cada um dos dois caminhos: `source_language= self.selected_source_language()` na consulta de offset e na leitura da pagina.

O que o teste precisou ter para valer: o banco de teste tem **seis linhas
inglesas com ids baixos e tres espanholas depois**. Com uma linha de cada, o
offset errado e o certo dao zero, e a producao quebrada fica indistinguivel da
correta — a armadilha que tres testes desta suite ja tinham caido antes (ver a
"Segunda rodada" de 2026-07-27). Com esse desenho, o offset de `ES 0` e 0 no
filtro e 6 na tabela inteira, e as duas mutacoes (uma por caminho) morrem.

### 17.2 Tres ferramentas de escrita em massa rodam durante uma traducao — CONCLUIDO

`reset_translations`, `reset_glossary` e "Corrigir Lances" verificam
`app.is_processing` e recusam com dialogo. **Restaurar BD, Importar CSV e
Aplicar Automaticas nao verificam** — e restaurar um backup enquanto o worker
grava produz um banco que nao e nem o backup nem a execucao, com o cache em
memoria apontando para linhas que ja nao existem. Agravante: os botoes de
"Ferramentas" sao criados anonimos e nao ha como desabilita-los; a guarda tem
de ser a primeira linha de cada acao, com a mesma mensagem das tres que ja
fazem certo.

**Garantia T5** — *nenhuma ferramenta de escrita em massa roda durante uma
traducao.* A guarda virou uma funcao (`_busy_with_translation`) e as **seis**
ferramentas passam por ela — inclusive as tres que ja faziam certo, cada uma com
a sua propria copia da mensagem. Deixar as tres copias de pe seria manter viva
exatamente a divergencia que produziu este item.

**"Backup BD" ficou de fora, e por decisao.** Ele so LE o banco, e a API de
backup do SQLite ve o banco logico — a copia sai consistente com o worker
escrevendo. Recusar negaria a copia justamente a quem quer guardar o estado de
uma execucao longa. Isso esta declarado como limite na secao 10 da SPEC e tem
teste proprio, para nao parecer esquecimento na proxima varredura.

### 17.3 Botoes que engolem o clique — CONCLUIDO

"Reprocessar Falhas" e "Normalizar PGN" comecam com `if app.is_processing: return` — retorno mudo. Clicar durante uma traducao nao faz nada e nao diz
nada ("Corrigir Lances" no mesmo caso abre um dialogo explicando). O botao de
reprocessar tambem nunca e desabilitado junto com os outros. Trocar os dois
`return` por mensagem e uma linha em cada.

**Feito**, pela mesma `_busy_with_translation`. O botao de reprocessar entrou nas
duas listas de estado (`_begin_translation_run` e `reset_buttons`) e tambem na do
normalizador, que poe `is_processing` de pe sem passar por aquela funcao — outra
lista paralela, e vale registrar que ela existe.

### 17.4 A verificacao em massa propaga pela traducao, nao pelo original — CONCLUIDO

"Marcar como verificada" propaga para as linhas do mesmo par cuja **traducao**
e identica — e a unica propagacao possivel (originais identicos ja sao uma
linha so pela UNIQUE), e quase sempre e o que se quer. O risco esta nas
traducoes curtas: se o Google verteu "Checkmate." errado como "Empate.",
verificar o "Draw." -> "Empate." legitimo marca a linha errada junto — dado
por revisado o que ninguem viu, exatamente o que R9 existe para impedir. A
correcao barata: a confirmacao mostra **quantos originais distintos** vao ser
marcados (e quais, ate um limite), em vez de so "N iguais tambem verificadas".

**Garantia V1** — *a verificacao em massa diz o que vai marcar, por original.*

**A analise dizia "a confirmacao mostra", e nao havia confirmacao nenhuma.** A
propagacao acontecia junto com a gravacao e era anunciada DEPOIS, no rodape:
"N iguais também verificadas". Entao o item nao foi mudar uma mensagem — foi criar
o dialogo que faltava, com tres consequencias de desenho:

- **A previa e a escrita leem a mesma consulta** (`_exact_translation_matches`), e
  a escrita recebe os ids que a previa mostrou (`only_ids`). Se o worker gravar
  uma linha com a mesma traducao enquanto o dialogo esta aberto, ela nao entra: o
  usuario nao a viu. Duas consultas em dois lugares nao quebrariam nada visivel —
  elas so discordariam, que e a licao dos itens 2.8, 3.6 e 11.1.
- **A pergunta acontece com a transacao ja comitada e a conexao fechada.** Um
  modal aberto sobre uma transacao de escrita seguraria o banco enquanto ninguem
  clica, e o "Salvar" do worker esperaria o `busy_timeout` inteiro — seria uma
  regressao de C3 introduzida por uma melhoria de V1.
- **A pergunta so aparece quando ha consequencia.** Uma traducao sem gemeas nao
  abre dialogo nenhum: um modal por verificacao viraria ruido e passaria a ser
  clicado no automatico, que e o oposto do que este item quer.

O criterio da propagacao **nao mudou** — continua sendo a traducao identica dentro
do par, que e a unica possivel. O que mudou e que ela se anuncia.

### 17.5 A previa de "Corrigir Lances" esconde a parte irreversivel — CONCLUIDO

A ferramenta rotula **todas** as linhas sem origem do destino antes de corrigir
(secao 11 explica por que), e a previa mostra contagens de correcao — mas nao
diz **quantas linhas serao rotuladas**. Num banco com 200 mil linhas legadas, o
"Sim" afirma "todo o meu acervo veio do espanhol" sem que esse numero tenha
aparecido. Ele so e dito no dialogo de resultado, depois de feito. E uma linha
na previa, com o dado que o `analyze` ja tem.

**A analise errou aqui, e o erro e instrutivo.** O `analyze` **nao** tinha o
dado: ele conhece o escopo (as linhas sem origem entram na varredura), e nunca
contou quantas sao. A contagem teve de ser escrita — `count_adoptable_unknown _source` — e escrevendo-a apareceu uma segunda coisa que a nota nao previa: um
`COUNT(*)` do escopo do `UPDATE` seria um **teto**, e nao o numero. A adocao usa
`UPDATE OR IGNORE`, que pula a linha cuja adocao esbarraria na propria chave (ja
existe o mesmo comentario no par declarado). Num dialogo que nao tem volta, um
numero aproximado e pior do que nenhum, entao a consulta desconta essas linhas
com um `NOT EXISTS` — indexado pela UNIQUE — e o teste confere o numero da previa
contra o que a adocao de verdade faz.

A linha so aparece quando ha o que rotular: um "0 linhas serao rotuladas" fixo
faria o usuario procurar um problema que nao existe, que e o mesmo criterio das
linhas de lances e de comentarios `;` no resumo do worker.

### 17.6 O backup do banco migra a origem antes de copiar — CONCLUIDO

`create_database_backup` abre a origem com `initialize_database` — que roda a
migracao de schema e o backfill. O "backup de seguranca" pre-restauracao pode
entao **alterar o banco de trabalho** antes de copia-lo, e capturar o estado
pos-migracao: se a migracao for a causa do problema que o usuario quer
desfazer, nao ha mais volta. Abrir a origem com `sqlite3.connect` puro copia o
que esta la, como esta.

**Feito**, e a correcao levou junto um segundo motivo que a nota nao mencionava:
`open_database` tambem esta fora. Ele grava `journal_mode = WAL` no arquivo, e
num banco antigo em modo `delete` o "backup" reconfiguraria o original. Ler para
copiar nao precisa de nenhum dos dois.

O teste usa o `_schema3_database` que a secao 9 deixou pronto — um banco escrito a
mao no schema antigo — e afirma tres coisas: a origem continua na versao 3 e sem a
coluna nova, a copia tambem, e o conteudo chega. A terceira e a defesa contra "nao
migrar" virar "nao copiar". Um quarto teste confere que a migracao continua
acontecendo onde ela deve: no banco de trabalho, **depois** da restauracao.

### 17.7 O CSV de traducoes e somente-exportacao na pratica — CONCLUIDO

O fluxo natural — exportar, corrigir 300 traducoes na planilha, importar — nao
faz **nada**: a gravacao respeita T1 (nunca sobrescrever preenchida), entao
toda linha volta como "Sem alteracao", e ate o `verified` editado e descartado
(so e aplicado a linhas inseridas ou preenchidas). A previa e honesta, mas o
usuario descobre depois do trabalho feito. Falta o modo explicito "sobrescrever
existentes" — com backup, contagem propria na previa ("N seriam
sobrescritas"), registro no historico (R2) e reavaliacao de QA (R6), como toda
escrita em massa. T1 continua sendo o padrao; sobrescrever passa a ser uma
decisao, nao um acidente.

**Feito, com o dialogo de tres botoes.** A previa passou a contar as duas coisas
numa passagem so — o que a importacao faria e o que ela deixaria de fazer
(`overwritable`) —, e e isso que permite oferecer a sobrescrita no MESMO dialogo em
que os numeros aparecem, em vez de fazer o usuario escolher o modo antes de ver.
Sim sobrescreve, Nao importa respeitando T1, Cancelar nao importa nada.

Duas decisoes que o item nao previa apareceram ao escrever a gravacao, as duas
sobre o `verified`:

- **Texto identico nao e sobrescrita.** Num CSV exportado e corrigido em parte, o
  igual e a grande maioria; contar essas linhas inflaria o numero do dialogo com
  o que a exportacao devolveu intacto.
- **A coluna `verified` so PROMOVE.** A nota pedia que o `verified` editado
  deixasse de ser descartado, e a leitura ingenua disso — aplicar o valor da
  coluna — teria sido um desastre: um CSV montado a mao nao tem a coluna, e
  `_normalize_import_row` devolve `False` para a ausencia. Aplicada, uma
  importacao de rotina rebaixaria para "pendente" cada linha que voltou igual. A
  ausencia de uma afirmacao nao e a afirmacao contraria. Quando o TEXTO muda, ai
  sim o `verified` cai — a revisao era do texto anterior, e essa demissao e a
  regra que `save_translation` ja aplica ao preencher uma linha vazia.

### 17.8 Buscar `[%eval` no modo "Trecho" devolve lixo — CONCLUIDO

O `LIKE` e montado sem `ESCAPE`: `%` e `_` do texto do usuario viram curinga.
A busca mais natural do dominio — uma tag de comando, que **comeca** com `%` —
e justamente a que quebra. `LIKE ? ESCAPE '\'` mais o escape dos tres
caracteres no padrao.

**Feito**, e o escape ficou junto do `ESCAPE` de proposito (`LIKE_MATCH_SQL` e
`escape_like_pattern` no mesmo lugar): um sem o outro nao da erro nenhum, so
volta a tratar o texto do usuario como curinga. A ordem dentro do escape tambem
importa e esta comentada — a barra primeiro, senao as barras recem-inseridas
seriam escapadas de novo.

O teste que fecha o buraco de verdade nao e o do resultado da busca, e o que
confere que **a contagem e a lista concordam** sob o escape: as duas usam o mesmo
`WHERE`, e escapar em uma so faria a lista paginar por um numero que a tela nao
mostra (garantia R5).

### 17.9 A garantia S5 morre sob `pythonw` — CONCLUIDO

`report_glossary_error` faz `print(...)` **antes** de chamar o handler da
interface — e sob `pythonw`/PyInstaller windowed `sys.stdout` e `None`, entao o
`print` levanta e o handler nunca roda. A funcao que existe para tornar a falha
visivel e a unica que quebra no empacotado. Guarda de uma linha (`if sys.stdout:`), e um teste que simule `stdout=None` — que e exatamente o cenario
que M2/S5 ja ensinaram a testar.

**Feito**, e a guarda cobriu mais do que uma linha: os outros dois `print` crus do
`glossario.py` passaram pela mesma funcao. O do `except` de `add_to_glossary` era
o pior deles — sob `pythonw` ele transformava "nao consegui gravar a regra" num
`AttributeError` no meio do popup do editor, que e justamente o caminho do item
17.10 sobre aquele popup. O `try` em volta cobre tambem um `stdout` fechado (pipe
rompido), que levanta por outro motivo e tem o mesmo efeito.

### 17.10 Miudezas confirmadas da mesma varredura — CONCLUIDO

- `prefer_db=False` e ignorado quando `db_path` e passado (o argumento
  explicito do chamador perde para a conveniencia interna).
- **Worker**: interrompido pelo disjuntor, a barra de progresso congela no
  valor em que estava; uma excecao geral perde a lista de falhas da execucao
  (T4 so e gravada no caminho feliz — a lista anterior fica valendo e
  "Reprocessar Falhas" reprocessa os arquivos errados); o lote e montado sobre
  o texto **cru** mas enviado **limpo** — regras de limpeza que expandem furam
  B1 por fora (a folga de 200 chars segura hoje; e acoplamento, nao garantia).
- `game-BR-2.pgn` (saida com sufixo numerico de colisao) **nao** e reconhecido
  como gerado — confirmado: a terceira execucao da mesma pasta traduz
  portugues para portugues e produz `game-BR-2-BR.pgn`. O `strip_generated _suffix` precisa aceitar o `-N` opcional (idem `-NORM-2` no normalizador).
- **Normalizador de metadados**: uma secao repetida no `spelling.ssp` **apaga**
  as 984 mil entradas da anterior (atribuicao onde devia ser merge — e o jeito
  natural de acrescentar nomes e criar um segundo bloco `@PLAYER` no fim);
  uma falha num arquivo derruba o lote inteiro sem estatisticas parciais; o
  valor corrigido e inserido sem re-escapar aspas.
- **Janelas**: os editores ignoram a geometria salva (o `maximize=True`
  agendado a +50 ms sobrescreve a restauracao — todo o caminho de
  `safe_geometry` esta morto na pratica); o popup "Adicionar ao glossario"
  abre em tela cheia para tres campos e fecha sem validar nem avisar (falha =
  janela fechada = usuario acha que gravou); a janela de historico, modeless
  de proposito (R3), abre maximizada **cobrindo** a lista que deveria
  continuar clicavel.

**As dez foram feitas.** O que vale registrar de cada uma:

| miudeza                      | o que a correcao teve de resolver                                                                                                                                                                                                                                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prefer_db=False` ignorado | Nao basta a resposta bater: o teste confere que o indice**nao e nem aberto**, senao `prefer_db=False` continuaria pagando o custo dele                                                                                                                                                                                         |
| barra congelada              | Ela passou a terminar num estado que SIGNIFICA algo: cheia se concluiu, vazia se nao — cancelada, interrompida ou morta por excecao. O`finally` decide, entao o caminho novo nao pode ser esquecido por um `return`                                                                                                               |
| T4 perdida na excecao        | `failed_count` e `failed_files` foram declarados FORA do `try`: sem isso o tratador nao os alcanca quando a excecao acontece antes da atribuicao. O registro virou uma funcao, com a regra do cancelamento dentro dela — agora ha duas chamadas, e a regra tem de valer para as duas                                            |
| lote medido no cru           | Reagrupado pelo MESMO algoritmo, exposto como indices (`batch_index_groups`), com `create_comment_batches` passando a ser uma casca dele. No caminho comum sai um grupo so e nada muda                                                                                                                                             |
| `-BR-2` nao reconhecido    | `(-\d+)?` no regex, e o mesmo para `-NORM-2`. Um `torneio-2.pgn` continua sendo arquivo do usuario: o `-N` so conta depois de um sufixo de idioma                                                                                                                                                                              |
| secao repetida apaga         | `setdefault` no lugar da atribuicao. Entre blocos vale a regra de dentro de um bloco: o primeiro a definir a chave vence. **O numero da nota estava errado**: o `spelling.ssp` do projeto tem 512.668 grafias de jogador, e nao 984 mil (medido parsear o arquivo real: 1,06 s). O defeito e o mesmo; a escala e a do README |
| aspas nao re-escapadas       | A conversao tinha de entrar nas DUAS pontas — desescapar para comparar com o dicionario, reescapar para gravar. So a segunda era o bug; sem a primeira, um nome com aspas nunca casava                                                                                                                                                |
| falha derruba o lote         | Cada arquivo num`try`, com o motivo contado e logado, e o resultado virando AVISO em vez de "concluida"                                                                                                                                                                                                                              |
| geometria ignorada           | `restore_or_maximize`: sao alternativas, e nao duas configuracoes que se somam. O teste confere tambem que nenhum dos dois editores volta a pedir as duas                                                                                                                                                                            |
| popup em tela cheia          | `maximize=False` e as tres validacoes com mensagem propria. O teste exige que a mensagem nomeie o campo que falta — sem isso ele passava com a validacao do original removida                                                                                                                                                       |

### 17.11 O que a verificacao fixou

**131 testes novos** — 549 -> 649 em `test_core.py`, 79 -> 98 no editor de
traducoes e 57 -> 69 na janela principal — e **23 mutacoes**, uma por correcao.

As duas que sobreviveram na primeira rodada disseram a mesma coisa, por caminhos
diferentes: **o teste afirmava o efeito colateral, e nao o efeito.**

| mutacao                                                 | por que ela sobreviveu                                                                                                                                                                                      |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| a previa de "Corrigir Lances" sem a contagem de rotulos | Havia teste para`count_adoptable_unknown_source` e para o campo `labeled` do `analyze`. Nenhum lia o **texto do dialogo** — o numero podia ser calculado com exatidao e nunca aparecer na tela |
| o popup do glossario sem a validacao do original        | Com os dois campos vazios, a validacao da SUBSTITUICAO dispara: um aviso, a janela aberta e nenhuma regra gravada. O teste afirmava exatamente esses tres, e eles valiam com e sem a correcao               |

A segunda e a mais util das duas, porque o padrao dela e velho: e o mesmo de
"afirmar que um botao esta habilitado sem nunca te-lo desabilitado" (5.1). O teste
partia de um cenario em que a producao quebrada e a correta produzem o mesmo
observavel. As correcoes foram exigir que a mensagem **nomeie o campo que falta**
e acrescentar os dois cenarios que so a validacao do original pega — original
vazio com substituicao preenchida, e original vazio numa regra de limpeza (que
dispensa a substituicao, e nao o padrao).

**Tres afirmacoes do diagnostico nao sobreviveram**, e as tres ficaram
registradas no proprio item — a conclusao certa so se entende ao lado da errada:

| onde  | o que a nota dizia                      | o que era                                                                                                                  |
| ----- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 17.4  | "a confirmacao mostra os originais"     | Nao havia confirmacao nenhuma: a propagacao acontecia junto com a gravacao e era anunciada depois                          |
| 17.5  | "com o dado que o`analyze` ja tem"    | Ele nao tinha, e escrever a contagem revelou um segundo problema — um`COUNT(*)` do escopo seria um teto, e nao o numero |
| 17.10 | "apaga as 984 mil entradas da anterior" | 512.668, medido no arquivo real. O defeito era exatamente o descrito; so a escala estava inflada                           |

A terceira e a mais barata de todas de evitar, e por isso vale registra-la: o
numero certo estava escrito no README (`~513 mil nomes de jogadores`) desde antes
da varredura.

**O que a verificacao NAO alcanca**, dito para nao ser lido como mais amplo do que
e: os testes de janela conferem `maximize=False` interceptando a chamada, e nao o
tamanho real da janela na tela. Medir geometria de verdade depende do gerenciador
de janelas e seria um teste que falha por motivo alheio; o que se protege aqui e a
decisao no codigo.

---

## 18. O banco nao sabe de onde cada traducao veio — CONCLUIDO (2026-07-29)

A tabela `comments` guarda o texto e o par de idiomas — e nada mais. Nao ha
arquivo de origem, partida, numero do lance nem execucao. Consequencias diretas
para quem traduz um livro:

- a lista do editor e `ORDER BY id` — ordem de insercao, misturando todos os
  PGN ja processados; **nao existe ordem de leitura da obra**;
- nao ha progresso por livro ("faltam 120 comentarios do capitulo 7");
- nao ha como reverter "tudo que a execucao de ontem gravou";
- nao ha como mostrar, um dia, a posicao do lance comentado — validar lance e
  nao-objetivo (secao 1 da SPEC) e continua sendo, mas **exibir o contexto** ao
  revisor e outra coisa, e hoje e estruturalmente impossivel.

A `UNIQUE (original, origem, destino)` e o coracao do reuso — o mesmo
comentario em 12 livros e uma linha, uma traducao, uma revisao — e **nao deve
ser tocada**. Contexto entra por uma tabela de **ocorrencias** ao lado
(`occurrences`: comentario -> arquivo, partida, indice), N para 1, gravada pelo
worker que ja tem todos esses dados na mao durante a extracao. O editor ganha
filtro por arquivo e ordenacao por ocorrencia; as estatisticas ganham progresso
por obra; e o esquema fica pronto para o dia em que uma FEN por ocorrencia
fizer sentido.

E a unica mudanca de esquema proposta nesta revisao, e a decisao arquitetural
que convem tomar **antes** de crescer o resto: cada melhoria do editor que
nascer sem ela (17, 19) nasce para ser refeita.

**Entregue: o esquema 7, quatro garantias novas (O1-O4) e os tres consumidores
— filtro por arquivo com ordem de leitura no editor, progresso por obra nas
estatisticas e o registro pelo worker.** Reverter uma execucao ficou de fora e
esta dito em 18.7. O que a medicao mudou no desenho esta em 18.6.

### 18.1 A tabela: o contexto entra AO LADO, e nao dentro

```sql
CREATE TABLE occurrences (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id    INTEGER NOT NULL,   -- -> comments.id
    source_file   TEXT NOT NULL,      -- caminho absoluto do PGN
    game_index    INTEGER,            -- 1..n, contado pelas tags [Event ...]
    comment_index INTEGER NOT NULL,   -- 1..n, ordem de leitura NO arquivo
    move_number   INTEGER,            -- ultimo lance antes do comentario
    recorded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file, comment_index),
    FOREIGN KEY(comment_id) REFERENCES comments(id) ON DELETE CASCADE
)
```

Quatro decisoes, cada uma com o que ela impede:

- **A chave natural e `(source_file, comment_index)`, sem `comment_id`.** Uma
  posicao da obra tem um dono. Com o `comment_id` na chave, reprocessar um
  arquivo cujo comentario da posicao 5 mudou de texto deixaria as duas
  afirmacoes no banco, e a ordem de leitura escolheria por sorteio qual
  aparece.
- **`game_index` e `move_number` aceitam nulo** porque podem faltar de
  verdade: um comentario antes do primeiro lance da partida nao tem lance
  anterior. Um zero ali se confundiria com medicao — e apareceria na tela como
  "lance 0".
- **A `FOREIGN KEY` e declarativa.** O SQLite so a aplica com `PRAGMA foreign_keys = ON`, que este programa nao liga (mesmo caso de
  `comment_history`). Quem apaga comentario em massa e o "Zerar Traducoes", e
  ele derruba as tabelas juntas — ver O4.
- **Nao ha coluna de FEN.** O item pedia o esquema "pronto para o dia em que
  uma FEN fizer sentido", e pronto significa **existir a linha em que ela
  penduraria**, nao uma coluna que ninguem escreve. Uma coluna sempre nula em
  200 mil linhas nao e preparo; e peso morto com cara de recurso.

**Um indice novo, `(comment_id, source_file, comment_index)`.** A UNIQUE ja
indexa o caminho de ida (arquivo -> posicoes, que e o filtro e a ordem); este e
o de volta (comentario -> onde ele aparece), e cobre a consulta inteira. **Um
terceiro indice, `(source_file, comment_id)`, foi medido e recusado**: ele
economizou 3 ms de 207 no progresso por obra e 20 ms de 121 no menu de
arquivos — nao paga o custo de escrita numa tabela que o worker grava em lote.

### 18.2 O contexto sai do PGN, e o movetext e lido sem os comentarios

`comment_reading_context` recebe o conteudo do arquivo e os spans dos
comentarios, e devolve `(partida, lance)` para cada um. Ela roda sobre uma
copia do texto com **os spans trocados por espaco nos mesmos offsets**
(`_blank_spans`), e essa e a decisao que faz o resultado valer:

- comentario de livro cita lance a vontade ("melhor era 14. Bxf7"). Lido junto
  com o movetext, o lance CITADO no comentario 1 seria a posicao do comentario
  2 — um numero errado com cara de medido;
- um `[Event` dentro de um comentario nao inventa partida nova.

O lance e recortado **pela partida**: sem isso, um comentario colado nas tags
da partida 2 herdaria o lance 41 da partida 1 e afirmaria com confianca uma
posicao que nao existe. Sem lance antes dele, o valor e `None`.

Tres recortes do que conta como numero de lance, e todos vieram de casos reais:

| recusado                    | por que                                                                                                                                                        |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `+0.35` no movetext       | Decimal.**Este foi encontrado pelo teste**: a primeira versao devolvia "lance 0"                                                                         |
| `[Date "2011.??.??"]`     | Linha de tag. A data COMPLETA (`2011.05.12`) ja cai na regra do decimal; a forma com `??` — comum em PGN de banco de dados — nao, e viraria o lance 2011 |
| `; ver a partida 99. Kh1` | Resto de linha de comentario`;`, que este programa nem traduz                                                                                                |

E um aceito, que existe para impedir a correcao larga: **`1. 0-0` continua
sendo o lance 1.** Recusar todo digito depois do ponto apagaria o roque escrito
com zeros, que aparece em PGN antigo. O que caracteriza decimal e o digito
COLADO no ponto — o mesmo criterio que a secao 13.2 usou no achatamento.

O indice conta os comentarios **aproveitados**: um `{}` vazio nao vira linha no
banco, entao nao ocupa posicao. Ocupando, o indice do vizinho pularia um numero
e a ordem de leitura teria um buraco que nada explica.

### 18.3 Gravar: o arquivo em disco e a verdade sobre a obra

O worker chama `resolve_comment_ids` (texto -> id, no par, em lotes como a carga
de cache) e `record_occurrences`, depois dos lotes de cada arquivo e **antes**
do `break` do disjuntor: as traducoes que aquele arquivo conseguiu ja estao no
banco, e aquele e o unico momento em que o programa tem a procedencia na mao.

**O conjunto do arquivo e SUBSTITUIDO, e nao mesclado.** Se o PGN encurtou, as
posicoes que sobravam nao existem mais, e mante-las deixaria o banco afirmando
que o comentario 2 daquele arquivo e um texto que ninguem le mais ali. O preco
esta dito porque e real: uma execucao interrompida no meio de um arquivo grava
so as posicoes que conseguiu traduzir, e a obra aparece menor do que e ate a
execucao seguinte — que encontra o resto no cache e completa o registro.

Duas consequencias que o log precisa dizer, e diz:

- um comentario **sem linha no banco** (falhou na traducao, ou foi esvaziado
  pela limpeza) nao vira ocorrencia: nao ha para onde apontar. O numero e
  contado e anunciado — "a obra tem 1.200 posicoes" e diferente de "tem 1.200,
  40 ainda sem traducao";
- o caminho e normalizado (`abspath`) **dentro** de `record_occurrences`, que e
  a unica porta pela qual caminho entra na tabela. `cap01.pgn` e `.\cap01.pgn`
  sao o mesmo arquivo, e duas grafias dariam duas obras no filtro, cada uma com
  metade do livro.

### 18.4 O editor: um controle novo, e a ordem que segue dele

Um menu **"Arquivo"** na barra dos filtros, com "Todos os arquivos" e uma
entrada por obra do par. Escolher um arquivo filtra a lista **e** a poe em
ordem de leitura; "Todos os arquivos" volta ao `id`, que e o que a lista sempre
foi.

**Nao ha um seletor de ordem, e a ausencia e a decisao.** Escolher um arquivo E
pedir a obra em ordem de leitura — ninguem quer o capitulo 7 na ordem em que as
traducoes dele entraram no cache. E sem arquivo a ordem de leitura nao existe:
o mesmo comentario esta em varios arquivos, e ordenar pela primeira ocorrencia
de cada um custaria uma agregacao da tabela inteira por pagina, que e
exatamente o que a garantia R5 proibe. O rotulo da pagina passa a dizer
"· ordem de leitura", porque uma lista que reordena sem avisar parece
embaralhada.

Duas coisas que este item obrigou a arrumar antes:

- **Todos os filtros da lista passaram a sair de um lugar so**
  (`list_filters`/`list_query_args`). A garantia R10 nasceu de duas consultas
  que recebiam um filtro a menos; o filtro por arquivo teria sido a terceira, e
  a ORDEM seria a quarta — porque "quantas linhas vem antes deste id" deixa de
  ser "quantas tem id menor" no momento em que a lista se ordena por ocorrencia.
- **O rodape do original diz onde ele foi lido**, com preferencia pelo arquivo
  que esta aberto: quem le o capitulo 7 nao pode ver a posicao do mesmo
  comentario no capitulo 1 — e verdade, responde outra pergunta, e na tela passa
  por erro. Quando a traducao serve a varias posicoes, o rodape diz quantas: e a
  informacao que muda o que o revisor faz.

**O rodape passou por tres versoes, e quem as corrigiu foi a TELA.** A primeira
punha o texto na mesma linha do rotulo "Original:", encostado a direita, com duas
posicoes por extenso. Numa captura do app de verdade o resultado era ilegivel: o
Tk corta o que nao cabe, e encostado a direita ele corta o **comeco** — o rotulo
aparecia como `Original: · comentário 2 | cap02.pgn ...`, sem o nome do arquivo,
que e justamente a parte que responde a pergunta. As tres correcoes, cada uma
medida em `winfo_reqwidth` (faixa de 596 px, janela de 1280):

| mudanca                           | por que                                                                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| linha propria, ancorada a oeste   | Na linha do rotulo sobravam 596 px menos os 70 do "Original:", e o corte caia no comeco. Em linha propria a faixa e toda dele, e o que falta sai do FIM         |
| uma posicao por extenso, nao duas | Duas posicoes de nome longo pediam 728 px                                                                                                                       |
| um localizador, nao dois          | O lance e o que um leitor de xadrez usa; o indice do comentario e a ordem da extracao, que ninguem ve. Ele entra so quando nao ha lance. Os dois somavam ~90 px |

Depois das tres: **258 px** no caso comum (`cap01.pgn`, uma posicao), com 338 de
sobra. No pior caso medido — nome de capitulo de 41 caracteres com 12 posicoes —
sao 631 px, e **35 px estouram**: perdem-se ~6 caracteres do fim de "(a mesma
tradução)", com arquivo, partida, lance e a contagem inteiros na tela. A ordem dos
pedacos foi escolhida para que o corte caia sempre no menos importante.

O rodape **sai do grid** quando nao ha procedencia, em vez de ficar como rotulo
vazio: as linhas sem ocorrencia sao a maioria de um banco antigo, e uma faixa em
branco acima do texto em 201.607 delas seria altura roubada do comentario para nao
dizer nada. E o mesmo padrao do aviso de conflito do editor de glossario.

A escolha e lembrada **pelo caminho**, e nao pelo rotulo do menu (o rotulo
ganha a pasta quando dois nomes coincidem, entao amanha pode significar outro
arquivo). Um arquivo lembrado que nao esta mais na lista cai em "Todos os
arquivos": uma lista vazia sem explicacao e o pior desfecho de um filtro
lembrado.

### 18.5 As estatisticas: progresso por obra

"Estatisticas do BD" ganhou um bloco por arquivo — posicoes, comentarios
distintos, verificadas com porcentagem, pendentes e avisos QA — cortado em 20
obras, com o corte dito na ultima linha (o resumo e um `messagebox`, que nao
rola nem se copia; ver a secao 19, item 7).

O numero mais facil de errar aqui e o de trabalho: **o progresso conta
comentarios distintos**, e nao posicoes. Somando `verified` sobre o `JOIN`, um
comentario verificado que aparece tres vezes viraria tres verificacoes e o
progresso passaria de 100%. As posicoes, essas sim, contam a repeticao — e o
tamanho do livro.

Num banco sem ocorrencia nenhuma o bloco **nao fica vazio**: ele diz que as
traducoes ja gravadas nao tem procedencia e que ela e registrada ao processar o
PGN de novo. A leitura obvia de um bloco em branco seria "o programa nao
registrou", que e a conclusao errada.

### 18.6 O que a medicao mostrou, e a decisao que ela derrubou

Medido num banco **sintetizado** na escala do banco do usuario — 201.500 linhas
e 200 mil ocorrencias em 100 arquivos, ~1.900 comentarios distintos por arquivo
com ~13% de repeticao interna. Nao e o banco real (esta na maquina do usuario);
a distribuicao esta dita para o numero poder ser refeito.

**A primeira escrita do filtro por arquivo era um `EXISTS`, e ela estava
errada.** `EXISTS` e correlacionado: o SQLite varre `comments` e pergunta linha
por linha. O `IN` com subconsulta independente vira uma lista que ele percorre
pelo indice do arquivo, buscando cada comentario por `rowid`. As duas dizem a
mesma coisa — pertence ao conjunto, uma vez — e custam isto:

| consulta                                     | `EXISTS` | `IN`           |
| -------------------------------------------- | ---------- | ---------------- |
| pagina em ordem de leitura, um arquivo       | 831 ms     | **1,6 ms** |
| total do filtro                              | 70 ms      | **0,6 ms** |
| pagina em ordem de id, com filtro de arquivo | 51,7 ms    | **0,5 ms** |

O plano de execucao e que explica: com `EXISTS`, `SCAN comments`; com `IN`,
`SEARCH comments USING INTEGER PRIMARY KEY` alimentado por `SEARCH occurrences USING INDEX (source_file=?)`. **A forma que parecia mais natural era 500 vezes
mais lenta**, e nada na tela teria denunciado — 831 ms por pagina passam por
"o banco esta grande".

Com o `IN`, tudo o que tem arquivo escolhido ficou **mais barato que o caminho
sem filtro**, porque a obra e um recorte pequeno:

| operacao               | com arquivo | sem arquivo (como antes) |
| ---------------------- | ----------- | ------------------------ |
| pagina (offset 0)      | 2,0 ms      | 0,5 ms                   |
| pagina (offset 1.700)  | 3,7 ms      | —                       |
| resumo por status      | 0,8 ms      | 34,8 ms                  |
| offset do "Ir para ID" | 2,2 ms      | 24,5 ms                  |

Os dois custos que sobraram estao dentro de acoes que nao acontecem por tecla
digitada, e ficam declarados:

- **menu de arquivos: 137 ms**, so na abertura da janela e na troca de par. E
  um `GROUP BY` sobre as ocorrencias do par, por definicao.
- **progresso por obra: 207-309 ms**, dentro de "Estatisticas do BD". A
  agregacao le todas as ocorrencias, tambem por definicao. Isso reforca o item
  7 da secao 19 (estatisticas fora do clique) em vez de contradize-lo.

E a migracao: **0,05 s** para o banco de dev de 6.500 linhas, porque ela cria
uma tabela e mais nada. Ver O2 para por que nao ha backfill.

### 18.7 O que ficou de fora, dito por extenso

- **Reverter "tudo que a execucao de ontem gravou" NAO foi entregue.** A
  ocorrencia registra `recorded_at`, entao da para ver QUANDO uma posicao foi
  lida, mas reverter uma execucao e apagar traducoes — decidir entre o que a
  execucao inseriu e o que ela reaproveitou do cache, e o que foi revisado a
  mao depois. Isso pede uma tabela de execucoes e uma decisao de produto que
  este item nao tem; o backup continua sendo o caminho de volta.
- **As linhas ja gravadas continuam sem procedencia**, e nenhuma heuristica vai
  dar uma a elas (O2). Elas so aparecem em "Todos os arquivos", e nao existe
  filtro "sem arquivo": ele seria um anti-join da tabela inteira por interacao,
  e a garantia R5 vale para os filtros novos como vale para os velhos.
- **A FEN por ocorrencia**, que era o proposito declarado de "esquema pronto".
  Continua fora, e agora ha onde pendura-la.
- **O CSV nao leva ocorrencia.** Importar traducoes cria linhas sem
  procedencia, como as legadas. Levar o contexto no CSV muda o formato do
  arquivo, e isso conversa com a exportacao TMX (secao 19, item 8).

### 18.8 O que a verificacao fixou

**59 testes novos em `test_core.py`** (706 -> 765) e **32 na janela de edicao**
(98 -> 130), e **40 mutacoes**.

**Uma sobreviveu, e ela e inalcancavel de proposito.** O `ORDER BY` da ordem de
leitura termina em `, id` como desempate, e a `UNIQUE(source_file, comment_index)` faz os indices de um arquivo serem distintos — entao os minimos
de dois comentarios diferentes tambem sao, e o desempate nunca decide nada. Ele
fica porque o filtro e de UM arquivo, e no dia em que for de uma obra inteira
(varios arquivos) os minimos passam a poder empatar; o preco de deixar e uma
clausula, e o de tirar e uma pagina que repete linha sem erro nenhum. Esta
escrito no codigo para nao ser lido como protecao ativa.

**Tres sobreviveram na primeira rodada e viraram teste**, e as tres sao padroes
que esta suite ja conhecia:

| mutacao                                | o que ela mostrou                                                                                                                                                                                           |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| linha de tag deixa de ser recortada    | **O exemplo nao exercitava a regra.** `[Date "2011.05.12"]` ja e recusado pela regra do decimal, entao o teste passava com a checagem e sem ela. A forma que precisa dela e `[Date "2011.??.??"]` |
| comentario`;` deixa de ser recortado | O mesmo: com um`2. Nf3` depois do `;`, o lance certo vinha dali e a checagem nao era exercitada. O `;` tem de ser a ultima coisa antes do comentario                                                  |
| o rodape ignora o arquivo aberto       | **A afirmacao era sobre a presenca, e o efeito e a ORDEM.** O rodape mostra duas posicoes, entao "cap02 aparece no texto" valia com e sem a preferencia                                               |

Depois disso, as duas metades da guarda de movetext ganharam **uma mutacao
cada** (linha de tag e `;` separadas): juntas, um teste que exercitasse so uma
delas passaria por metade certa.

**Duas correcoes ao proprio codigo NAO sairam de mutacao nenhuma**, e vale
registrar de onde sairam:

- **de um teste:** o `+0.35` no movetext virava "lance 0". A regra que faltava —
  decimal e o digito colado no ponto — e a mesma da secao 13.2, e o teste do roque
  `0-0` esta ao lado dela para que a proxima correcao nao seja larga;
- **da MEDICAO:** o filtro por arquivo em `EXISTS` custava 831 ms por pagina. Vinte
  e nove mutacoes mortas nao diriam nada sobre isso — o `EXISTS` estava correto, e
  so era 500 vezes mais lento (18.6);
- e **da TELA:** o rodape da procedencia aparecia cortado pelo comeco, sem o nome
  do arquivo. Os testes leem `cget("text")`, e o texto estava certo — o que estava
  errado era onde ele caberia (18.4).

Tres formas de erro que teste verde nao pega: uma regra que ninguem escreveu, uma
consulta certa e lenta, e um texto certo que nao cabe.

**O que a verificacao NAO alcanca:**

- o numero da partida e do lance vem de `[Event` e do ultimo numero de lance, e
  nao de um leitor de PGN. Um arquivo com tags fora de ordem, ou sem `[Event`,
  conta como uma partida so — os testes afirmam isso como comportamento, e nao
  como acerto. Ler PGN de verdade para melhorar esses dois numeros e trabalho de
  outro tamanho, e nao e o que este item precisava para dar ordem de leitura a obra;
- a largura do rodape foi medida por `winfo_reqwidth` num script, e **nao virou
  teste**: geometria de janela depende do gerenciador de janelas e do tema, e o
  teste falharia por motivo alheio (a mesma decisao registrada em 17.11). O que os
  testes protegem e o FORMATO do texto — uma posicao, um localizador — que e o que
  a medicao mostrou ser a variavel que importa.

---

## 19. O fluxo do tradutor profissional — CONCLUIDO (2026-07-30); o item 11 em 2026-08-03

O editor foi construido para revisar uma linha; um livro sao vinte mil. Os
itens abaixo sao o que separa "da para revisar" de "da para trabalhar o dia
inteiro nisso", em ordem de retorno por esforco. Nenhum exige o esquema novo
(18); os que se beneficiam dele estao marcados — e a **tabela `occurrences` ja
existe**, entao os marcados deixaram de esperar por ela.

**Entregue: os 13 itens, e as garantias F1-F11 (secao 9 da SPEC).** Doze sairam
em 2026-07-30. O item 11 (corretor ortografico de prosa) ficou para depois
porque dependia de um dicionario e de uma dependencia que nao cabia decidir aqui
(19.14); as duas escolhas foram feitas em 2026-08-03 e ele saiu na **secao 26**,
que tambem corrige um numero desta secao — o dicionario e de 5,5 MB, e nao de
~1 MB. O que a verificacao mostrou esta em 19.16, e inclui uma correcao ao
proprio codigo que somente um teste de janela encontrou.

A ordem abaixo e a do plano original (retorno por esforco); a implementacao de
cada um esta no subitem 19.x correspondente.

1. **Lado a lado opcional.** Original acima da traducao, em 6 linhas contra
   12, obriga a rolar a fonte num comentario longo de livro. Um `PanedWindow`
   horizontal alternavel (posicao persistida, como os divisores que ja
   existem).
2. **`Ctrl+F` no lugar certo.** Hoje foca a busca da **lista**; o gesto
   universal e buscar **no texto aberto**. `Ctrl+F` no texto, `Ctrl+L` na
   lista.
3. **Voltar depois de buscar.** Usar a busca como concordancia ("como traduzi
   *outpost* ate aqui?") descarta a pagina em que se estava, sem volta. Uma
   pilha de ids visitados e `Alt+Backspace`.
4. **A linha da lista diz o que importa.** 54 caracteres de cada lado, sem
   marcador de aviso QA e sem idioma de origem — em "Origem: Todos" nao da
   para ver de onde a linha veio sem carrega-la. O `SELECT` da pagina ja quase
   tudo traz; e rotulo.
5. **Diff de verdade na previa de "Aplicar todas"** — dois blocos de texto a
   olho nu para conferir 80 substituicoes; as faixas trocadas ja sao
   calculadas, falta pinta-las.
6. **Contagem de palavras.** A metrica com que tradutor profissional orca,
   mede e cobra — e nao existe em lugar nenhum do programa. Palavras do
   original e da traducao por status, no resumo e por par; `comment_history`
   ja tem carimbo por edicao e daria produtividade por dia sem esquema novo.
7. **Estatisticas fora do clique.** "Estatisticas do BD" roda na thread da
   interface e materializa as linhas com aviso de todos os pares — a unica
   operacao pesada que ficou fora do `run_with_progress` (2.11), e o resultado
   e um `messagebox` que nao se copia nem exporta. Janela propria, copiavel,
   com as contagens de palavras do item 6.
8. **Exportacao TMX.** O acervo de 200 mil pares revisados **e** uma memoria
   de traducao — presa num formato que so este programa le. TMX 1.4 e um XML
   simples (o `id` como `tuid`), abre em OmegaT/Trados/memoQ, e transforma o
   trabalho acumulado em ativo portavel. Incluir o `id` no CSV atual e o passo
   barato imediato (round-trip seguro; hoje o reimport casa por texto).
9. **Selecao em lote na lista** (com 18: por arquivo/obra): marcar a pagina
   como verificada, exportar so a selecao.
10. **Rascunho fora da thread da interface.** A cada 700 ms de pausa na
    digitacao, o JSON inteiro de configuracoes e relido, serializado e trocado
    atomicamente — na thread do Tk. Em disco lento ou com antivirus, isso e
    engasgo na digitacao. Debounce maior e gravacao em segundo plano.
11. **Corretor ortografico do idioma de destino.** O `spelling.ssp` e
    dicionario de **nomes proprios** (tags), nao serve para prosa; um
    dicionario pt-BR (hunspell) sublinhando no editor pegaria os erros de
    digitacao da revisao — que hoje so o proximo leitor ve.
12. **Status alem do binario** — "rejeitada"/"em duvida" e nota do revisor por
    linha; pendente/verificada nao expressa "voltar aqui com o autor".
13. **Requebra em 80 colunas na gravacao** (export format do padrao PGN, o que
    editoras esperam). Veio da secao 13.6, que preservou o fim de linha e deu a
    opcao de BOM mas nao quebrou linha: requebrar exige decidir onde cortar
    dentro do comentario traduzido sem tocar na chave de cache — que e o
    achatado, e esta certo que seja.

### 19.1 Lado a lado: um divisor, e nao dois layouts — CONCLUIDO

Os dois textos passaram a viver num `PanedWindow` proprio, e o botao ao lado dos
controles de fonte troca a orientacao dele. **Um divisor, e nao dois layouts
alternativos**, por duas razoes: a proporcao entre original e traducao continua
sendo do usuario nas duas orientacoes, e trocar passa a ser uma linha
(`configure(orient=...)`) em vez de reconstruir os paineis.

A diferenca nao e de elegancia. Reconstruir destruiria os widgets de texto, e
dentro deles vivem **o texto digitado, a pilha de desfazer do Tk, a selecao e as
marcas de busca** — os quatro perdidos no meio de uma edicao nao salva. A garantia
F1 e exatamente isso.

**A posicao do divisor e gravada por ORIENTACAO** (`texts_sash_y` e
`texts_sash_x`), e no eixo certo: `sash_coord` devolve o par e o valor do outro
eixo e sempre 1, entao gravar sempre o `x` deixaria o divisor vertical com um
numero inutil. `collect_sash_positions` e `restore_sash` — compartilhados com o
editor de glossario — ganharam o eixo como quarto campo opcional, com 0 (o
horizontal) como padrao, que e o que os divisores antigos sao.

### 19.2 `Ctrl+F` no texto, `Ctrl+L` na lista — CONCLUIDO

Uma linha em cada bind, e a troca nao e questao de gosto: `Ctrl+F` e o gesto
universal de "procurar no que estou lendo", e quem revisa um comentario longo o
aperta para achar uma palavra NO TEXTO. Caindo no campo da lista, ele fazia a
coisa mais destrutiva possivel — **a busca da lista troca a pagina**, e o revisor
perdia o lugar em que estava.

O teste destes dois **nao le `focus_get()`**: a suite roda com a janela nao
mapeada (o `root` fica `withdraw`n para nada piscar na tela) e o Tk nao entrega
foco a janela invisivel — ele devolve `None` para o caso certo e para o errado. O
que se confere e a chamada de `focus_set`, interceptada, mais a ligacao da tecla.
E a mesma decisao registrada em 17.11 para a geometria: confere-se a decisao no
codigo, e nao o efeito do gerenciador de janelas.

### 19.3 Voltar depois de buscar — CONCLUIDO

`Alt+Backspace` (e um botao "< Voltar", porque atalho que ninguem descobre nao
devolve pagina a ninguem) desfaz o ultimo SALTO.

**A pilha guarda um retrato, e nao um id** — e essa e a decisao do item. Usar a
busca como concordancia ("como traduzi *outpost* ate aqui?") troca a lista; voltar
para um id que a busca nova nao contem nao e voltar. O retrato leva a linha
aberta, o texto da busca, o status, a origem, o arquivo e a pagina, e `restore_view`
repoe os seis antes de reencontrar a linha.

**So os saltos empilham**: buscar, limpar a busca, ir para um id ou uma pagina,
trocar de filtro/arquivo/par e o F7. Navegar para a linha vizinha nao empilha — um
"voltar" que andasse linha por linha nao devolveria nada a quem revisa um livro.

Duas decisoes menores, e as duas apareceram como mutacao sobrevivente ou como
teste: a pilha e limitada a 50 retratos (uma sessao de revisao dura horas), e um
retrato que nao da para repor **nao trava** a pilha — o proximo assume, porque a
linha pode ter sido apagada por outra janela.

`jump_to_id` foi extraida de `go_to_id` para que o "voltar" use a MESMA maquina de
posicionar: offset calculado na lista filtrada e na ordem ativa. Duas
implementacoes de "posicionar num id" divergiriam no dia em que uma das duas
ganhasse um filtro novo — que e literalmente a historia da garantia R10.

### 19.4 A linha da lista diz o que importa — CONCLUIDO

O rotulo ganhou o **marcador de aviso QA** e o **idioma de origem**, e a pagina
passou a trazer a coluna `quality_warning` (decima posicao da tupla, depois de
tudo o que ja vinha no fim).

**O marcador sai da COLUNA, e nao de reavaliar o texto em Python.** As duas
respostas sao a mesma enquanto R6 valer, e usar a coluna e o que garante que o
marcador concorde com o filtro "Avisos QA" — que tambem le a coluna. Reavaliar
daria uma tela em que a linha nao tem marcador e o filtro a mostra.

A linha reconstruida em memoria depois de uma edicao (`update_current_row_cache`)
recalcula o bit pela MESMA funcao da gravacao. Copiar o bit antigo deixaria o
marcador mostrando o veredito de antes: a linha corrigida continuaria marcada, e a
que passou a ter aviso nao apareceria.

### 19.5 Diff pintado na previa de "Aplicar todas" — CONCLUIDO

As faixas trocadas sao pintadas nos dois lados, e a previa diz quantos trechos
mudaram.

**O ROADMAP dizia que "as faixas trocadas ja sao calculadas", e isso era meia
verdade.** `apply_glossary_pair_with_cursor` calcula as posicoes de cada regra no
texto daquela passagem e as descarta guardando so o cursor — mas o problema maior
e que elas nao serviriam: a segunda regra aplicada **desloca** as faixas da
primeira, e a previa mostra o texto depois de todas. Comparar os dois textos
prontos (`diff_spans`, `SequenceMatcher` por token) responde a pergunta certa e nao
depende de quantas passagens houve.

O diff e por PALAVRA. Por caractere, `torre` -> `Torre` viraria um `T` trocado no
meio de uma palavra inteira pintada de igual, e o que o revisor precisa ver e a
palavra que mudou.

### 19.6 Contagem de palavras — CONCLUIDO

Modulo proprio (`word_count.py`), minusculo, porque a definicao de "palavra" e uma
decisao que precisa estar num lugar so: duas contagens diferentes no mesmo programa
fariam o orcamento discordar do relatorio (garantia F4).

**Palavra e sequencia separada por espaco em branco** — a mesma definicao do `wc -w`, do Word e do OmegaT, que e a que o cliente usa para pagar. `14.Bxf7` conta
como uma. A alternativa, contar so o que tem letra, foi recusada porque daria um
numero MENOR do que aquele pelo qual o tradutor cobra.

**A contagem e em Python, e nao em SQL**, e a decisao custa uma passagem pelo
banco: o SQL contaria espacos (`LENGTH(x) - LENGTH(REPLACE(x, ' ', ''))`), o que
acerta o ORIGINAL — ele e achatado, um espaco entre palavras — e erra a TRADUCAO,
que passou pela mao do revisor e pode ter quebra de linha e espaco duplo. Um
relatorio de orcamento que conta certo de um lado e por aproximacao do outro nao
serve para cobrar.

**Produtividade por dia sai do `comment_history`**, sem esquema novo, e com duas
decisoes ditas: as palavras sao as da traducao NOVA de cada edicao (a diferenca
seria negativa quando o revisor encurta, e "produzi -40 palavras hoje" nao e
metrica de trabalho), e a mesma linha editada tres vezes conta tres — sao tres
passagens de revisao, e o numero e de atividade, nao de acervo.

### 19.7 Estatisticas fora do clique — CONCLUIDO

Janela propria (`stats_window.py`), copiavel e salvavel em `.txt`, com o conteudo
computado por `collect_database_stats` numa thread de trabalho (garantia F5). Era
a ultima operacao pesada fora do `run_with_progress` (item 2.11), e desde a secao
18 ela ficou mais pesada ainda — 1,12 s no banco de 201.500 linhas, com a contagem
de palavras dentro.

O relatorio ficou dividido em duas funcoes: uma que le o banco e uma **pura** que
formata o texto. Os testes atacam as duas juntas, sem janela e sem `messagebox` — o
que antes exigia interceptar um dialogo para conferir um numero.

A janela e **modeless**: o proposito dela e ser consultada ENQUANTO se trabalha —
copiar um numero para o orcamento, ver quanto falta do capitulo. Um modal aqui
seria o `messagebox` de volta, so maior.

O texto e selecionavel mas nao editavel, e a distincao importou na implementacao:
`state="disabled"` no Tk impede tambem a SELECAO, e um relatorio que nao se copia
e exatamente o defeito que o item veio corrigir. A escrita e barrada no `<Key>`,
deixando passar `Ctrl+C`, `Ctrl+A` e as setas.

### 19.8 Exportacao TMX, e o id no CSV — CONCLUIDO

TMX 1.4 escrito **a mao e em blocos**, nao com `ElementTree`: montar a arvore de
200 mil unidades antes de gravar a primeira e o que o item 2.9 tirou da exportacao
de CSV, e aqui custaria mais (cada `<tu>` e um objeto com quatro filhos). Medido:
**1,13 s e 55 MB** para 201.500 unidades.

Tres decisoes do formato, cada uma com o que ela evita:

| decisao                      | por que                                                                                                                                                                                             |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `srclang="*all*"`          | O acervo tem varios idiomas de origem ao mesmo tempo, e`*all*` e o valor que o proprio padrao define para isso. Declarar um so faria toda ferramenta importar o acervo inteiro como se fosse dele |
| origem vazia vira`und`     | `xml:lang=""` nao e valido, inventar `en` seria mentir, e pular as linhas deixaria de fora a MAIORIA de um banco anterior a secao 9.2. `und` e o codigo ISO de "indeterminado"                |
| linha sem traducao fica fora | Uma memoria com o lado de destino vazio nao ajuda ferramenta nenhuma e polui a busca por concordancia de quem a importar                                                                            |

O texto e escapado e os **controles C0 sao removidos**: o XML 1.0 nao os aceita nem
escapados, e um deles no meio de um comentario produz um arquivo que nao abre — o
erro apareceria na ferramenta do usuario, nao aqui. Um TMX cortado no meio e
apagado, como o CSV: ele nao fecha `</body>`, entao nao abre em lugar nenhum, e o
usuario so descobriria isso depois de contar com o arquivo.

**O `id` entrou no CSV, como primeira coluna.** Ele e a unica coluna que identifica
a linha sem depender do texto, e e o que torna o round-trip pela planilha
conferivel. A importacao continua casando por TEXTO — dito como limite na SPEC,
porque exportar um id que a volta ignora e uma promessa pela metade se ninguem
avisar.

### 19.9 Selecao em lote na lista — CONCLUIDO

Uma marca por linha, e uma barra com "Página", "Limpar", "Verificar" e "Exportar".

**A selecao e por ID, e sobrevive a trocar de pagina** — e o que torna "exportar so
a selecao" util em vez de curiosidade: juntar 30 linhas de tres paginas e o caso
real de quem prepara uma entrega. Ela morre na troca de PAR, porque um id do par
anterior nao esta na lista nova e "Verificar" marcaria linhas que o revisor nao ve.

A marca fica FORA do botao da linha (o `CTkButton` nao aceita filho), e isso e o
desenho certo por outra razao: clicar na marca nao pode carregar a linha, e clicar
na linha nao pode marcar. Confundi-las faria o revisor marcar como verificada uma
linha que ele so queria ler.

Duas decisoes da acao em lote:

- **passa pelo mesmo caminho de uma linha so** (`set_translation_verified_by_id`),
  entao cada uma ganha carimbo e historico. Um `UPDATE` em massa seria mais rapido
  e deixaria N linhas verificadas sem historico — e "quem marcou isto, e quando" e
  a primeira pergunta de uma revisao que deu errado (R2);
- **nao propaga para traducoes iguais.** A propagacao tem confirmacao propria
  (V1) porque marca originais que ninguem leu; encadea-la aqui abriria 100 dialogos
  para 100 linhas marcadas, ou — pior — nenhum. A confirmacao diz isso em palavras.

### 19.10 Rascunho fora da thread da interface — CONCLUIDO

Debounce de 700 ms para **2.500 ms**, e a gravacao numa thread (garantia F8).

Quem digita uma frase de comentario para varias vezes por mais de 700 ms — para
pensar, para ler o original —, e cada parada custava reler o JSON inteiro,
serializar tudo e trocar o arquivo de nome. Em disco lento ou com antivirus no
caminho, isso e o programa parando entre duas teclas.

O que roda na thread e SO o disco: os valores sao capturados na thread principal e
o rotulo e escrito de volta por `after` (garantia C1). O snapshot em memoria e
atualizado na thread principal, e nao la, porque a propria janela o le — se a linha
for reaberta antes de a gravacao terminar, o rascunho tem de estar visivel.

**E `update_settings` ganhou um lock.** Duas threads no ciclo ler-alterar-gravar
fazem a segunda ler o disco ANTES de a primeira gravar, e o que a primeira escreveu
desaparece: e a perda que a garantia R4 existe para impedir, agora por corrida em
vez de por snapshot velho. O teste roda 24 threads e exige as 24 chaves.

### 19.11 Corretor ortografico de prosa — CONCLUIDO (2026-08-03)

Ficou por ultimo, e o motivo esta em 19.14. **Feito na secao 26**, depois que as
duas escolhas que ele esperava foram tomadas: `spylls` (hunspell em Python puro,
MIT) e o dicionario pt-BR do VERO, empacotado junto. O item da secao 26 traz a
medicao do filtro de ruido, que e onde o trabalho de fato estava.

### 19.12 Status alem do binario — CONCLUIDO

Schema 8: `review_status` e `reviewer_note`, dois `ALTER TABLE` (nenhuma restricao
muda, entao a tabela nao e reconstruida). Medido: **1,86 s** em 201.500 linhas.

**`verified` continua sendo a autoridade sobre verificada/pendente**, e o campo
novo so refina o lado pendente: `''`, `rejected` ou `doubt`. Guardar "verified"
tambem ali daria dois lugares dizendo a mesma coisa, e um dia eles discordariam sem
nada quebrar — a familia de defeito que a garantia R6 nomeia.

A regra, uma frase, e a garantia F10: **verificar limpa o status, e um status alem
de pendente derruba o verificado.** Rejeitar uma linha verificada e dizer que a
verificacao estava errada; deixar o bit de pe a manteria fora do filtro de
pendentes, e ela nunca voltaria para a fila de ninguem.

**A frase e curta e os caminhos que a implementam eram QUATRO**, e foi por ai que
o item quase escapou: `set_translation_verified_by_id`, `update_translation_by_id`
(o "Salvar e verificar"), `set_exact_translation_matches_verified` (a propagacao) e
`overwrite_translation_by_id` (a importacao). A primeira versao tratou so a
primeira, e um teste de JANELA — "verificar uma linha em duvida limpa o status" —
foi o que encontrou: a linha ficava verificada E em duvida ao mesmo tempo, estado
que nenhum filtro mostra direito. Ver 19.16.

Os dois status novos entraram no botao segmentado da lista, e o `if/elif` que
traduzia rotulo para filtro virou um dicionario: eram dois lugares, e acrescentar um
filtro exigia mexer nos dois — esquecer um dava um botao que nao filtra nada. As
contagens deles aparecem no rodape **so quando existem**; um "Rejeitadas: 0" fixo na
janela de quem nunca usou o recurso e ruido.

O filtro exige `verified <> 1` junto com o status, embora o lockstep torne o outro
caso impossivel pelo caminho do programa. A guarda existe para o `UPDATE` de fora
(uma restauracao pela metade, outra ferramenta), e o teste dela escreve o estado
inconsistente com SQL cru — sem isso a mutacao que removia a guarda sobrevivia, o
que e a mesma discussao da mutacao inalcancavel de 18.8.

### 19.13 Requebra em 80 colunas — CONCLUIDO

`output.wrap_columns` no arquivo de configuracoes, zero (desligado) por padrao. 80
e o export format do padrao PGN.

**So o espaco em branco muda** (garantia F9): as palavras saem na mesma ordem e com
os mesmos caracteres, e um espaco entre duas delas vira uma quebra de linha. E o que
permite requebrar sem tocar na chave de cache — que e o texto achatado, e continua
sendo (13.2).

Quatro decisoes que a implementacao obrigou a tomar:

- **a primeira linha sabe que comeca no meio.** Depois de `12. Nf3 {` sobra menos
  espaco, e a conta e exata (nao uma estimativa) porque os spans sao substituidos da
  direita para a esquerda: nada antes do comentario ainda vai mudar;
- **um `[%...]` conta como UMA palavra.** A garantia X1 gastou uma secao protegendo
  esses spans; quebra-los na gravacao seria desfazer o trabalho no ultimo passo;
- **a quebra e a do ARQUIVO.** O conteudo e lido com `newline=''` para o `\r\n`
  sobreviver (13.6), e inserir `\n` puro daria um PGN de fim de linha misturado — a
  requebra existe para agradar editora, e entregaria um arquivo pior que o sem
  requebra;
- **palavra maior que a linha fica inteira** e estoura a coluna. Cortar no meio dela
  produziria um token que nao existe: requebrar e formatacao, inventar palavra nao.

Custo medido: **277 ms** para requebrar 15.000 comentarios de 60 palavras — o
tamanho do PGN de 40 MB que a secao 20 usa como pior caso.

### 19.14 O item que esperou, e o que ele esperava

> **Resolvido em 2026-08-03, na secao 26.** As tres decisoes abaixo foram
> tomadas: `spylls`, dicionario pt-BR empacotado, portugues so — com a janela
> anunciando a ausencia nos outros seis idiomas. A estimativa de tamanho deste
> item estava errada por 5x: o par `.dic`/`.aff` e de **5,5 MB**, e nao de ~1 MB.
> O texto abaixo fica como estava, porque e o registro do que era sabido quando
> a decisao foi adiada.

**Item 11, corretor ortografico do idioma de destino.** O `spelling.ssp` que o
programa ja traz e dicionario de nomes proprios e nao serve para prosa; um corretor
de verdade precisa de **um dicionario hunspell pt-BR (~1 MB) e de uma dependencia
nova** (`spylls`, `cyhunspell` ou equivalente).

As duas coisas sao decisao de quem mantem o programa, e nao deste item:

- a dependencia entra no `requirements.txt` e no `.spec` do PyInstaller, e muda o
  tamanho e o processo de build do executavel;
- o dicionario precisa ser escolhido (licenca, variante ortografica) e versionado
  junto, ou baixado — e baixar dicionario na primeira execucao e um comportamento
  novo que ninguem pediu;
- e o corretor teria de valer para os SETE idiomas de destino, ou declarar-se
  parcial — a mesma discussao que a lista de termos suspeitos ja teve (16.1).

**O que ficou de fora, ficou inteiro**: nao ha esqueleto, nao ha coluna nula, nao
ha botao desabilitado. Um recurso que nao funciona mas parece existir e pior do que
a ausencia — a mesma decisao que 18.1 registrou sobre a coluna de FEN.

### 19.15 O que a medicao mostrou

Mesmo banco sintetizado da secao 18 (201.500 linhas, 200 mil ocorrencias — ver o
apendice).

| operacao                                      | custo                     |
| --------------------------------------------- | ------------------------- |
| migracao 7 -> 8 (dois`ALTER TABLE`)         | 1,86 s, uma vez           |
| pagina da lista, agora com`quality_warning` | 0,5 ms (igual a de antes) |
| contagem de palavras do acervo inteiro        | 675 ms                    |
| atividade de revisao por dia                  | 1,1 ms                    |
| coleta inteira das estatisticas               | 1,12 s                    |
| exportar TMX (201.500 unidades)               | 1,13 s, 55 MB             |
| exportar CSV (com o`id`)                    | 1,30 s                    |
| requebrar 15.000 comentarios de 60 palavras   | 277 ms                    |

**A coluna nova na pagina da lista nao custou nada** (0,5 ms, o mesmo numero da
secao 18), e valia medir: ela entrou numa consulta que roda a cada interacao, e a
garantia R5 e sobre exatamente isso.

**A contagem de palavras e o unico numero grande, e e por definicao**: ela le os
dois textos de todas as linhas. Os 675 ms sao dentro de uma operacao que o item 7
acabou de tirar da thread da interface — os dois itens se pagam um ao outro, e essa
foi a razao de fazer os dois juntos.

### 19.16 O que a verificacao fixou

**52 testes novos em `test_core.py`** (765 -> 817) e **39 na janela de edicao**
(130 -> 169), e **51 mutacoes**.

**Uma correcao ao proprio codigo saiu de um teste de janela**, e e a mais grave da
secao: `save_changes(mark_verified=True)` nao passa por
`set_translation_verified_by_id` — ele grava pelo `update_translation_by_id` —, e a
regra de lockstep do item 12 estava so no primeiro. O efeito era uma linha
**verificada E em duvida ao mesmo tempo**, que nenhum filtro mostra direito. Procurar
os outros caminhos depois disso revelou mais dois (a propagacao e a sobrescrita pelo
CSV): **quatro lugares escrevem `verified`**, e a frase "verificar limpa o status"
precisava valer nos quatro.

**Tres mutacoes sobreviveram na primeira rodada**, e as tres sao padroes que esta
suite ja conhece:

| mutacao                                        | o que ela mostrou                                                                                                                                                                              |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `while` -> `if` na pilha do "voltar"       | **O cenario dava o mesmo observavel.** Com UM retrato na pilha, desistir no primeiro e continuar terminam os dois em "Nada para voltar". O teste passou a empilhar dois, o de cima morto |
| zerar a contagem de palavras na coleta         | **O teste afirmava o rotulo, e nao o numero.** Ele procurava "Palavras no original:" no texto; a linha aparecia com zero e ele passava. Agora ele confere 14, 11, 2 e 9                  |
| tirar`verified <> 1` do filtro de rejeitadas | **O cenario nao existe pelo caminho do programa** — o lockstep o impede. O teste dele escreve o estado inconsistente com SQL cru, que e o que um `UPDATE` de fora produziria          |

E uma quarta "sobrevivente" era **a mutacao errada, e nao o teste**: o trecho do
regex da requebra estava escrito com escape trocado no script e nao casava com o
arquivo. O script acusa isso (`trecho aparece 0x`), que e a razao de ele conferir a
contagem antes de substituir — a licao do padrao 5 de 2026-07-29.

**O que a verificacao NAO alcanca:**

- a **orientacao** dos textos e conferida por `cget("orient")` e pela chave gravada,
  e nao pelo tamanho dos paineis na tela: medir geometria depende do gerenciador de
  janelas (a mesma decisao de 17.11). O que se protege e que o texto sobrevive a
  troca, que e o que a implementacao escolhida compra;
- o **foco** dos atalhos e conferido interceptando `focus_set`, pelo motivo dito em
  19.2 — a janela da suite nao e mapeada;
- a **thread** do rascunho e conferida por qual thread chamou `update_settings`. Que
  a gravacao nao engasgue a digitacao em disco lento com antivirus e a razao do item,
  e nao da para afirmar num teste;
- o **TMX** e validado como XML e nos campos que o padrao exige, e nao abrindo-o no
  OmegaT. Um arquivo que o `ElementTree` le e que tem `tuid`, `srclang` e os dois
  `tuv` e o que o formato pede; se alguma ferramenta recusar por outra razao, isso
  aparece no uso.

---

## 20. Desempenho e memoria do pipeline — CONCLUIDO (2026-07-30)

Itens medidos ou derivados na revisao de 2026-07-29, todos sem mudanca de
comportamento — so de custo. Nenhum era urgente com os acervos atuais; todos
viravam parede com um livro grande.

O diagnostico original, mantido como foi escrito:

- **`generate_translated_pgn` e O(n·m)**: cada substituicao copia o arquivo
  inteiro (`content[:start] + rep + content[end:]`). Um PGN de 40 MB com 15 mil
  comentarios sao centenas de GB de copia de memoria. Os spans ja vem
  ordenados; uma passada com `"".join` e O(n). E junto: hoje nao ha checagem de
  `cancel_flag` nessa fase.
- **Cada arquivo e lido 3 a 4 vezes** (deteccao de encoding le inteiro, a
  extracao rele, a geracao rele e redetecta). Reaproveitar conteudo e encoding
  da extracao corta metade do I/O.
- **Duplicatas dentro do lote pagam API**: o cache so aprende depois da
  resposta, entao um lote com "Diagram" 30 vezes envia as 30. `dict.fromkeys`
  no lote resolve — e de quebra conserta o contador de "novas traducoes", que
  hoje subnotifica porque a segunda gravacao da mesma chave volta "unchanged".
- **`info_by_file` segura todos os PGN na memoria** a execucao inteira (o
  conteudo normalizado vive duas vezes: na lista de comentarios e nas tuplas de
  posicao). Processar e soltar por arquivo, guardando so o que a adocao (P2) e
  a carga de cache precisam.
- **O `spelling.ssp` e reparseado a cada uso**: 985 mil linhas, ~1,1 s e
  centenas de MB transitorios para normalizar um PGN de 20 KB. O mesmo desenho
  do `glossario.db` resolve — um indice SQLite derivado, com hash do fonte, e
  o botao passa a custar milissegundos.
- **A chave do cache de sugestoes e O(n) por consulta**: uma tupla de 6.958
  elementos e montada e hasheada a cada tecla no editor. Um contador de versao
  do glossario (incrementado a cada recarga) substitui a tupla por um inteiro.

**Entregue: os seis itens, e as garantias D1-D7 (secao 9 da SPEC).** 46 testes
novos (suite de nucleo 817 -> 863, suite completa 1.080 -> 1.126) e 22 mutacoes,
21 mortas e uma investigada em 20.8.

**"Sem mudanca de comportamento" acabou nao valendo ao pe da letra**, e o que
mudou esta dito: o resumo da traducao ganhou a linha dos comentarios repetidos (a
conta nao fechava sem ela — 20.3), o log do "Normalizar PGN" passou a anunciar o
dicionario em vez do arquivo e a construcao do indice quando ela acontece (20.5), e
cancelar durante a gravacao agora **tem** efeito (20.1). O PGN gerado e as
traducoes gravadas continuam byte a byte os mesmos. Tres afirmacoes do proprio diagnostico nao sobreviveram a medicao — o pico
do `spelling.ssp` (20.5), o texto que "vive duas vezes" (20.4) e o tamanho da
tupla (20.6) —, e cada uma esta corrigida no item que a fez.

O que foi medido, antes e depois:

| medida                                                           | antes               | depois                   |
| ---------------------------------------------------------------- | ------------------- | ------------------------ |
| gravar 15.000 comentarios num PGN de 3,2 MB                      | **26.891 ms** | **22,9 ms**        |
| pico dessa gravacao                                              | 15,1 MB             | 7,8 MB                   |
| leituras de cada PGN por execucao                                | 4                   | **2**              |
| pico com 8 arquivos (2.000 comentarios, 50 distintos)            | 16,1 MB             | **5,3 MB**         |
| memoria viva durante a fase da API (1 livro, 15 mil comentarios) | 10,5 MB             | **4,1 MB**         |
| pico da execucao desse mesmo livro                               | 67,4 MB             | 75,5 MB (ver 20.4)       |
| abrir o dicionario de grafias                                    | 1.038 ms / 72 MB    | **29 ms / 2,1 MB** |
| uma tecla no editor, com o glossario real                        | 9,15 ms             | **7,21 ms**        |
| montar a chave do cache de ordenacao                             | 1,75 ms             | 0,0002 ms                |

O metodo das medidas esta em 20.9.

### 20.1 A gravacao do PGN era O(n·m) — CONCLUIDO

O laco antigo refazia o arquivo inteiro a cada comentario, da direita para a
esquerda. O custo cresce com o **produto** do numero de comentarios pelo tamanho
do arquivo, e a curva medida nesta maquina nao deixa duvida:

| comentarios | arquivo | antes     | depois  |
| ----------- | ------- | --------- | ------- |
| 4.000       | 0,8 MB  | 752 ms    | 5,2 ms  |
| 8.000       | 1,7 MB  | 6.552 ms  | 9,6 ms  |
| 15.000      | 3,2 MB  | 26.891 ms | 22,9 ms |

**A gravacao e por PEDACOS, e nao por `"".join`.** O diagnostico pedia o `join`,
e o `join` corrigia o tempo (18,9 ms) pagando com pico: ele monta o PGN de saida
inteiro na memoria ao lado do de entrada e dos pedacos. Medido no PGN de 3,2 MB,
o pico da fase era 15,1 MB com `join` contra 7,8 MB escrevendo pedaco por pedaco
— e os 4 ms de diferenca no tempo sao 0,015% do que o item economizou. Trocar
tempo por pico seria consertar metade do problema, entao `write_pgn_pieces`
recebe uma **funcao** que devolve os pedacos: o fallback de codificacao precisa
percorre-los de novo, e guardar a lista seria a copia que isto evita.

**O `cancel_flag` entrou na fase**, conferido a cada 512 comentarios. A fase toda
custa 23 ms num PGN de 15 mil comentarios, entao o intervalo nao precisa ser
curto; ele existe para o caso extremo — arquivo enorme com requebra ligada. Um
cancelamento devolve `False` **sem gravar nada**: um arquivo de saida pela metade
seria pior do que nenhum.

**Um bug real apareceu no caminho.** `{a} {b}` com os dois comentarios esvaziados
pela limpeza: o span de `{b}` reclamava para tras o espaco que o de `{a}` ja
havia levado, e dois spans sobrepostos, aplicados da direita para a esquerda,
**apagavam todo o resto do arquivo**. Reproduzido, virou teste, e agora ha duas
trancas — o limite do span anterior e a passada unica, em que uma sobreposicao de
um caractere so produz uma fatia vazia. Ver 20.8: a mutacao que tira **so** o
limite sobrevive por causa disso.

**A gravacao por pedacos criou um risco novo, e ele tem teste.** `utf-8-sig` e
`utf-16` escrevem a marca de ordem de bytes na PRIMEIRA codificacao; se um pedaco
passasse a ser um `open` proprio, cada um levaria a sua BOM e o arquivo sairia
ilegivel para qualquer ferramenta. O teste conta as marcas nos bytes, porque no
texto elas sao caracteres invisiveis no meio da prosa e um `assertIn` passaria.

**O comentario de `_comment_line_room` estava errado**, e ficou registrado nele:
ele afirmava que o texto antes do comentario "ja e final" porque a substituicao ia
da direita para a esquerda. Nunca foi — a requebra sempre foi calculada na fase de
montagem, antes de qualquer substituicao. A conta e a mesma; o motivo dito era
outro.

### 20.2 Cada arquivo era lido quatro vezes — CONCLUIDO

Contado com o `open` interceptado, e nao por leitura do codigo: a extracao abria
duas vezes (uma em bytes, para detectar, outra em texto) e a geracao repetia as
duas. `read_pgn_text` le os bytes uma vez, detecta a codificacao **neles** e
decodifica; `detect_encoding_from_bytes` e a metade do criterio que nao precisa de
disco. A execucao passou de **4 leituras por arquivo para 2** — uma na passada
que conta e outra na vez do arquivo, que ja entrega o conteudo para a gravacao.

Medido num PGN de 3,2 MB: `detect_encoding` + `open` custavam 4,2 ms, contra
2,8 ms de `read_pgn_text`. E pouco em disco quente; o que o item de fato entrega e
uma decodificacao completa a menos por arquivo (a deteccao valida a codificacao
decodificando o arquivo inteiro — garantia E4).

Nenhum comportamento muda, e ha teste para isso: `read_pgn_text` devolve o mesmo
texto e a mesma codificacao que `detect_encoding` + `open(newline='')` davam, em
UTF-8 com CRLF, UTF-8 com BOM, cp1252 e UTF-16. O `newline=''` era o que
preservava o `\r\n` do arquivo (ROADMAP 13.6), e `bytes.decode` nao traduz fim de
linha nenhum.

O normalizador de metadados ganhou a mesma leitura unica, pelo mesmo motivo.

### 20.3 Duplicatas dentro do arquivo pagavam API — CONCLUIDO

O cache so aprende a traducao depois da resposta, e o lote inteiro sai antes dela:
um capitulo com "Diagram" trinta vezes enviava as trinta. A lista de cada arquivo
passa por `dict.fromkeys` na primeira passada, e o que vai para os lotes sao os
**textos distintos**. A geracao continua trocando todas as ocorrencias — ela
procura o texto no `translated_map`, nao a posicao — e a tabela `occurrences`
continua recebendo uma linha por ocorrencia (ROADMAP 18 intacto).

**A deduplicacao e POR ARQUIVO.** Entre arquivos quem serve e o cache em memoria,
que ja funcionava; deduplicar globalmente nao economizaria requisicao e faria a
barra de progresso mentir sobre o arquivo em curso.

**Duas contas do resumo estavam erradas, e nao uma.** A primeira e a que o
diagnostico apontou: a segunda gravacao da mesma chave volta `unchanged`, que nao
e contado em contador nenhum, entao 5 comentarios processados apareciam como "2
novas" e mais nada — tres comentarios sumiam da aritmetica. A segunda so apareceu
ao implementar: **o denominador da barra de progresso** era o total com
duplicatas, e com a deduplicacao a barra pararia antes do fim (2 passos de 5).
Hoje o denominador e o numero de distintos, e o total ganhou uma linha que fecha a
conta:

    Total de comentarios detectados: 5
    Comentarios repetidos dentro do proprio arquivo: 3 (traduzidos uma vez so)

A linha **so aparece quando existe**, como a dos lances corrigidos e a dos
comentarios `;`: um "repetidos: 0" fixo faria o usuario procurar um problema que
nao ha.

**Nao ha medida de quanto isso economiza num livro real**, e e melhor dizer do que
inventar: o repositorio nao tem PGN de livro, e a taxa de repeticao interna
depende da obra. O que se mediu foi o comportamento — o comentario repetido sai
uma vez para a API, as quatro ocorrencias voltam traduzidas no arquivo.

### 20.4 O acervo inteiro vivia na memoria — CONCLUIDO

`info_by_file` guardava o resultado COMPLETO da extracao de todos os PGN —
comentarios, posicoes e contexto de leitura de cada um — pela execucao inteira.
Agora a execucao tem duas passadas com papeis diferentes:

- a **primeira** le so o que a adocao (P2) e a carga de cache precisam: os textos
  distintos de cada arquivo, mais as contagens e os comentarios `;`. Nem posicao,
  nem contexto de leitura;
- na **vez de cada arquivo**, e **depois da fase da API**, ele e lido uma vez e
  extraido por inteiro; as posicoes vao para a gravacao e morrem com ela.

**Depois da API, e nao antes** — foi a medicao que decidiu isso. A fase da API
dura minutos (543 lotes no livro medido, ~1 s por lote em rede real), e o conteudo
do PGN nao tem nada a fazer nela. A memoria viva durante essa fase caiu de
**10,5 MB para 4,1 MB**, e o que sai dela e justamente o que cresce com o livro:
num livro de 40 MB, sao 40 MB que deixam de ser segurados por minutos enquanto o
usuario trabalha em outro programa.

| cenario                                           | antes   | depois  |
| ------------------------------------------------- | ------- | ------- |
| 8 arquivos, 2.000 comentarios cada (50 distintos) | 16,1 MB | 5,3 MB  |
| 1 livro, 15.000 comentarios distintos em 9 MB     | 67,4 MB | 75,5 MB |

**O pico de um livro unico subiu 12%, e a decisao foi consciente.** A parte cara
da extracao e o contexto de leitura (`comment_reading_context` copia o conteudo
inteiro para apagar os spans dos comentarios — 174 ms dos 263 ms de uma extracao
de 3,2 MB), e ela agora acontece quando a execucao ja tem os textos e as
traducoes na mao, e nao no comeco, quando quase nada estava alocado. Foram
medidas as duas ordens: extrair antes do laco dos lotes da 71,1 MB de pico e
devolve o conteudo para dentro da fase da API. Preferiu-se o pico de 75,5 MB
**uma vez** a 9 MB segurados **por minutos** — parede se bate no pico, mas o que
o usuario sente numa maquina com outros programas abertos e o sustentado. Baixar
esse pico exige tirar a copia de `comment_reading_context`, que e desenho da
secao 18 e nao deste item.

**A afirmacao do diagnostico estava errada, e virou verdade no meio do caminho.**
"O conteudo normalizado vive duas vezes: na lista de comentarios e nas tuplas de
posicao" — nao vivia: `comments`, `positions` e `occurrences` guardam **o mesmo
objeto** `str`, e o custo era de ponteiros. Mas ler o arquivo em duas passadas
FARIA o texto viver duas vezes (a segunda extracao criaria objetos novos de igual
conteudo, 3,9 MB no livro medido, exatamente no momento da gravacao). Dai
`known_texts`: a segunda extracao recebe os textos que a primeira ja tem e
devolve **os mesmos objetos**. O teste afirma identidade (`assertIs`), e nao
igualdade — `assertEqual` passaria de qualquer jeito, e nao e disso que a memoria
depende.

**Um vazamento apareceu na medicao, e nao na leitura do codigo.** A primeira
versao soltava a lista de textos com um `comentarios_do_lote = None` "de
proposito" — e o pico nao caiu. O motivo: **as variaveis de um laco Python
sobrevivem ao laco**, entao o `info` do ULTIMO arquivo continuava vivo ate o fim
da execucao. A passada virou uma funcao (`_first_pass`), que e o unico jeito
confiavel de nao ter esse tipo de sobra.

### 20.5 O `spelling.ssp` era reparseado a cada uso — CONCLUIDO

Mesmo desenho do `glossario.db`: um indice SQLite derivado, ao lado do fonte,
reconstruido quando o hash do conteudo do fonte muda.

| operacao                                         | antes                             | depois                       |
| ------------------------------------------------ | --------------------------------- | ---------------------------- |
| carregar o dicionario                            | 1.038 ms / 72 MB de pico          | 29 ms / 2,1 MB de pico       |
| construir o indice (uma vez por versao do fonte) | —                                | 2,0 s / 5,4 MB de pico       |
| corrigir uma tag                                 | 0,0005 ms (dicionario em memoria) | 0,048 ms (consulta indexada) |

Dos 29 ms de abertura, **27 sao o hash do fonte** (30,5 MB de SHA-256). Vale
pagar: e o que garante que trocar o `spelling.ssp` por uma versao nova das
classificacoes seja notado, e o `mtime` nao serve (muda quando o arquivo e
reescrito igual e nao muda quando outro toma o lugar dele com a mesma data).

Decisoes, cada uma com o que ela evita:

| decisao                                           | por que                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| leitura em fluxo (`iter_spelling_records`)      | O dicionario inteiro em memoria e o custo que o item vem eliminar; um gerador de eventos serve aos dois consumidores — o`dict` e o banco — com **uma** implementacao do formato                                                                                                                                                          |
| `INSERT OR IGNORE` na chave `(section, key)`  | Reproduz o`setdefault` do dicionario: o primeiro a definir uma chave vence, dentro do bloco e entre blocos repetidos. Sem isso, um `@PLAYER` no fim do arquivo passaria a sobrescrever os nomes do bloco de cima — o defeito de 17.10, de volta pela porta do indice                                                                          |
| `source_hash` gravado por ULTIMO                | Uma construcao interrompida deixa um banco sem a marca, e a carga seguinte o trata como invalido. E a mesma escolha de Q2: a marca significa "isto terminou"                                                                                                                                                                                       |
| zerar por`DROP TABLE`, e nao apagando o arquivo | **Foi um teste que mostrou:** no Windows, remover um `.db` que outra conexao mantem aberto falha, o `except OSError` engolia a falha, e o indice novo era gravado POR CIMA do antigo — com os nomes que ja tinham saido do fonte continuando a responder. Um arquivo que nao e banco nenhum e apagado e a abertura recomeca, uma vez so |
| degradar para o dicionario, com aviso             | O`_internal` do executavel pode estar em pasta sem escrita. O botao continua funcionando, custando o que sempre custou, e o log diz por que                                                                                                                                                                                                      |
| o indice**nao** e versionado                | Diferente do`glossario.db`, e a diferenca e tamanho: 1,1 MB que viajam junto para poupar uma reconstrucao, contra 25,5 MB para poupar 2 s. O `*.db` do `.gitignore` ja o mantem fora. (O fonte, `spelling.ssp`, **e** versionado — o comentario do `.spec` dizia o contrario, e estava errado desde o commit que o adicionou)     |

`correct_spelling_value` aceita o indice **ou** o dicionario, por `getattr(..., "entry", None)` e nao por `isinstance`: os testes do formato passam dicionarios
literais e continuam valendo sem conhecer a classe nova.

**A afirmacao de "centenas de MB transitorios" nao se sustentou.** O pico medido
com `tracemalloc` e de **72 MB** para o arquivo de 30,5 MB — muito, e o suficiente
para justificar o item, mas nao centenas. O numero certo esta na tabela.

O indice guarda **513.797 entradas**, e a construcao ignora **4.495 chaves
repetidas** — o mesmo numero que o dicionario em memoria descartava em silencio.
O log diz as duas coisas.

### 20.6 A chave do cache de ordenacao era O(n) — CONCLUIDO

`order_rules_by_specificity` memoriza por conteudo, e a chave era uma tupla com
uma entrada por regra, montada e hasheada a cada consulta. O editor consulta a
cada tecla digitada.

| medida (glossario real)                   | antes   | depois    |
| ----------------------------------------- | ------- | --------- |
| montar a chave                            | 1,75 ms | 0,0002 ms |
| ordenar com o cache quente                | 1,96 ms | 0,017 ms  |
| uma tecla (`find_glossary_suggestions`) | 9,15 ms | 7,21 ms   |

A lista carregada e uma `VersionedRules`, que traz o proprio numero de versao. O
`id()` nao serviria — uma lista nova reaproveita o endereco de uma coletada —, e
uma versao resolve isso **e** um caso que a chave por conteudo tambem cobria de
graca: a lista alterada no lugar. Por isso **cada mutacao renova a versao**
(doze metodos de `list`, envolvidos num laco para que nenhum fique de fora); sem
isso, uma lista mutada receberia a ordem antiga, com regras que nao estao mais
nela. Uma lista comum — de teste, escrita a mao — continua caindo na chave por
conteudo.

O que sobrou dos 7,21 ms por tecla sao as 7.334 buscas de padrao no texto
(`find_glossary_matches` por regra). E outro item, e nao este.

**O numero do diagnostico envelheceu:** eram 6.958 regras interativas quando ele
foi escrito, e sao **7.334** depois da curadoria da secao 14 (o `@casa@` expande
para 64 regras cada). A medida acima e com o glossario de hoje.

### 20.7 O que os testes protegem

46 testes novos, e cada um deles falha sem a correcao correspondente:

| garantia | o que fixa                                                                            |
| -------- | ------------------------------------------------------------------------------------- |
| D1       | A gravacao e uma passada, sem uma segunda copia do arquivo na memoria                 |
| D2       | Cancelar interrompe a gravacao e nao deixa arquivo pela metade                        |
| D3       | Cada PGN e lido uma vez por passada, e o texto e a codificacao sao os mesmos de antes |
| D4       | Comentario repetido no arquivo vai uma vez para a API, e a conta do resumo fecha      |
| D5       | Conteudo, posicoes e contexto de um PGN nao atravessam a fase da API                  |
| D6       | O indice de grafias responde como o arquivo, e um fonte trocado o reconstroi          |
| D7       | A ordem das regras e identificada por versao, e mutar a lista renova a versao         |

Dois deles medem custo em vez de comportamento, porque as duas familias de
defeito deste secao nao aparecem em teste de igualdade (ver a licao da secao 18):
o cronometro da gravacao (8.000 comentarios em menos de 0,5 s; a versao antiga
levava 6,5 s) e o `tracemalloc` do pico (menos de 3x o tamanho do arquivo). Os
limites sao generosos de proposito — o que eles precisam distinguir e uma ordem de
grandeza, nao a velocidade desta maquina.

### 20.8 A rodada de mutacao

22 mutacoes, 21 mortas. As duas primeiras versoes do script tinham uma mutacao
**invalida** cada — um `NameError` de nome que deixou de existir e um `del` de
variavel de laco vazio —, e as duas deixavam o pytest vermelho sem que teste
nenhum tivesse olhado comportamento. O script passou a distinguir "vermelho com
teste citado" de "vermelho sem teste", que e a checagem que faltava depois do
padrao 5 da secao 16.

**A sobrevivente:** tirar o limite do span anterior no ajuste do espaco vizinho
(`start > fim_anterior` -> `start > 0`) nao deixa nenhum teste vermelho. Nao e
teste inutil: **e guarda redundante**, e a redundancia foi criada por esta secao.
O desastre de `{a} {b}` precisava de DOIS erros — a sobreposicao e a substituicao
da direita para a esquerda —, e a passada unica ja torna a sobreposicao
inofensiva (uma fatia vazia). O limite ficou porque e o que mantem `replacements`
sem sobreposicao, que e o invariante de que a gravacao depende; confiar numa
fatia vazia seria correcao por acidente. O teste diz isso, e o docstring dele
tambem.

Uma segunda guarda redundante foi **apagada** em vez de documentada: a checagem
`if not gravado: return True` em `spelling_index_is_stale` — a comparacao com o
hash ja responde "precisa reconstruir" quando a marca nao existe (`None` nunca e
igual a um hash).

### 20.9 O metodo das medidas, para poder ser refeito

- **Maquina**: a mesma da secao 18 (Windows 10, Python 3.13). Todo numero e o
  melhor de 3 a 5 execucoes, com o cache de paginas quente.
- **Arquivos de medida**: PGN sinteticos, gerados no diretorio temporario. Dois
  formatos, e a diferenca importa: um "so comentarios" (comentario de 180 a 400
  caracteres a cada dois lances) exagera o peso do texto, e um "de livro"
  (movetext na proporcao de uma obra real, comentario ~20% dos bytes) e o que
  vale para os numeros de memoria da execucao. Os dois estao ditos onde
  aparecem.
- **Memoria**: `tracemalloc` (pico e vivo), amostrado tambem **por linha de log**
  do worker — foi assim que o vazamento das variaveis de laco apareceu, e o
  proprio pico contou onde ele acontece.
- **Antes/depois do worker**: o `translation_worker.py` do commit anterior foi
  trocado no lugar do novo (`git show HEAD:...`) e medido no mesmo cenario, com o
  resto do programa igual. Nao e estimativa: sao as duas versoes rodando.
- **Leituras por arquivo**: contadas interceptando o `open` embutido e filtrando
  pelo caminho do PGN.
- **`spelling.ssp`**: o arquivo real de 30,5 MB e 985.829 linhas. A conferencia de
  equivalencia comparou o indice com o dicionario em 21.129 chaves sorteadas
  (semente fixa) e em todos os parametros de secao: zero divergencias.
- **Glossario**: `load_interactive_substitutions()` com o `Substituicoes.txt` do
  repositorio (7.334 regras depois da expansao de `@casa@`).

---

## 21. Instalar sem perder o que ja foi feito — CONCLUIDO (2026-07-30)

O programa nunca teve instalador: distribui-lo era compactar `dist\` e mandar a
pasta. A queixa que abriu esta secao e a que essa forma produz — **"nas proximas
atualizacoes eu nao perderia o que ja fiz de correcoes"** —, e ela nao e um
detalhe de empacotamento: e onde os dados moram.

**O problema, medido.** Ate aqui todo caminho saia de `sys.argv[0]`, ou seja, da
pasta do executavel: glossario, banco, `backups\`, `logs\` e as configuracoes.
Nesta maquina isso e **~350 MB de dados dentro da pasta do programa**, e
atualizar o programa significa trocar essa pasta. Pior: o README mandava copiar
o `Substituicoes.txt` para dentro de `dist\` antes de distribuir, entao um
instalador construido sobre aquela pasta **levaria o glossario junto e o
sobrescreveria** — em silencio, e justamente o arquivo que representa a curadoria
de 5.910 regras.

| o que                              | tamanho aqui          | perder significa                     |
| ---------------------------------- | --------------------- | ------------------------------------ |
| `Substituicoes.txt`              | 294 KB                | as 5.910 regras curadas              |
| `traducoes.db`                   | 4,8 MB (6.500 linhas) | o acervo de traducoes                |
| `backups\`                       | 346 MB                | as copias de seguranca de tudo acima |
| `pgn_tradutor_pro_settings.json` | 803 B                 | preferencias e rascunhos             |
| `glossario.db`, `spelling.db`  | 1,1 MB + 25,5 MB      | nada: derivados, voltam sozinhos     |

### 21.1 A regra: quem decide e como o programa foi iniciado — CONCLUIDO

| inicio                                    | pasta de dados                       |
| ----------------------------------------- | ------------------------------------ |
| empacotado (`sys.frozen`)               | `%APPDATA%\PGN Tradutor Pro\`      |
| do fonte (`python PGN_Tradutor_Pro.py`) | ao lado do script — como sempre foi |
| `PGN_TRADUTOR_DATA=<pasta>`             | vence os dois                        |

A regra dos dois modos e o que atende ao pedido de usar **os dois** ao mesmo
tempo: o app instalado nao enxerga o checkout, o checkout nao enxerga o acervo, e
nenhuma atualizacao toca em nenhum dos dois. A suite continua valendo sem
adaptacao porque ela roda do fonte.

`sys.frozen` e a pergunta certa, e nao o nome do executavel (que pode ser
renomeado) nem `sys.argv[0]` (que muda com o jeito de invocar). A variavel de
ambiente existe para o pendrive, para o teste e para apontar o checkout ao acervo
de verdade de proposito; um valor **vazio** e tratado como ausencia, senao um
`set PGN_TRADUTOR_DATA=` sem valor gravaria o acervo no diretorio de trabalho de
quem chamou.

**Sete lugares derivavam caminho, e um deles so apareceu ao olhar:** o
`spelling.db`. Ele e escrita, e escrita nao pode morar na pasta do programa —
instalado em `C:\Program Files` ela nao e gravavel, e a normalizacao cairia no
caminho degradado (1,0 s e 72 MB por uso, ROADMAP 20.5) em toda execucao, para
sempre, so avisando no log.

O que vem COM o programa nao se moveu: `spelling.ssp`, dicionario-semente e
`Termos-suspeitos.txt` continuam saindo de `__file__`. A distincao ja existia no
codigo e agora tem as duas pontas nomeadas — dado de programa e substituido por
uma atualizacao, dado de usuario nunca.

### 21.2 A primeira execucao depois de instalar — CONCLUIDO

`first_run.prepare_data_dir` cobre as duas situacoes, e **nunca sobrescreve**: a
condicao e sempre "o destino nao existe", e nao "a origem e mais nova" — data de
arquivo nao diz quem tem razao.

- **quem ja usava a pasta distribuida** tem os dados ao lado do `.exe`; eles sao
  **copiados** para a pasta de dados. Copiados, e nao movidos: voltar a versao
  antiga tem de continuar encontrando o que ela espera;
- **quem instalou agora** recebe o glossario que vai dentro do pacote
  (`Substituicoes-inicial.txt`, com outro nome de proposito — um
  `Substituicoes.txt` dentro do pacote seria confundido com o do usuario por
  quem estivesse procurando onde o dele foi parar).

`backups\` e `logs\` **nao** sao copiados: sao centenas de MB, e a primeira
abertura depois de instalar pareceria travada. Ficam onde estao, e o log diz
onde.

A pasta de dados e anunciada no log da abertura. Uma pergunta que o usuario nao
consegue responder olhando a tela ("onde esta meu glossario?") vira chamado de
suporte.

### 21.3 O sandbox dos testes virou o mecanismo do programa — CONCLUIDO

A suite protegia o glossario real substituindo tres funcoes por dublês. Com uma
porta unica, ela passou a usar **a mesma variavel que o programa usa** — e isso
nao e so arrumacao: os dublês escondiam dos testes justamente o codigo que
calcula os caminhos. Duas linhas a menos no `setUpModule` e no `gui_harness`, e o
caminho real exercitado em cada um dos 1.140 testes.

**Um vazamento meu apareceu, e o jeito como ele apareceu vale mais que ele:** um
teste novo definia `%APPDATA%` e depois fazia `pop`, o que **apaga do processo** o
valor de verdade. A suite seguiu sem `%APPDATA%`, e quem falhou foi um teste de
janela em outro arquivo, sem relacao nenhuma com o assunto. Snapshot e
restauracao, nunca `pop` — e o teste que falha longe da causa e o sintoma classico
de estado global vazado.

### 21.4 O instalador — CONCLUIDO E VERIFICADO

`instalador\PGN_Tradutor_Pro.iss` (Inno Setup 6), com a regra que governa o
arquivo inteiro: **ele nao distribui nem toca em nenhum arquivo de dados**. Nao
tem o glossario para sobrescrever.

| decisao                                                             | por que                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PrivilegesRequired=lowest`                                       | Instala por usuario, sem pedir administrador. O programa nao e assinado, e cada dialogo a menos e um passo a menos de SmartScreen. Com os dados fora,`Program Files` tambem funcionaria — o que nao funcionava era a versao anterior |
| nenhum arquivo de dados no`[Files]`                               | O glossario inicial vai dentro do pacote e quem o instala e a primeira execucao, so quando nao ha nenhum. O instalador nao tem como errar naquilo que ele nao carrega                                                                   |
| desinstalar**pergunta** sobre os dados, com "Nao" como padrao | Quem desinstala para reinstalar uma versao nova nao quer perder o acervo por clicar rapido demais                                                                                                                                       |
| `instalador\saida\` no `.gitignore`                             | A receita e versionada; o`.exe` de 77 MB gerado por ela, nao                                                                                                                                                                          |

**Compilado com o Inno Setup 6.7.3, e o ciclo inteiro foi rodado.** Sai um
instalador de 23,4 MB. A primeira versao deste item dizia que o Inno Setup "nao
esta instalado nesta maquina" — **estava**, em
`%LOCALAPPDATA%\Programs\Inno Setup 6\`, e a busca anterior so tinha olhado o
PATH e as duas pastas `Program Files`. Instalado por usuario nao aparece em
nenhum dos tres.

### 21.5 O ciclo, e o que ele protege — CONCLUIDO

`instalador\verificar-ciclo.ps1` roda o que a suite de testes nao alcanca:
instalar, usar, atualizar por cima e desinstalar, com um `.exe` de instalacao de
verdade. As garantias I1 e I4 so existem nesse nivel — nao ha como um teste em
Python afirmar o que o Inno Setup faz com uma pasta.

O que ele confere, na ordem:

| etapa                         | checagem                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------- |
| instalar (`/VERYSILENT`)    | o programa esta la, e**nenhum arquivo de dados** veio junto               |
| primeira execucao             | a pasta de dados nasce em`%APPDATA%` e recebe o glossario inicial             |
| (edita o glossario e o banco) | e o "trabalho do usuario" que o resto tem de preservar                          |
| instalar a 1.0.1 por cima     | **I1**: o glossario continua byte a byte o mesmo (hash), e o banco tambem |
| desinstalar (`/VERYSILENT`) | **I4**: a pasta de dados e o glossario sobrevivem                         |

Ele **se recusa a rodar se ja houver dados** em `%APPDATA%\PGN Tradutor Pro`: o
roteiro escreve nessa pasta e desinstala no fim, e usar o acervo de verdade como
cobaia seria o oposto do que esta secao existe para garantir.

Duas coisas que so apareceram ao rodar:

- **o `MsgBox` do desinstalador travaria uma desinstalacao silenciosa.** Sem
  ninguem para clicar, ele ficaria esperando para sempre — e `/VERYSILENT` e como
  um atualizador ou um script chamam. Hoje o silencio responde o conservador (os
  dados ficam) sem perguntar nada;
- **a receita nao podia ser compilada de outra pasta.** O `DistDir` relativo
  resolve a partir do `.iss`, e o roteiro compila uma copia no `%TEMP%` para
  trocar a versao sem sujar a arvore. Virou `#ifndef`, entao a linha de comando
  manda (`ISCC /DDistDir=...`).

### 21.6 A versao — CONCLUIDO

**Havia tres numeros, e nenhum derivava de outro:** o `pyproject.toml` em
`0.2.1`, parado desde o import inicial (dez secoes atras); o cabecalho
`creationtoolversion="1.0"` do TMX exportado, que viaja para dentro do OmegaT de
quem importa a memoria; e o `1.0.0` que eu tinha escrito no instalador. Um
programa 0.2.1 anunciando-se como 1.0.0 e o tipo de mentira que so aparece quando
alguem tenta descobrir qual versao esta instalada.

Agora ha uma fonte: **`tradutor_pgn.__version__`**, hoje em `0.3.0` — o `0.2.1`
antecede as secoes 13 a 21, e continuar nele seria dizer que nada aconteceu. Dela
derivam, sem copia em lugar nenhum:

| quem                         | como chega la                                                                            |
| ---------------------------- | ---------------------------------------------------------------------------------------- |
| titulo da janela             | `PGN Tradutor Pro 0.3.0` — a primeira pergunta de qualquer suporte                    |
| TMX exportado                | `creationtoolversion`                                                                  |
| recurso de versao do`.exe` | o`.spec` gera o `version_info` e o carimba no executavel                             |
| instalador                   | `GetStringFileInfo(...)` **le do proprio `.exe`**                              |
| `pyproject.toml`           | escrito a mao (o projeto nao e empacotado como biblioteca), e um teste falha se divergir |

**O instalador nao declara mais versao nenhuma.** Ele le a do executavel que
esta empacotando, entao nao existe um segundo numero para esquecer. O `#ifndef`
continua permitindo `ISCC /DAppVersion=...`, que e como o roteiro simula uma
atualizacao sem reconstruir o `.exe`.

**Instalar uma versao mais velha por cima nao acontece mais em silencio**
(garantia I5): o instalador compara com `ComparePackedVersion` — e nao com texto,
onde "0.10.0" < "0.9.0" — e, quando a instalada e mais nova, pergunta. Numa
instalacao silenciosa ele **recusa** e diz por que no log.

Tres armadilhas, todas descobertas rodando o ciclo e nenhuma delas visivel na
leitura:

- **`/SUPPRESSMSGBOXES` responde SIM, e nao o botao padrao.** A primeira versao
  da guarda confiava no `MB_DEFBUTTON2` para recusar em modo silencioso, e a
  versao velha entrava direto — exatamente no caso que mais importa, o do
  atualizador automatico. Hoje o `WizardSilent` decide **antes** de qualquer
  `MsgBox`;
- **`SetupSetting("AppId")` devolve o texto CRU da diretiva**, com o `{{` do
  escape. A chave de registro montada com ele nao existia, a consulta falhava e a
  guarda saia liberando tudo — em silencio. O GUID passou a ser um `#define`
  usado nas duas formas;
- **uma linha do `[Code]` nao pode comecar com `#`.** O preprocessador le
  `#13#10` no inicio da linha como diretiva e aborta com "Unknown preprocessor
  directive", apontando para o meio de um `MsgBox`.

### 21.7 O que falta

Nada nesta secao. O que sobra e escolha de quem mantem: assinar o executavel
(exige certificado pago) e decidir quando `0.3.0` vira `0.4.0` — que agora e uma
linha em `tradutor_pgn/__init__.py`, e o resto acompanha.

---

## 22. A tela diz uma coisa e o programa faz outra — revisao de UI da janela de edicao

Revisao de 2026-07-31. **Os itens 22.1 a 22.9 foram implementados em 2026-07-31
e os 22.10 a 22.14 em 2026-08-01. A secao inteira esta CONCLUIDA.**
Pedido do usuario: uma analise detalhada do
programa com olhos de especialista em UI, com foco na janela "Editar traduções",
e uma varredura profunda por melhorias. O metodo foi o das revisoes anteriores,
em seis varreduras paralelas e independentes: hierarquia visual e descoberta;
custo em gestos do fluxo profissional; estado e perda de dados; acessibilidade
por medicao; as demais janelas; pipeline e indices.

A evidencia veio de duas execucoes, e cada item abaixo diz qual e a dele:
**janela real** (a janela de verdade, aberta em sandbox com o harness da suite
GUI — banco proprio, nada tocou os dados reais), **headless** (a funcao real
chamada com entrada e saida citadas, e o banco de dev de 6.500 linhas em modo
somente-leitura) ou **leitura de codigo** (linhas citadas, sem reproducao — e
que, como manda a secao 11 da SPEC, precisa de teste que falhe antes da
correcao).

O tema que domina: a secao 19 deu a janela um fluxo profissional, e esta revisao
achou o que ficou entre as juntas — em tres familias.

- **Caminhos que descartam texto digitado sem gravar nem avisar.** Oito
  operacoes que trocam a lista gravam a edicao aberta antes; tres nao gravam
  (22.1), e quatro acoes destroem a pilha de desfazer (22.4).
- **A tela afirmando o que o codigo nao faz.** O rotulo de QA avalia sem o par
  de idiomas e diz "sem avisos" numa linha que o filtro marca (22.2); um
  docstring promete um rodape que o metodo nao escreve (22.9); os quatro
  placeholders da janela nunca aparecem, por um bug da biblioteca (22.7); o
  dialogo de Zerar Glossario anuncia 7.325 regras e apaga 5.910 (22.12).
- **O que e invisivel.** Dez dos treze atalhos existem so no fonte; o foco do
  teclado nao tem indicador; o estado ativo do botao "B" no tema escuro e a
  MESMA cor do inativo, byte a byte; e as quatro cores semanticas de rotulo
  reprovam na medicao de contraste em pelo menos um tema (22.8, 22.9).

### 22.1 Tres trocas de lista descartam a edicao aberta — CONCLUIDO (2026-07-31)

Toda operacao que troca a lista recarrega a linha aberta, e `load_item`
sobrescreve o widget de texto. Por isso quase todas gravam antes: `navigate`,
`change_page`, `go_to_page`, `go_to_id`, `apply_search`, `change_file_filter`,
`change_language_filter`, `go_back` — todas chamam `save_changes` na primeira
linha. Tres nao chamavam (as linhas sao as de ANTES da correcao):

| caminho               | linha               | o que o usuario fez                                       |
| --------------------- | ------------------- | --------------------------------------------------------- |
| `toggle_filter`     | edit_window.py:3080 | clicou num filtro de status ("Pendentes", "Avisos QA"...) |
| `clear_search`      | edit_window.py:3103 | clicou em "Limpar" na busca da lista                      |
| `set_review_status` | edit_window.py:2971 | clicou em "Rejeitar", "Em dúvida" ou "Limpar" do status  |

A perda nao e so "nao gravou": o recarregamento chama `set_translation_text` ->
`set_dirty(False)` -> `cancel_draft_save`, que **cancela o rascunho agendado**.
O que o revisor digitou desde a ultima pausa de 2,5 s (`DRAFT_SAVE_DELAY_MS`)
nao esta no widget, nao esta no banco e nao esta no rascunho — sumiu sem
mensagem. O rascunho persistido antes da ultima pausa sobrevive e volta quando a
linha e reaberta; a janela de perda e o intervalo do debounce, que e exatamente
quando se digita.

Demonstrado em janela real (sandbox, 3 linhas semeadas): digitado
`TEXTO DIGITADO E NAO SALVO` na linha 1 e clicado o filtro "Pendentes" — widget
`AAA traducao um`, banco `AAA traducao um`, rascunho `None`. O mesmo gesto via
busca grava: digitado `TEXTO VIA BUSCA` e clicado "Buscar" — banco
`TEXTO VIA BUSCA`. E "Limpar" da mesma barra descarta: `EDICAO ANTES DE LIMPAR BUSCA` digitado com busca ativa, "Limpar" clicado, banco intacto. Buscar grava e
limpar a busca descarta — dois botoes lado a lado, na mesma barra.

`set_review_status` tem um agravante: rejeitar E anotar por que e um gesto so, e
e justamente quem edita a traducao e desiste ("rejeitar e anotar para depois")
que clica "Rejeitar" com texto sujo. Demonstrado: `EDICAO ANTES DE REJEITAR`
digitado, "Rejeitar" clicado — a edicao sumiu do widget e do banco.

**A correcao**, e ela nao foi so `save_changes()` no comeco dos tres. Nos dois
primeiros foi: uma linha cada, na mesma posicao em que os outros oito a tem — e
em `clear_search` ela fica DEPOIS da saida antecipada, porque sem busca ativa o
clique nao troca lista nenhuma e gravar ali seria efeito colateral de um botao
que nao fez nada (carimbaria `updated_at` e o historico de uma linha que
ninguem mandou salvar, contra R1).

Em `set_review_status` a mesma linha, sozinha, cria um bug pior do que o que
conserta. `save_changes` pode recarregar a lista — com o filtro "Avisos QA"
ativo, corrigir o aviso tira a propria linha (R7) — e depois disso
`self.current` aponta para OUTRA, cuja nota o `load_item` acabou de por no
campo. Lendo o id e a nota depois da gravacao, "Rejeitar" carimbaria a linha
seguinte, com a nota dela, e as duas na tela pareceriam certas. Por isso os dois
valores sao lidos ANTES, e a pintura do status na tela so acontece se a linha
aberta ainda for aquela — a mesma regra que a janela de historico segue (R3).
Quem repoe a linha certa e o `reload_rows` + `row_index_for_id` que ja existiam
no fim do metodo.

**A garantia F12 esta na secao 9 da SPEC**: toda troca de lista grava a edicao
aberta antes de recarregar. Cinco testes novos em
`tests/test_editor_windows.py` (`ListSwitchSavesTheOpenEditTests`), e eles olham
o BANCO e nao o widget — o widget e repovoado pelo recarregamento de qualquer
jeito, e afirmar sobre ele passaria com a producao consertada E com a quebrada.

**A rodada de mutacao: cinco mutacoes, cinco mortas, nenhuma sobrevivente.**
As tres primeiras removem o `save_changes` de cada caminho. As outras duas sao as
que valem o registro, porque cada uma protege uma decisao e nao uma linha:

| mutacao                                              | teste que a pegou                                         |
| ---------------------------------------------------- | --------------------------------------------------------- |
| a correcao PARCIAL: id e nota lidos DEPOIS de gravar | `..._writes_to_the_line_the_user_was_looking_at`        |
| gravar tambem na saida antecipada de`clear_search` | `..._with_nothing_searched_does_not_touch_the_database` |

A primeira e a razao de o teste do filtro "Avisos QA" existir: sem ele, a
correcao pela metade — a que qualquer um escreveria — passa nos outros quatro
testes e grava na linha errada em producao.

### 22.2 O rotulo de QA avalia sem o par de idiomas — CONCLUIDO (2026-07-31)

`update_quality_warnings` (edit_window.py:1441, antes da correcao) chama
`evaluate_translation_quality(orig, texto)` sem `source_language` e
`target_language` — e a heuristica 7 de Q1 (terminologia) so roda com o par. A
propria docstring da funcao (review_quality.py:257-260) manda: "quem chama TEM
de passar o par quando o conhece", citando R6. O editor o conhece: `load_item`
guarda `current["source_language"]` e `current["target_language"]` declarando
em comentario que e "o que mantem a avaliacao de qualidade da tela igual a da
coluna materializada" — e `update_quality_warnings` nao os usa.

Reproduzido com a funcao real:

```
evaluate_translation_quality('White has a decisive advantage on the queenside.',
                             'White tem vantagem decisiva na ala da dama.')
-> []                                # o que o rotulo verde da tela faz
mesma chamada com ('en', 'pt')
-> ["Terminologia: 'White' no original e 'White' na tradução."]
                                     # o que a coluna materializada grava
```

Na tela: a linha aberta diz "QA: sem avisos" em verde, a lista mostra "⚠ QA" e
o filtro "Avisos QA" a inclui. E a divergencia que R6 existe para proibir,
agora entre dois pontos da MESMA janela.

O ramo do F7 sob o filtro "Avisos QA" (edit_window.py:2760) tem a mesma
omissao: a linha e selecionada (ela esta na lista pela coluna), mas o flash
"Aviso QA: ..." fica mudo quando o unico aviso e de terminologia. O ramo sem
filtro usa `row_quality_warnings`, que le o par da propria linha, e acerta.

**A correcao.** No rotulo, o par passa a vir de `current_row_languages()` — um
acessor novo, e nao os dois campos de `current` lidos a mao. O acessor existe
porque o par tem de sair do MESMO lugar em dois pontos: o rotulo da tela e a
linha que `update_current_row_cache` remonta em memoria. Com fontes diferentes,
o marcador da lista passaria a depender de a linha ter sido editada nesta
sessao — que e a divergencia de R6, so que por dentro da janela. No F7, a
chamada virou `row_quality_warnings(...)`, a mesma que o ramo sem filtro sempre
usou.

O acessor tambem nao pode ser confundido com `scoped_languages()`, que e o par
do FILTRO: la "Todos" vira `""` de proposito (uma regra de glossario com escopo
nao vale para uma lista que mistura origens), e aqui a pergunta e de que lingua
veio ESTE texto. Sao dois pares diferentes na mesma janela, e trocar um pelo
outro seria um bug silencioso — o docstring de cada um diz qual e qual.

**A correcao achou um segundo defeito no mesmo metodo**, e ele nao estava no
diagnostico: **sem linha aberta, o rotulo anunciava "QA: Tradução vazia."** O
texto do widget vazio produz esse aviso — verdadeiro, e sobre coisa nenhuma —,
entao ele aparecia em ambar ao abrir um banco sem linhas. O ramo `else` que
existia justamente para o caso "sem linha aberta" **nunca era alcancado**, porque
o aviso chegava antes dele: era codigo morto que parecia tratar o caso. Hoje a
saida vem primeiro, e sem linha aberta nao ha veredito na tela.

**A garantia Q3 esta na secao 9 da SPEC.** Seis testes novos em
`tests/test_editor_windows.py` (`QualityLabelUsesTheRowLanguagePairTests`),
sobre o par `('White', 'White', 'pt')` do `Termos-suspeitos.txt` que vem com o
programa — escolhido porque o aviso dele e o UNICO que aqueles textos produzem:
com qualquer outra heuristica disparando junto, o teste passaria sem o par e nao
provaria nada.

**A rodada de mutacao: seis mutacoes, seis mortas.** Quatro delas sao correcoes
PELA METADE — as que alguem escreveria de boa fe:

| mutacao                                                        | testes que a pegaram |
| -------------------------------------------------------------- | -------------------- |
| passar so a ORIGEM, esquecendo o destino                       | 4                    |
| avaliar com par**so quando a origem foi declarada**      | 1 (a linha legada)   |
| consertar o rotulo e deixar o F7 como estava                   | 1                    |
| o rotulo e a linha em memoria lendo o par de fontes diferentes | 1                    |

A segunda e a que mais importa: a terminologia e escopada por DESTINO
justamente para alcancar as linhas legadas, que sao a maioria de um banco
anterior a 9.2 — e a "correcao" que so age com a origem declarada deixaria de
fora exatamente quem mais precisa dela.

**O que os testes NAO provam, dito por extenso:** que a ORIGEM chega a
avaliacao. Nenhuma das 24 entradas do `Termos-suspeitos.txt` tem escopo de par
(sao 14 `pt`, 2 para cada uma das outras cinco linguas, todas por destino),
entao com o arquivo que vem no programa a origem nao muda o resultado de
nenhuma. Ela e passada pela mesma razao que a coluna materializada a passa — as
duas avaliacoes tem de receber os mesmos argumentos, ou a simetria de R6 vale
por coincidencia. Uma entrada com escopo `en>pt` tornaria isso testavel; hoje
nao ha nenhuma.

### 22.3 O retrato do "voltar" nao guarda o modo de busca nem o destino — CONCLUIDO (2026-07-31)

`current_view` (edit_window.py:1896-1903, antes da correcao) guarda id, busca,
status, origem, arquivo e pagina. Faltam dois campos, e cada falta quebra F3 de
um jeito:

- **O modo de busca (Termos/Trecho) — janela real.** Trocar o modo dispara
  `apply_search`, que empilha o retrato — mas o retrato nao diz em que modo a
  busca foi feita, e `restore_view` nao toca no seletor. Demonstrado: busca
  `BB` em "Trecho" acha 1 linha (substring de `BBB`); trocado para "Termos"
  (0 linhas — termo nao casa); "Voltar" repos a busca `BB` **sob o modo
  novo**, nao achou a linha do retrato e caiu no retrato anterior — devolveu o
  revisor a linha 1, nao a linha 2 que ele tinha deixado, dizendo "Voltou para
  o ponto anterior". A SPEC justifica o retrato com "voltar para um id que a
  busca nova nao contem nao e voltar" — o modo muda o resultado da mesma
  busca, entao o argumento se aplica a ele por identico.
- **O destino — leitura de codigo.** A SPEC F3 lista "trocar ... de par" entre
  os saltos que o "voltar" desfaz, e `change_language_filter` de fato empilha.
  Mas o retrato nao guarda o destino: apos trocar pt -> es, `jump_to_id`
  consulta com `self.lang` ainda `es`, nenhum id do par pt esta na lista, e o
  `while` de `go_back` **consome e descarta a pilha inteira** ate "Nada para
  voltar". E o unico salto listado por F3 que, alem de nao voltar, destroi os
  outros ate 49 retratos.

**A correcao proposta acima estava errada — e foi a implementacao que mostrou.**
Acrescentar os dois campos nao entrega F13, porque os campos que JA existiam
guardavam o valor errado. O retrato lia os SELETORES, e o comando de um seletor
roda com o widget ja no valor NOVO: o retrato dizia para onde o usuario estava
indo, e nao de onde vinha.

Medido na janela real, com o editor aberto e uma linha selecionada:

| o usuario foi de | para          | o retrato guardou       |
| ---------------- | ------------- | ----------------------- |
| status "Todas"   | "Verificadas" | **"Verificadas"** |
| origem "Todos"   | "Espanhol"    | **"Espanhol"**    |
| modo "Termos"    | "Trecho"      | **"Trecho"**      |

E o sintoma, na mesma medicao: trocar para "Verificadas" e clicar em "Voltar"
deixava a tela **em "Verificadas"**. Ou seja, o "voltar" nao repunha filtro
nenhum — F3 valia so para a busca, que e o unico campo que o retrato nao lia de
um widget (ele sai de `state.active_search`, que so muda depois de o retrato ser
tirado). O primeiro teste escrito para o modo de busca **passou por
coincidencia** e precisou ser refeito: a linha que a busca achava era a mesma em
que a janela ja estava, entao cair no retrato errado dava o mesmo resultado.

**O retrato passou a sair da consulta, e nao dos seletores.** `reload_rows`
grava em `state.applied_view` os filtros que ELA usou — o que a janela esta
mostrando agora —, e `remember_position` empilha isso mais a linha aberta. Como
`reload_rows` roda em todo caminho que troca a lista, o retrato fica certo para
os seis campos de uma vez, e nao so para os dois que faltavam. O destino sai de
`self.lang` pela mesma razao: `lang` so muda quando a troca de par entra em
vigor, enquanto o menu muda no clique.

Duas consequencias que a mudanca trouxe junto:

- **`remember_position` passou a vir ANTES do `save_changes`** nos cinco
  caminhos que trocam um seletor. A gravacao pode recarregar a lista por conta
  propria (filtro "Avisos QA" + aviso corrigido), e esse recarregamento gravaria
  em `applied_view` o filtro de destino. O retrato tem de ser tirado antes de
  qualquer coisa acontecer.
- **`apply_language_selection` foi extraida de `change_language_filter`**:
  idioma, titulo e o recorte do glossario (S11). Eram essas linhas, presas
  dentro da troca de par, que faltavam ao "voltar" — sem elas ele repunha o
  seletor e a lista voltava ao par certo com **as sugestoes do par que se
  deixou**. Isso nao estava no diagnostico e so apareceu ao escrever o teste do
  glossario.

E o `go_back` ganhou o que faltava para a mensagem dele ser verdade: repor um
retrato mexe nos seletores antes de saber se a linha existe, entao quando
NENHUM da pilha serve a janela ficava com os filtros do ultimo que falhou — e,
depois de o par entrar no retrato, ate em outro idioma. O ponto de partida e
guardado e reposto: "Nada para voltar" passou a querer dizer que nada mudou.

**A garantia F13 esta na secao 9 da SPEC.** Oito testes em
`tests/test_editor_windows.py` (`BackStackRestoresTheWholeViewTests`).

**A rodada de mutacao: seis mutacoes, e na primeira passada uma SOBREVIVEU** —
justamente a ordem `remember_position`/`save_changes`, que nenhum teste
distinguia. Ela nao era guarda redundante: o caminho existe (o unico em que
`save_changes` recarrega sozinho antes de o retrato ser tirado), e o que faltava
era o teste. Escrito o teste, a segunda passada matou as seis:

| mutacao                                                                    | testes que a pegaram |
| -------------------------------------------------------------------------- | -------------------- |
| o retrato lido dos seletores —**a correcao que este item propunha** | 6                    |
| o restore nao repoe o destino                                              | 3                    |
| o restore repoe o destino mas nao reescopa o glossario                     | 2                    |
| o restore nao repoe o modo                                                 | 1                    |
| o retrato tirado depois do`save_changes`                                 | 1                    |
| sem repor o ponto de partida quando a pilha inteira falha                  | 1                    |

A primeira linha e o registro que importa: a correcao descrita no diagnostico,
aplicada sozinha, e derrubada por seis dos oito testes.

### 22.4 Quatro acoes destroem a pilha de desfazer — CONCLUIDO (2026-07-31)

`set_translation_text` (edit_window.py:1639, antes da correcao) chama `edit_reset()`, que apaga as
pilhas de desfazer e refazer do Tk. Passam por ela: "Copiar original",
"Aplicar selecionada", "Aplicar todas" e o "Todos" da busca-e-troca. Ou seja:
as quatro acoes que REESCREVEM o texto em bloco — justamente as que mais pedem
um Ctrl+Z — sao as que o desligam. "Trocar" (uma ocorrencia) edita o widget com
`delete`/`insert` e o desfazer sobrevive, o que prova que nao e decisao: e um
efeito colateral do caminho de carga, que precisa do `edit_reset` para a TROCA
DE LINHA nao "desfazer" para o texto da linha anterior.

Demonstrado em janela real: digitado ` ACRESCIMO`, clicado "Copiar original",
Ctrl+Z -> "Nada para desfazer". O contraste: "Trocar" e depois Ctrl+Z -> a troca
e desfeita. Ha um caminho de volta ("Restaurar" repoe o que esta salvo no
banco), mas ele descarta TUDO, inclusive o que o revisor queria manter.

**A correcao** e um argumento novo em `set_translation_text`, `keep_undo`, e a
pergunta que ele responde e uma so: **a linha aberta mudou?** Trocando de linha
a pilha morre; reescrevendo a MESMA linha ela sobrevive. O padrao continua sendo
apagar, e de proposito — um chamador novo que esqueca o argumento erra para o
lado seguro, que e o unico dos dois em que o erro corrompe dado (ver abaixo).

**Cinco chamadores optaram por preservar**, e nao os quatro do diagnostico: o
"Restaurar" entrou junto, pela mesma regra. Ele era o unico caminho de volta das
outras quatro e descartava TUDO, inclusive o que o revisor queria manter — com a
pilha de pe, deixa de ser um penhasco. Os chamadores de carga (`load_item`, nos
tres ramos dele) e o `HistoryWindow.restore` ficaram no padrao.

**Os separadores sao a metade que faltava.** So preservar a pilha nao basta: sem
desligar `autoseparators` durante a substituicao, o `delete` e o `insert` viram
dois passos, e o primeiro Ctrl+Z deixa o editor **vazio** — o revisor veria a
traducao sumir onde esperava ve-la voltar. A substituicao inteira entra entre
dois `edit_separator()` explicitos, com os automaticos desligados no meio, e uma
acao vira um Ctrl+Z. Isso vale igual para as 80 substituicoes de um "Aplicar
todas": uma acao, um desfazer.

**A garantia F14 esta na secao 9 da SPEC.** Seis testes em
`tests/test_editor_windows.py` (`BlockRewritesKeepTheUndoStackTests`), um por
acao mais o que protege o padrao.

**A rodada de mutacao: seis mutacoes, seis mortas.** As duas primeiras sao as
que importam:

| mutacao                                                                  | testes que a pegaram |
| ------------------------------------------------------------------------ | -------------------- |
| apagar a pilha sempre — o bug original                                  | 5                    |
| **preservar a pilha sem os separadores** — a correcao pela metade | 5                    |
| nunca apagar, nem ao trocar de linha                                     | 1                    |
| cada um dos tres chamadores voltando ao padrao                           | 1 cada               |

A segunda linha e a que justifica o teste de "um passo so": a correcao obvia —
tirar o `edit_reset` e parar por ai — passa por consertada e produz um Ctrl+Z
que apaga a traducao inteira.

E a terceira e a razao de o padrao nao ter mudado: sem `edit_reset` na troca de
linha, um Ctrl+Z traz o texto da linha ANTERIOR para dentro desta, e a gravacao
ao navegar o leva para o banco — escrevendo numa linha a traducao de outra. O
teste que a mata e o unico desta classe que nao e sobre desfazer funcionar, e
sim sobre ele **nao** funcionar.

### 22.5 `navigate` pula uma linha da fila de avisos — CONCLUIDO (2026-07-31)

Com o filtro "Avisos QA" ativo, corrigir o aviso e clicar "Próxima >":
`save_changes` recarrega a lista (a linha corrigida saiu do filtro) e ja
seleciona quem ocupou a posicao dela — que E a proxima da fila. De volta em
`navigate` (edit_window.py:2565-2573), `new_index = index + delta` avanca mais
uma casa: a linha que ocupou o lugar e pulada sem ser vista. E o caso que a
garantia R7 enuncia, com a regra ja implementada em `mark_and_next`
(2841-2851: capturar o id antes de gravar; se `rows[position][0] != id`, a
posicao ja e a proxima) — `navigate` nao a aplica.

**Confirmado antes de corrigir**, que e o que este item precisava por ter
nascido so de leitura. Os testes foram escritos primeiro e rodados contra o
codigo velho, em janela real: com tres linhas com aviso, o filtro "Avisos QA"
ativo e o aviso da primeira corrigido, "Próxima >" caiu em `CCC aviso tres` — a
segunda foi pulada sem aparecer na tela.

**E o F7 tinha a mesma conta, o que o diagnostico nao viu.** O mesmo cenario com
"Próximo aviso QA" caiu tambem em `CCC aviso tres`: `start_offset` sai de
`get_index() + 1`, lido depois da gravacao. Ali o defeito e pior — a fila de
avisos existe justamente para nao deixar nenhuma linha para tras, e o botao que
a percorre era o que pulava.

**A correcao tirou a regra de dentro de `mark_and_next`** e a pos num lugar so,
`index_after_save`, que os tres caminhos agora leem. Ela cabe em duas frases: se
a linha aberta saiu da lista, quem ocupou a posicao dela JA e a proxima, e somar
mais uma casa pula uma traducao; **para tras a conta nao muda**, porque a linha
que vinha antes continua uma casa antes da posicao vaga. Nos tres, o id e a
posicao passaram a ser capturados ANTES do `save_changes`.

**A garantia F15 esta na secao 9 da SPEC.** Cinco testes em
`tests/test_editor_windows.py` (`NavigationAfterASaveThatShrinksTheListTests`):
dois para o defeito (o "Próxima >" e o F7), um para a direcao contraria e dois
para o caso comum, que a correcao nao podia quebrar.

**A rodada de mutacao: cinco mutacoes, cinco mortas**, rodadas tambem contra as
classes que exercitam `mark_and_next` e `navigate` — a regra agora e uma so, e
mexer nela nao pode passar despercebido por esses caminhos:

| mutacao                                             | testes que a pegaram |
| --------------------------------------------------- | -------------------- |
| somar delta sempre — o bug original                | 3                    |
| aplicar a regra**tambem para tras**           | 1                    |
| aplicar a regra mesmo quando a linha FICOU na lista | 3                    |
| `navigate` lendo a posicao depois da gravacao     | 1                    |
| o F7 lendo a posicao depois da gravacao             | 1                    |

As duas do meio sao as que valem o registro: uma regra "sempre pule o +1" quebra
o "< Anterior" e o caso comum de andar na lista, que sao 90% do uso do botao.

### 22.6 Mensagens que se atropelam e somem cedo demais — CONCLUIDO (2026-07-31)

`flash_message` (editor_widgets.py:23-30) agenda `after(1500)` para limpar o
rotulo e **nao cancela o timer anterior**: mensagem A em t=0, mensagem B em
t=1,0 s — o timer de A dispara em t=1,5 s e apaga B, que viveu 0,5 s.
Demonstrado com a funcao real e os `after` capturados. O editor encadeia
mensagens nesse ritmo em fluxos comuns: "Rascunho restaurado" seguido de
"Aviso QA: ..." ou "Voltou para o ponto anterior".

E 1,5 s e pouco para as mensagens que mais importam: "Tradução salva e
verificada; 3 outro(s) original(is) também verificado(s)" tem 74 caracteres —
e a unica noticia de que a gravacao alterou OUTRAS linhas alem da aberta, e nao
ha como rever a ultima mensagem depois que ela some. O mesmo padrao de timer
esta no `_flash` da janela de estatisticas (stats_window.py:110).

**A correcao** fez as duas primeiras coisas da lista acima, e **recusou a
terceira** com um argumento que so apareceu ao olhar de perto para as mensagens
que ela protegeria (esta abaixo).

O id do `after` passou a ficar no proprio rotulo, e `flash_message` cancela o
pendente antes de agendar o seu. O id fica no rotulo, e nao em quem chama,
porque sao tres janelas com um rotulo cada e o unico lugar que as tres
compartilham e `editor_widgets`.

O tempo de tela virou uma funcao do texto, e ela e **pura** — mora em
`editor_common`, que nao importa Tk, e por isso se confere sem abrir janela:

```
Salvo                                              5 car -> 1500 ms (o piso)
Marcada como verificada                           23 car -> 1500 ms
Verificada; 12 outro(s) original(is)...           57 car -> 2565 ms
Tradução salva e verificada; 3 outro(s)...        73 car -> 3285 ms
qualquer coisa muito longa                            -> 6000 ms (o teto)
```

Os 45 ms por caractere saem de uma convencao de leitura, e nao de uma medicao
nesta maquina — ~200 palavras por minuto, palavra media de ~6,3 caracteres com o
espaco, dao ~21 caracteres por segundo. Esta dito assim no codigo, para ninguem
ler o numero como medido. O piso e o que o programa sempre usou; o teto existe
porque um rotulo parado na tela deixa de ser noticia.

**A terceira parte foi recusada, e a razao e que a premissa dela estava
errada.** "Nao ha como rever a mensagem" pressupoe que ela e a noticia; ela e o
RECIBO. As quatro mensagens que relatam efeito em outras linhas — a propagacao
da verificacao, o lote, as regras automaticas — vem todas depois de uma
confirmacao que o usuario leu e aceitou, e a da propagacao lista os originais um
a um antes de agir (garantia V1). Fazer a mensagem ficar na tela ate a proxima
acao criaria um rotulo que envelhece em silencio, para repetir o que um dialogo
ja disse com mais detalhe. Com o tempo proporcional, a de 73 caracteres passou
de 1,5 s para 3,3 s — que e o tempo de le-la.

**E a janela de estatisticas tinha uma copia do defeito** (`_flash` com
`after(2000)` sem cancelar o anterior): clicar "Copiar" e "Salvar .txt" em
seguida fazia o timer do primeiro apagar a mensagem do segundo. Ela passou a
usar a mesma funcao dos dois editores — uma copia que ninguem lembraria de
corrigir junto e exatamente o que o item 3.2 descreve. O editor de glossario
perdeu o `1800` fixo pelo mesmo motivo: era um terceiro numero para a mesma
decisao.

**A garantia F16 esta na secao 9 da SPEC.** Onze testes em
`tests/test_editor_windows.py`, e **nove deles nao abrem janela**: o defeito e
sobre qual `after` dispara quando, e com um Tk de verdade isso viraria um teste
de relogio. Um dublê de janela guarda os agendamentos e o teste os dispara na
ordem que quiser. Os dois que abrem janela existem para provar a ligacao — que o
editor e a janela de estatisticas passam mesmo por aqui.

**A rodada de mutacao: seis mutacoes, seis mortas**, em tres arquivos:

| mutacao                                               | testes que a pegaram |
| ----------------------------------------------------- | -------------------- |
| agendar sem cancelar o anterior — o bug original     | 2                    |
| cancelar mas nao guardar o id novo                    | 3                    |
| voltar ao tempo fixo de 1,5 s                         | 1                    |
| tirar o piso da duracao                               | 3                    |
| tirar o teto da duracao                               | 1                    |
| a janela de estatisticas com o timer proprio de volta | 1                    |

### 22.7 Nenhum placeholder da janela aparece — CONCLUIDO (2026-07-31)

O CustomTkinter 5.2.2 tem um bug de comparacao no `_activate_placeholder` do
`CTkEntry`:

```
if self._entry.get() == "" and self._placeholder_text is not None \
        and (self._textvariable is None or self._textvariable == ""):
```

`self._textvariable == ""` compara o OBJETO `StringVar` com a string — e
`StringVar() == ""` e `False` sempre (executado nesta maquina). Com
`textvariable`, o placeholder nunca ativa. Os quatro campos com placeholder da
janela usam `textvariable`: a busca da lista (556), o "Buscar" e o "Substituir"
do texto (828, 835) e a nota do revisor (866). As capturas de tela confirmam:
os campos aparecem em branco.

Os dois campos do `find_bar` sao os mais atingidos: nao tem NENHUM rotulo alem
do placeholder que nao aparece — dois campos anonimos lado a lado, um que busca
e um que substitui, e trocar os dois e digitar a substituicao no campo de
busca.

**O diagnostico contou quatro campos e sao sete**, em tres arquivos — e o
levantamento mudou o tamanho do problema, para menos. Cada placeholder do
programa foi conferido contra o que ha ao lado dele:

| campo | quem o nomeia hoje |
|---|---|
| `find_bar` "Buscar" | **ninguem** |
| `find_bar` "Substituir" | **ninguem** |
| busca da lista (editor) | o botao "Buscar" na mesma barra |
| nota do revisor | o rotulo "Nota:" |
| busca do editor de glossario | o botao "Buscar" na mesma barra |
| "Teste rápido" do glossario | o rotulo "Teste rápido:" acima |
| palavra de confirmacao do "Zerar" | o rotulo "Para confirmar, digite _delete_ abaixo:" |

Ou seja: **so dois campos ficam anonimos**, e sao os dois que o diagnostico ja
apontava como os mais atingidos. Nos outros cinco o placeholder acrescentava uma
dica — o escopo da busca, o que escrever na nota —, e nao a identidade do campo.
O do dialogo de "Zerar" era o unico com risco de tornar a janela inoperante, e
nao torna: a palavra a digitar esta num rotulo de verdade acima do campo.

**A correcao sao dois rotulos**, e nao um conserto do placeholder. O argumento
nao e so que a biblioteca e de terceiros: **placeholder some na primeira tecla**,
e e exatamente com texto dentro que os dois campos ficam impossiveis de
distinguir — o momento em que a duvida "digitei a busca no campo de troca?"
aparece e o momento em que o placeholder nao estaria mais la. O rotulo fica.

O segundo chama-se **"Trocar por:"** e nao "Substituir:": o botao que aplica
aquele campo se chama "Trocar", e o rotulo tem de usar a palavra do botao.

Os dois campos perderam o `placeholder_text`, que passou a ser peso morto — se a
biblioteca for corrigida um dia, ele viraria uma segunda dica dizendo dentro do
campo o que o rotulo ja diz do lado. Os outros cinco ficaram: eles nao aparecem
hoje e voltariam sozinhos, de graca, no dia em que a comparacao for consertada.

**O escopo da busca da lista nao foi restaurado**, e esta dito no codigo por
que: "Buscar no original ou tradução" e informacao de quem esta comecando, e um
rotulo permanente com essa frase custaria ~230 px numa coluna cujo minimo e 320.

**A garantia F17 esta na secao 9 da SPEC.** Cinco testes em
`tests/test_editor_windows.py` (`NoFieldDependsOnAPlaceholderTests`), um deles
sobre o fato que causa tudo: `StringVar() == ""` e falso. Ele afirma semantica do
`tkinter.Variable`, e nao da biblioteca de widgets — se ela mudar de ideia sobre
o placeholder, a comparacao que ela erra hoje continua sendo essa.

**A rodada de mutacao: seis mutacoes, e na primeira passada uma SOBREVIVEU** — a
que empurra o rotulo para outra FILEIRA do grid, embaixo dos botoes. O teste
agrupava os rotulos so pela coluna, entao um rotulo fora do lugar continuava
"ao lado" do campo aos olhos dele. A chave virou `(linha, coluna)` e a segunda
passada matou as seis:

| mutacao | testes que a pegaram |
|---|---|
| voltar ao placeholder sem rotulo — o bug original | 3 |
| o rotulo do "Trocar por" some | 2 |
| o rotulo existe mas nao e gridado | 2 |
| os dois rotulos trocados de lugar | 2 |
| **um rotulo empurrado para outra fileira** | 1 |
| o placeholder da busca da lista removido junto | 1 |

### 22.8 O que e invisivel: atalhos, foco, o "B", o tema — CONCLUIDO (2026-07-31)

**Dez dos treze atalhos existem so no fonte.** O inventario de
`connect_events`: Ctrl+F, Ctrl+L, Ctrl+B, Ctrl+H, Ctrl+S, Ctrl+Return, Ctrl+Z,
Ctrl+Y, Alt+Backspace, Alt+Left, Alt+Right, F3, F7. Nenhum aparece na
interface — nao ha menu, tooltip (o CustomTkinter nao tem) nem janela de
ajuda; o README documenta tres (Ctrl+F, Ctrl+L, Alt+Backspace). O criterio e
do proprio projeto ("um atalho que ninguem descobre nao devolve a pagina a
ninguem", 19.3) — aplicado ate hoje so ao "< Voltar". O caso extremo e o
**Ctrl+B** (negrito na selecao, restaurado no item 4.1): nao tem botao, nao tem
menu, nao esta no README — e um recurso sem NENHUM caminho de descoberta. A
verificacao adversarial confirmou o achado e o rebaixou de alta para media:
nada funciona errado; e lacuna de descoberta. Correcao barata em duas frentes:
o atalho no rotulo dos botoes que ja existem ("Salvar (Ctrl+S)") e um dialogo
"Atalhos" (F1 e um botao "?"), unico lugar possivel para os que nao tem botao.

**O foco do teclado nao tem indicador.** No fonte instalado do CustomTkinter
5.2.2, o unico widget que reage a `<FocusIn>` e o `CTkEntry` — e o handler so
alterna o placeholder (que nunca aparece, 22.7). Nos dois `tk.Text`, quem tem o
anel de destaque e o `container` (`tk.Frame`), que nunca recebe foco; o
`highlightcolor` nao e configurado. Numa janela com ~30 botoes e 6 campos, o
unico sinal de onde o Tab parou e o cursor piscando dentro de um texto.

**O estado ativo do botao "B" no tema escuro e invisivel** — leitura + hexes:
`toggle_bold_view` (1726-1733) usa `#1f6aa5` para "ativo" e `#1F6AA5` para
"inativo": a mesma cor, byte a byte. No claro o delta e (0, -12, +38) — sutil.
E o mesmo simbolo cobre dois recursos: o botao alterna a FONTE do editor
inteiro; Ctrl+B poe negrito na SELECAO. Quem conhece um atribui ao outro o
mesmo gesto.

**O tema pode trocar no meio e a janela fica pela metade** — leitura da
biblioteca: o programa roda em `set_appearance_mode("System")` e o tracker do
CustomTkinter re-detecta o tema do Windows a cada 30 ms, atualizando os widgets
CTk vivos. Mas `pane_bg`, as cores dos `tk.Text`, as tags de busca/glossario/
diff e as bordas sao lidas UMA vez na construcao (515, 726-738). Uma troca de
tema do Windows com o editor aberto deixa frames escuros com dois retangulos de
texto claros. Correcao: um callback de tema reaplicando as ~10 cores tk, ou
documentar o limite.

**A correcao, nas quatro frentes** (garantia F18, SPEC secao 9). Treze testes em
`WhatWasInvisibleTests` e **catorze mutacoes, catorze mortas**.

**Atalhos: o dialogo, e nao o rotulo dos botoes.** Das duas frentes propostas,
so uma foi feita, e a escolha tem duas razoes. A primeira e alcance: os rotulos
chegam a dez dos treze, e os tres que sobram — `Ctrl+F`, `Ctrl+L` e `Ctrl+B` —
sao justamente os que nao tem botao nenhum, incluindo o unico recurso do
programa sem caminho de descoberta. A segunda e largura: as duas fileiras do
rodape ja pedem 831 e 932 px dos ~1080 da largura minima (medido em 22.10), e
acrescentar "(Ctrl+S)" a sete rotulos e mexer justamente onde nao ha folga. O
"249 px de sobra" que este item citava foi levantado pela analise e **nao
confirmado** pela verificacao adversarial; nao entrou na decisao.

O caminho de entrada e `F1` **e** um botao "?" — um atalho para descobrir
atalhos so serve a quem ja os descobriu. O "?" fica na fileira dos ROTULOS do
rodape, ancorado a direita: e a unica faixa da janela com espaco sobrando (os
rotulos dela sao todos `side=LEFT`), e ajuda nao e uma acao de revisao para
disputar lugar com "Salvar".

A lista vive numa tabela, `KEYBOARD_SHORTCUTS`, **com a sequencia do Tk ao lado
do rotulo** — e e isso que a impede de envelhecer: dois testes comparam a tabela
com os binds reais da janela, nos dois sentidos. Um atalho ligado e nao listado
falha tanto quanto um listado e nao ligado. Sem isso, a tabela seria
documentacao, que e a especie que fica errada em silencio.

**Foco: o bind num widget e o efeito no outro.** Quem recebe o foco e o
`tk.Text`; quem desenha a borda visivel e o `tk.Frame` em volta — por isso o
`highlightcolor` do proprio Text nao resolveria. Os `CTkEntry` ficaram de fora,
e a razao esta no proximo item: a borda deles ja carrega o status de revisao
(F10), e um segundo significado na mesma borda faria as duas informacoes se
apagarem.

**O "B": duas diferencas, e nao uma.** A cor ligada mudou de familia (difere do
desligado nos dois temas — o par anterior era `#1f6aa5` contra `#1F6AA5`, a
mesma cor no escuro) **e** ganhou borda, que e o sinal que funciona para quem
nao distingue dois azuis. E o desligado passou a ser lido do TEMA
(`ThemeManager`), em vez dos hexes do tema padrao transcritos a mao — que
congelavam o botao na aparencia de quem os copiou.

A colisao de simbolo (o botao alterna a fonte de leitura, `Ctrl+B` marca a
selecao) nao virou rotulo novo: o dialogo diz "Ctrl+B — negrito no trecho
selecionado da tradução" com todas as letras, que e a desambiguacao que faltava,
e renomear rotulos e o assunto de 22.10.

**Tema: o gancho existe, e e da biblioteca.** `AppearanceModeTracker.add` chama
o callback com o nome do modo a cada troca; as ~10 cores do Tk puro sairam dos
dois `build_*` e viraram `read_theme_colors`/`apply_theme_colors`, num lugar so.
Duas defesas: o registro esta em `try/except` (o registrador e interno da
biblioteca, e a falta dele nao pode impedir a janela de ABRIR — sem o gancho o
comportamento e o de antes), e o callback sai calado se a janela ja morreu,
porque a lista de callbacks e de CLASSE. Por isso o `close_editor` tambem
desregistra: sem isso, cada abrir-e-fechar deixaria mais um la.

Duas mutacoes existem so por causa dessa lista de classe: "sem a guarda da
janela morta" e "reabrir empilha copias da janela de atalhos" — as duas sao
vazamentos que nao aparecem numa sessao curta.

### 22.9 O contraste, medido — CONCLUIDO (2026-07-31)

Razoes de contraste WCAG calculadas pela formula de luminancia relativa
(headless; fundo claro `#dbdbdb` confirmado por amostragem de pixels da captura
real; escuro `#2b2b2b` do codigo; rotulos CTk de 13 px exigem 4,5:1):

| cor                     | onde                                                | claro            | escuro           |
| ----------------------- | --------------------------------------------------- | ---------------- | ---------------- |
| `#f59e0b` ambar       | "Alterações não salvas", avisos QA, "Em dúvida" | **1,55:1** | 6,6:1            |
| `#dc2626` vermelho    | "Falha ao salvar rascunho", "Rejeitada"             | **3,49:1** | **2,93:1** |
| `#16a34a` verde       | "Salvo", mensagens, "QA: sem avisos"                | **2,38:1** | **4,30:1** |
| `#64748b` cinza       | selecao em lote, procedencia do original, rascunho  | **3,44:1** | **2,98:1** |
| branco sobre`#3b82f6` | linha selecionada da lista (11 px)                  | **3,68:1** | 5,7:1            |
| branco sobre`#fb923c` | ocorrencia atual do Ctrl+F                          | **2,26:1** | **3,57:1** |

O pior par da janela e o ambar no tema claro — 1,55:1 — e e justamente o texto
que avisa que algo esta errado. O vermelho de "Falha ao salvar rascunho" (a
unica noticia de que a digitacao NAO esta protegida em disco) reprova nos dois
temas. Os textos grandes (linhas da lista, editores, destaques) passam com
folga, de 6,8:1 a 17:1 — o problema e a camada de rotulos de estado.

Correcao: pares por tema, como o CTk ja faz em todo widget. Substitutas
medidas: ambar `('#92400e', '#f59e0b')` da 5,12:1 e 6,6:1; verde
`('#166534', '#4ade80')` da 5,15:1 e 8,1:1; vermelho `('#991b1b', '#f87171')`
da 6,0:1 e 5,1:1; cinza `('#475569', '#94a3b8')` da 5,5:1 nos dois. Os mesmos
hexes estao em stats_window.py, glossary_editor.py e background_task.py.

**E o status rejeitada/em-duvida da linha aberta e comunicado SO por cor** —
uma borda de ~2 px no campo de nota (`update_review_status_label`, 3016-3031).
A docstring do metodo diz "e diz qual e no rodape"; o metodo nao escreve rodape
nenhum, e nenhum outro ponto exibe o NOME do status da linha aberta (o rodape
agrega contagens; a linha da lista diz `PEND`, igual a pendente comum). Para um
protanope, simulacao de Machado 2009: as duas cores viram dois tons de oliva
com 2,8:1 entre si. O flash "Marcada como rejeitada" some em 1,5 s; depois
disso, nada na tela diz o status. Correcao: fazer o que a docstring ja promete
— um rotulo textual ("Rejeitada" / "Em dúvida") atualizado pelo mesmo metodo —
e corrigir a docstring ate la.

**A correcao** (garantia F19, SPEC secao 9). Dez testes em duas classes e **dez
mutacoes, dez mortas** — depois de a primeira rodada achar um teste fraco meu.

**As quatro cores viraram pares, num lugar so.** Elas estavam como hex literal em
quatro arquivos — `edit_window`, `glossary_editor`, `stats_window` e
`background_task` —, somando 23 ocorrencias. Agora vivem em `editor_common`, que
e o modulo sem Tk que os dois editores ja compartilham, e cada janela importa. As
razoes medidas nesta maquina, contra os dois fundos de rotulo:

| | antes (claro / escuro) | depois |
|---|---|---|
| verde | 2,38 / 4,30 | **5,15 / 8,13** |
| ambar | **1,55** / 6,59 | **5,12 / 6,59** |
| vermelho | 3,49 / 2,93 | **6,00 / 5,12** |
| cinza | 3,44 / 2,98 | **5,47 / 5,52** |

Os outros dois pares da tabela do diagnostico foram por caminhos diferentes, e a
diferenca e a razao:

- **a linha selecionada** trocou o fundo (`#3b82f6` -> `#1d4ed8`, 3,68 -> 6,70):
  ali o branco e o texto de todas as linhas da lista, e mexer nele mudaria as
  outras;
- **a ocorrencia atual do Ctrl+F** trocou o TEXTO (branco -> `#111827`, 2,26 ->
  7,84 no claro e 3,56 -> 4,98 no escuro): ali o fundo laranja e o que distingue
  a ocorrencia atual das demais, e escurece-lo o bastante para o branco passar
  apagaria essa diferenca. O branco reprovava nos DOIS temas, e nao so no claro
  como o diagnostico sugeria.

Uma cor da mesma familia foi medida e **passa**: o branco sobre o azul da selecao
de texto (`#2563eb`), 5,17:1. Ela nao estava na tabela e fica como esta.

**O status ganhou palavra.** Um rotulo — "Rejeitada" / "Em dúvida" — ao lado do
campo de nota, pintado com a mesma cor da borda, e que **sai do grid** quando a
linha esta pendente: o padrao nao precisa de rotulo, e escrever "Pendente" em
toda linha faria o normal virar ruido e esconderia a excecao (a mesma regra da
prioridade no editor de glossario). A docstring que prometia um rodape
inexistente foi reescrita para dizer o que o metodo faz — e o que ele fazia.

**A rodada de mutacao, e o teste fraco que ela achou.** Uma sobreviveu na
primeira passada: voltar o texto da ocorrencia atual para branco. O teste
declarava a cor que esperava e media a propria declaracao — ele nunca olhou para
a janela. Reescrito para ler `tag_cget("find_current", ...)` do widget, ele mata
a mutacao. E ganhou uma segunda assercao, que e a que fecha a saida pelos fundos:
o branco tem de continuar REPROVANDO sobre aquele fundo, senao escurecer o
laranja tambem passaria por correcao.

| mutacao | testes que a pegaram |
|---|---|
| cada uma das quatro cores voltando ao hex unico | 1 cada |
| a linha selecionada voltando ao azul claro demais | 1 |
| **a ocorrencia atual voltando ao texto branco** | 1 |
| o status voltando a ser so cor | 3 |
| a palavra ficando na tela sem status | 2 |
| a palavra e a borda discordando | 1 |
| a pendente ganhando rotulo tambem | 3 |

### 22.10 Rotulos que colidem e larguras que nao fecham — CONCLUIDO (2026-08-01)

**Tres botoes "Limpar" fazem tres coisas diferentes** na mesma janela: limpa a
busca (561), desmarca a selecao em lote (633) e limpa o status de revisao (874
— este GRAVA no banco). E "Página" e quatro coisas: dois botoes de navegacao
("< Página"/"Página >"), o rotulo do campo de salto e o botao da barra de lote
que MARCA a pagina — leitura natural de navegacao, acao de alimentar uma
escrita em massa. Os quatro rotulos propostos foram os aplicados: "Limpar
busca", "Desmarcar", "Limpar status" e "Marcar página". Sobrou uma repeticao, e
ela fica: os dois "Ir" da barra de salto, cujo objeto esta no rotulo do campo
colado a eles ("Página" e "ID") — que e justamente o que os "Limpar" nao tinham.

**A medicao na janela real mudou tres das quatro contas.** O diagnostico era de
CONSTANTES declaradas, e a secao 22.14 exigia medir `winfo_*` antes de gravar
numero novo. Medido com o harness da suite GUI, janela em 1120x680 fora da area
visivel:

| conta                    | diagnostico              | medido                                                 |
| ------------------------ | ------------------------ | ------------------------------------------------------ |
| painel de sugestoes       | 244 de 300 px            | **109** de 300 px; os seis botoes com 40 dos 140 que pedem |
| barra de lote             | "Exportar" cortado       | "Verificar" com**25** de 80 e "Exportar" comecando em x=355 numa faixa de 300 — inteiramente fora |
| fileira de rotulos        | 272 caracteres           | 1.167 px pedidos contra 1.080 disponiveis              |
| as duas fileiras de botoes | 831 e 932 contra ~1080 | confirmado, e sao as unicas que ja estavam certas       |

**E achou uma quinta que o diagnostico nao tinha: a barra de salto.** Ela pede
406 px, e `grid` reparte a falta por TODAS as colunas — nao so pelas que tem
peso. Com o divisor no minimo da lista, o campo da pagina media **11 px** e o do
id, 29; na largura padrao do painel, 51 px. Um campo de 11 px nao mostra um
digito. A correcao foi tirar o "< Voltar" dali e po-lo entre as duas viradas de
pagina, que e o que ele tambem e: com isso a fileira cai para 320 px e os dois
campos passam a medir 54 e 72 px no minimo. A decisao do 19.3 — que o "voltar"
precisa de botao, e nao so do `Alt+Backspace` — continua de pe.

**A correcao das larguras, item a item:**

- `MIN_WIDTH` deixou de ser um numero solto e passou a ser a SOMA dos minimos
  (`LIST_PANE_MIN + SASH_WIDTH + BOTTOM_PANE_MIN + MAIN_PANE_PADX`), com o
  `minsize` do painel de sugestoes corrigido de 300 para **308** — o
  `winfo_reqwidth` dele medido: com 300, os seis botoes ficavam 4 px curtos.
  A largura minima da janela e hoje 1184, contra 1120.
- O `minsize` do painel de baixo era 620 e passou a ser 836 (editor + divisor +
  sugestoes). **Este e o conserto de verdade**, e a razao esta na proxima linha.
- `restore_pane_positions` ficou MENOR do que era, e nao maior. A primeira
  versao da correcao lhe deu um teto calculado da janela do momento, com esta
  explicacao: "`minsize` de `PanedWindow` so vale ao arrastar; no desenho
  inicial cada painel recebe o que pede e o ultimo fica com o resto". **A frase
  esta errada, e quem mostrou foi a rodada de mutacao.** Tirando o teto, nada
  mudava: 320/520/308 nas duas versoes, medido. O Tk honra o `minsize` dos
  vizinhos tambem ao POSICIONAR um divisor — com 836 declarado, quem recua e a
  lista, e uma posicao gravada de 900 px numa tela larga volta para 320 numa
  janela estreita sozinha.

  O teto nao era so redundante: `restore_pane_positions` roda agendado, e a
  largura que ele lia podia nao ser a final — medido nesta maquina, ele
  ENCOLHIA a lista para 442 px onde o teto correto seria 496. Saiu, junto com o
  maximo de 520 que a versao antiga tinha e com o minimo de 360 (os dois eram
  numeros escolhidos a parte dos paineis; o minimo passou a ser o `LIST_PANE_MIN`
  de 320).

  **Do maximo de 520 nao ha teste, e a razao esta medida:** a tela desta maquina
  tem 1360 px, a janela chega a 1340 de painel, e com os 836 do painel de baixo a
  lista nunca passa de 496 px — o maximo de 520 nunca chegava a valer aqui. O
  que da para proteger e o minimo, e ha teste para ele: uma posicao gravada de
  330 px volta como 330, e nao como 360.
- A barra de lote virou duas fileiras em `grid`. `pack` nao encolhe filho
  nenhum: entrega a largura pedida a quem chega primeiro e nao desenha o resto.
  `grid` divide a falta — medido, quatro botoes de 120 px num quadro de 300
  ficam com 71 cada.
- No rodape, a ordem de empacotamento passou a ser a de IMPORTANCIA, e nao a da
  leitura: o aviso de "Alterações não salvas" primeiro, as duas contagens
  estaveis ancoradas a direita, e por ultimo a mensagem transitoria (cortada por
  `preview` em 52 caracteres) e o estado do rascunho. A proposta original
  protegia so as duas contagens, e o pior caso medido derrubava junto o rotulo
  de "nao salvo" — que e o unico da faixa cuja ausencia custa trabalho.

**A garantia F20 esta na secao 9 da SPEC**, com 17 testes em
`LabelsAndWidthsFitTests`. Eles medem `winfo_*` na janela real, e nao repetem as
constantes: o que afirmam e "nenhum painel abaixo do minimo", "nenhum botao do
lote fora da faixa", "os dois rotulos estaveis inteiros no pior caso" e — a
ancora que faz o teste anterior valer alguma coisa — "alguem CEDE no pior caso".

### 22.11 O custo em gestos de um dia de revisao — CONCLUIDO (2026-08-01)

Cada item com o custo de hoje e o proposto; nenhum contraria decisao registrada
na SPEC (conferido item a item contra a secao 6). **Os dez foram feitos**, e as
mudancas de rumo estao ditas ao lado de cada um.

- **Verificar-e-avancar nao tem atalho.** Ctrl+Enter verifica mas nao navega;
  so no filtro "Pendentes" a linha sai da lista e a proxima "entra" de brinde.
  Em "Todas" — o filtro que 19.4 defende como o contexto de quem revisa — sao
  2 chords por linha (Ctrl+Enter + Alt+Right). `mark_and_next`, que faz a coisa
  certa nos dois filtros, so e alcancavel pelo botao. Proposta: um bind para
  `mark_and_next` (Ctrl+Shift+Enter, ou promover o Ctrl+Enter). Num livro de
  20.000 linhas revisadas em "Todas", e um chord a menos por linha.
- **PageUp/PageDown nao viram pagina.** `change_page` so existe nos botoes;
  nenhum `<Prior>/<Next>` no pacote (grep vazio). Proposta:
  Ctrl+PageDown/PageUp (Ctrl para nao roubar a rolagem nativa do texto).
- **Nao existe "selecionar tudo do filtro".** A barra de lote marca a PAGINA;
  marcar os 3.000 resultados de um capitulo sao 30 idas ao "Página" + 29
  "Página >". Buscar todos os ids do filtro custa 3,03 ms (medido no banco de
  dev) — o custo e de interface, nao de banco. Proposta: "Marcar tudo (N)" ao
  lado de "Marcar página", com o N do total filtrado.
- **Aplicar uma sugestao custa dois cliques com deslocamento** (selecionar +
  "Aplicar selecionada"), e nao ha duplo-clique nem atalho. Proposta:
  duplo-clique na sugestao aplica (o clique simples continua selecionando).
- **As outras posicoes de um comentario reusado sao invisiveis.** O rodape diz
  "· e mais N posições (a mesma tradução)" e nenhum gesto mostra QUAIS — o
  `origin_label` nao tem bind. Antes de editar um texto que serve a 12
  posicoes, "em que capitulos isso aparece" decide se a edicao vale para
  todas. A consulta ja existe e ja e paga a cada clique
  (`fetch_comment_occurrences`); a SPEC so registra razao contra po-las TODAS
  no rodape, nao contra o acesso sob demanda. Proposta: rodape clicavel
  quando N > 1, abrindo uma lista modeless copiavel.
- **Clicar numa linha nao poe o foco na traducao** — o segundo clique e dentro
  do texto, senao a digitacao vai para o vazio. `apply_one` ja usa
  `focus_editor=True` exatamente porque "depois desta acao o usuario vai
  digitar". Proposta: focar o texto no caminho do CLIQUE (os reloads
  programaticos ficam como estao, para nao roubar o foco da busca).
- **A nota do revisor so e gravada por "Rejeitar"/"Em dúvida"/"Limpar".**
  Editar a nota e navegar descarta a edicao em silencio — nada marca sujeira
  (o `set_dirty` so observa o texto da traducao) e Enter no campo nao faz
  nada. Proposta: nota diferente da carregada conta como sujeira e regrava
  com o status atual; Enter no campo regrava — fecha o fluxo de teclado.
- **Zoom so em saltos de 1 pt nos botoes A-/A+.** Sem Ctrl+roda (grep
  `MouseWheel`: zero no pacote) e sem Ctrl+±. Ir de 12 a 18 pt sao 6 cliques
  num botao de 42 px. Proposta: `<Control-MouseWheel>` e Ctrl+± chamando o
  `adjust_font` que ja existe.
- **"Verificar" em lote joga a selecao para o topo da pagina.** E o unico
  recarregamento pos-acao que nao reencontra a linha aberta pelo id
  (`select_index(0)` em 2939; `set_review_status` e `mark_and_next` usam
  `row_index_for_id`). Quem verifica um lote no meio do capitulo volta ao
  comeco da pagina.
- **A selecao em lote sobrevive a troca de arquivo, status e busca** — so
  morre na troca de par. A razao registrada para mata-la no par ("um id do par
  anterior nao esta na lista nova e Verificar marcaria linhas que o revisor
  nao ve") se aplica letra por letra ao arquivo. Nao ha decisao registrada
  em F7 sobre esses tres casos. Proposta minima: decidir e registrar; se a
  sobrevivencia for desejada (juntar linhas de varios capitulos), a
  confirmacao do lote deve dizer quantas das marcadas estao FORA dos filtros
  atuais.

**O que a implementacao decidiu diferente:**

- **`Ctrl+Shift+Enter`, e nao promover o `Ctrl+Enter`.** Promover teria trocado
  o significado de um habito ja formado: quem tem o acorde antigo na memoria dos
  dedos passaria a navegar sem pedir. Os dois convivem, e um teste guarda cada
  um — o novo verifica e AVANCA, o antigo verifica e FICA.
- **O N de "Marcar tudo" nao coube no rotulo.** A proposta era "Marcar tudo (N)",
  e o N do total filtrado tem ate seis digitos: medido, "Marcar tudo (201.482)"
  pede 125 px de texto numa fileira que ja disputa os 300 px do minimo do painel
  (22.10). O N passou para uma confirmacao, que so aparece quando a marcacao
  excede uma pagina — que e exatamente quando ela deixa de ser verificavel na
  tela. Com 100 linhas o revisor ve o que marcou, e perguntar seria ruido.
- **A selecao em lote FICA sobrevivendo** as trocas de arquivo, status e busca —
  e quem passou a dizer a verdade e a confirmacao, que conta quantas das
  marcadas estao fora dos filtros atuais. Matar a selecao a cada troca de filtro
  trocaria um risco silencioso por uma perda de trabalho garantida; e a diferenca
  para o caso do PAR, onde ela morre, e que dali nao se volta: os ids do par
  anterior nao existem na lista nova.
- **Os gestos de mouse ganharam tabela propria** (`MOUSE_GESTURES`) na mesma
  janela de atalhos. A razao e de teste: a parceria entre a lista e a janela e
  conferida nos DOIS sentidos (F18), e o lado "todo bind aparece na lista" so
  consegue separar atalho de evento de ciclo de vida porque o Tk poe `Key` em
  toda sequencia de tecla. Um `<Double-Button-1>` na mesma tupla ficaria listado
  e nunca verificado — a forma de envelhecer que F18 existe para impedir.
- **A nota do revisor precisou de tres coisas, e nao das duas propostas.** Alem
  de contar como sujeira e de o `Enter` gravar, ela e gravada ANTES da traducao
  dentro do `save_changes`: `set_review_status_by_id` mantem `verified` em
  lockstep com o status (F10), e chama-la depois de um `mark_verified` desfaria a
  verificacao que o usuario acabou de pedir. E a saida antecipada de `auto_only`
  ganhou uma excecao — sem ela, anotar numa linha que so as regras automaticas
  tocaram e navegar continuava perdendo a nota, que e o caminho que o item veio
  fechar.

**A garantia F21 esta na secao 9 da SPEC**, com 32 testes em `GestureCostTests` e
tres em `OccurrenceLinesTests`.

### 22.12 As outras janelas — CONCLUIDO (2026-08-01)

**O dialogo de Zerar Glossario anuncia um numero errado nas duas pontas —
headless.** `total = len(app.glossary_substitutions)` conta a lista APLICAVEL:
expande `@casa@` (uma linha vira 64 regras), soma as 232 regras da SEMENTE —
que o zerar nao apaga — e exclui as 50 de limpeza — que o zerar apaga. Medido
com as funcoes reais: o arquivo tem 5.910 entradas (5.674 sugestao + 186
automaticas + 50 limpeza) e o dialogo anuncia 7.325. Correcao: contar com
`load_glossary_entry_details(deduplicate=False)` (a mesma fonte do "Total" do
editor de glossario) e dizer o numero por tipo.

**Depois de zerar, a semente some da sessao e "volta" na proxima abertura —
headless.** `reset_glossary` poe `app.glossary_substitutions = []`, mas
recarregar um arquivo vazio devolve 232 regras (a semente, garantia S15).
Na sessao o editor fica sem sugestao nenhuma; ao reabrir, "Glossário
carregado: 232 entradas" aparece do nada. Correcao: recarregar com
`load_interactive_substitutions()` como `update_app_glossary` ja faz, e avisar
que as sugestoes de fabrica continuam.

**O "Teste rápido" do editor de glossario nao reproduz o pipeline — headless.**
Ele usa os pares crus, sem a conversao real: prioridade descartada (com uma
regra promovida via "Priorizar esta", a previa da `the roque` e o pipeline da
`the torre` — a previa contradiz o proprio banner S9 exibido ao lado), escopo
ignorado e `@casa@` inerte. E a licao da garantia S9: o anuncio nao IMITA o
criterio da aplicacao, ele USA o criterio. Correcao: construir as regras da
previa com a mesma conversao (`_as_rule` + `expand_square_placeholder`).

**A janela de estatisticas "nao editavel" aceita edicao por Ctrl+V/X/K/D/O/T/H
— headless.** O `_block_typing` deixa passar QUALQUER tecla com Control, e os
bindings de classe do Tk mapeiam essas sete para colar/recortar/apagar/
transpor. O docstring da janela diz por que isso nao pode acontecer: "um
relatorio editavel viraria um numero diferente do que o banco disse". Correcao:
whitelist (c/a/Insert e navegacao) ou `break` nos eventos virtuais `<<Paste>>`,
`<<Cut>>`, `<<Undo>>`, `<<Redo>>`, `<<Clear>>`.

**Historico: restaurar grava sem pergunta, e a janela nao diz o que mudou** —
leitura de codigo. E a unica restauracao do programa sem confirmacao (Restaurar
BD e backup do glossario perguntam; ate excluir UMA regra pergunta), com os
dois botoes de restaurar colados ao "Fechar". E os dois textos "Anterior"/
"Nova" nao pintam o diff — `diff_spans` ja existe, e pura e ja pinta a previa
do 19.5 —, o rotulo da linha nao resume o que mudou, e o limite de 100 versoes
corta sem avisar. Correcoes na mesma ordem: `askyesno` curto; pintar com as
tags do 19.5; "N trecho(s)" no rotulo; "Mostrando as 100 mais recentes".

**Paridade do editor de glossario** — leitura de codigo: `connect_events` liga
so Ctrl+S e Ctrl+N. Sem Ctrl+L, sem voltar, sem anterior/proxima, sem campo de
pagina, sem selecao em lote (com os filtros "Duplicadas"/"Conflitos", excluir 8
duplicatas sao 8 ciclos clique+Excluir+Sim) e a previa sem diff pintado.
Transplantar o subconjunto que faz sentido — a busca que salta para o primeiro
resultado ja e um salto sem volta.

**Fechar a janela principal nao tem handler** — leitura de codigo: nenhum
`WM_DELETE_WINDOW` na raiz. O X mata uma traducao em andamento sem pergunta (o
PGN da vez pode ficar truncado; a lista T4 de falhas so e gravada no caminho
feliz) e as janelas filhas nao passam pelos seus fechamentos — a edicao aberta
do editor perde ate 2,5 s de digitacao sem o `save_changes` do `close_editor`.
Correcao: handler na raiz — com traducao ativa, perguntar e cancelar antes de
sair; sem, repassar o fechamento as filhas.

**Miudezas confirmaveis por leitura, cada uma com correcao de uma linha ou
uma decisao:**

- A janela principal e a unica que nunca lembra tamanho e posicao — sempre
  abre maximizada (`maximize=True` incondicional; os dois editores restauram).
- A selecao de entrada aceita UM arquivo ou uma pasta — sem multiplos
  (`askopenfilename` singular) e sem arrastar-e-soltar; o worker ja aceita
  lista explicita (`only_files`). Multiplos e um troca de funcao; DnD exigiria
  dependencia nova (registrar como decisao).
- O log salta para o fim a cada mensagem — reler um `[AVISO]` durante uma
  execucao e ser puxado de volta a cada tick. Autoscroll condicional (so se a
  borda inferior ja estava visivel) e o padrao de console.
- A palavra de confirmacao dos "Zerar" e `delete`, em ingles, num dialogo todo
  em portugues cujo botao se chama "Apagar" — e digitar "apagar" e recusado.
  Trocar para "apagar" (aceitando as duas por uma versao).
- O erro de carga do editor de glossario e o unico `messagebox` do arquivo sem
  `parent=self.win` — abre atras do editor maximizado.
- A janela de estatisticas exporta so `.txt` corrido; as tabelas (progresso por
  obra, palavras por par, atividade por dia) sao o que se cola numa planilha
  de orcamento. Um "Salvar CSV" com as estruturas que `collect_database_stats`
  ja devolve.

**O que a implementacao fez, e o que ela decidiu nao fazer:**

- **Zerar Glossario** passou a contar com `load_glossary_entry_details(deduplicate=False)`
  e a dizer o numero por tipo. Medido no `Substituicoes.txt` de hoje: 5.908
  entradas (5.663 sugestoes, 195 automaticas, 50 limpezas) — a lista aplicavel
  que o dialogo anunciava tem outro tamanho por tres razoes somadas, e nao por
  uma. E o `app.glossary_substitutions = []` virou uma recarga real: a sessao
  fica com as regras de fabrica que continuam valendo, em vez de ficar sem
  nenhuma e "recuperar" 232 na abertura seguinte.
- **A previa do glossario** passou a construir as regras com
  `interactive_rules_from_entries`, que e a MESMA funcao que
  `load_interactive_substitutions` usa. Alem dos tres pontos diagnosticados
  (prioridade, escopo, `@casa@`), a medicao achou um quarto: a previa trocava
  so a PRIMEIRA ocorrencia (`apply_substitution` passa `count=1`), e o pipeline
  troca todas — num paragrafo com tres "bishop" ela mostrava um resultado que
  nunca aconteceria. O escopo passou a ser avaliado com o par da janela
  principal, que e onde o par de uma traducao e escolhido.
- **A janela de estatisticas** ganhou a lista BRANCA (c/a/Insert e navegacao)
  **e** o `break` nos eventos virtuais — as duas, e nao uma ou outra: a lista
  decide o que o usuario digita, e o evento virtual e por onde o Tk edita, entao
  uma versao futura que mapeie outra tecla para `<<Paste>>` continua barrada.
- **O historico** ganhou as quatro correcoes propostas. O resumo "N trecho(s)"
  sai do mesmo `diff_spans` que pinta os dois paineis — dois criterios de "o que
  mudou" acabariam divergindo, e a lista contradiria o detalhe.
- **A paridade do editor de glossario** ficou no teclado: `Ctrl+L`, `Alt+←/→`
  pela lista FILTRADA (pela do arquivo, `+1` pousaria numa regra que a tela nao
  mostra — o erro que R10 nomeou no outro editor) e `Ctrl+PageUp/PageDown`. A
  **selecao em lote ficou de fora, e por decisao**: uma exclusao em massa e acao
  destrutiva nova e pede confirmacao e backup proprios, e nao os da exclusao de
  uma regra. Esta registrada na secao 10 da SPEC.
- **A selecao de entrada continua aceitando UM arquivo ou uma pasta**, como o
  item previa: multiplos e troca de funcao e DnD exigiria dependencia nova.
  Registrado na secao 10.

**Uma armadilha da propria suite apareceu aqui.** `DIALOG_MODULES`, do
`gui_harness`, listava cinco modulos e nao incluia `stats_window` nem
`history_window` — e a janela de estatisticas chama
`filedialog.asksaveasfilename`. O primeiro teste que a exercitou abriu o seletor
NATIVO do Windows e travou a suite esperando um clique. E a armadilha do item 3.2
na forma mais silenciosa: a lista so estava certa enquanto ninguem testasse
aqueles dois modulos.

**As garantias F22, F23, F24, F25, S16, S17 e S18 estao na secao 9 da SPEC**, com
11 testes de estatisticas, 9 de historico, 6 da previa do glossario, 7 da
paridade, 8 do fechamento da janela principal, 2 do log e 16 headless (contagens
por tipo, tabelas do CSV, resumo do historico e autoscroll), alem dos quatro
acrescentados a `ResetGlossaryTests`.

### 22.13 Duas medicoes de pipeline: o indice que o 19.12 perdeu e o Cancelar que espera — CONCLUIDO (2026-08-01)

**O resumo por status voltou a tocar a tabela — headless, medido.** O item
19.12 acrescentou `review_status` a agregada de `get_review_status_counts`, e
os dois indices de cobertura criados para ela nao tem a coluna. Conferido no
banco de dev em modo somente-leitura: `EXPLAIN QUERY PLAN` devolve `SEARCH comments USING INDEX idx_comments_counts` **sem** a palavra `COVERING` — uma
leitura da tabela por linha do par. Medido em copia sintetica de 204 mil linhas
(mediana de 20 execucoes): resumo do par 118,8 ms -> 60,8 ms e resumo
destino-apenas 138,3 ms -> 58,2 ms depois de recriar os indices com
`review_status` no fim. A consulta roda em TODA recarga da lista, na thread do
Tk. E a mesma classe de regressao silenciosa de R5 que a secao 17 nomeou quando
`source_language` entrou no WHERE — desta vez introduzida pelo proprio recurso
que a evitou da outra vez. O comentario de database.py:688-693 e os numeros de
R5 na SPEC descrevem um plano que nao existe mais; a SPEC ja foi corrigida
nesta revisao para dizer isso.

Correcao: migracao de schema 9 recriando `idx_comments_counts`
`(target_language, verified, quality_warning, review_status)` e
`idx_comments_pair_counts` `(target_language, source_language, verified, quality_warning, review_status)` — custo unico na primeira abertura.

**Cancelar nao alcanca o retry — headless.** `translate_text_chunk` nem RECEBE
o `cancel_flag`: o laco de tres tentativas dorme em `time.sleep` sem olhar
cancelamento, e `translate_text` so confere o flag ENTRE chunks. Reproduzido
com sessao falsa: flag ligado durante a primeira tentativa, e as tres rodaram
mesmo assim (1,56 s so de esperas de retry com falha instantanea). Com o
timeout real de 30 s por tentativa, a janela em que "Cancelar" nao tem efeito
chega a ~93 s por chunk contra um endpoint que pendura a conexao — o cenario em
que mais se clica Cancelar. A SPEC (C2) enumera os cinco pontos onde o flag e
conferido; nenhum esta dentro do retry. Correcao: passar o flag e conferi-lo
antes de cada tentativa e antes de cada espera (devolvendo `None`, que os
chamadores ja tratam); a requisicao em voo continua inevitavel.

**As duas correcoes sairam como descritas, com um detalhe a mais em cada uma.**

- A migracao 9 precisou **DERRUBAR** os dois indices antes de recriar. Um
  `CREATE INDEX IF NOT EXISTS` sobre um indice que ja existe com o mesmo nome e
  colunas diferentes nao faz nada e nao reclama: sem o `DROP`, a correcao valeria
  so para instalacoes novas — que sao exatamente as que nao tem o problema. Ha
  um teste que parte de um banco na versao 8, com o indice velho, e exige a
  coluna nova depois de reabrir.
- O SQL do resumo saiu para `review_status_counts_query`, que devolve
  `(sql, params)`. Nao e arrumacao: com a consulta escrita dentro da funcao que a
  executa, o teste do `EXPLAIN QUERY PLAN` teria de transcreve-la — e passaria a
  medir a propria transcricao, que continuaria coberta enquanto a de verdade
  deixasse de ser. E o padrao 2 da lista de testes que nao testam nada.
- No `translate_text_chunk`, os dois pontos de conferencia sao ambos
  necessarios, e ha um teste para cada: sem o de antes da tentativa, o
  cancelamento durante a espera ainda dispara a requisicao seguinte; sem o de
  antes da espera, espera-se 1,5 s para depois desistir. O teste substitui o
  `time.sleep` — o assunto dele e QUANTAS tentativas acontecem, e uma suite que
  dorme 4,5 s por caso deixa de ser rodada.

**As garantias R11 e C4 estao na secao 9 da SPEC**, com 4 e 6 testes. O sexto de
C4 nasceu de uma mutacao: com o cancelamento acontecendo antes da requisicao, a
conferencia do topo do laco podia ser removida sem nada ficar vermelho — quem a
exige e o caso em que o flag e ligado DURANTE a espera, que e a janela de tempo
em que o usuario realmente clica.

### 22.14 O que fica registrado do metodo — CONCLUIDO (2026-08-01)

- As confirmacoes **em janela real** rodaram no harness da suite GUI
  (`tests/gui_harness.py`): sandbox de caminhos, banco proprio, dialogos
  silenciados — nada tocou os dados reais, e as janelas abriram em segundo
  plano, atras do trabalho do usuario.
- A verificacao adversarial planejada (um refutador por achado) morreu no
  limite de sessao em 8 dos 9 achados enviados; o que compensou foi a
  confirmacao empirica direta, e a base de cada item esta dita nele. O unico
  refutador que completou confirmou o achado dos atalhos e o REBAIXOU (de alta
  para media), corrigindo dois exageros: o README documenta 3 dos 13, e "quem
  nao leu o fonte nao descobre" era forte demais. Nenhum achado foi refutado
  por inteiro — mas so um passou pelo crivo; os demais ficam com o grau de
  confianca da sua evidencia, nao mais.
- As aritmeticas de largura (22.10) sao de CONSTANTES declaradas no codigo,
  nao de medicao na janela; a correcao de cada uma deve medir `winfo_*` antes
  de gravar numeros novos — a licao do 18.4, que mediu com `winfo_reqwidth` e
  nao com captura.
- Os numeros de contraste sairam da formula WCAG executada nesta maquina, e os
  dois fundos foram conferidos: o claro por amostragem de pixels da captura
  real, o escuro pelo codigo.

**O que a implementacao de 22.10 a 22.13 acrescentou a este registro
(2026-08-01):**

- **A exigencia de medir se pagou, e mudou quatro numeros.** Tres das quatro
  contas do 22.10 estavam erradas para MENOS (o painel de sugestoes media 109 px
  e nao 244; a barra de lote perdia dois botoes e nao um) e uma quinta faixa —
  a barra de salto, com o campo de pagina em 11 px — nao estava no diagnostico.
  Nenhuma delas apareceria lendo o codigo com mais atencao: o que as revelou foi
  abrir a janela em 1120x680 e perguntar `winfo_x` e `winfo_width` a cada widget.
- **A licao nova e sobre o gerenciador de layout, e vale para a proxima janela.**
  `pack` nao encolhe filho nenhum: entrega a largura pedida a quem chega primeiro
  e simplesmente nao desenha o resto — o botao existe, tem o tamanho certo e esta
  fora da faixa. `grid` divide a falta entre TODAS as colunas, com peso ou sem
  ele. Medido nesta maquina: quatro botoes de 120 px num quadro de 300 ficam com
  71 px cada em `grid` e com 120, 120, 48 e 1 em `pack`. Onde faltar espaco, a
  escolha entre os dois e a escolha entre "todos menores" e "os ultimos somem".
- **Medir janela em teste pede dois cuidados que custaram tempo aqui.** O
  `CTkToplevel` nasce ESCONDIDO — ele se retira para pintar a barra de titulo e
  se mostra por um `after` — entao todo `winfo_width` responde 1 ate alguem
  chamar `deiconify`; e cancelar os `after` pendentes (para o `bring_window_to_front`
  nao maximizar no meio da medida) cancela junto esse `deiconify`. E `focus_get()`
  devolve `None` quando o programa nao esta em primeiro plano, que e como esta
  suite roda: a pergunta que serve e `focus_lastfor`, e a resposta se compara
  pelo CAMINHO do widget, porque os widgets do CustomTkinter poem o foco no Tk
  puro que carregam dentro.
- **A suite tinha um buraco de dialogo, e ele so aparece quando se testa.**
  `DIALOG_MODULES` nao listava `stats_window` nem `history_window`; o primeiro
  teste que exercitou o "Salvar .txt" abriu o seletor nativo do Windows e travou
  tudo. Ao escrever teste para uma janela ainda nao coberta, conferir a lista
  ANTES e mais barato do que descobrir pelo travamento.
- **E ha um segundo caminho de dialogo que o harness nao alcanca.** Uma excecao
  que escapa de um callback do Tk vira dialogo pelo relator de C3, e ele monta o
  `messagebox` a partir do `tkinter`, e nao do modulo — o silenciador nao chega
  la. O teste do fechamento com uma filha defeituosa trava a suite ate trocar o
  `report_callback_exception` da raiz por um que registre.
- **Onde a proposta do diagnostico nao coube, o que decidiu foi a medicao.** O
  "Marcar tudo (N)" virou "Marcar tudo" com o N na confirmacao porque
  "Marcar tudo (201.482)" pede 125 px de texto numa fileira de 300; e o rodape
  passou a proteger tambem o rotulo de "nao salvo", que a proposta original
  deixava cair junto com a mensagem transitoria.

**A rodada de mutacao: 42 mutacoes, e ela pagou o preco dela.** Seis
sobreviveram na primeira passada, e cada uma disse algo diferente:

| sobrevivente                                     | o que ela mostrou                                                                                |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| teto do divisor removido                          | **guarda redundante** — e pior que redundante: o teto lia uma largura que podia nao ser a final. Saiu |
| rodape de volta ao`side=LEFT`                    | o teste afirmava que os rotulos estaveis SOBREVIVEM, e nao que eles ficam a DIREITA — duas coisas   |
| roda multiplicando pelo`delta`                   | o teste so usava`delta=±120`, onde as duas contas dao o mesmo numero. Uma roda de alta resolucao manda 40, e a mutante nao zoom nenhum |
| nota gravada DEPOIS da traducao                   | o cenario partia de uma linha PENDENTE, e com status vazio as duas ordens dao o mesmo resultado    |
| rodape de procedencia sem`bind`                  | todos os testes chamavam o metodo na mao: nenhum provava que alguem o chama                        |
| estatisticas sem os eventos virtuais              | o`event_generate` ia para o quadro do CustomTkinter, e nao para o `tk.Text` de dentro — o evento nao chegava a lugar nenhum |

Cinco viraram teste novo; a primeira virou codigo a menos. As quatro do meio sao
o padrao 1 e o padrao 2 da lista de "testes que nao testam nada", em quatro
disfarces diferentes — e nenhuma delas teria aparecido sem a rodada. Reaplicadas
depois, as seis morreram, e o placar fecha em **42 mutacoes e nenhuma
sobrevivente**.

**Uma sobrevivente ficou sem teste, e por medicao:** tirar o maximo de 520 do
divisor da lista nao e observavel nesta tela (ver 22.10). Esta registrada aqui em
vez de virar um teste que passaria por acidente.

**E o proprio script cobrou duas armadilhas novas**, alem das duas que a secao 20
ja tinha registrado. `-k` do unittest nao entende "A or B" — ele casa substring,
e um filtro com " or " nao casa classe nenhuma: a rodada devolve "NO TESTS RAN"
com codigo de erro, e so a exigencia de uma linha `FAIL:` na saida impediu duas
mutacoes de serem contadas como mortas sem ninguem ter olhado nada. E
`read_text`/`write_text` trocam as quebras de linha no Windows: restaurar um
arquivo LF o devolveu em CRLF, a conferencia de SHA quebrou no meio da rodada, e
**matar o script ali deixou uma mutacao aplicada na producao** — as tres rodadas
seguintes mediram um `edit_window.py` sem o `bind` do rodape ate a arvore ser
conferida marca por marca.

---

## Apendice da revisao de 2026-07-29 — o metodo, para poder ser refeito

- **Banco de desenvolvimento**: `traducoes.db` local, 6.500 linhas en -> pt
  (amostra real de livro; o banco de producao do usuario, ~201 mil linhas, nao
  foi tocado). As contagens de terminologia (16) sairam de padroes regex
  estreitos por termo, rodados sobre `original_comment`/`translated_comment`;
  subcontam de proposito.
- **Glossario**: `Substituicoes.txt` na versao de 7.105 regras; contagens por
  tipo/prioridade/familia por varredura completa; colisoes de caixa por
  agrupamento `casefold`; regras mortas confirmadas aplicando o glossario real
  a frases de teste.
- **Corrupcoes (13.1, 13.2)**: reproduzidas nesta maquina chamando
  `fix_move_notation` e `flatten_comment` reais, com os pares de entrada/saida
  registrados no proprio item. `is_generated_pgn('game-BR-2.pgn') == False`
  idem.
- **Achados de codigo sem reproducao** (guardas ausentes, navegacao com filtro
  de origem, backup que migra, CSV somente-exportacao): conferidos por leitura
  das linhas citadas; cada um precisa de teste que falhe antes da correcao,
  como manda a regra da secao 11 da SPEC.
- **Banco sintetizado da secao 18**: as ocorrencias so nascem ao processar um PGN,
  entao o banco de dev tem zero delas e nao servia para medir o filtro por arquivo.
  O banco de medida sai de uma copia do `traducoes.db` local inflada a 201.500
  linhas (o mesmo texto com sufixo, para caber na UNIQUE) e 200 mil ocorrencias em
  100 arquivos — ~1.900 comentarios distintos por arquivo, com ~13% de repeticao
  interna, `ANALYZE` rodado no fim. Nao e o banco do usuario; e a escala dele.
  Numeros de pagina, contagem e offset sao o melhor de 5 execucoes, ja com o cache
  de paginas quente.
- **Largura do rodape da procedencia (18.4)**: medida por `winfo_reqwidth` com a
  janela `withdraw`n, na geometria padrao (1280 px de janela, 596 px de faixa) e na
  minima declarada. Sem screenshot de proposito: a captura anterior pegou a janela
  atras de outro programa e mostrou a tela errada.

---

## 23. O historico nao respondia a pergunta que se faz a ele — CONCLUIDO (2026-08-01)

Relato do usuario, no dia seguinte a secao 22: "o historico so esta aparecendo a
traducao atual; acredito que deveria ser uma lista das ultimas alteracoes, assim
em caso de engano posso escolher qual restaurar".

### 23.1 A lista mostra ALTERACOES, e a versao inicial e recuperavel

**Medido no banco de dev (6.500 linhas) antes de mexer em qualquer coisa:**

| | |
| ------------------------------------------------------- | ------------- |
| comentarios no banco                                     | 6.500         |
| **sem nenhuma linha de historico**                       | **5.871 (90%)** |
| com historico                                            | 629 (no maximo 3 entradas) |
| entradas de historico que **nao mudam o texto**          | **607 de 889** |
| comentarios cujo historico inteiro nao muda texto        | 355 de 629    |

Sao duas causas somadas, e as duas produzem a mesma tela:

1. **A traducao que veio do pipeline nunca foi registrada.** O `INSERT` de
   `save_translation` e o UNICO caminho que escreve `translated_comment` sem
   gravar historico — conferido um a um: editar, importar CSV, aplicar
   automaticas, corrigir lances e preencher linha vazia registram todos. Em 90%
   das linhas a janela abria em "Nenhuma alteracao registrada".
2. **`verify` grava uma entrada com `previous == new`.** Marcar como verificada
   nao muda texto, e os dois painels mostravam a MESMA coisa — que e literalmente
   "so aparece a traducao atual". Exemplo real, id 1: `anterior` e `nova`
   identicos, os dois com o texto que esta na linha hoje.

**A correcao nao grava nada, e essa foi a decisao que mudou o plano.** A ideia
aprovada era gravar uma linha-base no `INSERT` e migrar o acervo existente.
Medindo o que isso custaria, a derivacao apareceu como estritamente melhor:

- **a versao da maquina e derivavel e exata.** Como todo caminho que muda texto
  registra, andar para tras chega nela sem ambiguidade: e o
  `previous_translation` da entrada MAIS ANTIGA, ou o texto atual quando nao ha
  historico. `machine_translation_for` faz isso numa consulta indexada por
  `comment_id`;
- **gravar custaria o acervo duplicado em disco.** A linha-base leva o texto
  inteiro no `new_translation`; numa execucao de 200 mil linhas, a
  `comment_history` (hoje com 889 linhas) passaria a ter o tamanho do corpus;
- **e a migracao poderia errar onde a derivacao nao tem como.** Ela calcularia
  exatamente a mesma coisa, uma vez, com risco de escrita em massa.

O filtro das entradas sem mudanca e em **SQL**, e nao em Python depois, por causa
do `LIMIT`: com 100 verificacoes gravadas, filtrar depois traria 100 linhas
inuteis e ZERO alteracoes — o limite se gastaria inteiro no que ia ser
descartado. Ha teste para exatamente isso.

**O que a janela mostra agora**, medido nas tres formas de linha do banco real:

| linha                | antes                        | depois                                    |
| -------------------- | ---------------------------- | ----------------------------------------- |
| sem historico (90%)   | "Nenhuma alteracao registrada" | 1 versao: a da traducao automatica        |
| so verificacao        | 1 entrada, dois painels iguais | 1 versao: a da maquina, + o aviso do que ficou fora |
| editada (id 107)      | 3 entradas, uma delas inutil   | 2 alteracoes + a versao da maquina        |

Na id 107 a diferenca aparece: a versao da maquina era
`"O jogo esta comecando a tomar forma nos moldes de um frances cla..."` e a atual
e `"A partida esta comecando a tomar forma nos moldes de um Francesa..."` — o
texto para o qual "em caso de engano" nao havia como voltar.

**Duas decisoes menores, ditas porque sao escolhas e nao consequencias:**

- **A linha da maquina nao tem carimbo nem transicao de status.** Ela nao
  aconteceu num instante que alguem registrou e nao mudou status nenhum;
  escrever "- | pendente -> pendente" seria inventar tres fatos para preencher um
  formato.
- **O que fica fora da lista e anunciado**, na mesma linha que ja avisava do
  corte em 100 versoes. Sumir com 607 de 889 entradas sem dizer nada trocaria uma
  lista confusa por uma lista incompleta.

**O filtro derrubou dois testes antigos, e eles estavam certos em falhar.**
`test_review_history_timestamps_are_recorded` e
`test_exact_translation_matches_can_be_verified_together` afirmam sobre entradas
`verify`, `mark_pending` e `verify_exact_match` — exatamente as que a lista deixa
de trazer. Eles testam a GRAVACAO, e nao o que a janela mostra, entao passaram a
pedir o historico inteiro (`only_text_changes=False`); o padrao continua sendo o
que a janela precisa.

Os dois apareceram primeiro como `PermissionError` ao limpar o diretorio
temporario — a conexao SQLite continuava aberta porque a excecao real acontecia
antes do fim do teste, e no Windows o arquivo em uso nao e apagado. **A mascara
custou mais tempo que o defeito**: a mensagem que aparece descreve a limpeza, e
a que interessa esta tres blocos acima, atras de dois "During handling of the
above exception". Os dois testes ganharam `conn.close()` no fim, que e o que
impede a proxima falha deles de chegar disfarcada.

**A garantia F26 esta na secao 9 da SPEC**, com 15 testes headless
(`HistoryIsAListOfChangesTests` e `HiddenHistoryLabelTests`) e 5 de janela.
**Oito mutacoes, oito mortas.**

## 24. O acento sobrevivia a gravacao e morria na leitura — CONCLUIDO (2026-08-03)

Relato do usuario, depois de abrir no ChessBase o PGN traduzido: "conferi e as
letras com acento foram omitidas. também foram omitidas palavras com ç~, etc".

### 24.1 Nao era a traducao, era a codificacao de saida

A primeira suspeita — traducao gravada sem acento — foi medida e **descartada**
antes de mexer em qualquer coisa:

| | |
| ---------------------------------------------------- | ------ |
| caracteres acentuados no `traducoes.db`              | 14.432 |
| sequencias de mojibake (`Ã§`, `Ã£`)                  | 0      |
| palavras que perderam acento em relacao ao backup    | 0      |
| palavras tipo `posicao`, `nao`, `tambem`, `acao`     | 0      |

O banco estava inteiro. O defeito estava no arquivo gerado, e medi-lo mostra o
mecanismo inteiro:

| | |
| --------------------------------- | ---------------------------------- |
| PGN de origem (ingles)            | 842.680 bytes, **23** bytes altos  |
| codificacao detectada na origem   | **cp1252**                         |
| PGN gerado                        | 887.208 bytes, **14.793** bytes altos |
| acentos no arquivo gerado         | 14.733, **todos presentes**        |
| decodifica como UTF-8             | **nao**                            |

`detect_encoding` devolve a codificacao da ENTRADA e a gravacao a reusava. Vinte
e tres nomes de jogador acentuados bastam para o livro em ingles inteiro ser
classificado cp1252 (garantia E3); a traducao para portugues enche o arquivo de
acento; e a saida sai com quinze mil bytes altos de byte unico. Quem le
esperando UTF-8 — o ChessBase 26, por exemplo — trata cada um deles como UTF-8
invalido e o **descarta**:

| gravado (cp1252)      | lido como UTF-8      |
| --------------------- | -------------------- |
| `Deixe-me levá-lo`    | `Deixe-me lev-lo`    |
| `o Dragão Acelerado`  | `o Drago Acelerado`  |
| `uma linha específica`| `uma linha especfica`|

E letra que some, e nao mojibake — por isso o relato fala em "omitidas". Nada no
programa acusava.

**O fallback que ja existia nao alcanca este caso.** `write_pgn_pieces` cai para
UTF-8 no `UnicodeEncodeError`, e o cp1252 representa todo acento do portugues sem
levantar nada. O acento nao se perdia na gravacao; se perdia na leitura seguinte,
que e onde nenhum teste olhava.

**A opcao `utf8_bom` tambem nao alcancava.** `_output_encoding` so trocava
`utf-8` por `utf-8-sig`; com origem cp1252 ela devolvia cp1252 inalterado. Nao
havia ajuste nenhum, em lugar nenhum, que produzisse saida UTF-8 a partir de uma
origem de byte unico.

### 24.2 A correcao: promover o que nao e Unicode

`_output_encoding` grava em UTF-8 sempre que a codificacao de entrada nao for
Unicode. O criterio e o do LEITOR, e nao o do gravador: uma codificacao serve se
representa qualquer caractere **e se anuncia** a quem le depois.

| entrada                       | `use_bom`  | gravacao      |
| ----------------------------- | ---------- | ------------- |
| cp1252, latin-1, iso-8859-\*  | falso      | `utf-8`       |
| cp1252, latin-1, iso-8859-\*  | verdadeiro | `utf-8-sig`   |
| utf-8                         | falso      | `utf-8`       |
| utf-8                         | verdadeiro | `utf-8-sig`   |
| utf-16, utf-32                | qualquer   | inalterada    |

**UTF-16 e UTF-32 ficam fora de proposito**: carregam BOM, se anunciam ao leitor
e nao perdem caractere — promove-las trocaria uma codificacao correta por outra
sem ganho nenhum. E promover uma saida que so tem ASCII nao muda byte algum,
entao a regra nao precisa de excecao para esse caso.

**A opcao de BOM continua valendo DEPOIS da promocao**, e por isso a saida
promovida sai sem BOM por padrao. As duas alternativas foram consideradas e
descartadas: forcar o BOM tiraria do usuario uma opcao que ja existe e que
incomoda quem versiona o PGN (git, diff, parsers estritos); nao promover deixaria
o defeito de pe. A evidencia do proprio caso decide entre elas — o ChessBase 26
le UTF-8 sem BOM **como UTF-8**, e foi assim que ele descartou os bytes cp1252.

**A troca vai para o log**, na linha do arquivo gerado. E o programa mudando a
codificacao por conta propria; quem comparar entrada e saida byte a byte tem de
achar o motivo registrado em algum lugar.

### 24.3 Verificado no arquivo de verdade, e nao so em fixture

Reexportado pelo caminho do programa (`run_translation`, o mesmo do botao), com
`translate_text` neutralizado para garantir que nenhuma chamada de API
acontecesse sem ninguem ter pedido:

| | |
| ------------------------------- | ----------------------------- |
| comentarios no PGN              | 7.487                         |
| reaproveitados do cache         | 6.500 (todos os distintos)    |
| chamadas de API                 | **0**                         |
| comentarios que falharam        | 0                             |
| posicoes registradas            | 7.487/7.487                   |
| saida                           | 902.033 bytes, **utf-8**      |
| decodifica UTF-8 **estrito**    | sim                           |
| acentos                         | 14.733                        |
| `U+FFFD`                        | 0                             |

A prova e a do leitor: o arquivo e decodificado com `bytes.decode("utf-8")` sem
`errors`. Antes da correcao essa linha levanta `UnicodeDecodeError`.

### 24.4 O teste antigo passou a testar um caminho que deixou de existir

`test_a_translation_the_input_encoding_cannot_hold_falls_back_to_utf8` montava um
PGN cp1252 e punha um caractere chines numa traducao para forcar o
`UnicodeEncodeError`. Com a promocao, esse PGN nunca mais e gravado em cp1252, e
o teste continuaria **verde testando outra coisa** — a familia que a secao 5
descreve: passa com a producao certa E com a errada.

Ele virou `test_a_single_byte_input_encoding_does_not_become_the_output_encoding`,
com as duas metades juntas: o arquivo tem de sair INTEIRO (a checagem de
truncamento, que era o ponto do teste antigo) e tem de sair em UTF-8. O fallback
do `UnicodeEncodeError` fica onde estava — hoje so alcancavel por UTF-16/32 com
surrogate solto —, porque e ele que trunca o arquivo pela metade que a primeira
tentativa deixou.

**A garantia G2 da SPEC foi reescrita.** Ela dizia "a gravacao usa a codificacao
detectada na origem" — exatamente o comportamento que causava o defeito.

**Tres testes novos, seis mutacoes, seis mortas:**

| mutacao                                              | testes que falham |
| ---------------------------------------------------- | ----------------- |
| promocao removida                                    | 3 de 4            |
| condicao invertida                                   | 4 de 4            |
| prefixo `utf8` no lugar de `utf` (promove UTF-16/32) | 2 de 4            |
| promove sempre com BOM, ignorando a opcao            | 2 de 4            |
| promocao depois da opcao de BOM                      | 3 de 4            |
| log da troca removido                                | 1 de 4            |

Conferido tambem ao contrario: com a versao anterior de `_output_encoding`
restaurada, os tres testes novos falham (5 falhas e 1 erro, contando os
subtestes da tabela de promocao).

## 25. As familias de casa voltaram a ser escritas a mao — CONCLUIDO (2026-08-03)

O `Substituicoes.txt` da arvore de trabalho tinha 621 linhas a mais que o ultimo
commit, e elas desfaziam duas decisoes registradas aqui. Nao foi leitura: os
dois testes que existem exatamente para isso estavam vermelhos, e foi assim que
o item apareceu.

### 25.1 O que as 621 linhas fizeram

|                                | HEAD  | antes | depois |
| ------------------------------ | ----- | ----- | ------ |
| linhas do arquivo              | 5.922 | 6.514 | 6.077  |
| entradas                       | 5.916 | 6.508 | 6.067  |
| regras com casa literal        | 20    | **466** | 18   |
| regras com `@casa@`            | 20    | 20    | 27     |
| entradas sem escopo (`'*'`)    | 19    | **310** | 19   |

**As familias voltaram a ser enumeradas casa a casa.** Sete delas — `torre-`,
`dama-`, `rei-`, `cavalo-`, `bispo-`, `casa-` e `A troca no ` — escritas as 64
casas na mao, 446 linhas. E a mesma enumeracao que o item 14.7 colapsou, e
aquele item ja tinha dito como se faz isto hoje: "quem quiser a familia inteira
automatica agora troca uma linha, e nao 64".

O censo por familia mostra a marca da passagem manual, a mesma que 14.7
descreve: `bispo-` estava **partida em duas**, 36 casas com escopo `'*'` e 28
com o escopo do arquivo; `cavalo-` em 63 mais 1. Nao e criterio, e onde a
digitacao parou.

**Cinco das sete tinham escopo `'*'`, e isso nao e cosmetico.** Medido com a
conversao do proprio programa — `filter_glossary_entries_by_type`, que filtra
por par de idiomas e expande o `@casa@` —, e nao contando linhas do arquivo:

| regras `automatic` que alcancam o par | HEAD | antes | depois |
| ------------------------------------- | ---- | ----- | ------ |
| en, es, fr, de, it, ru (cada um)      | 3    | **294** | 3    |
| pt                                    | 294  | 899   | 899    |

**291 regras portuguesas passaram a valer para os outros seis idiomas de
destino.** `bispo-d4` -> `bispo de d4` aplicado, sem revisao, a uma traducao
para o italiano — onde bispo e `alfiere` e a preposicao e `di`. E o defeito que
a secao 15 conserta e que a garantia S11 nomeia, de volta pela porta dos dados
em vez da do codigo.

### 25.2 O conserto: sete linhas no lugar de 446

As sete familias viraram sete regras com `@casa@`, `automatic`, **sem escopo
declarado** — que e como se herda o `escopo = 'pt'` do topo do arquivo. As duas
familias partidas se juntaram no caminho.

**As 20 regras literais do HEAD ficam onde estao**: as 14 automaticas de
`@casa@-peão` e as quatro da Siciliana sao a excecao deliberada de 14.7, que
existe para nao mudar o tipo de 91 padroes. Duas das 20 sumiram — a casa unica
de `bispo-` e a de `cavalo-`, que eram membros das familias colapsadas e agora
saem da expansao.

**O comportamento em portugues nao mudou, e isso foi medido e nao suposto.** O
conjunto de regras aplicado (padrao, substituicao) e **identico** antes e depois
nos tres tipos:

| conjunto      | antes | depois | identico |
| ------------- | ----- | ------ | -------- |
| pt/automatic  | 899   | 899    | sim      |
| pt/suggestion | 6.819 | 6.819  | sim      |
| pt/cleanup    | 50    | 50     | sim      |

A unica diferenca no arquivo inteiro, em qualquer par de idiomas, e a saida das
291 regras dos seis idiomas que nunca deveriam te-las visto. **Nenhuma regra foi
acrescentada e nenhuma casa se perdeu** — a expansao cobre as 64 por
construcao.

O `glossario.db` foi reconstruido junto (`rebuild_glossary_database`): ele e
indice derivado e se refaz sozinho por hash de conteudo, mas e versionado, e um
par arquivo/indice inconsistente no commit seria um defeito novo (3.7). O
`Substituicoes.txt` anterior ficou em `backups/`, pela funcao do proprio
programa, com a retencao dela.

**Os dois testes voltaram ao verde sem que nenhum limite fosse afrouxado**:
`test_the_real_glossary_declares_the_portuguese_scope` (310 -> 19 globais,
limite 25) e `test_the_real_glossary_uses_the_placeholder` (466 -> 18 literais,
limite 40). Suite inteira: **934 passam, nenhum falha**.

## 26. Corretor ortografico de prosa — CONCLUIDO (2026-08-03)

O item 19.11, o unico que a secao 19 nao entregou. Ele ficou de fora porque
dependia de duas escolhas que 19.14 registrou como sendo de quem mantem o
programa — a dependencia e o dicionario —, e o item so pode ser feito depois que
elas sao feitas. **Foram**, e o levantamento mudou um numero do proprio 19.14
antes de qualquer codigo:

|                          | 19.14 estimava | medido                            |
| ------------------------ | -------------- | --------------------------------- |
| dicionario pt-BR         | ~1 MB          | **5,5 MB** (4,58 `.dic` + 0,97 `.aff`) |
| licenca                  | a decidir      | **LGPL 2.1**, VERO/OpenOffice.org.br |
| codificacao do `.aff`    | —              | **ISO-8859-1**                    |

**Motor: `spylls`, hunspell em Python puro, MIT.** Python puro decide contra o
`cyhunspell`: uma extensao em C pede compilador na maquina de quem instala e
muda a forma do build do PyInstaller, e nenhuma das duas coisas se paga aqui. Se
o pacote faltar, `load_dictionary` trata o import que falha como "sem
dicionario" — o programa abre igual e so o corretor fica de fora.

**Empacotar, e nao baixar na primeira execucao.** Baixar dicionario e
comportamento novo que ninguem pediu, e procura-lo na maquina faria o recurso
existir em umas e nao em outras — o oposto da decisao que 19.14 registrou sobre
recurso pela metade. Os 5,5 MB entram ao lado dos 30 MB de `spelling.ssp` que o
pacote ja carrega: crescimento de ~18%, e nao de ordem de grandeza.

**So o portugues tem dicionario, e a janela diz isso.** Nos outros seis idiomas
de destino ela mostra "Ortografia: sem dicionario para IT (so PT por enquanto)"
em vez de nao marcar nada. Um sublinhado que nunca aparece nao distingue "texto
sem erro" de "corretor ausente", e a janela nao responderia sozinha qual dos
dois e — a mesma discussao da garantia X3.

### 26.1 O filtro do ruido e o item; o dicionario e so o comeco dele

Um corretor generico sobre prosa enxadristica marca o livro inteiro. Medido nas
6.500 linhas do banco de desenvolvimento, com cada filtro em cima do anterior:

| etapa                                          | ocorrencias | distintas |
| ---------------------------------------------- | ----------- | --------- |
| o dicionario nao conhece                       | 5.098       | 2.380     |
| menos notacao e palavra colada a digito        | 3.347       | 1.969     |
| menos o vocabulario do texto de ORIGEM da linha| 143         | 53        |
| menos o lado direito do glossario              | **81**      | **49**    |

**80 linhas de 6.500 recebem alguma marca — 1,2%.** O custo e de **1,00 ms por
linha**, que e o que permite refazer o realce a cada tecla.

Os dois filtros que fazem o trabalho nao sao listas novas para manter:

- **o texto de origem da propria linha.** Nome de jogador, de torneio e de
  cidade chegam a traducao vindos do PGN em ingles, e e la que eles estao.
  Sozinho, leva 3.347 marcas para 143;
- **o lado direito do glossario.** E a terminologia que o proprio usuario impos;
  marca-la seria brigar com a decisao dele. `contra-jogo` sozinho respondia por
  58 das 143. **O lado direito e nao o esquerdo**: a esquerda esta o texto que
  ele quer TROCAR, que e justamente o errado — ensina-lo ao corretor calaria o
  aviso no unico lugar em que ele acerta sozinho.

### 26.2 O que a medicao encontrou, e que nenhum teste teria encontrado

**Dois defeitos meus, os dois no tokenizador, os dois virados regra e teste:**

- **quebrar a palavra no digito** transforma `Cd4` em `Cd`, e `Cd` nao casa
  padrao nenhum de notacao. Eram **40 das 70 marcas mais frequentes** —
  estilhacos de um token que o texto nao tem. Hoje o digito entra no token e
  palavra com digito nunca e marcada: nenhuma palavra de prosa tem um;
- **deixar o apostrofo na ponta** faz `'insipido'` virar a palavra `insipido'`.

**Um erro de medicao meu, que quase apagou o segundo filtro.** A primeira
medicao dizia que o glossario nao tirava marca nenhuma, e por isso ele quase
ficou de fora. O script carregava o glossario sem caminho, e
`_default_substitutions_path()` deriva de `sys.argv[0]` — sob um script do
scratchpad, ele resolvia para o scratchpad e devolvia **vazio**. E a mesma
armadilha que o `setUpModule` da suite documenta, e ela custou aqui a conclusao
oposta da verdadeira: o filtro tira 43% das marcas restantes.

**O indice de sobrenomes do `spelling.ssp` foi medido e descartado.** Ele era a
ideia obvia — 514 mil entradas de jogador ja no programa — e as entradas sao
chaveadas pelo nome INTEIRO (`Carlsen, Magnus`), enquanto a prosa traz o
sobrenome sozinho. Derivar os 212.787 sobrenomes e consulta-los tira **uma**
palavra do resultado (27 -> 26 distintas, na medicao em que ele foi avaliado).
Um indice novo, uma versao de esquema a mais e 25 MB a manter, por uma palavra —
enquanto o filtro do texto de origem ja pega os mesmos nomes de graca, e pela
mesma razao: eles vieram de la.

### 26.3 O que sobra e o que se queria ver

As 49 palavras restantes sao, quase todas, vocabulario que um dicionario de 2010
nao tem — `subvariações`, `dragonistas`, `fianquetada`, `pseudo-sacrifício`,
`contramedidas`, `precisíssimo` — mais alguns toponimos (`Tromsø`, `Breslávia`,
`Calcídica`) e uns poucos nomes que nao aparecem no original da mesma linha. Nao
sao falso positivo barato: sao exatamente as palavras sobre as quais um revisor
decide, e a decisao dele hoje pode virar uma regra de glossario, que **ensina o
corretor no mesmo gesto**.

O sublinhado e vermelho e sem fundo, e nao um realce: a marca cai sobre uma
palavra isolada, e pintar o fundo dela competiria com o realce do glossario e o
da busca, que ja disputam a mesma caixa. Contraste medido sobre o fundo do
texto: 5,0:1 no tema escuro, 5,9:1 no claro.

**O que o dicionario custa, medido e nao estimado**: 2,3 s de carga e **258 MB
de objetos Python** (`tracemalloc`) para os 4,6 MB em disco. E muito, e por isso
a carga e **preguicosa**: acontece na primeira linha aberta num idioma que tem
dicionario, e quem nunca abre o editor — ou trabalha num dos outros seis idiomas
— nao paga nada. A carga vai para uma **thread**, com o realce refeito quando
ela termina; na thread da interface seria a janela congelada na abertura, que e
o que 2.11 tirou de todo o resto do programa.

### 26.4 O cache que nao era cache, e quem o encontrou

A primeira versao de `load_dictionary` conferia o cache **com o cadeado** e o
**soltava para carregar**:

```python
with _dictionary_lock:
    if chave in _dictionaries:
        return _dictionaries[chave]
dicionario = Dictionary.from_files(...)   # <- fora do cadeado
```

Numa janela so isso passa despercebido: a segunda pergunta chega depois de a
primeira ter terminado. Na suite de janelas, nao — cada janela de teste dispara
a carga do seu lado, **nenhuma delas terminou quando as outras conferem o
cache**, e o processo passa a montar varias copias de 4,6 MB em paralelo.

**Medido**: a suite ia de 407 s para nao terminar, com o processo em **1.287 MB**
e subindo. Foi assim que o defeito apareceu — nao num teste que o procurava, mas
no tempo de uma suite que antes fechava em sete minutos.

O conserto sao dois cadeados, e os dois precisam existir: um do **registro**
(rapido, so protege o dicionario) e um por **idioma**, segurado durante a carga
inteira, com a checagem do cache refeita dentro dele. Um cadeado unico segurado
durante a carga faria o idioma B esperar o A sem precisar; um cadeado unico
solto durante a carga e exatamente o defeito.

`test_threads_asking_at_once_do_not_each_load_their_own_copy` fixa isso com oito
threads e um `from_files` que conta chamadas: com a versao errada ele conta
**oito**, com a certa conta **uma**.

### 26.5 O retorno que vinha da thread errada

Consertada a corrida de 26.4, a suite de janelas voltou a terminar — e mostrou o
**segundo** defeito da mesma peca, que so aparece quando a carga de fato termina
em paralelo com janelas sendo abertas e destruidas:

```
Exception in thread Thread-35 (trabalho):
  File "tradutor_pgn/edit_window.py", line 2478, in pronto
    self.win.after(0, aplicar)
  File "tkinter/__init__.py", line 1698, in _register
    self.tk.createcommand(name, f)
RuntimeError: main thread is not in main loop
```

A carga recebia um `on_ready` e o chamava **na thread**; do outro lado, a janela
precisava de `win.after(...)` para voltar a thread do Tk. Mas `after` **registra
um comando no interpretador Tk**, e fora da thread principal isso levanta
`RuntimeError` sempre que a janela ja morreu ou nao ha mainloop rodando. A suite
produziu o traceback **uma vez por janela de teste**, e o `except tk.TclError`
que existia nao pega `RuntimeError`.

Alargar o `except` calaria o sintoma e manteria o desenho errado. **A inversao
conserta a causa**: a thread nao avisa mais ninguem, e a janela **pergunta** —
`request_dictionary` devolve o dicionario ou `None`, `is_loading` diz se vale
perguntar de novo, e quem reagenda e a propria janela, com o `after` dela, que
roda onde deve. Depois disso nenhuma chamada Tk sai da thread principal.

A trava `_prose_retry_scheduled` existe porque `highlight_spelling` roda a cada
tecla: sem ela, cada tecla digitada durante os 2,3 s da carga poria mais um
`after` na fila.

**18 testes** em `ProseSpellcheckTests`, entre eles os dois defeitos do
tokenizador, a corrida de 26.4, o contrato de 26.5 e a contraprova do dicionario
escolhido (ele conhece os 16 termos que o glossario impoe).

### 26.6 Um modulo de teste inteiro nunca rodava

Achado de passagem, ao rodar a suite documentada para conferir 26.5:
`test_background_task.py` importava `from tests.gui_harness import GuiTestCase`,
com o nome **pontuado**. O runner do README e `unittest discover -s tests`, que
poe `tests/` no `sys.path` — e nao a raiz do projeto. Os outros dois modulos de
janela sempre usaram `from gui_harness import`.

O efeito: o modulo **nao era carregado**, e a suite terminava em
`FAILED (errors=1)` com um unico `ImportError` no meio de 1.368 testes que
passavam — a forma mais facil de um erro virar paisagem. Os **17 testes** que
ele traz passam todos; nunca tinham rodado por aqui.

Suite inteira, com o runner documentado: **1.385 testes, OK**.

## 27. Duas entregas e uma cara — CONCLUIDO (2026-08-03)

Pedido do usuario: "cria o executavel instalavel e um que roda da propria pasta,
cria um icone que alude a xadrez e idiomas".

### 27.1 O portatil e o instalavel sao o MESMO executavel

A diferenca inteira entre as duas entregas e **um arquivo vazio ao lado do
`.exe`**: o `portatil.txt` que `app_paths.running_portable()` procura. Com ele,
os dados vao para `dados\` dentro da pasta do programa; sem ele, para
`%APPDATA%\PGN Tradutor Pro\`, como a secao 21 estabeleceu.

Dois builds separados seriam duas coisas para construir, testar e manter em dia
por causa de **uma linha de comportamento** — e a versao que ninguem roda e a
que quebra primeiro.

A ordem de precedencia ganhou um degrau no meio:

| o que decide                | pasta de dados                        |
| --------------------------- | ------------------------------------- |
| `PGN_TRADUTOR_DATA`         | o que a variavel disser               |
| `portatil.txt` ao lado do exe | `<pasta do programa>\dados\`        |
| empacotado                  | `%APPDATA%\PGN Tradutor Pro\`         |
| do fonte                    | ao lado do script                     |

**A variavel continua vencendo o marcador**, e nao o contrario: apontar um
`.exe` de pendrive para o acervo do disco e exatamente o caso que ela existe
para atender.

**O marcador so vale empacotado.** Do fonte os dados ja ficam ao lado do script,
entao ele nao teria o que mudar — e um `portatil.txt` esquecido no checkout nao
pode alterar onde a suite grava. Ha teste para isso.

**Uma subpasta `dados\`, e nao a raiz da pasta do programa.** Copiar a pasta
para o pendrive leva programa e acervo juntos, e ainda da para olhar e ver o que
e do usuario e o que e do programa.

**O marcador nunca entra em `dist\`**, e isso e o ponto delicado: o `.iss`
empacota `dist\*` inteiro com `recursesubdirs`, entao um `portatil.txt`
esquecido la viajaria para dentro do INSTALADOR e faria a versao instalada
gravar dentro de `Program Files` — o defeito que a secao 21 consertou, de volta
pela porta do empacotamento. `empacotar-portatil.py` escreve o marcador **direto
no zip**, o disco nunca o ve, e ele **recusa** rodar se encontrar um solto em
`dist\`.

**A linha do log passou a nomear o modo**, e nao so a pasta: `Pasta de dados
(portatil): ...`. Sao quatro situacoes e o caminho sozinho nao distingue duas
delas — um `.exe` portatil e um instalado apontado por `PGN_TRADUTOR_DATA` podem
gravar na MESMA pasta por motivos diferentes, e saber qual esta valendo e o que
explica o que a proxima atualizacao vai fazer com aquele acervo.

**Verificado com o `.exe` de verdade**, e nao so por teste: o zip foi extraido
num diretorio temporario e o programa aberto. Ele criou `dados\` ao lado de si
com `Substituicoes.txt`, `glossario.db` e `traducoes.db` — e o
`%APPDATA%\PGN Tradutor Pro\` continuou com os arquivos de 2026-07-30, sem um
byte tocado.

### 27.2 O icone

Um peao partido ao meio: metade clara, metade escura — as duas cores do
tabuleiro, que sao as duas linguas. No peito, `N` e `C`: o cavalo em ingles e o
cavalo em portugues, que e a troca que o programa faz o dia inteiro. Embaixo,
quatro casas fecham a base.

**Bandeira nao entrou de proposito**, que e a saida obvia para "idiomas": ela
nomeia PAIS, e o programa traduz para sete linguas — a de Portugal e a do Brasil
seriam duas bandeiras para o mesmo `pt`.

**Desenhado por codigo** (`recursos/gerar_icone.py`), e nao guardado so como
binario: o `.ico` tem seis tamanhos, e refaze-los a mao a cada ajuste e onde um
icone envelhece. Cada tamanho e desenhado NO PROPRIO TAMANHO — reduzir o de 256
borra os tracos finos que dao a forma.

Tres rodadas de ajuste, todas olhando uma folha de contato com os seis tamanhos
lado a lado e as ampliacoes de 16 e 32 px. O que cada uma mostrou esta no
docstring do gerador, porque e o que evita refazer a conta no proximo ajuste: o
peao estava pequeno demais no quadro; as letras transbordavam a silhueta e
pousavam no fundo; e a faixa do tabuleiro flutuava separada da base.

A regra que ficou: **o que nao sobrevive a 32x32 nao entra** — por isso as
letras so aparecem a partir de 48 px. Em 16 px o icone e o peao bicolor sobre a
faixa, que e a leitura que resiste.

Ele vai a **tres** lugares, e os tres sao necessarios: recurso do `.exe` do
programa (o que o Explorer mostra), recurso do `.exe` do instalador
(`SetupIconFile` — sem ele o assistente e o unico arquivo da entrega com o icone
generico do Inno Setup, justamente o primeiro que o usuario ve) e arquivo dentro
do pacote, de onde `apply_window_icon` o le para por na janela. O recurso do
`.exe` nao e um caminho que o Tk consiga abrir.

`apply_window_icon` **nunca levanta**: icone e enfeite, e enfeite nao pode
impedir o programa de abrir. Sem o arquivo, a janela abre com o icone do Tk,
como antes deste item.

### 27.3 As duas entregas

    python -m PyInstaller PGN_Tradutor_Pro.spec        # o executavel
    ISCC.exe instalador\PGN_Tradutor_Pro.iss           # o instalador
    python instalador\empacotar-portatil.py            # o portatil

| entrega                                    | tamanho |
| ------------------------------------------ | ------- |
| `PGN-Tradutor-Pro-0.3.0-instalador.exe`    | 25,6 MB |
| `PGN-Tradutor-Pro-0.3.0-portatil.zip`      | 33,3 MB |

O zip leva um `LEIA-ME-PORTATIL.txt` gerado junto, que diz onde os dados ficam,
o que acontece ao apagar o marcador, como atualizar sem perder o acervo e como
usar a variavel de ambiente.

O instalador nao ficou maior por causa dos 5,5 MB do dicionario: o `lzma2` do
Inno Setup comprime melhor um `.dic` de 4,6 MB do que o `deflate` do zip.

**Quatro testes novos** em `DataDirRuleTests`, entre eles a contraprova de que o
marcador nao faz nada rodando do fonte e a de que a variavel continua vencendo.
Suite inteira: **1.389 testes, OK**.

### 27.4 Um susto que nao era defeito, e como ele foi descartado

A primeira rodada da suite depois deste item levou **1.048 s** contra os 373 s da
anterior, e cuspiu **24 tracebacks** de `can't delete Tcl command` no teardown
das janelas — nenhum deles existia antes. Com uma chamada nova de `iconbitmap`
em toda abertura de janela, a suspeita era obvia.

**Nao era.** Medido A/B nos testes da janela principal, com e sem a chamada:

| | tempo | erros de Tcl |
| ----------------- | ------- | --- |
| com `iconbitmap`  | 76,3 s  | 0   |
| sem `iconbitmap`  | 72,1 s  | 0   |

O que explicava as duas coisas era a maquina: a rodada aconteceu logo depois de
extrair os 33 MB do zip portatil e rodar o `.exe` de dentro dele, com o antivirus
varrendo tudo. Repetida com a maquina quieta, a suite voltou a **514 s e zero
erros de Tcl**.

Fica registrado porque a conclusao errada era barata de tirar e cara de desfazer:
o proximo a ver esses 24 tracebacks nao precisa refazer o A/B.
