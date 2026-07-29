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
    save_translation,
)
from .glossario import (
    apply_automatic_substitutions,
    clean_comment_for_translation,
    load_automatic_substitutions,
    load_cleanup_substitutions,
)
from .pgn_utils import (
    available_output_path,
    collect_pgn_files,
    create_comment_batches,
    extract_comments_from_file,
    generate_translated_pgn,
    join_comments_for_batch,
    split_batch_translation,
    translated_output_path,
)
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
    http_session = requests.Session()
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
        cleanup_rules = load_cleanup_substitutions()
        if cleanup_rules:
            app.log_message(f"Regras de limpeza carregadas: {len(cleanup_rules)}")
        automatic_rules = load_automatic_substitutions()
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
        use_bom = read_output_settings(load_settings())["utf8_bom"]

        info_by_file = {}
        total_comments = 0
        total_semicolon = 0
        comentarios_do_lote = []

        for pgn_file in pgn_files:
            if app.cancel_flag.is_set():
                canceled = True
                app.log_message("Traducao cancelada antes da extracao completa.")
                return

            info = extract_comments_from_file(pgn_file, app.log_message)
            info_by_file[pgn_file] = info
            total_comments += len(info["comments"])
            comentarios_do_lote.extend(info["comments"])
            # Garantia X3: o que o pipeline ignora e contado e anunciado. Sem
            # isto, um PGN anotado so com `;` termina em "nenhum comentario
            # encontrado" e o usuario conclui que o programa falhou.
            ignorados = info.get("semicolon_comments", 0)
            if ignorados:
                total_semicolon += ignorados
                app.log_message(
                    f"  - {ignorados} comentario(s) no formato ';' ignorados "
                    f"(nao suportado)."
                )

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

        # ANTES da carga do cache, e nao depois: adotar rotula as linhas destes
        # comentarios que ainda nao tem idioma de origem, e e isso que faz o
        # cache ja gravado continuar valendo quando o usuario passa a declarar o
        # idioma. Depois da carga, a adocao chegaria tarde — o cache ja teria
        # vindo vazio e a execucao ja teria decidido pagar tudo de novo.
        adotadas = adopt_unknown_source_language(
            cursor, target_language, source_language, comentarios_do_lote
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
            comentarios_do_lote,
            source_language=source_language,
        )
        # Contado sobre a lista, e nao por `len(cache)`: acima do limite a carga
        # completa sai mais barata e o dicionario vem com o idioma inteiro, entao
        # o tamanho dele nao diz nada sobre ESTES arquivos.
        reaproveitaveis = len(
            {c for c in comentarios_do_lote if c in app.translation_cache}
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
        failed_count = 0
        generated_files = 0
        failed_files = set()
        consecutive_failed_batches = 0
        aborted_by_api = False

        def update_progress():
            value = (processed_comments / total_comments) * 100 if total_comments > 0 else 0
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
            info = info_by_file[pgn_file]
            comments = info["comments"]
            positions = info["positions"]

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
                    batch_pause_time += wait_if_paused()

                    if app.cancel_flag.is_set():
                        canceled = True
                        conn.commit()
                        app.log_message("Traducao cancelada pelo usuario.")
                        return

                    originals = [item[0] for item in to_translate]
                    masked_texts = [item[1] for item in to_translate]
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
                        # A API respondeu — o disjuntor conta lotes SEM resposta,
                        # e nao lotes desalinhados. Desalinhamento e um problema
                        # do conteudo, nao da conexao.
                        consecutive_failed_batches = 0
                        parts = split_batch_translation(translated_joined, len(originals))

                    if parts:
                        for (original, _masked, tokens), part in zip(to_translate, parts):
                            translation = apply_automatic_substitutions(part, automatic_rules)
                            # Depois das regras automaticas e ANTES de gravar: o
                            # que vai para o banco e para o PGN e o mesmo texto,
                            # entao corrigir aqui cobre os dois de uma vez.
                            translation, corrigidos = fix_move_notation(
                                original, translation, source_language, target_language
                            )
                            # A restauracao e o ULTIMO passo, e e verificada: se
                            # a traducao nao devolveu cada sentinela exatamente
                            # uma vez, gravar seria guardar uma anotacao
                            # corrompida com cara de certa. O comentario conta
                            # como falha e fica no idioma original (T2/T3).
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
                        # A CHAMADA falhou (garantia B3). Nao e desalinhamento:
                        # o `translate_text` acabou de gastar as 3 tentativas
                        # dele contra o endpoint e voltou de maos vazias.
                        #
                        # Reprocessar comentario a comentario aqui era o pior
                        # caminho possivel. Cada um gasta outras 3 tentativas,
                        # cada tentativa espera ate os 30 s de timeout: um lote
                        # de 40 comentarios contra um endpoint que pendura a
                        # conexao levava perto de uma hora para terminar com os
                        # 40 contados como falha do mesmo jeito. E, ate agora,
                        # este era o unico caminho SEM log — o `if
                        # translated_joined` deixava a mensagem de fora
                        # justamente quando a causa era a pior.
                        #
                        # T2/T3 continuam valendo: os comentarios ficam no
                        # idioma original e sao contados e informados.
                        failed_count += len(to_translate)
                        failed_files.add(pgn_file)
                        consecutive_failed_batches += 1
                        app.log_message(
                            f"  - [FALHA] A API nao respondeu para o lote "
                            f"({len(originals)} comentarios). Eles ficam no "
                            f"idioma original."
                        )
                        if consecutive_failed_batches >= MAX_CONSECUTIVE_FAILED_BATCHES:
                            # Disjuntor: se N lotes seguidos falharam inteiros, o
                            # problema nao e um comentario, e a conexao ou o
                            # endpoint. Insistir so arrasta a execucao por horas
                            # para terminar com tudo falhando igual.
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
                        for original, masked, tokens in to_translate:
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
                                # A mesma verificacao do caminho do lote, e nao
                                # por zelo: uma correcao que so existisse num
                                # dos dois daria uma execucao cujo resultado
                                # depende de a rede ter respondido alinhada — a
                                # licao da secao 10.4 do ROADMAP.
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
                                # Comita AQUI, e nao no fim do lote (garantia
                                # C3). O primeiro INSERT abre a transacao de
                                # escrita; deixar para comitar depois do laco a
                                # manteria aberta atravessando todas as chamadas
                                # de rede restantes — num lote de 40 comentarios
                                # a ~1 s por requisicao sao 40 s de lock retido,
                                # mais que o `busy_timeout` do editor. O caminho
                                # do lote alinhado nao precisa disso: la as
                                # gravacoes acontecem todas depois da unica
                                # chamada de API.
                                conn.commit()
                                if save_status == "inserted":
                                    translated_count += 1
                                elif save_status == "filled_empty":
                                    filled_empty_count += 1
                            else:
                                # Garantia T2/T3: o comentario fica no idioma
                                # original no arquivo de saida, mas isso precisa
                                # ser contado e informado ao usuario.
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

                    processed_comments += len(to_translate)
                    update_progress()

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
        #
        # Uma execucao cancelada nao pode chegar aqui: os arquivos ainda nao
        # visitados nao foram avaliados, e gravar esta lista parcial por cima da
        # anterior perderia o que ela ja sabia. Hoje quem garante isso e o
        # `return` de cada ponto de cancelamento, que pula todo este trecho — a
        # condicao abaixo e redundante e esta aqui so para que mudar aquela
        # estrutura nao passe a sobrescrever a lista em silencio. O invariante
        # tem teste proprio, que nao depende de qual dos dois o assegura.
        if not canceled:
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
            resumo = (
                f"Total de comentarios: {total_comments}\n"
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

        app.is_processing = False
        app.pause_flag.clear()
        app.cancel_flag.clear()
        app.root.after(0, app._reset_buttons)
