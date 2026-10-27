"""O piloto do modelo de linguagem (ROADMAP 28.7, passo 0): as partes puras.

O script decide se o provedor e construido, entao o que ele conta tem de
contar certo. Aqui ficam as pecas que nao precisam de chave nem de rede: a
estratificacao, o contexto de leitura, a validacao do lote (B5), o
pos-processamento e a folha cega com o seu gabarito.
"""

import importlib.util
import json
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("piloto_llm", RAIZ / "ferramentas" / "piloto_llm.py")
piloto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(piloto)


def linha(cid, original, julgada=True):
    return {"id": cid, "original": original, "julgada": julgada, "google": "g", "humano": "h"}


class EstratosTests(unittest.TestCase):
    def test_the_three_strata_are_recognised(self):
        self.assertEqual(piloto.classificar("and Black is fine after"), {"preposicao"})
        self.assertEqual(piloto.classificar(", A. Karpov-B. Kasparov, Linares 1993."), {"citacao"})
        self.assertEqual(piloto.classificar("x" * 300), {"longo"})
        self.assertEqual(piloto.classificar("Nothing special here."), set())

    def test_a_line_belongs_to_one_stratum_only_and_the_judged_come_first(self):
        linhas = [linha(n, f"comment {n} after") for n in range(6)]
        linhas += [linha(10 + n, f"comment {n} after", julgada=False) for n in range(6)]
        amostra = piloto.sortear_estratificado(linhas, estratos=(("preposicao", 8),), semente=1)
        ids = [a["id"] for a in amostra]
        self.assertEqual(len(ids), len(set(ids)), "linha repetida")
        self.assertEqual(len(ids), 8)
        self.assertEqual(sorted(i for i in ids if i < 10), [0, 1, 2, 3, 4, 5], "as seis julgadas entram")
        self.assertEqual(sum(1 for a in amostra if not a["julgada"]), 2, "duas nao julgadas completam")

    def test_a_line_in_two_strata_is_not_drawn_twice(self):
        # Citacao E preposicao: cai no primeiro estrato sorteado, e so nele.
        dupla = linha(1, ", A. Karpov-B. Kasparov, Linares 1993, and White wins after")
        amostra = piloto.sortear_estratificado(
            [dupla, linha(2, "a fine move after")], estratos=(("preposicao", 5), ("citacao", 5))
        )
        self.assertEqual(sorted(a["id"] for a in amostra), [1, 2])
        self.assertEqual({a["estrato"] for a in amostra}, {"preposicao"}, "a citacao ficou sem ela")

    def test_the_judgement_flag_excludes_the_ai_day(self):
        self.assertFalse(piloto.julgada_por_humano(None))
        self.assertFalse(piloto.julgada_por_humano("2026-08-01 10:00:00"))
        self.assertTrue(piloto.julgada_por_humano("2026-07-29 10:00:00"))


class ContextoDeLeituraTests(unittest.TestCase):
    PGN = "1. e4 c5 2.Nf3 d6 {A solid choice, see X.Wemmers-K.Shiven,\rAmsterdam 2010.} 3.d4 cxd4 4.Nxd4"

    def test_the_moves_around_the_comment_are_found_across_cr_and_glued_names(self):
        antes, depois = piloto.contexto_de_leitura(
            self.PGN, "A solid choice, see X. Wemmers-K. Shiven, Amsterdam 2010."
        )
        self.assertEqual(antes, "d6")
        self.assertEqual(depois, "3.d4")

    def test_a_comment_that_is_not_in_the_file_gets_no_context(self):
        self.assertEqual(piloto.contexto_de_leitura(self.PGN, "never written"), ("", ""))
        self.assertEqual(piloto.contexto_de_leitura("", "anything"), ("", ""))


