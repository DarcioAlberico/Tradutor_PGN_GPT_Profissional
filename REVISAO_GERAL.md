# Revisão Geral — PGN Tradutor Pro

Data da revisão: 23 de outubro de 2026
Estado: proposta consolidada; nenhuma ação abaixo deve ser considerada implementada sem teste e medição.
Escopo: aplicação, pipeline, Google e LLMs, glossário, banco, interface, ícones, produtividade, empacotamento, testes e operação.

## 1. Resumo executivo

O PGN Tradutor Pro já não é um protótipo. Ele tem um domínio rico, cuidados incomuns com integridade de PGN, cache por par de idiomas, revisão profissional, histórico, rollback de execução, glossário com escopo, instalador e uma suíte de 1.809 testes coletados. O ROADMAP original registra medições e decisões com qualidade acima da média.

O risco agora mudou de natureza: não é falta de funcionalidades básicas, e sim crescimento sem uma arquitetura proporcional. Quatro arquivos concentram 15.797 linhas (`edit_window.py`, `database.py`, `glossario.py` e `glossary_editor.py`), e `run_translation` concentra quase todo o pipeline em uma função iniciada em `translation_worker.py:230`. Isso aumenta o custo de cada mudança, dificulta testes na interface correta e torna o conhecimento dependente de comentários extensos.

### Veredito

| Área | Estado | Principal decisão |
|---|---|---|
| Correção do PGN | forte | preservar as garantias existentes e adicionar corpus dourado |
| Qualidade de tradução | forte com LLM; desigual no Google | medir aceitação humana por motor e par de idiomas |
| Google gratuito | risco alto | retirar `google-gtx` da posição de padrão seguro |
| Glossário | poderoso, porém difícil de operar | transformar em módulo profundo e fluxo de curadoria |
| Desempenho | bom nos caminhos já medidos | criar benchmarks permanentes e orçamento de regressão |
| Interface | funcional, densa e textual | redesenhar por tarefas, com navegação e comandos consistentes |
| Acessibilidade | parcial e pouco verificada | auditoria de teclado, foco, escala e leitor de tela |
| Engenharia | muitos testes, módulos grandes | modularizar por interfaces de domínio, não por helpers |
| CI/release | boa base, guardas vencidas | tornar GUI e tipos bloqueantes; testar o artefato instalado |
| Segurança/privacidade | razoável no Windows | consentimento de envio, política de dados e segredos fora do Windows |

### Prioridades imediatas

**Revisão em 06/11/2026:** a lista abaixo preserva a ordem do diagnóstico
original. A cópia integrada já possui a publicação transacional e o CI do PR #7
passou com verificações bloqueantes; esses resultados não comprovam o instalador
nem a recuperação integral dos dados. O próximo trabalho operacional é RG-003:
verificação somente de leitura e ensaio de restauração em diretório temporário.
Para RG-036, permanecem a precisão mínima, a estabilidade e a auditoria de
distribuição do LanguageTool.

1. **P0 — glossário:** corrigir a deduplicação que pode apagar entradas legítimas de outra fase ou escopo e a identidade ambígua usada para atualizar/excluir.
2. **P0 — saída:** tornar a publicação do PGN e do pacote traduzido atômica; hoje um crash pode deixar um PGN parcial com aparência de saída válida.
3. **P0 — Google:** não tratar `google-gtx` como serviço estável ou autorizado; oferecer API oficial e modo experimental explicitamente identificado.
4. **P0 — CI:** remover os `continue-on-error` cuja validade terminou em 30/09/2026 e investigar qualquer flake antes de bloquear merge.
5. **P0 — dados:** testar restauração real e consistência de `traducoes.db`, glossário, configurações e nova pasta `Minhas Traduções`.
6. **P1 — arquitetura:** extrair um módulo profundo `TranslationJob` do worker e um módulo profundo `GlossaryCatalog` da dupla arquivo/SQLite/editor.
7. **P1 — produto:** reconstruir a janela principal como centro de trabalho, com foco em “selecionar → estimar → traduzir → revisar → exportar”.
8. **P1 — português:** ampliar o Hunspell existente para um assistente local que ofereça correções ortográficas e concordâncias explicáveis, sem alteração automática.

## 2. Método e evidências

Esta revisão combinou:

- leitura de `README.md`, `SPEC.md`, `ROADMAP.md`, código de produção, testes, build e instalador;
- inventário de módulos e tamanho dos arquivos;
- coleta da suíte: **1.809 testes**;
- execução do `mypy`: sucesso nos oito módulos atualmente incluídos;
- leitura e medição do glossário real: **6.071 entradas**, sendo 5.622 sugestões, 399 automáticas e 50 de limpeza; carga do texto em ~0,085 s e análise de conflitos em ~0,015 s nesta máquina;
- pesquisa do Google em fontes primárias, registrada em [docs/PESQUISA_RISCO_GOOGLE.md](docs/PESQUISA_RISCO_GOOGLE.md);
- revisão crítica adversarial independente. Não foi usado Claude nesta sessão; nenhuma conclusão é atribuída a ele;
- princípios de módulos profundos: interface pequena, complexidade encapsulada, testes na mesma interface usada pelos chamadores.

As medições de tempo acima são fotografia desta máquina, não orçamento universal. Devem virar benchmarks repetíveis antes de orientar otimizações adicionais.

## 3. Consolidação do roadmap anterior

O `ROADMAP.md` atual é valioso como diário técnico, mas já passou de 9.500 linhas e mistura história, diagnóstico, solução, medição e estado. Esta revisão passa a ser o índice executivo. O documento antigo permanece como registro de decisões.

### O que já está consolidado e deve ser preservado

- higiene, backup, conflitos, escopo e cache SQLite do glossário;
- paginação, índices, WAL, menor uso de memória e escrita linear do PGN;
- isolamento de testes e ampla cobertura de janelas reais;
- retry, jitter, ritmo adaptativo, disjuntor e reprocessamento de falhas;
- origem e destino na chave do cache;
- preservação de lances, NAGs, anotações `[%...]`, nomes e codificação;
- contexto de ocorrência, FEN opcional, QA, histórico e estados de revisão;
- fluxo profissional com atalhos, busca, fila de avisos, rascunho e propagação;
- Google, Claude, OpenAI e DeepSeek como motores selecionáveis;
- portão de âncoras, custo estimado, saída estruturada e contexto de lances para LLMs;
- dados fora do executável instalado, versão portátil e instalador com proteção contra downgrade;
- builds reproduzíveis a partir do `uv.lock` e artefato `onedir`.

### Pendências antigas que continuam válidas

- a leitura cega do piloto de LLM ainda é a métrica humana que decide qualidade real;
- assinatura de código do executável continua pendente;
- cobertura do `mypy` alcança somente oito módulos;
- testes de janela e tipos continuam não bloqueantes no CI, apesar do prazo documentado ter expirado;
- os limites conhecidos da SPEC precisam virar backlog com dono, critério e data, em vez de permanecerem como narrativa;
- a nova organização de `Minhas Traduções` ainda não tem retenção, busca, índice, limpeza nem migração documentada.

## 4. Riscos P0

### RG-000 — deduplicação do glossário pode apagar entradas válidas

**Atualização V2 (24/10/2026):** RG-000, GL-001 e GL-002 implementados nos
commits de `6cbc5c7` a `e296589`, com identidade canônica completa,
`stable_id`/`revision` por entrada e `catalog_revision` nas operações em lote.
O editor salva/exclui por ID e revisão e apresenta comparação em conflito.
Deduplicação preserva variantes de fase/escopo; ações bulk sem transação
atômica continuam desabilitadas. O diagnóstico abaixo registra a situação
anterior à migração; os resultados da validação integrada estão no ROADMAP,
seção 30. Esta entrega não conclui o corretor de português nem os demais marcos.

**Aceitação integrada pendente:** o gate focado passou (938 testes, 1 skip,
6.467 subtestes), assim como Ruff e mypy. A suíte integral teve 2 falhas GUI
(log e alocação de menus Tk); as duas classes passaram juntas em processo
novo (17 testes). O ROADMAP, seção 30.1, registra comandos e resultados.
Não considerar a suíte verde nem concluir a aceitação global por esse recorte.

**Confirmado por execução:** três entradas com o mesmo original/substituição — `suggestion/pt`, `suggestion/it` e `cleanup/pt` — são reduzidas somente à primeira por `deduplicate_glossary_entries` (`glossario.py:1453`). A inserção, corretamente, considera `(original, substituição, fase, escopo)` e ignora apenas prioridade (`glossario.py:1498`), mas a deduplicação e os diagnósticos da UI usam apenas o par textual. O botão de exclusão em massa pode, portanto, destruir decisões semanticamente diferentes.

Há uma segunda inconsistência: a linha-base do formulário e `find_glossary_entry_index` omitem escopo. Após alteração externa que desloque o índice, atualizar ou excluir pode atingir a variante de outro escopo.

**Correção imediata:**

1. definir a identidade canônica da **entrada de glossário** como `(original normalizado, substituição normalizada, fase, escopo)`;
2. fazer deduplicação, diagnóstico, localização, update, delete, importação e UI usarem a mesma identidade;
3. recusar operação ambígua, nunca “escolher a primeira”;
4. adicionar `id` e `revision` estáveis no modelo persistente; até a migração, usar hash/revisão do arquivo e identidade completa;
5. desabilitar temporariamente “Deduplicar/Excluir duplicadas” se a correção não puder entrar imediatamente;
6. criar regressões cruzando fase × escopo × prioridade e concorrência externa.

