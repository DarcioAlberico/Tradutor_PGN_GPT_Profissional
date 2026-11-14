# Pesquisa: risco do mecanismo de tradução Google

Pesquisa realizada em 23 de outubro de 2026. Foram usadas somente fontes
primárias do Google e o código-fonte deste repositório. Isto é uma análise
técnica e contratual preliminar, não um parecer jurídico.

## Conclusão executiva

O motor chamado de **Google** pelo programa tem exposição operacional e
contratual **relevante, mas sem probabilidade quantificável**. Ele não usa a Cloud
Translation API documentada: automatiza um endpoint sem autenticação,
`/translate_a/single`, com `client=gtx`. O Google proíbe expressamente o uso de
APIs não documentadas sem permissão em sua política de dados de APIs; os Termos
das APIs exigem acesso pelos meios descritos na documentação. A aplicação
contratual exata ao endpoint anônimo requer cautela, como explicado na seção 2.1.
Diminuir a frequência das requisições pode reduzir falhas e bloqueios, mas
**não regulariza o mecanismo**.

Como inferência técnica, o risco imediato mais plausível não é o “ban de uma
conta Google”: o fluxo atual não autentica conta, projeto ou chave. O risco
imediato é receber throttling,
bloqueio por IP ou mudança/remoção do endpoint e, com isso, perder o motor
padrão do programa. Não existe fonte oficial que permita atribuir uma
probabilidade a esses eventos ou afirmar que o uso anônimo de `client=gtx`
causará ban de uma conta.

A correção estrutural é oferecer a **Cloud Translation oficial (v2 ou v3)**,
com credenciais, cobrança, quotas configuráveis e mensagens transparentes. O
endpoint `gtx`, se mantido durante a transição, deve ser identificado como
experimental/não oficial, ficar desabilitado por padrão e nunca ser apresentado
como uma API gratuita suportada pelo Google.

## 1. O que o programa faz hoje

Fatos observados no repositório:

- `tradutor_pgn/translation_api.py:192-207` envia um `GET` para
  `https://translate.googleapis.com/translate_a/single`, sem chave, token ou
  projeto. Os parâmetros são `client=gtx`, `sl`, `tl`, `dt=t` e `q=<texto>`.
- O provedor é registrado como `google-gtx`
  (`tradutor_pgn/translation_api.py:25`).
- Os lotes normais têm alvo de 4.800 caracteres
  (`tradutor_pgn/pgn_utils.py:650-702`); comentários individuais maiores podem
  ultrapassar esse alvo e são divididos pela camada de rede em trechos de até
  5.000 (`tradutor_pgn/app_config.py:53`; `translation_api.py:125-152,258-279`).
- Uma `requests.Session` é reutilizada durante a execução
  (`tradutor_pgn/translation_worker.py:285,382-390`). O processamento é
  sequencial, não concorrente.
- O intervalo normal é sorteado entre 0,04 e 0,12 segundo no laço do worker
  (`tradutor_pgn/app_config.py:60`; `translation_worker.py:1134-1135`). Isso
  corresponde teoricamente a aproximadamente **500–1.500 requisições por
  minuto** enquanto houver trabalho. Com lotes cheios, a vazão teórica chega a
  aproximadamente **2,4–7,2 milhões de caracteres por minuto**. São limites
  matemáticos do caminho normal com uma requisição por lote, não medições de
  produção nem limites globais. Latência, cache e lotes menores os reduzem;
  chunks internos e retries não recebem essa mesma pausa entre cada chamada HTTP.
- Há no máximo três tentativas para 429, 500, 502, 503, 504 e exceções de rede.
  Outros 5xx não são repetidos. O 429 usa backoff exponencial
  com jitter e faz o intervalo futuro crescer; o teto adaptativo equivale a
  2,4–7,2 segundos (`translation_api.py:28-32,45-92`).
- O programa não lê o cabeçalho `Retry-After`. HTTP 403 não é repetido e recebe
  apenas a mensagem genérica de erro (`translation_api.py:218-234`). O ritmo
  aprendido também não é compartilhado entre duas instâncias nem persiste
  entre execuções.
- Cache e deduplicação já evitam chamadas repetidas
  (`translation_worker.py:798-804,833-873`), e três lotes consecutivos sem
  resposta acionam um disjuntor (`translation_worker.py:973-1013`). Essas são
  boas proteções operacionais, mas não mudam a natureza não documentada do
  endpoint.
