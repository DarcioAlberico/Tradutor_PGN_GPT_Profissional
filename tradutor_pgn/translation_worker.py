import os
import time
from datetime import datetime
from tkinter import messagebox

import requests

from .annotation_mask import mask_annotations, restore_annotations
from .chess_notation import fix_move_notation, supports_notation
from .database import (
    SOURCE_LANGUAGE_UNKNOWN,
    adopt_unknown_source_language,
    initialize_database,
    load_translation_cache,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
)
from .glossario import (
    apply_automatic_substitutions,
    clean_comment_for_translation,
    load_automatic_substitutions,
    load_cleanup_substitutions,
)
from .pgn_utils import (
    BATCH_MAX_CHARS,
    available_output_path,
    batch_index_groups,
    collect_pgn_files,
    create_comment_batches,
    extract_comment_texts_from_file,
    extract_comments_from_content,
    generate_translated_pgn,
    join_comments_for_batch,
    read_pgn_text,
    split_batch_translation,
    translated_output_path,
)
from itertools import chain

from .app_config import TRANSLATION_REQUEST_DELAY_SECONDS  # noqa: F401 (compat)
from .failed_runs import build_failed_run_record, save_failed_run
from .settings import load_settings, read_output_settings
from .translation_api import RequestPacer, translate_text

# Disjuntor (garantia B3): tantos lotes seguidos sem NENHUMA resposta da API e a
# conexao ou o endpoint, nao o conteudo. Cada lote ja gastou 3 tentativas com
# ate 30 s de timeout cada, entao insistir custa minutos por lote para terminar
# com tudo falhando igual. Tres da margem para uma instabilidade passageira sem
# transformar uma queda em horas de espera.
MAX_CONSECUTIVE_FAILED_BATCHES = 3


def _first_pass(app, pgn_files):
    """Le so o que a adocao (P2) e a carga de cache precisam: os TEXTOS.

    Devolve `{"total", "distintos", "semicolon", "por_arquivo"}`, ou `None` se o
    usuario cancelou no meio. `por_arquivo` e `{caminho: [textos distintos]}`, na
    ordem em que os comentarios aparecem no arquivo.

    **O que fica guardado sao os textos, e nada mais** (ROADMAP 20.4). Antes,
    `info_by_file` guardava o resultado COMPLETO da extracao de todos os PGN —
    comentarios, posicoes e contexto de leitura de cada um — pela execucao
    inteira. Posicao e contexto agora nascem na vez do arquivo, junto com o
    conteudo dele, e morrem com ela; os textos ficam porque a adocao e a carga de
    cache precisam de todos de uma vez.

    Os textos distintos por arquivo sao os MESMOS objetos em `por_arquivo` e nas
    consultas ao banco: a lista de cada arquivo custa um ponteiro por texto, e
    nao uma copia.

    E uma funcao, e nao um laco dentro de `run_translation`, por causa da
    memoria: as variaveis de um laco Python sobrevivem ao laco, entao o `info` do
    ULTIMO arquivo continuava vivo ate o fim da execucao. A medicao mostrou esse
    vazamento — o pico nao caiu quando a lista foi liberada "de proposito" —, e um
    escopo proprio e o unico jeito confiavel de nao ter esse tipo de sobra.
    """
    total_comments = 0
    total_distintos = 0
    total_semicolon = 0
    por_arquivo = {}

    for pgn_file in pgn_files:
        if app.cancel_flag.is_set():
            app.log_message("Traducao cancelada antes da extracao completa.")
            return None

        info = extract_comment_texts_from_file(pgn_file, app.log_message)
        total_comments += len(info["comments"])
        # `dict.fromkeys` preservando a ordem: o mesmo comentario repetido no
        # arquivo — "Diagram", "(D)", a legenda de cada figura — era enviado
        # tantas vezes quantas aparecia, porque o cache so aprende a traducao
        # DEPOIS da resposta e o lote inteiro sai antes dela (ROADMAP 20.3).
        distintos = list(dict.fromkeys(info["comments"]))
        total_distintos += len(distintos)
        por_arquivo[pgn_file] = distintos
        # Garantia X3: o que o pipeline ignora e contado e anunciado. Sem isto,
        # um PGN anotado so com `;` termina em "nenhum comentario encontrado" e o
        # usuario conclui que o programa falhou.
        ignorados = info.get("semicolon_comments", 0)
        if ignorados:
            total_semicolon += ignorados
            app.log_message(
                f"  - {ignorados} comentario(s) no formato ';' ignorados "
                f"(nao suportado)."
            )

    return {
        "total": total_comments,
        "distintos": total_distintos,
        "semicolon": total_semicolon,
        "por_arquivo": por_arquivo,
    }


