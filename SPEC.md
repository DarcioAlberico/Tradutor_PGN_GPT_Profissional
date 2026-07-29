# Especificacao — PGN Tradutor Pro

Documento de referencia do comportamento do sistema. Descreve **o que** o programa
faz e sob quais garantias, nao **como** cada funcao esta escrita.

Versao do documento: 2026-07-28.

---

## 1. Objetivo

Traduzir os comentarios (`{...}`) de arquivos PGN de xadrez, preservando
integralmente lances, variantes e metadados, com:

- cache persistente de traducoes (SQLite), para nunca pagar duas vezes pela
  mesma frase — indexado pelo **par de idiomas**, para que o mesmo texto vindo
  de duas linguas nao seja tratado como uma traducao so;
- um glossario de substituicoes controlado pelo usuario, para corrigir a
  terminologia enxadristica que o tradutor automatico erra;
- uma etapa de revisao humana assistida.

Nao-objetivos: jogar xadrez, validar legalidade de lances, editar a arvore de
variantes.

---

## 2. Componentes e artefatos em disco

Todos os caminhos sao resolvidos a partir do diretorio de `sys.argv[0]`
(o diretorio do `PGN_Tradutor_Pro.py`). Empacotado com PyInstaller, `sys.argv[0]`
e o caminho do proprio `.exe` — e nao a pasta temporaria de extracao —, entao os
artefatos abaixo ficam ao lado do executavel, e a pasta dele precisa ser
gravavel.

| Artefato | Papel | Versionado |
|---|---|---|
| `traducoes.db` | Cache de traducoes + historico de edicoes | Nao |
| `traducoes.db` (`PRAGMA user_version`) | Versao do schema; migracao so roda quando desatualizada | — |
| `comments_fts` (dentro do `traducoes.db`) | Indice de busca FTS5, mantido por gatilhos (R8) | Nao |
| `Substituicoes.txt` | Fonte de verdade do glossario | Sim |
| `glossario.db` | Indice SQLite derivado do `Substituicoes.txt` | Sim |
| `glossario.db` (`schema_version`) | Marca do esquema; um banco de versao anterior e reconstruido do arquivo | — |
| `glossario.db` (`source_path`, `source_hash`) | De qual arquivo ele veio: caminho relativo ao proprio banco e hash do conteudo | — |
| `pgn_tradutor_pro_settings.json` | Estado da UI e rascunhos de edicao | Nao |
| `backups/` | Copias automaticas do glossario e do banco, com retencao (S8) | Nao |
| `logs/` | Log por execucao de traducao (`traducao-<carimbo>.log`), com retencao | Nao |
| `spelling_ssp/spelling.ssp` | Dicionario de nomes proprios do "Normalizar PGN" | Sim |

O `pgn_tradutor_pro_settings.json` guarda tambem a lista de arquivos que ficaram
com comentarios sem traduzir na ultima execucao, usada pelo "Reprocessar Falhas"
(garantia T4), e as escolhas da janela principal (garantia M1).

**Garantia M1 — a janela principal reabre no que foi escolhido.** Idioma de
origem, idioma de destino, caminho e "processar subdiretorios" sao gravados
quando mudam e restaurados na abertura.

O idioma de ORIGEM e a razao de isto existir. Ele e a escolha que mais muda o
resultado — decide o `sl=` da API e liga a correcao das letras dos lances (P3) —,
e o padrao dele, "Detectar", e justamente o valor que deixa as duas desligadas.
Resetando a cada abertura, esquecer um clique custa uma execucao inteira
traduzida no escuro, e nada denuncia isso depois: o PGN gerado parece pronto.

A gravacao passa por `update_settings`, que rele o disco imediatamente antes de
escrever: os rascunhos das janelas de edicao vivem no mesmo arquivo (garantia
R4). Um valor que o programa nao reconhece mais — um idioma que saiu da lista,
um tipo errado, a secao inteira corrompida — cai no padrao em vez de deixar um
seletor num estado que ele nao sabe exibir. O caminho salvo **nao** e conferido
contra o disco: ele pode estar num pendrive que ainda nao foi plugado, e quem
valida a existencia e o "Iniciar Traducao", que ja o fazia.

---

## 3. Pipeline de traducao

### 3.1 Extracao

1. Coleta os `.pgn` do caminho escolhido (arquivo ou pasta, com ou sem
   subdiretorios). Arquivos ja gerados pelo programa (sufixo de idioma) sao
   ignorados quando a origem e uma pasta.
2. Para cada arquivo, detecta a codificacao e le o conteudo.
3. Extrai cada comentario `{...}` e o **achata**: colapsa espacos em branco e
   normaliza o espaco depois de `.`, `!` e `?`. O texto achatado e a chave de
   cache; a posicao (inicio, fim) no arquivo original e guardada.

**Garantia E1 — deteccao de codificacao.** A codificacao e decidida analisando
o arquivo **inteiro**, nunca uma amostra. Um arquivo cujos acentos aparecem so
depois dos primeiros 64 KB deve ser lido corretamente.

**Garantia E2 — `ascii` nunca e um veredito final.** Um arquivo cujo prefixo e
ASCII puro nao pode ser lido como ASCII, porque bytes altos podem aparecer
adiante. Quando o conteudo e integralmente ASCII, adota-se UTF-8 (superset
seguro).

**Garantia E3 — ordem de preferencia.** BOM UTF-8 vence; depois UTF-8 valido;
depois o palpite do `chardet` (confianca >= 0.60), com `windows-1252` mapeado
para `cp1252`; por fim `cp1252` e `latin-1` por tentativa de decodificacao.

**Garantia E4 — a codificacao escolhida decodifica o arquivo inteiro.** Nenhum
ramo da deteccao devolve uma codificacao sem confirmar que ela da conta de todos
os bytes, nem mesmo quando ha BOM ou quando o `chardet` responde com confianca
alta. Sem isso, `errors='replace'` na leitura injeta `U+FFFD` em silencio — e
esse texto e o que vira chave de cache e o que e gravado de volta no PGN.

E4 tambem cobre o que E1/E2/E3 nao alcancavam, que era conteudo multibyte:

- As BOMs de UTF-16 e UTF-32 sao reconhecidas junto com a de UTF-8. A BOM longa
  e testada antes da curta, porque `FF FE` (UTF-16-LE) e prefixo de
  `FF FE 00 00` (UTF-32-LE).
- UTF-16 **sem** BOM e reconhecido pelos NUL intercalados, antes do teste de
  ASCII puro — que ele passaria, ja que `\x00` e ASCII valido. O lado em que os
  NUL caem decide entre little e big-endian.

A leitura de um mesmo PGN gravado em UTF-8, UTF-8 com BOM, cp1252, UTF-16 LE/BE
sem BOM, UTF-16 com BOM e UTF-32 produz os mesmos comentarios, com ou sem o
`chardet` instalado — que e um import opcional.

### 3.2 Lotes

Comentarios sao agrupados em lotes e enviados **numa unica requisicao**,
unidos pelo separador `" ||| "`.

