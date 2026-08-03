# -*- coding: utf-8 -*-
"""Gera `recursos/PGN_Tradutor_Pro.ico` — o icone do programa.

Desenhado por codigo, e nao guardado so como binario, por duas razoes: o `.ico`
tem seis tamanhos e refaze-los a mao a cada ajuste e onde um icone envelhece; e
o desenho fica revisavel como o resto do projeto.

**O que a marca diz.** Um peao de xadrez partido ao meio: a metade da esquerda
clara, a da direita escura — as duas cores do tabuleiro, que sao as duas linguas
do programa. Sobre o peito do peao, as duas letras que o programa troca o dia
inteiro: o `N` do cavalo em ingles e o `C` do cavalo em portugues, cada uma do
lado da sua metade. Embaixo, quatro casas de tabuleiro fecham a base.

**Bandeira nao entrou de proposito**, que e a saida obvia para "idiomas": ela
nomeia PAIS, e o programa traduz para sete linguas — a de Portugal e a do Brasil
seriam duas bandeiras para o mesmo `pt`. As letras dizem a mesma coisa sem essa
confusao, e dizem em xadrez.

O desenho foi ajustado tres vezes, sempre olhando uma folha de contato com os
seis tamanhos lado a lado e as ampliacoes de 16 e 32 px. O que cada rodada
mostrou, porque e o que evita refazer a conta no proximo ajuste:

1. **o peao estava pequeno demais no quadro** — desenhado centrado, com folga em
   volta, ele virava um risco em 16 px. Hoje ocupa de 0,04 a 0,87 na vertical;
2. **as letras transbordavam a silhueta.** Em corpo 0,26 no meio do corpo do
   peao elas pousavam no fundo, e o icone parecia ter letras soltas ATRAS da
   peca. Hoje sao 0,165, na altura 0,585, que e onde o corpo e mais largo;
3. **a faixa do tabuleiro flutuava.** A base do peao parava em 0,80 e a faixa
   comecava em 0,87: duas figuras separadas, e nao uma marca. Hoje a base desce
   ate encostar nela.

A regra que ficou: **o que nao sobrevive a 32x32 nao entra** — por isso as
letras so aparecem a partir de 48 px. Cada tamanho e desenhado no proprio
tamanho, e nao reduzido a partir do maior: um `resize` do desenho de 256 px
borra justamente os tracos finos que dao a forma.
"""
import os
import sys

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "PGN_Tradutor_Pro.ico")

# Os tamanhos que o Windows pede: 16 na barra de titulo, 32 na barra de tarefas
# e no Explorer, 48 na visao "icones medios", 256 na "icones extra grandes" e no
# instalador.
TAMANHOS = (16, 24, 32, 48, 64, 256)

CLARO = (241, 245, 249)      # a metade clara do peao
ESCURO = (30, 41, 59)        # a metade escura
CONTORNO = (15, 23, 42)
DESTAQUE = (37, 99, 235)     # o azul dos botoes do programa
LETRA_CLARA = (248, 250, 252)
LETRA_ESCURA = (15, 23, 42)


def _peao(d, s):
    """O peao, em coordenadas relativas ao lado `s` do quadro.

    O peao OCUPA o quadro: da 0,04 a 0,80 na vertical e quase de borda a borda
    na base. A primeira versao o desenhava menor e centrado, com folga em volta,
    e em 16 px a silhueta virava um risco. Icone pequeno nao tem margem a
    perder.
    """
    def p(x, y):
        return (x * s, y * s)

    # Base larga, corpo troncudo e cabeca grande — proporcao de peca de plastico
    # de torneio, e nao de peao estilizado. O que sobrevive a 16 px e a MASSA.
    base = [p(0.08, 0.87), p(0.92, 0.87), p(0.78, 0.66), p(0.22, 0.66)]
    corpo = [p(0.26, 0.66), p(0.74, 0.66), p(0.66, 0.40), p(0.34, 0.40)]
    colar = [p(0.24, 0.40), p(0.76, 0.40), p(0.70, 0.33), p(0.30, 0.33)]
    cabeca = (p(0.30, 0.04), p(0.70, 0.38))

    for forma in (base, corpo, colar):
        d.polygon(forma, fill=CLARO)
    d.ellipse(cabeca, fill=CLARO)