class ValidarLoteTests(unittest.TestCase):
    def test_each_id_exactly_once_is_a_clean_batch(self):
        por_id, problemas = piloto.validar_lote(
            json.dumps({"itens": [{"id": 1, "traducao": "a"}, {"id": 2, "traducao": "b"}]}), [1, 2]
        )
        self.assertEqual(por_id, {1: "a", 2: "b"})
        self.assertEqual(problemas, [])

    def test_a_missing_id_is_reported_and_the_rest_kept(self):
        por_id, problemas = piloto.validar_lote(json.dumps({"itens": [{"id": 1, "traducao": "a"}]}), [1, 2])
        self.assertEqual(por_id, {1: "a"})
        self.assertEqual(problemas, ["id 2 faltou"])

    def test_a_duplicated_id_and_a_foreign_id_are_reported(self):
        por_id, problemas = piloto.validar_lote(
            json.dumps({"itens": [{"id": 1, "traducao": "a"}, {"id": 1, "traducao": "b"}, {"id": 9, "traducao": "z"}]}),
            [1],
        )
        self.assertNotIn(9, por_id, "o id do vizinho nao entra")
        self.assertIn("id 1 veio 2 vezes", problemas)
        self.assertIn("id 9 nao era deste lote", problemas)

    def test_invalid_json_is_a_problem_and_not_an_exception(self):
        por_id, problemas = piloto.validar_lote("{not json", [1])
        self.assertEqual(por_id, {})
        self.assertTrue(problemas and problemas[0].startswith("json invalido"))


class PosProcessarTests(unittest.TestCase):
    def test_sentinels_come_back_and_the_automatic_rule_is_applied_after(self):
        original = "White plays [%cal Ra1h8] and wins."
        mascarado, tokens = piloto.mask_annotations(original)
        self.assertIn("⟦0⟧", mascarado)
        saida = piloto.pos_processar(original, "As brancas jogam ⟦0⟧ e vencem.", tokens, [("vencem", "ganham")])
        self.assertTrue(saida["sentinela_ok"])
        self.assertEqual(saida["final"], "As brancas jogam [%cal Ra1h8] e ganham.")

    def test_a_swallowed_sentinel_fails_instead_of_being_kept(self):
        original = "White plays [%cal Ra1h8] and wins."
        _m, tokens = piloto.mask_annotations(original)
        saida = piloto.pos_processar(original, "As brancas jogam e vencem.", tokens, [])
        self.assertFalse(saida["sentinela_ok"])
        self.assertEqual(saida["final"], "")

    def test_the_piece_letter_is_still_fixed_when_the_model_forgets(self):
        saida = piloto.pos_processar("After 12.Nf3 Black is fine.", "Depois de 12.Nf3 as pretas estão bem.", [], [])
        self.assertEqual(saida["lances_corrigidos"], 1)
        self.assertIn("12.Cf3", saida["final"])


class PromptTests(unittest.TestCase):
    def test_the_system_prompt_is_stable_and_names_the_pair_letters(self):
        a = piloto.prompt_de_sistema()
        b = piloto.prompt_de_sistema()
        self.assertEqual(a, b, "um prefixo que muda nao cacheia")
        self.assertIn("K -> R, Q -> D, R -> T, B -> B, N -> C", a)
        self.assertIn("⟦n⟧", a)

    def test_the_batch_message_carries_the_context_and_the_masked_text(self):
        itens = [{"id": 7, "mascarado": "Black is fine ⟦0⟧", "lance_anterior": "12.Nf3", "lance_seguinte": "12...Bg7"}]
        texto = piloto.mensagem_do_lote(itens, ["fine -> bem"])
        corpo = json.loads(texto.split("\n\n")[1])
        self.assertEqual(corpo["itens"][0], {"id": 7, "antes": "12.Nf3", "texto": "Black is fine ⟦0⟧", "depois": "12...Bg7"})
        self.assertIn("fine -> bem", texto)

    def test_only_matching_suggestions_travel_and_the_cap_holds(self):
        itens = [{"mascarado": "the rook and the bishop"}]
        regras = [("rook", "torre", "suggestion"), ("queen", "dama", "suggestion"), ("bishop", "bispo", "suggestion")]
        self.assertEqual(piloto.sugestoes_para_o_lote(itens, regras), ["rook -> torre", "bishop -> bispo"])
        self.assertEqual(piloto.sugestoes_para_o_lote(itens, regras, limite=1), ["rook -> torre"])

    def test_cost_follows_the_price_table(self):
        uso = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.assertEqual(piloto.custo_em_dolares("claude-opus-5", uso), 5.0)
        self.assertIsNone(piloto.custo_em_dolares("modelo-inventado", uso))