- O tamanho do lote respeita `BATCH_MAX_CHARS`, ja contando os separadores.
- Um comentario maior que o limite forma um lote sozinho.

**Garantia B1 — o lote nunca e fatiado.** `BATCH_MAX_CHARS` e estritamente
menor que `MAX_TRANSLATE_CHARS` (o limite de divisao por sentenca da camada de
API). Se nao fosse, um lote poderia ser cortado no meio de um separador e o
realinhamento seria impossivel. Essa relacao e verificada em teste.

**Garantia B2 — realinhamento ou nada.** Se a resposta traduzida nao devolver
exatamente o numero esperado de partes, o lote e descartado e os comentarios
sao traduzidos individualmente. Nunca se atribui uma traducao a um comentario
sem certeza de alinhamento.

**Garantia B3 — falha de API nao e desalinhamento.** O caminho individual so e
acionado quando a resposta **veio** e nao pode ser realinhada. Se a chamada em si
falhou, os comentarios do lote sao contados como falha de uma vez: repeti-los um
a um so gastaria outras 3 tentativas por comentario contra um endpoint que ja
nao respondeu.

`MAX_CONSECUTIVE_FAILED_BATCHES` lotes seguidos sem nenhuma resposta interrompem
a execucao, com o motivo no log e no dialogo final. O contador zera assim que a
API responde qualquer coisa, inclusive uma resposta desalinhada — que e problema
do conteudo e nao da conexao.

Quando a execucao e interrompida assim, o PGN de saida do arquivo em andamento
**nao** e gerado: ele sairia quase todo no idioma original e pareceria pronto. O
que ja foi traduzido esta no banco, entao reexecutar paga so o que falta.

### 3.3 Idioma de origem

O usuario declara em que idioma os PGN estao, entre os sete que o programa
conhece, ou escolhe **"Detectar"** — que e o padrao e o comportamento que o
programa sempre teve. A escolha tem tres efeitos:

- a API recebe `sl=<idioma>` em vez de `sl=auto`, e deixa de adivinhar a partir
  de um comentario que muitas vezes tem tres palavras;
- a traducao e gravada dentro do **par** (origem, destino), que e o que permite
  ao editor mostrar um par de cada vez;
- "Reprocessar Falhas" reusa o par inteiro da execucao que falhou, e nao so o
  destino.

**Garantia P1 — o par de idiomas e a identidade da traducao.** A chave da tabela
e `(comentario original, idioma de origem, idioma de destino)`. O mesmo texto
vindo do espanhol e do italiano sao duas traducoes independentes, e nenhuma e
oferecida no lugar da outra.

"Detectar" nao e um idioma: as linhas que ele produz ficam com a origem **nao
informada**, o mesmo estado das linhas gravadas antes de o programa perguntar. E
uma string vazia, e nao `NULL`, porque num indice UNIQUE o SQLite considera todo
`NULL` distinto de qualquer outro — com `NULL` ali, a chave deixaria de valer
justamente para as linhas legadas e cada execucao as inseriria de novo.

**Garantia P2 — declarar o idioma nao cobra o cache de novo.** As traducoes ja
gravadas ficaram sem idioma de origem, e uma execucao que declara um idioma as
**adota**: as linhas daqueles comentarios que ainda nao tem origem passam a ter a
declarada. Sem isso, a primeira execucao a dizer "estes PGN estao em espanhol"
nao acharia nenhuma das 201.607 linhas existentes e mandaria tudo de volta para
a API.

A adocao so alcanca quem **nao tinha idioma nenhum**: reetiquetar uma linha que
ja diz de onde veio seria apagar uma declaracao do usuario com outra. E ela nunca
derruba a execucao — se ja existir uma linha no par de destino, a linha sem
rotulo permanece como esta.

### 3.4 Traducao e cache

Para cada comentario:

1. Se ja esta no cache em memoria, reusa.
2. Senao, aplica as regras de **limpeza** (`cleanup`). Se o resultado ficar
   vazio, o comentario e considerado descartavel e vira string vazia.
3. Senao, vai para a API. A resposta recebe as regras **automaticas**
   (`automatic`) e e gravada no cache.

O cache em memoria traz **apenas os comentarios dos arquivos desta execucao**, e
nao o idioma inteiro: sao os unicos pelos quais o worker pergunta. Acima de
metade da tabela a carga completa sai mais barata e e usada — o dicionario passa
a conter mais do que foi pedido, o que e indiferente para a consulta mas torna
`len(cache)` inutil como contagem do que veio destes arquivos.

**Garantia T1 — nunca sobrescrever traducao existente.** A gravacao no cache
so insere linhas novas ou preenche traducoes vazias. Uma traducao ja
preenchida (possivelmente revisada por humano) jamais e substituida pelo
processo automatico.

**Garantia T2 — falha e sempre reportada.** Um comentario que nao pode ser
traduzido e contabilizado como falha, registrado no log e exibido no resumo
final. O programa nunca apresenta uma execucao com falhas como sucesso limpo.

**Garantia T4 — a falha fica anotada.** Terminada uma execucao com falhas, os
arquivos que ficaram devendo sao registrados junto com o idioma, e
"Reprocessar Falhas" reexecuta **so eles**. Reprocessar tudo tambem funciona (o
cache torna barato o que ja deu certo), mas cobra uma varredura da pasta inteira
por causa de dois arquivos.

O idioma vem do registro, e nao do seletor: a lista foi montada traduzindo para
aquele idioma, e reaproveita-la com outro produziria um arquivo misturado sem que
ninguem tivesse pedido. A lista explicita nao passa pelo filtro de arquivos ja
gerados — senao um PGN de origem chamado `estudo-BR.pgn` sairia dela justamente
por ter falhado antes.

Uma execucao sem falhas apaga o registro; uma execucao cancelada nao o toca,
porque os arquivos ainda nao visitados nao foram avaliados e a lista parcial
perderia o que a anterior ja sabia. Arquivos que sumiram do disco no intervalo
sao ignorados e informados.

**Garantia T3 — falha nao inventa texto.** Um comentario que falhou permanece
no idioma original no arquivo de saida. E um resultado aceitavel, desde que
declarado (ver T2).

### 3.5 Letras das pecas nos lances

A notacao algebrica usa uma letra por peca, e **as letras colidem entre
idiomas**: o `R` do ingles e Torre, o `R` do portugues e Rei.

| peca | en | pt | es | fr | it | de | ru |
|---|---|---|---|---|---|---|---|
| Rei | K | R | R | R | R | K | Кр |
| Dama | Q | D | D | D | D | D | Ф |
| Torre | R | T | T | T | T | T | Л |
| Bispo | B | B | A | F | A | L | С |
| Cavalo | N | C | C | C | C | S | К |

**Garantia P3 — as letras dos lances vem do comentario original.** Antes de
gravar, cada lance da traducao e conferido contra o lance correspondente do
original. So a letra da peca (e a da promocao) muda; casa, captura, desempate,
xeque e o `=` saem do proprio texto. A funcao nunca insere um lance que nao
estava la nem apaga um que estava — o pior resultado possivel dela e deixar um
lance como o tradutor escreveu.

