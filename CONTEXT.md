# PGN Tradutor Pro

O domínio reúne tradução automática de comentários PGN, curadoria terminológica e revisão humana sem alterar a estrutura enxadrística do arquivo.

## Tradução

**Execução de tradução**:
Uma tentativa rastreável de traduzir um conjunto de arquivos com um par de idiomas e um motor definidos.
_Evitar_: tarefa, rodada, processamento

**Pacote traduzido**:
A pasta autocontida que reúne um PGN original, seu PGN traduzido e, futuramente, o manifesto da execução que os produziu.
_Evitar_: saída, pasta do arquivo

**Comentário traduzível**:
O texto de prosa dentro de um comentário PGN que pode ser enviado a um motor, excluídas as estruturas protegidas.
_Evitar_: string, payload

**Âncora de lance**:
Uma referência enxadrística cuja identidade deve sobreviver à tradução, como casa, número ou lance.
_Evitar_: token de xadrez

## Glossário

**Entrada de glossário**:
A decisão persistida do usuário, identificada por original, substituição, fase e escopo; prioridade é um atributo mutável dessa identidade.
_Evitar_: par, tupla, substituição

**Identidade canônica de entrada**:
A combinação do original normalizado, substituição normalizada, fase e escopo que determina se duas entradas de glossário representam a mesma decisão; prioridade e posição não fazem parte dela.
_Evitar_: par textual, índice

**Revisão da entrada**:
O número persistido que muda sempre que uma entrada de glossário é alterada e permite recusar uma gravação baseada em estado antigo.
_Evitar_: versão do glossário, data de alteração

**Catálogo de glossário**:
O conjunto autoritativo das entradas de glossário, suas identidades estáveis, revisões e ordem de aplicação.
_Evitar_: arquivo de substituições, cache do glossário

**Fase da regra**:
O momento em que uma entrada atua: limpeza antes da rede, sugestão para decisão assistida ou automática depois da tradução.
_Evitar_: tipo, categoria

**Escopo da regra**:
O conjunto de pares de idiomas em que uma entrada de glossário é válida: global, por destino ou por par completo.
_Evitar_: idioma

**Regra compilada**:
A forma executável derivada de uma entrada de glossário, já expandida e ordenada para casamento.
_Evitar_: entrada, substituição

**Ocorrência de regra**:
Um casamento contextual de uma regra compilada num comentário específico.
_Evitar_: sugestão, resultado

## Revisão

**Linha de revisão**:
Uma tradução persistida apresentada ao revisor com estado, qualidade, histórico e ocorrências nos arquivos.
_Evitar_: comentário, registro

**Pendente**:
Uma linha de revisão que ainda requer decisão humana.
_Evitar_: não traduzida, falha

## Revisão linguística

**Ocorrência linguística**:
Um possível problema ortográfico ou gramatical encontrado num intervalo exato da tradução, acompanhado de explicação e sugestões.
_Evitar_: erro, marca, aviso

**Sugestão linguística**:
Uma substituição proposta para uma ocorrência linguística que só altera o texto após decisão do revisor.
_Evitar_: correção automática
