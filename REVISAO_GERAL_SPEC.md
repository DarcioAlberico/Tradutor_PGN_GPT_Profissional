# REVISAO_GERAL — Especificação do produto

Versão: 1.0-draft
Data: 23 de outubro de 2026
Documento associado: [REVISAO_GERAL.md](REVISAO_GERAL.md)
Especificação anterior: [SPEC.md](SPEC.md)

## 1. Finalidade

Esta é a especificação normativa do estado-alvo descrito na Revisão Geral. A `SPEC.md` anterior continua documentando o comportamento da versão 0.4.0; quando houver conflito, esta especificação só prevalece depois que o requisito correspondente for implementado, testado e registrado como concluído.

O produto traduz comentários de arquivos PGN, preserva a estrutura enxadrística, aplica decisões terminológicas, organiza a revisão humana e produz um pacote autocontido com original, tradução e proveniência.

## 2. Princípios obrigatórios

1. **O original é imutável.** Nenhuma operação modifica o PGN de entrada.
2. **Estrutura antes de prosa.** Lance, casa, NAG, tag e anotação protegida nunca podem ser sacrificados para melhorar estilo.
3. **Publicação atômica.** Um arquivo final visível é completo; parcial é temporário ou explicitamente incompleto.
4. **Humano decide.** Tradução, glossário e corretor linguístico sugerem; somente regras automáticas explicitamente promovidas alteram texto sem gesto por ocorrência.
5. **Sem troca silenciosa.** Motor, modelo, idioma ou política nunca mudam por falha sem consentimento.
6. **Privacidade explícita.** Antes do primeiro envio, o usuário sabe que texto sai da máquina, para quem e sob quais condições.
7. **Estado explicável.** Toda correção, regra ou falha deve dizer origem, motivo, alcance e reversibilidade.
8. **Offline degrada com clareza.** Função indisponível é anunciada; ausência nunca se parece com “nenhum erro”.
9. **Acessibilidade é critério de release.** Jornadas críticas funcionam por teclado, com foco visível, escala de 200% e alto contraste.
10. **Medição antes de complexidade.** Otimizações e migrações de toolkit exigem benchmark ou teste de tarefa.

## 3. Vocabulário

Os termos canônicos estão em [CONTEXT.md](CONTEXT.md). Esta especificação usa especialmente:

- **execução de tradução**: tentativa rastreável com arquivos, par e motor definidos;
- **pacote traduzido**: pasta com original, traduzido e manifesto;
- **entrada de glossário**: decisão persistida identificada por original, substituição, fase e escopo;
- **regra compilada**: forma executável derivada da entrada;
- **linha de revisão**: tradução persistida apresentada ao revisor;
- **ocorrência linguística**: problema ortográfico ou gramatical encontrado num intervalo do texto, com sugestões e explicação.

## 4. Escopo funcional

### 4.1 Jornadas principais

O produto deve permitir:

1. selecionar arquivo ou pasta PGN;
2. escolher origem, destino, motor e política de qualidade/custo;
3. estimar volume, reaproveitamento, custo, tempo e destino;
4. traduzir com pausa, cancelamento e retomada segura;
5. abrir o pacote produzido;
6. revisar pendências priorizadas por risco e impacto;
7. corrigir ortografia e concordância em português com sugestões;
8. transformar edições recorrentes em entradas de glossário;
9. exportar, restaurar e verificar os dados do usuário;
10. consultar histórico e proveniência.

### 4.2 Fora do escopo

- tradução integral do movetext ou das tags PGN;
- alteração automática silenciosa de gramática;
- garantia de disponibilidade de endpoint não oficial;
- telemetria remota sem consentimento;
- substituir revisão profissional por pontuação automática;
- corretor de estilo literário ou reescrita criativa na primeira versão do corretor linguístico.

## 5. Arquitetura de referência

### 5.1 `TranslationJob`

Interface externa do módulo:

```python
result = TranslationJob(plan, repository, provider, output_store).run(events, cancel)
```

`TranslationJob` deve esconder descoberta, lotes, máscara, âncoras, cache, retries, commits, QA e publicação. Não recebe janela, widget ou `PGNTranslatorApp`.

### 5.2 `GlossaryCatalog` e `GlossaryEngine`