**Nao da para fazer isso com regras de glossario, e o motivo e o mesmo da
garantia S4.** Um par de regras `K -> R` e `R -> T` aplicado em sequencia
destroi a informacao: depois da primeira, os `R` que vieram de `K` sao
indistinguiveis dos que ja eram `R`, e a segunda transforma os dois em `T`. Nao
e a ordem que esta errada — e a sequencia. Numa passagem so, `Kf1` vira `Rf1` e
`Rf1` vira `Tf1`.

Isso resolve metade. A outra e que o tradutor **e inconstante**: as vezes traduz
o lance, as vezes deixa, as vezes erra. Medido no endpoint real, traduzindo do
ingles para o portugues:

```
EN     The move Rd1 doubles the rooks; Kg2 is slow.
Google O movimento Rd1 dobra as torres; Kg2 e lento.
```

O `Rd1` e o pior caso possivel: **parece** notacao portuguesa valida e nomeia a
peca errada. Olhando so a traducao nao ha como distinguir um Rei ja traduzido de
uma Torre que ficou para tras. Quem distingue e o original.

**A ancora e a parte do lance que nao muda de idioma** — `f1`, `xe4+`, `bd7`.
Um lance do original e um lance da traducao com a mesma ancora sao o mesmo lance,
e a letra e o que se corrige. Quando a ancora empata (duas pecas para a mesma
casa, "Rf1 ou Kf1"), o desempate e a ordem; se nem ela resolver, **nada e
tocado**.

A captura conta como `x`, `×` ou `:`, e a ancora normaliza os tres. Nao e
tolerancia gratuita: material publicado usa `×`, e uma regra automatica do
glossario converte `×` em `x` — entao o original guarda `N×d4` e a traducao chega
com `Nxd4`. Sem normalizar, os dois teriam ancoras diferentes e o lance nao seria
pareado. Medido no banco real: 4.316 capturas com `x`, 198 com `×` e 7 com `:`.

**O corpo do lance corrigido sai da TRADUCAO**, e nao do original — e o que "so a
letra muda" quer dizer literalmente. Copiar o lance do original inteiro parece
equivalente e nao e: devolveria ao texto o `×` que o glossario acabou de
normalizar, desfazendo em silencio uma decisao do usuario.

**A leitura do original e restrita ao idioma declarado; a da traducao, nao.** No
original a letra e a informacao, e aceitar mais alfabetos devolveria a
ambiguidade que declarar o idioma veio resolver. Na traducao a letra e ruido —
o tradutor pode devolver a notacao inglesa ate num par que nao passa pelo ingles
—, entao ali vale qualquer letra conhecida.

Sem idioma de origem declarado a correcao **nao roda**, e o log diz isso: sem
saber em que alfabeto o original esta, corrigir seria trocar um erro do tradutor
por um palpite do programa.

**Garantia P4 — o que ja estava gravado tambem alcanca a correcao.** P3 so
protege o que passa pela traducao; o que entrou no banco antes dela continua com
as letras que o tradutor deixou — 4.144 de 201.603 traducoes no banco real. A
ferramenta "Corrigir Lances" aplica a mesma correcao ao que ja esta gravado, para
o par de idiomas que os seletores da janela principal declaram.

Ela **rotula e corrige na mesma transacao**, e a ordem importa: enquanto as
linhas estiverem como "origem nao informada" elas nao pertencem a par nenhum, e a
correcao — que precisa saber o que `R` significa no original — nao teria como
alcanca-las. Cancelar desfaz as duas: uma metade aplicada, linhas rotuladas com
os lances ainda errados, seria um estado que ninguem pediu e que nao se distingue
do correto.

Como toda escrita em massa: backup antes, previa com contagem e exemplos,
progresso e cancelamento, `rollback` ao desistir. O `quality_warning` e
reavaliado (R6) e cada alteracao entra no historico (R2) — isto reescreve texto
que o usuario pode ter revisado a mao, e ele precisa poder ver o que era. O
`verified` **nao** e mexido: corrigir a letra de um lance nao desfaz a revisao
humana do resto do comentario.

A previa e a aplicacao usam **o mesmo criterio de escopo**, num lugar so. A
primeira versao nao usava — a previa olhava so o par declarado, e as linhas
legadas so entravam nele durante a aplicacao —, entao ela anunciava "nenhuma
traducao precisa de correcao" exatamente no caso para o qual a ferramenta existe.

### 3.6 Geracao do PGN traduzido

O arquivo de origem e relido e cada comentario e substituido pela traducao, de
tras para frente (para nao invalidar as posicoes). Chaves `{` e `}` dentro de
uma traducao viram parenteses, para nao quebrar a estrutura do PGN.

Saida: `<nome>-<SUFIXO>.pgn` ao lado do original (`BR`, `EN`, `ES`, `FR`,
`DE`, `IT`, `RU`). Se o nome ja existir, sufixa `-2`, `-3`, ...

**Garantia G1 — o original nunca e modificado.**

**Garantia G2 — a saida preserva os acentos.** A gravacao usa a codificacao
detectada na origem; se algum caractere nao couber nela, cai para UTF-8 e
registra isso no log. Em nenhuma hipotese um caractere e substituido por
`U+FFFD` no arquivo gerado.

### 3.7 Controle de execucao

Roda em thread separada, com pausa e cancelamento cooperativos. Toda
atualizacao de interface e agendada na thread principal do Tk.

**Garantia C1 — Tk so na main thread.** Nenhum widget e tocado fora da thread
principal; o log usa fila + polling.

**Garantia C2 — cancelamento preserva o trabalho feito.** Ao cancelar, o que
ja foi traduzido esta gravado no banco.

**Garantia C3 — o worker nao segura o banco.** O worker e o editor de traducoes
usam o **mesmo** `traducoes.db`, cada um com sua conexao. Duas conexoes nunca
escrevem ao mesmo tempo — nem em WAL —, entao uma transacao de escrita aberta no
worker bloqueia o "Salvar" do editor ate o `busy_timeout` (30 s) e depois falha.

Por isso **nenhuma transacao de escrita permanece aberta atravessando uma chamada
de rede**. No caminho individual (o do fallback), cada traducao e comitada antes
da requisicao seguinte; antes disso a transacao atravessava o lote inteiro, o que
com 40 comentarios passava dos 30 s do editor. Gravar no editor durante uma
traducao espera, no maximo, o tempo de uma gravacao.

O banco fica em `journal_mode=WAL` com `synchronous=NORMAL`. Isso nao e o que
resolve o bloqueio acima — e o que torna o commit por traducao barato (0,14 ms
contra 3,45 ms em `delete`+`FULL`) e o que garante que a leitura do editor nunca
espere, nem durante um commit. `synchronous=NORMAL` significa que uma queda do
sistema operacional pode custar as ultimas transacoes; uma queda do programa,
nao. Para um cache que se reconstroi reexecutando, e a troca aceita.

