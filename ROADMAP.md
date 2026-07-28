# Roadmap — PGN Tradutor Pro

Registro das melhorias do programa. Cada item traz o motivo, o impacto medido
(quando ha medicao) e como a correcao foi verificada — inclusive quando a
verificacao mostrou que a analise estava errada, caso em que o erro fica no
proprio item.

**Nada pendente no momento.** As garantias que os testes protegem estao na
[SPEC.md](SPEC.md), secao 8; ela e a lista que vale, e nao uma copia aqui.

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

| o que a nota dizia | o que era |
|---|---|
| "11 de 25 funcoes de `app_actions` aparecem em algum teste" (5.1) | aparecer nao e ser exercitada: **cinco** eram chamadas |
| "agora que `background_task` existe, migra-los e mecanico" (2.7 -> 2.11) | cada operacao deixa um lixo diferente ao ser cancelada, e ligar as tres expos um defeito do proprio 2.7 |
| a assimetria dos dois editores, anotada na skill como armadilha de uso | era divida estrutural — o item 3.1 inteiro, no outro editor, e sem estar no ROADMAP |

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

| padrao | fica | sai |
|---|---|---|
| `brancas para jogar` | #1070 `brancas jogam` | `brancas de jogar` |
| `e e f` | #6115 `'e' e 'f'` | `'e' e f` |
| `as Pretas` | #6996 `as pretas` | `das pretas` |
| `/\` | #6103 `com a idéia de` (sugestao) | `Com a ideia de` (automatica) |

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

| onde | como | compatibilidade |
|---|---|---|
| `Substituicoes.txt` | 4o elemento da tupla | so escrito quando != 0 |
| `glossario.db` | coluna `priority` | `ALTER TABLE` + reconstrucao |
| CSV | coluna `priority` | opcional na leitura |

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

| operacao | antes | agora |
|---|---|---|
| troca de pagina (filtro "todas") | 559 ms | **47 ms** |
| troca de pagina (filtro "Avisos QA") | 544 ms | **38 ms** |
| contagem de avisos | 491 ms | **1,3 ms** |

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

| etapa | tempo |
|---|---|
| previa (`analyze_database_automatic_rules`) | 12,4 s |
| aplicar (`apply_database_automatic_rules`) | 25,7 s |
| **total de um clique no botao** | **38,1 s** |

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

| | antes | agora |
|---|---|---|
| tempo do clique | 38,1 s | **26,0 s** |
| pico de memoria | 80 MB | **1 MB** |
| janela | travada | responde, com progresso e "Cancelar" |

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

| consulta | sem busca | com busca |
|---|---|---|
| `count_review_rows` | 9,7 ms | **~100 ms** |
| `get_review_status_counts` | 35,1 ms | **~110 ms** |
| `fetch_review_rows_page` | 8,4 ms | 1,3 ms a 105 ms |

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

| cenario | antes | agora |
|---|---|---|
| sem busca, filtro "todas" | 43,7 ms | **33,4 ms** |
| busca `bispo`, filtro "todas" | 217,3 ms | **109,0 ms** |
| busca sem nenhum resultado | 264,3 ms | **131,0 ms** |
| busca `bispo`, filtro "Avisos QA" | 121,6 ms | 108,7 ms |

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

| modo | casa | custo |
|---|---|---|
| **Termos** (FTS5) | palavra inteira; `bisp*` para prefixo | O(pagina) |
| **Trecho** (`LIKE`) | qualquer pedaco, ate no meio de palavra | O(tabela) |

Um seletor no topo da lista decide qual vale, a escolha e lembrada entre sessoes,
e trocar o modo refaz a busca na hora — deixar o resultado antigo na tela com o
seletor novo faria a lista mentir sobre o que esta mostrando. O padrao e
"Termos", que e o caminho rapido.

Medido no banco real (195.607 linhas), somando o resumo de status e a pagina:

| cenario | Trecho | Termos |
|---|---|---|
| sem busca | 33,9 ms | 33,4 ms |
| `bispo`, 1a pagina | 109,4 ms | **39,1 ms** |
| `bispo`, pagina 100 | 205,7 ms | **45,8 ms** |
| termo sem nenhum resultado | 196,5 ms | **18,6 ms** |
| dois termos | 215,3 ms | **28,0 ms** |

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

| operacao | tempo | memoria |
|---|---|---|
| `load_translation_cache` (inicio de cada traducao) | 0,75 s | **58 MB** |
| `fetch_export_rows` (Exportar CSV) | 1,0 s | **102 MB** |
| `analyze_automatic_translation_updates` | 12,4 s | **80 MB** |

Nenhuma e um defeito hoje — o computador aguenta —, mas as tres crescem com o
banco e duas nao precisam da lista:

- **Exportar CSV** so escreve linha a linha. `csv.writerows(cursor)` aceita o
  proprio cursor: memoria constante e o arquivo comeca a sair na hora.
- **Regras automaticas**: ver 2.7.
- **Cache de traducao** e o caso legitimo: e um dicionario de consulta usado o
  tempo todo pelo worker. Vale registrar o custo (58 MB por idioma, hoje) e o
  ponto de virada: se o banco dobrar, cabe carregar so os comentarios dos
  arquivos que vao ser processados, que e um `SELECT ... WHERE original_comment
  IN (...)` sobre uma lista que o worker ja tem em maos.

**Feito:** as regras automaticas (junto com 2.7, 80 MB -> 1 MB) e a exportacao de
CSV. `fetch_export_rows` devolve o cursor em vez de `fetchall`, e o
`csv.writerows` consome direto:

| | antes | agora |
|---|---|---|
| exportar CSV (195.607 linhas, 41 MB) | 1,7 s / **102 MB** | 1,1 s / **~0 MB** |

**Feito tambem o cache de traducao.** A previsao era esperar o banco dobrar; nao
foi preciso, porque a mudanca e menor do que parecia: o worker ja extraia todos
os comentarios para `info_by_file` **antes** de usar o cache. Bastou mover a carga
para depois da extracao e passar a lista que ele ja tinha em maos.

| cenario | antes | agora |
|---|---|---|
| pasta com 200 comentarios | 306 ms / 74 MB | **4 ms / 0,1 MB** |
| pasta com 2.000 | 306 ms / 74 MB | **40 ms / 0,6 MB** |
| 20.000 (10% da tabela) | 306 ms / 74 MB | **304 ms / 5,7 MB** |
| a tabela inteira (pior caso) | 306 ms / 74 MB | 333 ms / 75 MB |

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

| | antes | agora |
|---|---|---|
| `order_rules_by_specificity` (57 regras) | 0,0174 ms | **0,0072 ms** |
| `find_glossary_suggestions` (7.008 regras) | 12,5 ms | **10,7 ms** |

A ordenacao passou a ser memorizada por **conteudo** das regras — a lista nao e
hashavel e o `id()` dela nao serve (uma lista nova pode reaproveitar o endereco
de uma coletada), entao a chave e a tupla dos pares.

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

| operacao | antes | agora | atualizacoes de progresso |
|---|---|---|---|
| backup do banco | 396 ms | 397 ms | 13 |
| exportar CSV (41 MB) | 1079 ms | 1062 ms | 41 |

O ganho e o outro: durante esse tempo a janela ficava parada, sem dizer o que
estava acontecendo e sem forma de desistir — e a importacao de um CSV grande nao
tem teto nenhum. Os arquivos gerados sao **identicos** aos de antes (conferido
byte a byte pelo tamanho e pelo conteudo em teste).

**A copia do SQLite passou a ser em blocos.** `Connection.backup(..., pages=,
progress=)` existe justamente para isso: sem `pages` a copia e uma chamada so
que retorna no fim, sem lugar para reportar nem para desistir. `BACKUP_PAGES_PER_STEP
= 2048` (~8 MB) da 13 atualizacoes num banco de 81 MB e custa 1 ms no total.

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

| era | virou |
|---|---|
| `show_message` (x2) | `flash_message` |
| `save_editor_settings` (x2) | `save_window_section` |
| `restore_pane_position(s)` (x2) | `restore_sash` + `collect_sash_positions` |
| `render_rows` (x2) | `render_row_buttons` + um `build_row_button` por editor |

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

| | mediana | min |
|---|---|---|
| antes (chave montada inline, com a regra na tupla) | 4,48 ms | 4,40 ms |
| depois (`sorted` sobre as posicoes) | **3,62 ms** | 3,57 ms |

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

| marca | o que era | por que nao sobrevive |
|---|---|---|
| `source_path` | `C:\Python Course\...\Substituicoes.txt` | absoluto: outra pasta ja diverge |
| `source_mtime` | `1785184475.31` | o git nao guarda `mtime`; o arquivo clonado tem a hora do checkout |

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

| mutacao | quem acusa |
|---|---|
| `source_path` volta a ser absoluto | `..._survives_a_clone`: "o cache clonado foi descartado" |
| `source_hash` volta a ser o `mtime` | o mesmo, **e** `..._rewriting_the_same_content...` |
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
e exatamente o que ela precisa para nao ser feita as cegas. `tests/
test_editor_windows.py` abre as janelas de verdade, clica nos botoes e confere
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

| modo | commit por traducao | commit por lote |
|---|---|---|
| `delete` + `synchronous=FULL` (o antigo) | 3,45 ms | 0,11 ms |
| `wal` + `synchronous=NORMAL` (o novo) | **0,14 ms** | 0,01 ms |

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
  cada um gasta outras 3 tentativas. Repare que nesse caso nem log ha — o `if
  translated_joined` deixa a mensagem de fora justamente quando a causa e a pior.

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

| | 1a espera | 2a espera |
|---|---|---|
| antes (qualquer status) | 0,3–2,2 s | 0,3–2,2 s |
| agora, 5xx | 0,6 s | 1,2 s |
| agora, 429 | **2,0 s** | **4,0 s** |

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