def run_translation(
    app,
    source_path,
    target_language,
    process_subdirs,
    only_files=None,
    source_language=SOURCE_LANGUAGE_UNKNOWN,
):
    """Traduz os comentarios dos PGN de `source_path`.

    `only_files` restringe a execucao a uma lista explicita, que e como o
    "Reprocessar falhas" reaproveita esta funcao inteira em vez de duplicar o
    laco (ROADMAP 7.3).

    `source_language` e o idioma em que os PGN estao. Vazio significa "detectar
    automaticamente", que e o que o programa sempre fez. Declara-lo tem dois
    efeitos: a API recebe `sl=<idioma>` em vez de `sl=auto` — deixa de adivinhar
    —, e a traducao e gravada dentro do par de idiomas, o que e o que permite ao
    editor mostrar so um par de cada vez.
    """
    source_language = source_language or SOURCE_LANGUAGE_UNKNOWN
    conn = None
    canceled = False
    # A barra de progresso precisa terminar num estado DEFINIDO, e quem decide
    # qual e este par. Interrompida pelo disjuntor — ou por uma excecao geral — ela
    # congelava no valor em que estava: 43% para sempre, sem nada na tela
    # distinguindo "ainda trabalhando" de "acabou mal". Ver o `finally`.
    completed = False
    # Declarados FORA do `try` de proposito: sem isso, uma excecao geral no meio
    # da execucao chegava ao tratador sem que eles existissem, e a lista de falhas
    # desta execucao era perdida — a lista da execucao ANTERIOR continuava
    # valendo, e "Reprocessar Falhas" reprocessava os arquivos errados (T4).
    failed_count = 0
    failed_files = set()
    failures_recorded = False
    http_session = requests.Session()

    def registrar_falhas():
        """Grava (ou apaga) a lista para o "Reprocessar falhas" (garantia T4).

        Uma execucao CANCELADA nao registra: os arquivos ainda nao visitados nao
        foram avaliados, e gravar essa lista parcial por cima da anterior
        perderia o que ela ja sabia. Uma execucao que morreu de excecao esta na
        situacao oposta — a lista anterior fala de outra execucao, e mante-la e
        que seria mentir sobre o que ficou devendo.

        Uma vez so: o caminho normal chama no fim, e o tratador de excecao chama
        se o normal nao chegou la.
        """
        nonlocal failures_recorded
        if canceled or failures_recorded:
            return
        failures_recorded = True
        try:
            save_failed_run(
                build_failed_run_record(
                    target_language,
                    failed_files,
                    failed_count,
                    when=datetime.now().isoformat(timespec="seconds"),
                    source_language=source_language,
                )
            )
        except Exception as exc:  # pragma: no cover - defensivo
            # Anotar a lista e conveniencia; falhar aqui nao pode transformar
            # uma traducao concluida em erro.
            app.log_message(f"[AVISO] Nao foi possivel anotar as falhas: {exc}")
    # Um por execucao: o ritmo aprendido com os 429 vale para o resto da
    # traducao, e nao so para o lote em que a reclamacao apareceu (ROADMAP 7.2).
    pacer = RequestPacer()

    try:
        origem_dita = source_language or "detectar automaticamente"
        app.log_message(
            f"Iniciando traducao de {origem_dita} para o idioma: {target_language}"
        )
        app.log_message(f"Banco de dados: {app.output_db}")

        conn = initialize_database(app.output_db)
        cursor = conn.cursor()
        # O cache e carregado depois da extracao, quando ja se sabe QUAIS
        # comentarios esta execucao vai consultar (ROADMAP 2.9).
        app.translation_cache = {}
        # O par de idiomas decide QUAIS regras existem nesta execucao (garantia
        # S11). Uma regra escopada para o portugues nao alcanca uma traducao para
        # o italiano — e era esse o defeito: `('movimento', 'lance')` corrompia
        # `il movimento` porque o glossario nao sabia para que lingua traduzia.
        cleanup_rules = load_cleanup_substitutions(
            source_language=source_language, target_language=target_language
        )
        if cleanup_rules:
            app.log_message(f"Regras de limpeza carregadas: {len(cleanup_rules)}")
        automatic_rules = load_automatic_substitutions(
            source_language=source_language, target_language=target_language
        )
        if automatic_rules:
            app.log_message(f"Regras automaticas carregadas: {len(automatic_rules)}")

        if only_files is None:
            pgn_files, skipped_generated = collect_pgn_files(source_path, process_subdirs)
            if skipped_generated:
                app.log_message(
                    f"Arquivos PGN gerados anteriormente ignorados: {skipped_generated}"
                )
        else:
            # Lista explicita: nao passa por `collect_pgn_files` de proposito. Ela
            # descarta arquivos com sufixo de idioma, e um PGN de origem que por
            # acaso se chame "algo-BR.pgn" sairia da lista de reprocessamento
            # justamente por ter falhado antes.
            pgn_files = list(only_files)
            app.log_message(f"Reprocessando {len(pgn_files)} arquivo(s) com falhas.")

        if not pgn_files:
            app.log_message("Nenhum arquivo PGN encontrado.")
            return

        # Opcao de gravacao lida uma vez por execucao, como as regras do
        # glossario: e uma escolha do usuario no arquivo de configuracoes, e
        # nao muda no meio de uma traducao (ROADMAP 13.6).
        opcoes_de_saida = read_output_settings(load_settings())
        use_bom = opcoes_de_saida["utf8_bom"]
        wrap_columns = opcoes_de_saida["wrap_columns"]
        if wrap_columns:
            app.log_message(
                f"Requebra dos comentarios ligada: {wrap_columns} colunas."
            )

        primeira = _first_pass(app, pgn_files)
        if primeira is None:
            canceled = True
            return
        total_comments = primeira["total"]
        # O denominador do progresso, e o numero de comentarios que a execucao de
        # fato traduz: um comentario repetido no proprio arquivo e processado uma
        # vez so (ROADMAP 20.3).
        total_distintos = primeira["distintos"]
        total_semicolon = primeira["semicolon"]
        comentarios_por_arquivo = primeira["por_arquivo"]
        primeira = None

        def comentarios_do_lote():
            """Todos os textos, um iterador novo a cada chamada.

            Iterador, e nao uma lista a mais: os textos ja estao guardados por
            arquivo, e uma copia global deles seria o acervo em memoria duas vezes
            (ROADMAP 20.4). Quem consome deduplica sozinho — `adopt` e
            `load_translation_cache` fazem `dict.fromkeys` internamente —, e cada
            chamada devolve um iterador novo porque um gerador esgotado nao serve
            para a segunda pergunta.
            """
            return chain.from_iterable(comentarios_por_arquivo.values())

        if total_comments == 0:
            if total_semicolon:
                app.log_message(
                    f"Nenhum comentario {{...}} encontrado, mas ha "
                    f"{total_semicolon} comentario(s) no formato ';', que o "
                    f"programa nao traduz."
                )
            else:
                app.log_message("Nenhum comentario encontrado nos arquivos PGN.")
            return

        app.log_message(f"Total de comentarios detectados: {total_comments}")
        repetidos = total_comments - total_distintos
        if repetidos:
            # So quando existe, como a linha dos lances e a dos `;`. E dito aqui
            # porque muda o que o usuario ve na barra e no resumo: sao os
            # comentarios que o programa NAO envia de novo (ROADMAP 20.3).
            app.log_message(
                f"Comentarios repetidos dentro do proprio arquivo: {repetidos} "
                f"(traduzidos uma vez so)"
            )

        # ANTES da carga do cache, e nao depois: adotar rotula as linhas destes
        # comentarios que ainda nao tem idioma de origem, e e isso que faz o
        # cache ja gravado continuar valendo quando o usuario passa a declarar o
        # idioma. Depois da carga, a adocao chegaria tarde — o cache ja teria
        # vindo vazio e a execucao ja teria decidido pagar tudo de novo.
        adotadas = adopt_unknown_source_language(
            cursor, target_language, source_language, comentarios_do_lote()
        )
        if adotadas:
            conn.commit()
            app.log_message(
                f"{adotadas} traducao(oes) sem idioma de origem foram marcadas "
                f"como '{source_language}'."
            )

        # So agora, e so o que estes arquivos usam: carregar o idioma inteiro
        # trazia 195 mil traducoes (58 MB) para traduzir uma pasta com algumas
        # centenas de comentarios (ROADMAP 2.9).
        app.translation_cache = load_translation_cache(
            cursor,
            target_language,
            comentarios_do_lote(),
            source_language=source_language,
        )
        # Contado sobre a lista, e nao por `len(cache)`: acima do limite a carga
        # completa sai mais barata e o dicionario vem com o idioma inteiro, entao
        # o tamanho dele nao diz nada sobre ESTES arquivos.
        reaproveitaveis = len(
            {c for c in comentarios_do_lote() if c in app.translation_cache}
        )
        app.log_message(
            f"Cache carregado: {reaproveitaveis} destes comentarios ja estavam "
            f"traduzidos"
        )

        # A correcao de lances precisa do idioma de origem declarado: ela le os
        # lances do comentario ORIGINAL para saber o que cada letra significa, e
        # sem saber em que alfabeto ele esta nao ha o que ler. Dito uma vez, no
        # comeco, para o usuario saber o que ganhou (ou o que esta deixando de
        # ganhar) ao escolher "Detectar".
        corrige_lances = supports_notation(source_language) and supports_notation(
            target_language
        )
        if corrige_lances:
            app.log_message(
                "Correcao de lances ligada: as letras das pecas serao conferidas "
                f"contra o comentario original ({source_language} -> {target_language})."
            )
        elif not source_language:
            app.log_message(
                "Correcao de lances desligada: o idioma de origem nao foi "
                "declarado, entao nao da para saber o que as letras dos lances "
                "significam no original."
            )

        processed_comments = 0
        translated_count = 0
        move_fixes = 0
        filled_empty_count = 0
        cache_count = 0
        cleaned_empty_count = 0
        generated_files = 0
        consecutive_failed_batches = 0
        aborted_by_api = False

        def update_progress():
            # Sobre os DISTINTOS, e nao sobre o total: com a deduplicacao do lote
            # (ROADMAP 20.3) um comentario repetido e processado uma vez, e um
            # denominador maior que o numero de passos deixaria a barra parada
            # antes do fim num arquivo cheio de "Diagram".
            value = (
                (processed_comments / total_distintos) * 100
                if total_distintos > 0
                else 0
            )
            app.root.after(0, lambda v=value: app.progress.set(v / 100))

        def wait_if_paused():
            pause_started = None
            while app.pause_flag.is_set() and not app.cancel_flag.is_set():
                if pause_started is None:
                    pause_started = time.perf_counter()
                time.sleep(0.2)
            if pause_started is None:
                return 0.0
            return time.perf_counter() - pause_started

        for pgn_index, pgn_file in enumerate(pgn_files, start=1):
            if app.cancel_flag.is_set():
                canceled = True
                app.log_message("Traducao cancelada pelo usuario.")
                return

            app.log_message(
                f"Processando arquivo {pgn_index}/{len(pgn_files)}: {os.path.basename(pgn_file)}"
            )
            # Os textos distintos vem da primeira passada, e o ARQUIVO nao e lido
            # aqui: ele so serve para gravar, e a fase da API que vem a seguir
            # dura minutos — segurar um livro de 40 MB por todo esse tempo e o
            # custo que este item existe para nao pagar (ROADMAP 20.4). Posicao e
            # contexto de leitura nascem depois do laco dos lotes, junto com o
            # conteudo, e vao direto para a gravacao.
            #
            # Sao os DISTINTOS: o mesmo comentario repetido no arquivo — "Diagram",
            # "(D)", a legenda de cada figura — era enviado tantas vezes quantas
            # aparecia, porque o cache so aprende a traducao DEPOIS da resposta e o
            # lote inteiro sai antes dela (ROADMAP 20.3). A geracao continua
            # trocando todas as ocorrencias: ela procura o texto no
            # `translated_map`, e nao a posicao.
            comments = comentarios_por_arquivo.get(pgn_file) or []

            if not comments:
                app.log_message("  - Nenhum comentario neste arquivo.")
                continue

            batches = create_comment_batches(comments)
            translated_map = {}

            for batch_idx, batch in enumerate(batches, start=1):
                batch_started = time.perf_counter()
                batch_api_time = 0.0
                batch_wait_time = 0.0
                batch_pause_time = wait_if_paused()
                batch_api_requests = 0
                start_translated_count = translated_count
                start_filled_empty_count = filled_empty_count
                start_cache_count = cache_count
                start_cleaned_empty_count = cleaned_empty_count

                if app.cancel_flag.is_set():
                    canceled = True
                    conn.commit()
                    app.log_message("Traducao cancelada pelo usuario.")
                    return

                # Fase 1: separar comentários em cache dos que precisam de tradução
                to_translate = []  # lista de (original, mascarado, tokens)
                for comment in batch:
                    batch_pause_time += wait_if_paused()

                    if app.cancel_flag.is_set():
                        canceled = True
                        conn.commit()
                        app.log_message("Traducao cancelada pelo usuario.")
                        return

                    if comment in app.translation_cache:
                        translated_map[comment] = app.translation_cache[comment]
                        cache_count += 1
                        processed_comments += 1
                        update_progress()
                    else:
                        cleaned_comment = clean_comment_for_translation(
                            comment,
                            cleanup_rules,
                        )
                        if not cleaned_comment:
                            translated_map[comment] = ""
                            cleaned_empty_count += 1
                            processed_comments += 1
                            update_progress()
                        else:
                            # DEPOIS da limpeza, para que uma regra de limpeza
                            # ainda possa remover uma anotacao inteira se o
                            # usuario quiser; ANTES da API, que e de quem a
                            # mascara protege (garantia X1). As regras
                            # automaticas e a correcao de lances rodam sobre o
                            # texto ainda mascarado — anotacao escondida nao e
                            # reescrita por engano — e a restauracao e o ultimo
                            # passo antes de gravar.
                            masked_comment, annotation_tokens = mask_annotations(
                                cleaned_comment
                            )
                            to_translate.append(
                                (comment, masked_comment, annotation_tokens)
                            )

                # Fase 2: traduzir em lote os comentários restantes
                if to_translate:
                    # O lote foi montado sobre o texto CRU, e o que vai para a
                    # API e o texto limpo e MASCARADO — que pode ser mais longo
                    # (uma regra de limpeza que expande, uma sentinela de mascara
                    # maior que o `[%cal ...]` que ela substitui). Reagrupar aqui,
                    # pelo mesmo algoritmo do `create_comment_batches`, e o que
                    # torna a garantia B1 uma garantia: no caminho comum sai um
                    # grupo so e nada muda; no caso que estourava o limite, o
                    # envio e dividido em vez de chegar a camada de API grande
                    # demais e ser cortado por sentenca no meio de um `|||`.
                    grupos = batch_index_groups([item[1] for item in to_translate])
                    if len(grupos) > 1:
                        app.log_message(
                            f"  - Lote {batch_idx} dividido em {len(grupos)} "
                            f"envios: depois da limpeza e da mascara o texto "
                            f"passou de {BATCH_MAX_CHARS} caracteres."
                        )

                    for grupo in grupos:
                        grupo_items = [to_translate[i] for i in grupo]
                        batch_pause_time += wait_if_paused()

                        if app.cancel_flag.is_set():
                            canceled = True
                            conn.commit()
                            app.log_message("Traducao cancelada pelo usuario.")
                            return

                        originals = [item[0] for item in grupo_items]
                        masked_texts = [item[1] for item in grupo_items]
                        joined = join_comments_for_batch(masked_texts)

                        api_started = time.perf_counter()
                        translated_joined = translate_text(
                            joined,
                            target_language,
                            app.log_message,
                            app.cancel_flag,
                            session=http_session,
                            pacer=pacer,
                            source_language=source_language,
                        )
                        batch_api_time += time.perf_counter() - api_started
                        batch_api_requests += 1

                        parts = None
                        if translated_joined:
                            # A API respondeu — o disjuntor conta lotes SEM
                            # resposta, e nao lotes desalinhados. Desalinhamento
                            # e um problema do conteudo, nao da conexao.
                            consecutive_failed_batches = 0
                            parts = split_batch_translation(
                                translated_joined, len(originals)
                            )

                        if parts:
                            for (original, _masked, tokens), part in zip(
                                grupo_items, parts
                            ):
                                translation = apply_automatic_substitutions(
                                    part, automatic_rules
                                )
                                # Depois das regras automaticas e ANTES de
                                # gravar: o que vai para o banco e para o PGN e o
                                # mesmo texto, entao corrigir aqui cobre os dois
                                # de uma vez.
                                translation, corrigidos = fix_move_notation(
                                    original, translation, source_language, target_language
                                )
                                # A restauracao e o ULTIMO passo, e e verificada:
                                # se a traducao nao devolveu cada sentinela
                                # exatamente uma vez, gravar seria guardar uma
                                # anotacao corrompida com cara de certa. O
                                # comentario conta como falha e fica no idioma
                                # original (T2/T3).
                                translation, intactas = restore_annotations(
                                    translation, tokens
                                )
                                if not intactas:
                                    failed_count += 1
                                    failed_files.add(pgn_file)
                                    app.log_message(
                                        f"  - [FALHA] Anotacoes [%...] nao voltaram "
                                        f"intactas da traducao: \"{original[:60]}\""
                                    )
                                    continue
                                move_fixes += corrigidos
                                app.translation_cache[original] = translation
                                translated_map[original] = translation
                                save_status = save_translation(
                                    cursor, original, translation, target_language,
                                    source_language,
                                )
                                if save_status == "inserted":
                                    translated_count += 1
                                elif save_status == "filled_empty":
                                    filled_empty_count += 1
                        elif not translated_joined:
                            # A CHAMADA falhou (garantia B3). Nao e
                            # desalinhamento: o `translate_text` acabou de gastar
                            # as 3 tentativas dele contra o endpoint e voltou de
                            # maos vazias.
                            #
                            # Reprocessar comentario a comentario aqui era o pior
                            # caminho possivel. Cada um gasta outras 3
                            # tentativas, cada tentativa espera ate os 30 s de
                            # timeout: um lote de 40 comentarios contra um
                            # endpoint que pendura a conexao levava perto de uma
                            # hora para terminar com os 40 contados como falha do
                            # mesmo jeito. E, ate agora, este era o unico caminho
                            # SEM log — o `if translated_joined` deixava a
                            # mensagem de fora justamente quando a causa era a
                            # pior.
                            #
                            # T2/T3 continuam valendo: os comentarios ficam no
                            # idioma original e sao contados e informados.
                            failed_count += len(grupo_items)
                            failed_files.add(pgn_file)
                            consecutive_failed_batches += 1
                            app.log_message(
                                f"  - [FALHA] A API nao respondeu para o lote "
                                f"({len(originals)} comentarios). Eles ficam no "
                                f"idioma original."
                            )
                            if consecutive_failed_batches >= MAX_CONSECUTIVE_FAILED_BATCHES:
                                # Disjuntor: se N lotes seguidos falharam
                                # inteiros, o problema nao e um comentario, e a
                                # conexao ou o endpoint. Insistir so arrasta a
                                # execucao por horas para terminar com tudo
                                # falhando igual.
                                app.log_message(
                                    f"[ABORTADO] {consecutive_failed_batches} lotes "
                                    f"seguidos sem resposta da API. Verifique a "
                                    f"conexao e reprocesse depois."
                                )
                                aborted_by_api = True
                                conn.commit()
                                break
                        else:
                            # Desalinhamento: a resposta VEIO, mas nao deu para
                            # separar de volta. Aqui o fallback individual e a
                            # resposta certa — e a garantia B2.
                            app.log_message(
                                f"  - Aviso: divisao do lote falhou "
                                f"({len(originals)} comentarios), traduzindo individualmente."
                            )
                            for original, masked, tokens in grupo_items:
                                if app.cancel_flag.is_set():
                                    canceled = True
                                    conn.commit()
                                    app.log_message("Traducao cancelada pelo usuario.")
                                    return
                                api_started = time.perf_counter()
                                translated = translate_text(
                                    masked,
                                    target_language,
                                    app.log_message,
                                    app.cancel_flag,
                                    session=http_session,
                                    pacer=pacer,
                                    source_language=source_language,
                                )
                                batch_api_time += time.perf_counter() - api_started
                                batch_api_requests += 1
                                if translated:
                                    translation = apply_automatic_substitutions(
                                        translated, automatic_rules
                                    )
                                    translation, corrigidos = fix_move_notation(
                                        original,
                                        translation,
                                        source_language,
                                        target_language,
                                    )
                                    # A mesma verificacao do caminho do lote, e
                                    # nao por zelo: uma correcao que so
                                    # existisse num dos dois daria uma execucao
                                    # cujo resultado depende de a rede ter
                                    # respondido alinhada — a licao da secao
                                    # 10.4 do ROADMAP.
                                    translation, intactas = restore_annotations(
                                        translation, tokens
                                    )
                                    if not intactas:
                                        failed_count += 1
                                        failed_files.add(pgn_file)
                                        app.log_message(
                                            f"  - [FALHA] Anotacoes [%...] nao "
                                            f"voltaram intactas da traducao: "
                                            f"\"{original[:60]}\""
                                        )
                                        wait_seconds = pacer.next_delay()
                                        time.sleep(wait_seconds)
                                        batch_wait_time += wait_seconds
                                        continue
                                    move_fixes += corrigidos
                                    app.translation_cache[original] = translation
                                    translated_map[original] = translation
                                    save_status = save_translation(
                                        cursor, original, translation, target_language,
                                        source_language,
                                    )
                                    # Comita AQUI, e nao no fim do lote
                                    # (garantia C3). O primeiro INSERT abre a
                                    # transacao de escrita; deixar para comitar
                                    # depois do laco a manteria aberta
                                    # atravessando todas as chamadas de rede
                                    # restantes — num lote de 40 comentarios a
                                    # ~1 s por requisicao sao 40 s de lock
                                    # retido, mais que o `busy_timeout` do
                                    # editor. O caminho do lote alinhado nao
                                    # precisa disso: la as gravacoes acontecem
                                    # todas depois da unica chamada de API.
                                    conn.commit()
                                    if save_status == "inserted":
                                        translated_count += 1
                                    elif save_status == "filled_empty":
                                        filled_empty_count += 1
                                else:
                                    # Garantia T2/T3: o comentario fica no
                                    # idioma original no arquivo de saida, mas
                                    # isso precisa ser contado e informado ao
                                    # usuario.
                                    failed_count += 1
                                    failed_files.add(pgn_file)
                                    app.log_message(
                                        f"  - [FALHA] Nao foi possivel traduzir: "
                                        f"\"{original[:60]}\""
                                    )
                                wait_seconds = pacer.next_delay()
                                time.sleep(wait_seconds)
                                batch_wait_time += wait_seconds

                        wait_seconds = pacer.next_delay()
                        time.sleep(wait_seconds)
                        batch_wait_time += wait_seconds

                        processed_comments += len(grupo_items)
                        update_progress()

                    if aborted_by_api:
                        # O `break` do disjuntor saiu do laco dos envios; este
                        # tira a execucao do laco dos lotes, como antes de o
                        # reagrupamento existir.
                        break

                conn.commit()
                batch_total_time = time.perf_counter() - batch_started
                batch_local_time = max(
                    0.0,
                    batch_total_time - batch_api_time - batch_wait_time - batch_pause_time,
                )
                batch_new = translated_count - start_translated_count
                batch_filled = filled_empty_count - start_filled_empty_count
                batch_cache = cache_count - start_cache_count
                batch_cleaned = cleaned_empty_count - start_cleaned_empty_count
                average_api_time = (
                    batch_api_time / batch_api_requests
                    if batch_api_requests
                    else 0.0
                )
                app.log_message(
                    f"  - Lote {batch_idx}/{len(batches)} concluido. "
                    f"Novas: {translated_count} (+{batch_new}) | "
                    f"Preenchidas: {filled_empty_count} (+{batch_filled}) | "
                    f"Cache: {cache_count} (+{batch_cache}) | "
                    f"Limpeza: {cleaned_empty_count} (+{batch_cleaned})"
                )
                app.log_message(
                    f"    Tempos do lote: total {batch_total_time:.1f}s | "
                    f"API {batch_api_time:.1f}s ({batch_api_requests} req, "
                    f"media {average_api_time:.1f}s) | "
                    f"espera {batch_wait_time:.1f}s | "
                    f"pausa {batch_pause_time:.1f}s | "
                    f"local {batch_local_time:.1f}s"
                )

            # A vez do arquivo: aqui — e so aqui — ele vive inteiro na memoria,
            # com as posicoes e o contexto de leitura (ROADMAP 20.4). Uma leitura
            # so: o conteudo segue para a geracao, que o recebe pronto em vez de
            # reler o arquivo e redetectar a codificacao (ROADMAP 20.2).
            #
            # Depois do laco dos lotes, e nao antes: entre a extracao e a gravacao
            # esta a fase da API, e o que nao precisa atravessa-la nao atravessa.
            try:
                content, encoding = read_pgn_text(pgn_file)
                # `known_texts`: os textos que a primeira passada ja tem na mao
                # voltam como os MESMOS objetos, e nao como copias de igual
                # conteudo. Sem isso, ler o arquivo duas vezes faria o texto do
                # livro viver duas vezes justamente no momento da gravacao, que e
                # onde o pico da execucao acontece (ROADMAP 20.4).
                info = extract_comments_from_content(
                    content,
                    count_semicolons=False,
                    known_texts={texto: texto for texto in comments},
                )
            except Exception as exc:
                # A primeira passada leu este arquivo; se agora nao da, algo mudou
                # no disco no meio da execucao. Um arquivo ilegivel nao derruba o
                # acervo — e o mesmo criterio do normalizador. As traducoes dele ja
                # estao no banco; o que se perde e o PGN de saida e as posicoes.
                app.log_message(
                    f"  - [ERRO] Nao foi possivel reler "
                    f"{os.path.basename(pgn_file)}: {exc}"
                )
                if aborted_by_api:
                    break
                continue

            positions = info["positions"]

            # ANTES do `break` do disjuntor de proposito: as traducoes que este
            # arquivo conseguiu ja estao no banco, e registrar de onde elas vieram
            # e o unico momento em que o programa tem essa informacao na mao. Uma
            # execucao interrompida grava as posicoes que conseguiu; a proxima
            # encontra o resto no cache e completa (ROADMAP 18).
            posicoes = info.get("occurrences") or []
            if posicoes:
                ids_por_texto = resolve_comment_ids(
                    cursor,
                    target_language,
                    [texto for _i, _p, _l, texto in posicoes],
                    source_language,
                )
                gravadas, sem_linha = record_occurrences(
                    cursor, pgn_file, posicoes, ids_por_texto
                )
                conn.commit()
                sufixo = (
                    f" ({sem_linha} sem traducao no banco)" if sem_linha else ""
                )
                app.log_message(
                    f"  - Posicoes registradas: {gravadas}/{len(posicoes)}{sufixo}"
                )

            if aborted_by_api:
                # Nao gera o PGN deste arquivo: com a API fora, ele sairia quase
                # todo no idioma original e pareceria pronto. O que ja foi
                # traduzido esta gravado no banco (mesma logica de C2), entao
                # reprocessar depois so paga o que falta.
                break

            if translated_map:
                preferred_output_pgn = translated_output_path(pgn_file, target_language)
                output_pgn = available_output_path(preferred_output_pgn)

                if output_pgn != preferred_output_pgn:
                    app.log_message(f"  - Arquivo de saida ja existia; usando: {output_pgn}")

                if generate_translated_pgn(
                    pgn_file,
                    output_pgn,
                    translated_map,
                    positions,
                    app.log_message,
                    use_bom=use_bom,
                    wrap_columns=wrap_columns,
                    content=content,
                    encoding=encoding,
                    cancel_flag=app.cancel_flag,
                ):
                    generated_files += 1
                    app.log_message(f"  - Arquivo traduzido gerado: {output_pgn}")

        conn.commit()

        if aborted_by_api:
            app.log_message("====== TRADUCAO INTERROMPIDA: API SEM RESPOSTA ======")
        elif failed_count:
            app.log_message("====== TRADUCAO FINALIZADA COM FALHAS ======")
        else:
            app.log_message("====== TRADUCAO FINALIZADA ======")
        app.log_message(f"Total de comentarios: {total_comments}")
        if repetidos:
            app.log_message(
                f"Comentarios repetidos no proprio arquivo (nao reenviados): "
                f"{repetidos}"
            )
        app.log_message(f"Comentarios novos traduzidos nesta execucao: {translated_count}")
        app.log_message(f"Traducoes vazias preenchidas: {filled_empty_count}")
        app.log_message(f"Comentarios removidos por limpeza: {cleaned_empty_count}")
        app.log_message(f"Traducoes reutilizadas do cache: {cache_count}")
        app.log_message(f"Comentarios que falharam: {failed_count}")
        app.log_message(f"Arquivos PGN traduzidos gerados: {generated_files}")
        if corrige_lances:
            app.log_message(f"Lances com a letra da peca corrigida: {move_fixes}")
        if total_semicolon:
            # So quando existe (garantia X3): um "0 ignorados" fixo faria o
            # usuario procurar um problema que nao ha — o mesmo criterio da
            # linha de lances acima.
            app.log_message(
                f"Comentarios ';' ignorados (nao suportado): {total_semicolon}"
            )
        app.log_message(f"Banco de dados: {app.output_db}")

        if failed_count:
            if generated_files:
                # So faz sentido mandar reprocessar o que foi gerado quando algo
                # foi gerado. Com a API fora, ou com todos os comentarios de um
                # arquivo falhando, nao ha arquivo de saida nenhum — e a
                # instrucao antiga mandava reprocessar um arquivo inexistente.
                onde = "Reprocesse os arquivos gerados para completar a traducao."
            else:
                onde = (
                    "Nenhum arquivo de saida foi gerado; reprocesse os arquivos "
                    "de origem quando a traducao voltar a funcionar."
                )
            app.log_message(
                f"ATENCAO: {failed_count} comentario(s) permaneceram no idioma "
                f"original em {len(failed_files)} arquivo(s). {onde}"
            )
            for failed_file in sorted(failed_files):
                app.log_message(f"  - {os.path.basename(failed_file)}")

        # Registra (ou apaga) a lista para o "Reprocessar falhas" (ROADMAP 7.3).
        # A condicao de cancelamento vive dentro de `registrar_falhas`, porque
        # agora ha duas chamadas — esta e a do tratador de excecao — e a regra
        # precisa valer para as duas.
        registrar_falhas()

        # Chegou ao fim sem cancelamento e sem excecao: a barra pode ir a 100%.
        # Com o disjuntor a execucao passa por aqui tambem (`aborted_by_api`), e
        # ai o `finally` a devolve ao repouso — nada foi concluido.
        completed = not aborted_by_api

        if not canceled:
            # A linha dos lances so aparece quando houve o que corrigir: uma
            # execucao entre idiomas que compartilham as letras (es -> pt) nunca
            # corrige nada, e um "Lances corrigidos: 0" fixo so faria o usuario
            # procurar um problema que nao existe.
            linha_lances = f"\nLances corrigidos: {move_fixes}" if move_fixes else ""
            linha_semicolon = (
                f"\nComentarios ';' ignorados: {total_semicolon}"
                if total_semicolon
                else ""
            )
            # Mesmo criterio das duas linhas acima: aparece quando ha o que
            # dizer. Sem ela, "Total de comentarios: 1.000" com "Reutilizados do
            # cache: 300" e "Novas: 400" nao fecha a conta, e o usuario fica
            # procurando os 300 que sumiram (eles sao repeticoes).
            linha_repetidos = (
                f"\nRepetidos no proprio arquivo: {repetidos}" if repetidos else ""
            )
            resumo = (
                f"Total de comentarios: {total_comments}{linha_repetidos}\n"
                f"Novas traducoes: {translated_count}\n"
                f"Vazias preenchidas: {filled_empty_count}\n"
                f"Removidos por limpeza: {cleaned_empty_count}\n"
                f"Reutilizados do cache: {cache_count}\n"
                f"Falharam: {failed_count}\n"
                f"Arquivos gerados: {generated_files}{linha_lances}{linha_semicolon}"
            )

            if aborted_by_api:
                app.root.after(
                    0,
                    lambda texto=resumo, n=MAX_CONSECUTIVE_FAILED_BATCHES: (
                        messagebox.showwarning(
                            "Interrompido: API sem resposta",
                            f"A traducao foi interrompida depois de {n} lotes "
                            f"seguidos sem resposta da API.\n\n"
                            f"O que ja havia sido traduzido esta gravado no "
                            f"banco. Verifique a conexao e execute de novo — "
                            f"so o que falta sera traduzido.\n\n{texto}"
                        )
                    )
                )
            elif failed_count:
                app.root.after(
                    0,
                    lambda texto=resumo, n=failed_count, arquivos=len(failed_files): (
                        messagebox.showwarning(
                            "Concluido com falhas",
                            f"Traducao finalizada, mas {n} comentario(s) nao "
                            f"puderam ser traduzidos e permaneceram no idioma "
                            f"original em {arquivos} arquivo(s).\n\n{texto}"
                        )
                    )
                )
            else:
                app.root.after(
                    0,
                    lambda texto=resumo: messagebox.showinfo(
                        "Concluido",
                        f"Traducao finalizada!\n\n{texto}"
                    )
                )

    except Exception as e:
        app.log_message(f"[ERRO GERAL] {e}")
        # A lista de falhas desta execucao, ANTES de a excecao levar tudo. O que
        # existia antes deste registro era pior do que nao ter lista: a da
        # execucao anterior continuava valendo, e "Reprocessar Falhas" reprocessava
        # com confianca os arquivos de uma execucao que nao era esta (garantia T4).
        registrar_falhas()
        app.root.after(
            0,
            lambda err=str(e): messagebox.showerror(
                "Erro",
                f"Ocorreu um erro durante o processamento:\n{err}"
            )
        )

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                app.log_message(f"[ERRO] Falha ao fechar banco de dados: {e}")
        http_session.close()

        # A barra termina num estado que significa algo: cheia quando a execucao
        # concluiu, vazia quando nao — cancelada, interrompida pelo disjuntor ou
        # morta por excecao. Congelada no meio ela dizia "estou trabalhando" para
        # sempre, e era o unico sinal na tela que continuava mentindo depois do
        # dialogo de aviso.
        app.root.after(0, lambda v=1.0 if completed else 0.0: app.progress.set(v))

        app.is_processing = False
        app.pause_flag.clear()
        app.cancel_flag.clear()
        app.root.after(0, app._reset_buttons)
