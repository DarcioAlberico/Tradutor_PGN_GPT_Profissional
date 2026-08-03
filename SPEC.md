# Especificacao — PGN Tradutor Pro

Documento de referencia do comportamento do sistema. Descreve **o que** o programa
faz e sob quais garantias, nao **como** cada funcao esta escrita.

Versao do documento: 2026-07-29.

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

**Dado de usuario e dado de programa moram em lugares diferentes, e quem decide
e como o programa foi iniciado** (ROADMAP 21):

| inicio | pasta de dados do usuario |
|---|---|
| `PGN_TRADUTOR_DATA=<pasta>` | vence todos os outros |
| empacotado **com `portatil.txt` ao lado do `.exe`** | `<pasta do programa>\dados\` |
| empacotado (`sys.frozen`) | `%APPDATA%\PGN Tradutor Pro\` |
| do fonte (`python PGN_Tradutor_Pro.py`) | ao lado do script |

O marcador portatil so vale **empacotado** (ROADMAP 27): do fonte os dados ja
ficam ao lado do script, e um `portatil.txt` esquecido no checkout nao pode
mudar onde a suite grava.

E o que permite atualizar o programa sem tocar no trabalho de quem usa: a
instalacao troca a pasta do programa inteira, e a de dados nem e vista. E e o que
permite ter o app instalado e o repositorio na mesma maquina sem que um enxergue
os dados do outro — a suite de testes, que roda do fonte, nao alcanca o acervo.

O que vem COM o programa (`spelling.ssp`, dicionario-semente,
`Termos-suspeitos.txt` e o glossario inicial) sai de `__file__`, viaja dentro do
pacote e **e** substituido por uma atualizacao. A regra tem as duas pontas: o que
sai de `__file__` a atualizacao troca, o que sai da pasta de dados ela nunca
toca.

| Artefato | Papel | Versionado |
|---|---|---|
| `traducoes.db` | Cache de traducoes + historico de edicoes | Nao |
| `traducoes.db` (`PRAGMA user_version`) | Versao do schema; migracao so roda quando desatualizada | — |
| `comments_fts` (dentro do `traducoes.db`) | Indice de busca FTS5, mantido por gatilhos (R8) | Nao |
| `occurrences` (dentro do `traducoes.db`) | Onde cada comentario foi lido: arquivo, partida, indice e lance (O1) | Nao |
| `Substituicoes.txt` | Fonte de verdade do glossario do usuario | Sim |
| `tradutor_pgn/Substituicoes-semente.txt` | Terminologia que vem com o programa (S15) | Sim |
| `glossario.db` | Indice SQLite derivado do `Substituicoes.txt` | Sim |
| `glossario.db` (`schema_version`) | Marca do esquema; um banco de versao anterior e reconstruido do arquivo | — |
| `glossario.db` (`source_path`, `source_hash`) | De qual arquivo ele veio: caminho relativo ao proprio banco e hash do conteudo | — |
| `pgn_tradutor_pro_settings.json` | Estado da UI e rascunhos de edicao | Nao |
| `backups/` | Copias automaticas do glossario e do banco, com retencao (S8) | Nao |
| `logs/` | Log por execucao de traducao (`traducao-<carimbo>.log`), com retencao | Nao |
| `spelling_ssp/spelling.ssp` | Dicionario de nomes proprios do "Normalizar PGN" — dado de PROGRAMA, vai dentro do pacote | Sim |
| `spelling.db` (na pasta de dados) | Indice SQLite derivado dele, construido na primeira normalizacao (D6). Fica com os dados porque e escrita: na pasta do programa, um `Program Files` o barraria e a normalizacao ficaria no caminho lento para sempre | Nao |
| `tradutor_pgn/Substituicoes-inicial.txt` (no pacote) | Copia do glossario feita no build; a primeira execucao a instala na pasta de dados quando nao ha glossario la | — |
| `spelling.db` (`schema_version`, `source_hash`, `entry_count`) | Marcas do indice; a do hash e gravada por ultimo e significa "construcao concluida" | — |

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

**Garantia M2 — um BOM no arquivo de configuracoes nao apaga nada.** A leitura e
`utf-8-sig` e a gravacao e `utf-8`: aceita-se o BOM, nao se escreve um. O arquivo
e JSON editavel a mao, e o Bloco de Notas do Windows grava UTF-8 com BOM — lido
como `utf-8`, o `json.load` levanta, a leitura degrada para "sem configuracao" e
o programa perde de uma vez os rascunhos das janelas de edicao (R4), a lista de
arquivos que ficaram devendo (T4), o modo de busca, o tamanho da fonte e as
escolhas da janela principal (M1). E a perda e definitiva: nada avisa, e a
proxima gravacao escreve um arquivo novo sem nada daquilo.

A tolerancia para no BOM. Um arquivo que nao seja JSON, ou que nem seja texto,
continua degradando para vazio — o programa abre com os padroes em vez de nao
abrir.

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
2. Para cada arquivo, le os bytes **uma vez**, detecta a codificacao neles e
   decodifica sem traduzir fim de linha, para que o do original chegue intacto a
   geracao (ver 3.6).
3. Extrai cada comentario `{...}` e o **achata**: colapsa espacos em branco e
   normaliza o espaco depois de `.`, `!` e `?` — **exceto quando o ponto esta
   entre dois digitos**, que e notacao (`2.5`, `[%eval +0.35]`, `v1.2.3`) e nao
   fim de frase. O texto achatado e a chave de cache; a posicao (inicio, fim)
   no arquivo original e guardada.
4. Junto com cada comentario, extrai o **contexto de leitura**: a partida
   (contada pelas tags `Event`), o indice do comentario no arquivo e o numero do
   ultimo lance antes dele. E o que vai para a tabela `occurrences` (garantia
   O1).

**Garantia O1 — o banco registra onde cada comentario foi lido.** Arquivo,
partida, indice e numero do lance entram na tabela `occurrences`, uma linha por
posicao do arquivo, gravadas pelo worker depois dos lotes de cada PGN. E o que
da ordem de leitura da obra ao editor e progresso por livro as estatisticas.

O contexto e lido do movetext com **os comentarios apagados**: um comentario de
livro cita lances a vontade ("melhor era 14. Bxf7"), e sem apaga-los o lance
citado num comentario passaria a ser a posicao do seguinte. O numero de lance e
recortado pela partida — sem lance anterior dentro dela, o valor e nulo, e nao
zero. Nao contam como numero de lance: decimais (`+0.35`), linhas de tag
(`[Date "2011.??.??"]`) e o resto de linha de um comentario `;`.

**A extracao nao le PGN**: a partida sai da contagem de tags `Event` e o lance,
do ultimo numero de lance do texto. Um arquivo sem `[Event` conta como uma
partida so. Validar lance continua sendo nao-objetivo (secao 1); registrar onde o
comentario estava e outra coisa.

**Garantia D3 — cada PGN e lido uma vez por passada.** Os bytes sao lidos uma vez
e a codificacao e detectada **neles**, e nao numa leitura propria: eram quatro
leituras do arquivo por execucao (a deteccao lia inteiro, a extracao relia, a
geracao repetia as duas), duas delas decodificando tudo para validar a
codificacao (E4). O texto e a codificacao sao os mesmos que a forma antiga
produzia, incluindo o `\r\n` do original, e ha teste comparando as duas em UTF-8,
UTF-8 com BOM, cp1252 e UTF-16.

**Garantia D5 — o conteudo de um PGN nao atravessa a fase da API.** A execucao tem
duas passadas com papeis diferentes:

- a **primeira** le todos os arquivos e guarda so o que a adocao (P2) e a carga de
  cache precisam: os textos distintos de cada um, as contagens e os comentarios
  `;`. Nem posicao, nem contexto de leitura;
- na **vez de cada arquivo**, e depois dos lotes dele, ele e lido uma vez e
  extraido por inteiro. As posicoes e o contexto vao para a gravacao e para a
  tabela `occurrences`, e morrem com a iteracao.

Antes, o resultado completo da extracao de todos os PGN ficava guardado pela
execucao inteira. A fase da API dura minutos, e o conteudo do arquivo nao tem nada
a fazer nela: e a diferenca entre segurar um livro de 40 MB por minutos e nao
segurar. A segunda extracao reaproveita os objetos de texto da primeira, para que
ler duas vezes nao faca o texto viver duas vezes.

**Garantia X3 — o que o pipeline ignora e contado e anunciado.** O padrao PGN
tem uma segunda forma de comentario, `;` ate o fim da linha, que o programa nao
traduz. As linhas com `;` fora de `{...}` e fora das tags sao contadas, ditas
no log por arquivo e no resumo final — e um PGN anotado **so** com `;` recebe a
explicacao inteira em vez de um "nenhum comentario encontrado" que parece
defeito. As linhas do resumo so aparecem quando a contagem nao e zero.

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

**Garantia O2 — o contexto entra ao lado da traducao, e nunca e inventado.** A
chave de P1 nao ganhou coluna nenhuma: o mesmo comentario em doze livros continua
sendo uma linha, uma traducao e uma revisao, e a procedencia vive em
`occurrences`, N para 1. Se o arquivo fosse parte da identidade, cada livro
criaria a sua copia e a revisao passaria a ser feita doze vezes.

Do outro lado da mesma garantia: a migracao que cria a tabela **nao preenche
nada**. Onde um comentario ja gravado foi lido nao esta em lugar nenhum do banco —
nao ha de onde derivar —, e uma procedencia inventada apareceria no filtro por
arquivo como uma obra que ninguem traduziu. As linhas antigas ganham a primeira
ocorrencia quando o PGN delas for processado de novo, e ate la aparecem so em
"Todos os arquivos".

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
3. Senao, as anotacoes de maquina (`[%clk]`, `[%eval]`, `[%cal]`, `[%csl]`)
   sao **mascaradas** por sentinelas e o texto vai para a API. A resposta
   recebe as regras **automaticas** (`automatic`) e a correcao de lances (P3)
   ainda mascarada — anotacao escondida nao e reescrita por engano —, os
   sentinelas sao **restaurados e conferidos**, e so entao a traducao e gravada
   no cache.

**Garantia X1 — anotacoes `[%...]` atravessam a traducao byte a byte, ou o
comentario conta como falha.** A mascara e aplicada depois da limpeza (uma
regra de limpeza ainda pode remover uma anotacao inteira, se o usuario quiser)
e a restauracao e o ultimo passo antes de gravar. Os bytes voltam identicos por
construcao — o texto do span nunca sai da maquina —; o que se confere e que
cada sentinela voltou **exatamente uma vez**. Sumiu, duplicou ou apareceu um
que o comentario nunca teve (vazamento do vizinho de lote): o comentario e
tratado como falha (T2/T3) e fica no idioma original, em vez de gravado com
uma anotacao corrompida com cara de certa. A verificacao vale nos dois
caminhos, lote e individual.

O cache em memoria traz **apenas os comentarios dos arquivos desta execucao**, e
nao o idioma inteiro: sao os unicos pelos quais o worker pergunta. Acima de
metade da tabela a carga completa sai mais barata e e usada — o dicionario passa
a conter mais do que foi pedido, o que e indiferente para a consulta mas torna
`len(cache)` inutil como contagem do que veio destes arquivos.

**Garantia D4 — comentario repetido no proprio arquivo vai uma vez para a API.** O
cache so aprende a traducao depois da resposta, e o lote inteiro sai antes dela:
um capitulo com "Diagram" trinta vezes enviava as trinta. Os lotes de cada arquivo
sao montados sobre os textos **distintos** dele; entre arquivos quem serve e o
cache em memoria, que ja fazia esse papel. A geracao continua trocando todas as
ocorrencias (ela procura o texto, nao a posicao), e a tabela `occurrences` continua
recebendo uma linha por ocorrencia.

**A conta do resumo fecha, e antes nao fechava.** A segunda gravacao da mesma chave
volta "sem alteracao", que nao era contado em contador nenhum: cinco comentarios
processados apareciam como "2 novas" e mais nada. Hoje os repetidos tem linha
propria, no log e no resumo, e a barra de progresso conta sobre os distintos — com o
denominador antigo ela pararia antes do fim. As duas linhas so aparecem quando ha
repeticao, como a dos lances corrigidos e a dos comentarios `;`.

**Garantia T1 — nunca sobrescrever traducao existente.** A gravacao no cache
so insere linhas novas ou preenche traducoes vazias. Uma traducao ja
preenchida (possivelmente revisada por humano) jamais e substituida pelo
processo automatico.

"Automatico" e a palavra que delimita T1. Ha **um** caminho que sobrescreve, e ele
existe porque o padrao virava um beco: exportar o CSV, corrigir 300 traducoes na
planilha e importar nao fazia nada — as 300 voltavam como "Sem alteracao", e o
usuario descobria depois do trabalho feito. A importacao passou a oferecer o modo
"sobrescrever existentes", com tres condicoes que o separam do acidente:

- **e uma escolha explicita**, num dialogo de tres botoes (sobrescrever / importar
  sem sobrescrever / cancelar) que mostra quantas linhas do arquivo diferem do
  que esta gravado, e quantas dessas estao marcadas como verificadas;
- **passa pelas mesmas garantias de toda escrita em massa**: backup antes,
  historico com acao propria (R2) e reavaliacao do aviso de qualidade (R6);
- **rebaixa o `verified` da linha reescrita**, a nao ser que o CSV diga o
  contrario: a revisao era do texto anterior, e mante-la sobre um texto que
  ninguem leu e o que R9 e V1 existem para impedir.

T1 continua sendo o padrao, e continua valendo integralmente para o worker — ele
nunca chama esse caminho.

**Garantia T5 — nenhuma ferramenta de escrita em massa roda durante uma
traducao.** "Restaurar BD", "Importar CSV", "Aplicar Automaticas", "Corrigir
Lances", "Zerar Traducoes" e "Zerar Glossario" recusam com uma mensagem enquanto
o worker esta ativo. A pior era a restauracao: substituir o banco enquanto o
worker grava produz um arquivo que nao e nem o backup nem a execucao, com o cache
em memoria apontando para linhas que ja nao existem.

A guarda e a primeira linha de cada acao, e nao um botao desabilitado, porque os
botoes de "Ferramentas" sao criados anonimos — o clique acontece de todo jeito. E
por isso ela e uma MENSAGEM: um `return` mudo faz o clique nao fazer nada e nao
dizer nada, e quem clicou conclui que o programa travou. "Reprocessar Falhas" e
"Normalizar PGN" tinham exatamente esse `return`, e "Reprocessar Falhas" tambem
passou a ser desabilitado junto com o "Iniciar" — as duas comecam uma traducao, e
deixar so uma apagada dizia que a outra estava disponivel.

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

**As anotacoes `[%cal]`/`[%csl]` nao sao lances.** Os codigos de cor do Lichess
(`R`ed, `G`reen, `Y`ellow, `B`lue) vivem dentro do comentario e `Ra1h8` tem a
forma exata de um lance de Torre — sem exclusao explicita, a correcao reescrevia
a seta vermelha como `Ta1h8` (ROADMAP 13.1). Os spans `[%...]` ficam fora da
leitura **dos dois lados**: no original, um `[%cal Rd4d8]` viraria uma ancora
esperada falsa; na traducao, e o proprio texto que era reescrito. A exclusao
vale tambem para a ferramenta em massa (P4), que passa pelas mesmas funcoes — e
existe mesmo com a mascara de X1, porque a ferramenta opera sobre texto ja
gravado, onde a mascara nao passou.

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

O conteudo vem da extracao da vez do arquivo (D5), e o PGN de saida e escrito
**numa passada**: os trechos entre comentarios e as traducoes vao para o arquivo
em ordem crescente de posicao. Chaves `{` e `}` dentro de uma traducao viram
parenteses, para nao quebrar a estrutura do PGN.

Saida: `<nome>-<SUFIXO>.pgn` ao lado do original (`BR`, `EN`, `ES`, `FR`,
`DE`, `IT`, `RU`). Se o nome ja existir, sufixa `-2`, `-3`, ...

**Garantia D1 — a gravacao e uma passada, sem uma segunda copia do arquivo.** A
forma anterior refazia o arquivo inteiro a cada comentario
(`content[:start] + rep + content[end:]`, de tras para frente), e o custo crescia
com o **produto** do numero de comentarios pelo tamanho do arquivo: 15 mil
comentarios num PGN de 3,2 MB custavam 26,9 s, e um livro de 40 MB seriam centenas
de GB copiados. Os pedacos sao escritos direto no arquivo em vez de concatenados
antes, porque juntar produziria o PGN de saida inteiro na memoria ao lado do de
entrada.

Duas consequencias que valem dizer: os spans precisam estar em ordem e sem
sobreposicao (a montagem ordena, e um span sobreposto e ignorado com aviso no log),
e um comentario cujo span foi ignorado sai no idioma original — nunca corrompido.

**Garantia D2 — cancelar interrompe a gravacao.** O `cancel_flag` e conferido
durante a montagem, e um cancelamento devolve "nao gerado" **sem criar o arquivo**:
um PGN de saida pela metade e pior do que nenhum. A fase nao tinha checagem
nenhuma, e num acervo grande "Cancelar" ficava sem efeito visivel enquanto ela
rodava.

**Garantia G1 — o original nunca e modificado.**

**Garantia G2 — a saida preserva os acentos, tambem na leitura seguinte.** A
gravacao usa a codificacao detectada na origem **quando ela e Unicode**; quando
nao e — cp1252, latin-1 e afins —, a saida sai em UTF-8, e a troca aparece no
log. Se algum caractere nao couber na codificacao escolhida, cai para UTF-8 e
registra isso no log. Em nenhuma hipotese um caractere e substituido por
`U+FFFD` no arquivo gerado.

Herdar a codificacao de byte unico da origem gravava sem erro e quebrava no
leitor. Um PGN em ingles com dois nomes de jogador acentuados e detectado como
cp1252 (E3); a traducao para portugues enche o arquivo de acento; o cp1252
representa todos eles sem reclamar, entao o fallback do `UnicodeEncodeError`
nunca dispara; e quem le esperando UTF-8 — o ChessBase 26, por exemplo — trata
cada byte alto como UTF-8 invalido e o descarta. O resultado e letra que some,
e nao mojibake: `Dragao` no lugar de `Dragão`, `posio` no lugar de `posição`.
Medido no livro do Hansen: origem com 23 bytes altos, saida com 14.793.

UTF-16 e UTF-32 nao entram na promocao: carregam BOM, se anunciam ao leitor e
nao perdem caractere. A opcao `utf8_bom` continua valendo **depois** dela, de
modo que a saida promovida sai sem BOM por padrao e com BOM para quem le no
ChessBase antigo, que trata UTF-8 sem BOM como ANSI.

**Garantia X2 — comentario esvaziado pela limpeza sai do arquivo sem deixar
`{}`.** O span inteiro e removido, com um espaco vizinho junto — nunca uma
quebra de linha, que estrutura o resto do arquivo, e nunca o comeco de um span
colado (`{a}{b}`). Um comentario que **falhou** nao passa por aqui: ele nao
entra no mapa de traducoes e fica no idioma original (T3) — o unico vazio
possivel no mapa e o da limpeza.

**O fim de linha do original e preservado.** Leitura e gravacao usam
`newline=''`: um PGN CRLF sai CRLF, um LF sai LF, byte a byte fora dos spans
traduzidos. Antes, a saida trocava o fim de linha pelo da plataforma e um
acervo comparado por hash mudava inteiro.

**UTF-8 com BOM e opcao, desligada por padrao** (`output.utf8_bom` no
`pgn_tradutor_pro_settings.json`). Existe pelo consumidor: um PGN ASCII cuja
traducao introduz acentos sai UTF-8, e sem BOM o ChessBase do Windows le ANSI
e exibe mojibake. So afeta saidas UTF-8; um BOM nao significa nada em cp1252.

**Garantia F9 — a requebra muda so espaco em branco.** `output.wrap_columns`
requebra os comentarios do arquivo gerado (80 e o export format do padrao PGN, o
que editora espera); zero, o padrao, mantem o comentario em linha unica como
sempre. As palavras saem na mesma ordem e com os mesmos caracteres — um espaco
entre duas delas vira uma quebra de linha, e nada mais. E o que permite requebrar
sem tocar na chave de cache, que continua sendo o texto achatado.

Quatro recortes, e cada um evita um estrago:

- a **primeira linha** sabe que comeca no meio: depois de `12. Nf3 {` sobra menos
  espaco. A coluna e medida no texto original — quando dois comentarios dividem a
  linha, o primeiro pode encolher e a coluna do segundo muda com ele, e o erro
  desloca uma quebra de linha, nunca texto;
- um **`[%...]` conta como uma palavra** e nunca e partido. X1 gastou uma secao
  protegendo esses spans; quebra-los na gravacao seria desfaze-lo no ultimo passo;
- a quebra inserida e a **do arquivo** (`\r\n` num arquivo CRLF), senao a requebra
  entregaria um PGN de fim de linha misturado — pior que o sem requebra;
- uma **palavra maior que a linha** fica inteira e estoura a coluna: cortar no meio
  dela produziria um token que nao existe.

Larguras invalidas caem no padrao: `true` (que em Python e `1`), qualquer valor
abaixo de 20 colunas e qualquer tipo que nao seja inteiro. Uma palavra por linha
nao e um PGN requebrado.

### 3.7 Controle de execucao

Roda em thread separada, com pausa e cancelamento cooperativos. Toda
atualizacao de interface e agendada na thread principal do Tk.

**Garantia C1 — Tk so na main thread.** Nenhum widget e tocado fora da thread
principal; o log usa fila + polling.

**Garantia C2 — cancelamento preserva o trabalho feito.** Ao cancelar, o que
ja foi traduzido esta gravado no banco.

O `cancel_flag` e conferido em sete pontos: entre arquivos, entre lotes, entre
comentarios de um lote, entre requisicoes do caminho individual, **durante a
gravacao do PGN** (D2) e — desde 22.13 — **antes de cada tentativa e antes de
cada espera do retry** (C4). O da gravacao nao grava arquivo nenhum quando
dispara: meio PGN traduzido em disco seria pior do que nenhum.

**Garantia C4 — "Cancelar" alcanca o laco de tentativas.** `translate_text_chunk`
nem recebia o flag: o laco de tres tentativas dormia em `time.sleep` sem olhar
cancelamento, e a conferencia entre chunks nao cobre nada num comentario de um
chunk so — que e a maioria. Com o timeout de 30 s por tentativa, o clique ficava
ate ~93 s sem efeito contra um endpoint que pendura a conexao, que e o cenario em
que mais se clica Cancelar.

Os dois pontos sao necessarios: sem o de antes da tentativa, cancelar durante a
espera ainda dispara a requisicao seguinte; sem o de antes da espera, espera-se
1,5 s para depois desistir. **A requisicao EM VOO continua inevitavel** — quem a
interromperia e o timeout do `requests`. Cancelado devolve `None`, que os
chamadores ja tratam: para eles, cancelado e falha sao o mesmo caminho.

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
`apagar`; ate entao o botao de apagar fica inerte **e parece inerte**. As demais
confirmacoes do programa sao `Sim/Nao` e bastam para o que e reversivel; aqui um
"Sim" fica a um pixel do "Nao", e o que se perde sao 201 mil traducoes ou 7 mil
regras. Aceita-se qualquer caixa e espaco nas pontas: quem digitou `APAGAR `
decidiu tanto quanto quem digitou `apagar`.

A palavra era `delete` ate 2026-08-01 (ROADMAP 22.12), num dialogo todo em
portugues cujo botao se chama "Apagar" — e digitar "apagar", a leitura mais
natural do que esta na tela, era **recusado sem explicacao**. Uma barreira que
existe para transformar clique em decisao nao pode falhar por vocabulario.
`delete` continua sendo aceito por uma versao, porque quem usa o programa ha
meses tem a palavra antiga na memoria dos dedos; a tolerancia vale so quando o
dialogo esta pedindo a palavra padrao.

Fechar a janela, apertar `Esc` ou clicar em "Cancelar" e **nao**. Nao ha caminho
em que sumir com o dialogo signifique seguir adiante, e o proprio comando do
botao reconfere a palavra em vez de confiar no estado dele.

**Garantia Z3 — uma zera, a outra nao e afetada.** Zerar as traducoes nao toca
no glossario e vice-versa. Zerar as traducoes leva junto o historico de edicoes
(historico de traducoes que nao existem mais nao e historico de nada), esvazia o
indice de busca, libera o espaco em disco (`VACUUM`) e limpa o cache em memoria —
que tem precedencia sobre o banco e, deixado como estava, faria a proxima
traducao reaproveitar exatamente o que acabou de ser apagado.

**Garantia O4 — zerar leva as ocorrencias junto.** Elas apontam para linhas de
`comments` por id, e o `AUTOINCREMENT` reinicia com a tabela: uma ocorrencia
sobrevivente passaria a apontar para a PRIMEIRA traducao gravada depois do
zeramento — o comentario errado, no arquivo certo, sem nada acusando na tela. A
tabela e derrubada com as outras e recriada vazia pela migracao.

Nenhuma das duas roda com uma traducao em andamento — e nenhuma das outras
ferramentas de escrita em massa tambem (garantia T5, secao 3.4).

---

## 5. Glossario

### 5.1 Formato

`Substituicoes.txt` contem uma atribuicao Python com uma lista de tuplas, lida
com `ast.literal_eval` (nunca `exec`). Cada regra tem de dois a cinco campos —
`(original, substituicao, tipo, prioridade, escopo)` — e **cada campo so e
escrito quando tem algo a dizer**:

```python
escopo = 'pt'                               # padrao do arquivo (opcional)

substituicoes = [
    ('rook', 'torre'),                      # suggestion, prioridade 0, escopo 'pt'
    ('Queen', 'Dama'),
    ('== EndSquare ==', '', 'cleanup'),     # outro tipo
    ('torre', 'castle', 'suggestion', 1),   # com prioridade
    ('×', 'x', 'automatic', 0, '*'),        # excecao: vale para todo par
    ('@casa@-torre', 'torre de @casa@'),    # vale pelas 64 casas
]
```

**O escopo e declarado uma vez para o arquivo, e por regra apenas para
discordar.** A ausencia do quinto campo significa "herda o padrao"; num arquivo
sem a declaracao, herdar e "vale para todo par", e por isso um
`Substituicoes.txt` de antes desta versao continua valendo sem uma linha
alterada. O `'*'` e como se escreve a excecao global quando existe um padrao.

A razao e a mesma que faz tipo e prioridade serem omitidos: o arquivo tem
milhares de linhas e e versionado. Escrever `, 'pt'` nas 5.900 regras
portuguesas do acervo seria um diff do arquivo inteiro para registrar uma
decisao unica — a migracao real custou 23 insercoes e 19 remocoes.

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

**Garantia S13 — tipo de regra desconhecido avisa em vez de degradar em
silencio.** A degradacao para `suggestion` continua (e o que S5 manda), mas a
carga do arquivo publica um aviso pelo handler do glossario, nomeando os valores
que nao foram entendidos. Um `('x', 'y', 'automático')` deixava de rodar depois
da API e nada dizia por que. O aviso e **um** por carga, com ate cinco valores
distintos: um arquivo com cem tipos tortos precisa de um aviso, nao de cem
dialogos. Ele mora na leitura do texto, e nao do `glossario.db` — o banco guarda
tipos ja normalizados, onde a grafia errada nao existe mais.

**Um padrao pode conter `@casa@`**, que na carga vale pelas 64 casas do
tabuleiro: `('@casa@-torre', 'torre de @casa@')` e uma linha no arquivo e 64
regras na aplicacao. As regras expandidas sao **literais**, exatamente as que
seriam escritas a mao — a expansao nao introduz expressao regular nenhuma. Quem
manda e o padrao: sem `@casa@` nele, a regra sai intacta mesmo que a substituicao
tenha um. O editor de glossario mostra e edita **uma** linha, com o placeholder.

O CSV de importacao/exportacao tem as mesmas quatro colunas (`original`,
`replacement`, `type`, `priority`), e a leitura aceita a ausencia das duas
ultimas — um CSV de tres colunas, ou montado numa planilha, continua importavel.

**Garantia S14 — exportar e reimportar o glossario preserva as regras de
delecao.** Substituicao vazia e invalida em toda regra menos na de `cleanup`,
onde ela e o proprio ponto (apagar lixo de conversao). A validacao do editor e a
da importacao de CSV usam o **mesmo** criterio; enquanto discordavam, um
round-trip pelo CSV descartava em silencio as 50 regras de delecao do glossario.

**Garantia S11 — regra com escopo de idioma so e aplicada no seu par.** O escopo
nomeia o idioma de **DESTINO** (`'pt'`), ou o par inteiro quando o erro e daquela
traducao especifica (`'en>pt'`). Sem escopo, vale para todo par — o
comportamento que o programa sempre teve.

E o destino sem excecao por tipo, e isso e uma decisao e nao um descuido. A
leitura tentadora seria "o idioma do texto que a regra le", que para uma regra de
`cleanup` e a ORIGEM (ela le o comentario original): com ela, um arquivo que
declara `escopo = 'pt'` desligaria em silencio todas as regras de limpeza numa
execucao en -> pt. O preco da escolha simples esta declarado na secao 10.

Um escopo que exige idioma de origem **nao casa uma execucao em "Detectar"**: sem
a declaracao nao ha como afirmar que o original esta em ingles, e aplicar seria um
palpite. E a mesma razao pela qual a correcao de lances (P3) nao roda ali.

Duas regras com escopos que **nunca se cruzam nao conflitam** (S9/S12): uma para
`'pt'` e outra para `'it'` sao carregadas em execucoes diferentes, e acusa-las de
disputa seria descrever uma briga que nao acontece. Escopo vazio cruza com todos.

**Garantia S16 — o dialogo de zerar conta o que apaga.** Ele contava
`len(app.glossary_substitutions)`, que e a lista APLICAVEL — outra coisa por tres
razoes somadas: ela expande `@casa@` (uma linha do arquivo vira 64 regras), soma
as da semente (que zerar nao apaga, porque a semente vem com o programa) e exclui
as de limpeza (que zerar apaga). Medido no glossario real: 5.910 entradas no
arquivo, 7.325 anunciadas. A contagem sai de `load_glossary_entry_details(deduplicate=False)`, que e a mesma fonte do
"Total" do editor de glossario, e o dialogo diz o numero por tipo.

**Depois de zerar, a sessao fica com as regras de fabrica** — nao com nenhuma. O
codigo esvaziava a lista em memoria, e a proxima abertura recarregava a semente
(S15): na pratica o programa "recuperava" sozinho, no dia seguinte, um glossario
que o usuario acabou de zerar. Recarregar do disco na hora e o que faz a tela
dizer a verdade, e a mensagem final diz quantas continuam valendo.

**Garantia S17 — o "Teste rápido" usa a conversao do pipeline.** Ele trabalhava
com os pares crus e divergia da aplicacao em quatro pontos: prioridade descartada
(com uma regra promovida por "Priorizar esta", a previa dava um resultado e o
pipeline outro — contradizendo o banner de conflito exibido ao lado, S9), escopo
ignorado, `@casa@` inerte e apenas a PRIMEIRA ocorrencia trocada. As regras da
previa saem de `interactive_rules_from_entries`, a MESMA funcao que
`load_interactive_substitutions` usa: e a licao de S9 escrita noutro lugar — o
anuncio nao IMITA o criterio da aplicacao, ele USA o criterio.

O escopo e avaliado com o par escolhido na janela principal, que e onde o par de
uma traducao e escolhido. A semente fica de fora de proposito: a previa responde
"o que as MINHAS regras fazem com este texto", e explicar um resultado por uma
regra que nao esta em lugar nenhum da tela seria pior do que a omissao.

**Garantia S18 — o editor de glossario anda pelo teclado.** `Ctrl+L` para o campo
de busca, `Alt+←/→` pela lista FILTRADA e `Ctrl+PageUp/PageDown` para virar
pagina. Pela lista filtrada, e nao pela do arquivo: com "Duplicadas" ativo, `+1`
sobre o indice do arquivo pousaria numa regra que a tela nao mostra — o erro que
R10 nomeou no outro editor. Nas bordas ele para, em vez de dar a volta: dar a
volta faria `Alt+→` no fim da lista parecer que nada aconteceu.

**Garantia S15 — o dicionario-semente nunca sobrepoe uma regra do usuario.** O
programa vem com terminologia enxadristica propria
(`tradutor_pgn/Substituicoes-semente.txt`, 232 regras, ingles -> destino,
escopadas, todas `suggestion`), carregada junto com o glossario do usuario. Uma
regra da semente e **descartada** quando ele tem uma com o mesmo padrao no mesmo
escopo — ou sem escopo nenhum, que e uma decisao mais ampla ainda. A comparacao e
por `casefold`, pela licao de S12. As que sobram entram depois das dele, entao a
ordem do arquivo continua dando a ele a palavra final.

Os dois arquivos **nao se misturam no disco**: o do usuario sai de `sys.argv[0]`
(ao lado do executavel, onde ele edita), a semente sai de `__file__` (dentro do
pacote). Atualizar o programa troca a semente e nao toca no trabalho de quem usa.
Um defeito na semente degrada para "sem semente" e **avisa** — ela vem com o
programa, entao o defeito e nosso.

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

**Garantia D7 — a ordem das regras e identificada por versao.** A ordenacao por
especificidade e memorizada, porque as mesmas regras entram nela muitas vezes
seguidas: o editor de traducoes reordena o glossario a cada tecla digitada. A
chave dessa memoria era a **tupla do conteudo** — uma entrada por regra, montada e
hasheada em cada consulta —, o que custava 1,75 ms dos 9,15 ms de uma tecla com o
glossario real (7.334 regras).

Cada lista carregada traz um numero de versao, e a chave passou a ser ele. O
`id()` da lista nao serviria (uma lista nova reaproveita o endereco de uma
coletada), e a versao cobre tambem o caso que a chave por conteudo cobria de
graca: **mutar a lista renova a versao**. Sem isso, uma lista alterada no lugar
receberia a ordem antiga, com regras que nao estao mais nela. Uma lista comum —
escrita a mao, ou de teste — continua sendo identificada pelo conteudo.

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
regras que casam o mesmo texto com substituicoes diferentes nao empatam. S3
ordena por comprimento do padrao; padroes identicos empatam sempre, entao o que
decide e a prioridade (S10) e, sem ela, a ordem do arquivo — vence quem foi
digitado primeiro, e o congelamento de S4 impede a outra de rever o trecho. O
editor mostra, na regra selecionada, qual delas o programa aplica, e oferece duas
saidas: "Priorizar esta", que a poe na frente sem apagar nada, e "Manter esta",
que remove as concorrentes do arquivo.

**Garantia S12 — conflito por diferenca de caixa e anunciado como o exato, e so
quando a vencedora produz outra coisa.** "O mesmo texto" e mais largo do que "o
mesmo padrao": uma regra escrita **toda em minusculas** casa sem diferenciar
caixa, entao ela engole a variante capitalizada que venha depois — `('black',
'pretas')` mata `('Black', 'as pretas')`, e o agrupamento por padrao exato nao
via isso. Medido no glossario real: 210 regras nunca disparavam.

A relacao **nao e simetrica**. Com a de caixa fixa na frente as duas vivem, cada
uma no seu texto; o que mata e a insensivel chegar antes.

E uma regra sombreada so e conflito **quando perde algo**. A substituicao propaga
a capitalizacao do texto encontrado, entao `('as pretas deve', 'as pretas
devem')` aplicada a `"As pretas deve"` ja produz `"As pretas devem"` — o que a
regra capitalizada ao lado dela queria. Ela esta morta e nada se perde: e
redundancia, e a redundancia tem aviso proprio. O criterio e o que a vencedora
**produz** naquele padrao, avaliado pela mesma funcao que a aplicacao usa; das
210 mortas, 166 sao redundancia e 44 eram conflito de verdade.

O que "Manter esta" remove inclui a duplicata exata do grupo, mesmo ela nao sendo
conflito: deixada la, ela continuaria engolindo a regra escolhida, e o clique nao
honraria o nome.

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

**Garantia R10 — o filtro de origem vale para navegar tambem.** "Ir para ID" e
"Proximo aviso QA" (F7) consultam o banco com o mesmo filtro que a lista, porque
os dois trabalham com POSICOES: o offset de uma linha e a posicao dela na lista
filtrada, e o limite da varredura de F7 e o total filtrado. Sem o filtro na
consulta, digitar um ID de outra origem selecionava uma linha arbitraria — e F7
anunciava o aviso de uma linha que nao esta na tela. Nos dois casos, sem
mensagem. E a mesma classe do bug que R7 fechou: navegar pela posicao errada.

A barra de status nomeia o par da **linha carregada**, que com "Origem: Todos" nao
e o mesmo que o filtro — e e justamente ai que a informacao importa, porque e o
unico momento em que a lista mistura idiomas de origem de proposito.

Trocar qualquer um dos dois grava a edicao aberta antes (a linha pertence ao par
antigo e sai da lista na troca) e volta para a primeira pagina — a pagina 40 do
par anterior nao quer dizer nada no novo. Com um filtro de origem ativo,
"Aplicar automaticas" fica restrito a ele: reescrever tambem as linhas das outras
linguas seria uma alteracao em massa que o usuario nao pediu nem consegue ver.

**Garantia O3 — com um arquivo escolhido, a lista e a obra em ordem de
leitura.** Um terceiro seletor, "Arquivo", lista as obras do par (as que tem
ocorrencia gravada) mais "Todos os arquivos". Escolher uma filtra a lista e a
ordena pela posicao do comentario NAQUELE arquivo; "Todos os arquivos" volta a
ordem de `id`, que e a ordem de insercao no cache.

Cada comentario aparece **uma vez**, ordenado pela primeira posicao em que o
leitor o encontra: um livro repete o mesmo comentario ("Diagram") dezenas de
vezes, e a identidade da lista e o comentario, nao a posicao.

Nao existe um seletor de ordem, e a ausencia e a decisao: escolher um arquivo E
pedir a obra em ordem de leitura. Sem arquivo, a ordem de leitura nao existe — o
mesmo comentario esta em varios — e ordenar pela primeira ocorrencia de cada um
custaria uma agregacao da tabela inteira por pagina, o que R5 proibe. O rotulo da
pagina diz "· ordem de leitura" quando ela esta ativa.

R10 vale para o arquivo como vale para a origem, e com um agravante proprio:
**"quantas linhas vem antes deste id" deixa de ser "quantas tem id menor"** no
momento em que a lista se ordena por ocorrencia. O offset do "Ir para ID" e a
varredura do F7 usam o mesmo criterio do `ORDER BY`; um id fora do arquivo
recebe "nao encontrado nos filtros atuais", como fora da origem.

O rodape do original diz onde ele foi lido — arquivo, partida, lance e indice do
comentario —, com preferencia pelo arquivo aberto: quem le o capitulo 7 nao pode
ver no rodape a posicao do mesmo comentario no capitulo 1, que e verdade e
responde outra pergunta. Quando a traducao serve a varias posicoes, o rodape diz
quantas — editar ali muda todas elas, e e isso que o numero avisa. Uma linha sem
ocorrencia (as gravadas antes desta versao, e as importadas por CSV) deixa o
rodape vazio.

A escolha e lembrada entre sessoes **pelo caminho do arquivo**, e nao pelo rotulo
do menu: o rotulo ganha a pasta quando dois nomes coincidem, entao ele pode
significar outro arquivo amanha. Um arquivo lembrado que nao esta mais na lista
cai em "Todos os arquivos".

### 6.1 O fluxo de quem trabalha o dia inteiro nisso

**Garantia F1 — trocar a orientacao dos dois textos nao perde a edicao.** Original
e traducao vivem num divisor proprio, e um botao alterna entre empilhado (o padrao,
como sempre foi) e lado a lado. A troca e `configure(orient=...)`, e nao a
reconstrucao dos paineis: o texto digitado, a pilha de desfazer, a selecao e as
marcas de busca vivem DENTRO dos widgets de texto, e recria-los perderia os quatro
no meio de uma edicao nao salva.

A orientacao e lembrada, e a posicao do divisor e lembrada **por orientacao**: o
divisor horizontal mede largura e o vertical mede altura, e reaproveitar o numero
de um no outro poria o divisor num lugar sem relacao com o escolhido.

**Garantia F2 — a linha da lista diz status, aviso e origem.** A primeira linha do
rotulo carrega o que decide se vale abrir a linha: o status, o id, o marcador de
aviso QA e o idioma de origem. O marcador sai da COLUNA `quality_warning`, que e a
mesma que o filtro "Avisos QA" le — reavaliar o texto no rotulo daria uma tela em
que a linha nao esta marcada e o filtro a mostra (R6). Uma linha que nao traz a
coluna nao ganha marcador, em vez de ganhar "sem aviso".

**`Ctrl+F` busca no TEXTO aberto e `Ctrl+L` na lista.** Era o contrario, e o gesto
universal caia no campo que TROCA a pagina — quem procurava uma palavra no
comentario perdia o lugar em que estava.

**Garantia F3 — "voltar" restaura a linha e os filtros.** `Alt+Backspace` (ou o
botao "< Voltar") desfaz o ultimo SALTO: buscar, limpar a busca, ir para um id ou
uma pagina, trocar de filtro, de arquivo ou de par, e o F7. Navegar para a linha
vizinha nao empilha nada — um "voltar" que andasse linha por linha nao devolveria
nada a quem revisa um livro.

O que a pilha guarda e um **retrato** (linha aberta, busca, modo de busca, status,
origem, destino, arquivo e pagina), e nao um id: usar a busca como concordancia
troca a lista, e voltar para um id que a busca nova nao contem nao e voltar. A
pilha guarda 50 retratos, e um retrato que nao da para repor — a linha foi apagada
por outra janela — nao a trava: o proximo assume.

**Garantia F13 — o retrato e o da consulta que estava em vigor.** Os filtros do
retrato saem do que a ultima consulta da lista USOU, e nao dos seletores: o
comando de um seletor roda com o widget ja no valor novo, entao ler o widget
gravava para onde o usuario estava indo. Media na janela real, o retrato de quem
trocava "Todas" por "Verificadas" guardava "Verificadas" — e "voltar" nao repunha
filtro nenhum. Vale para os seis campos; a busca era o unico certo, por nao vir de
um widget.

Disso saem tres regras que o codigo segue:

- **o destino sai de `self.lang`**, e nao do menu, porque `lang` so muda quando a
  troca de par entra em vigor;
- **o retrato e tirado antes do `save_changes`** nos caminhos que trocam um
  seletor, porque a gravacao pode recarregar a lista sozinha (filtro "Avisos QA" +
  aviso corrigido) e esse recarregamento ja usaria o filtro de destino;
- **repor o par repoe tambem o recorte do glossario** (S11) e o titulo, e nao so o
  seletor — senao a lista volta para o par certo com as sugestoes do par que se
  deixou.

Quando NENHUM retrato da pilha pode ser reposto, a janela volta para onde estava:
repor mexe nos seletores antes de saber se a linha existe, e sem isso "Nada para
voltar" deixava a tela com os filtros do ultimo retrato que falhou.

**Garantia F7 — a selecao em lote e por id.** Uma marca por linha; "Verificar" e
"Exportar" valem para o que esta marcado, e a selecao sobrevive a trocar de pagina
(juntar 30 linhas de tres paginas e o caso real de quem prepara uma entrega). Ela
morre na troca de par, porque um id do par anterior nao esta na lista nova.

Ela **sobrevive** as trocas de arquivo, de status e de busca, e essa e uma decisao
tomada em 22.11 e nao um descuido: dali da para voltar, os ids continuam validos, e
juntar linhas de tres capitulos e o que a barra existe para servir. O que a
sobrevivencia custa esta pago na confirmacao, que diz quantas das marcadas estao
FORA dos filtros atuais (F21) — a mesma preocupacao que mata a selecao na troca de
par, respondida com informacao em vez de com perda de trabalho.

"Marcar tudo" marca o filtro INTEIRO, e nao a pagina, e pergunta quando passa de
uma pagina: com 100 linhas o revisor ve o que marcou, com 3.000 ele so ve o
contador. O numero aparece na pergunta porque nao cabe no rotulo do botao (F20).

Verificar em lote passa pelo mesmo caminho de uma linha so, entao cada linha ganha
carimbo e historico (R2), e **nao propaga para traducoes iguais**: a propagacao tem
confirmacao propria (V1) porque marca originais que ninguem leu, e encadea-la aqui
abriria uma confirmacao por linha marcada — ou nenhuma. A confirmacao do lote diz
isso em palavras.

**Garantia F11 — a previa de "Aplicar todas" marca o que muda.** As faixas trocadas
sao pintadas nos dois lados e a previa diz quantos trechos mudaram. O diff e
calculado entre os dois textos PRONTOS, e nao acumulado regra a regra: a segunda
substituicao desloca as faixas da primeira, e a previa mostra o texto depois de
todas. E por palavra, e nao por caractere — `torre` -> `Torre` como um `T` trocado
no meio de uma palavra pintada de igual nao e o que o revisor precisa ver.

**Garantia F10 — `verified` e `review_status` andam em lockstep.** Uma linha nao
verificada pode estar **rejeitada** ou **em duvida**, com uma nota do revisor:
"pendente/verificada" nao expressa "voltar aqui com o autor". `verified` continua
sendo a autoridade sobre verificada/pendente, e o campo novo so refina o lado
pendente — guardar "verified" nos dois daria duas fontes para a mesma verdade.

A regra e uma frase: **verificar limpa o status, e um status alem de pendente
derruba o verificado.** Rejeitar uma linha verificada e dizer que a verificacao
estava errada; deixar o bit de pe a manteria fora do filtro de pendentes e ela
nunca voltaria para a fila de ninguem. Sao **quatro** os caminhos que escrevem
`verified` — marcar, salvar-e-verificar, a propagacao e a sobrescrita pelo CSV —, e
a frase vale nos quatro.

Os dois status novos sao filtros da lista e aparecem no rodape **so quando
existem**. Eles sao recortes das pendentes, e nao categorias ao lado delas: somar os
tres daria um total maior que a tabela.

**Garantia F5 — as estatisticas saem do clique.** "Estatisticas do BD" abre uma
janela propria, copiavel e salvavel em `.txt`, com o conteudo computado numa thread
de trabalho e com progresso cancelavel. Era a ultima operacao pesada dentro do
callback de um botao (C1), e o resultado era um `messagebox` que nao rola, nao se
seleciona e nao se copia — sendo justamente o numero que vai para um orcamento.

A janela e modeless: o proposito dela e ser consultada enquanto se trabalha. O
texto e selecionavel e nao editavel — `state="disabled"` no Tk impediria tambem a
selecao, e um relatorio que nao se copia e o defeito que ela veio corrigir.

**Garantia F4 — "palavra" e a mesma unidade em todo o programa.** Palavra e
sequencia separada por espaco em branco, a mesma definicao do `wc -w`, do Word e do
OmegaT — a que o cliente usa para pagar. `14.Bxf7` conta como uma. A contagem
aparece no acervo inteiro e por par, com o original e a traducao separados: o
tradutor orca pelo original (e o que o cliente manda) e mede o trabalho feito pela
traducao.

A contagem e feita em Python, e nao em SQL: contar espacos acerta o original — ele
e achatado — e erra a traducao, que passou pela mao do revisor e pode ter quebra de
linha e espaco duplo.

**A produtividade por dia sai do `comment_history`**: cada edicao conta uma, com as
palavras da traducao NOVA. A mesma linha editada tres vezes conta tres, porque sao
tres passagens de revisao — o numero e de atividade, e nao de acervo. Diferenca em
relacao ao texto anterior seria negativa quando o revisor encurta, e "produzi -40
palavras hoje" nao e uma metrica de trabalho.

**Garantia F8 — o rascunho grava fora da thread da interface.** A pausa que dispara
a gravacao subiu de 700 ms para 2,5 s e o disco saiu da thread do Tk: cada gravacao
rele o JSON inteiro, serializa tudo e troca o arquivo de nome, o que em disco lento
ou com antivirus e o programa parando entre duas teclas.

O que roda na thread e so o disco; os valores sao capturados antes e o rotulo e
escrito de volta por `after` (C1). E `update_settings` passou a serializar o ciclo
ler-alterar-gravar sob um lock: com duas threads gravando, a segunda lia o disco
antes de a primeira gravar e o que a primeira escreveu desaparecia — a perda que R4
existe para impedir, agora por corrida.

**Garantia F6 — o acervo sai em TMX 1.4.** "Exportar TMX" escreve o banco como
memoria de traducao: um `<tu>` por linha, o `id` como `tuid`, os dois idiomas nos
`<tuv>`. Abre em OmegaT, Trados e memoQ. Sem isso, 200 mil pares revisados ficavam
presos num formato que so este programa le.

Tres decisoes do arquivo:

- **`srclang="*all*"`** — o acervo tem varios idiomas de origem ao mesmo tempo, e
  esse e o valor que o padrao define para isso. Declarar um so faria toda
  ferramenta importar o acervo inteiro como se fosse dele;
- **origem nao declarada vira `und`** (ISO 639-2, "indeterminado"). `xml:lang=""`
  nao e valido, inventar `en` seria mentir, e pular essas linhas deixaria de fora a
  maioria de um banco anterior a 9.2;
- **linha sem traducao fica fora.** Uma memoria com o lado de destino vazio nao
  ajuda ferramenta nenhuma e polui a concordancia de quem a importar.

O texto e escapado e os controles C0 sao removidos — o XML 1.0 nao os aceita nem
escapados, e um deles produz um arquivo que nao abre. Um TMX interrompido no meio e
apagado, como o CSV: sem `</body>` ele nao abre em lugar nenhum.

**O `id` passou a ser a primeira coluna do CSV de traducoes**, com o status de
revisao e a nota no fim. E a unica coluna que identifica a linha sem depender do
texto, e e o que torna o round-trip pela planilha conferivel.

**Garantia F19 — o que a tela diz, ela diz de forma legivel.** Duas partes, e as
duas eram sobre informacao que so existia como cor.

As **quatro cores semanticas** dos rotulos — verde, ambar, vermelho e cinza —
sao pares `(claro, escuro)` e passam o minimo de 4,5:1 da WCAG nos dois temas.
Cada uma era um hex unico para os dois fundos, e um hex so nao serve a dois
fundos: as quatro reprovavam em pelo menos um tema, e o ambar dos avisos dava
1,55:1 no claro — o pior par da janela, e justamente o texto que avisa que algo
esta errado. Elas vivem num lugar so; as quatro janelas que dao recado importam
de la.

Os dois destaques com texto branco foram por caminhos diferentes, e a diferenca e
a regra: **na linha selecionada muda o FUNDO** (o branco e o texto de todas as
linhas da lista), e **na ocorrencia atual da busca muda o TEXTO** (o fundo
laranja e o que a distingue das outras ocorrencias, e escurece-lo apagaria essa
distincao).

O **status de revisao da linha aberta aparece em palavras** — "Rejeitada" / "Em
dúvida" ao lado do campo de nota —, e nao so como a cor de uma borda: para um
protanope as duas cores viram tons de oliva com 2,8:1 entre si, e a mensagem de
confirmacao some em segundos. A linha pendente nao ganha rotulo: o padrao nao
precisa de nome, e escreve-lo em toda linha faria o normal virar ruido.

**Garantia F18 — o que a janela sabe fazer aparece na janela.** Quatro coisas
eram invisiveis, e a correcao de cada uma tem uma regra propria:

- **Os atalhos tem uma lista**, aberta por `F1` ou pelo botao "?" do
  rodape — os dois, porque um atalho para descobrir atalhos so serve a quem ja
  os descobriu. Eram treze quando a garantia nasceu; sao vinte desde 22.11. A
  lista e uma tabela com a sequencia do Tk ao lado do rotulo, e dois testes a
  comparam com os binds reais **nos dois sentidos**: um atalho ligado e nao
  listado falha tanto quanto um listado e nao ligado. E o que impede a lista de
  virar documentacao errada. O `Ctrl+B` era o unico recurso do programa sem
  caminho de descoberta nenhum: nao tem botao (o "B" da barra faz outra coisa) e
  nao estava no README.
- **Os gestos de MOUSE tem tabela propria** (`MOUSE_GESTURES`), na mesma janela.
  A separacao e o que mantem a conferencia acima possivel: o lado "todo bind
  aparece na lista" so consegue distinguir atalho de evento de ciclo de vida
  porque o Tk poe `Key` em toda sequencia de tecla, e um `<Double-Button-1>` na
  mesma tupla ficaria listado e nunca verificado.
- **O foco do teclado pinta a borda** dos dois campos de texto. Quem recebe o
  foco e o `tk.Text` e quem desenha a borda e o quadro em volta dele. Os campos
  de uma linha ficaram de fora: a borda deles ja diz o status de revisao (F10), e
  dois significados na mesma borda apagam um ao outro.
- **O estado ligado do botao "B" difere do desligado nos DOIS temas**, e por
  duas vias — cor de outra familia e borda. O par anterior era a mesma cor no
  tema escuro, byte a byte: clicar nao mudava nada na tela. O desligado e lido
  do tema, e nao de hexes copiados.
- **Trocar o tema do sistema com a janela aberta repinta o Tk puro.** Os widgets
  do CustomTkinter recebem pares e se viram sozinhos; os `PanedWindow`, os dois
  textos e as tags deles recebem uma cor so, e ficavam com a do tema anterior.
  O gancho e o registrador da propria biblioteca, protegido por `try/except`:
  sem ele o comportamento e o de antes, e a janela abre do mesmo jeito.

**Garantia F20 — o rotulo carrega o objeto, e a faixa cabe.** Duas familias que
sao a mesma coisa vista de dois lados: a janela afirmando o que nao entrega.

Tres botoes escritos "Limpar" faziam tres coisas diferentes (a busca, a selecao
em lote e o status de revisao, que GRAVA no banco), e "Página" era quatro. Hoje
sao "Limpar busca", "Desmarcar", "Limpar status" e "Marcar página". Sobra uma
repeticao, deliberada: os dois "Ir" da barra de salto, cujo objeto esta no rotulo
do campo colado a eles.

**A largura minima da janela e a SOMA dos minimos dos paineis** — 320 da lista,
520 do editor, 308 das sugestoes, dois divisores de 8 e 20 de `padx` — e nao um
numero declarado a parte: hoje sao 1184. Eram 1120 contra 1176 de soma (com as
sugestoes ainda declarando 300), e a diferenca saia sempre do mesmo painel:
**medido na janela real, o de sugestoes ficava com 109 px dos 300 que
declarava**, com os seis botoes mostrando 40 dos 140 de que precisam — e os 300
tambem estavam curtos, porque as duas colunas de botoes com os `padx` pedem 308.

Tres regras saem disso, e valem para qualquer janela nova:

- **O `minsize` de um painel tem de ser o que o CONTEUDO dele precisa.** O painel
  de baixo declarava 620 e continha 836 (editor + divisor + sugestoes), e a
  diferenca saia do ultimo painel. O Tk honra o `minsize` dos vizinhos tambem ao
  POSICIONAR um divisor, e nao so ao arrasta-lo: com a soma certa declarada,
  quem recua e a lista e nenhum calculo a mais e necessario — uma posicao
  gravada numa tela larga volta ao minimo numa janela estreita sozinha.
- **`pack` nao encolhe filho nenhum**; `grid` reparte a falta entre todas as
  colunas. Medido: quatro botoes de 120 px num quadro de 300 ficam com 71 px cada
  em `grid` e com 120, 120, 48 e 1 em `pack` — o quarto existe, tem o tamanho
  pedido e esta fora da faixa. Onde faltar espaco, e a escolha entre "todos
  menores" e "os ultimos somem".
- **A ordem de empacotamento e a de importancia, e nao a da leitura.** No rodape:
  primeiro o aviso de "Alterações não salvas" (o unico rotulo cuja ausencia custa
  trabalho), depois as duas contagens estaveis ancoradas a direita, e por ultimo
  a mensagem transitoria e o estado do rascunho — os dois que se repoem sozinhos.
  O pior caso medido pedia 1.167 px numa faixa de 1.080 (e 1.525 numa de 1.144,
  com as duas contagens de revisao no maximo), entao alguem cede sempre; a
  decisao e sobre QUEM.

**Garantia F21 — o que se repete o dia inteiro tem atalho.** `Ctrl+Shift+Enter`
verifica e avanca (o `Ctrl+Enter` continua verificando e ficando, porque promove-lo
trocaria o significado de um habito ja formado), `Ctrl+PageUp/PageDown` viram
pagina, `Ctrl+roda` e `Ctrl+±` mudam a fonte, duplo clique aplica uma sugestao e
o rodape "Lido em:" abre as outras posicoes do comentario.

Duas correcoes desta garantia sao sobre gravacao, e nao sobre gesto:

- **A nota do revisor e gravada como o texto e.** Ela so saia por
  "Rejeitar"/"Em dúvida"/"Limpar status"; editar a nota e navegar a descartava em
  silencio. Ela e gravada **antes** da traducao dentro do `save_changes`, porque
  `set_review_status_by_id` mantem `verified` em lockstep com o status (F10) e
  chama-la depois de um `mark_verified` desfaria a verificacao pedida. E ela
  atravessa a saida antecipada de `auto_only`: digitar uma nota e acao do
  usuario, e R1 fala de gravacao sem acao dele.
- **"Verificar" em lote volta para a linha que estava aberta**, pelo id. Era o
  unico recarregamento pos-acao que caia no topo da pagina.

**Garantia F22 — o X da janela principal tem handler.** Com traducao ativa ele
CANCELA e mantem o programa aberto, em vez de fechar: fechar depois de pedir o
cancelamento mataria a thread do mesmo jeito, e o worker precisa de tempo para
terminar o arquivo que esta escrevendo (a lista T4 so e gravada no fim). Sem
traducao, ele grava a geometria da janela e repassa o fechamento as filhas — e o
`close_editor` de cada uma que grava a edicao aberta.

Uma excecao dentro do fechamento de uma filha **nao** volta pelo `tk.call`: o Tk
a entrega ao relator de callbacks (C3), que a transforma em log e dialogo. As
outras filhas e o fechamento continuam.

A janela principal tambem passou a lembrar tamanho e posicao, como os dois
editores ja faziam. Sem geometria gravada ela maximiza, que e o que sempre fez e
o certo para a primeira abertura.

**Garantia F23 — o log so rola sozinho se o fim ja estava visivel.** O `see(END)`
era incondicional: reler um `[AVISO]` durante uma execucao era ser puxado de volta
a cada tick de 100 ms. A pergunta e feita ANTES de inserir — depois da insercao o
fim ja e outro, e a resposta seria sempre "nao". Um log que ainda nao foi
desenhado responde "sim", que e o comportamento de quem nunca rolou nada.

**Garantia F24 — a janela de estatisticas nao aceita edicao.** O filtro deixava
passar QUALQUER tecla com Control, e os bindings de classe do Tk mapeiam sete
delas para editar (Ctrl+V/X/K/D/O/T/H). A defesa tem duas camadas porque sao duas
portas: uma lista BRANCA de teclas (c/a/Insert e navegacao) para o que o usuario
digita, e `break` nos eventos virtuais `<<Paste>>`, `<<Cut>>`, `<<Clear>>`,
`<<Undo>>` e `<<Redo>>` — que e por onde o Tk edita, e por isso uma versao futura
que mapeie outra tecla para `<<Paste>>` continua barrada.

Ela tambem exporta as tres tabelas do relatorio em CSV (progresso por obra,
palavras por par, atividade por dia), num arquivo so com um bloco por tabela:
elas sao lidas juntas, e tres seletores de arquivo para um clique seriam piores
que a linha em branco que as separa.

**Garantia F25 — restaurar do historico pergunta, e a janela diz o que mudou.**
Era a unica restauracao do programa sem confirmacao — restaurar o banco pergunta,
o backup do glossario pergunta, ate excluir UMA regra pergunta — com os dois
botoes de restaurar colados ao "Fechar". A pergunta mostra o texto que vai entrar,
porque e ele que distingue "Restaurar anterior" de "Restaurar nova".

Os dois textos ganharam o diff pintado do 19.5, e a linha da lista diz em quantos
trechos aquela versao mexeu — entre 100 entradas com o mesmo rotulo ("Verificacao",
"Regras automaticas"), o tamanho da mudanca e o que distingue a procurada, e
algumas delas nao mexeram no texto. O resumo sai do MESMO `diff_spans` que pinta o
detalhe: dois criterios de "o que mudou" acabariam divergindo. E o corte em 100
versoes, que terminava a lista em silencio, e anunciado.

**Garantia F26 — o historico lista alteracoes, e o ponto de partida e sempre
recuperavel.** A lista mostra so as entradas que MUDARAM o texto, e fecha com uma
versao derivada: a que a traducao automatica produziu.

Duas coisas a tornavam inutil, e as duas foram medidas no banco de 6.500 linhas:
**5.871 comentarios (90%) nao tinham nenhuma linha de historico** — o `INSERT` do
pipeline e o unico caminho que escreve traducao sem registrar — e **607 das 889
entradas gravadas nao mudam o texto** (`verify` grava `previous == new`), o que
punha o mesmo texto nos dois painels. Em 355 dos 629 comentarios com historico
era so isso.

**A versao da maquina e derivada, e nao gravada.** Como todo caminho que muda
texto registra — editar, importar CSV, aplicar automaticas, corrigir lances,
preencher linha vazia —, andar para tras chega nela sem ambiguidade: e o
`previous_translation` da entrada mais antiga, ou o texto atual quando nao ha
historico. Grava-la no `INSERT` daria a mesma resposta e duplicaria o acervo em
disco, porque o texto iria no `new_translation` de cada uma das 200 mil linhas.

O filtro e em SQL pelo mesmo motivo que o `LIMIT` existe: filtrando depois de
buscar, 100 verificacoes gastariam a pagina inteira e nenhuma alteracao apareceria.
E o que sai da lista e anunciado embaixo dela, junto com o corte em 100 versoes —
esconder 607 de 889 entradas em silencio trocaria uma lista confusa por uma
incompleta.

**Garantia F27 — o corretor de prosa marca erro de digitacao, e nunca xadrez.**
O texto da traducao e conferido contra um dicionario hunspell do idioma de
DESTINO, e a palavra desconhecida sai sublinhada na propria caixa. Tres coisas
nunca sao marcadas, e as tres foram medidas nas 6.500 linhas do banco de
desenvolvimento:

- **notacao**, e toda palavra com digito colado (`Cd4`, `13.exd5`, `h4-h5`).
  Nenhuma palavra de prosa tem digito, e quebrar o token nele produzia
  estilhacos (`Cd`) que eram 40 das 70 marcas mais frequentes;
- **o vocabulario do texto de ORIGEM da linha.** Nome de jogador, de torneio e
  de cidade chegam a traducao vindos de la. Sozinho, este filtro leva 3.347
  marcas a 143;
- **o lado direito do glossario** — a terminologia que o usuario impos; marca-la
  seria brigar com a decisao dele. O lado esquerdo NAO entra: la esta o texto que
  ele quer trocar. Este filtro leva as 143 a **81**, em **80 linhas de 6.500**.

**O corretor nunca fica em silencio onde nao funciona.** So o portugues tem
dicionario embarcado; nos outros idiomas de destino a janela diz "sem dicionario
para XX" em vez de nao marcar nada — sem isso, "nenhuma marca" significaria duas
coisas opostas, texto sem erro e corretor ausente. Se o `spylls` faltar, o
programa abre igual e so o corretor sai de cena.

A carga do dicionario (4,6 MB em disco, **258 MB em memoria**, ~2,3 s) e
**preguicosa** e acontece **fora da thread da interface**: so na primeira linha
aberta num idioma que tem dicionario, e o realce e refeito quando ela chega. Quem
nunca abre o editor nao paga nada.

**Nenhuma chamada Tk sai da thread principal.** A thread de carga nao avisa
ninguem; a janela pergunta (`request_dictionary`) e reagenda a si mesma com o
`after` dela. Um retorno vindo da thread precisaria de `after` para voltar ao Tk,
e `after` registra um comando no interpretador — fora da thread principal isso
levanta `RuntimeError`, que nao e `TclError` e escapa do `except` obvio.

A conferencia custa 1,00 ms por linha, o que permite refaze-la a cada tecla.

**Garantia F17 — nenhum campo depende do placeholder para ser identificado.**
Nenhum placeholder do programa aparece: o CustomTkinter decide mostra-lo
comparando o OBJETO `StringVar` com `""`, e essa comparacao e falsa sempre. Dos
sete campos com placeholder, cinco tem um rotulo ou um botao ao lado que os
nomeia — para eles o placeholder era uma dica a mais, e nao a identidade. Os dois
do buscar-e-substituir nao tinham nada, e ganharam rotulo: **"Buscar:"** e
**"Trocar por:"**, com a palavra do botao que aplica cada um.

O rotulo e melhor que o placeholder ali mesmo com a biblioteca corrigida:
placeholder some na primeira tecla, e e com texto dentro que dois campos iguais
lado a lado ficam impossiveis de distinguir.

**O escopo da busca da lista continua sem aparecer.** "Buscar no original ou
tradução" e o placeholder que informa mais e o unico que faz falta; um rotulo
permanente com essa frase custaria ~230 px numa coluna cujo minimo e 320.

**Garantia F16 — a mensagem de status espera o tempo do texto, e nao e engolida
pela anterior.** Cada mensagem cancela o apagamento pendente antes de agendar o
seu: sem isso o timer de uma mensagem antiga limpava o rotulo sem olhar o que
havia nele, e a mensagem nova durava o que sobrava do relogio da outra.

O tempo cresce com o texto — piso de 1,5 s, teto de 6 s, ~45 ms por caractere,
derivados de uma velocidade de leitura de ~200 palavras por minuto e nao de uma
medicao. A frase mais longa da janela ("Tradução salva e verificada; N outro(s)
original(is) também verificado(s)", 73 caracteres) passou de 1,5 s para 3,3 s.

**As mensagens nao ficam na tela ate serem substituidas**, e a decisao tem
razao: as que relatam efeito em OUTRAS linhas sao recibos de uma acao que o
usuario confirmou num dialogo — o da propagacao lista os originais um a um antes
de agir (V1). Um rotulo permanente repetiria, envelhecendo em silencio, o que o
dialogo ja disse com mais detalhe.

As tres janelas que dao recado — os dois editores e a de estatisticas — passam
pela mesma funcao. A de estatisticas tinha uma copia do padrao, com o mesmo
defeito.

**Garantia F14 — reescrever a linha aberta nao apaga o desfazer.** "Copiar
original", "Aplicar selecionada", "Aplicar todas", o "Todos" da busca-e-troca e
o "Restaurar" reescrevem o texto inteiro de uma vez — sao as acoes que mais
pedem um Ctrl+Z, e eram as unicas que o desligavam. "Trocar", que edita o widget
sem passar pelo caminho de carga, sempre teve desfazer: a diferenca era efeito
colateral, e nao decisao.

A reescrita inteira e **um** passo de desfazer, e nao dois. Os separadores
automaticos sao desligados durante ela de proposito: sem isso o primeiro Ctrl+Z
desfaz so a insercao e deixa o editor vazio — a traducao sumindo onde o revisor
esperava ve-la voltar. Vale igual para as 80 substituicoes de um "Aplicar
todas".

**Trocar de linha continua apagando a pilha**, e este e o padrao do caminho:
um Ctrl+Z que atravessasse a troca traria o texto da linha ANTERIOR para dentro
desta, e a gravacao ao navegar o levaria para o banco. E o unico dos dois lados
em que o erro corrompe dado, entao e o que um chamador novo recebe sem pedir.

**Garantia F12 — toda troca de lista grava a edicao aberta antes de
recarregar.** Trocar de pagina, de filtro, de arquivo, de par, buscar, limpar a
busca, ir para um id, voltar, e marcar a linha como rejeitada ou em duvida: os
onze caminhos gravam primeiro. Nao e zelo — a troca RECARREGA a linha, e o
recarregamento sobrescreve o widget e cancela o rascunho ainda agendado, entao o
que nao for gravado ali nao sobra em lugar nenhum.

Tres nao gravavam (o filtro de status, o "Limpar" da busca e os botoes de status
de revisao), e o "Limpar" da busca ficava ao lado do "Buscar", que sempre
gravou. **A excecao e o clique que nao troca lista nenhuma**: "Limpar" sem busca
ativa nao grava, porque uma gravacao ali seria efeito colateral de um botao que
nao fez nada — carimbo e historico numa linha que ninguem mandou salvar,
contra R1.

**E o status vai para a linha que estava na tela.** Rejeitar le o id e a nota
ANTES da gravacao do texto: `save_changes` pode recarregar a lista — com o
filtro "Avisos QA" ativo, corrigir o aviso tira a propria linha (R7) — e depois
disso a janela ja mostra outra, com a nota dela no campo. Lidos depois, o status
e a nota iriam para essa outra, e as duas na tela pareceriam certas.

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

**Garantia R11 — o resumo por status e resolvido so pelo indice.** Os numeros do
paragrafo acima chegaram a nao valer: o item 19.12 pos `review_status` na mesma
agregada e os dois indices de cobertura nao tinham a coluna, entao o plano voltou
a tocar a tabela (`EXPLAIN QUERY PLAN`: `SEARCH comments USING INDEX idx_comments_counts`, **sem** `COVERING`). Medido em 204 mil linhas
sinteticas, mediana de 20 execucoes: 118,8 ms por recarga com filtro de origem e
138,3 ms sem, contra 60,8 ms e 58,2 ms com os indices estendidos. E a mesma
regressao que o paragrafo acima registra, reintroduzida pelo recurso seguinte —
por isso o invariante virou garantia com nome, e nao so um numero num paragrafo.

A correcao e a migracao de schema **9**, que DERRUBA os dois indices antes de
recria-los com `review_status` no fim. O `DROP` nao e detalhe: `CREATE INDEX IF NOT EXISTS` sobre um indice que ja existe com o mesmo nome e colunas diferentes
nao faz nada e nao reclama, e sem ele a correcao valeria so para instalacoes
novas — que sao exatamente as que nao tem o problema.

O teste le o PLANO, e nao o cronometro: em 20 linhas nenhum tempo distingue nada,
e a palavra `COVERING` e a afirmacao que se quer proteger. Para que ele pergunte
pelo SQL de verdade, a consulta mora em `review_status_counts_query` — escrita
dentro da funcao que a executa, o teste teria de transcreve-la e passaria a medir
a propria transcricao.

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

No modo "Trecho" o texto digitado tambem nao vai cru: `%`, `_` e `\` sao
escapados e a consulta declara `ESCAPE '\'`. Sem isso o campo de busca era uma
linguagem de padroes que ninguem documentou, e a busca mais natural do dominio —
`[%eval`, uma tag de comando do Lichess, que **comeca** com `%` — era justamente
a que quebrava: ela casava toda linha com `[`, qualquer coisa e `eval`, e
devolvia lixo em vez de nada.

Eram duas varreduras por interacao ate 2026-07-27: o total do filtro ativo era
pedido numa segunda consulta, com o mesmo `WHERE` da agregada de status que ja
havia acabado de rodar. Hoje ele sai do proprio resumo (`STATUS_COUNT_KEYS`), e a
correspondencia entre filtro e chave do resumo e verificada em teste contra a
consulta dedicada — os dois criterios vivem em codigos diferentes e, se
divergirem, a lista pagina por um numero errado sem erro visivel.

**Garantia R6 — o cache de avisos nunca diverge.** `quality_warning` e derivada
de `evaluate_translation_quality` e atualizada em toda escrita de traducao
(insercao, preenchimento de vazia, edicao manual, sobrescrita por CSV e aplicacao
em massa das regras automaticas). A contagem exibida e sempre igual ao que a
avaliacao em Python produziria para as mesmas linhas.

Isso passou a exigir que o PAR DE IDIOMAS chegue aos dois caminhos, porque uma
das heuristicas depende dele (ver Q1 abaixo): as linhas do editor trazem origem e
destino nas duas ultimas posicoes, e todo ponto que grava a coluna le o par da
propria linha. Um caminho avaliando com par e o outro sem faria o numero do
rodape parar de bater com a lista, sem erro nenhum.

**Garantia Q1 — o aviso de qualidade sabe que o texto e xadrez.** As cinco
heuristicas originais eram genericas de traducao (vazia, igual ao original,
chaves perdidas, curta demais, longa demais). A medicao que motivou isto, no
banco de desenvolvimento (6.500 traducoes en -> pt, reais, de livro):

| | |
|---|---|
| linhas com erro de terminologia enxadristica | **321 (4,9%)** |
| linhas que o `quality_warning` marcava | 11 |
| intersecao entre os dois conjuntos | **0** |

As heuristicas de xadrez, todas comparando ORIGINAL com TRADUCAO:

| # | heuristica | o que ela pega |
|---|---|---|
| 1 | **lance perdido ou inventado** | o multiconjunto de ANCORAS de lance tem de bater. A ancora e a parte que nao muda de idioma (`f1`, `xe4+`), entao o aviso vale sem saber a lingua — inclusive nas linhas legadas |
| 2 | **anotacao `[%...]` rompida** | os spans do original presentes e identicos na traducao. E a prova de que a mascara de X1 funcionou, e a unica forma de achar o que execucoes anteriores ja corromperam |
| 3 | **NAGs e simbolos de avaliacao** | multiconjunto de `$n` e dos simbolos de mais de um caractere (`!!`, `+-`, `∞`) |
| 4 | **`U+FFFD`** | o sinal direto de que `errors='replace'` engoliu bytes. E4/G2 impedem na leitura nova; isto acha o legado |
| 5 | **separador vazado** | `\|\|\|` no texto gravado e desalinhamento que a contagem de partes nao pegou (B2) |
| 6 | **quase-igualdade** | uma traducao 95% identica ao original e o tradutor tendo desistido |
| 7 | **terminologia por par** | o termo X no original com a forma errada Y na traducao, com escopo de idioma (S11) |

A lista de termos vive em `Termos-suspeitos.txt`, ao lado do dicionario-semente e
com as mesmas regras: vem com o programa, e substituida na atualizacao, e um
defeito nela avisa em vez de derrubar (S5). Ela e escopada por DESTINO, e nao por
par, pela mesma razao que a semente: o termo procurado esta em ingles, e um padrao
ingles nao casa texto portugues por acaso — o proprio padrao ja e a guarda de
origem, e escopar por par deixaria de fora as linhas legadas.

**Garantia Q3 — a avaliacao da tela usa o par de idiomas da LINHA.** O rotulo
"QA:" do texto aberto e o anuncio do F7 dao a mesma resposta que a coluna
materializada daria para a mesma linha. A heuristica de terminologia so roda com
o par, entao avaliar sem ele produzia o pior desfecho possivel: "QA: sem avisos"
em verde numa linha que a lista marcava com "⚠ QA" e que o filtro "Avisos QA"
mostrava — R6 violada entre dois pontos da mesma janela.

O par sai de um acessor unico (`current_row_languages`), que e de onde a linha
remontada em memoria tambem o le. Ele **nao** e o par do filtro
(`scoped_languages`): ali "Todos" vira `""` porque uma regra de glossario com
escopo nao vale para uma lista que mistura origens, e aqui a pergunta e de que
lingua veio este texto.

**Sem linha aberta nao ha veredito.** O texto de um editor vazio produz "traducao
vazia" — um aviso verdadeiro sobre coisa nenhuma —, e ele aparecia ao abrir um
banco sem linhas.

**Garantia Q2 — as heuristicas tem versao, e muda-las reavalia o banco.**
`quality_warning` e materializada e o backfill so preenche `NULL` — correto para a
coluna nova, insuficiente para heuristica nova: com uma regra a mais, as linhas
ja avaliadas ficam com o veredito velho e R6 passa a ser violada exatamente pela
melhoria. A versao das heuristicas e gravada em `db_metadata`, e na abertura o
programa compara: se mudou, reavalia o banco com barra de progresso e
cancelamento, como toda escrita em massa. Medido: 0,127 ms por linha, ~25 s nas
200 mil do banco real, uma vez por mudanca.

**A versao so e gravada quando a reavaliacao TERMINA.** Cancelar deixa a marca
antiga de proposito — o banco esta metade reavaliado, e dizer que ele esta em dia
seria mentir de um jeito que ninguem descobre depois, porque a coluna nao tem como
acusar que esta velha. Na proxima abertura a reavaliacao acontece de novo, e o
botao "Reavaliar QA" existe para quem quiser faze-la na hora.

E a unica escrita em massa **sem backup**, e a razao e o que a coluna e:
`quality_warning` nao guarda nada que o usuario escreveu, e o seu conteudo e
recomputavel a partir do texto — que e exatamente o que a operacao faz. Um backup
de 115 MB para proteger um bit por linha, derivado, seria custo sem risco.

**Garantia V1 — a verificacao em massa diz o que vai marcar, por original.**
Marcar uma traducao como verificada propaga para as linhas do mesmo par cuja
**traducao** e identica. E a unica propagacao possivel — originais identicos ja
sao uma linha so, pela UNIQUE — e quase sempre e o que se quer; o risco esta nas
traducoes curtas. Se o tradutor verteu "Checkmate." errado como "Empate.",
verificar o "Draw." -> "Empate." legitimo marcaria a outra linha junto.

Por isso a propagacao **pergunta antes**, e a pergunta e por ORIGINAL: ela nomeia
quantos originais distintos serao marcados e lista os primeiros. A mensagem
antiga — "N iguais também verificadas", depois do fato — descrevia as traducoes, e
era exatamente por isso que nao alarmava ninguem: o que estava sendo dado por
revisado eram N textos diferentes que o usuario nao leu. Responder "Nao" verifica
so a linha aberta.

Os ids propagados sao os que a previa mostrou. Uma linha que o worker gravar com
a mesma traducao enquanto o dialogo estiver aberto nao entra — o usuario nao a
viu. E a pergunta acontece com a transacao ja comitada e a conexao fechada
(garantia C3): um dialogo modal sobre uma transacao de escrita seguraria o banco
enquanto ninguem clica.

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

**Garantia F15 — e essa regra vale nos TRES caminhos que avancam.** Ela morava
dentro de "Marcar como verificada", que era o unico a aplica-la; "Próxima >" e
"Próximo aviso QA" (F7) somavam uma casa a posicao lida DEPOIS da gravacao, e
pulavam a linha que tinha acabado de ocupar o lugar. No F7 isso e o defeito mais
caro que a janela podia ter: a fila de avisos existe para nao deixar nenhuma
linha para tras, e o botao que a percorre era o que saltava.

Hoje os tres leem a mesma funcao, e o id e a posicao sao capturados antes de
gravar. **Para tras a conta nao muda** — a linha que vinha antes continua uma
casa antes da posicao vaga —, e quando a linha permanece na lista o avanco e o
normal.

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

**Uma secao repetida no `spelling.ssp` acrescenta, e nao substitui.** O jeito
natural de acrescentar nomes ao arquivo e abrir um segundo bloco `@PLAYER` no
fim, e isso APAGAVA as entradas do bloco anterior — 512.668 grafias de jogador no
arquivo que vem com o projeto, medidas —, sem uma linha de aviso. Entre blocos
vale a mesma regra que dentro de um: o primeiro a definir uma chave vence. O
`ignore_chars` do bloco repetido substitui o anterior, porque e um parametro do
bloco e nao uma lista para acumular.

**Garantia D6 — o dicionario de grafias tem indice derivado, com hash do fonte.**
O `spelling.ssp` sao 30,5 MB e 985.829 linhas, e ele era reparseado por inteiro a
cada uso: 1,0 s e 72 MB de pico para corrigir cinco tags de um PGN de 20 KB. O
indice e um SQLite ao lado do fonte, com o mesmo desenho do `glossario.db`:

- **construido em fluxo**, na primeira normalizacao de cada maquina (2,0 s, 5,4 MB
  de pico, 513.797 entradas). O dicionario inteiro nunca existe em memoria;
- **valido enquanto o hash do conteudo do fonte for o mesmo**. Trocar o
  `spelling.ssp` por uma versao nova das classificacoes reconstroi o indice; o
  `mtime` nao serviria (muda quando o arquivo e reescrito igual);
- a marca de conclusao e gravada **por ultimo**, entao uma construcao interrompida
  e refeita em vez de consultada pela metade;
- as respostas sao as do arquivo, chave por chave, inclusive a precedencia entre
  blocos repetidos (`INSERT OR IGNORE` reproduz "o primeiro vence");
- **se o indice nao puder ser usado** — pasta sem escrita, banco corrompido —, a
  normalizacao le o arquivo direto, com aviso no log dizendo por que. O botao
  continua funcionando pelo custo que sempre teve.

O indice **nao** e versionado no repositorio, ao contrario do `glossario.db`, e a
diferenca e de tamanho: 1,1 MB que viajam junto para poupar uma reconstrucao,
contra 25,5 MB para poupar 2 s.

**O valor gravado e re-escapado.** O `spelling.ssp` fala na forma que se escreve
(`O"Kelly`) e o PGN na forma escapada (`O\\"Kelly`); a conversao acontece nas duas
pontas — desescapar para comparar com o dicionario, reescapar para gravar. Sem a
segunda, um `"` no nome canonico era inserido cru e a tag deixava de ser valida:
o dano nao aparece neste programa, aparece no ChessBase de quem abre o arquivo.

**Um arquivo que falha nao derruba o lote.** Permissao negada, arquivo aberto no
ChessBase, disco cheio na gravacao: a excecao subia daqui ate a interface, que
mostrava "Erro ao normalizar PGN" e nenhuma estatistica — os arquivos ja
corrigidos ficavam em disco sem que nada dissesse quais eram, e os seguintes nunca
eram tentados. Hoje cada falha e contada com o motivo, o lote segue, e o resultado
e um AVISO em vez de um "concluida" liso.

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
| T5 | Nenhuma ferramenta de escrita em massa roda durante uma traducao | Bug: restaurar um backup durante uma execucao produz um banco que nao e nem um nem outro |
| P1 | O par (original, origem, destino) e a identidade da traducao | Limite: o mesmo texto em duas linguas era uma linha so |
| P2 | Declarar o idioma adota o cache existente em vez de paga-lo de novo | Risco: a mudanca de chave cobrar 201.607 traducoes ja feitas |
| O1 | O banco registra onde cada comentario foi lido: arquivo, partida, indice e lance | Limite: `ORDER BY id` nao e ordem de leitura de obra nenhuma |
| O2 | O contexto entra ao lado da traducao (N para 1), e nunca e inventado | Risco: o arquivo na chave faria a revisao ser feita uma vez por livro |
| O3 | Com um arquivo escolhido, a lista e a obra em ordem de leitura, cada comentario uma vez | Limite: nao havia como revisar um livro na ordem em que ele se le |
| O4 | "Zerar Traducoes" leva as ocorrencias junto | Risco: o `AUTOINCREMENT` reinicia, e a ocorrencia velha aponta para a traducao nova |
| F1 | Trocar a orientacao dos dois textos nao perde o que esta sendo editado | Risco: reconstruir os paineis apaga texto, desfazer e selecao no meio de uma edicao |
| F2 | A linha da lista diz status, aviso e origem, e o marcador vem da coluna | Limite: achar as linhas com aviso exigia trocar o filtro e perder a obra de vista |
| F3 | "Voltar" restaura a linha E os filtros que a traziam | Limite: usar a busca como concordancia descartava a pagina, sem volta |
| F4 | "Palavra" e a mesma unidade em todo o programa | Risco: duas contagens fariam o orcamento discordar do relatorio |
| F5 | As estatisticas sao computadas fora da thread da interface, e o resultado se copia | Bug: a ultima operacao pesada dentro do callback do botao, num `messagebox` que nao se copia |
| F6 | O TMX exportado e XML valido, e so leva par com traducao | Risco: um acervo de 200 mil pares preso num formato que so este programa le |
| F7 | A selecao em lote e por id, verifica so o que esta marcado e nao propaga | Risco: 100 linhas marcadas abrindo 100 confirmacoes de propagacao, ou nenhuma |
| F8 | O rascunho grava fora da thread da interface, e duas gravacoes nao se perdem | Bug: engasgo na digitacao em disco lento; corrida entre as duas threads que gravam |
| F9 | A requebra muda so espaco em branco, e nunca dentro de `[%...]` | Risco: requebrar tocando a chave de cache, ou partindo uma anotacao que X1 protegeu |
| F10 | `verified` e `review_status` andam em lockstep, nos quatro caminhos que os escrevem | Bug: linha verificada E em duvida ao mesmo tempo, que nenhum filtro mostra direito |
| F11 | A previa de "Aplicar todas" marca as faixas trocadas nos dois lados | Risco: conferir 80 substituicoes comparando dois blocos de texto a olho nu |
| F12 | Toda troca de lista grava a edicao aberta antes de recarregar, e o status vai para a linha que estava na tela | Bug: o filtro de status, o "Limpar" da busca e o "Rejeitar" descartavam o texto digitado — nem no widget, nem no banco, nem no rascunho |
| F13 | O retrato do "voltar" e o da consulta que estava em vigor, e repoe os seis filtros — busca, modo, status, origem, destino e arquivo | Bug: o retrato lia os seletores, que ja estavam no valor novo; "voltar" repunha o filtro que o usuario acabou de escolher |
| F14 | Reescrever a linha aberta preserva o desfazer, e a reescrita inteira e UM passo; trocar de linha apaga a pilha | Bug: as cinco acoes que reescrevem o texto em bloco eram as unicas sem Ctrl+Z; e uma pilha que atravessasse a troca de linha gravaria a traducao de uma linha noutra |
| F15 | Gravar e avancar nao pula a linha que ocupou o lugar da que saiu do filtro | Bug: com "Avisos QA" ativo, corrigir o aviso e clicar "Próxima >" (ou F7) saltava a linha seguinte da fila, sem nada na tela |
| F16 | Uma mensagem de status nao e apagada pelo timer da anterior, e o tempo de tela cresce com o texto | Bug: duas mensagens em menos de 1,5 s davam meio segundo a segunda; e a frase de 73 caracteres tinha o tempo de "Salvo" |
| F17 | Nenhum campo depende do placeholder para ser identificado | Bug: o CustomTkinter nao mostra placeholder em campo com `textvariable`, e o buscar-e-substituir eram dois campos anonimos lado a lado |
| F18 | Os atalhos aparecem na janela, o foco tem borda, o "B" ligado se ve nos dois temas e a troca de tema repinta o Tk puro | Bug: treze atalhos so no fonte (um deles sem nenhum caminho de descoberta), foco invisivel, "B" ligado igual ao desligado no escuro, e meia janela no tema antigo |
| F19 | As cores de rotulo passam 4,5:1 nos dois temas, e o status de revisao aparece em palavras | Bug: as quatro cores semanticas reprovavam (o ambar dos avisos a 1,55:1), e rejeitada/em-duvida era so a cor de uma borda |
| F20 | Cada rotulo de acao carrega o objeto dela, a largura minima da janela e a SOMA dos minimos dos paineis, e nada e desenhado fora da faixa em que vive | Bug: tres botoes "Limpar" e quatro "Página"; e a 1120 px o painel de sugestoes ficava com 109 dos 300 que declara, dois botoes do lote saiam da barra e o campo de pagina media 11 px |
| F21 | Toda acao repetida do fluxo tem atalho, a nota do revisor e gravada como o texto, e o clique numa linha poe o foco onde se vai digitar | Custo: em "Todas" eram dois acordes por linha; a nota digitada era descartada em silencio ao navegar; e "Verificar" em lote voltava ao topo da pagina |
| F22 | O X da janela principal cancela em vez de matar uma traducao, e repassa o fechamento as janelas filhas | Bug: nao havia handler nenhum — o PGN da vez ficava truncado, a lista T4 nao era gravada e a edicao aberta do editor perdia ate 2,5 s |
| F23 | O log so rola sozinho quando o fim dele ja estava visivel | Incomodo: reler um `[AVISO]` durante uma execucao era ser puxado de volta a cada 100 ms |
| F24 | A janela de estatisticas nao aceita edicao, nem por evento virtual, e exporta as tabelas em CSV | Bug: Ctrl+V/X/K/D/O/T/H editavam um relatorio que o docstring declara imutavel; e as tabelas de orcamento so saiam em texto corrido |
| F25 | Restaurar uma versao do historico pergunta antes, e a janela diz o que mudou entre as duas | Risco: a unica restauracao do programa sem confirmacao, com os dois botoes colados no "Fechar" e nenhum diff pintado |
| F26 | O historico lista as ALTERACOES, e a versao da traducao automatica e sempre recuperavel | Bug: 90% das linhas abriam em "nenhuma alteracao registrada" e 607 das 889 entradas mostravam o mesmo texto dos dois lados — nao havia como voltar ao que a maquina produziu |
| S16 | O dialogo de zerar o glossario conta o que apaga, por tipo, e a semente nao "volta" depois | Bug: anunciava 7.325 regras e apagava 5.910; e zerar deixava a sessao sem sugestao nenhuma e a abertura seguinte com 232 |
| S17 | O "Teste rápido" do glossario usa a conversao do pipeline, e nao os pares crus | Bug: prioridade descartada, escopo ignorado, `@casa@` inerte e so a primeira ocorrencia trocada — a previa contradizia o banner S9 ao lado dela |
| S18 | O editor de glossario anda pelo teclado: achar, andar pela lista filtrada e virar pagina | Custo: dois atalhos contra os treze do outro editor, numa janela que existe para varrer 7 mil linhas |
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
| S12 | Conflito por diferenca de caixa e anunciado, e so quando a vencedora produz outra coisa | Bug: 210 regras nunca disparavam, e o detector era cego a todas |
| S13 | Tipo de regra desconhecido avisa em vez de degradar em silencio | Bug: `'automático'` virava sugestao e deixava de rodar depois da API |
| S14 | Exportar e reimportar o glossario preserva as regras de delecao | Bug: o round-trip pelo CSV descartava as 50 em silencio |
| S11 | Regra com escopo de idioma so e aplicada no seu par | Bug: `('movimento','lance')` corrompia `il movimento` numa traducao para o italiano |
| S15 | A semente nunca sobrepoe uma regra do usuario | Risco: o programa passar a vir com terminologia e ela vencer a de quem usa |
| R1 | Gravacao so por acao do usuario | Bug: navegar reescreve o banco |
| R5 | Navegar custa O(pagina) | Perf: paginacao anulada por varredura |
| R11 | O resumo por status e respondido so pelo indice, sem tocar a tabela | Perf: o item 19.12 poe `review_status` no WHERE e nao nos indices de cobertura; o plano perdeu a palavra `COVERING` e a consulta de toda recarga passou a ler 200 mil linhas |
| R8 | Navegar custa O(pagina) tambem com busca ativa | Perf: `LIKE '%x%'` varre a tabela a cada interacao |
| R6 | Cache de avisos nao diverge | Risco da coluna materializada |
| Q1 | Lance perdido e anotacao rompida geram aviso | Medicao: 401 erros de terminologia contra 11 linhas marcadas, intersecao zero |
| Q2 | As heuristicas de QA tem versao, e muda-las reavalia o banco | Risco: a melhoria violar R6 nas 200 mil linhas ja avaliadas |
| Q3 | A avaliacao de QA na tela usa o par de idiomas da LINHA, e sem linha aberta nao ha veredito | Bug: "QA: sem avisos" em verde numa linha que a lista marcava com "⚠ QA"; e "traducao vazia" anunciado com o editor vazio |
| R7 | A lista carrega o item clicado | Bug: clicar em B carregava C |
| R9 | O editor mostra um par de idiomas de cada vez | Queixa de uso: revisar em espanhol achando que era italiano |
| R10 | "Ir para ID" e "Proximo aviso" respeitam o filtro de origem | Bug: com "Origem: Espanhol", um ID ingles selecionava uma linha espanhola arbitraria |
| V1 | A verificacao em massa diz o que vai marcar, por original | Risco: "Draw." e "Checkmate." com a mesma traducao curta, e um deles dado por revisado sem ninguem ver |
| Z1 | O backup vem antes da pergunta, e o caminho dele aparece nela | Risco: a unica volta atras depender de o que vem depois do "Apagar" |
| Z2 | Apagar exige a palavra digitada, e o botao parece inerte ate la | Risco: "Sim" a um pixel do "Nao" para 201 mil traducoes |
| Z3 | Zerar um nao toca no outro, e leva junto historico, indice e cache | Risco: o cache em memoria reviver o que foi apagado |
| N1 | So as cinco tags mudam; lances, variantes e comentarios saem identicos | Risco: a lista de tags vivia em dois lugares |
| C1 | Trabalho pesado roda fora da thread do Tk, e a resposta volta nela | Bug: "Aplicar automaticas" segurava a janela por 38 s |
| C3 | Nenhuma transacao de escrita atravessa uma chamada de rede, e um lock vira mensagem | Bug: worker travava o "Salvar" do editor por um lote inteiro |
| C4 | "Cancelar" e conferido dentro do laco de tentativas, antes de cada uma e antes de cada espera | Bug: `translate_text_chunk` nem recebia o flag; contra um endpoint que pendura a conexao, o clique ficava ate ~93 s sem efeito |
| M1 | A janela principal reabre no que foi escolhido | Risco: "Detectar" volta sozinho e desliga a correcao de lances sem avisar |
| M2 | Um BOM no arquivo de configuracoes nao apaga nada | Bug: um caractere invisivel zerava rascunhos, lista de falhas e preferencias |
| X1 | Anotacoes `[%...]` atravessam a traducao byte a byte, ou o comentario conta como falha | Bug: `[%cal Ra1h8]` virava `[%cal Ta1h8]`; `[%eval +0.35]` quebrado antes da API |
| X2 | Comentario esvaziado pela limpeza sai do arquivo sem deixar `{}` | Sujeira: o PGN gerado saia pontilhado de `{}` |
| X3 | Comentarios `;` sao contados e anunciados | Bug de percepcao: PGN so com `;` respondia "nenhum comentario encontrado" |
| D1 | O PGN traduzido e escrito numa passada, sem uma segunda copia dele na memoria | Perf: 15 mil comentarios em 3,2 MB custavam 26,9 s de copia; o custo cresce com o produto |
| D2 | Cancelar interrompe a gravacao do PGN, e sem deixar arquivo pela metade | Bug: a fase nao olhava o `cancel_flag`, e "Cancelar" ficava sem efeito visivel |
| D3 | Cada PGN e lido uma vez por passada, com a codificacao detectada nos bytes lidos | Perf: quatro leituras do arquivo por execucao, duas delas decodificando tudo |
| D4 | Comentario repetido no proprio arquivo vai uma vez para a API, e a conta do resumo fecha | Custo: um lote com "Diagram" 30 vezes enviava as 30; tres comentarios sumiam da aritmetica |
| D5 | Conteudo, posicoes e contexto de leitura de um PGN nao atravessam a fase da API | Perf: `info_by_file` segurava o acervo inteiro pela execucao toda |
| D6 | O indice de grafias responde como o arquivo, e um fonte trocado o reconstroi | Perf: 1,0 s e 72 MB por uso para corrigir cinco tags de um PGN de 20 KB |
| D7 | A ordem das regras do glossario e identificada por versao, e mutar a lista renova a versao | Perf: uma tupla de 7.334 elementos montada e hasheada a cada tecla do editor |
| I1 | Atualizar o programa nao toca em nenhum arquivo da pasta de dados | Risco: o README mandava copiar o glossario para dentro de `dist\`, e um instalador feito sobre aquela pasta o sobrescreveria (protegida por `instalador\verificar-ciclo.ps1`, e nao pela suite) |
| I2 | A primeira execucao instala o glossario inicial so quando nao ha nenhum | Risco: "instalar o padrao" e "sobrescrever o do usuario" sao a mesma linha com a condicao errada |
| I3 | Dados de uma instalacao anterior sao COPIADOS, e o original fica onde estava | Risco: mover impede voltar para a versao anterior |
| I4 | Desinstalar preserva a pasta de dados, a menos que o usuario peca o contrario | Risco: desinstalar para reinstalar apagaria o acervo (protegida por `instalador\verificar-ciclo.ps1`) |
| I5 | A versao tem uma fonte so, e instalar uma mais velha por cima nao acontece em silencio | Bug: tres numeros que nao se falavam (0.2.1 no `pyproject`, 1.0 no TMX, 1.0.0 no instalador) e nenhuma protecao contra voltar no tempo |
| I6 | A entrega portatil e a instalavel sao o MESMO executavel, e o que as separa e um arquivo ao lado dele | Risco: dois builds seriam duas coisas para testar, e a que ninguem roda quebra primeiro. O marcador nunca entra em `dist\` — o `.iss` empacota a pasta inteira, e ele faria a versao INSTALADA gravar dentro de `Program Files` |
| I7 | O log nomeia o MODO, e nao so a pasta de dados | Risco: um `.exe` portatil e um instalado apontado por `PGN_TRADUTOR_DATA` podem gravar na mesma pasta por motivos diferentes, e so o modo explica o que a proxima atualizacao fara com o acervo |

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
- **"Backup BD" continua permitido durante uma traducao**, e e a unica
  ferramenta fora de T5. Ele so LE o banco de trabalho, e a API de backup do
  SQLite ve o banco logico (`-wal` incluido): a copia sai consistente com o
  worker escrevendo. Recusar negaria a copia justamente a quem quer guardar o
  estado de uma execucao longa. (ROADMAP 17.2)

**Anotacoes embutidas e conteudo que nao e prosa**

A secao 13 do ROADMAP fechou as corrupcoes desta familia (garantias X1, X2 e
X3). O que resta declarado como limite:

- **NAGs `$n` e simbolos de avaliacao dentro de comentarios vao crus para a
  API.** A mascara de X1 cobre so os spans `[%...]`; um `$14` ou um `+-` na
  prosa fica sujeito ao tradutor. NAG vive no movetext — que nunca e tocado —,
  entao o caso e raro. A garantia Q1 passou a **acusar** o que isso produz (o
  multiconjunto de NAGs e simbolos tem de bater dos dois lados), mas nao a
  impedir: mascarar tambem esses tokens continua sendo o passo que falta, e agora
  ha como medir se ele vale a pena. Medido no banco de desenvolvimento: zero
  comentarios com NAG ou simbolo divergente.
- **Anotacoes ja corrompidas por execucoes anteriores continuam no banco**, e
  agora ELAS GERAM AVISO (Q1, heuristica 2): X1 protege a traducao nova, e a
  comparacao byte a byte entre os spans dos dois lados e o que faz o legado
  corrompido aparecer no filtro "Avisos QA". Corrigi-lo continua sendo trabalho
  manual, uma linha por vez.
- **O arquivo gerado sai com comentarios em linha unica**, fora do export
  format de 80 colunas que editoras esperam. Requebrar na gravacao esta na
  secao 19 do ROADMAP (item 13).
- **UTF-8 com BOM e opt-in** (`output.utf8_bom`); o padrao continua sem BOM, e
  quem le os PGN no ChessBase do Windows precisa ligar a opcao.

**Desempenho e escala**

- O modo "Trecho" varre a tabela por definicao — e o preco de achar um pedaco
  literal, e a interface declara qual modo esta ativo.
- A migracao para o schema 4 custa ~7 s uma vez, na primeira abertura apos a
  atualizacao: a tabela de 201.607 linhas e reconstruida porque o SQLite nao
  remove restricao de tabela, e so isso troca a UNIQUE antiga pela do par de
  idiomas. Os ids sao preservados, entao o indice FTS5 continua valendo e nao
  precisa ser refeito. (ROADMAP 9.2)
- A migracao para o schema 5 e de dados, nao de colunas: colapsa `digito.
  digito` com espaco nas chaves de cache gravadas pelo achatamento antigo, uma
  vez (ROADMAP 13.2). Uma chave cujo par colapsado ja exista fica como esta —
  peso morto que nunca mais casa com arquivo nenhum, e nao erro.
- A migracao para o schema 7 cria a tabela `occurrences` e nada mais: 0,05 s no
  banco de dev. Nao ha backfill (O2), entao ela e barata em qualquer tamanho de
  banco.
- A migracao para o schema 8 sao dois `ALTER TABLE` (`review_status` e
  `reviewer_note`): nenhuma restricao muda, entao a tabela nao e reconstruida.
  Medido em 201.500 linhas: 1,86 s, uma vez.
- **A contagem de palavras le os dois textos de todas as linhas** — 675 ms em
  201.500 linhas, dentro da coleta das estatisticas (1,12 s no total). E uma
  passagem completa por definicao, e por isso ela roda fora da thread da interface,
  com progresso e cancelamento (F5).
- **Exportar o acervo custa ~1,2 s e ~55 MB** em TMX (201.500 unidades) e ~1,3 s em
  CSV. Os dois escrevem em blocos, sem materializar o banco em memoria, e os dois
  apagam o arquivo se forem cancelados.
- A requebra de 80 colunas custa **277 ms para 15.000 comentarios** de 60
  palavras — o tamanho do PGN de 40 MB que o ROADMAP 20 usa como pior caso.
- **O pico de memoria de um livro unico e maior do que era, e a troca foi
  deliberada.** Medido num PGN de 9 MB com 15 mil comentarios: 67,4 MB antes,
  75,5 MB depois. A parte cara da extracao — a copia do conteudo que apaga os
  comentarios para ler partida e lance (O1) — passou a acontecer na vez do
  arquivo, quando os textos e as traducoes ja estao em memoria, em vez de no
  comeco da execucao. Em troca, a fase da API deixou de segurar o conteudo dos
  PGN: 4,1 MB de memoria viva contra 10,5 MB, e num livro de 40 MB sao 40 MB que
  nao ficam retidos por minutos. Baixar esse pico exige tirar a copia de
  `comment_reading_context`, que e desenho da secao 18 e nao da 20. (ROADMAP 20.4)
- **A primeira passada le todos os arquivos uma vez a mais do que o estritamente
  necessario para um arquivo so.** Ela existe para saber o total (a barra de
  progresso precisa do denominador antes do primeiro lote) e para carregar o cache
  numa consulta (ROADMAP 2.9). Com um arquivo unico, isso e uma leitura e uma
  varredura de comentarios que a execucao poderia evitar; com um acervo, e o que
  substitui guardar tudo na memoria. (ROADMAP 20.4)
- **A primeira normalizacao de metadados de cada maquina paga a construcao do
  indice** do `spelling.ssp`: 2,0 s para 513.797 entradas, anunciada no log. As
  seguintes abrem em 29 ms, dos quais 27 sao o hash do fonte — o preco de notar
  que o dicionario foi trocado. (ROADMAP 20.5)
- **O menu de arquivos do editor custa um `GROUP BY` sobre as ocorrencias do
  par** — 137 ms medidos em 200 mil ocorrencias. Ele e refeito na abertura da
  janela e na troca de par, e nao a cada interacao: por isso o filtro por arquivo
  nao viola R5, e por isso um arquivo processado enquanto a janela esta aberta so
  aparece no menu depois de trocar o par ou reabri-la. (ROADMAP 18.4)
- **O progresso por obra le todas as ocorrencias** — 207 a 309 ms em 200 mil,
  dentro de "Estatisticas do BD", que ainda roda na thread da interface. E uma
  agregacao por definicao; o que resolve o congelamento e tirar as estatisticas do
  clique (ROADMAP 19, item 7), nao a consulta. Um terceiro indice foi medido e
  recusado: economizou 3 ms de 207. (ROADMAP 18.1)

**Rede**

- Depende de um endpoint nao oficial, sujeito a bloqueio por volume.
- **"Cancelar" nao alcanca o retry em andamento**: o laco de tres tentativas
  nao olha o `cancel_flag`, e contra um endpoint que pendura a conexao o clique
  pode esperar ~93 s por chunk (3 x 30 s de timeout + as esperas). Reproduzido
  com sessao falsa: cancelado na primeira tentativa, as tres rodaram.
  (ROADMAP 22.13)

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
  adiantar uma regra e o escopo (S11) resolve o de restringi-la a um par de
  idiomas, mas nao ha **grupos nem condicoes**: dentro do seu escopo e do seu
  recorte de tipo, uma regra vale para todo texto.
- **O escopo alcanca o destino, e nao a origem numa regra de limpeza.** Uma
  regra de `cleanup` scopada por origem nao e expressavel; nenhuma das 50
  precisa, porque lixo de conversao nao tem lingua. A forma `'en>'` existe no
  parser e o que falta e decidir o que ela significaria ali. (ROADMAP 15.1)
- **A semente nao aparece no editor de glossario**, que edita o arquivo do
  usuario. As regras dela chegam como sugestao sem linha correspondente na
  lista, e "Excluir do glossario" numa delas cai no caminho de "entrada nao
  encontrada" (S6: nada e gravado, e o usuario e avisado). (ROADMAP 15.2)
- **A semente e toda `suggestion`**: para quem traduz para o italiano, ela ajuda
  na revisao e nao na passagem automatica. E deliberado — aplicar palpite
  generico sem ninguem ver e o que a secao 14 passou uma revisao consertando.
- A sensibilidade a caixa e **inferida da grafia do padrao** (`orig ==
  orig.lower()`), e nao declarada. Escrever uma regra em minusculas e a unica
  forma de pedir casamento sem diferenciar caixa, entao as duas decisoes —
  "quero casar maiusculas?" e "como grafo o padrao?" — vivem no mesmo lugar. A
  garantia S12 faz o programa **acusar** o que isso produz (a regra
  capitalizada engolida), mas nao separa as duas decisoes.
- As **166 regras mortas inofensivas** continuam no arquivo. Elas nunca
  disparam, e nada se perde: a vencedora produz o que elas queriam, porque a
  capitalizacao e propagada. O detector nao as aponta de proposito. (ROADMAP
  14.4)
- **A curadoria alcancou o que a medicao alcanca.** As regras que corrompem
  construcoes que ninguem escreveu numa frase de teste continuam la; o que o
  programa ganhou foi como acusa-las. (ROADMAP 14.10)
- Padronizar os **tres estilos de aspas** da coluna "e" (`'peão "e"'`,
  `"coluna 'e'"`, `'coluna e'`) ficou de fora: escolher qual aparece no texto
  publicado e decisao editorial, nao correcao. (ROADMAP 14.9)
- O reconhecimento de arquivo gerado e por **nome**, e so alcanca os sufixos
  que este programa escreve (`-BR`, `-BR-2`, `-NORM-3`). Um PGN renomeado a mao,
  ou traduzido por outra ferramenta, volta como entrada — nao ha marca dentro do
  arquivo dizendo que ele e uma saida. (ROADMAP 17.10)
- **Regra de `cleanup` nao e oferecida no editor**: o contexto interativo
  carrega sugestoes e automaticas. Para as 50 regras de delecao isso e o
  desenho certo — elas agem no PGN de origem, antes da API —, mas significa que
  lixo ja gravado numa traducao nao tem remocao por um clique. Medido no banco
  de desenvolvimento: zero ocorrencias dos 50 padroes nas traducoes. (ROADMAP
  14.5)

**Revisao e qualidade**

- **A lista de termos suspeitos cobre um idioma de destino.** Para portugues ela
  foi medida termo a termo nas 6.500 traducoes reais; para es/fr/de/it/ru so
  existem `White`/`Black` (o caso "nao foi traduzido", que nao depende de saber a
  forma consagrada de cada lingua). Os demais termos estao ausentes de proposito:
  nao ha medicao deles nesta maquina, e uma lacuna e melhor do que um aviso
  errado — a mesma decisao que o dicionario-semente registra. (ROADMAP 16.1)
- **Dois candidatos do plano nao sobreviveram a medicao e ficaram fora**, e o
  numero de cada um esta no ROADMAP 16.3: o multiconjunto de DIGITOS (marcava 3
  linhas, e as 3 eram formatacao correta em portugues — `2.500`, seculo `XIX`) e o
  par `exchange` -> `troca` (178 linhas, a maioria certa: "trocar" e a traducao boa
  do verbo). (ROADMAP 16.3)
- **A terminologia depende de o termo estar em ingles no original.** Um
  comentario original em espanhol traduzido para portugues nao e coberto por
  nenhuma entrada de hoje, e um erro de terminologia ali nao gera aviso.
- **O aviso nao sabe se a linha ja foi revisada por alguem.** Uma traducao
  marcada como verificada que gera aviso continua gerando: o aviso e sobre o
  texto, e "verificada" e sobre quem olhou. O editor mostra os dois, e o
  relatorio de QA separa por status.
- **Nenhuma entrada do `Termos-suspeitos.txt` tem escopo de PAR.** Sao 24, todas
  por destino (14 `pt`, 2 para cada uma das outras cinco linguas), entao com o
  arquivo que vem no programa o idioma de ORIGEM nunca muda o resultado da
  terminologia. Ele e passado a avaliacao mesmo assim, porque a coluna
  materializada o passa e as duas tem de receber os mesmos argumentos (Q3) — mas
  a simetria nao esta testada, e so estara quando existir uma entrada `en>pt`.
  (ROADMAP 22.2)
- **A reavaliacao nao acontece quando so o `Termos-suspeitos.txt` e editado a
  mao.** A versao das heuristicas e uma constante no codigo (Q2), e nao um hash do
  arquivo: quem editar a lista tem de subir a constante ou clicar em "Reavaliar
  QA". Um hash pareceria mais automatico e reavaliaria 200 mil linhas a cada
  atualizacao do programa que mexesse num comentario do arquivo. (ROADMAP 16.2)
- A verificacao em massa propaga pela **traducao** identica dentro do par, e
  continua sendo a unica propagacao possivel: originais identicos ja sao uma
  linha so, pela UNIQUE. V1 faz a operacao se anunciar antes — os originais
  aparecem na confirmacao —, e nao muda o criterio. Quem responder "Sim" sem ler
  a lista marca como revisado um texto que nao viu. (ROADMAP 17.4)
- O modo "sobrescrever existentes" da importacao **so promove** o `verified` do
  CSV: uma linha marcada como verificada no arquivo passa a verificada no banco,
  mas a coluna vazia (ou ausente, num CSV montado a mao) nao rebaixa nada. A
  ausencia de uma afirmacao nao e a afirmacao contraria — e rebaixar em massa por
  uma coluna que ninguem preencheu seria o pior acidente possivel dessa
  ferramenta. Voltar uma linha para pendente continua sendo acao do editor.
  (ROADMAP 17.7)
- A sobrescrita compara o texto **byte a byte**: um CSV que so mudou espacos em
  branco conta como diferente e sera gravado. Normalizar antes de comparar
  esconderia edicoes de espacamento que o tradutor fez de proposito.
  (ROADMAP 17.7)

**Fluxo de revisao (o que a secao 19 deixou de fora)**

- **Nao ha corretor ortografico da PROSA traduzida.** O `spelling.ssp` que o
  programa traz e dicionario de nomes proprios, para as tags; um corretor de
  verdade precisa de um dicionario hunspell por idioma de destino e de uma
  dependencia nova, que mudam o `requirements.txt` e o empacotamento. Nao ha
  esqueleto nem botao desabilitado no lugar: um recurso que parece existir e nao
  funciona e pior que a ausencia. Os erros de digitacao da revisao continuam
  chegando ao proximo leitor. (ROADMAP 19.14)
- **O status de revisao e a nota nao entram no historico de edicoes.** O
  `comment_history` e do TEXTO — quem mudou a traducao, quando, e para o que. Uma
  linha que foi rejeitada e depois aceita nao deixa rastro dessa ida e volta.
- **A importacao de CSV ignora `review_status` e `reviewer_note`**, que ela
  exporta. E o mesmo criterio do `verified` (a importacao so promove) levado ao
  limite: nao ha resposta segura para "quem vence" numa nota de texto livre escrita
  na planilha. O efeito e que um round-trip pelo CSV perde o que o revisor escreveu
  — e essa e a razao de estar escrito aqui.
- **A importacao continua casando por TEXTO, e nao pelo `id`** que agora ela
  exporta. Corrigir o original na planilha continua criando uma linha nova em vez de
  atualizar a antiga. (ROADMAP 19.8)
- **O TMX nao leva data de criacao nem de alteracao.** Os carimbos do SQLite sao
  hora local sem fuso; convertidos como UTC embutiriam o erro do fuso, e o padrao
  nao tem onde dizer "isto e local". O `tuid` continua sendo o que identifica a
  unidade.
- **A produtividade por dia so conta o que passou pelo EDITOR.** Traducao gravada
  pelo worker nao gera historico, entao um dia de traducao automatica aparece como
  zero — o numero e de revisao, e nao de producao.
- **A requebra de 80 colunas alcanca os comentarios, e nao o movetext.** As linhas
  de lances continuam como estavam no original: reflui-las seria reescrever o que a
  garantia N1 promete sair identico.
- **A contagem de palavras nao distingue prosa de notacao.** `14.Bxf7` conta como
  uma palavra, e um orcamento feito sobre um PGN muito anotado inclui esses tokens.
  E deliberado — e a mesma unidade que o cliente usa para pagar —, mas quem orca
  precisa saber.

**Interface (o que a revisao de 2026-07-31 encontrou; ROADMAP 22)**

Cada item e comportamento ATUAL, confirmado como o ROADMAP 22 descreve —
em janela real, headless ou por leitura de codigo, dito la item a item.

- **Os placeholders que sobraram continuam sem aparecer**, nos cinco campos que
  tem rotulo ou botao proprio (F17). Eles voltariam sozinhos se o CustomTkinter
  corrigir a comparacao; ate la, a dica que cada um daria — o escopo da busca, o
  que escrever na nota — nao chega a ninguem. (22.7)
- **O rotulo dos botoes nao diz o atalho deles.** A lista de F18 alcanca os
  vinte, mas quem esta com a mao no mouse so descobre que "Salvar" tem `Ctrl+S`
  se abrir a lista. Pendurar o atalho no rotulo esbarra na largura: as duas
  fileiras do rodape pedem 831 e 932 px dos ~1080 da largura minima — medido de
  novo em 22.10, e os dois numeros continuam valendo. (22.8)
- **O contraste foi medido na camada de rotulos, e nao em toda a janela.** F19
  cobre as cores semanticas, a linha selecionada e o destaque da busca; os
  fundos dos proprios widgets do CustomTkinter e os botoes ficaram como o tema
  os entrega. Os textos grandes ja passavam com folga, de 6,8:1 a 17:1. (22.9)
- **Nao ha historico das mensagens de status.** Elas somem depois do tempo de
  leitura (F16) e nao ficam em lugar nenhum. As que relatam efeito em outras
  linhas sao recibos de uma acao confirmada em dialogo, entao a informacao nao
  se perde — mas quem olhar para o lado na hora errada perde o recibo. (22.6)
- **A selecao em lote sobrevive a trocar de arquivo, de status e de busca** — so
  a troca de PAR a apaga. E deliberado: juntar linhas de tres capitulos e o caso
  que a barra existe para servir (F7). O preco esta pago pela confirmacao, que
  diz quantas das marcadas estao fora dos filtros atuais (F21); o que nao existe
  e um jeito de VER quais sao. (22.11)
- **O editor de glossario nao tem selecao em lote.** Com os filtros
  "Duplicadas"/"Conflitos", excluir oito duplicatas continua sendo oito ciclos
  de clique + "Excluir" + "Sim". A paridade transplantada em S18 e a do teclado;
  uma exclusao em massa e acao destrutiva nova, e pede confirmacao e backup
  proprios em vez de herdar os da exclusao de uma regra. (22.12)
- **A selecao de entrada aceita UM arquivo ou uma pasta.** Nao ha selecao
  multipla (`askopenfilename` no singular) nem arrastar-e-soltar. O worker ja
  aceita lista explicita (`only_files`), entao multiplos e troca de funcao; DnD
  exigiria dependencia nova (`tkinterdnd2`), e a decisao registrada e nao
  acrescenta-la por isto. (22.12)
- **A previa do glossario nao mostra a semente.** Ela responde "o que as MINHAS
  regras fazem com este texto" (S17), e as de fabrica nao estao na lista que o
  editor mostra — explicar um resultado por uma regra que nao esta em lugar
  nenhum da tela seria pior do que a omissao. (22.12)
- **A mensagem de status do editor e cortada em 52 caracteres.** As duas de
  propagacao passam disso e ficam com reticencias. E o que cabe na faixa do
  rodape na largura minima, medido (F20); elas sao recibo de uma acao ja
  confirmada em dialogo (V1), e a contagem que fica mostra o resultado. (22.10)

**Procedencia (de onde cada traducao veio)**

- **As linhas gravadas antes do schema 7 nao tem procedencia**, e nao vao ganhar
  uma por heuristica (O2). Elas aparecem so em "Todos os arquivos", e **nao existe
  um filtro "sem arquivo"**: ele seria um anti-join da tabela inteira por
  interacao, e R5 vale para os filtros novos como vale para os velhos.
- **A obra e identificada pelo CAMINHO do arquivo.** Mover ou renomear a pasta e
  reprocessar cria uma segunda obra no filtro, com o mesmo nome de arquivo e a
  pasta no rotulo para desempatar. E a falha escolhida: identificar pelo nome
  faria `Livro A/cap01.pgn` e `Livro B/cap01.pgn` disputarem as mesmas posicoes, e
  ai uma sobrescreveria a outra em silencio.
- **Uma execucao interrompida no meio de um arquivo encurta a obra.** O conjunto
  de ocorrencias do arquivo e substituido a cada processamento, e um comentario
  sem traducao no banco nao tem para onde apontar: a obra aparece menor ate a
  execucao seguinte, que acha o resto no cache e completa. O log diz quantas
  posicoes ficaram de fora. (ROADMAP 18.3)
- **Importar traducoes por CSV cria linhas sem procedencia**, como as legadas: o
  formato do CSV nao carrega arquivo, partida nem lance. Levar o contexto no CSV
  conversa com a exportacao TMX (ROADMAP 19, item 8).
- **Nao ha como reverter "tudo que a execucao de ontem gravou".** A ocorrencia
  guarda `recorded_at`, entao da para ver QUANDO uma posicao foi lida, mas
  reverter uma execucao e apagar traducoes — e decidir entre o que ela inseriu, o
  que reaproveitou do cache e o que foi revisado a mao depois. O backup continua
  sendo o caminho de volta. (ROADMAP 18.7)
- **A partida e o lance nao vem de um leitor de PGN.** A partida e a contagem de
  tags `Event` antes do comentario, e o lance e o ultimo numero de lance da mesma
  partida. Um arquivo sem `[Event` conta como uma partida so; um com tags fora de
  ordem conta o que estiver escrito. Sao numeros para localizar o comentario na
  obra, e nao uma leitura da posicao — validar lance segue nao-objetivo (secao 1).
- **Nao existe FEN por ocorrencia.** O esquema tem onde pendura-la, e nenhuma
  coluna foi criada para ficar nula: uma coluna que ninguem escreve em 200 mil
  linhas nao e preparo. (ROADMAP 18.1)

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
protegem. Cada uma entra na secao 9 quando o item correspondente do ROADMAP
estiver pronto e tiver teste que falhe sem a correcao.

**Nenhuma pendente.** As nove garantias da revisao de 2026-07-31 — **F12**
(22.1), **Q3** (22.2), **F13** (22.3), **F14** (22.4), **F15** (22.5), **F16**
(22.6), **F17** (22.7), **F18** (22.8) e **F19** (22.9) — migraram para a secao
9 no mesmo dia, com 5, 6, 8, 6, 5, 11, 5, 13 e 10 testes e nove rodadas de
mutacao sem sobrevivente. **F26** (23.1) veio de um relato de uso no dia
seguinte, e pelo mesmo caminho. As onze da segunda metade dela — **F20** (22.10),
**F21** (22.11), **F22**, **F23**, **F24**, **F25**, **S16**, **S17** e **S18**
(22.12), **R11** e **C4** (22.13) — migraram em 2026-08-01, pelo mesmo caminho:
121 testes e 42 mutacoes, seis sobreviventes na primeira passada e nenhuma no
fim. Cinco delas viraram teste novo e **uma virou codigo a menos** — o teto do
divisor de 22.10, que era uma segunda tranca e ainda por cima calculava de uma
largura que podia nao ser a final.

**Duas delas foram declaradas com o enunciado errado aqui, e a implementacao
corrigiu.** F12 falava so em gravar antes de recarregar, e faltava dizer que o
status precisa ir para a linha que estava na tela (o `save_changes` pode trocar
a linha aberta antes de o status ser gravado). F13 falava em acrescentar dois
campos ao retrato, e o problema maior era outro: os campos que ja existiam
guardavam o valor de DEPOIS da mudanca. As duas medicoes que mostraram isso
estao nos itens do ROADMAP; o que fica aqui e a regra que as duas confirmam —
**uma garantia planejada e uma hipotese ate alguem tentar implementa-la.**

As demais garantias — X1-X3 e S11-S15 (secoes 13 a 15), Q1-Q2 (secao 16), R10,
T5 e V1 (secao 17), O1-O4 (secao 18), F1-F11 (secao 19) e D1-D7 (secao 20) —
estao todas na secao 9.

**A secao 20 acabou declarando garantia nova, ao contrario do que estava previsto
aqui.** A previsao era que ela nao declararia nada: sendo custo e nao
comportamento, o mesmo resultado por menos memoria seria protegido pelos testes
que ja existiam. Duas coisas mudaram isso. Primeiro, "o resultado nao muda" **e**
uma afirmacao que precisa de teste quando a implementacao inteira muda — e um
deles achou um bug real (dois comentarios esvaziados lado a lado apagavam o resto
do arquivo). Segundo, custo tem forma observavel: cancelar durante a gravacao, o
numero de leituras do arquivo, o comentario repetido que nao volta para a API, o
indice que se reconstroi quando o fonte muda. D1-D7 sao essas afirmacoes, e duas
delas sao medidas com cronometro e `tracemalloc`, porque em teste de igualdade
"correto e lento" e indistinguivel de "correto e rapido".

**O item 11 da secao 19 (corretor ortografico de prosa) nao foi feito**, e nao
declara garantia planejada: ele depende de escolher um dicionario e uma dependencia
nova, que e decisao de quem mantem o programa e nao um desenho pendente. Esta como
limite na secao 10.

**As garantias do instalador (I1-I4, ROADMAP 21) estao na secao 9**, e duas delas
sao protegidas por um teste que **nao** fica na suite: `pytest` nao tem como
afirmar o que o Inno Setup faz com uma pasta. O que as protege e
`instalador\verificar-ciclo.ps1`, que instala, usa, atualiza por cima e
desinstala com um `.exe` de verdade — e que esta dito na secao 9 ao lado delas,
para ninguem procurar na suite o teste que as sustenta.
