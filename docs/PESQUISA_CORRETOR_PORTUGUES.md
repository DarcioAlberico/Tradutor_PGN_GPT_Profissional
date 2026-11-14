# Pesquisa: corretor ortográfico e gramatical em português

## Decisão recomendada

Para entregar sugestões de **ortografia, gramática e concordância em pt-BR**, a opção mais viável é integrar o **LanguageTool local** como um processo auxiliar, acessado por uma interface interna independente de fornecedor. O corretor Hunspell/spylls que o programa já possui deve continuar existindo como _fallback_ ortográfico leve.

O LanguageTool remoto não deve ser o padrão: além de enviar o texto traduzido a terceiros, a API pública gratuita publica limites de uso incompatíveis com processamento transparente de PGNs grandes. spaCy e Stanza são analisadores linguísticos, não corretores prontos; adotá-los como motor principal transferiria para este projeto a criação, validação e manutenção das regras de concordância.

A recomendação é condicionada a um protótipo mensurado. O projeto não deve prometer qualidade de concordância, tamanho do instalador ou consumo de memória antes de testar a distribuição local escolhida em um corpus real de comentários de xadrez.

## Estado atual do programa

O programa já possui uma camada ortográfica local coerente:

- `tradutor_pgn/prose_spellcheck.py` carrega, fora da thread da interface, um par Hunspell `pt_BR.dic`/`pt_BR.aff` por meio do spylls;
- palavras do texto de origem, termos impostos pelo glossário e tokens de notação enxadrística são filtrados para reduzir falsos positivos;
- `spylls>=0.1.7` está declarado no `pyproject.toml` e em `requirements.txt`;
- o `.spec` do PyInstaller inclui o import condicional, os dicionários e os avisos de licença;
- o pacote atual acrescenta aproximadamente 5,55 MB de dados Hunspell (`.dic` + `.aff`), além da licença e documentação.

Essa camada reconhece palavras e gera sugestões lexicais. Ela **não analisa relações entre palavras** e, portanto, não detecta de forma geral erros como “as peça está presa”. A nova funcionalidade deve complementar essa base, não fingir que Hunspell resolve concordância.

## Alternativas avaliadas

### 1. LanguageTool local