def _meia_sombra(img, s):
    """Escurece a METADE DIREITA do peao. As duas cores do tabuleiro, e as duas
    linguas: e a unica ideia do icone, e ela precisa aparecer inteira em 16 px.
    """
    sombra = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sombra)
    ds.rectangle([(s // 2, 0), (s, s)], fill=ESCURO + (255,))
    recorte = img.split()[3]  # so onde o peao existe
    sombra.putalpha(Image.composite(sombra.split()[3], recorte, recorte))
    img.alpha_composite(Image.composite(sombra, Image.new("RGBA", (s, s)), recorte))


def _casas(d, s):
    """Quatro casas alternadas fechando a base — o tabuleiro, sem desenha-lo.

    Alta o bastante para ser uma FAIXA e nao um risco: em 16 px sao 2 px, que e
    o minimo em que a alternancia das cores ainda se ve.
    """
    altura = max(2, round(s * 0.13))
    topo = s - altura
    largura = s / 4
    for i in range(4):
        cor = ESCURO if i % 2 == 0 else DESTAQUE
        d.rectangle(
            [(round(i * largura), topo), (round((i + 1) * largura) - 1, s - 1)],
            fill=cor,
        )


def _letras(d, s):
    """`N` e `C` — o cavalo em ingles e em portugues, um de cada lado.

    **Abaixo de 48 px elas nao entram.** Medido olhando a folha de contato: em
    32 px as duas viram dois borroes de tres pixels que sujam a silhueta em vez
    de dizer alguma coisa. Nesses tamanhos o icone fica so com o peao bicolor
    sobre a faixa do tabuleiro, que e a leitura que sobrevive. Fingir que se le
    letra em 16 px e o que produz icone sujo.
    """
    if s < 48:
        return
    from PIL import ImageFont

    # 0,165 na altura 0,585 — o ponto em que o corpo do peao e mais largo. A
    # primeira versao usava 0,26 no meio do corpo, e as duas letras
    # transbordavam a silhueta e pousavam no fundo: o icone parecia ter letras
    # soltas ATRAS da peca.
    corpo = round(s * 0.165)
    try:
        fonte = ImageFont.truetype("arialbd.ttf", corpo)
    except OSError:
        fonte = ImageFont.load_default()

    for texto, x, cor in (("N", 0.375, LETRA_ESCURA), ("C", 0.625, LETRA_CLARA)):
        caixa = d.textbbox((0, 0), texto, font=fonte)
        largura = caixa[2] - caixa[0]
        altura = caixa[3] - caixa[1]
        d.text(
            (x * s - largura / 2 - caixa[0], 0.585 * s - altura / 2 - caixa[1]),
            texto,
            font=fonte,
            fill=cor,
        )


def desenhar(s):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _peao(d, s)
    _meia_sombra(img, s)
    d = ImageDraw.Draw(img)
    _casas(d, s)
    _letras(d, s)
    return img


def main():
    quadros = [desenhar(s) for s in TAMANHOS]
    # `append_images` guarda cada tamanho como foi DESENHADO. Gravar so o de 256
    # e deixar o Pillow reduzir daria o borrao que este modulo existe para
    # evitar.
    quadros[-1].save(
        DESTINO,
        format="ICO",
        sizes=[(s, s) for s in TAMANHOS],
        append_images=quadros[:-1],
    )
    print(f"gravado: {DESTINO} ({os.path.getsize(DESTINO)} bytes)")
    print("tamanhos:", ", ".join(f"{s}x{s}" for s in TAMANHOS))

    # Um PNG de 256 para o README e para quem quiser olhar o desenho sem abrir
    # um `.ico`.
    png = os.path.join(AQUI, "PGN_Tradutor_Pro.png")
    quadros[-1].save(png, format="PNG")
    print(f"gravado: {png} ({os.path.getsize(png)} bytes)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