- Como `q` está na query string de um `GET`, o texto do PGN integra a URL. HTTPS
  protege o tráfego em rede, mas URLs são mais suscetíveis a aparecer em logs de
  clientes, proxies e ferramentas de diagnóstico do que um corpo `POST`. O
  caminho de erro de rede registra a exceção como texto
  (`translation_api.py:236-238`), que pode incluir URL e query string. Não há
  redaction explícita nessa camada; isso deve ser verificado mesmo sem proxies.

Essas observações são de análise estática. Não foram enviadas traduções ao
endpoint nem coletados logs de produção nesta pesquisa. A presença de tratamento
para 429 não prova que um bloqueio tenha ocorrido.

## 2. O que o Google documenta

### 2.1 O endpoint atual não é a API oficial documentada

A referência da Cloud Translation Basic documenta
`POST https://translation.googleapis.com/language/translate/v2`, aceita uma
chave válida ou OAuth e lista os escopos de autorização. Ela não documenta
`GET /translate_a/single`, `client=gtx` ou o formato de resposta usado pelo
programa. [Método oficial `translate` v2](https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate)

A v3 documenta `POST https://translate.googleapis.com/v3/{parent}:translateText`,
com projeto/localização, autorização OAuth/IAM e corpo JSON. Portanto, o domínio
`translate.googleapis.com` por si só não define se uma integração é oficial:
o caminho, método e autenticação são decisivos. O código atual não faz scraping
de HTML nem controla um navegador; automatiza um endpoint JSON não documentado.
[Método oficial `translateText` v3](https://docs.cloud.google.com/translate/docs/reference/rest/v3/projects.locations/translateText)

Os Termos das APIs dizem que o acesso deve ocorrer somente pelos meios descritos
na documentação da API. A política de dados das APIs também proíbe APIs não
documentadas sem permissão expressa. **Ressalva de escopo:** a introdução dessa
política diz que ela rege o acesso a dados de usuários Google; o fluxo anônimo
atual não solicita esses dados via OAuth. Sua cláusula reforça a orientação do
Google, mas não basta, isoladamente, para concluir de forma jurídica definitiva
que este aplicativo específico viola essa política. Não foi encontrada
autorização oficial para `client=gtx` nas referências consultadas.
[Termos das APIs, seção 2.c](https://developers.google.com/terms/#section_2_using_our_apis)
e [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy#deceptive-or-unauthorized-use-of-google-api-services-is-prohibited)

### 2.2 Limites, bloqueio e suspensão

Os Termos das APIs permitem ao Google estabelecer e aplicar limites, proíbem
contorná-los e permitem suspender o acesso de um cliente de API sem aviso quando
houver suspeita razoável de violação. [Google APIs Terms of Service,
seções 2.d e 3.a](https://developers.google.com/terms/)

Os Termos gerais proíbem interferir nos sistemas ou contornar proteções, bem
como usar meios automatizados contra instruções legíveis por máquina. Eles
preveem suspensão ou encerramento do acesso por violação material/repetida ou
conduta que cause dano. Isso não prova que o fluxo atual gera automaticamente
uma suspensão; define apenas as faculdades contratuais do Google.
[Termos de Serviço do Google](https://policies.google.com/terms)

A cláusula de automação é condicionada ao descumprimento de instruções legíveis
por máquina; ela não é uma proibição genérica de toda automação. Esta pesquisa
não comprovou qual instrução `robots.txt` rege `/translate_a/single`, nem usa
essa cláusula para afirmar que todo uso do Google Tradutor web é proibido.

Na Cloud Translation oficial, o Google publica quotas, recomenda cerca de 5 mil
caracteres por requisição e informa, atualmente, 6 milhões de caracteres por
minuto por projeto e por usuário para o modelo geral. A quota v2 publicada é
300 mil requisições por minuto por projeto, e a v3 publica 6 mil; no Basic com
chave, o IP do cliente é usado para aplicar a quota por usuário. Excesso de quota da Translation é
documentado como HTTP 403 com `Daily Limit Exceeded` ou
`User Rate Limit Exceeded`. [Quotas e limites da Cloud Translation](https://docs.cloud.google.com/translate/quotas)

Os 5 mil caracteres são uma recomendação, não o máximo oficial absoluto: a
documentação distingue 100 mil bytes por requisição no Basic e 30 mil code points no
Advanced. Os números publicados são padrões, sujeitos à quota efetiva do
projeto e ao método/modelo escolhido. [Limites de conteúdo](https://docs.cloud.google.com/translate/quotas#content_limit_per_request)

Esses valores **não podem ser tratados como quota do endpoint `gtx`**. Eles só
servem como referência para a API oficial autenticada; não foram encontrados
quota, SLA ou contrato específicos para o caminho usado pelo programa.

### 2.3 Dados e privacidade

Para a Cloud Translation oficial, o Google declara que usa o conteúdo somente
para prestar o serviço, não o disponibiliza ao público ou a terceiros, mantém o
texto brevemente em memória e não o usa para treinar/melhorar os modelos de
tradução. Também oferece endpoints regionais na edição Advanced.
[FAQ oficial sobre uso de dados](https://docs.cloud.google.com/translate/data-usage)

**Incerteza importante:** essa FAQ se refere nominalmente à Cloud Translation
API. Não há base para estender as mesmas garantias contratuais ao endpoint
anônimo `gtx`. O aplicativo deve informar que envia os comentários dos PGNs a um
serviço externo e evitar sugerir garantias de privacidade que não possui.

## 3. Avaliação de risco

| Risco | Avaliação | Natureza | Justificativa |
|---|---:|---|---|
| Quebra ou remoção do endpoint | Impacto alto; probabilidade desconhecida | Inferência | Não foi encontrado contrato, versão pública ou SLA específico para esse caminho. |
| Throttling/429 ou bloqueio por IP | Exposição relevante; probabilidade desconhecida | Inferência técnica, sem reprodução | Ritmo teórico elevado no caminho normal e sem quota publicada para `gtx`; código trata 429, mas isso não comprova ocorrência. Instâncias no mesmo IP não se coordenam. |
| Incompatibilidade com termos de acesso | Relevante | Texto contratual + aplicação prudencial | Termos exigem meios documentados; política de dados contém proibição expressa, com a ressalva de escopo da seção 2.1. |
| Ban da conta Google | Não demonstrado no fluxo atual | Incerteza | Não há autenticação de conta/projeto. Não foi encontrada política oficial específica para `gtx` que permita afirmar ou quantificar ban de conta. |
| Suspensão de projeto na API oficial | Prevista por política; probabilidade desconhecida | Fato condicionado | Projetos podem ser suspensos por violação de ToS/políticas; excesso de quota documentado é erro de requisição e não demonstra, por si só, suspensão. [Diretrizes de suspensão](https://docs.cloud.google.com/resource-manager/docs/project-suspension-guidelines) |
| Exposição de texto em URLs | Média | Inferência técnica | O PGN vai no parâmetro `q` de um GET; a API oficial aceita POST. O impacto depende do conteúdo e da infraestrutura local. |

## 4. Recomendações priorizadas

### P0 — corrigir antes de distribuir amplamente

1. **Implementar um provedor oficial Cloud Translation.** Preferir v3 Advanced
   quando glossário nativo, processamento em lote ou localização regional dos
   dados justificarem o custo; usar v2 Basic para uma migração menor. Configurar
   projeto, billing e quota; v2 aceita chave ou OAuth, enquanto v3 requer
   autenticação OAuth/IAM e não aceita chave de API. Usar ADC quando adequado
   ao ambiente, sem embutir credenciais distribuídas com o programa.
   [Comparação das edições](https://docs.cloud.google.com/translate/docs/api-overview)
   O Google recomenda bibliotecas oficiais,
   que já integram autenticação e retries.
   [Visão geral de uso da API](https://docs.cloud.google.com/translate/docs/reference/api-overview)
2. **Mudar o padrão para o provedor oficial ou para escolha explícita.** Rotular
   `google-gtx` como “Google não oficial/experimental”, desabilitado por padrão,
   com aviso de indisponibilidade, termos e envio externo de dados.
3. **Não tentar evadir bloqueios.** Não alternar proxies/IPs, falsificar cliente,
   resolver CAPTCHA automaticamente nem fragmentar tráfego para contornar
   limites. Isso aumenta, em vez de reduzir, o risco contratual.

### P1 — resiliência durante a transição

1. Honrar `Retry-After` quando presente e usar exponential backoff com full
   jitter para 429/5xx.
2. Distinguir 403, 429 e indisponibilidade nas mensagens e no disjuntor. No
   endpoint não oficial, não presumir a causa de um 403. Na API oficial,
   interpretar a resposta para distinguir quota de autenticação/permissões;
   403 não é sinônimo de ban. Persistindo o erro, interromper e informar o usuário.
3. Persistir uma janela de resfriamento entre execuções e coordenar um limite
   global entre instâncias locais. Uma segunda janela hoje volta ao ritmo máximo.
4. Tornar o ritmo conservador por padrão e configurável para baixo. O objetivo
   é estabilidade, não descobrir empiricamente o limite de um endpoint sem
   quota publicada.
5. Medir localmente requisições/minuto, caracteres/minuto, 429, 403, tentativas,
   tempo de espera e taxa de cache. Exibir isso no resumo e no diagnóstico, sem
   enviar telemetria externa por padrão.
6. Trocar GET por POST somente no provedor oficial documentado. Alterar o verbo
   do endpoint privado por tentativa não o torna suportado.

### P2 — produto, custo e glossário

1. Exibir estimativa de caracteres e custo antes da Cloud Translation, como o
   programa já faz para LLMs. A tabela oficial atual concede crédito mensal aos
   primeiros 500 mil caracteres de texto NMT (crédito de US$ 10) e lista
   US$ 20 por milhão no consumo padrão depois disso; outros modelos e métodos
   têm cobrança própria. Preços mudam e devem vir de configuração/documentação
   atualizada, não ficar
   codificados como promessa. [Preços oficiais](https://cloud.google.com/translate/pricing)
2. Manter o glossário local independente do provedor. Para v3, avaliar um
   adaptador que exporte apenas regras compatíveis ao glossário oficial e
   preserve localmente regras de limpeza, regex, escopo por idioma e revisão.
   A Cloud Translation Advanced oferece glossários e batch assíncrono; isso não
   substitui automaticamente a semântica atual do programa.
   [Visão geral da Cloud Translation](https://docs.cloud.google.com/translate/docs/api-overview)
3. Acrescentar uma tela curta “Privacidade e provedores”: quais textos saem da
   máquina, para qual fornecedor, credenciais usadas, retenção documentada e
   link dos termos. Não enviar caminho de arquivo, banco, chave ou contexto além
   do necessário.
4. Cobrir por testes: `Retry-After`, 403 terminal, cooldown persistente,
   coordenação entre instâncias, redaction de URLs/textos nos logs, contadores de
   quota e seleção/fallback sem troca silenciosa de provedor.

## 5. Decisão sugerida para o roadmap

Adotar a Cloud Translation oficial como a única integração denominada
“Google”. Durante uma versão de transição, manter `google-gtx` somente atrás de
uma opção avançada com consentimento informado; depois, removê-lo. Essa decisão
elimina a dependência mais frágil, torna quota e custo observáveis e permite usar
garantias documentadas de tratamento de dados. O cache, a deduplicação, a
revisão humana e o glossário local continuam valiosos em todos os provedores.

## Fontes primárias

- [Google APIs Terms of Service](https://developers.google.com/terms/)
- [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
- [Google Terms of Service](https://policies.google.com/terms)
- [Cloud Translation v2: método `translate`](https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate)
- [Cloud Translation v3: método `translateText`](https://docs.cloud.google.com/translate/docs/reference/rest/v3/projects.locations/translateText)
- [Cloud Translation: autenticação REST](https://docs.cloud.google.com/docs/authentication/rest)
- [Cloud Translation: quotas e limites](https://docs.cloud.google.com/translate/quotas)
- [Cloud Translation: visão geral de uso da API](https://docs.cloud.google.com/translate/docs/reference/api-overview)
- [Cloud Translation: uso de dados](https://docs.cloud.google.com/translate/data-usage)
- [Cloud Translation: preços](https://cloud.google.com/translate/pricing)
- [Google Cloud: diretrizes de suspensão de projetos](https://docs.cloud.google.com/resource-manager/docs/project-suspension-guidelines)