**Aceite:** nenhuma combinação legítima de fase/escopo é removida; alteração externa causa conflito explícito; undo/backup identifica exatamente o que mudou.

### RG-000B — publicação do PGN não é atômica

**Progresso (13/11/2026):** a geração escreve em temporário exclusivo no
mesmo diretório e só substitui o PGN de destino após concluir a gravação;
falhas preservam o arquivo anterior e removem o temporário da tentativa. A
publicação de pacotes já prepara original, tradução e manifesto em diretório
temporário antes de publicá-los. Recuperação de temporários após encerramento
abrupto e garantias de durabilidade após queda de energia continuam pendentes.
Ao cancelar durante a publicação, a cópia do original e a verificação de hash
do traduzido são interrompidas entre blocos; o pacote parcial é descartado.
Uma leitura ou gravação de sistema já iniciada pode precisar terminar primeiro.
A escrita do PGN e as verificações do hash de origem antes e depois da tradução
também observam o cancelamento. O destino anterior é preservado quando a escrita
é interrompida antes da troca atômica.

**Inspeção de temporários:** a Biblioteca lista, sem acessar o conteúdo ou
remover arquivos, pastas de preparação com pelo menos 24 horas. A idade não
prova que uma tradução foi abandonada; o relatório alerta sobre trabalhos ainda
ativos e limita os exemplos. Recuperação ou limpeza automática permanecem
pendentes.
O relatório também informa quantas pastas reconhecidas são recentes e quantas
possuem data futura; essas contagens não provam se estão em uso.

`write_pgn_pieces` abre e trunca diretamente o caminho final (`pgn_utils.py:912-937`). Crash, disco cheio ou erro pode deixar um arquivo parcial; a execução seguinte vê o nome ocupado e cria `-2`. No pacote novo, a pasta nasce antes, enquanto a cópia do original ocorre apenas após a geração.

**Plano:** escrever no mesmo volume como `.tmp`, concluir/fechar, opcionalmente `flush` + `fsync`, validar tamanho/estrutura mínima e publicar com `os.replace`. Copiar o original por temporário, gravar manifesto por último e remover pacote incompleto ou marcá-lo explicitamente como incompleto.

**Aceite:** falha injetada em cada etapa nunca deixa um arquivo final parcial; reinício limpa/recupera temporários com segurança.

### RG-001 — `google-gtx` é um endpoint não documentado

**Avanço em 07/11/2026:** o adaptador `google-gtx` respeita `Retry-After`
em segundos ou data HTTP nas respostas de erro temporário e mantém a espera
entre comentários da mesma execução. A espera pode ser cancelada. Se o servidor
pedir mais de uma hora, novas chamadas com o mesmo controlador são interrompidas,
sem tentar antes do prazo. A regra do cabeçalho segue a [RFC 9110, seção
10.2.3](https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3).
O adaptador
`deep-translator` também passou a observar `Retry-After` nas respostas 429 e
503, sem alterar o parser da biblioteca; a espera vale para chamadas seguintes
do mesmo adaptador ou controlador e pode ser cancelada. O worker usa esses
objetos sequencialmente; eles não são seguros para chamadas simultâneas.

**Cooldown compartilhado:** processos que usam a mesma pasta de dados consultam
`google-cooldown.db` antes de chamar os dois adaptadores Google. HTTP 429 impõe
pelo menos 30 segundos, HTTP 403 pelo menos cinco minutos e HTTP 503 segue
`Retry-After` quando presente. O prazo maior prevalece e continua após reinício;
a espera pode ser cancelada. Dados do comentário, caminhos e chaves não entram
nesse arquivo. Falha ao consultar ou gravar bloqueia chamadas na execução que a
encontrou. Se uma gravação falhar, outra instância ainda pode ler o prazo antigo;
requisições já em voo não são interrompidas. Pastas de dados diferentes não
compartilham a proteção.

**Cotas compartilhadas:** o mesmo banco reserva cada tentativa atomicamente em
janelas móveis de um minuto e 24 horas. Os padrões são 60 e 3.000 tentativas;
os limites podem ser alterados em Configurações. Testes usam processos
independentes, inclusive chamadas internas do `deep-translator`. Mudanças
relevantes no relógio ou reinícios preservam as reservas de forma conservadora
e podem prolongar a espera. Cada reserva ocorre antes do envio; se o processo
for suspenso depois da reserva, o horário efetivo da requisição pode diferir.
Instâncias antigas não respeitam essas cotas.
**Estimativa inicial:** após consultar o cache e antes do envio, o registro mostra
comentários distintos, caracteres de comentários sem separadores, lotes iniciais
e limites configurados. A estimativa supõe sucesso e reutilização entre arquivos;
divisões, falhas e novas tentativas podem aumentar as requisições. Não estima
tempo, cotas já consumidas nem custos.
**Métricas locais:** ao terminar uma execução Google, inclusive quando
interrompida, o registro apresenta tentativas HTTP, caracteres nas tentativas,
respostas 403 e 429 e tempo total da consulta/espera compartilhada. Tentativas
incluem erros de rede e reenvios. As pausas são separadas em cota, cooldown e
ambos simultaneamente, conforme o motivo observado antes de cada pausa de até
um segundo; a consulta à base permanece apenas no total. Os contadores são
apenas dessa execução, sem armazenar os textos ou enviar telemetria.
Ainda falta a API oficial.

**Consentimento dos motores não oficiais:** o seletor identifica `gtx` e
`deep-translator` como experimentais. Antes do primeiro uso de cada motor, o
programa explica o envio dos comentários e idiomas e solicita aceitação. A
aceitação é versionada e guardada separadamente para cada motor em
`provider-consent.db`; recusa ou falha de leitura/gravação impede a tradução.
Se um motor lembrado não estiver disponível, o diálogo pede uma escolha em vez
de trocar para o Google. Políticas e consentimentos dos demais provedores ainda
fazem parte do RG-050.

**Evidência local:** `translation_api.py:192` chama `https://translate.googleapis.com/translate_a/single` com `client=gtx`, sem chave, projeto ou contrato. O código já o descreve como público e não oficial.

**Risco:** bloqueio temporário por IP, 403/429, mudança de formato ou retirada sem aviso. Como não há autenticação de conta Google, “ban da conta” não é a descrição tecnicamente sustentada; o risco imediato é IP/endpoint. Pelos termos oficiais pesquisados, o uso de APIs não documentadas sem permissão é incompatível com uma base de produto confiável. Ver a análise e as fontes em [PESQUISA_RISCO_GOOGLE.md](docs/PESQUISA_RISCO_GOOGLE.md).

**Diagnóstico original:** antes das alterações acima, o intervalo base permitia,
teoricamente, 500–1.500 requisições por minuto, sem cota compartilhada,
tratamento de `Retry-After`, cooldown persistente ou limite diário.

**Plano:**

1. adicionar adaptador oficial Google Cloud Translation v3 (v2 apenas se houver razão de custo/implantação documentada);
2. renomear o motor atual para “Google experimental (não oficial)” e nunca escolhê-lo silenciosamente;
3. exigir confirmação informada na primeira utilização;
4. respeitar `Retry-After`, tratar 403/429 como sinal de cooldown, persistir o cooldown e compartilhar ritmo entre instâncias;
5. incluir limite configurável por minuto/dia e estimativa antes da execução;
6. permitir desabilitar completamente o motor no build distribuído;
7. medir `requisições`, `caracteres`, `429`, `403`, tentativas e tempo em cooldown, sem registrar conteúdo.

**Aceite:** uma simulação com duas instâncias não ultrapassa a cota configurada; `Retry-After` é honrado; o motor experimental nunca é selecionado sem consentimento; falha do endpoint não perde dados nem gera tempestade de rede.

### RG-002 — CI tem guardas vencidas e não bloqueantes

**Atualização de 06/11/2026:** na branch do PR #7, Ruff, mypy e testes de janela
são bloqueantes. A execução 42128412406 passou: 1.982 testes sem interface e
666 testes de janela, além dos subtestes. A branch ainda está em revisão e a
publicação autocontida não foi validada; o diagnóstico abaixo é histórico.

**Evidência:** `.github/workflows/testes.yml` ainda mantém `mypy` e a suíte de janelas com `continue-on-error: true`, acompanhado de comentário “até 2026-09-30”. A revisão ocorre em 23/10/2026.

**Risco:** uma regressão real de UI ou tipos pode entrar em `main` com pipeline verde.

**Plano:** remover a exceção após uma janela curta de estabilização; publicar JUnit e screenshots em falhas; repetir somente testes declaradamente flaky e registrar taxa de flake; impedir build se a suíte obrigatória falhar.

**Aceite:** nenhuma etapa funcional crítica é não bloqueante; flake conhecido tem issue, telemetria de frequência e prazo.

### RG-003 — recuperação é testada por peças, não como desastre completo