A outra metade de C3 e que **uma colisao nunca aparece como traceback**. Hoje
improvavel, mas nao impossivel — e sob `pythonw` nao ha console, entao ela
simplesmente desapareceria e a gravacao apenas nao aconteceria.

O tratamento e o gancho do proprio Tk (`report_callback_exception`, instalado na
raiz na abertura do programa), e nao um `try` em cada acesso ao banco. Duas
razoes: o buraco nunca foi so do lock — era de **todo** callback do programa —, e
capturar dentro de `save_changes` e seguir adiante seria pior do que o
comportamento atual, porque a navegacao continuaria e a edicao do usuario seria
descartada em silencio. Deixando a excecao subir, o fluxo aborta como ja abortava
e o usuario passa a ser avisado.

O lock tem mensagem propria — diz que ha uma traducao em andamento, que nada foi
gravado e que basta tentar de novo — porque e o unico caso previsto e com causa
conhecida. A mesma mensagem nao reabre o dialogo por alguns segundos, para que um
callback periodico que falhe sempre nao encha a tela; passada essa janela, quem
tentar de novo e avisado de novo.

**Nenhuma operacao longa roda no callback do botao.** Ficam fora da thread da
interface, com barra de progresso: a traducao (que tem tambem pausa), a
normalizacao de metadados, a aplicacao das regras automaticas, o backup e a
restauracao do banco, e a importacao e a exportacao de CSV.

**Desistir no meio nao deixa lixo**, e o que isso exige e diferente em cada uma:

| operacao | ao cancelar |
|---|---|
| regras automaticas, importacao de CSV | `rollback`: o banco fica como estava |
| backup do banco | a copia parcial e apagada |
| exportacao de CSV | o arquivo parcial e apagado |
| restauracao do banco | **nao aceita cancelamento** |
| zerar o banco de traducoes | **nao aceita cancelamento** |

Um `.db` cortado no meio e um banco incompleto com cara de backup, e o proximo
"Restaurar backup" o ofereceria na lista; um CSV cortado abre, tem cabecalho e
linhas validas, e nada nele denuncia que esta pela metade. Por isso os dois sao
removidos.

O backup criado **antes** de uma importacao de CSV permanece mesmo se ela for
cancelada: e uma copia valida, e apaga-la seria destruir o unico registro de que
a operacao chegou a comecar.

A restauracao e o "zerar" sao as excecoes, e pelo mesmo motivo: as duas escrevem
no **banco de trabalho** e nao tem o recurso de apagar o que foi escrito —
interrompidas, deixam o banco incompleto. Oferecer um botao que nao pode ser
honrado seria pior do que nao oferecer, porque o usuario clicaria achando que
parou. A confirmacao avisa disso antes de comecar, e ela e a hora de desistir.

---

## 4. Zerar o banco e zerar o glossario

Duas ferramentas que apagam o trabalho acumulado do usuario — as traducoes ou as
regras — e sao as unicas do programa sem volta por dentro dele. O que existe e o
backup.

**Garantia Z1 — o backup vem antes da pergunta.** A copia e criada e o caminho
dela aparece na propria confirmacao. Custa 0,4 s no banco real e e a unica forma
de voltar atras; deixa-la para depois do "Apagar" significaria que uma falha
entre a confirmacao e a copia apaga tudo sem rede. O pior caso desta ordem e uma
copia a mais em `backups/` para quem desistiu, e a retencao (S8) cuida dela.

**Garantia Z2 — a confirmacao e digitada, nao clicada.** O usuario escreve
`delete`; ate entao o botao de apagar fica inerte **e parece inerte**. As demais
confirmacoes do programa sao `Sim/Nao` e bastam para o que e reversivel; aqui um
"Sim" fica a um pixel do "Nao", e o que se perde sao 201 mil traducoes ou 7 mil
regras. Aceita-se qualquer caixa e espaco nas pontas: quem digitou `DELETE `
decidiu tanto quanto quem digitou `delete`.

Fechar a janela, apertar `Esc` ou clicar em "Cancelar" e **nao**. Nao ha caminho
em que sumir com o dialogo signifique seguir adiante, e o proprio comando do
botao reconfere a palavra em vez de confiar no estado dele.

**Garantia Z3 — uma zera, a outra nao e afetada.** Zerar as traducoes nao toca
no glossario e vice-versa. Zerar as traducoes leva junto o historico de edicoes
(historico de traducoes que nao existem mais nao e historico de nada), esvazia o
indice de busca, libera o espaco em disco (`VACUUM`) e limpa o cache em memoria —
que tem precedencia sobre o banco e, deixado como estava, faria a proxima
traducao reaproveitar exatamente o que acabou de ser apagado.

Nenhuma das duas roda com uma traducao em andamento.

---

## 5. Glossario

### 5.1 Formato

`Substituicoes.txt` contem uma atribuicao Python com uma lista de tuplas, lida
com `ast.literal_eval` (nunca `exec`). Cada regra tem de dois a quatro campos —
`(original, substituicao, tipo, prioridade)` — e **cada campo so e escrito quando
tem algo a dizer**:

```python
substituicoes = [
    ('rook', 'torre'),                     # tipo suggestion, prioridade 0
    ('Queen', 'Dama'),
    ('== EndSquare ==', '', 'cleanup'),    # outro tipo
    ('torre', 'castle', 'suggestion', 1),  # com prioridade
]
```

O que faltar assume o padrao, entao um arquivo escrito por uma versao anterior
continua valendo sem conversao. O inverso tambem importa: o arquivo tem milhares
de linhas e e versionado, e escrever os quatro campos em todas transformaria uma
decisao tomada em duas regras num diff do arquivo inteiro.

Tipos:

| Tipo | Quando e aplicado | Revisao humana |
|---|---|---|
| `cleanup` | Antes de enviar para a API | Nao |
| `automatic` | Na resposta da API e em massa no banco | Nao |
| `suggestion` | Oferecido no editor, aplicado a pedido | Sim |

Um tipo ou uma prioridade que o programa nao entenda vira o padrao, em vez de
erro: o arquivo e editavel a mao e sobrevive a versoes do programa, e uma regra
mal escrita nao pode desligar as outras milhares na carga.

O CSV de importacao/exportacao tem as mesmas quatro colunas (`original`,
`replacement`, `type`, `priority`), e a leitura aceita a ausencia das duas
ultimas — um CSV de tres colunas, ou montado numa planilha, continua importavel.

### 5.2 Semantica de casamento

- O padrao da regra e sempre tratado como texto literal (escapado), nunca
  interpretado como expressao regular.
- Uma regra escrita **inteiramente em minusculas** casa sem diferenciar
  maiusculas; qualquer maiuscula na regra a torna sensivel a caixa.
- Quando o primeiro (ou ultimo) caractere do padrao e caractere de palavra,
  exige-se fronteira de palavra desse lado. `rook` nao casa dentro de `rooks`;
  `-fileira` casa depois de qualquer coisa.
