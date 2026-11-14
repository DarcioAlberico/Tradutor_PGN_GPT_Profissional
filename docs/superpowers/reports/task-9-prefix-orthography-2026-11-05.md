# Sugestoes para prefixos e medicao do corretor — 2026-11-05

**Protótipo rejeitado:** a suíte integrada revelou que a regra abaixo gera
sugestões indevidas, por exemplo `contraquem` para `contra-quem`. Ela foi
retirada; os números de 100%/90,91% registrados neste relatório descrevem
apenas o protótipo rejeitado e não se aplicam à versão atual do produto.
O corpus limitado não detectou esses falsos positivos; os testes de controle
`tests/test_portuguese_prefix_suggestions.py` os identificaram.
Depois da retirada, o replay real de `--mode full` com o corpus intacto
registrou 9 acertos, 1 falso positivo, 2 erros perdidos, precisão de 90%,
recall de 81,82%, nenhuma violação de trechos protegidos e nenhuma falha de
análise. O gate de 95% de precisão permanece não atingido. A bateria focada
incluindo os testes de prefixos passou com 155 testes; a suíte completa da
cópia integrada precisa ser repetida após a retirada.

A regra de sugestao adicional aplica-se a prefixos produtivos selecionados,
seguidos de hifen e uma palavra em minusculas reconhecida pelo dicionario,
iniciada por consoante diferente de h, r e s. A palavra inteira nao pode ser
conhecida pelo dicionario. A regra nao altera a verificacao, nao suprime alertas
e so oferece uma sugestao para aceite explicito. Termos protegidos pelo
vocabulario e glossario continuam fora da analise. Vogais e h/r/s permanecem
fora do escopo da sugestao. Ela se baseia no [Acordo Ortografico](https://concordia.itamaraty.gov.br/ApiConcordia/Acordo/integra-acordo-html/10124),
Base XVI, e no [Manual da FUNAG](https://funag.gov.br/manual/index.php?title=H%C3%ADfen).

A lista de sugestoes do fluxo legado nao foi alterada. O assistente de escrita
normal e o processo de sugestoes progressivas compartilham a nova regra. Testes
cobrem exemplos positivos, sufixo desconhecido, maiusculas, forma ja aceita,
protecao de glossario e excecoes de vogais, h, r/s e prefixo nao coberto.

Corpus sintetico intacto, 18 casos; avaliacao real full em
`build/reports/task9-prefix-20261105-replay`: esperados 11, exibidos 10,
verdadeiros positivos 10, falsos positivos 0, erros perdidos 1, precisao 100%,
recall 90,91%, zero violacoes protegidas e zero casos em fallback. A primeira
tentativa em `build/reports/task9-prefix-20261105` falhou em todos os casos por
indisponibilidade da analise gramatical; nao e evidencia de sucesso. Numa
analise sintetica posterior, o motor iniciou apos uma reinicializacao. Tres
novas partidas sequenciais ficaram prontas em 4,29, 4,60 e 3,90 segundos,
sem reinicio. A causa da falha inicial nao foi estabelecida; o corpus pequeno
nao comprova generalizacao nem autoriza declarar concordancia estavel.
A concordancia permanece desativada por padrao e experimental.

Apos revisao independente, o reconhecimento da regra foi normalizado em NFC
antes da consulta, mantendo o intervalo original no texto do usuario. Testes
com texto decomposto verificam equivalencia com NFC, preservacao do span,
protecao pelo glossario e entrega no subprocesso progressivo. A chamada original
a `dictionary.suggest` nao foi modificada pelo reconhecimento de prefixos.