class FolhaCegaTests(unittest.TestCase):
    def amostra(self):
        return [{"id": n, "original": f"o{n}", "google": f"g{n}", "humano": "", "julgada": True,
                 "primeira_acao": "verify", "estrato": "preposicao"} for n in range(1, 21)]

    def test_the_sheet_mixes_sides_and_the_key_names_them(self):
        amostra = self.amostra()
        google = {i["id"]: i["google"] for i in amostra}
        modelo = {i["id"]: f"m{i['id']}" for i in amostra}
        linhas, gabarito = piloto.montar_folha(amostra, ("google", google), ("modelo", modelo))
        self.assertEqual(len(linhas), 20)
        lados_a = {gabarito[str(l["n"])]["A"] for l in linhas}
        self.assertEqual(lados_a, {"google", "modelo"}, "A tem de ser ora um, ora outro")
        for l in linhas:
            chave = gabarito[str(l["n"])]
            esperado_a = google[l["id"]] if chave["A"] == "google" else modelo[l["id"]]
            self.assertEqual(l["traducao_A"], esperado_a)
            self.assertNotIn("google", l.values(), "a folha nao pode dizer quem e quem")

    def test_the_tally_credits_each_vote_to_the_right_engine(self):
        amostra = self.amostra()[:4]
        google = {i["id"]: i["google"] for i in amostra}
        modelo = {i["id"]: f"m{i['id']}" for i in amostra}
        linhas, gabarito = piloto.montar_folha(amostra, ("google", google), ("modelo", modelo))
        # Aceita sempre o lado em que o MODELO caiu; recusa o Google; prefere o modelo.
        for l in linhas:
            lado_modelo = "A" if gabarito[str(l["n"])]["A"] == "modelo" else "B"
            lado_google = "B" if lado_modelo == "A" else "A"
            l[f"aceito_{lado_modelo}"] = "s"
            l[f"aceito_{lado_google}"] = "N"
            l["melhor"] = lado_modelo
        resultado = piloto.apurar_folha(linhas, gabarito)
        self.assertEqual(resultado["modelo"], {"aceitas": 4, "julgadas": 4, "melhor": 4})
        self.assertEqual(resultado["google"], {"aceitas": 0, "julgadas": 4, "melhor": 0})

    def test_blank_cells_are_not_votes(self):
        amostra = self.amostra()[:2]
        linhas, gabarito = piloto.montar_folha(amostra, ("google", {1: "g", 2: "g"}), ("modelo", {1: "m", 2: "m"}))
        resultado = piloto.apurar_folha(linhas, gabarito)
        self.assertEqual(resultado["modelo"]["julgadas"], 0)
        self.assertEqual(resultado["google"]["julgadas"], 0)