- A capitalizacao do texto encontrado e propagada para a substituicao.

**Garantia S1 — matches nunca se sobrepoem.** Numa mesma regra, as ocorrencias
substituidas sao disjuntas. Aplicar `('de de' -> 'de')` a `"de de de"` produz
`"de de"`, nunca `"dede"`. Nenhum caractere fora de um match e removido.

**Garantia S2 — indices sao do texto original.** A busca sem diferenciar
maiusculas nao pode deslocar posicoes. Caracteres cujo `lower()` muda de
comprimento (`İ`, `ẞ`) nao podem corromper o texto nem impedir o casamento.

**Garantia S3 — a regra mais especifica vence.** As regras sao aplicadas em
ordem decrescente de comprimento do padrao, para que uma regra curta nao consuma
o texto que uma regra longa pretendia casar. Com `('verificacao' -> 'xeque')` e
`('da verificacao intermediaria' -> 'do xeque intermediario')`, vence a segunda.
Empates preservam a ordem do arquivo.

**Garantia S10 — a prioridade explicita decide antes do comprimento.** Uma regra
pode declarar uma prioridade inteira; a maior e aplicada primeiro, e so entre
prioridades iguais o comprimento (S3) volta a decidir. Zero e o valor de toda
regra que ninguem priorizou, entao S3 continua sendo o criterio de praticamente
todo o glossario.

Existe porque a especificidade e **derivada do texto**: sem prioridade, adiantar
uma regra exige alongar o padrao — mudar o que ela casa para mudar quando ela
roda. O campo separa as duas coisas.

No arquivo, a prioridade e o quarto elemento da tupla e so aparece quando nao e
zero (`('orig', 'novo', 'suggestion', 2)`); no CSV e a coluna `priority`, opcional
na leitura. Um `Substituicoes.txt` ou um CSV de antes desta versao continua
valendo, com prioridade zero em tudo.

**Garantia S4 — o texto substituido e final.** Um trecho ja produzido por uma
regra nao e reexaminado pelas regras seguintes. Sem isso, duas regras
contraditorias se desfazem uma a outra e o resultado passa a depender da ordem
em que foram digitadas. Exemplo real do glossario:

```
('Rei das brancas estao', 'Rei das brancas esta')
('brancas esta',          'brancas estao')
```

A segunda nao pode reverter a primeira. Cada regra entrega exatamente o que
declarou, e a regra genérica continua valendo onde a especifica nao alcanca.

**Garantia S9 — a interface diz qual regra do conflito esta valendo.** Duas
regras com o mesmo padrao e substituicoes diferentes nao empatam. S3 ordena por
comprimento do padrao; padroes identicos empatam sempre, entao o que decide e a
prioridade (S10) e, sem ela, a ordem do arquivo — vence quem foi digitado
primeiro, e o congelamento de S4 impede a outra de rever o trecho. O editor
mostra, na regra selecionada, qual delas o programa aplica, e oferece duas
saidas: "Priorizar esta", que a poe na frente sem apagar nada, e "Manter esta",
que remove as concorrentes do arquivo.

O vencedor e **por contexto**. `Substituicoes.txt` e uma lista so, mas o programa
carrega tres recortes dela: limpeza, automaticas, e sugestoes do editor (que
carrega sugestoes **e** automaticas). Duas regras so disputam dentro de um
recorte: uma de limpeza e uma de sugestao nunca sao aplicadas ao mesmo texto e
por isso nao conflitam. E uma regra pode perder no editor e ser a unica do seu
padrao nas automaticas — la ela e aplicada, e a mensagem diz isso em vez de
"nunca e aplicada".

Duplicata exata nao e conflito: e redundancia, e ja tem aviso proprio. O filtro
"Conflitos" e a contagem do rodape usam a mesma avaliacao da mensagem, entao a
lista mostra exatamente as regras para as quais a janela sabe dizer quem vence.

O anuncio nao imita o criterio da aplicacao: ele **usa** o criterio da aplicacao.
Anunciar e aplicar chamam a mesma ordenacao, sobre a mesma conversao de entrada
em regra, de modo que uma mudanca na ordem em que as regras disputam o texto
muda o que a janela diz na mesma edicao. Enquanto eram dois codigos, o que
mantinha os dois juntos era so um teste comparando os resultados.

**Garantia S5 — falha de carga e visivel.** Se o `Substituicoes.txt` estiver
malformado, o usuario e avisado no log da janela e num dialogo. O sistema nunca
opera em silencio com o glossario vazio, e um arquivo quebrado nunca impede o
programa de abrir — ele degrada para "sem regras" e diz por que.

O aviso nao pode depender do `stdout`: empacotado com `pythonw` nao ha console
nenhum. `glossario.py` publica as falhas por um handler que a interface
registra (`set_glossary_error_handler`), de modo que o modulo continua sem
importar Tk. Como a carga tambem acontece na thread do worker, cabe ao handler
levar o dialogo para a thread do Tk (garantia C1).

### 5.3 Edicao

- Toda gravacao e atomica (arquivo temporario + troca) e precedida de backup.
- `glossario.db` e um indice derivado; pode ser reconstruido a partir do
  arquivo texto a qualquer momento.

**Garantia S6 — a operacao atinge a entrada apontada.** Adicionar, editar ou
remover afeta exatamente a entrada escolhida, mesmo havendo duplicatas no
arquivo e mesmo que o glossario tenha mudado por fora desde que a janela
carregou.

A entrada e identificada pelo **conteudo** que o editor exibiu, nao pela posicao
no arquivo: a janela nao e notificada de alteracoes externas, e uma insercao
feita por outra janela desloca todos os indices seguintes. A posicao guardada
vale como desempate — se ainda contiver a entrada esperada, e ela que e
afetada, o que resolve o caso de duplicatas exatas.

Se a entrada nao existir mais como estava, **nada e gravado** e o usuario e
avisado. Escrever na posicao antiga sobrescreveria a entrada vizinha em
silencio.

**Garantia S7 — entradas nao tem espaco nas pontas.** Padrao e substituicao sao
normalizados na gravacao. Um espaco no fim do padrao e consumido pelo casamento
mas nao devolvido pela substituicao, colando duas palavras:
`(' a-coluna ' -> ' coluna a')` transforma `"na a-coluna aberta"` em
`"na coluna aaberta"`. Um espaco no inicio ainda desliga a checagem de fronteira
daquele lado. Nenhum dos dois efeitos e intencional.

**Garantia S8 — `backups/` tem retencao, e ela so apaga backup.** Depois de
criar uma copia, sobrevivem as `keep_count` mais novas daquela especie; das
restantes, saem as mais velhas que `BACKUP_MAX_AGE_DAYS`, nunca abaixo de um
piso de `BACKUP_KEEP_MINIMUM`. Tres limites do que a limpeza pode tocar:

- Os backups do glossario (`.txt`) e do banco (`.db`) convivem na mesma pasta e
  sao contados **separadamente** — salvar o glossario nao descarta backup do
  banco.
