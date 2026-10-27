# Assistente de escrita em português — design

## Intenção

Transformar o corretor ortográfico existente em um assistente de escrita pt-BR
com sugestões acionáveis, concordância nominal e verbal de alta confiança e uma
experiência de revisão contínua. O texto do usuário nunca é enviado à internet e
nenhuma correção é aplicada sem gesto explícito.

Este design concretiza PT-001 a PT-013 de `REVISAO_GERAL_SPEC.md` e preserva o
filtro ortográfico já medido em `prose_spellcheck.py`.

## Objetivos

- preservar ortografia local com `spylls` e os filtros existentes;
- acrescentar gramática/concordância com LanguageTool local em pt-BR;
- oferecer explicação, até cinco sugestões e ações por ocorrência;
- proteger SAN, NAGs, tags `[%...]`, nomes e termos do glossário;
- manter a UI responsiva e descartar resultados obsoletos;
- funcionar offline em instalação autocontida;
- degradar de modo visível e seguro para “Somente ortografia”;
- medir precisão, latência, memória e impacto do empacotamento antes de liberar
  concordância como funcionalidade estável.

## Não objetivos

- correção criativa, reescrita de estilo ou alteração de sentido;
- LanguageTool remoto ou qualquer envio de comentários a terceiros;
- habilitar concordância automaticamente para instalações existentes;
- aceitar silenciosamente toda sugestão do motor;
- criar regras de glossário automaticamente ao corrigir uma ocorrência;
- suportar gramática de outros idiomas neste recorte.

## Antiobjetivos

- travar a thread do Tk esperando Java, rede local ou dicionário;
- expor objetos internos de `spylls` ou LanguageTool aos editores;
- aplicar offsets calculados sobre uma versão antiga do texto;
- mascarar ausência/crash do motor como “nenhum erro encontrado”;
- desativar uma categoria inteira para esconder falso positivo pontual;
- manter payload de texto em logs ou métricas.

## Abordagens consideradas

### 1. Processo auxiliar persistente em loopback — escolhida

Um runtime Java reduzido inicia um servidor LanguageTool local numa porta livre,
preso a loopback. O processo é reutilizado entre análises e gerenciado pelo
aplicativo. Esta opção isola a JVM, reduz latência depois do aquecimento, permite
health check/reinício e mantém uma interface Python pequena.

### 2. Processo Java por análise — rejeitada

Simplifica o ciclo de vida, mas o custo de inicialização da JVM torna digitação
e navegação impraticáveis e aumenta o risco de processos órfãos.

### 3. Ponte JVM dentro do Python — rejeitada

Evita HTTP local, mas acopla dois runtimes no mesmo processo, piora crash
isolation, empacotamento e testes. O ganho não compensa a superfície nova.

## Módulo profundo e seam principal

O módulo `PortugueseWritingAssistant` é independente de Tk. Sua interface é a
superfície única usada por editores e testes:

```python
@dataclass(frozen=True)
class WritingRequest:
    text: str
    text_version: int
    target_language: str
    source_text: str = ""
    glossary_terms: frozenset[str] = frozenset()
    session_ignored_words: frozenset[str] = frozenset()
    disabled_rule_ids: frozenset[str] = frozenset()
    grammar_enabled: bool = False

@dataclass(frozen=True)
class WritingIssue:
    issue_id: str
    rule_id: str
    category: Literal[
        "SPELLING", "NOMINAL_AGREEMENT", "VERBAL_AGREEMENT",
        "GRAMMAR", "PUNCTUATION", "REPEATED_WORD"
    ]
    start: int
    end: int
    original: str
    message: str
    explanation: str
    suggestions: tuple[str, ...]
    severity: Literal["error", "warning"]
    provider: str
    text_version: int
    state: Literal["active", "suppressed_by_glossary"] = "active"

@dataclass(frozen=True)
class WritingResult:
    text_version: int
    issues: tuple[WritingIssue, ...]
    mode: Literal["full", "spelling_only", "unavailable"]
    diagnostic: str = ""

class PortugueseWritingAssistant:
    def analyze(self, request: WritingRequest) -> WritingResult: ...
    def status(self) -> AssistantStatus: ...
    def shutdown(self) -> None: ...
```

O módulo esconde tokenização, proteção, cache, providers, supressões,
priorização, deduplicação e lifecycle do processo. Callers conhecem somente o
pedido, o resultado normalizado e o estado.

## Adapters internos

### `SpyllsAdapter`

- reaproveita o dicionário, carga assíncrona, `suggestions` e filtros atuais;
- devolve `WritingIssue` em vez de spans crus;
- limita sugestões a cinco com ordem estável;
- considera vocabulário da origem, glossário, vocabulário pessoal e sessão;
- continua disponível quando gramática está desligada ou Java falha.

### `LanguageToolLocalAdapter`