`GlossaryCatalog` é responsável por identidade, persistência, revisão otimista, backup, importação e exportação. `GlossaryEngine` é responsável por compilação, casamento, precedência, explicação, simulação e aplicação.

A identidade canônica de uma entrada é:

```text
(original normalizado, substituição normalizada, fase, escopo)
```

Prioridade é atributo mutável, não identidade. Operação ambígua deve falhar explicitamente.

### 5.3 `PortugueseWritingAssistant`

O corretor de português deve ser um módulo profundo, independente de Tk:

```python
snapshot = assistant.check(text, context)
suggestions = assistant.suggestions(snapshot.issue(issue_id))
result = assistant.apply(text, issue_id, suggestion_id)
```

O módulo encapsula tokenização, proteção de notação, dicionário, análise gramatical, supressões, ordenação e explicações. A interface não expõe objetos internos de Hunspell, parser ou motor gramatical.

Dependências externas ocupam uma seam interna:

- adaptador ortográfico local `SpyllsAdapter`;
- adaptador gramatical `LanguageToolLocalAdapter`, isolado em processo auxiliar;
- adaptador falso determinístico para testes.

## 6. Requisitos do pipeline

### TR-001 — plano imutável

Uma execução captura arquivos, origem, destino, motor/modelo, opções e pasta de saída antes da primeira escrita. Mudanças posteriores na UI não alteram a execução.

### TR-002 — estados

Estados: `planned`, `running`, `paused`, `completed`, `completed_with_failures`, `canceled`, `aborted`, `crashed`. Toda transição inválida deve ser recusada.

### TR-003 — provedores

Cada provedor satisfaz o mesmo contrato de entrada estruturada, resultado por ID, cancelamento, falha tipada e métricas. Conteúdo nunca é separado por delimitador textual presente na prosa.

### TR-004 — Google

- Cloud Translation oficial é o único motor apresentado como “Google”.
- `google-gtx`, enquanto existir, aparece como experimental e não oficial.
- O modo experimental exige consentimento informado e limite conservador.
- `Retry-After`, 403, 429, cooldown persistente e cota global entre instâncias devem ser tratados.
- Não é permitido contornar bloqueio por proxy, rotação de IP ou falsificação de cliente.

### TR-005 — contexto e deduplicação

Comentários idênticos com contextos materialmente diferentes não podem receber automaticamente uma tradução baseada apenas na primeira ocorrência. A política usada deve ser registrada no manifesto e coberta por corpus de regressão.

### TR-006 — publicação

Todo arquivo é escrito em temporário no mesmo volume e publicado por substituição atômica. O manifesto é gravado por último. Falha antes do manifesto deixa pacote recuperável marcado como incompleto ou o remove integralmente.

### TR-007 — manifesto

O pacote contém `manifesto.json` com:

- versão do formato e do programa;
- caminhos relativos do original e traduzido;
- hashes SHA-256;
- idiomas;
- motor/modelo;
- instante e estado da execução;
- contagens, falhas e opções relevantes;
- nenhuma chave, payload ou caminho absoluto.

## 7. Requisitos do glossário

### GL-001 — integridade da identidade

Deduplicar, diagnosticar, localizar, atualizar, excluir e importar usam a mesma identidade canônica. Entradas iguais em fases ou escopos diferentes são distintas.

### GL-002 — concorrência

Cada alteração informa `id` e `revision`. Se a revisão persistida mudou, a operação é recusada e mostra comparação; nunca escolhe “a primeira entrada parecida”.

### GL-003 — explicação

Para qualquer texto, o motor devolve regras que casaram, vencedora, regras sombreadas, motivo da precedência e texto resultante.

### GL-004 — simulação

Antes de promover entrada automática, mostrar total atingido, divisão pendente/verificada, até dez exemplos e conflitos. Nenhuma linha é modificada pela simulação.

### GL-005 — curadoria

Edições repetidas podem gerar candidatos. Cada candidato guarda frequência, exemplos, pares, origem e estado; sugestão automática nunca é promovida sem confirmação.

### GL-006 — interface

Escopo usa seletores validados; prioridade tem níveis compreensíveis e modo avançado; importação tem prévia por linha; ações de arquivo ficam separadas de Nova/Salvar/Excluir.

## 8. Corretor de português

### 8.1 Objetivo