O LanguageTool se apresenta como verificador de gramática, estilo e ortografia e oferece um servidor HTTP local com o endpoint `POST /v2/check`. A documentação do servidor local exige Java 8 ou superior. No Windows, a detecção automática tem limitações porque o suporte a fastText não está disponível; além disso, a especificação da API orienta informar variantes como `pt-BR` para habilitar a verificação ortográfica correta. O aplicativo deve, portanto, enviar explicitamente `language=pt-BR`, sem autodetecção. Fontes: [documentação de desenvolvimento](https://dev.languagetool.org/), [servidor HTTP local](https://dev.languagetool.org/http-server) e [especificação oficial da API](https://languagetool.org/http-api/swagger-ui/).

Vantagens:

- oferece regras prontas de gramática e estilo, incluindo uma base real para concordância;
- funciona inteiramente no computador do usuário;
- a API HTTP cria um limite arquitetural claro entre a interface Python e o motor;
- falhas ou reinícios do motor podem ser isolados sem derrubar a janela;
- o texto não precisa sair da máquina.

Limitações:

- a edição local básica não equivale aos recursos de IA/nuvem do serviço comercial;
- requer Java e arquivos de dados próprios;
- o primeiro início, RAM e tamanho da distribuição serão maiores que os do spylls;
- regras gerais podem marcar SAN, nomes próprios e terminologia enxadrística; é indispensável medição no domínio;
- o processo auxiliar precisa de ciclo de vida, diagnóstico, timeout e encerramento controlados.

O núcleo declara licença LGPL-2.1-or-later, mas o próprio repositório alerta que recursos podem ter licenças distintas. A versão exata e todos os artefatos redistribuídos devem entrar no inventário de terceiros e no pacote de avisos: [README oficial](https://github.com/languagetool-org/languagetool/blob/master/README.md) e [POM oficial](https://github.com/languagetool-org/languagetool/blob/master/pom.xml).

#### Empacotamento Windows/PyInstaller

O desenho recomendado é distribuir o LanguageTool como processo auxiliar, e não tentar incorporá-lo ao processo Python. O PyInstaller empacota o cliente e deve copiar JARs, recursos e, se a decisão do produto for uma instalação autocontida, um runtime Java reduzido. O PyInstaller exige que dados e metadados não descobertos automaticamente sejam coletados de forma explícita: [documentação oficial de hooks](https://pyinstaller.org/en/stable/hooks.html).

Há duas variantes de distribuição:

1. **JRE externo:** instalador menor, mas introduz pré-requisito, variação de versão e suporte mais difícil.
2. **Runtime Java embarcado:** experiência previsível e offline, ao custo de instalador maior, mais artefatos para atualizar e maior superfície de segurança.

O servidor deve escutar somente em loopback, numa porta livre escolhida em tempo de execução, sem a opção `--public`. A inicialização deve aguardar um _health check_, registrar logs sem texto do usuário, aplicar timeout e encerrar o processo filho ao fechar o aplicativo. A estimativa corporativa de 8 GB de RAM/25 GB publicada para um servidor com todas as línguas não representa uma distribuição pt-BR dedicada; tamanho e memória devem ser medidos no protótipo, não extrapolados: [visão técnica oficial](https://languagetool.org/pdf/LanguageTool_Technischer_Ueberblick.pdf).

### 2. LanguageTool remoto

A API elimina Java e reduz o instalador, mas cria dependência de rede, tratamento de indisponibilidade e envio de texto a um terceiro. A API pública gratuita documenta limites, entre eles 20 requisições por minuto, 75 mil caracteres por minuto e 20 mil caracteres por requisição. Esses limites podem mudar e devem ser lidos na especificação no momento de qualquer integração: [API oficial](https://languagetool.org/http-api/swagger-ui/).

Consequência: o remoto pode ser um provedor **opcional e explicitamente ativado**, com aviso claro de privacidade, termos, limites e falhas. Não deve ser fallback silencioso quando o Java local não estiver disponível.

### 3. LibreOffice VERO/Hunspell e Lightproof

O repositório oficial do LibreOffice reúne o dicionário Hunspell pt-BR e o verificador de sentenças Lightproof no pacote brasileiro: [manifesto oficial do dicionário](https://github.com/LibreOffice/dictionaries/blob/master/Dictionary_pt-BR.mk). O dicionário atual informa LGPLv3 + MPL, enquanto o Lightproof pt-BR informa MPL 1.1 / GPLv3+ / LGPLv3+: [README do pt-BR](https://github.com/LibreOffice/dictionaries/blob/master/pt_BR/README_pt_BR.txt) e [README do Lightproof](https://github.com/LibreOffice/dictionaries/blob/master/pt_BR/README_Lightproof_pt_BR.txt).

O Hunspell é a abordagem leve que o projeto já emprega via spylls, mas continua sendo uma solução lexical. O Lightproof possui regras de sentença, porém foi criado como extensão integrada ao UNO/LibreOffice, não como uma biblioteca Python autônoma. Portá-lo ou reaproveitar suas regras exigiria engenharia específica, testes extensos e revisão das obrigações da licença escolhida. O arquivo oficial de regras pode ser inspecionado em [lightproof_pt_BR.py](https://github.com/LibreOffice/dictionaries/blob/master/pt_BR/pythonpath/lightproof_pt_BR.py).

Conclusão: manter Hunspell/spylls como fallback; não escolher Lightproof como primeira implementação de concordância.

### 4. spaCy

Os pipelines oficiais de português oferecem tokenização, morfologia, dependências e entidades em diferentes tamanhos, treinados principalmente em texto jornalístico: [modelos oficiais de português](https://spacy.io/models/pt). Isso permite construir regras próprias, mas o spaCy não entrega, por si só, um catálogo de erros com correções seguras.

Seria necessário projetar regras de concordância, gerar substituições, explicar cada alerta e controlar falsos positivos. Os modelos são pacotes locais, favoráveis à privacidade, mas acrescentam dados e dependências ao PyInstaller. A licença deve ser verificada no metadado da versão exata de cada modelo, sem presumir que todos os artefatos têm a mesma: [releases oficiais dos modelos](https://github.com/explosion/spacy-models/releases).

Conclusão: candidato de P&D para regras de xadrez muito específicas, não motor principal do primeiro lançamento.

### 5. Stanza

O Stanza fornece pipelines locais de português com tokenização, lema, POS, traços morfológicos e dependências: [site oficial](https://stanfordnlp.github.io/stanza/) e [lista de modelos](https://stanfordnlp.github.io/stanza/models.html). Assim como o spaCy, é infraestrutura de NLP, não um corretor pronto.

A biblioteca usa Apache-2.0, enquanto os pacotes de modelos são disponibilizados sob ODC Attribution 1.0 na extensão dos direitos de Stanford. A instalação envolve modelos baixados e PyTorch: [instalação/uso](https://stanfordnlp.github.io/stanza/installation_usage.html) e [download de modelos](https://stanfordnlp.github.io/stanza/download_models.html). Isso aumenta significativamente a complexidade de distribuição, inicialização e consumo de recursos quando comparado ao corretor atual.

Conclusão: não adotar como corretor principal; reavaliar somente se um experimento demonstrar ganho mensurável que justifique PyTorch e regras próprias.

## Arquitetura proposta

Criar uma porta interna que não exponha objetos do LanguageTool, spylls ou widgets:

```text
Editor de revisão
    -> ProofreadingCoordinator (debounce, cancelamento, cache, versão do texto)
        -> TextMasker (SAN/PGN, URLs, termos aceitos e spans protegidos)
        -> GrammarProvider
            -> LanguageToolLocalProvider
            -> LanguageToolRemoteProvider (opt-in)
            -> HunspellProvider (fallback apenas ortográfico)
        -> lista normalizada de ProofreadingIssue
```

Cada `ProofreadingIssue` deve conter: identificador estável da regra, categoria (`ortografia`, `gramática`, `concordância`, `estilo`), intervalo no texto original, mensagem, explicação curta, sugestões ordenadas, severidade, fornecedor e versão do texto analisado. A interface aplica uma sugestão somente se a versão e o trecho ainda coincidirem, evitando corrigir offsets obsoletos após edição.

Requisitos operacionais:

- nunca executar verificação na thread do Tk;
- aplicar _debounce_ ao digitar e cancelar/ignorar respostas antigas;
- verificar o comentário atual, não o PGN inteiro a cada tecla;
- cachear por hash de `(texto, idioma, configuração, versão do motor, glossário)`;
- preservar os filtros existentes de texto de origem e glossário;
- mascarar ou excluir SAN, NAGs e elementos estruturais do PGN sem alterar offsets;
- permitir “ignorar uma vez”, “ignorar esta regra” e “adicionar ao vocabulário pessoal”;
- nunca enviar texto ao provedor remoto sem consentimento explícito;
- mostrar no estado da interface se o corretor está local, remoto, somente ortográfico ou indisponível;
- degradar para spylls se o processo local falhar, deixando explícito que concordância está indisponível.

O glossário deve participar da correção em duas direções: seus termos de destino formam um vocabulário aceito, como já ocorre, e alterações nele invalidam o cache pertinente. Não se deve desativar globalmente uma regra gramatical apenas porque ela conflita com um termo; a supressão deve ser limitada ao intervalo ou ao identificador comprovadamente problemático.

## Implementação em fases

### Fase 0 — corpus e contrato

- montar um corpus versionado de comentários traduzidos: corretos, erros ortográficos, concordância nominal/verbal, regência, pontuação, SAN, nomes e termos do glossário;
- rotular o resultado esperado e os intervalos;
- definir `GrammarProvider` e `ProofreadingIssue` sem dependência de UI;
- medir a base atual do spylls.

### Fase 1 — protótipo LanguageTool local

- executar uma versão fixada do servidor apenas em loopback com `pt-BR` explícito;
- implementar cliente, timeout, cancelamento, normalização de resultados e fallback;
- medir cobertura, falso positivo, latência fria/quente, RAM, CPU e tamanho em disco;
- auditar licenças de todos os JARs, dados linguísticos e runtime Java selecionados.

Esta fase é uma prova técnica; ainda não entra no instalador de produção.

### Fase 2 — experiência de revisão

- sublinhados visualmente distintos para ortografia, gramática e estilo;
- painel/menu de sugestões com mensagem, substituições e comando de ignorar;
- navegação por teclado entre problemas;
- estado inequívoco do motor e da privacidade;
- configuração de categorias e regras, com padrões conservadores;
- telemetria apenas local e agregada de latência/erros, sem armazenar o texto.

### Fase 3 — distribuição Windows

- decidir, com base nas medições, entre JRE externo e runtime embarcado;
- ensinar o `.spec` e o instalador a incluir/verificar exatamente os artefatos fixados;
- adicionar inventário de terceiros, textos de licença, hashes e procedimento de atualização;
- testar instalação limpa, caminhos com acentos/espaços, antivírus, execução sem rede e encerramento sem processo órfão;
- tornar a ausência do motor gramatical recuperável e visível.

### Fase 4 — extensões opcionais

- oferecer API remota somente mediante opt-in e política de privacidade clara;
- experimentar spaCy ou Stanza apenas para regras do domínio que o LanguageTool não cubra;
- contribuir regras gerais corrigidas ao projeto de origem quando adequado, em vez de manter um _fork_ silencioso.

## Critérios de aceite

A decisão de produção deve se apoiar em um relatório reprodutível com:

- precisão e _recall_ separados por ortografia, concordância e demais categorias;
- taxa de falso positivo em SAN, nomes, topônimos e vocabulário do glossário;
- latência p50/p95 no primeiro uso e com motor aquecido;
- pico e regime de RAM/CPU;
- acréscimo ao instalador e ao diretório instalado;
- comportamento offline e sem Java;
- nenhuma chamada de rede no modo local, verificada por teste;
- nenhum congelamento perceptível da interface;
- offsets corretos com acentos, emojis, hífens e edições simultâneas;
- licenças e procedência de todo artefato redistribuído documentadas.

Uma meta inicial razoável para o protótipo é zero falso positivo em notação SAN do corpus, p95 inferior a 300 ms por comentário com o motor aquecido e nenhuma operação de rede no modo local. Precisão e _recall_ só devem ganhar metas numéricas depois de o corpus ser rotulado, pois fixá-las antes disso produziria uma garantia sem base.

## Riscos e controles

| Risco | Controle |
| --- | --- |
| Falsos positivos prejudicam a revisão | Corpus do domínio, regras conservadoras, filtros por span, desativação granular |
| Resposta antiga corrige texto novo | Versão do documento + validação de trecho antes de aplicar |
| Java aumenta o instalador e a superfície de atualização | Runtime mínimo fixado, SBOM/inventário, hashes e rotina documentada de atualização |
| Processo local fica exposto na rede | Bind exclusivo a loopback, porta efêmera, nunca usar `--public` |
| Texto privado é enviado sem clareza | Local como padrão; remoto apenas opt-in; indicador persistente |
| Termos corretos de xadrez são marcados | Vocabulário do glossário, origem e lista pessoal; testes de SAN |
| Licenças dos recursos são presumidas | Auditoria por artefato/versão e avisos incluídos no instalador |
| Motor gramatical falha ou não inicia | Timeout, diagnóstico, reinício limitado e fallback spylls explicitamente rotulado |

## Conclusão

O caminho de menor risco é evoluir o corretor existente para uma arquitetura de provedores e acrescentar **LanguageTool local** como camada gramatical. Isso preserva privacidade, aproveita regras maduras e mantém o spylls como opção leve. O custo real é operacional: Java, tamanho, memória, licenças e processo auxiliar. Por isso, o próximo passo correto é o protótipo mensurado contra o corpus de xadrez, antes da integração definitiva com a interface e o instalador.