- inicia somente quando “Verificar concordância” está habilitado;
- usa `language=pt-BR` explícito em `POST /v2/check`;
- conecta apenas a `127.0.0.1` numa porta dinâmica reservada pelo gerenciador;
- tem timeout de inicialização e por análise;
- valida PID/processo, health check e versão esperada;
- nunca usa API remota como fallback;
- normaliza categorias e rule IDs para `WritingIssue`;
- reinicia no máximo uma vez por falha; uma segunda falha muda o modo para
  `spelling_only` durante a sessão;
- encerra o filho no fechamento normal e tenta terminar processo órfão que ele
  próprio iniciou, sem tocar instâncias externas.

### `ProtectedTextAdapter`

Antes dos providers, identifica intervalos que não podem ser corrigidos:

- SAN, casas, roques, números de lance e NAGs;
- tags `[%eval]`, `[%clk]`, `[%cal]`, `[%csl]` e demais anotações;
- URLs, e-mails e identificadores técnicos já reconhecidos pelo produto;
- termos aplicáveis do glossário;
- nomes presentes no texto-fonte.

Providers podem analisar uma projeção mascarada, mas os offsets finais sempre
apontam para o texto real. Ocorrência que cruza intervalo protegido é descartada;
conflito gramatical exatamente sobre termo do glossário é mantido internamente
como `suppressed_by_glossary` para diagnóstico e não ganha sublinhado.

## Processo Java e distribuição

- fixar versões exatas de LanguageTool e do JDK usados no build;
- gerar runtime mínimo com `jlink`, incluindo apenas módulos necessários;
- distribuir runtime, JARs, dados pt-BR e licenças no instalável e portátil;
- o executável localiza recursos tanto em desenvolvimento quanto sob
  `_MEIPASS`/onedir;
- gerar SBOM e registrar hashes dos artefatos de terceiros;
- o build falha se runtime, JAR, dados pt-BR ou licenças estiverem ausentes;
- medir tamanho do instalador, RAM em repouso/pico e tempo de primeiro início;
- atualizações de LanguageTool/Java acontecem somente em release do programa,
  nunca por download automático em runtime.

## Lifecycle e concorrência

1. Ortografia carrega como hoje, fora da thread Tk.
2. Concordância desligada não inicia Java.
3. Ao habilitar, o gerenciador inicia o sidecar em thread de trabalho, aguarda
   health check e publica estado `starting` → `full` ou `spelling_only`.
4. Cada edição incrementa `text_version` e agenda análise com debounce.
5. Há no máximo uma análise ativa por janela e uma pendente mais recente.
6. Resultado só é aplicado se janela, registro, idioma, texto e versão ainda
   coincidirem.
7. Navegar ou fechar cancela logicamente o resultado; nenhuma callback tardia
   acessa widget destruído.
8. O sidecar é compartilhado pelo processo, mas pedidos e resultados não se
   misturam entre janelas.

Metas: ortografia incremental p95 ≤ 20 ms por linha; gramática em background
p95 ≤ 500 ms por comentário após aquecimento; nenhuma espera Java na thread Tk.

## Experiência de interface

### Layout escolhido

Painel lateral fixo “Revisão linguística”, recolhível manualmente e
automaticamente em telas estreitas. O texto continua no centro.

- vermelho ondulado: ortografia;
- azul/âmbar ondulado: concordância/gramática;
- painel lista ocorrências na ordem do texto;
- cabeçalho mostra contagem, posição e modo (`Completo`, `Somente ortografia`,
  `Iniciando`, `Indisponível`);
- selecionar item foca e revela o intervalo correspondente;
- `F7` avança e `Shift+F7` volta;
- mouse e teclado abrem até cinco sugestões e explicação curta.

### Ações

- **Aplicar:** substitui somente a ocorrência atual;
- **Aplicar todas iguais neste livro:** ação secundária, exige confirmação e
  prévia da quantidade, e só altera a mesma forma original com a mesma sugestão;
- **Ignorar uma vez:** oculta apenas aquele `issue_id` naquela versão;
- **Ignorar na sessão:** ignora a palavra/regra até fechar o programa;
- **Adicionar ao vocabulário pessoal:** global para todos os livros;
- **Desativar esta regra:** persistente por `rule_id`, reversível em
  Configurações.

Aplicação em massa não cria regra de glossário, não atravessa livros e é uma
única ação de desfazer por livro. Antes de substituir, cada intervalo é
revalidado contra texto e versão atuais; divergência aborta sem alteração
parcial.

## Preferências e dados do usuário

Configurações novas:

- `spelling_enabled` — padrão `true`;
- `grammar_enabled` — padrão `false`, escolhido pelo usuário;
- categorias visíveis;
- rule IDs desativadas;
- debounce/intensidade somente se houver necessidade medida.