Ampliar o corretor ortográfico existente para um assistente de escrita pt-BR que:

- detecta palavras desconhecidas;
- sugere grafias ordenadas;
- detecta concordâncias nominais e verbais de alta confiança;
- explica o problema sem substituir silenciosamente;
- respeita notação, nomes, glossário e fragmentos típicos de comentários de xadrez.

### 8.1.1 Motor recomendado e condição de adoção

O candidato de produção é o **LanguageTool local**, executado como processo auxiliar e consultado por HTTP somente em loopback com `language=pt-BR` explícito. O `spylls` permanece como fallback ortográfico leve. A decisão e a comparação de alternativas estão em [PESQUISA_CORRETOR_PORTUGUES.md](docs/PESQUISA_CORRETOR_PORTUGUES.md).

A adoção é condicionada a protótipo: versão e artefatos fixados, inventário de licenças, medição no corpus de xadrez, health check, timeout, encerramento sem processo órfão e decisão explícita entre JRE externo e runtime reduzido embarcado. O servidor nunca usa modo público e não escuta fora de loopback.

O LanguageTool remoto não é fallback. spaCy e Stanza não são corretores prontos e ficam fora da primeira implementação; Lightproof não será portado sem uma análise específica.

### 8.2 Classes de ocorrência

| Código | Classe | Exemplo | Ação esperada |
|---|---|---|---|
| `SPELLING` | grafia | `posiçao` | sugerir `posição` |
| `NOMINAL_AGREEMENT` | gênero/número no sintagma | `as preta estão ativa` | sugerir formas concordantes, preservando sentido |
| `SUBJECT_VERB_AGREEMENT` | sujeito e verbo | `as brancas tem vantagem` | sugerir `têm` |
| `ARTICLE_NOUN_AGREEMENT` | artigo e núcleo | `o posição` | sugerir `a posição` ou revisão manual |
| `REPEATED_WORD` | repetição acidental | `a a posição` | sugerir remoção de uma ocorrência |
| `PUNCTUATION_SPACING` | espaço/pontuação | `posição ,mas` | sugerir `posição, mas` |
| `STYLE` | estilo opcional | recomendação não normativa | desligado por padrão na primeira versão |

Ocorrências de baixa confiança não são mostradas como erro. Podem aparecer numa seção opcional “Sugestões de estilo” quando houver corpus que demonstre utilidade.

### 8.3 Modelo de dados

```python
WritingIssue(
    id: str,
    kind: IssueKind,
    start: int,
    end: int,
    original: str,
    message: str,
    explanation: str,
    suggestions: tuple[WritingSuggestion, ...],
    confidence: float,
    rule_id: str,
    source: str,
)

WritingSuggestion(
    id: str,
    replacement: str,
    label: str,
)
```

Offsets são relativos ao texto exato analisado. Aplicar uma sugestão exige que o trecho atual ainda seja igual a `original`; caso contrário, o resultado é `stale` e uma nova análise é solicitada.

### PT-001 — ortografia existente

Preservar `spylls`, o dicionário pt-BR embarcado e os filtros comprovados de:

- notação e tokens com dígitos;
- vocabulário do original;
- lado direito do glossário aplicável;
- nomes e termos aceitos pelo usuário.

### PT-002 — sugestões ortográficas

Clique direito ou comando de teclado sobre `SPELLING` mostra no máximo cinco sugestões, “Ignorar nesta ocorrência”, “Ignorar na sessão” e “Adicionar ao glossário/vocabulário pessoal”. A ordem deve ser estável numa mesma versão.

### PT-003 — concordância

O motor de concordância analisa somente pt-BR e somente prosa desprotegida. Deve detectar, no mínimo, os padrões de alta confiança definidos no corpus de aceite. Não deve inferir correção apenas pela distância entre palavras; precisa de análise morfossintática ou regra estrutural equivalente.

O adaptador normaliza a resposta do LanguageTool para `WritingIssue`, mantém o identificador da regra de origem e permite desativação granular. Regras gerais que produzam ruído no domínio são suprimidas por ID e caso documentado, não por filtragem silenciosa de toda a gramática.

### PT-004 — texto protegido

Antes da análise gramatical, mascarar com preservação de comprimento ou mapa de offsets:

- lances e casas;
- NAGs;
- `[%...]`;
- URLs, emails e caminhos;
- sentinelas internas;
- nomes identificados no original quando necessário.

Nenhuma sugestão pode cruzar um intervalo protegido.

### PT-005 — terminologia do glossário

O corretor não marca uma forma imposta por entrada aplicável do glossário sem ao menos indicar conflito. Se o motor gramatical discordar da terminologia, a ocorrência recebe estado `suppressed_by_glossary` para diagnóstico, não sublinhado para o usuário.

### PT-006 — apresentação

- ortografia: sublinhado ondulado vermelho;
- concordância/gramática: sublinhado ondulado azul ou âmbar;
- nunca depender somente da cor: tooltip/menu informa classe e mensagem;
- painel “Revisão linguística” lista ocorrências na ordem do texto;
- `F7` abre/navega pelo corretor; `Shift+F7` volta;
- menu oferece substituir, ignorar, explicar e criar regra;
- aplicar correção mantém undo/redo e marca a linha como alterada, não verificada.

### PT-007 — atualização assíncrona

A análise é feita fora da thread Tk, com debounce após digitação. Cada pedido recebe geração monotônica; resposta de geração antiga é descartada. Fechar ou trocar de linha cancela/ignora resultado pendente.

### PT-008 — desempenho

Orçamento inicial em máquina de referência:

- ortografia incremental: p95 ≤ 20 ms por linha;
- análise gramatical local de uma linha de até 1.000 caracteres: p95 ≤ 500 ms após aquecimento;
- nenhuma pausa da thread da UI acima de 50 ms;
- memória adicional documentada e medida;
- carga pesada preguiçosa, uma vez por processo.

Os valores devem ser recalibrados com o motor escolhido e registrados no benchmark.

### PT-009 — privacidade

O modo padrão é local. Um adaptador remoto, se algum dia existir, fica desligado por padrão, exige consentimento próprio e mostra exatamente que texto será enviado. Texto de livro nunca é enviado a serviço de correção público por conveniência silenciosa.

### PT-010 — falhas

Sem motor/dicionário, a UI mostra “Corretor indisponível” com motivo. Crash do corretor não fecha o editor, não altera texto e é registrado sem payload completo.

Se o LanguageTool falhar, o processo pode ser reiniciado uma vez sob controle. Persistindo a falha, o estado muda para “Somente ortografia”; não há chamada remota nem nova tentativa em laço.

### PT-011 — preferências

Configurações:

- ativar ortografia;
- ativar concordância;
- ativar sugestões de estilo;
- variante `pt-BR` (única inicialmente, explicitada);
- regras ignoradas;
- vocabulário pessoal exportável;
- verificação ao digitar ou apenas sob comando.

### PT-012 — corpus de aceite

Manter corpus versionado com:

- frases corretas de xadrez que não podem ser marcadas;
- erros reais anonimizados do histórico;
- concordância nominal e verbal;
- fragmentos sem sujeito explícito;
- citações, nomes, lances, casas e anotações;
- casos ambíguos que não devem gerar ocorrência;
- terminologia do glossário.

O corpus separa treino/ajuste de regressão final. Cada regra tem verdadeiros positivos, falsos positivos conhecidos e identificador estável.

### PT-013 — qualidade mínima

No corpus final:

- zero alteração automática;
- zero sugestão que altere notação ou intervalo protegido;
- precisão ≥ 95% nas ocorrências apresentadas como erro;
- recall reportado separadamente, sem sacrificar precisão;
- falsos positivos por 1.000 palavras reportados;
- tempo e memória reportados;
- avaliação humana com pelo menos os casos ambíguos mais frequentes.

## 9. Interface

### UI-001 — navegação

Destinos de primeiro nível: Biblioteca, Traduzir, Revisar, Glossário, Relatórios e Configurações. O log técnico é painel secundário.

### UI-002 — ações

Cada página tem uma ação primária. Ações destrutivas ficam separadas, rotuladas e confirmadas com impacto. Um registro central de comandos fornece rótulo, ícone, atalho, estado e handler para toolbar, menus e ajuda.

### UI-003 — acessibilidade

Jornadas críticas devem:

- funcionar integralmente por teclado;
- ter ordem de foco previsível e foco visível;
- expor nome, papel, estado e valor quando a toolkit permitir;
- continuar utilizáveis em 200% e 1366×768;
- não depender somente de cor;
- manter alvos de pelo menos 24×24 px e contraste mensurado.