- Um arquivo cujo nome nao tenha o carimbo `AAAAMMDD-HHMMSS` nao e backup do
  programa e nunca e removido.
- A copia recem criada, e o backup que uma restauracao ainda vai ler, ficam
  fora do alcance da limpeza.

A familia do banco tem ainda um teto de ESPACO, e nao so de contagem: cada
copia e o banco inteiro, que cresce com o uso, entao um numero fixo de copias
nao limita disco. Guarda-se o maior conjunto de copias recentes que cabe no
teto, respeitando o mesmo piso minimo.

A ordem "mais novo" vem do carimbo no **nome**, nao do `mtime`: a copia do
glossario preserva o mtime da origem, entao todas teriam a mesma data.

A politica e avaliada em dois momentos: depois de cada backup criado e **uma vez
na abertura do programa**, fora da thread da interface. So o primeiro nao basta —
enquanto ninguem salvar o glossario, nada e avaliado, e quem parar de edita-lo
fica com a pilha inteira para sempre.

`logs/` tem a mesma politica (`LOG_KEEP_COUNT`, `LOG_MAX_AGE_DAYS`), com os
arquivos nomeados `traducao-<carimbo>.log`. Logs gravados antes disso usavam
underscore no carimbo, nao casam com o padrao e por isso nunca sao removidos.

---

## 6. Editor de traducoes

Lista paginada por **par de idiomas**, com filtros (pendentes / verificadas /
avisos de qualidade) e busca. Permite editar, marcar como verificada, navegar por
avisos, consultar e restaurar historico, e aplicar sugestoes do glossario.

**Garantia R9 — a lista mostra um par de idiomas de cada vez.** Dois seletores
proprios, origem e destino, decidem o que e carregado; nada de outro par entra na
lista, na contagem do rodape ou no relatorio de QA. Revisar uma traducao do
espanhol achando que e do italiano nao produz erro nenhum — produz uma revisao
errada, e e disso que o filtro protege.

Os dois nao sao simetricos, e a diferenca tem razao:

| seletor | opcoes | lembrado entre sessoes |
|---|---|---|
| **Origem** | Todos · Nao informado · os sete idiomas | Sim |
| **Destino** | os sete idiomas | Nao: vem da janela principal |

"Todos" so existe na origem porque a janela edita as traducoes de **um** idioma
de destino — o rascunho, o titulo e a aplicacao das regras automaticas sao todos
por destino. E "Nao informado" nao e sinonimo de "Todos": ele traz exatamente as
linhas cuja origem ninguem declarou, que sao a maioria de um banco anterior a
esta versao.

O destino nao e lembrado de proposito: guarda-lo faria quem marcasse "Ingles" na
janela principal abrir o editor em portugues, sem nada na tela explicando de onde
aquilo veio.

A barra de status nomeia o par da **linha carregada**, que com "Origem: Todos" nao
e o mesmo que o filtro — e e justamente ai que a informacao importa, porque e o
unico momento em que a lista mistura idiomas de origem de proposito.

Trocar qualquer um dos dois grava a edicao aberta antes (a linha pertence ao par
antigo e sai da lista na troca) e volta para a primeira pagina — a pagina 40 do
par anterior nao quer dizer nada no novo. Com um filtro de origem ativo,
"Aplicar automaticas" fica restrito a ele: reescrever tambem as linhas das outras
linguas seria uma alteracao em massa que o usuario nao pediu nem consegue ver.

**Garantia R1 — gravacao e sempre intencional.** Apenas uma acao deliberada do
usuario altera o banco. Navegar pela lista nao reescreve traducoes.

**Garantia R5 — navegar custa O(tamanho da pagina).** Trocar de
pagina ou de filtro nunca le a tabela inteira. Os avisos de qualidade ficam
materializados na coluna `quality_warning`, entao contar e paginar "com aviso" e
uma consulta indexada.

Isso vale **tambem com o filtro de origem ativo**, e nao de graca: o indice de
cobertura do resumo de status precisou incluir a origem. Sem ele a agregada
deixava de ser resolvida so no indice e voltava a tocar a tabela — medido no
banco real, 34,9 ms sem filtro de origem contra 78,7 ms com ele. Seria uma
regressao de R5 introduzida justamente pelo filtro que R9 veio dar. Com o indice
sao 34,5 ms e 35,9 ms; um par sem nenhuma linha responde em 0,0 ms.

**Garantia R8 — navegar custa O(pagina) tambem com busca ativa.** A busca do
editor tem dois modos, e o usuario escolhe qual vale:

| modo | como filtra | casa | custo |
|---|---|---|---|
| **Termos** | indice FTS5 | palavra inteira (`bisp*` para prefixo) | O(pagina) |
| **Trecho** | `LIKE '%x%'` | qualquer pedaco, ate no meio de palavra | O(tabela) |

Nenhum substitui o outro, e por isso os dois existem. O indice resolve o custo,
mas muda a semantica: `bisp` deixa de achar "bispo". O `LIKE` e o unico jeito de
procurar um trecho literal, e continua disponivel — mais lento, e declaradamente.
"Termos" e o padrao, e a escolha e lembrada entre sessoes.

Medido em 195.607 linhas, somando o resumo de status e a pagina:

| | Trecho | Termos |
|---|---|---|
| sem busca | 33,9 ms | 33,4 ms |
| `bispo`, 1a pagina | 109,4 ms | **39,1 ms** |
| `bispo`, pagina 100 | 205,7 ms | **45,8 ms** |
| termo sem resultado | 196,5 ms | **18,6 ms** |

Com o indice, buscar custa o mesmo que nao buscar, e o custo para de crescer com
a profundidade da pagina — que era o ponto de R5.

O indice e um FTS5 `external content` (`content='comments'`): guarda so os termos,
sem duplicar o texto. Custa ~25 MB sobre um banco de 81 MB, e a criacao leva 1,8 s
uma vez, na primeira abertura apos a atualizacao. Quem o mantem em dia sao tres
gatilhos; a remocao usa o comando `'delete'` com os valores **antigos**, sem o
qual os termos de uma linha apagada ficam no indice para sempre. Os acentos sao
dobrados (`remove_diacritics 2`), entao "traducao" acha "tradução".

O texto digitado nunca vai cru para o `MATCH`: `AND`, `-`, `*`, `:`, `(` e aspas
sao operadores do FTS5, e uma busca por `bispo (branco)` viraria erro de sintaxe
no meio da navegacao. Cada palavra e enviada como termo literal; so o `*` final e
preservado, porque e ele que devolve o casamento por prefixo.

A busca por termos **degrada para o `LIKE`** — sem avisar, porque o resultado
continua correto — quando o SQLite nao tem o modulo FTS5, quando o indice ainda
nao existe no arquivo, ou quando a expressao nao sobra nenhum termo utilizavel.