O vocabulário pessoal é global, armazenado na pasta de dados em formato
versionado e escrito atomicamente. Comparação normaliza Unicode e caixa sem
alterar a grafia exibida. Configurações permitem listar/remover palavras e
reativar regras. Alteração invalida imediatamente caches pertinentes.

## Aplicação, histórico e desfazer

Toda sugestão passa pela mesma operação editorial usada pelo campo de tradução,
preservando `dirty`, histórico e Ctrl+Z. A ocorrência registra localmente
categoria, rule ID e ação (`aplicada`, `ignorada`, `vocabulário`), mas nunca o
texto completo. Salvar a tradução persiste o texto corrigido pelo fluxo normal.

## Falhas e diagnósticos

- dicionário ausente: `Indisponível — dicionário pt-BR ausente`;
- concordância desligada: `Somente ortografia` sem iniciar Java;
- sidecar iniciando: ortografia continua utilizável;
- crash/timeout: uma reinicialização, depois `Somente ortografia`;
- resposta inválida/offset impossível: descartar resposta e registrar regra,
  versão e erro, sem payload;
- encerramento: matar apenas o processo filho identificado pelo gerenciador;
- nenhuma falha do corretor fecha editor, muda texto ou bloqueia salvamento.

## Privacidade e segurança

- HTTP exclusivamente em loopback;
- porta não pública e token efêmero por processo quando suportado pelo servidor;
- nenhum comentário em log, métrica, crash report ou arquivo temporário;
- sem telemetria e sem LanguageTool remoto;
- caminhos do runtime/JAR são recursos confiáveis do aplicativo, não entrada do
  usuário;
- argumentos do processo são lista, nunca comando de shell concatenado.

## Corpus e critérios de aceite

Criar corpus versionado e revisado manualmente, separado do texto protegido por
direitos, contendo:

- frases corretas de xadrez;
- erros ortográficos, inclusive acentos/hífens;
- concordância nominal e verbal;
- palavras repetidas e pontuação de alta confiança;
- SAN, NAGs, tags, nomes e termos do glossário;
- fragmentos deliberadamente ambíguos que não devem gerar alerta;
- acentos, emoji e offsets Unicode.

Aceite antes de considerar concordância estável:

- precisão ≥ 95% das ocorrências apresentadas como erro;
- recall ≥ 80% no subconjunto de alta confiança;
- zero alteração/sugestão dentro de intervalos protegidos;
- sugestões de ortografia presentes para ≥ 95% dos typos do corpus;
- nenhuma correção automática sem gesto;
- metas de latência cumpridas em corpus pequeno, médio e grande;
- crash/reinício/fallback e callbacks tardias cobertos em janelas reais.

## Testes e gates

- testes puros da interface e normalização com adapters falsos;
- contratos compartilhados para Spylls e LanguageTool;
- servidor HTTP falso para lifecycle, timeout, reinício e respostas inválidas;
- integração real com LanguageTool empacotado no CI/release Windows;
- testes Tk do painel, atalhos, seleção, desfazer e navegação;
- property-based tests para offsets Unicode, proteção e aplicação de sugestões;
- testes de processo órfão e encerramento;
- smoke test do instalável e portátil sem Java do sistema;
- comparação de tamanho/RAM/tempo registrada no roadmap;
- Ruff, mypy, suíte completa e `git diff --check` bloqueantes.

## Migração e rollout

1. Introduzir tipos, módulo e adapter Spylls mantendo a UI atual.
2. Implementar corpus, proteção e ações ortográficas.
3. Prototipar e medir LanguageTool + jlink em desenvolvimento.
4. Integrar sidecar, preferência desligada por padrão e fallback.
5. Entregar painel lateral e ações completas.
6. Integrar build autocontido, licenças, SBOM e smoke tests.
7. Só declarar concordância estável se o corpus atingir os limites; caso
   contrário, manter a preferência como experimental e registrar regras
   problemáticas por ID.

## Decisões do usuário

- LanguageTool e Java reduzido entram no pacote, mesmo aumentando o tamanho.
- Arquitetura: processo auxiliar persistente em loopback.
- UI: painel lateral fixo/recolhível.
- Vocabulário pessoal: global.
- Concordância: somente quando o usuário habilitar nas configurações.
- Aplicação padrão: ocorrência atual; opção separada para todas as ocorrências
  idênticas no livro.

## Decisões deixadas ao construtor

- versão exata do LanguageTool/JDK, após auditoria de licença e compatibilidade;
- conjunto mínimo de módulos `jlink`, determinado por `jdeps` e smoke test;
- debounce exato, dentro das metas medidas;
- cores finais adaptadas aos temas, desde que mantenham contraste e distinção
  além da cor;
- armazenamento interno das métricas agregadas locais, reutilizando a camada de
  configurações/banco existente sem guardar texto.