**Inventário (17/11/2026):** a verificação separa backups de traduções e de
glossário, limita a 20 os nomes candidatos exibidos e informa os omitidos. O
relatório distingue pastas ausentes, vazias e listagens incompletas; resume os
estados dos pacotes pela leitura de metadados da Biblioteca sem mostrar nomes e
descarta a contagem se a pasta mudar durante a varredura. Essa leitura não
compara os hashes dos PGNs nem garante que backups possam ser restaurados.

**Avanço (13/11/2026):** a verificação aceita configurações UTF-8 com BOM e
relata JSON excessivamente aninhado como inválido; a leitura tolerante e a
recuperação das configurações também lidam com esse caso. Backups de arquivos
corrompidos preservam versões anteriores quando ocorrem no mesmo segundo.

**Risco identificado na revisão de 07/11/2026:** a gravação geral das
configurações usa bloqueio limitado ao processo e um temporário com nome fixo.
Duas instâncias podem disputar a gravação; o novo banco de consentimento usa
transações próprias, mas não corrige as demais configurações. Investigar com
reprodução entre processos e proteger o ciclo de leitura e gravação completo.

**Correção:** a disputa foi reproduzida com dois processos e arquivos temporários.
As atualizações pela interface `update_settings` agora usam bloqueio entre
processos durante toda a leitura, alteração e publicação. Há testes para
concorrência, timeout, falha de acesso e encerramento inesperado. O arquivo
lateral `.lock` deve permanecer no lugar enquanto houver instâncias abertas.
Versões antigas do programa e gravações diretas de snapshots por `save_settings`
não participam desse protocolo e não devem gravar simultaneamente o mesmo acervo.

**Implementação em 06/11/2026:** o botão **Verificar meus dados** examina
cópias temporárias dos bancos, valida o catálogo V2, verifica configurações e
apresenta candidatos de backup e contagem de PGNs sem expor seu conteúdo. Um
WAL não vazio impede classificar o banco como verificado. O [roteiro de
recuperação](docs/RECUPERACAO_DADOS.md) explica como copiar e testar o acervo,
incluindo chaves protegidas em outra conta. Um ensaio automatizado usa uma pasta
temporária e exercita banco, glossário, configurações e pacote de tradução.
Ainda falta ensaiar o instalador em ambiente isolado; não se deve interpretar
os candidatos listados como garantia de restauração completa.
Validação focada: 219 testes e 44 subtestes passaram, com um teste pulado;
Ruff passou. O roteiro existente de instalação não foi executado porque esta
máquina já possui instalação e dados, e ele poderia afetá-los.
**Segurança do ensaio (07/11/2026):** o roteiro agora recusa instalação ou
registro existentes e a variável `PGN_TRADUTOR_DATA`, encerra apenas o processo
que iniciou e preserva os dados de teste. Quatro testes verificam essas guardas;
isso não substitui o ciclo real em uma máquina isolada nem a aprovação do pacote.

Backups e restaurações têm bons testes, mas o cenário que importa é operacional: máquina nova, banco grande, glossário curado, configurações, chaves ilegíveis por DPAPI e pacotes em `Minhas Traduções`.

**Plano:** criar comando/roteiro “Verificar meus dados” que faça `PRAGMA integrity_check`, valide o glossário, liste backups restauráveis e gere um relatório sem conteúdo sensível. Criar teste de recuperação em diretório temporário e ensaio do instalador.

**Aceite:** restauração documentada e testada a partir de uma cópia da pasta de dados; nenhuma ação de verificação modifica o acervo.

## 5. Arquitetura e manutenção

### RG-010 — extrair o módulo profundo `TranslationJob`

`run_translation` começa em `translation_worker.py:230` e coordena descoberta de arquivos, estimativa, banco, glossário, rede, retries, QA, geração, cópia, UI, logs e encerramento. A interface real inclui dezenas de atributos implícitos de `app`.

Interface proposta:

```python
result = TranslationJob(plan, repository, provider, output_store).run(events, cancel)
```

- `TranslationPlan`: origem, par de idiomas, motor/modelo, arquivos, opções e política de saída;
- `TranslationResult`: estado, contagens, arquivos, custo e falhas tipadas;
- `events`: progresso estruturado, convertido em texto somente pela UI;
- `provider`: seam externa real, com adaptadores Google oficial, Google experimental, Anthropic e OpenAI-compatible;
- `repository`: transações e cache;
- `output_store`: cria o pacote original/traduzido e seu manifesto.

O módulo deve esconder batching, máscara, âncoras, retry, fallback e commits. A UI aprende uma interface pequena. Testes novos atravessam essa interface; testes internos redundantes são removidos gradualmente.

### RG-011 — parar de usar `app` como contêiner implícito

`app_actions.py`, worker e janelas dependem de atributos dinâmicos de `PGNTranslatorApp`. Isso é uma interface larga e não declarada. Introduzir dataclasses para estado de sessão e protocolos somente onde já existem dois adaptadores reais.

**Aceite:** o worker não importa Tk nem recebe `app`; progresso e confirmações cruzam interfaces explícitas.

### RG-012 — dividir por domínio, não por tamanho

Não extrair helpers arbitrários para “reduzir linhas”. Os cortes recomendados são:

- `translation_job`: orquestração e estados;
- `translation_pipeline`: transformação pura de cada comentário;
- `translation_providers`: seam externa e políticas de retry/cota;
- `output_packages`: nomes, manifestos, cópia atômica e retenção;
- `glossary_catalog`: consulta e mutação transacional;
- `glossary_engine`: casamento, precedência, simulação e aplicação;
- `review_queue`: consulta e navegação do trabalho humano;
- `ui_presenters`: estado de tela e comandos, sem SQL.

Cada módulo precisa passar no teste de deleção: removê-lo deve fazer a complexidade reaparecer em vários chamadores.

### RG-013 — tipos e lint como prevenção, não decoração

O `mypy` passa, mas só cobre oito módulos. Expandir primeiro para `translation_worker`, `glossario`, `pgn_utils`, `app_actions` e estados dos editores. Ativar regras Ruff de bugs e segurança de modo incremental (`B`, `SIM`, `UP`, `S` com justificativas), sem despejar centenas de avisos sem triagem.

### RG-014 — dependências coerentes nos dois modos de instalação