Eram duas varreduras por interacao ate 2026-07-27: o total do filtro ativo era
pedido numa segunda consulta, com o mesmo `WHERE` da agregada de status que ja
havia acabado de rodar. Hoje ele sai do proprio resumo (`STATUS_COUNT_KEYS`), e a
correspondencia entre filtro e chave do resumo e verificada em teste contra a
consulta dedicada — os dois criterios vivem em codigos diferentes e, se
divergirem, a lista pagina por um numero errado sem erro visivel.

**Garantia R6 — o cache de avisos nunca diverge.** `quality_warning` e derivada
de `evaluate_translation_quality` e atualizada em toda escrita de traducao
(insercao, preenchimento de vazia, edicao manual e aplicacao em massa das regras
automaticas). A contagem exibida e sempre igual ao que a avaliacao em Python
produziria para as mesmas linhas.

**Garantia R2 — historico completo.** Toda alteracao registra estado anterior,
novo, e status de verificacao, em `comment_history`.

**Garantia R3 — a janela de historico opera sobre o item que ela declara.** Ela
e modeless: a lista principal continua clicavel enquanto ela esta aberta. O item
e fixado na abertura e nunca relido do editor, senao "Restaurar" gravaria naquele
que estivesse selecionado no instante do clique. Se o editor ja estiver mostrando
outra traducao, a restauracao grava no banco e **nao** toca no texto na tela.

**Garantia R7 — a lista carrega o item clicado.** Selecionar uma linha grava a
anterior, e essa gravacao pode remover linhas da lista: com o filtro "Avisos QA"
ativo, corrigir o aviso tira a propria linha; com "Pendentes", verificar faz o
mesmo. A linha a carregar e identificada pelo **id** capturado antes da
gravacao, nunca pela posicao — que a essa altura ja aponta para outra coisa.
Vale igualmente para "proxima" depois de verificar: se a linha atual saiu da
lista, quem ocupou o lugar dela e a proxima, e nao a seguinte.

**Garantia R4 — rascunhos sobrevivem.** O rascunho nao salvo e persistido e
recuperado. Janelas concorrentes nao apagam os rascunhos uma da outra, e a
gravacao das configuracoes e atomica.

---

## 7. Normalizacao de metadados PGN

Corrige **apenas** as tags `White`, `Black`, `Site`, `Event` e `Round`, usando
`spelling_ssp/spelling.ssp`. Saida com sufixo `-NORM.pgn`.

**Garantia N1 — comentarios, lances e variantes nao sao tocados.** So as tags
listadas acima mudam; todo o resto do arquivo sai identico, linha a linha.

A lista de tags corrigidas tem uma fonte unica (`SUPPORTED_TAGS`), e o padrao
que reconhece as linhas candidatas e derivado dela. Mantidas em dois lugares,
as duas copias falhavam em silencio ao divergir: uma tag declarada e nao
reconhecida simplesmente nao era corrigida, e uma tag reconhecida e nao
declarada derrubava a normalizacao do arquivo inteiro.

---

## 8. Rede

Usa o endpoint publico do Google Translate, sem autenticacao. Nao ha chave de
API no projeto — nem deve haver.

- Sessao HTTP reusada durante toda a execucao.
- Ate 3 tentativas, apenas para 429/500/502/503/504.
- Outros codigos falham imediatamente.

**Garantia W1 — o programa nunca envia nada alem do texto a traduzir.**

**Garantia W2 — o programa desacelera quando a API reclama.** A resposta a um 429
acontece em dois lugares, porque um so nao basta:

- **Entre as tentativas da mesma requisicao**, a espera dobra a cada tentativa
  (teto de 20 s), e 429 parte de uma base maior que 5xx — um pede ritmo menor, o
  outro e instabilidade passageira do servidor. O jitter e multiplicativo, para
  que execucoes simultaneas se espalhem em proporcao a espera.
- **Entre requisicoes**, o intervalo normal e multiplicado a cada 429 e volta a
  cair so depois de uma sequencia de requisicoes sem reclamacao. Sem isso, o
  retry consertaria a requisicao que falhou e deixaria intacta a causa: a
  seguinte sairia no mesmo ritmo que provocou o 429.

Sobe rapido e desce devagar. Um 5xx nao altera o ritmo. Em repouso — nenhum 429 —
o intervalo e exatamente `TRANSLATION_REQUEST_DELAY_SECONDS`, como antes.

---

## 9. Invariantes que os testes devem proteger

| # | Invariante | Origem |
|---|---|---|
| E1 | Codificacao decidida pelo arquivo inteiro | Bug: acentos destruidos apos 64 KB |
| E2 | `ascii` nunca e veredito final | Mesmo bug |
| E4 | A codificacao escolhida decodifica o arquivo inteiro | Bug: UTF-16 lido como UTF-8, com NUL entre as letras |
| G2 | Saida sem `U+FFFD` | Mesmo bug |
| B1 | `BATCH_MAX_CHARS < MAX_TRANSLATE_CHARS` | Acoplamento fragil entre modulos |
| B2 | Desalinhamento -> traducao individual | — |
| B3 | Falha de API nao vira reprocessamento comentario a comentario | Bug: um lote morto custava ~1 h de requisicoes inuteis |
| W2 | Backoff exponencial, e o ritmo cai ao ver 429 | Risco: intervalo agressivo sem defesa contra limite de taxa |
| T1 | Nao sobrescrever traducao existente | — |
| T2 | Falhas contabilizadas e exibidas | Bug: sucesso reportado com PGN bilingue |
| T4 | A lista de falhas sobrevive a execucao, e so ela e reprocessada | Custo: reexecutar tudo por causa de dois arquivos |
| P1 | O par (original, origem, destino) e a identidade da traducao | Limite: o mesmo texto em duas linguas era uma linha so |
| P2 | Declarar o idioma adota o cache existente em vez de paga-lo de novo | Risco: a mudanca de chave cobrar 201.607 traducoes ja feitas |
| P3 | As letras dos lances vem do original, numa passagem so | Bug: `Rd1` (Torre) traduzido como `Rd1` (Rei) |
| P4 | A correcao alcanca tambem o que ja estava gravado | Limite: P3 so valia para traducao nova, e 4.144 linhas ficariam erradas |
| S1 | Matches disjuntos | Bug: `"de de de"` -> `"dede"` |
| S2 | Indices do texto original | Bug: `İ` desloca offsets |
| S3 | Regra especifica vence a generica | Bug: regra curta encobre a longa |
| S4 | Texto substituido e final | Bug: regras contraditorias se desfazem |
| S5 | Falha de carga chega na interface | Bug: `print` invisivel sob `pythonw` |
| S6 | Editar/excluir atinge a entrada correta | Bug: indice obsoleto grava na vizinha |
| S7 | Entradas sem espaco nas pontas | Bug: 48 regras colavam palavras |
| S8 | Retencao so apaga backup, da familia certa | Risco da limpeza automatica |
| S9 | A interface diz qual regra do conflito vence, pelo mesmo criterio que a aplica | Bug: regras iguais lado a lado, sem dizer qual dispara |
| S10 | Prioridade explicita decide antes do comprimento | Limite: adiantar uma regra exigia alongar o padrao |
| R1 | Gravacao so por acao do usuario | Bug: navegar reescreve o banco |
| R5 | Navegar custa O(pagina) | Perf: paginacao anulada por varredura |
| R8 | Navegar custa O(pagina) tambem com busca ativa | Perf: `LIKE '%x%'` varre a tabela a cada interacao |
| R6 | Cache de avisos nao diverge | Risco da coluna materializada |
| R7 | A lista carrega o item clicado | Bug: clicar em B carregava C |
| R9 | O editor mostra um par de idiomas de cada vez | Queixa de uso: revisar em espanhol achando que era italiano |
| Z1 | O backup vem antes da pergunta, e o caminho dele aparece nela | Risco: a unica volta atras depender de o que vem depois do "Apagar" |
| Z2 | Apagar exige a palavra digitada, e o botao parece inerte ate la | Risco: "Sim" a um pixel do "Nao" para 201 mil traducoes |
| Z3 | Zerar um nao toca no outro, e leva junto historico, indice e cache | Risco: o cache em memoria reviver o que foi apagado |
| N1 | So as cinco tags mudam; lances, variantes e comentarios saem identicos | Risco: a lista de tags vivia em dois lugares |
| C1 | Trabalho pesado roda fora da thread do Tk, e a resposta volta nela | Bug: "Aplicar automaticas" segurava a janela por 38 s |
| C3 | Nenhuma transacao de escrita atravessa uma chamada de rede, e um lock vira mensagem | Bug: worker travava o "Salvar" do editor por um lote inteiro |
| M1 | A janela principal reabre no que foi escolhido | Risco: "Detectar" volta sozinho e desliga a correcao de lances sem avisar |

