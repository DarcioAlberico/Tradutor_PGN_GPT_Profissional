"""Piloto do modelo de linguagem — ROADMAP 28.7, passo 0.

Um script, e nao codigo de produto, de proposito: ele existe para decidir se o
provedor de 28.7 e construido. A regua e a que a revisao critica mediu no banco
de dev — **o humano aceita 64 % das linhas do `gtx` sem editar** (504 de 784) —
e a barra e **>= 80 % aceitas sem editar** na leitura cega, com **zero**
divergencia de ancora que o portao nao pegue.

Quatro passos, cada um um subcomando, cada um gravando em `piloto/`:

    python ferramentas/piloto_llm.py amostrar
        200 comentarios do livro de dev, estratificados: 100 fragmentos
        terminados em preposicao, 50 longos, 50 com citacao de partida.
        Tirados de preferencia das 784 linhas que um humano JA julgou (a
        decisao dele e a referencia gratis), com o lance anterior e o
        seguinte lidos do PGN como contexto. Nao precisa de chave.

    python ferramentas/piloto_llm.py traduzir --modelo claude-opus-5
        Traduz a amostra em lotes JSON numerados, com a mascara X1 antes e
        as regras automaticas depois, como o pipeline. Grava a saida crua,
        a saida tratada e o `usage` de cada requisicao. Precisa de
        `ANTHROPIC_API_KEY` e de `pip install anthropic`. Rode uma vez por
        modelo; o relatorio compara todos.

    python ferramentas/piloto_llm.py avaliar
        Os 33 detectores de 28.2, o portao de ancoras, o sentinela, a
        concordancia com o texto que o humano deixou, tokens por linha,
        `cache_read_input_tokens`, lotes cortados por `max_tokens`. Grava
        `piloto/relatorio.md`. Nao precisa de chave.

    python ferramentas/piloto_llm.py folha
        A folha de leitura cega: original, traducao A e traducao B em ordem
        sorteada por linha, SEM dizer qual e o Google e qual e o modelo, e
        tres colunas para preencher (aceito A, aceito B, melhor). O gabarito
        fica em `piloto/gabarito.json`; nao abra antes de preencher.

    python ferramentas/piloto_llm.py apurar
        Le a folha preenchida e diz a taxa de "aceito sem editar" por motor.
        E o numero que decide.

Roda da RAIZ do projeto (`sys.path` abaixo cuida do import). Le o banco de dev
em `mode=ro`: o piloto nunca escreve em `traducoes.db`.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tradutor_pgn.annotation_mask import (  # noqa: E402
    PLAYER_PAIR_RE,
    mask_annotations,
    restore_annotations,
)
from tradutor_pgn.chess_notation import (  # noqa: E402
    fix_move_notation,
    move_anchors,
)
from tradutor_pgn.glossario import (  # noqa: E402
    apply_automatic_substitutions,
    load_automatic_substitutions,
    load_interactive_substitutions,
)
from tradutor_pgn.llm_prompt import (  # noqa: E402
    ESQUEMA_DO_LOTE,  # noqa: F401 - reexportado para quem le o piloto
    MAX_SUGESTOES_POR_LOTE,
    regras_automaticas_em_texto,  # noqa: F401 - idem
    terminologia_da_semente,  # noqa: F401 - idem
    validar_lote,  # noqa: F401 - idem
)
from tradutor_pgn import llm_prompt  # noqa: E402
from tradutor_pgn.prose_fixes import normalize_prose  # noqa: E402
from tradutor_pgn.review_quality import evaluate_translation_quality  # noqa: E402

PASTA = RAIZ / "piloto"
BANCO = RAIZ / "traducoes.db"
ORIGEM, DESTINO = "en", "pt"
SEMENTE_SORTEIO = 28

# O dia em que a sessao de IA editou 3.420 das 3.685 linhas do historico. Uma
# linha cujo PRIMEIRO evento e desse dia nao foi julgada por humano nenhum; as
# 784 restantes com historico foram (memoria da revisao de 2026-09-14).
DIA_DA_IA = "2026-08-01"

# Preposicoes e conjuncoes que fecham um fragmento cortado — o estrato que 28.4
# mediu como o mais caro (~3,7 h por livro).
PREPOSICAO_FINAL_RE = re.compile(
    r"\b(after|with|of|for|to|in|on|by|from|at|into|against|before|"
    r"without|than|and|or|but)\s*[.…]*\s*$",
    re.IGNORECASE,
)
LONGO_MINIMO = 250
ESTRATOS = (("preposicao", 100), ("citacao", 50), ("longo", 50))

# Um lance no PGN, para o contexto de leitura: "23.Nf3", "23...Bxe4", "O-O".
LANCE_RE = re.compile(
    r"(?:\d+\.(?:\.\.)?\s*)?(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?)[+#!?]*"
)

# Precos por milhao de tokens (US$), da tabela da referencia da API em
# 2026-06. Leitura de cache a 10 % da entrada e escrita a 125 %, a conferir na
# fatura — o piloto existe para calibrar chutes como este.
PRECOS = {
    "claude-opus-5": {"entrada": 5.0, "saida": 25.0, "cache_leitura": 0.5, "cache_escrita": 6.25},
    "claude-sonnet-5": {"entrada": 2.0, "saida": 10.0, "cache_leitura": 0.2, "cache_escrita": 2.5},
}

TAMANHO_DO_LOTE = 20
MAX_TOKENS = 16000


# ============================================================ utilitarios


def abrir_banco():
    return sqlite3.connect(f"file:{BANCO.as_posix()}?mode=ro", uri=True)


def gravar_json(nome, dados):
    PASTA.mkdir(exist_ok=True)
    caminho = PASTA / nome
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return caminho


def ler_json(nome):
    caminho = PASTA / nome
    if not caminho.exists():
        sys.exit(f"Falta {caminho}. Rode o passo anterior primeiro.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def normalizar_espacos(texto):
    return re.sub(r"\s+", " ", (texto or "").strip())


# ============================================================ 1. amostrar


def classificar(original):
    """Os estratos a que um original pertence (pode ser mais de um)."""
    estratos = set()
    if PREPOSICAO_FINAL_RE.search(original or ""):
        estratos.add("preposicao")
    if PLAYER_PAIR_RE.search(original or ""):
        estratos.add("citacao")
    if len(original or "") > LONGO_MINIMO:
        estratos.add("longo")
    return estratos


def julgada_por_humano(primeiro_evento):
    """`True` quando alguem olhou a linha: ha historico e ele nao e da IA."""
    return primeiro_evento is not None and not primeiro_evento.startswith(DIA_DA_IA)


def sortear_estratificado(linhas, estratos=ESTRATOS, semente=SEMENTE_SORTEIO):
    """Sorteia `n` linhas por estrato, sem repetir linha, preferindo as julgadas.

    `linhas` e uma lista de dicts com `original` e `julgada`. Cada linha entra
    num estrato so — o primeiro da ordem de `estratos` em que ela foi sorteada
    — para os 200 serem 200 comentarios distintos. As nao julgadas so entram
    quando as julgadas do estrato acabam (o estrato "longo" tem 46 julgadas
    para 50 vagas no banco de dev), e a linha diz isso em `julgada`.
    """
    sorteio = random.Random(semente)
    usados = set()
    amostra = []
    for nome, quantas in estratos:
        candidatas = [
            linha for linha in linhas
            if nome in classificar(linha["original"]) and linha["id"] not in usados
        ]
        julgadas = [c for c in candidatas if c["julgada"]]
        outras = [c for c in candidatas if not c["julgada"]]
        sorteio.shuffle(julgadas)
        sorteio.shuffle(outras)
        escolhidas = (julgadas + outras)[:quantas]
        for linha in escolhidas:
            usados.add(linha["id"])
            amostra.append(dict(linha, estrato=nome))
    return amostra


def contexto_de_leitura(conteudo_pgn, original):
    """`(lance_anterior, lance_seguinte)` em volta do comentario no PGN.

    E o contexto que 28.7 quer dar ao modelo: ~20 bytes por lado, lidos do
    proprio arquivo. O original foi extraido por `flatten_comment`, que
    normaliza espacos E insere um espaco depois de `.!?` seguido de letra
    (`K.Shiven` -> `K. Shiven`), entao entre duas palavras do original pode
    haver no arquivo qualquer espaco em branco — ou nenhum.
    """
    if not conteudo_pgn or not original:
        return "", ""
    padrao = r"\{\s*" + r"\s*".join(re.escape(p) for p in original.split()) + r"\s*\}"
    achado = re.search(padrao, conteudo_pgn)
    if achado is None:
        return "", ""
    antes = conteudo_pgn[max(0, achado.start() - 80):achado.start()]
    depois = conteudo_pgn[achado.end():achado.end() + 80]
    lances_antes = LANCE_RE.findall(antes)
    lances_depois = LANCE_RE.findall(depois)
    return (lances_antes[-1].strip() if lances_antes else "",
            lances_depois[0].strip() if lances_depois else "")


def amostrar(args):
    conn = abrir_banco()
    linhas = []
    for row in conn.execute(
        """
        SELECT c.id, c.original_comment, c.translated_comment, c.verified,
               (SELECT MIN(created_at) FROM comment_history h WHERE h.comment_id = c.id),
               (SELECT previous_translation FROM comment_history h
                 WHERE h.comment_id = c.id ORDER BY id LIMIT 1),
               (SELECT action FROM comment_history h
                 WHERE h.comment_id = c.id ORDER BY id LIMIT 1)
        FROM comments c
        WHERE c.source_language = ? AND c.target_language = ?
        """,
        (ORIGEM, DESTINO),
    ):
        cid, original, atual, verified, primeiro, maquina, acao = row
        linhas.append({
            "id": cid,
            "original": original or "",
            # O que o gtx produziu: `previous_translation` do evento mais antigo,
            # ou o texto atual quando ninguem mexeu (`machine_translation_for`).
            "google": (maquina if maquina is not None else atual) or "",
            # O que o humano deixou — so vale como referencia quando ele julgou.
            "humano": atual or "",
            "julgada": julgada_por_humano(primeiro),
            "primeira_acao": acao,
            "verificada": bool(verified),
        })
    arquivos = [r[0] for r in conn.execute("SELECT DISTINCT source_file FROM occurrences")]
    conn.close()

    amostra = sortear_estratificado(linhas)

    conteudo = ""
    for arquivo in arquivos:
        if os.path.exists(arquivo):
            from tradutor_pgn.pgn_utils import read_pgn_text
            conteudo += read_pgn_text(arquivo)[0] + "\n"
        else:
            print(f"[aviso] PGN nao encontrado, sem contexto de lances: {arquivo}")
    com_contexto = 0
    for item in amostra:
        item["lance_anterior"], item["lance_seguinte"] = contexto_de_leitura(conteudo, item["original"])
        com_contexto += bool(item["lance_anterior"] or item["lance_seguinte"])

    caminho = gravar_json("amostra.json", amostra)
    por_estrato = Counter(i["estrato"] for i in amostra)
    julgadas = sum(i["julgada"] for i in amostra)
    aceitas = sum(1 for i in amostra if i["julgada"] and i["primeira_acao"] in ("verify", "verify_exact_match"))
    print(f"{len(amostra)} comentarios em {caminho}")
    print(f"  por estrato: {dict(por_estrato)}")
    print(f"  julgadas por humano: {julgadas} ({aceitas} aceitas sem editar = "
          f"{100 * aceitas / max(1, julgadas):.0f} % — a regua do Google nesta amostra)")
    print(f"  com contexto de lances: {com_contexto}")


# ============================================================ 2. traduzir

# O prompt, o esquema do lote, a mensagem e a validacao moram em
# `tradutor_pgn.llm_prompt` desde que o provedor de produto existe (ROADMAP
# 28.7): o piloto e o programa falam com o modelo pelo MESMO texto, e uma
# mudanca de prompt e medida aqui antes de valer la. O que fica neste arquivo e
# a adaptacao da forma dos itens da amostra (`mascarado`, `lance_anterior`,
# `lance_seguinte`) para a do modulo (`texto`, `antes`, `depois`).


def prompt_de_sistema(origem=ORIGEM, destino=DESTINO):
    return llm_prompt.prompt_de_sistema(origem, destino)


def sugestoes_para_o_lote(itens, interativas, limite=MAX_SUGESTOES_POR_LOTE):
    return llm_prompt.sugestoes_para_o_lote(
        [item["mascarado"] for item in itens], interativas, limite
    )


def mensagem_do_lote(itens, sugestoes):
    return llm_prompt.mensagem_do_lote(
        [
            {
                "id": item["id"],
                "texto": item["mascarado"],
                "antes": item.get("lance_anterior", ""),
                "depois": item.get("lance_seguinte", ""),
            }
            for item in itens
        ],
        sugestoes,
    )


def custo_em_dolares(modelo, uso):
    p = PRECOS.get(modelo)
    if not p:
        return None
    return (
        uso["input_tokens"] * p["entrada"]
        + uso["output_tokens"] * p["saida"]
        + uso["cache_read_input_tokens"] * p["cache_leitura"]
        + uso["cache_creation_input_tokens"] * p["cache_escrita"]
    ) / 1_000_000


def _uso(resposta):
    u = resposta.usage
    return {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


def _texto_da_resposta(resposta):
    return next((b.text for b in resposta.content if b.type == "text"), "")


def pos_processar(original, cru, tokens, automaticas):
    """O que o pipeline faz depois da API: restaurar X1, automaticas, lances.

    Devolve um dict com o texto final, se a restauracao passou, quantos lances
    a correcao de letra ainda precisou trocar e se `normalize_prose` mudaria
    algo — a ultima e a pergunta de 28.2 camada 2: os artefatos do `gtx`
    (`U+200B`, hifen colado, reticencia) aparecem num modelo instruido?
    """
    restaurado, ok = restore_annotations(cru, tokens)
    if not ok:
        return {"final": "", "sentinela_ok": False, "lances_corrigidos": 0, "prosa_mudaria": False}
    texto = apply_automatic_substitutions(restaurado, automaticas)
    texto, corrigidos = fix_move_notation(original, texto, ORIGEM, DESTINO)
    normalizado, consertos = normalize_prose(original, texto, ORIGEM, DESTINO)
    return {
        "final": texto,
        "sentinela_ok": True,
        "lances_corrigidos": corrigidos,
        "prosa_mudaria": normalizado != texto,
        "prosa_consertos": consertos,
    }


def traduzir(args, client=None, amostra=None):
    """`client` e `amostra` sao injetaveis para o teste rodar o fluxo inteiro
    sem rede; sem eles, e o SDK com a chave do ambiente e `piloto/amostra.json`."""
    if client is None:
        try:
            import anthropic
        except ImportError:
            sys.exit("Falta o SDK: pip install anthropic (ou uv pip install anthropic).")
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY do ambiente
    if amostra is None:
        amostra = ler_json("amostra.json")
    modelo = args.modelo

    automaticas = load_automatic_substitutions(source_language=ORIGEM, target_language=DESTINO)
    interativas = load_interactive_substitutions(source_language=ORIGEM, target_language=DESTINO)
    sistema = [
        {"type": "text", "text": prompt_de_sistema(), "cache_control": {"type": "ephemeral"}},
        {
            "type": "text",
            "text": regras_automaticas_em_texto(automaticas),
            "cache_control": {"type": "ephemeral"},
        },
    ]

    for item in amostra:
        item["mascarado"], item["_tokens"] = mask_annotations(item["original"])

    def chamar(itens):
        sugestoes = sugestoes_para_o_lote(itens, interativas)
        inicio = time.perf_counter()
        resposta = client.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS,
            system=sistema,
            messages=[{"role": "user", "content": mensagem_do_lote(itens, sugestoes)}],
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA_DO_LOTE}},
        )
        duracao = time.perf_counter() - inicio
        por_id, problemas = validar_lote(_texto_da_resposta(resposta), [i["id"] for i in itens])
        return {
            "ids": [i["id"] for i in itens],
            "sugestoes": len(sugestoes),
            "stop_reason": resposta.stop_reason,
            "uso": _uso(resposta),
            "segundos": round(duracao, 1),
            "problemas": problemas,
        }, por_id

    saidas = {}
    requisicoes = []
    lotes = [amostra[i:i + args.lote] for i in range(0, len(amostra), args.lote)]
    if args.max_lotes:
        lotes = lotes[:args.max_lotes]
    for n, lote in enumerate(lotes, start=1):
        registro, por_id = chamar(lote)
        requisicoes.append(registro)
        print(f"lote {n}/{len(lotes)}: {registro['stop_reason']}, "
              f"{registro['uso']['input_tokens']} in / {registro['uso']['output_tokens']} out, "
              f"cache lido {registro['uso']['cache_read_input_tokens']}, "
              f"{registro['segundos']} s, {len(registro['problemas'])} problema(s)")
        for item in lote:
            if item["id"] in por_id:
                saidas[item["id"]] = por_id[item["id"]]
        # Como B1/B2: o que faltou ou veio torto e reenviado sozinho, uma vez.
        faltantes = [i for i in lote if i["id"] not in por_id]
        for item in faltantes:
            registro, por_id_unico = chamar([item])
            registro["reenvio"] = True
            requisicoes.append(registro)
            if item["id"] in por_id_unico:
                saidas[item["id"]] = por_id_unico[item["id"]]

    resultados = []
    for item in amostra:
        if item["id"] not in saidas:
            if args.max_lotes:
                continue
            resultados.append({"id": item["id"], "cru": None, "final": "", "sentinela_ok": False,
                               "falhou": True})
            continue
        cru = saidas[item["id"]]
        tratado = pos_processar(item["original"], cru, item["_tokens"], automaticas)
        resultados.append({"id": item["id"], "cru": cru, **tratado})

    total = Counter()
    for r in requisicoes:
        total.update(r["uso"])
    total = dict(total)
    for chave in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        total.setdefault(chave, 0)
    resumo = {
        "modelo": modelo,
        "quando": time.strftime("%Y-%m-%d %H:%M"),
        "itens": len(resultados),
        "requisicoes": len(requisicoes),
        "reenvios": sum(1 for r in requisicoes if r.get("reenvio")),
        "cortados_por_max_tokens": sum(1 for r in requisicoes if r["stop_reason"] == "max_tokens"),
        "uso_total": total,
        "custo_usd": custo_em_dolares(modelo, total),
        "segundos": round(sum(r["segundos"] for r in requisicoes), 1),
    }
    nome = f"traducoes-{modelo}.json"
    gravar_json(nome, {"resumo": resumo, "requisicoes": requisicoes, "resultados": resultados})
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    print(f"gravado em piloto/{nome}")


# ============================================================ 3. avaliar


def google_de_hoje(item):
    """O texto do gtx como o pipeline de HOJE o entregaria.

    O que esta no banco e o que a maquina produziu em 2026-08, antes de
    `normalize_prose` (P5/P6/P7) existir — 63 dos 87 avisos do Google na
    amostra sao o `after` -> `depois` sem `de`, que o pipeline ja conserta. A
    leitura cega compara o modelo com o programa de hoje, e nao com o de
    agosto; o "google" cru fica no relatorio porque e o que os 64 % mediram.
    """
    texto, _consertos = normalize_prose(item["original"], item["google"], ORIGEM, DESTINO)
    return texto


def motores_disponiveis(amostra):
    """`{nome: {id: traducao}}` — o Google vem do banco, os modelos dos arquivos."""
    motores = {
        "google": {i["id"]: i["google"] for i in amostra},
        "google-hoje": {i["id"]: google_de_hoje(i) for i in amostra},
    }
    for caminho in sorted(PASTA.glob("traducoes-*.json")):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        motores[dados["resumo"]["modelo"]] = {
            r["id"]: r.get("final", "") for r in dados["resultados"]
        }
    return motores


def similaridade(a, b):
    return difflib.SequenceMatcher(None, normalizar_espacos(a), normalizar_espacos(b)).ratio()


def avaliar_motor(amostra, traducoes):
    """As contagens de um motor sobre a amostra (so os itens que ele cobriu)."""
    itens = [i for i in amostra if i["id"] in traducoes]
    contagem = {"itens": len(itens), "com_aviso_qa": 0, "ancora_divergente": 0, "vazias": 0}
    avisos = Counter()
    iguais_ao_humano = 0
    similaridades = []
    julgadas_editadas = 0
    por_estrato = {nome: {"itens": 0, "com_aviso_qa": 0, "ancora_divergente": 0} for nome, _n in ESTRATOS}
    for item in itens:
        trad = traducoes[item["id"]] or ""
        if not trad.strip():
            contagem["vazias"] += 1
        lista = evaluate_translation_quality(item["original"], trad, ORIGEM, DESTINO)
        if lista:
            contagem["com_aviso_qa"] += 1
            por_estrato[item["estrato"]]["com_aviso_qa"] += 1
            for aviso in lista:
                avisos[aviso.split(":")[0][:60]] += 1
        if move_anchors(item["original"]) != move_anchors(trad):
            contagem["ancora_divergente"] += 1
            por_estrato[item["estrato"]]["ancora_divergente"] += 1
        por_estrato[item["estrato"]]["itens"] += 1
        if item["julgada"] and item["primeira_acao"] in ("edit", "edit_verify"):
            julgadas_editadas += 1
            similaridades.append(similaridade(trad, item["humano"]))
            if normalizar_espacos(trad) == normalizar_espacos(item["humano"]):
                iguais_ao_humano += 1
    contagem["avisos_mais_comuns"] = avisos.most_common(8)
    contagem["julgadas_editadas"] = julgadas_editadas
    contagem["iguais_ao_texto_do_humano"] = iguais_ao_humano
    contagem["similaridade_media_com_o_humano"] = (
        round(sum(similaridades) / len(similaridades), 3) if similaridades else None
    )
    contagem["por_estrato"] = por_estrato
    return contagem


def avaliar(args):
    amostra = ler_json("amostra.json")
    motores = motores_disponiveis(amostra)
    linhas = ["# Piloto do modelo de linguagem — avaliacao automatica", ""]
    linhas.append(f"Amostra: {len(amostra)} comentarios; {sum(i['julgada'] for i in amostra)} "
                  f"julgados por humano, dos quais "
                  f"{sum(1 for i in amostra if i['julgada'] and i['primeira_acao'] in ('edit', 'edit_verify'))} "
                  "editados (a referencia da similaridade).")
    linhas.append("")
    linhas.append("| motor | itens | com aviso QA | ancora divergente | vazias | iguais ao humano (das editadas) | similaridade media |")
    linhas.append("|---|---|---|---|---|---|---|")
    avaliacoes = {}
    for nome, traducoes in motores.items():
        c = avaliar_motor(amostra, traducoes)
        avaliacoes[nome] = c
        linhas.append(
            f"| {nome} | {c['itens']} | {c['com_aviso_qa']} | {c['ancora_divergente']} | {c['vazias']} | "
            f"{c['iguais_ao_texto_do_humano']}/{c['julgadas_editadas']} | {c['similaridade_media_com_o_humano']} |"
        )
    linhas.append("")
    for nome, c in avaliacoes.items():
        linhas.append(f"## {nome}")
        linhas.append("")
        linhas.append("Por estrato (itens / com aviso QA / ancora divergente):")
        for estrato, v in c["por_estrato"].items():
            linhas.append(f"- {estrato}: {v['itens']} / {v['com_aviso_qa']} / {v['ancora_divergente']}")
        linhas.append("")
        linhas.append("Avisos mais comuns:")
        for aviso, quantas in c["avisos_mais_comuns"]:
            linhas.append(f"- {quantas}x {aviso}")
        linhas.append("")
    for caminho in sorted(PASTA.glob("traducoes-*.json")):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        r = dados["resumo"]
        resultados = dados["resultados"]
        linhas.append(f"## Custo e mecanica — {r['modelo']} ({r['quando']})")
        linhas.append("")
        uso = r["uso_total"]
        entrada_total = uso["input_tokens"] + uso["cache_read_input_tokens"] + uso["cache_creation_input_tokens"]
        linhas.append(f"- requisicoes: {r['requisicoes']} ({r['reenvios']} reenvios individuais), "
                      f"{r['segundos']} s no total")
        linhas.append(f"- tokens: entrada {entrada_total} (cache lido {uso['cache_read_input_tokens']}, "
                      f"cache escrito {uso['cache_creation_input_tokens']}), saida {uso['output_tokens']}")
        if r["itens"]:
            linhas.append(f"- por linha: {entrada_total / r['itens']:.0f} de entrada, "
                          f"{uso['output_tokens'] / r['itens']:.0f} de saida")
        linhas.append(f"- cache lido / entrada total: "
                      f"{100 * uso['cache_read_input_tokens'] / max(1, entrada_total):.0f} %")
        linhas.append(f"- lotes cortados por max_tokens: {r['cortados_por_max_tokens']}")
        linhas.append(f"- custo: US$ {r['custo_usd']:.4f}" if r["custo_usd"] is not None else "- custo: modelo sem preco na tabela")
        sentinela_falhou = sum(1 for x in resultados if not x.get("sentinela_ok", True))
        com_mascara = sum(1 for i in amostra if mask_annotations(i["original"])[1])
        linhas.append(f"- sentinela ⟦n⟧: {sentinela_falhou} falha(s) em {com_mascara} item(ns) mascarados")
        linhas.append(f"- lances que fix_move_notation ainda corrigiu: "
                      f"{sum(x.get('lances_corrigidos', 0) for x in resultados)}")
        linhas.append(f"- itens em que normalize_prose mudaria algo (artefatos do gtx?): "
                      f"{sum(1 for x in resultados if x.get('prosa_mudaria'))}")
        linhas.append(f"- itens sem resposta: {sum(1 for x in resultados if x.get('falhou'))}")
        problemas = Counter()
        for req in dados["requisicoes"]:
            for p in req["problemas"]:
                problemas[re.sub(r"\d+", "N", p)] += 1
        if problemas:
            linhas.append("- problemas de lote: " + "; ".join(f"{q}x {p}" for p, q in problemas.most_common(5)))
        linhas.append("")
    linhas.append("A regua que decide nao esta aqui: e a leitura cega (`folha` e `apurar`). "
                  "Google hoje: 64 % aceitas sem editar no banco de dev; barra do piloto: >= 80 %.")
    PASTA.mkdir(exist_ok=True)
    (PASTA / "relatorio.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print("\n".join(linhas))
    print("\ngravado em piloto/relatorio.md")


# ============================================================ 4. folha e apurar


def montar_folha(amostra, esquerda, direita, semente=SEMENTE_SORTEIO):
    """`(linhas_da_folha, gabarito)`: A/B sorteados por linha, sem rotulo.

    `esquerda`/`direita` sao `(nome, {id: traducao})`. O gabarito diz, por
    numero de linha, qual motor ficou em A e qual em B — e fica noutro
    arquivo, para a leitura ser cega de verdade.
    """
    sorteio = random.Random(semente + 1)
    linhas = []
    gabarito = {}
    for n, item in enumerate(amostra, start=1):
        motores = [esquerda, direita]
        sorteio.shuffle(motores)
        (nome_a, trad_a), (nome_b, trad_b) = motores
        linhas.append({
            "n": n,
            "id": item["id"],
            "original": item["original"],
            "traducao_A": trad_a.get(item["id"], ""),
            "traducao_B": trad_b.get(item["id"], ""),
            "aceito_A": "",
            "aceito_B": "",
            "melhor": "",
        })
        gabarito[str(n)] = {"A": nome_a, "B": nome_b, "id": item["id"]}
    return linhas, gabarito


def folha(args):
    amostra = ler_json("amostra.json")
    motores = motores_disponiveis(amostra)
    if args.modelo not in motores:
        sys.exit(f"Nao ha traducoes de {args.modelo!r}; disponiveis: {sorted(motores)}")
    linhas, gabarito = montar_folha(
        amostra, ("google-hoje", motores["google-hoje"]), (args.modelo, motores[args.modelo])
    )
    PASTA.mkdir(exist_ok=True)
    caminho = PASTA / f"folha-cega-{args.modelo}.csv"
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)
    gravar_json(f"gabarito-{args.modelo}.json", gabarito)
    print(f"Folha em {caminho} ({len(linhas)} linhas), separador ';', UTF-8 com BOM (abre no Excel).")
    print("Preencha aceito_A e aceito_B com S ou N (\"aceito sem editar\") e melhor com A, B ou =.")
    print(f"NAO abra piloto/gabarito-{args.modelo}.json antes de terminar.")


def apurar_folha(linhas, gabarito):
    """`{motor: {'aceitas', 'julgadas', 'melhor'}}` a partir da folha preenchida."""
    resultado = {}
    for linha in linhas:
        chave = gabarito.get(str(linha["n"]))
        if not chave:
            continue
        for lado in ("A", "B"):
            motor = chave[lado]
            r = resultado.setdefault(motor, {"aceitas": 0, "julgadas": 0, "melhor": 0})
            voto = (linha.get(f"aceito_{lado}") or "").strip().upper()
            if voto in ("S", "N"):
                r["julgadas"] += 1
                r["aceitas"] += voto == "S"
        melhor = (linha.get("melhor") or "").strip().upper()
        if melhor in ("A", "B"):
            resultado[chave[melhor]]["melhor"] += 1
    return resultado


def apurar(args):
    caminho = PASTA / f"folha-cega-{args.modelo}.csv"
    if not caminho.exists():
        sys.exit(f"Falta {caminho}.")
    with caminho.open("r", encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    gabarito = ler_json(f"gabarito-{args.modelo}.json")
    resultado = apurar_folha(linhas, gabarito)
    print(f"Leitura cega — {len(linhas)} linhas")
    for motor, r in resultado.items():
        taxa = 100 * r["aceitas"] / r["julgadas"] if r["julgadas"] else float("nan")
        print(f"  {motor}: {r['aceitas']}/{r['julgadas']} aceitas sem editar = {taxa:.0f} %; "
              f"preferido em {r['melhor']} linha(s)")
    print("Barra de 28.7: >= 80 % aceitas sem editar (Google hoje: 64 % no banco de dev).")


# ============================================================ main


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("amostrar").set_defaults(func=amostrar)
    t = sub.add_parser("traduzir")
    t.add_argument("--modelo", default="claude-opus-5")
    t.add_argument("--lote", type=int, default=TAMANHO_DO_LOTE)
    t.add_argument("--max-lotes", type=int, default=0, help="so os N primeiros lotes (ensaio barato)")
    t.set_defaults(func=traduzir)
    sub.add_parser("avaliar").set_defaults(func=avaliar)
    f = sub.add_parser("folha")
    f.add_argument("--modelo", default="claude-opus-5")
    f.set_defaults(func=folha)
    a = sub.add_parser("apurar")
    a.add_argument("--modelo", default="claude-opus-5")
    a.set_defaults(func=apurar)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