class TraduzirComClienteFalsoTests(unittest.TestCase):
    """O fluxo inteiro de `traduzir`, com um cliente que responde sem rede.

    O que se confere e a costura: mascara antes, JSON numerado, validacao por
    id, reenvio do que faltou, pos-processamento e o `usage` somado no resumo.
    A unica coisa que fica de fora e a chamada de rede em si.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta_original = piloto.PASTA
        piloto.PASTA = Path(self.tmp.name)
        self.addCleanup(setattr, piloto, "PASTA", self.pasta_original)
        self.pedidos = []

    class Uso:
        def __init__(self):
            self.input_tokens, self.output_tokens = 100, 40
            self.cache_read_input_tokens, self.cache_creation_input_tokens = 30, 0

    class Bloco:
        type = "text"

        def __init__(self, texto):
            self.text = texto

    def cliente(self, responder):
        teste = self

        class Mensagens:
            def create(self, **kwargs):
                teste.pedidos.append(kwargs)
                pedido = json.loads(kwargs["messages"][0]["content"].split("\n\n")[1])
                itens = responder(pedido["itens"])
                resposta = type("R", (), {})()
                resposta.content = [teste.Bloco(json.dumps({"itens": itens}))]
                resposta.stop_reason = "end_turn"
                resposta.usage = teste.Uso()
                return resposta

        return type("C", (), {"messages": Mensagens()})()

    def amostra(self):
        return [
            {"id": 1, "original": "White plays [%cal Ra1h8] and wins.", "google": "g", "humano": "", "julgada": False,
             "primeira_acao": None, "verificada": False, "estrato": "longo", "lance_anterior": "1.e4", "lance_seguinte": ""},
            {"id": 2, "original": "and Black is fine after", "google": "g", "humano": "", "julgada": False,
             "primeira_acao": None, "verificada": False, "estrato": "preposicao", "lance_anterior": "", "lance_seguinte": "12...Bg7"},
        ]

    def test_a_clean_batch_is_translated_masked_and_post_processed(self):
        def responder(itens):
            return [{"id": i["id"], "traducao": "T " + i["texto"]} for i in itens]

        piloto.traduzir(type("A", (), {"modelo": "claude-opus-5", "lote": 20, "max_lotes": 0})(),
                        client=self.cliente(responder), amostra=self.amostra())

        dados = json.loads((piloto.PASTA / "traducoes-claude-opus-5.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["resumo"]["requisicoes"], 1)
        self.assertEqual(dados["resumo"]["uso_total"]["cache_read_input_tokens"], 30)
        self.assertAlmostEqual(dados["resumo"]["custo_usd"], (100 * 5 + 40 * 25 + 30 * 0.5) / 1e6)
        por_id = {r["id"]: r for r in dados["resultados"]}
        self.assertIn("⟦0⟧", self.pedidos[0]["messages"][0]["content"], "a mascara foi antes")
        self.assertEqual(por_id[1]["final"], "T White plays [%cal Ra1h8] and wins.", "e a restauracao depois")
        self.assertTrue(por_id[1]["sentinela_ok"])
        self.assertEqual(self.pedidos[0]["output_config"]["format"]["type"], "json_schema")
        self.assertTrue(all("cache_control" in bloco for bloco in self.pedidos[0]["system"]))

    def test_a_missing_id_is_resent_alone_and_counted(self):
        chamadas = []

        def responder(itens):
            chamadas.append([i["id"] for i in itens])
            # No lote, o item 2 e engolido; sozinho, volta.
            return [{"id": i["id"], "traducao": "ok"} for i in itens if i["id"] != 2 or len(itens) == 1]

        piloto.traduzir(type("A", (), {"modelo": "claude-opus-5", "lote": 20, "max_lotes": 0})(),
                        client=self.cliente(responder), amostra=self.amostra())

        dados = json.loads((piloto.PASTA / "traducoes-claude-opus-5.json").read_text(encoding="utf-8"))
        self.assertEqual(chamadas, [[1, 2], [2]])
        self.assertEqual(dados["resumo"]["reenvios"], 1)
        self.assertEqual(dados["requisicoes"][0]["problemas"], ["id 2 faltou"])
        self.assertEqual({r["id"] for r in dados["resultados"] if not r.get("falhou")}, {1, 2})

    def test_a_swallowed_sentinel_is_a_failed_item_not_a_kept_text(self):
        def responder(itens):
            return [{"id": i["id"], "traducao": "sem marcador"} for i in itens]

        piloto.traduzir(type("A", (), {"modelo": "claude-opus-5", "lote": 20, "max_lotes": 0})(),
                        client=self.cliente(responder), amostra=self.amostra())
        dados = json.loads((piloto.PASTA / "traducoes-claude-opus-5.json").read_text(encoding="utf-8"))
        por_id = {r["id"]: r for r in dados["resultados"]}
        self.assertFalse(por_id[1]["sentinela_ok"])
        self.assertEqual(por_id[1]["final"], "")
        self.assertEqual(por_id[2]["final"], "sem marcador")


if __name__ == "__main__":
    unittest.main()