---

## 10. Limites conhecidos

Cada item tem o numero do ROADMAP que o resolve. Estao aqui para que ninguem
leia uma garantia acima como mais ampla do que ela e.

**Concorrencia**

- A restauracao do banco e o "Zerar Traducoes" nao podem ser cancelados depois
  de comecar: os dois escrevem no banco de trabalho e interrompe-los o deixaria
  incompleto. O que da para desistir e antes de comecar, na confirmacao.
  (ROADMAP 2.11, 9.1)
- A barra de progresso pode demorar a sair do lugar em operacoes limitadas por
  CPU: a thread de trabalho segura o GIL entre dois relatos, e a atualizacao so
  chega quando a thread da interface e escalonada. A janela responde e o
  "Cancelar" funciona; o que atrasa e o numero. (ROADMAP 2.11)

**Desempenho e escala**

- O modo "Trecho" varre a tabela por definicao — e o preco de achar um pedaco
  literal, e a interface declara qual modo esta ativo.
- A migracao para o schema 4 custa ~7 s uma vez, na primeira abertura apos a
  atualizacao: a tabela de 201.607 linhas e reconstruida porque o SQLite nao
  remove restricao de tabela, e so isso troca a UNIQUE antiga pela do par de
  idiomas. Os ids sao preservados, entao o indice FTS5 continua valendo e nao
  precisa ser refeito. (ROADMAP 9.2)

**Rede**

- Depende de um endpoint nao oficial, sujeito a bloqueio por volume.

**Idioma de origem**

- A correcao das letras dos lances (P3 e P4) so roda com o idioma de origem
  declarado. Em "Detectar" ela fica desligada, e o log — ou, na ferramenta, um
  dialogo — diz por que.
- "Corrigir Lances" rotula **todas** as linhas sem origem do idioma de destino
  com o idioma declarado. E uma afirmacao do usuario sobre o proprio acervo, e
  nao uma deteccao: se parte dele veio de outra lingua, essas linhas ficam
  rotuladas errado. O backup anterior a operacao e o caminho de volta.
- Ela confere **a letra da peca**, e nao a legalidade do lance: um `Kf1` que o
  tabuleiro nao permite continua saindo como `Rf1`. Validar lance exigiria a
  posicao, que o programa nao le (e nao-objetivo, secao 1).
- Um lance que o alfabeto declarado nao explica nao vira ancora. Isso deixa de
  fora a notacao descritiva, a figurina e o PGN cujo idioma foi declarado
  errado — nesses casos a correcao simplesmente nao acontece.
- "Detectar" e as linhas gravadas antes desta versao compartilham o mesmo balde,
  "nao informado". Sao coisas diferentes — uma e uma escolha, a outra e ausencia
  de escolha — e o programa nao as distingue: guardar dois valores para "nao sei"
  daria dois filtros que ninguem sabe escolher entre si. O que separa uma linha
  do balde e declarar o idioma, e ai a adocao (P2) a leva para o par certo.
- Uma execucao em "Detectar" nao reaproveita as traducoes de um par declarado, e
  vice-versa: sao pares diferentes, e e o que P1 diz. O preco e traduzir de novo
  um texto que existe no outro balde; o ganho e nunca entregar a traducao de uma
  lingua para outra.
- O idioma declarado nao e verificado contra o conteudo. Dizer "espanhol" para um
  PGN italiano produz uma traducao ruim e uma linha rotulada errado, e o programa
  nao tem como saber — declarar e uma afirmacao do usuario, nao uma deteccao.

**Glossario e arquivos gerados**

- O glossario e uma lista linear. A prioridade explicita (S10) resolve o caso de
  adiantar uma regra, mas so entre regras — nao ha grupos, escopos por idioma
  nem condicoes: uma regra vale para todo texto do seu recorte. Em particular,
  **o glossario nao e por par de idiomas**: as mesmas regras valem para as
  traducoes de todas as linguas de origem.

**Estrutura**

- `glossario.db` e um cache derivado, e um cache pode ficar velho de um jeito que
  a data do arquivo nao denuncia: uma coluna nova entra com o valor padrao para
  todas as regras. Por isso ele carrega uma marca de esquema (`schema_version`) e
  e reconstruido a partir do `Substituicoes.txt` quando ela nao bate. **Toda
  coluna acrescentada tem de subir essa marca** — e tambem toda mudanca no
  significado de `source_path` ou `source_hash`, que e como o banco diz de onde
  veio.
- O cache e versionado, entao as marcas de origem precisam valer em outra
  maquina: `source_path` e relativo ao proprio banco e `source_hash` e o conteudo
  do arquivo, nao a data dele. Um caminho absoluto ou um `mtime` fariam o clone
  reconstruir o indice na primeira carga, que e o que versiona-lo pretende
  evitar. O preco e ler o `Substituicoes.txt` a cada checagem em vez de um
  `stat`: 0,28 ms contra 0,03 ms, dentro de uma checagem que custa ~1,3 ms.

---

## 11. Garantias planejadas

Declaradas aqui para que a secao 9 continue sendo apenas o que os testes ja
protegem. Cada uma entra na tabela quando o item correspondente do ROADMAP
estiver pronto e tiver teste que falhe sem a correcao.

Nenhuma pendente no momento.

| # | Garantia | Item |
|---|---|---|
