"""O quadro do tabuleiro do editor (ROADMAP 28.8, garantia O5).

Um `tk.Canvas` de 8 x 8 casas de 24 px com glifos Unicode das pecas: 192 px
de lado, que cabem nos 308 px do painel de sugestoes com folga. Nao precisa
do `python-chess` — le a FEN gravada no banco (`pgn_positions.fen_board_rows`),
entao um `.exe` sem o pacote desenha as posicoes que um banco vindo do fonte
ja tem.

Tk puro, e por isso pinta as cores por tema a mao: o editor o repinta na
mesma chamada em que repinta os campos de texto (`apply_theme_colors`, F18).
"""

import tkinter as tk

from .pgn_positions import PIECE_GLYPHS, fen_board_rows, side_to_move

SQUARE = 24
BOARD_SIDE = SQUARE * 8

# (claro, escuro) como as cores do `editor_common`: casas claras e escuras do
# tabuleiro, e a cor das pecas — os glifos brancos e pretos do Unicode ja se
# distinguem pelo desenho, entao a peca usa UMA cor de tinta por tema, legivel
# nas duas casas.
LIGHT_SQUARE = ("#f0d9b5", "#8b7355")
DARK_SQUARE = ("#b58863", "#4a3b2a")
PIECE_INK = ("#111111", "#f5f5f5")
BORDER = ("#94a3b8", "#475569")


def theme_index(mode):
    return 1 if (mode or "").lower() == "dark" else 0


class BoardCanvas(tk.Canvas):
    """Desenha uma FEN. `set_fen(None)` limpa; `apply_theme(modo)` repinta."""

    def __init__(self, parent, mode="Light", square=SQUARE, **kwargs):
        lado = square * 8
        super().__init__(
            parent,
            width=lado,
            height=lado,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        self.square = square
        self.fen = None
        self.mode = mode
        self.font = ("Segoe UI Symbol", int(square * 0.72))
        self.apply_theme(mode)

    def apply_theme(self, mode):
        self.mode = mode
        indice = theme_index(mode)
        self.configure(
            bg=LIGHT_SQUARE[indice], highlightbackground=BORDER[indice],
            highlightcolor=BORDER[indice],
        )
        self.redraw()

    def set_fen(self, fen):
        self.fen = fen
        self.redraw()

    def redraw(self):
        self.delete("all")
        linhas = fen_board_rows(self.fen)
        if linhas is None:
            return
        indice = theme_index(self.mode)
        casa = self.square
        for fileira, casas in enumerate(linhas):
            for coluna, peca in enumerate(casas):
                x0, y0 = coluna * casa, fileira * casa
                cor = LIGHT_SQUARE if (fileira + coluna) % 2 == 0 else DARK_SQUARE
                self.create_rectangle(
                    x0, y0, x0 + casa, y0 + casa, fill=cor[indice], outline=""
                )
                if peca:
                    self.create_text(
                        x0 + casa / 2,
                        y0 + casa / 2 + 1,
                        text=PIECE_GLYPHS[peca],
                        font=self.font,
                        fill=PIECE_INK[indice],
                    )

    def describe(self):
        """"Brancas jogam" / "Pretas jogam" da FEN atual, para o rotulo ao lado."""
        return side_to_move(self.fen)