**Atualização de 07/11/2026:** os dois arquivos de dependências usam
`requests>=2.33.1` e `chardet>=5.2,<8`, faixa compatível com a [verificação
de compatibilidade do Requests 2.33.1](https://github.com/psf/requests/blob/v2.33.1/src/requests/__init__.py).
O lock existente foi validado sem atualizar as versões já resolvidas. Em um
ambiente `pip` novo, a instalação, `pip check` e os imports passaram com
Requests 2.34.2/Chardet 7.7.0 e também com a versão mínima de Requests
2.33.1/Chardet 7.4.3. O CI recebeu a etapa de instalação limpa; sua execução
remota ainda precisa ser confirmada depois da integração ao repositório.

O ambiente global desta auditoria emitiu `RequestsDependencyWarning`: `requests 2.32.5` com `chardet 7.4.3`. O ambiente do `uv.lock` resolve outra versão de `requests`, mas `requirements.txt` e os limites abertos permitem combinações não suportadas.

**Plano:** gerar `requirements.txt` do lock ou eliminá-lo como fonte manual; adicionar smoke test via `pip` em ambiente limpo; fixar/faixar `chardet` conforme compatibilidade documentada; executar `pip check` e import do app.

## 6. Glossário — foco principal

### Diagnóstico

O glossário é um diferencial do produto, não uma preferência. Ele combina três semânticas distintas:

- **limpeza:** altera o original antes da rede;
- **sugestão:** auxilia a decisão humana e o prompt;
- **automática:** impõe uma decisão após a tradução.

Hoje essas regras vivem em `Substituicoes.txt`, são materializadas em `glossario.db` e mantidas como listas/dicionários em vários fluxos. O desenho protege portabilidade e edição manual, mas expõe duas fontes de verdade aparentes e obriga o usuário a compreender tipo, prioridade, escopo e conflito sem uma visão de impacto completa.

### RG-020 — criar `GlossaryCatalog`

**Recorte entregue em V2 (24/10/2026):** persistência, identidade, migração,
concorrência otimista, importação append com prévia e backup/restauração
validada estão encapsulados em `GlossaryCatalog`. `glossario-v2.db` é a
autoridade; `Substituicoes.txt` é espelho/importação explícita e
`default_scope` é metadado persistente. Falhas de espelho ficam visíveis como
`mirror_pending`, sem desfazer a transação confirmada; divergência externa
exige reconciliação explícita. Recuperação está documentada no README.
Busca/simulação/explicação completas e `GlossaryEngine` seguem no backlog;
a interface proposta abaixo não deve ser tomada como toda implementada.

Interface proposta:

```python
catalog.search(query)
catalog.validate(draft)
catalog.simulate(draft, corpus)
catalog.commit(change, expected_version)
catalog.export(format)
```

O catálogo encapsula arquivo, cache SQLite, versionamento otimista, backup e eventos de mudança. O editor deixa de recarregar e remontar listas por conhecimento próprio. `Substituicoes.txt` pode continuar como formato portátil/exportável, mas uma única camada decide sincronização e conflito.

O vocabulário canônico foi registrado em `CONTEXT.md`: entrada persistida, fase, escopo, regra compilada e ocorrência são conceitos diferentes. Isso evita continuar usando “tupla/regra/substituição” para objetos com identidades distintas.

### RG-021 — criar `GlossaryEngine`

**Progresso (13/11/2026):** a aplicação existente pode registrar as
substituições efetivas; `glossary_engine` retorna resultado e ocorrências
estruturadas, com padrão, prioridade, trecho casado e substituição. A prévia
de todas as regras mostra contagem e permite consultar as regras aplicadas. A
análise detalhada identifica candidatas no texto original bloqueadas por
sobreposição, mostra alternativas e trechos aplicados e aponta prioridade,
especificidade ou ordem como critério; a
lista é limitada e não explica outras causas de ausência. Seguem pendentes uma
explicação completa de todas as decisões e medições em corpus reais.

**Simulação comparativa:** o motor compara conjuntos de regras automáticas com
prioridade e escopo por par de idiomas. No editor, **Comparar edição** usa o
texto de teste e **Comparar pendentes** lê o banco sem escrita, em segundo
plano, limitando exemplos e permitindo cancelar. A comparação reaplica as
regras do catálogo aos textos existentes; não inclui a semente nem a fase de
limpeza e não prevê a tradução de textos futuros.

**Detalhes do impacto (17/11/2026):** a comparação de pendências informa a
proporção afetada, os totais por par de idiomas e quantos exemplos ficaram fora
do limite de exibição. A mensagem distingue ausência de pendências de resultado
sem alterações. Para regras não automáticas, explica que uma mudança pode
retirar uma regra do conjunto automático. Os totais descrevem apenas a amostra
consultada; a comparação completa do painel de impacto permanece pendente.

O cancelamento também é conferido periodicamente durante a aplicação das
regras a cada comentário. Uma busca de padrão já iniciada pode precisar terminar
antes da interrupção; resultados parciais continuam descartados.

Casamento, fronteira de palavra, `@casa@`, caixa, especificidade, prioridade, escopo e ordem formam um único domínio. A interface deve responder:

- quais regras casaram;
- qual venceu e por quê;
- quais foram ocultadas;
- qual texto resulta;
- quanto custa aplicar ao corpus.

Isso permite que worker, preview, QA, importação e editor usem exatamente a mesma decisão. A explicação deve ser um objeto estruturado, não uma string montada para uma tela.

### RG-022 — caixa de entrada de curadoria

**Progresso (13/11/2026):** a janela de trocas repetidas permite criar uma
sugestão no catálogo para o par de idiomas, sem alterar traduções; conflitos
concorrentes e duplicatas são informados. A lista tem busca sem acento e
filtro para trocas sem regra correspondente e ordenação por frequência,
quantidade de comentários ou texto. A paginação permite acessar
todos os candidatos mantendo até 40 linhas renderizadas por página. Continua sendo uma visão das
edições de uma obra, não uma caixa de entrada persistente para todas as fontes.

A curadoria oferece ordenação pelas trocas menos frequentes ou presentes em
menos comentários, além das ordens anteriores. É possível limpar os filtros
sem alterar a ordenação e navegar por páginas com `Alt+←`, `Alt+→`,
`Alt+Home` e `Alt+End`; `Ctrl+L` limpa a busca e os filtros da lista.
`Alt+↑` e `Alt+↓` selecionam a troca anterior ou seguinte, inclusive entre páginas.
`Ctrl+Shift+C` copia a troca selecionada.
O filtro **Somente ignoradas** restringe a lista às decisões ignoradas e pode
ser combinado com a busca e com o filtro de regras ainda não correspondentes.
A busca também reconhece o tipo de regra exibido. A faceta de frequência
oferece limites mínimos de 5, 10 ou 20 ocorrências.

**Ignorar e restaurar:** uma troca pode ser ignorada por obra e par de idiomas,
ocultada da lista e restaurada individualmente ou para os candidatos da lista.
A restauração em lote respeita busca, filtro de regra e frequência em todas as
páginas; a opção de exibição de ignoradas não altera esse conjunto.
A criação de regra confere novamente a decisão antes de gravar. A decisão é persistida como identificador
derivado, sem gravar os textos ou caminhos em claro; não altera regras nem
traduções. Mover a obra altera sua identificação e não transfere a decisão.
A conferência final e a gravação da regra compartilham o bloqueio usado para
ignorar ou restaurar candidatos, evitando uma corrida entre essas ações.
A lista completa de fontes e as demais ações de curadoria seguem
pendentes.

**Exemplos de curadoria (17/11/2026):** a contagem de comentários distintos
agora deduplica o identificador ao longo de todas as edições, preservando a
contagem de ocorrências. Cada troca oferece até cinco comentários distintos;
é possível escolher um, abrir a linha atual no editor ou consultar e copiar o
antes/depois da primeira edição histórica registrada para aquela troca e
comentário. O relatório indica truncamento e esclarece que a tradução atual
pode ter mudado. A consulta não altera histórico, traduções ou regras.

Adicionar uma fila “Sugestões para o glossário” produzida por:

- edições humanas repetidas;
- diferenças recorrentes entre motor e versão aceita;
- termos desconhecidos pelo corretor;
- sugestões do modelo, sempre marcadas como não confiáveis;
- importações pendentes.

Cada candidato mostra frequência, arquivos/pares afetados, exemplos antes/depois e colisões. Ações: aceitar como sugestão, promover para automática após simulação, ignorar, mesclar ou adiar.

### RG-023 — revisão em lote e facetas

**Progresso (13/11/2026):** o editor oferece filtros persistentes por tipo e
escopo global, específico ou compatível com o par atual,
combinado com busca e filtros de diagnóstico. A busca aceita acentos opcionais,
palavras em qualquer ordem e termos em original, substituição, tipo e escopo.
A lista também pode ser ordenada por prioridade crescente ou decrescente,
preservando a ordem do catálogo em empates. É possível limpar os filtros sem
descartar o rascunho; quando a entrada selecionada deixa de aparecer, a tela
indica que ela está fora do filtro. As demais facetas e operações em lote
continuam pendentes.

O filtro de prioridade distingue valores positivos, zero e negativos e pode
ser combinado com tipo e escopo. A escolha é lembrada pelo editor e pode ser
limpa sem descartar o rascunho.
A busca sem filtro de diagnóstico evita calcular avisos por entrada; os filtros
de duplicatas, conflitos e entradas inválidas continuam consultando os avisos.

O editor atual tem busca, filtros, ordenação, paginação e diagnóstico, mas a lista de 6.071 regras pede facetas persistentes:

- tipo, idioma/par, origem da regra, alterada recentemente, nunca acionada, frequência, conflito, cobertura e risco;
- seleção múltipla com mudança de escopo/tipo/prioridade;
- comparação lado a lado antes de importar/restaurar;
- desfazer da sessão e histórico de alterações do glossário;
- “regras mortas” com último uso e contagem de uso, não somente análise sintática.

### RG-024 — UX do formulário

**Avanço:** o editor explica a fase selecionada com exemplos e oferece atalhos
de prioridade baixa/normal/alta sem remover o campo numérico. Os atalhos de
escopo usam todos os idiomas, o destino atual ou o par declarado; se faltar um
idioma necessário, não alteram o campo. A prévia é atualizada ao editar e a
limpeza selecionada usa a mesma transformação de espaços do pipeline. Alterar
o escopo também marca a entrada como modificada.

**Escopo e prévia:** seletores de origem e destino incluem a opção global e
sincronizam com o campo avançado; códigos personalizados são preservados. A
janela descreve o escopo, sinaliza regra fora do par atual ou prioridade
inválida e realça diferenças no resultado de prévias curtas. O realce não
indica posições removidas e é omitido para textos longos ou com caracteres
fora do plano básico Unicode. Há comandos para limpar e copiar a prévia e
atalhos `Ctrl+T` e `Ctrl+Shift+T`. O painel de impacto e a reorganização das
ações continuam pendentes.

**Alterações automáticas:** mudanças de escopo e prioridade, inclusive pelo
comando de priorização de conflito, também pedem simulação antes de salvar.
O diálogo mostra ambos os valores e informa que a regra é simulada
isoladamente, sem calcular concorrência com outras regras.

**Entender esta regra (17/11/2026):** uma análise rolável e copiável explica a
fase, o escopo e a prioridade do rascunho; aplica a regra isolada ao texto de
teste e compara o catálogo carregado antes e depois da edição, incluindo
concorrência e sobreposições na fase escolhida. A análise roda em segundo plano,
pode ser cancelada e não grava dados. Sugestões são identificadas como não
automáticas; regras de semente, outras fases e textos futuros não entram nessa
comparação. Quando o tipo muda, a fase anterior ainda requer análise separada.

- trocar `Idioma:` livre por controles de origem/destino com opção “todos”, mantendo modo avançado textual;
- explicar tipo com exemplos diretamente na tela;
- substituir prioridade numérica crua por “normal/alta/baixa” com valor avançado opcional;
- mostrar um painel “Esta regra fará…” com escopo, precedência, exemplos e impacto;
- realçar no preview o trecho casado e o texto produzido;
- tornar “Salvar” a ação primária e agrupar importar/exportar/restaurar num menu secundário;
- exibir atalho no tooltip e no próprio menu de comandos.

### RG-025 — produtividade do glossário

Meta de fluxo: criar ou corrigir uma regra em até 20 segundos sem conhecer o formato interno. Medir:

- cliques/teclas por regra criada;
- tempo busca → edição → validação → próxima regra;
- taxa de promoção desfeita;
- regras nunca acionadas;
- redução de edições humanas após promoção.

### RG-026 — integridade e migração

- schema versionado para o arquivo, não apenas para o cache SQLite;
- importação com relatório reproduzível e identificador da operação;
- hashes e contagens no backup;
- teste baseado em propriedades para precedência, escopo, caixa e idempotência;
- corpus mínimo por idioma com regressões de xadrez reais;
- edição concorrente detectada por versão/hash antes de gravar.

### RG-027 — contexto faz parte da decisão de tradução

Hoje comentários textualmente iguais são traduzidos uma vez e o contexto de leitura vem apenas da primeira ocorrência (`pgn_utils.py:500-512`). Uma frase curta como “Better is…” pode precisar de traduções diferentes conforme o lance. Para LLMs, definir explicitamente uma destas políticas:

- chave de trabalho inclui um contexto canônico;
- contexto serve apenas para desambiguação e a resposta precisa ser válida em todas as ocorrências;
- comentários repetidos com contextos materialmente diferentes são separados.

Não alterar a chave da memória de tradução sem migração e medição de custo. Criar corpus com texto idêntico em posições semanticamente diferentes.

### RG-028 — eliminar o delimitador `|||` da interface interna

Um comentário legítimo contendo `|||` é repartido como se fossem vários itens antes da saída JSON. O provider deve receber uma lista estruturada de itens com IDs e contextos. O adaptador Google experimental pode fazer chamadas separadas ou usar escaping inequívoco; o domínio nunca deve depender de um separador presente no texto do usuário.

**Progresso (13/11/2026):** o worker envia listas estruturadas aos modelos de linguagem, incluindo na tentativa individual, e isola comentários com `|||` nos provedores Google. A estimativa Google considera esses envios. A interface textual legada de `LLMTranslator.translate` permanece por compatibilidade; a remoção completa do delimitador das interfaces legadas e dos adaptadores textuais continua pendente.

**QA de marcador literal:** a revisão compara as quantidades no original e na
tradução: ocorrência preservada não recebe aviso, mas acréscimo ou perda recebe.
A versão do cache de QA foi elevada; pela política existente, o aplicativo
reavalia os avisos na próxima abertura, com possibilidade de cancelar. Contagens
iguais não provam, por si só, que o conteúdo esteja alinhado.

## 7. Interface, beleza e produtividade

### Princípio de redesign

A tela deve refletir o trabalho, não a lista de funções internas. A orientação oficial do Windows recomenda navegação consistente, simples e clara, comandos agrupados e hierarquia por espaçamento/tipografia ([Microsoft Design Basics](https://learn.microsoft.com/en-us/windows/apps/design/basics/), [Navigation basics](https://learn.microsoft.com/windows/apps/design/basics/navigation-basics)).

### RG-030 — nova estrutura da janela principal

```text
┌ Biblioteca ─ Traduzir ─ Revisar ─ Glossário ─ Relatórios ─ Configurações ┐
│                                                                          │
│  TRADUZIR                                                               │
│  Origem [ arquivo/pasta ................................ ] [Escolher]    │
│  Inglês → Português      Motor: Claude Opus ▾      [Estimar]             │
│                                                                          │
│  12 arquivos · 7.438 comentários · 63% já em cache                       │
│  Custo estimado: US$ … · Tempo estimado: … · Risco/privacidade: …        │
│                                                                          │
│  [Iniciar tradução]       [Pausar] [Cancelar]                            │
│  ███████████░░  Arquivo 8/12 · lote 31/44 · ~6 min                       │
│                                                                          │
│  Próximos passos: [Revisar 214 pendentes] [Abrir traduzidos] [Relatório] │
└──────────────────────────────────────────────────────────────────────────┘
```

Mudanças:

- navegação de primeiro nível por destino de trabalho;
- ação primária única por página;
- ferramentas raras saem da grade permanente e entram em “Relatórios/Manutenção”;
- resumo antes da execução mostra volume, cache, custo, privacidade e destino;
- conclusão oferece próximos passos, sem depender do log;
- log vira painel recolhível “Detalhes técnicos”, não o principal feedback.

### RG-031 — biblioteca de traduções

**Publicação concorrente:** instâncias que usam o novo protocolo escolhem o nome
final sob bloqueio curto e preservam ambos os pacotes em caso de colisão. O
arquivo lateral `.publicacao.lock` deve permanecer enquanto houver instâncias
ativas. A coordenação não cobre alterações feitas por programas externos.

**Busca:** aceita termos em qualquer ordem entre nome, idiomas e motor, sem
exigir acentos nem diferenciar maiúsculas de minúsculas.
Os idiomas podem ser pesquisados pelo código ou pelo nome exibido no programa;
idiomas ausentes não são presumidos.
A busca também reconhece a situação e a data do pacote exibidas na Biblioteca;
datas podem ser digitadas como `AAAA-MM-DD` ou `DD/MM/AAAA`.
Quando disponíveis, os nomes dos arquivos original e traduzido também são
pesquisáveis; caminhos completos não entram na busca. A contagem de falhas da
geração pode ser pesquisada quando informada, sem presumir zero nos pacotes antigos.
Para exigir contagem exata, use `falhas:N` (por exemplo, `falhas:3`); esse
termo pode ser combinado com a busca textual e os demais filtros.
`falhas:?` encontra pacotes sem informação de contagem, sem confundi-los com zero.
Também são aceitos limites como `falhas:>=2 falhas:<10`; valores desconhecidos
não satisfazem comparações numéricas.

**Avanço:** novos pacotes incluem `manifesto.json` versão 1, publicado junto
com os PGNs. Ele contém nomes relativos, SHA-256, data UTC, versão do programa,
idiomas e motor selecionado para a execução. O motor registrado não garante a
origem de comentários reutilizados do cache. Pacotes antigos não são alterados;
o manifesto não registra progresso de revisão.

**Falhas por pacote:** novos manifestos registram quantos comentários distintos
falharam durante a geração daquele arquivo; a Biblioteca mostra essa fotografia
no cartão. Pacotes anteriores não recebem um zero presumido. A contagem não
inclui comentários `;` não suportados, não é uma contagem de ocorrências e não
é atualizada quando outra execução reprocessa a obra.

**Leitura local:** `translation_library.py` lista manifestos válidos e
identifica pacotes antigos inequívocos, incompletos e metadados inválidos, sem
alterar o acervo. O filtro permite buscar por nome, idioma ou motor. A listagem
valida a estrutura e os caminhos, mas não recalcula hashes nem verifica a
integridade do conteúdo. Um índice persistente e a migração continuam pendentes.
Ao fechar a janela, a varredura da Biblioteca solicita cancelamento; a operação
não retorna uma listagem parcial. Leituras de sistema já iniciadas podem demorar.
Durante uma atualização, o botão **Cancelar** interrompe a leitura e mantém a
última lista concluída; na primeira abertura, não há lista anterior a preservar.
Se a atualização falhar, a última lista continua visível com aviso de que pode
estar desatualizada; os filtros continuam funcionando sobre essa fotografia.

**Cancelamento da integridade:** a Biblioteca permite interromper a leitura dos
arquivos em blocos e informa que a verificação foi cancelada, sem afirmar que
o pacote foi conferido. Fechar a janela também solicita o cancelamento; uma
leitura do sistema operacional já em andamento pode precisar terminar antes.

**Integridade em lote (17/11/2026):** **Verificar filtrados** examina todos os
pacotes da lista filtrada, inclusive outras páginas, em segundo plano. Mostra
progresso, permite cancelar sem apresentar resultados parciais e resume
correspondências, divergências, alterações durante a leitura e pacotes não
verificáveis, com até dez exemplos. A operação usa a verificação individual e
não altera os pacotes. Ela não autentica a procedência do manifesto; pacotes
sem manifesto compatível não podem ser conferidos.

**Janela inicial:** o botão **Biblioteca** abre uma lista pesquisável com
estados dos pacotes e ações para abrir pasta, original e tradução. A leitura
acontece em segundo plano, e os arquivos são conferidos novamente antes da
abertura. A ação **Verificar integridade** compara os dois arquivos com os
hashes do manifesto em segundo plano e informa divergências ou mudanças
detectadas durante a leitura. Isso não autentica a procedência do manifesto.
Pacotes antigos sem manifesto não podem ser conferidos dessa forma. A janela
exibe até 20 cartões por página, combina filtros por situação, origem, destino
e motor e ordena por nome ou data;
pacotes sem data ficam no fim da ordenação cronológica.

**Vínculo com revisão:** pacotes produzidos a partir desta alteração recebem
um identificador aleatório e vínculo no banco local para a origem e o par de
idiomas. **Revisar pendentes** verifica os arquivos e o vínculo antes de abrir
o editor no arquivo e par corretos. Para pacotes anteriores ou copiados sem
vínculo, a biblioteca procura uma obra compatível pelo conteúdo original e par
de idiomas; se houver mais de uma possibilidade, não escolhe. Uma única
correspondência exige confirmação e não comprova que seja a mesma execução.
O original registrado precisa estar acessível e ter o mesmo nome e conteúdo.
O manifesto não contém o caminho absoluto. Se o vínculo não puder ser gravado,
o pacote continua publicado e o registro informa a limitação. Índice
persistente e migração permanente de pacotes anteriores seguem pendentes.

**Progresso sob demanda:** em pacotes com vínculo confiável, **Consultar
progresso** verifica o pacote e lê o banco em segundo plano para mostrar quantos
comentários distintos estão verificados e pendentes. As contagens representam o
estado atual do banco, podem abranger traduções compartilhadas com outras obras
e não representam falhas de tradução nem o número de ocorrências no PGN.
Pacotes sem vínculo confiável não recebem um progresso presumido.

**Detalhes e cancelamento (17/11/2026):** a consulta também mostra quantos
pendentes estão em dúvida ou rejeitados e quantos possuem ou não alerta QA.
Esses números são subconjuntos dos pendentes e podem se sobrepor. É possível
cancelar a consulta; resultados que chegam depois do cancelamento são
descartados. A leitura em blocos observa o cancelamento; uma consulta SQLite ou
operação de sistema já iniciada pode precisar terminar antes.

**Regerar PGN:** a Biblioteca cria um novo pacote usando as traduções salvas
no banco, sem consultar o motor de tradução e sem substituir o pacote anterior.
Se faltar alguma tradução para o par de idiomas, a geração é interrompida e a
quantidade de comentários distintos ausentes é informada. Para pacotes antigos
com uma única obra compatível, o usuário confirma a correspondência antes da
geração. Os dados são consultados em uma fotografia do banco; edições ainda não
salvas não entram na nova versão. A operação verifica integridade e usa as
configurações atuais de BOM e requebra.
A regeneração também é interrompida se o original contiver comentários `;`, que
o programa ainda não traduz, ou traduções salvas apenas com espaços.
O aviso de traduções ausentes mostra até cinco exemplos curtos. A busca do vínculo,
a verificação dos arquivos e a leitura do original observam o cancelamento entre
etapas ou blocos; uma operação de sistema já iniciada pode precisar terminar.

**Busca estruturada (17/11/2026):** a Biblioteca aceita `origem:en`, `destino:pt`, `motor:google`, `situação:com-manifesto` e `data:2026-11-17`, inclusive comparações de data completa. Também aceita `nome:`, `original:`, `traduzido:`, `idioma:` e datas por ano ou mês. Os termos podem ser combinados com a busca e os filtros existentes; `?` seleciona dados não informados nos campos compatíveis. Datas inválidas não produzem correspondências.

**Produtividade e teclado:** a Biblioteca filtra e ordena pela contagem de
falhas da geração, mantendo pacotes sem essa informação como desconhecidos.
A consulta de progresso mostra percentual sem arredondar uma revisão incompleta
para 100%. `Ctrl+F` foca a busca e `Alt+←`/`Alt+→` navegam entre páginas. A ação
**Copiar resumo** copia somente metadados exibíveis, sem o conteúdo dos PGNs,
hashes ou caminhos absolutos. A acessibilidade completa do RG-034 ainda exige
validação com tecnologias assistivas, escalas e alto contraste.

A biblioteca também indica quantos filtros estão ativos e oferece **Limpar
filtros** (`Ctrl+L`), `F5` para atualizar e `Alt+Home`/`Alt+End` para acessar
a primeira ou última página. Limpar preserva a ordenação escolhida. A ordenação
e os filtros são lembrados ao fechar, exceto a busca textual; opções de idiomas
ou motor que não existirem mais voltam a “Todos”. Se a leitura da biblioteca
falhar ou estiver em curso, as preferências anteriores não são sobrescritas.
Ao fechar, a gravação também preserva um arquivo de configurações ilegível ou
corrompido, sem tentar recuperá-lo automaticamente, e informa que as
preferências não puderam ser salvas.

Transformar `Minhas Traduções` em uma página do produto, não apenas uma pasta:

- cartões/linhas com título, idioma, motor, data, progresso de revisão e falhas;
- abrir original, traduzido, pasta ou editor;
- busca, ordenação e filtro;
- manifesto JSON por pacote com caminhos relativos, hashes, versão, motor/modelo, idiomas e estado;
- política de colisão, retenção e limpeza;
- “revelar no Explorer” continua disponível.

### RG-032 — sistema visual

- escala tipográfica consistente: título, seção, corpo, metadado;
- grade de espaçamento de 4/8 px;
- tokens únicos para cor, raio, estados, foco e tipografia;
- largura responsiva: a janela mínima atual de 900 px não deve esconder comandos;
- cor comunica junto com ícone e texto, nunca sozinha;
- estados vazios com orientação concreta;
- skeleton/progresso indeterminado em operações cujo total ainda não existe;
- mensagens persistentes para falhas; toasts curtos somente para sucesso reversível.

### RG-033 — ícones

O ícone do aplicativo tem conceito coerente e versões desenhadas por tamanho. Preservá-lo. O problema está na ausência de iconografia funcional: quase todos os comandos são botões textuais.

Plano:

- adotar uma família única de ícones vetoriais alinhada ao Fluent, empacotada localmente;
- ícone + texto para comandos principais; apenas ícone onde a convenção é inequívoca e há tooltip;
- símbolos distintos para abrir, pasta, iniciar, pausar, cancelar, revisar, glossário, conflito, automático, sugestão e limpeza;
- nunca usar emoji como ícone de produção;
- validar em 100%, 150% e 200% de escala e nos temas claro, escuro e alto contraste;
- manter o gerador do ícone de marca e criar folha de contato automatizada para os ícones de comando.

### RG-034 — acessibilidade

**Posição textual (17/11/2026):** no editor, **Descrição (F8)** abre texto
selecionável e copiável com peças e casas, vez, direitos de roque, casa en
passant e contadores informados pela FEN. Campos ausentes ou inválidos são
indicados; a descrição não verifica a legalidade da posição. Ela é uma
alternativa textual, mas a validação com Narrator e tecnologias assistivas,
contraste e escalas continua pendente.

A referência de release deve incluir teclado completo, nome/papel/estado para tecnologia assistiva, foco visível, alto contraste e escala de texto. A Microsoft recomenda expor nomes e estados via UI Automation, tornar toda interação acessível por teclado e testar 200% de escala ([Windows accessibility best practices](https://learn.microsoft.com/en-us/windows/apps/get-started/best-practices)). Como referência mensurável, WCAG 2.2 usa 4,5:1 para texto normal, alvo mínimo de 24×24 e foco com mudança de contraste de 3:1 ([WCAG 2.2](https://www.w3.org/TR/wcag/), [Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum), [Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance)).

Backlog:

- mapa de tabulação e teste automatizado de foco;
- indicador de foco próprio e consistente;
- acessibilidade de `CTkButton`, campos, listas virtuais e canvas do tabuleiro verificada com Narrator;
- atalhos visíveis numa command palette (`Ctrl+K`);
- não exigir mouse para divisor, seleção múltipla ou menus contextuais;
- escalas 100/125/150/200%, 1366×768 e múltiplos monitores;
- alternativa textual completa ao tabuleiro.

### RG-035 — command palette e ações contextuais

**Primeiro recorte (17/11/2026):** na janela principal, **Comandos (Ctrl+K)**
oferece busca sem acentos, navegação por setas, Enter e Escape e cinco ações:
selecionar arquivo, iniciar tradução, abrir Biblioteca, glossário e configurações.
A tradução informa quando não há caminho válido ou já existe execução e
confere essas condições novamente ao executar. Ações adicionais, atalhos nas
janelas secundárias e validação com tecnologias assistivas permanecem pendentes.

**Cinco ações adicionais (17/11/2026):** a paleta também permite selecionar uma
pasta, revisar pendências da última execução, iniciar uma nova regra no
glossário, exportar TMX e verificar dados. A revisão exige arquivos registrados;
a verificação não pode ser iniciada duas vezes. A criação de regra usa a ação
existente do editor e suas confirmações, e a lista possui barra de rolagem.

**Controle da tradução (17/11/2026):** a paleta acrescenta abrir o editor de
traduções, reprocessar falhas, pausar, continuar e cancelar. As ações usam os
mecanismos existentes e indicam quando o estado atual não permite executá-las;
o estado é conferido novamente na execução. Reprocessar mantém o diálogo e a
seleção de idiomas do fluxo existente. A paleta continua restrita à janela
principal.

**Acesso a arquivos e dados (17/11/2026):** a paleta também oferece abrir
Minhas Traduções, abrir a pasta da última execução, exportar e importar CSV e
criar backup do banco. A importação fica indisponível durante tradução, e a
pasta da última execução exige arquivos registrados; as condições são
conferidas novamente ao executar. Os fluxos existentes mantêm seus diálogos.

Uma command palette pesquisável reduz a densidade sem esconder capacidade. Deve oferecer “Abrir arquivo”, “Iniciar”, “Ir para pendentes”, “Nova regra”, “Exportar TMX”, “Verificar dados” e configurações, mostrando atalhos e recusando ações inválidas com motivo.

### RG-036 — corretor de português com ortografia e concordância

**Validação de 05/11/2026:** a cópia integrada passou na suíte completa com
2.662 testes e 6.785 subtestes; 55 testes foram pulados, inclusive os testes
opcionais do LanguageTool real. Em execução separada com o motor local preparado,
os 43 testes opcionais do LanguageTool passaram. O CI do PR #7 passou com testes de janela e
verificação de tipos obrigatórios. Isso confirma a integração testada, mas não
aprova a distribuição autocontida nem substitui a avaliação de qualidade real.

**Andamento em 05/11/2026:** o assistente, o painel de sugestões, o vocabulário
global, a aplicação individual ou em lote e a integração local com LanguageTool
já foram implementados. A concordância permanece experimental e desligada por
padrão. Uma tentativa que atingiu 100% de precisão e 90,91% de recall no corpus
de 18 casos foi rejeitada porque outros testes detectaram sugestões incorretas;
após sua retirada, o replay confirmou 90% de precisão e 81,82% de recall. Uma cópia
local integrada preserva as alterações de saída e
permite testar a função. A distribuição autocontida permanece bloqueada pela
revisão de fontes, licenças e avisos, e pela validação final dos artefatos.

O corretor anterior já sublinhava palavras pt-BR desconhecidas com `spylls` e
excluía notação, nomes do original e termos do glossário. O assistente amplia esse
fluxo com sugestões e análise gramatical; a validação de alta confiança continua pendente.

Implementação planejada:

- preservar o corretor ortográfico local e expor até cinco sugestões por menu/teclado;
- criar o módulo profundo `PortugueseWritingAssistant`, independente de Tk;
- usar LanguageTool local como candidato gramatical, isolado em processo auxiliar HTTP restrito a loopback, mantendo `spylls` como fallback ortográfico;
- detectar concordância nominal, artigo–substantivo e sujeito–verbo, repetição acidental e espaçamento de pontuação;
- mascarar lances, casas, NAGs e `[%...]` antes da análise;
- apresentar ortografia e gramática com estilos visuais diferentes, texto explicativo e navegação por `F7`;
- aplicar uma sugestão por gesto, com undo; nunca corrigir concordância silenciosamente;
- analisar fora da thread da UI, com debounce, geração e descarte de resultado obsoleto;
- usar modo local por padrão; qualquer adaptador remoto exige consentimento próprio;
- medir precisão, falsos positivos, memória, latência e tamanho do executável antes de ativar concordância por padrão.

Os contratos, classes de ocorrência, interface, corpus e critérios de aceite estão em [REVISAO_GERAL_SPEC.md](REVISAO_GERAL_SPEC.md), seção 8. A pesquisa e a comparação de LanguageTool, Lightproof, spaCy e Stanza estão em [PESQUISA_CORRETOR_PORTUGUES.md](docs/PESQUISA_CORRETOR_PORTUGUES.md). A adoção final do LanguageTool continua condicionada à qualidade real em fragmentos de xadrez, licença, Java, memória e custo de empacotamento — não apenas a uma demonstração em frases completas.

## 8. Desempenho

### RG-040 — benchmarks como contrato

**Avanço:** `benchmarks/pgn_extraction.py` mede a leitura e extração de
comentários com PGNs sintéticos temporários. O relatório registra amostras,
mediana, p95, pico de alocações Python e ambiente. A primeira medição local,
com cinco amostras para 1 e 10 MiB, está em
[`benchmarks/baseline-local.json`](benchmarks/baseline-local.json). O p95 com
cinco amostras é apenas o maior valor observado; o corpus repete a mesma partida
e não representa todos os acervos. Na [medição local de 100 MiB](benchmarks/baseline-100mib-local.json),
a mediana de cinco amostras foi 2,41 s e o pico rastreado pelo Python foi cerca
de 421 MiB, medido em execução separada. Esse pico não inclui necessariamente
toda a memória do processo. Os outros cenários e o gate do CI continuam pendentes.

O benchmark [`glossary_matching.py`](benchmarks/glossary_matching.py) mede a
aplicação de regras automáticas sintéticas, com primeira aplicação e chamadas
seguintes. Na [medição local](benchmarks/baseline-glossario-local.json), a
mediana das chamadas seguintes foi cerca de 9,6 ms com 6 mil regras e 1,42 s
com 50 mil. Nesse cenário de 50 mil regras houve 250 mil faltas no cache de
regex em cinco aplicações, contra zero com 6 mil; isso justifica investigar
o RG-041, mas um comentário curto e regras sintéticas não representam todos os
usos. O pico de alocações Python é medido separadamente com caches limpos.

O benchmark [`translation_database.py`](benchmarks/translation_database.py)
mede cache completo, cache de até 100 comentários e busca paginada por trecho em
banco temporário sintético. Na [medição local](benchmarks/baseline-banco-local.json)
de 100 mil linhas, as medianas foram cerca de 162 ms, 0,2 ms e 43 ms,
respectivamente, com cinco amostras e possível cache do sistema aquecido. Na
[medição de 1 milhão de linhas](benchmarks/baseline-banco-1milhao-local.json),
as medianas foram 1,26 s, 0,23 ms e 398 ms, respectivamente; o cache completo
atingiu cerca de 268 MiB de alocações Python rastreadas em execução separada.
Havia outros processos ativos e o cache do sistema pode estar aquecido. Outros
cenários e um gate de CI permanecem pendentes; os números não representam
automaticamente bancos reais nem toda a memória do processo.

O benchmark [`pgn_generation.py`](benchmarks/pgn_generation.py) mede a geração
com posições já extraídas e compara a saída completa com os bytes esperados para
um corpus sintético UTF-8/CRLF. Na [medição local](benchmarks/baseline-geracao-pgn-local.json),
as medianas foram 11,7 ms para 1 MiB e 116,2 ms para 10 MiB, em cinco amostras.
A preparação, a validação e a memória previamente ocupada pelo texto e pelas
posições ficam fora da medição. Isso não comprova preservação para todos os PGNs.

Criar `benchmarks/` com corpus sintético e corpus anonimizado/permitido para:

- extrair 1 MB, 10 MB e 100 MB de PGN;
- carregar e pesquisar 10 mil/100 mil/1 milhão de traduções;
- casar 6 mil e 50 mil regras de glossário;
- abrir primeira tela dos editores;
- renderizar página, buscar e salvar regra;
- gerar PGN preservando bytes fora dos comentários;
- uso de memória por livro e por pasta.

Registrar mediana, p95, pico de memória e máquina. O CI detecta regressão grande; microvariações não quebram build.

### RG-041 — compilador de glossário

**Avanço:** a busca descarta padrões seguramente ausentes antes de compilar a
regex, preservando a busca original para casos Unicode que exigem comparação
insensível a caixa. No mesmo cenário sintético de 50 mil regras do RG-040, a
mediana das chamadas seguintes passou de 1,42 s para 61 ms e as faltas no cache
passaram de 250 mil para zero em cinco aplicações. A medição posterior está em
[`depois-filtragem-glossario-local.json`](benchmarks/depois-filtragem-glossario-local.json).
Esses números descrevem um comentário ASCII curto; textos Unicode e glossários
reais podem ter resultados diferentes. O plano compilado e o índice continuam
pendentes de medição e justificativa para os demais cenários.

**Ampliação Unicode:** padrões ASCII insensíveis a caixa também podem ser
descartados com segurança em comentários acentuados; candidatos seguem para a
regex original. A normalização para essa triagem considera as equivalências
especiais de `re.IGNORECASE`, e um teste percorre os caracteres Unicode que
casam com letras ASCII. No comentário sintético acentuado de 50 mil regras, a
mediana passou de 1,69 s para 70 ms. Resultados detalhados estão em
[`antes`](benchmarks/antes-unicode-glossario-local.json) e
[`depois`](benchmarks/depois-unicode-glossario-local.json). Regras não ASCII
continuam usando a busca anterior, portanto o ganho depende do acervo.

O glossário atual ordena e aplica regras com caches bem pensados, suficiente para 6.071 entradas. Para crescer 10×, criar um plano compilado por tipo/escopo e um índice por primeiro token/trigrama. Não introduzir Aho-Corasick ou outra estrutura complexa sem benchmark demonstrando necessidade e preservação exata da precedência.

### RG-042 — virtualização da interface

Os editores ainda constroem botões por página e mantêm estado considerável em memória. Avaliar uma lista virtualizada/canvas com acessibilidade, mas só trocar se medir ganho e preservar teclado, foco e testes. CustomTkinter pode virar o limite técnico; registrar critérios para permanecer ou migrar para Qt/WinUI, sem reescrita estética sem business case.

### RG-043 — operações incrementais

**Avanço (14/11/2026):** a inspeção de temporários conta todas as pastas
e mantém apenas os exemplos mais antigos solicitados em memória. A listagem
principal da Biblioteca ainda não possui índice persistente.

- salvar uma regra não deve exigir reconstruir todo o catálogo se um delta validado basta;
- contagens e facetas devem ser mantidas/consultadas por índice;
- estatísticas pesadas devem ser canceláveis e cacheadas por versão do banco;
- `Minhas Traduções` precisa de índice/manifesto para não varrer todo o disco a cada abertura.

## 9. Rede, privacidade e segurança

### RG-050 — consentimento e política por provedor

**Progresso (17/11/2026):** o LibreTranslate diferencia falhas de conexão,
tempo esgotado, certificado, acesso recusado e limite do servidor, sem registrar
o conteúdo das exceções. Em Configurações, **Testar conexão e idiomas** consulta
a lista de idiomas em segundo plano e confere o par selecionado sem enviar
comentários ou chave. A consulta não valida a chave nem garante que uma
tradução posterior funcionará. Os demais requisitos de consentimento seguem
pendentes.

Antes da primeira chamada de cada motor, mostrar:

- qual texto sai da máquina;
- provedor e endpoint;
- se há contrato/cota oficial;
- estimativa de custo;
- link para política aplicável;
- opção de não usar e de não perguntar novamente para aquela versão da política.

Não enviar nomes de arquivos, caminhos locais, FEN ou metadados que não sejam necessários. Logs guardam métricas e IDs locais, não payloads.

### RG-051 — segredos fora do Windows

**Progresso (13/11/2026):** as configurações informam quando a gravação ocorre
sem criptografia, indicam corretamente a chave de ambiente ativa e ocultam
inteiramente chaves com até quatro caracteres. Alterações de chaves são
sincronizadas entre instâncias; arquivos ilegíveis são preservados, e a
publicação usa temporário exclusivo. Armazenamento seguro fora do Windows e
permissões de acesso específicas no Windows ainda estão pendentes.

`api_keys.py:13-14` documenta que, sem DPAPI, a chave é apenas base64 com `cifra: nenhuma`. Isso é aceitável como fallback explícito de desenvolvimento, não como armazenamento silencioso de produção.

Plano: usar keyring do sistema quando houver; caso contrário, exigir variável de ambiente ou avisar claramente que não haverá armazenamento seguro. Restringir permissões do arquivo onde o sistema permitir.

### RG-052 — cadeia de suprimentos

- Dependabot/Renovate com PRs agrupados e teste completo;
- auditoria de vulnerabilidades no lock;
- SBOM do artefato;
- hashes e procedência do instalador;
- assinatura de código quando distribuição justificar o custo;
- versões de GitHub Actions fixadas por SHA para maior rigor;
- licença de cada dicionário/asset incluída no pacote e relatório de terceiros.

## 10. Qualidade de tradução e produtividade

### RG-060 — métrica humana como norte

A taxa “aceita sem editar” é a métrica principal. Executar leitura cega por par de idiomas, estratificada por comprimento, fragmento, citação, notação e presença de glossário. Reportar intervalo de confiança e comparação pareada entre motores.

### RG-061 — roteamento por risco

Não usar o mesmo motor para tudo. Classificar antes de enviar:

- cache/verificada: não envia;
- simples e baixo risco: motor barato/oficial;
- fragmento, ambiguidade, nome ou notação densa: LLM de maior qualidade;
- alta confiança de regra automática: aplicar deterministicamente;
- risco alto: destacar para revisão humana.

O usuário escolhe política (“econômica”, “equilibrada”, “qualidade”), sempre com estimativa.

### RG-062 — fila de revisão por valor

Ordenar pendências por risco × frequência × impacto. Uma frase repetida em 200 posições deve vir antes de uma frase única; divergência de âncora, QA grave e regra automática recém-promovida vêm primeiro.

### RG-063 — reduzir gestos

- salvar e avançar configurável;
- aceitar sugestão por atalho;
- aplicar correção às ocorrências selecionadas;
- próxima linha de maior risco;
- comparação com memória e histórico no mesmo foco visual;
- painel lateral recolhível, sem abrir diálogos para ações frequentes;
- sessão de trabalho com meta, progresso e retomada exata.

## 11. Testes e observabilidade

### RG-070 — pirâmide por interfaces reais

Preservar os testes GUI valiosos, mas migrar lógica para presenters/módulos profundos testáveis sem Tk. A divisão recomendada:

- propriedades e corpus dourado para parser/glossário;
- contrato único aplicado a todos os provedores;
- integração `TranslationJob` com SQLite e filesystem temporários;
- poucos testes GUI por jornada crítica;
- smoke test no `.exe` gerado e no instalador;
- ensaio de upgrade/downgrade/restauração.

### RG-071 — testes que faltam

- concorrência de duas instâncias traduzindo e editando glossário;
- disco cheio, permissão negada e caminho longo durante saída/cópia;
- crash entre PGN gerado e cópia do original;
- corrupção parcial de manifesto/pacote;
- relógio alterado e suspensão do Windows;
- proxies, TLS interception, DNS e modo offline;
- escalas e idiomas de UI com textos mais longos;
- Narrator/teclado e alto contraste;
- propriedade “bytes fora dos spans traduzidos permanecem iguais” sobre PGNs gerados aleatoriamente;
- fuzzing do parser de comentários e do importador de glossário.

### RG-072 — eventos estruturados

Substituir strings como contrato de observabilidade por eventos tipados: `BatchStarted`, `RateLimited`, `CommentFailed`, `OutputWritten`. Um formatador produz log humano. Métricas locais agregadas podem ser exportadas pelo usuário; nada deve ser enviado automaticamente sem consentimento.

## 12. Plano de execução

### Marco 0 — segurança operacional (1–2 semanas)

**Em andamento (23/10/2026):** publicação transacional do pacote, detecção de alteração do arquivo-fonte, estados de falha/cancelamento fiéis e atualização de `certifi`/`urllib3` implementados e cobertos por testes. Os artefatos existentes em `dist/` ainda precisam ser reconstruídos para incorporar a nova resolução.

- RG-000 identidade/deduplicação do glossário;
- RG-000B escrita atômica do pacote;
- RG-001 modo seguro do Google e limites;
- RG-002 CI bloqueante;
- RG-003 verificação/restauração;
- RG-014 dependências coerentes;
- testes da nova pasta de traduções e escrita atômica do pacote.

**Saída:** versão patch segura, sem redesign.

### Marco 1 — medir e estabilizar (2–3 semanas)

- benchmarks RG-040;
- eventos RG-072;
- leitura cega RG-060;
- métricas de gestos do glossário;
- auditoria de acessibilidade das jornadas atuais.

**Saída:** baseline publicada neste documento, com números e limites.

### Marco 2 — módulos profundos (4–8 semanas)

- `TranslationJob` e contratos de provider;
- `GlossaryCatalog` e `GlossaryEngine`;
- pacotes de saída com manifesto;
- expansão progressiva do mypy;
- testes novos nas interfaces e remoção dos redundantes.

**Saída:** comportamento byte a byte preservado, interface interna menor.

### Marco 3 — interface produtiva (4–6 semanas)

- protótipo navegável da nova janela;
- teste de tarefas com usuário real antes da implementação completa;
- centro Traduzir, Biblioteca e Glossário;
- sistema visual, ícones e command palette;
- teclado, foco, escala e alto contraste.
- sugestões ortográficas acionáveis e painel de revisão linguística;

**Saída:** redução medida de gestos e tempo nas três jornadas principais.

### Marco 4 — inteligência de curadoria (3–6 semanas)

- caixa de entrada do glossário;
- impacto, explicação e revisão em lote;
- roteamento por risco;
- priorização da fila humana;
- painel de qualidade por motor/par.
- concordância pt-BR local, ativada após cumprir a precisão mínima da spec;

**Saída:** aumento demonstrado de aceitação sem editar e menor tempo por mil palavras.

## 13. Critérios de sucesso

| Objetivo | Métrica |
|---|---|
| estabilidade | zero perda/corrupção em testes de crash e recuperação |
| Google seguro | zero seleção silenciosa do endpoint não oficial; cota global respeitada |
| qualidade | taxa de aceitação sem editar por motor/par, medida cegamente |
| produtividade | tempo e gestos por 100 comentários e por regra de glossário |
| performance | orçamento p95 e memória para corpus pequeno/médio/grande |
| arquitetura | worker sem dependência de Tk; interfaces explícitas e tipadas |
| acessibilidade | jornadas críticas completas por teclado em 200% e alto contraste |
| release | CI crítico bloqueante e smoke test do artefato instalado |
| glossário | cada decisão explica casamento, vencedor, escopo e impacto |

## 14. Decisões que não devem ser tomadas ainda

- reescrever tudo em outra toolkit de UI sem provar que CustomTkinter impede os requisitos;
- adicionar estruturas algorítmicas complexas ao glossário sem benchmark acima de 6 mil regras;
- transformar toda função em classe ou criar portas com um único adaptador;
- enviar telemetria remota por padrão;
- substituir o ROADMAP histórico: ele continua sendo a memória das decisões;
- tornar um LLM padrão apenas por QA automática; a leitura cega humana decide;
- prometer ausência de “ban” ou segurança do `gtx`: não há contrato que sustente essa promessa.

## 15. Próxima ação recomendada

**Atualização de 06/11/2026:** implementar RG-003 em etapas verificáveis:
primeiro uma inspeção que não altere o acervo e não exponha conteúdo sensível;
depois um ensaio de restauração em diretório temporário, incluindo banco,
glossário, configurações e pacotes de tradução. A inspeção precisa informar
limitações de bases em uso e arquivos SQLite WAL, sem prometer consistência de
uma cópia feita enquanto o programa grava. Validar também o fluxo do instalador.
Em paralelo, manter RG-036 aberto até atingir a meta de qualidade e concluir as
fontes, licenças e avisos do pacote autocontido.

Abrir cinco issues a partir do Marco 0, cada uma com responsável, teste de aceite e medição. A primeira deve ser **“Tornar Google não oficial explicitamente experimental e adicionar política global de cota/cooldown”**. Em paralelo, produzir um protótipo descartável da janela principal proposta e medir três tarefas: iniciar uma tradução, retomar pendentes e criar uma regra automática com segurança.