### UI-004 — ícones

Usar uma única família local. Ações principais recebem ícone e texto. Controle somente com ícone exige convenção inequívoca, tooltip e nome acessível. Emoji não é ícone de produção.

## 10. Dados, segurança e operação

### DS-001 — diretório de dados

Instalado usa pasta gravável do usuário; portátil usa `dados`; fonte usa diretório do programa; variável explícita vence. Atualização nunca sobrescreve acervo.

### DS-002 — segredos

Windows usa DPAPI. Fora do Windows, armazenamento persistente inseguro não é silencioso: usar keyring, variável de ambiente ou aviso explícito.

### DS-003 — verificação

“Verificar meus dados” executa validações somente leitura, produz relatório e nunca usa o acervo real como cobaia destrutiva.

### DS-004 — dependências

Lock é a fonte do build. CI verifica vulnerabilidades, licenças e SBOM. Ações de CI são fixadas por SHA. Dependência nova do corretor exige licença compatível e medição do artefato.

## 11. Observabilidade

Eventos estruturados representam progresso, falha, rate limit, correção e publicação. O formatador gera texto humano. Logs não contêm chave, URL com texto, comentário integral por padrão ou caminho desnecessário.

Métricas locais mínimas:

- cache, chamadas, caracteres, retries, 403/429 e cooldown;
- tempo por fase;
- custo estimado/real;
- ocorrências linguísticas por classe, aceitas e ignoradas;
- regras de glossário acionadas e sombreadas;
- tempo humano por 100 linhas.

## 12. Testes de aceitação

### TA-001 — glossário

Mesma expressão em `pt` e `it`, e como limpeza/sugestão, sobrevive a deduplicação. Alteração externa durante edição produz conflito e não toca a variante vizinha.

### TA-002 — saída

Falha injetada em abertura, escrita, flush, substituição, cópia e manifesto nunca deixa PGN final parcial.

### TA-003 — contexto

Texto idêntico em dois lances semanticamente distintos segue a política registrada e não herda contexto por acidente.

### TA-004 — corretor

Em `As pretas tem uma posiçao ativa depois de 13.Cd4 [%eval +0.35].`, o corretor:

- sugere `posição`;
- sugere `têm`;
- não marca `13.Cd4` nem `[%eval +0.35]`;
- aplica cada sugestão individualmente com undo;
- não marca a linha como verificada.

### TA-005 — ambiguidade

Fragmentos corretos como `Com vantagem para as brancas.` e citações com nomes não geram concordância inventada.

### TA-006 — UI

Selecionar arquivo, estimar, traduzir, abrir pendentes, corrigir com F7 e salvar é possível sem mouse em 200% de escala.

### TA-007 — rede

Duas instâncias respeitam cota global; 429 com `Retry-After` impede nova chamada antes do prazo; 403 interrompe o motor experimental sem fallback silencioso.

## 13. Migração

1. corrigir identidade do glossário e escrita atômica antes de mudar formatos;
2. introduzir objetos tipados mantendo adaptadores para tuplas antigas;
3. implementar ortografia sugerível sobre o `spylls` existente;
4. avaliar e empacotar o adaptador gramatical local escolhido;
   - protótipo: LanguageTool local em loopback, sem entrar ainda no instalador;
   - medir precisão/recall, p50/p95, RAM/CPU e tamanho;
   - auditar JARs, recursos linguísticos e runtime Java por versão;
5. lançar concordância atrás de preferência, coletando somente métricas locais;
6. ativar por padrão após cumprir PT-013;
7. migrar interface por jornadas, preservando atalhos e comportamento coberto;
8. aposentar adaptadores legados somente após exportação/migração verificável.

## 14. Definition of Done

Um requisito está concluído somente quando:

- comportamento e erro estão implementados;
- teste automatizado cobre caminho feliz e falha relevante;
- acessibilidade e thread da UI foram verificadas quando aplicável;
- desempenho foi medido quando há orçamento;
- documentação e migração foram atualizadas;
- build empacotado contém dependências/licenças corretas;
- CI obrigatório passa;
- nenhuma garantia anterior foi enfraquecida sem decisão registrada.
