import csv
from contextlib import closing
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .app_config import LANGUAGE_NAMES, LANGUAGES, UNKNOWN_SOURCE_LABEL, language_label
from .database import (
    SEARCH_MODE_SUBSTRING,
    SEARCH_MODE_TERMS,
    SOURCE_LANGUAGE_UNKNOWN,
    count_from_status_counts,
    count_review_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_translation_by_id,
    get_review_row_offset,
    get_review_status_counts,
    initialize_database,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from .db_tools import apply_automatic_rules_to_database
from .editor_text import find_text_ranges, replace_all_text
from .glossario import (
    add_to_glossary,
    apply_automatic_substitutions,
    case_adjusted_replacement,
    delete_glossary_entry_by_pair,
    find_glossary_matches,
    find_glossary_suggestions,
    load_automatic_substitutions,
    load_interactive_substitutions,
)
from .editor_common import (
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    clamp_page,
    format_timestamp,
    local_index_for_offset,
    page_count as compute_page_count,
    page_offset,
    page_of_offset,
    preview,
    row_index_for_id,
    window_safe_geometry,
)
from .editor_widgets import (
    flash_message,
    render_row_buttons,
    restore_sash,
    save_window_section,
)
from .glossary_editor import open_glossary_editor
from .history_window import HistoryWindow
from .review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    find_first_quality_warning,
    row_has_quality_warning,
)
from .settings import (
    clear_editor_draft,
    get_editor_draft,
    load_settings,
    set_editor_draft,
    update_settings,
)
from .window_utils import bring_window_to_front


ROW_COLOR = ("#f8fafc", "#1f2937")
VERIFIED_ROW_COLOR = ("#d1fae5", "#14532d")
VERIFIED_ROW_TEXT_COLOR = ("#065f46", "#d1fae5")
SUGGESTION_COLOR = ("#f8fafc", "#1f2937")
SUGGESTION_TEXT_COLOR = ("#111827", "#e5e7eb")
SUGGESTION_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
PAGE_SIZE = 100
SEARCH_MODE_LABEL_TERMS = "Termos"
SEARCH_MODE_LABEL_SUBSTRING = "Trecho"
MIN_WIDTH = 1120
MIN_HEIGHT = 680

# Rotulo do filtro de origem que nao filtra nada. Precisa ser diferente de
# `UNKNOWN_SOURCE_LABEL`: "Todos" traz a tabela inteira, "Não informado" traz so
# as linhas cuja origem ninguem declarou. Confundir os dois foi exatamente o que
# esta janela passou a existir para evitar.
SOURCE_FILTER_ALL = "Todos"


def source_filter_labels():
    return [SOURCE_FILTER_ALL, UNKNOWN_SOURCE_LABEL] + [nome for nome, _ in LANGUAGES]


def target_language_labels():
    return [nome for nome, _ in LANGUAGES]


def source_filter_code(label):
    """O que o rotulo do seletor de origem significa para o banco.

    Tres respostas diferentes, e o `None` e a que nao pode ser confundida com as
    outras duas: `None` nao filtra, `""` filtra pelas linhas sem origem
    declarada, e um codigo filtra por aquele idioma. Devolver `""` para "Todos"
    esconderia a tabela inteira menos as legadas.
    """
    if label == SOURCE_FILTER_ALL:
        return None
    if label == UNKNOWN_SOURCE_LABEL:
        return SOURCE_LANGUAGE_UNKNOWN
    for nome, codigo in LANGUAGES:
        if nome == label:
            return codigo
    return None


def target_language_code(label):
    for nome, codigo in LANGUAGES:
        if nome == label:
            return codigo
    return None


def safe_geometry(win, geometry):
    return window_safe_geometry(win, geometry, MIN_WIDTH, MIN_HEIGHT)


def row_label(row):
    status = "OK" if len(row) > 3 and row[3] == 1 else "PEND"
    return (
        f"{status}  #{row[0]}\n"
        f"O: {preview(row[1], 54)}\n"
        f"T: {preview(row[2], 54)}"
    )


def row_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_COLOR
    return ROW_COLOR


def row_text_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_TEXT_COLOR
    return ROW_TEXT_COLOR


class EditorState:
    """Estado mutavel da janela de edicao, em atributos.

    Antes cada um destes campos era um dict de um item so, lido e escrito pelo
    indice: `page_index = {...}` e depois `page_index[...]` em toda parte.
    Isso nao era estilo: as dezenas de funcoes aninhadas de
    `open_translation_editor` precisam ESCREVER no estado compartilhado, e uma
    atribuicao simples dentro de uma funcao aninhada cria uma variavel local em
    vez de alterar a de fora. O dict contornava isso porque mutar um objeto nao
    e atribuir a um nome.

    Um objeto com atributos resolve o mesmo problema sem o ruido do
    `["value"]`, e — o que importa mais — deixa o estado da janela declarado num
    lugar so, em vez de espalhado por onze linhas soltas no meio da construcao
    da interface. E o primeiro passo para a janela virar uma classe (item 3.1
    do ROADMAP): quando as funcoes aninhadas virarem metodos, este estado ja
    esta reunido.
    """

    def __init__(self, font_size=12):
        # Paginacao e contagens da lista.
        self.rows = []
        self.total_rows = 0
        self.page_index = 0
        self.status_counts = {"total": 0, "pending": 0, "verified": 0, "qa": 0}
        self.active_search = ""

        # Selecao.
        self.selected_index = None
        self.selected_suggestion = None

        # Edicao em andamento. `loading` suprime o marcador de "nao salvo"
        # enquanto o proprio programa preenche os campos.
        self.dirty = False
        self.loading = False
        self.draft_save_after = None

        # Aparencia e busca dentro do texto.
        self.font_size = font_size
        self.bold_view = False
        self.current_find_match = None


class TranslationEditor:
    """A janela de edicao de traducoes.

    Era uma funcao de 2.2 mil linhas com 86 funcoes aninhadas, todas presas ao
    mesmo escopo de closure: mudar qualquer coisa exigia ler o arquivo inteiro
    para saber o que estava no escopo, e escrever no estado compartilhado so
    funcionava por meio de dicts de um item so. Os nomes agora sao atributos e as
    funcoes sao metodos (ROADMAP 3.1).

    A conversao nao mudou comportamento nenhum: cada funcao virou metodo com o
    mesmo corpo. O estado ja tinha sido reunido em `EditorState` na etapa 1, que
    e o que tornou este passo viavel.
    """

    def __init__(self, app):
        self.app = app
        self.build_state()
        self.build_list_pane()
        self.build_editor_pane()
        self.build_suggestion_pane()
        self.build_status_bar()
        self.connect_events()
        self.load_first_page()

    def build_state(self):
        """Estado da janela, variaveis de controle e fontes."""
        # O destino comeca no que a janela principal tem selecionado — que e o
        # que esta janela sempre fez — mas deixa de estar preso a ele: o seletor
        # abaixo permite trocar sem fechar o editor.
        self.lang = self.app.target_language.get()

        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title(f"Editar traduções ({self.lang})")
        self.win.geometry("1280x760")
        self.win.minsize(1120, 680)
        bring_window_to_front(self.win, self.app.root, maximize=True)

        self.settings = load_settings()
        self.editor_settings = self.settings.get("editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

        saved_geometry = self.editor_settings.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            try:
                self.win.geometry(safe_geometry(self.win, saved_geometry))
            except tk.TclError:
                pass

        self.row_buttons = []
        saved_font_size = self.editor_settings.get("font_size", 12)
        if not isinstance(saved_font_size, int):
            saved_font_size = 12
        self.state = EditorState(font_size=max(9, min(24, saved_font_size)))
        self.current = {
            "id": None,
            "orig": "",
            "trans": "",
            "saved_trans": "",
            "created_at": "",
            "updated_at": "",
            "verified_at": "",
            "source_language": "",
            # True quando o texto exibido difere do banco apenas por causa das regras
            # automaticas, sem o usuario ter digitado nada. Nesse estado a gravacao
            # silenciosa (a que acontece ao navegar) e suprimida: so uma acao
            # deliberada altera o banco (garantia R1 da SPEC.md).
            "auto_only": False,
        }
        self.glossary = self.app.glossary_substitutions
        self.automatic_glossary = load_automatic_substitutions()
        self.current_suggestions = []
        self.suggestion_buttons = []
        self.search_text = tk.StringVar(master=self.win, value="")
        self.editor_find_text = tk.StringVar(master=self.win, value="")
        self.editor_replace_text = tk.StringVar(master=self.win, value="")
        self.editor_case_sensitive = tk.BooleanVar(master=self.win, value=False)
        self.go_page_text = tk.StringVar(master=self.win, value="")
        self.go_id_text = tk.StringVar(master=self.win, value="")
        self.body_font = tkfont.Font(family="Segoe UI", size=self.state.font_size)
        self.body_bold_font = tkfont.Font(family="Segoe UI", size=self.state.font_size, weight="bold")
        self.row_font = ctk.CTkFont(family="Segoe UI", size=11)
        self.suggestion_font = ctk.CTkFont(size=11)

        if not hasattr(self.app, "glossary_change_callbacks"):
            self.app.glossary_change_callbacks = []

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)


    def build_list_pane(self):
        """Painel esquerdo: paginacao, busca, filtros e a lista."""
        self.pane_bg = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
        self.main_pane = tk.PanedWindow(
            self.win,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        self.list_frame = ctk.CTkFrame(self.main_pane, corner_radius=8, width=400)
        self.main_pane.add(self.list_frame, minsize=320)
        self.list_frame.columnconfigure(0, weight=1)
        self.list_frame.rowconfigure(6, weight=1)

        self.header = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        self.header.columnconfigure(1, weight=1)
        ctk.CTkLabel(self.header, text="Traduções", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.page_label = ctk.CTkLabel(self.header, text="", anchor="e")
        self.page_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.page_nav = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.page_nav.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.page_nav.columnconfigure(1, weight=1)
        self.btn_page_prev = ctk.CTkButton(self.page_nav, text="< Página", width=92)
        self.btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.btn_page_next = ctk.CTkButton(self.page_nav, text="Página >", width=92)
        self.btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

        self.search_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.search_bar.columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(
            self.search_bar,
            textvariable=self.search_text,
            placeholder_text="Buscar no original ou tradução",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_search = ctk.CTkButton(self.search_bar, text="Buscar", width=82)
        self.btn_search.grid(row=0, column=1, padx=(0, 6))
        self.btn_clear_search = ctk.CTkButton(self.search_bar, text="Limpar", width=74)
        self.btn_clear_search.grid(row=0, column=2)

        # As duas buscas nao sao a mesma coisa e nenhuma serve para tudo, entao a
        # escolha e do usuario e fica a vista (garantia R8):
        #   Termos  — indexado, custa o tamanho da pagina, casa palavra inteira
        #   Trecho  — varre a tabela, mas acha qualquer pedaco literal
        self.search_mode_segment = ctk.CTkSegmentedButton(
            self.search_bar,
            values=[SEARCH_MODE_LABEL_TERMS, SEARCH_MODE_LABEL_SUBSTRING],
        )
        saved_mode = self.editor_settings.get("search_mode", SEARCH_MODE_LABEL_TERMS)
        if saved_mode not in {SEARCH_MODE_LABEL_TERMS, SEARCH_MODE_LABEL_SUBSTRING}:
            saved_mode = SEARCH_MODE_LABEL_TERMS
        self.search_mode_segment.set(saved_mode)
        self.search_mode_segment.grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0)
        )

        self.jump_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.jump_bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.jump_bar.columnconfigure(1, weight=1)
        self.jump_bar.columnconfigure(4, weight=1)
        ctk.CTkLabel(self.jump_bar, text="Página").grid(row=0, column=0, sticky="w")
        self.page_entry = ctk.CTkEntry(self.jump_bar, textvariable=self.go_page_text, width=64)
        self.page_entry.grid(row=0, column=1, sticky="ew", padx=(6, 4))
        self.btn_go_page = ctk.CTkButton(self.jump_bar, text="Ir", width=46)
        self.btn_go_page.grid(row=0, column=2, padx=(0, 10))
        ctk.CTkLabel(self.jump_bar, text="ID").grid(row=0, column=3, sticky="w")
        self.id_entry = ctk.CTkEntry(self.jump_bar, textvariable=self.go_id_text, width=82)
        self.id_entry.grid(row=0, column=4, sticky="ew", padx=(6, 4))
        self.btn_go_id = ctk.CTkButton(self.jump_bar, text="Ir", width=46)
        self.btn_go_id.grid(row=0, column=5)

        self.status_segment = ctk.CTkSegmentedButton(
            self.list_frame,
            values=["Todas", "Pendentes", "Verificadas", "Avisos QA"],
        )
        saved_status = self.editor_settings.get("status_filter", "Todas")
        if saved_status not in {"Todas", "Pendentes", "Verificadas", "Avisos QA"}:
            saved_status = "Todas"
        self.status_segment.set(saved_status)
        self.status_segment.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.build_language_bar()

        self.rows_frame = ctk.CTkScrollableFrame(self.list_frame, height=420)
        self.rows_frame.grid(row=6, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def build_language_bar(self):
        """Os dois seletores de idioma, acima da lista.

        Ficam junto dos outros filtros, e nao numa barra propria no topo da
        janela, porque e isso que eles sao: filtram a mesma lista que o status e
        a busca filtram, e a lista e o que muda quando qualquer um dos tres muda.

        **Sao menus, e nao botoes segmentados como o status.** Oito idiomas em
        botoes lado a lado nao cabem na largura do painel, e a forma segmentada so
        se paga quando todas as opcoes ficam visiveis de uma vez.

        A ORIGEM e o filtro que este item existe para dar (ver ROADMAP), e por
        isso ela e a primeira e a unica com a opcao "Todos": o destino nunca e
        "todos", porque a janela edita as traducoes de um idioma so — o rascunho,
        o titulo e a aplicacao das regras automaticas sao todos por idioma de
        destino.
        """
        self.language_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.language_bar.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.language_bar.columnconfigure(1, weight=1)
        self.language_bar.columnconfigure(3, weight=1)

        ctk.CTkLabel(self.language_bar, text="Origem").grid(row=0, column=0, sticky="w")
        self.source_menu = ctk.CTkOptionMenu(
            self.language_bar,
            values=source_filter_labels(),
            command=lambda _value: self.change_language_filter(),
        )
        saved_source = self.editor_settings.get("source_filter", SOURCE_FILTER_ALL)
        if saved_source not in source_filter_labels():
            saved_source = SOURCE_FILTER_ALL
        self.source_menu.set(saved_source)
        self.source_menu.grid(row=0, column=1, sticky="ew", padx=(6, 10))

        ctk.CTkLabel(self.language_bar, text="Destino").grid(row=0, column=2, sticky="w")
        self.target_menu = ctk.CTkOptionMenu(
            self.language_bar,
            values=target_language_labels(),
            command=lambda _value: self.change_language_filter(),
        )
        # Um idioma que nao esteja na lista (um banco antigo com um codigo que o
        # programa nao oferece mais) cai no primeiro em vez de deixar o menu em
        # branco — e o `change_language_filter` que roda depois grava a troca.
        self.target_menu.set(LANGUAGE_NAMES.get(self.lang, LANGUAGES[0][0]))
        self.target_menu.grid(row=0, column=3, sticky="ew", padx=(6, 0))


    def build_editor_pane(self):
        """Painel central: original, traducao e busca no texto."""
        self.bottom_pane = tk.PanedWindow(
            self.main_pane,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.add(self.bottom_pane, minsize=620)

        self.text_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.text_frame, minsize=520)
        self.text_frame.columnconfigure(0, weight=1)
        self.text_frame.rowconfigure(1, weight=1, minsize=120)
        self.text_frame.rowconfigure(3, weight=3, minsize=180)

        self.text_bg = "#111827" if ctk.get_appearance_mode() == "Dark" else "#f9fafb"
        self.text_fg = "#e5e7eb" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.text_border = "#374151" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
        self.highlight_bg = "#7c5800" if ctk.get_appearance_mode() == "Dark" else "#fff3bf"
        self.highlight_fg = "#fef3c7" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.find_bg = "#334155" if ctk.get_appearance_mode() == "Dark" else "#fde68a"
        self.find_fg = "#f8fafc" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.current_find_bg = "#ea580c" if ctk.get_appearance_mode() == "Dark" else "#fb923c"

        ctk.CTkLabel(self.text_frame, text="Original:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2)
        )
        self.orig_text = self.create_text_editor(self.text_frame, 1, readonly=True)
        self.translation_header = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        self.translation_header.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
        ctk.CTkLabel(self.translation_header, text="Tradução:").pack(side=tk.LEFT)
        self.font_controls = ctk.CTkFrame(self.translation_header, fg_color="transparent")
        self.font_controls.pack(side=tk.RIGHT)
        self.btn_font_down = ctk.CTkButton(self.font_controls, text="A-", width=42)
        self.btn_font_down.pack(side=tk.LEFT, padx=(0, 4))
        self.font_label = ctk.CTkLabel(self.font_controls, text=f"{self.state.font_size} pt", width=46)
        self.font_label.pack(side=tk.LEFT)
        self.btn_font_up = ctk.CTkButton(self.font_controls, text="A+", width=42)
        self.btn_font_up.pack(side=tk.LEFT, padx=4)
        self.btn_bold = ctk.CTkButton(
            self.font_controls,
            text="B",
            width=42,
            font=ctk.CTkFont(weight="bold"),
        )
        self.btn_bold.pack(side=tk.LEFT, padx=(4, 0))
        self.trans_text = self.create_text_editor(self.text_frame, 3, bottom_pad=4)

        self.find_bar = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        self.find_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.find_bar.columnconfigure(0, weight=1)
        self.find_bar.columnconfigure(1, weight=1)

        self.editor_find_entry = ctk.CTkEntry(
            self.find_bar,
            textvariable=self.editor_find_text,
            placeholder_text="Buscar",
            width=120,
        )
        self.editor_find_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.editor_replace_entry = ctk.CTkEntry(
            self.find_bar,
            textvariable=self.editor_replace_text,
            placeholder_text="Substituir",
            width=120,
        )
        self.editor_replace_entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.find_buttons = ctk.CTkFrame(self.find_bar, fg_color="transparent")
        self.find_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.btn_find_next = ctk.CTkButton(self.find_buttons, text="Prox.", width=58)
        self.btn_find_next.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_replace_current = ctk.CTkButton(self.find_buttons, text="Trocar", width=68)
        self.btn_replace_current.pack(side=tk.LEFT, padx=4)
        self.btn_replace_all = ctk.CTkButton(self.find_buttons, text="Todos", width=62)
        self.btn_replace_all.pack(side=tk.LEFT, padx=4)
        self.case_check = ctk.CTkCheckBox(
            self.find_buttons,
            text="Aa",
            variable=self.editor_case_sensitive,
            width=46,
        )
        self.case_check.pack(side=tk.LEFT, padx=(4, 0))

        self.qa_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color="#16a34a",
        )
        self.qa_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 2))
        self.history_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
        )
        self.history_label.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))


    def create_text_editor(self, parent, row, readonly=False, bottom_pad=8):
        container = tk.Frame(
            parent,
            bg=self.text_border,
            highlightthickness=1,
            highlightbackground=self.text_border,
        )
        container.grid(row=row, column=0, sticky="nsew", padx=10, pady=(0, bottom_pad))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        text = tk.Text(
            container,
            wrap=tk.WORD,
            undo=not readonly,
            relief=tk.FLAT,
            borderwidth=0,
            font=self.body_font,
            bg=self.text_bg,
            fg=self.text_fg,
            insertbackground=self.text_fg,
            selectbackground="#2563eb",
            selectforeground="#ffffff",
            padx=8,
            pady=6,
            height=6 if readonly else 12,
        )
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.tag_configure("bold", font=self.body_bold_font)
        text.tag_configure(
            "glossary_hit",
            background=self.highlight_bg,
            foreground=self.highlight_fg,
            font=self.body_bold_font,
        )
        text.tag_configure(
            "find_match",
            background=self.find_bg,
            foreground=self.find_fg,
        )
        text.tag_configure(
            "find_current",
            background=self.current_find_bg,
            foreground="#ffffff",
        )
        if readonly:
            text.configure(state=tk.DISABLED)
        return text


    def build_suggestion_pane(self):
        """Painel direito: sugestoes do glossario."""
        self.sugg_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.sugg_frame, minsize=300)
        self.sugg_frame.columnconfigure(0, weight=1)
        self.sugg_frame.columnconfigure(1, weight=1)
        self.sugg_frame.rowconfigure(1, weight=1)

        ctk.CTkLabel(self.sugg_frame, text="Sugestões do glossário:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )

        self.suggestions_frame = ctk.CTkScrollableFrame(self.sugg_frame, height=160)
        self.suggestions_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            padx=10,
            pady=(0, 8),
        )

        self.btn_refresh = ctk.CTkButton(self.sugg_frame, text="Recarregar sugestões")
        self.btn_apply_one = ctk.CTkButton(self.sugg_frame, text="Aplicar selecionada")
        self.btn_apply_all = ctk.CTkButton(self.sugg_frame, text="Aplicar todas")
        self.btn_add_gloss = ctk.CTkButton(self.sugg_frame, text="Adicionar ao glossário")
        self.btn_reload_gloss = ctk.CTkButton(self.sugg_frame, text="Atualizar glossário")
        self.btn_open_gloss = ctk.CTkButton(self.sugg_frame, text="Editar glossário")

        self.btn_refresh.grid(row=2, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.btn_apply_one.grid(row=2, column=1, sticky="ew", padx=(4, 10), pady=4)
        self.btn_apply_all.grid(row=3, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.btn_add_gloss.grid(row=3, column=1, sticky="ew", padx=(4, 10), pady=4)
        self.btn_reload_gloss.grid(row=4, column=0, sticky="ew", padx=(10, 4), pady=(0, 10))
        self.btn_open_gloss.grid(row=4, column=1, sticky="ew", padx=(4, 10), pady=(0, 10))


    def build_status_bar(self):
        """Rodape: mensagens, contagens e os botoes de acao."""
        self.status_frame = ctk.CTkFrame(self.win, corner_radius=8)
        self.status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.status_frame.columnconfigure(0, weight=1)

        self.status_info = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.status_info.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

        self.msg_label = ctk.CTkLabel(self.status_info, text="", text_color="#16a34a")
        self.msg_label.pack(side=tk.LEFT)

        self.dirty_label = ctk.CTkLabel(self.status_info, text="Salvo", text_color="#16a34a")
        self.dirty_label.pack(side=tk.LEFT, padx=(12, 0))

        self.draft_label = ctk.CTkLabel(self.status_info, text="", text_color="#64748b")
        self.draft_label.pack(side=tk.LEFT, padx=(12, 0))

        self.selection_label = ctk.CTkLabel(self.status_info, text="Item 0/0")
        self.selection_label.pack(side=tk.LEFT, padx=(12, 0))

        self.counts_label = ctk.CTkLabel(
            self.status_info,
            text="Todas: 0 · Pendentes: 0 · Verificadas: 0 · QA: 0",
        )
        self.counts_label.pack(side=tk.LEFT, padx=(12, 0))

        self.primary_actions = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.primary_actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 4))
        self.secondary_actions = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.secondary_actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.btn_save_verify = ctk.CTkButton(
            self.primary_actions,
            text="Salvar e verificar",
            width=150,
        )
        self.btn_save_plain = ctk.CTkButton(self.primary_actions, text="Salvar", width=90)
        self.btn_mark = ctk.CTkButton(
            self.primary_actions,
            text="Marcar como verificada",
            width=170,
        )
        self.btn_pending = ctk.CTkButton(
            self.primary_actions,
            text="Marcar como pendente",
            width=165,
        )
        self.btn_prev = ctk.CTkButton(self.primary_actions, text="< Anterior", width=110)
        self.btn_next = ctk.CTkButton(self.primary_actions, text="Próxima >", width=110)

        for index, button in enumerate(
            [
                self.btn_save_verify,
                self.btn_save_plain,
                self.btn_mark,
                self.btn_pending,
                self.btn_prev,
                self.btn_next,
            ]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
            self.primary_actions.columnconfigure(index, weight=1)

        self.btn_copy_original = ctk.CTkButton(
            self.secondary_actions,
            text="Copiar original",
            width=120,
        )
        self.btn_restore = ctk.CTkButton(self.secondary_actions, text="Restaurar", width=90)
        self.btn_undo = ctk.CTkButton(self.secondary_actions, text="Desfazer", width=86)
        self.btn_redo = ctk.CTkButton(self.secondary_actions, text="Refazer", width=78)
        self.btn_next_qa = ctk.CTkButton(
            self.secondary_actions,
            text="Próximo aviso QA",
            width=150,
        )
        self.btn_export_qa = ctk.CTkButton(self.secondary_actions, text="Exportar QA", width=110)
        self.btn_apply_auto = ctk.CTkButton(
            self.secondary_actions,
            text="Aplicar automaticas",
            width=150,
        )
        self.btn_history = ctk.CTkButton(self.secondary_actions, text="Hist\u00f3rico", width=100)

        for index, button in enumerate(
            [
                self.btn_copy_original,
                self.btn_restore,
                self.btn_undo,
                self.btn_redo,
                self.btn_next_qa,
                self.btn_export_qa,
                self.btn_apply_auto,
                self.btn_history,
            ]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
            self.secondary_actions.columnconfigure(index, weight=1)


    def connect_events(self):
        """Liga cada botao, atalho e evento ao metodo correspondente."""
        self.btn_copy_original.configure(command=self.copy_original_to_translation)
        self.btn_restore.configure(command=self.restore_saved_translation)
        self.btn_undo.configure(command=self.undo_translation)
        self.btn_redo.configure(command=self.redo_translation)
        self.btn_save_plain.configure(command=lambda: self.save_changes(False))
        self.btn_save_verify.configure(command=lambda: self.save_changes(False, mark_verified=True))
        self.btn_font_down.configure(command=lambda: self.adjust_font(-1))
        self.btn_font_up.configure(command=lambda: self.adjust_font(1))
        self.btn_bold.configure(command=self.toggle_bold_view)
        self.btn_search.configure(command=self.apply_search)
        self.btn_clear_search.configure(command=self.clear_search)
        self.btn_go_page.configure(command=self.go_to_page)
        self.btn_go_id.configure(command=self.go_to_id)
        self.btn_page_prev.configure(command=lambda: self.change_page(-1))
        self.btn_page_next.configure(command=lambda: self.change_page(1))
        self.btn_prev.configure(command=lambda: self.navigate(-1))
        self.btn_next.configure(command=lambda: self.navigate(1))
        self.btn_mark.configure(command=self.mark_and_next)
        self.btn_pending.configure(command=self.mark_pending)
        self.btn_next_qa.configure(command=self.go_to_next_quality_warning)
        self.btn_export_qa.configure(command=self.export_quality_report)
        self.btn_apply_auto.configure(command=self.apply_automatic_rules_for_current_language)
        self.btn_history.configure(command=self.open_history_window)
        self.status_segment.configure(command=lambda _value: self.toggle_filter())
        # Trocar o modo refaz a busca na hora: deixar o resultado antigo na tela
        # com o seletor novo faria a lista mentir sobre o que esta mostrando.
        self.search_mode_segment.configure(command=lambda _value: self.apply_search())
        self.btn_refresh.configure(command=self.refresh_suggestions)
        self.btn_apply_one.configure(command=self.apply_one)
        self.btn_apply_all.configure(command=self.apply_all)
        self.btn_add_gloss.configure(command=self.add_gloss_popup)
        self.btn_reload_gloss.configure(command=self.reload_glossary)
        self.btn_open_gloss.configure(command=self.open_integrated_glossary_editor)
        self.btn_find_next.configure(command=self.find_next_in_translation)
        self.btn_replace_current.configure(command=self.replace_current_in_translation)
        self.btn_replace_all.configure(command=self.replace_all_in_translation)
        self.editor_find_text.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        self.editor_case_sensitive.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        self.search_entry.bind("<Return>", lambda _event: self.apply_search())
        self.editor_find_entry.bind("<Return>", self.find_next_in_translation)
        self.editor_replace_entry.bind("<Return>", self.replace_current_in_translation)
        self.page_entry.bind("<Return>", lambda _event: self.go_to_page())
        self.id_entry.bind("<Return>", lambda _event: self.go_to_id())
        self.trans_text.bind("<<Modified>>", self.on_translation_modified)
        self.trans_text.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.trans_text.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.trans_text.bind("<Control-b>", self.toggle_bold_selection)
        self.trans_text.bind("<Control-B>", self.toggle_bold_selection)
        self.win.bind("<Control-f>", self.focus_search)
        self.win.bind("<Control-F>", self.focus_search)
        self.win.bind("<Control-h>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-H>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-s>", self.save_shortcut)
        self.win.bind("<Control-S>", self.save_shortcut)
        self.win.bind("<Control-Return>", self.verify_shortcut)
        self.win.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Alt-Left>", self.previous_shortcut)
        self.win.bind("<Alt-Right>", self.next_shortcut)
        self.win.bind("<F3>", self.find_next_in_translation)
        self.win.bind("<F7>", self.next_quality_warning_shortcut)
        self.win.bind(
            "<Destroy>",
            lambda event: self.unregister_glossary_callback() if event.widget is self.win else None,
        )
        self.win.protocol("WM_DELETE_WINDOW", self.close_editor)


        self.app.glossary_change_callbacks.append(self.on_glossary_editor_change)

    def load_first_page(self):
        """Carrega a primeira pagina e seleciona o primeiro item."""
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

        self.win.after(100, self.restore_pane_positions)

    def show_message(self, text):
        flash_message(self.msg_label, self.win, text)

    def save_editor_settings(self):
        save_window_section(
            self.settings,
            "editor",
            {
                "font_size": self.state.font_size,
                "status_filter": self.status_segment.get(),
                "search_mode": self.search_mode_segment.get(),
                # So a ORIGEM e lembrada. O destino volta a cada abertura para o
                # que a janela principal tem selecionado, que e o comportamento
                # que esta janela sempre teve: lembra-lo faria quem marcasse
                # "Inglês" na janela principal abrir o editor em portugues, sem
                # nada na tela explicando de onde veio aquilo.
                "source_filter": self.source_menu.get(),
            },
            window=self.win,
            sashes=(
                ("main_sash_y", self.main_pane, 0),
                ("bottom_sash_x", self.bottom_pane, 0),
            ),
        )

    def restore_pane_positions(self):
        restore_sash(
            self.main_pane, self.editor_settings.get("main_sash_y"), 360, 520
        )
        restore_sash(
            self.bottom_pane, self.editor_settings.get("bottom_sash_x"), 520
        )

    def cancel_draft_save(self):
        if self.state.draft_save_after is None:
            return
        try:
            self.win.after_cancel(self.state.draft_save_after)
        except tk.TclError:
            pass
        self.state.draft_save_after = None

    def draft_text(self):
        return self.trans_text.get("1.0", tk.END).rstrip("\n")

    def clear_current_draft(self, persist=True):
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        comment_id = self.current["id"]
        # Mantem o snapshot local coerente...
        clear_editor_draft(self.settings, self.app.output_db, self.lang, comment_id)

        if persist:
            # ...e limpa o rascunho relendo o disco, para nao apagar o que a
            # outra janela gravou (garantia R4 da SPEC.md).
            try:
                update_settings(
                    lambda disk: clear_editor_draft(
                        disk, self.app.output_db, self.lang, comment_id
                    )
                )
            except OSError:
                self.draft_label.configure(
                    text="Falha ao limpar rascunho",
                    text_color="#dc2626",
                )
                return
        self.draft_label.configure(text="", text_color="#64748b")

    def persist_current_draft(self):
        self.state.draft_save_after = None
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        comment_id = self.current["id"]
        text = self.draft_text()
        base = self.current["saved_trans"]

        try:
            if text == base:
                self.clear_current_draft(persist=True)
                return

            set_editor_draft(self.settings, self.app.output_db, self.lang, comment_id, text, base)
            update_settings(
                lambda disk: set_editor_draft(
                    disk, self.app.output_db, self.lang, comment_id, text, base
                )
            )
            self.draft_label.configure(
                text=f"Rascunho salvo {datetime.now().strftime('%H:%M:%S')}",
                text_color="#64748b",
            )
        except OSError:
            self.draft_label.configure(
                text="Falha ao salvar rascunho",
                text_color="#dc2626",
            )

    def schedule_draft_save(self):
        if self.state.loading or not self.current["id"]:
            return
        self.cancel_draft_save()
        self.draft_label.configure(text="Salvando rascunho...", text_color="#64748b")
        self.state.draft_save_after = self.win.after(700, self.persist_current_draft)

    def set_dirty(self, value, autosave_draft=True):
        self.state.dirty = value
        if value:
            self.dirty_label.configure(text="Alterações não salvas", text_color="#f59e0b")
            if autosave_draft:
                self.schedule_draft_save()
        else:
            self.cancel_draft_save()
            self.dirty_label.configure(text="Salvo", text_color="#16a34a")

    def update_counts_label(self):
        self.counts_label.configure(
            text=(
                f"Todas: {self.state.status_counts['total']} · "
                f"Pendentes: {self.state.status_counts['pending']} · "
                f"Verificadas: {self.state.status_counts['verified']} · "
                f"QA: {self.state.status_counts['qa']}"
            )
        )

    def update_selection_label(self):
        index = self.get_index()
        if index is None or not self.state.rows:
            self.selection_label.configure(text=f"Item 0/{self.state.total_rows}")
            return

        absolute_index = page_offset(self.state.page_index, PAGE_SIZE) + index + 1
        self.selection_label.configure(
            text=f"Item {absolute_index}/{self.state.total_rows} · {self.current_pair()}"
        )

    def current_pair(self):
        """O par de idiomas da linha carregada, como `Inglês -> pt`.

        Sai da LINHA e nao do filtro: com "Origem: Todos" os dois divergem, e e
        justamente nesse caso que a informacao importa — e o unico momento em que
        a lista mistura idiomas de origem.
        """
        origem = self.current.get("source_language") or ""
        return f"{language_label(origem)} -> {self.lang}"

    def update_quality_warnings(self):
        warnings = evaluate_translation_quality(
            self.current["orig"],
            self.trans_text.get("1.0", tk.END),
        )
        if warnings:
            self.qa_label.configure(
                text="QA: " + " | ".join(warnings),
                text_color="#f59e0b",
            )
        elif self.current["id"]:
            self.qa_label.configure(text="QA: sem avisos", text_color="#16a34a")
        else:
            self.qa_label.configure(text="", text_color="#16a34a")

    def update_history_label(self):
        if not self.current["id"]:
            self.history_label.configure(text="")
            return

        self.history_label.configure(
            text=(
                f"Criada: {format_timestamp(self.current['created_at'])} | "
                f"Editada: {format_timestamp(self.current['updated_at'])} | "
                f"Verificada: {format_timestamp(self.current['verified_at'])}"
            )
        )

    def set_current_history(self, row):
        self.current["created_at"] = row[2] or "" if len(row) > 2 else ""
        self.current["updated_at"] = row[3] or "" if len(row) > 3 else ""
        self.current["verified_at"] = row[4] or "" if len(row) > 4 else ""
        self.update_history_label()

    def text_index_for_offset(self, offset):
        return f"1.0+{max(0, int(offset))}c"

    def clear_find_highlights(self):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)
        self.state.current_find_match = None

    def editor_find_ranges(self):
        return find_text_ranges(
            self.draft_text(),
            self.editor_find_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )

    def highlight_find_ranges(self, ranges, current_range=None):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)

        for start, end in ranges:
            self.trans_text.tag_add(
                "find_match",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )

        if current_range is not None:
            start, end = current_range
            self.trans_text.tag_add(
                "find_current",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )
            self.trans_text.tag_raise("find_current")

    def refresh_find_matches(self, keep_current=True):
        if not self.editor_find_text.get():
            self.clear_find_highlights()
            return []

        ranges = self.editor_find_ranges()
        current_range = None
        if keep_current and self.state.current_find_match in ranges:
            current_range = self.state.current_find_match
        self.state.current_find_match = current_range
        self.highlight_find_ranges(ranges, current_range)
        return ranges

    def select_find_match(self, ranges, index):
        if not ranges:
            self.clear_find_highlights()
            return

        index = index % len(ranges)
        current_range = ranges[index]
        self.state.current_find_match = current_range
        self.highlight_find_ranges(ranges, current_range)

        start, end = current_range
        start_index = self.text_index_for_offset(start)
        end_index = self.text_index_for_offset(end)
        self.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.trans_text.tag_add(tk.SEL, start_index, end_index)
        self.trans_text.mark_set(tk.INSERT, end_index)
        self.trans_text.see(start_index)
        self.trans_text.focus_set()
        self.show_message(f"Ocorrencia {index + 1}/{len(ranges)}")

    def find_next_in_translation(self, _event=None):
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia encontrada")
            return "break"

        if self.state.current_find_match in ranges:
            offset = self.state.current_find_match[1]
        else:
            try:
                offset = len(self.trans_text.get("1.0", tk.INSERT))
            except tk.TclError:
                offset = 0

        for index, (start, _end) in enumerate(ranges):
            if start >= offset:
                self.select_find_match(ranges, index)
                return "break"

        self.select_find_match(ranges, 0)
        return "break"

    def replace_current_in_translation(self, _event=None):
        if not self.current["id"]:
            return "break"
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia para substituir")
            return "break"

        match = self.state.current_find_match
        if match not in ranges:
            match = ranges[0]
        start, end = match
        replacement = self.editor_replace_text.get()
        self.trans_text.delete(self.text_index_for_offset(start), self.text_index_for_offset(end))
        self.trans_text.insert(self.text_index_for_offset(start), replacement)
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()

        next_offset = start + len(replacement)
        ranges = self.refresh_find_matches(keep_current=False)
        if ranges:
            for index, (match_start, _match_end) in enumerate(ranges):
                if match_start >= next_offset:
                    self.select_find_match(ranges, index)
                    break
            else:
                self.select_find_match(ranges, 0)

        self.show_message("Ocorrencia substituida")
        return "break"

    def replace_all_in_translation(self):
        if not self.current["id"]:
            return
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return

        new_text, count = replace_all_text(
            self.draft_text(),
            self.editor_find_text.get(),
            self.editor_replace_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )
        if count == 0:
            self.show_message("Nenhuma ocorrencia para substituir")
            return

        self.set_translation_text(new_text, mark_dirty=True)
        self.refresh_find_matches(keep_current=False)
        self.show_message(f"{count} ocorrencia(s) substituida(s)")

    def set_translation_text(self,
        text,
        mark_dirty=False,
        autosave_draft=True,
        insert_offset=None,
        focus_editor=False,
    ):
        self.state.loading = True
        self.trans_text.delete("1.0", tk.END)
        self.trans_text.insert("1.0", text or "")
        try:
            self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.state.loading = False
        self.set_dirty(mark_dirty, autosave_draft=autosave_draft)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches(keep_current=False)
        if insert_offset is not None:
            insert_index = self.text_index_for_offset(insert_offset)
            self.trans_text.mark_set(tk.INSERT, insert_index)
            self.trans_text.see(insert_index)
            self.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        if focus_editor:
            self.trans_text.focus_set()

    def on_translation_modified(self, _event=None):
        try:
            modified = self.trans_text.edit_modified()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            return
        if modified and not self.state.loading:
            # A partir daqui a alteracao e do usuario, nao mais das regras
            # automaticas: a gravacao ao navegar volta a ser legitima.
            self.current["auto_only"] = False
            self.set_dirty(True)
            self.update_quality_warnings()
            self.refresh_find_matches()

    def apply_font_size(self):
        size = self.state.font_size
        self.body_font.configure(size=size)
        self.body_bold_font.configure(size=size, weight="bold")
        self.row_font.configure(size=max(10, size - 1))
        self.suggestion_font.configure(size=max(10, size - 1))
        self.font_label.configure(text=f"{size} pt")
        for text in (self.orig_text, self.trans_text):
            text.tag_configure("bold", font=self.body_bold_font)
            text.tag_configure("glossary_hit", font=self.body_bold_font)

    def adjust_font(self, delta):
        self.state.font_size = max(9, min(24, self.state.font_size + delta))
        self.apply_font_size()
        self.save_editor_settings()

    def toggle_bold_view(self):
        self.state.bold_view = not self.state.bold_view
        if self.state.bold_view:
            self.trans_text.configure(font=self.body_bold_font)
            self.btn_bold.configure(fg_color=("#3b82f6", "#1f6aa5"), hover_color=("#2563eb", "#1d4ed8"))
        else:
            self.trans_text.configure(font=self.body_font)
            self.btn_bold.configure(fg_color=("#3B8ED0", "#1F6AA5"), hover_color=("#36719F", "#144870"))

    def toggle_bold_selection(self, _event=None):
        """Marca (ou desmarca) em negrito o trecho selecionado da traducao.

        Existia no projeto original e se perdeu quando o botao "B" passou a
        alternar a fonte do editor inteiro (`toggle_bold_view`). Sao recursos
        diferentes e ambos uteis: um e leitura, o outro e marcacao. O botao
        continua com o alternador de fonte, junto dos controles A-/A+ onde ele
        pertence; a marcacao voltou no `Ctrl+B`, que e o gesto universal para
        "negrito no que esta selecionado".

        A marca e **visual e da sessao**: a tag do Tk nao vai para o banco, e
        recarregar a traducao a desfaz. Era assim no original, e faz sentido —
        o que se grava e o texto do comentario, nao a formatacao de quem revisa.
        """
        try:
            inicio = self.trans_text.index(tk.SEL_FIRST)
            fim = self.trans_text.index(tk.SEL_LAST)
        except tk.TclError:
            self.show_message("Selecione um trecho da tradução")
            return "break"

        if "bold" in self.trans_text.tag_names(inicio):
            self.trans_text.tag_remove("bold", inicio, fim)
        else:
            self.trans_text.tag_add("bold", inicio, fim)
        return "break"

    def highlight_glossary_hits(self):
        self.trans_text.tag_remove("glossary_hit", "1.0", tk.END)
        # Lido UMA vez: estava dentro do laco, o que fazia ate 80 travessias
        # Tk->Python do texto inteiro para pintar sempre a mesma coisa.
        text = self.trans_text.get("1.0", tk.END)
        for orig, _new in self.current_suggestions:
            for start, end in find_glossary_matches(text, orig):
                self.trans_text.tag_add(
                    "glossary_hit",
                    self.text_index_for_offset(start),
                    self.text_index_for_offset(end),
                )

    def clear_current(self):
        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.configure(state="disabled")
        self.trans_text.delete("1.0", tk.END)
        self.current["id"] = None
        self.current["orig"] = ""
        self.current["trans"] = ""
        self.current["saved_trans"] = ""
        self.current["created_at"] = ""
        self.current["updated_at"] = ""
        self.current["verified_at"] = ""
        # Sem isto o rotulo continuaria anunciando o par da linha que acabou de
        # sair da tela — a informacao errada e mais cara que nenhuma.
        self.current["source_language"] = ""
        try:
            self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        self.clear_find_highlights()
        self.draft_label.configure(text="")
        self.refresh_suggestions()
        self.update_selection_label()
        self.update_quality_warnings()
        self.update_history_label()

    def page_count(self):
        return compute_page_count(self.state.total_rows, PAGE_SIZE)

    def selected_status_filter(self):
        value = self.status_segment.get()
        if value == "Pendentes":
            return "pending"
        if value == "Verificadas":
            return "verified"
        if value == "Avisos QA":
            # "warnings" e resolvido em SQL pela coluna quality_warning, entao o
            # filtro de avisos usa exatamente o mesmo caminho paginado dos
            # demais — nada de carregar a tabela inteira para depois fatiar.
            return "warnings"
        return "all"

    def selected_search_mode(self):
        """O modo escolhido no seletor, na forma que o banco entende.

        Lido a cada consulta, e nao guardado no estado: assim trocar o modo e o
        proprio recarregamento ja bastam para o resultado mudar, sem uma copia
        do valor para ficar desatualizada.
        """
        if self.search_mode_segment.get() == SEARCH_MODE_LABEL_SUBSTRING:
            return SEARCH_MODE_SUBSTRING
        return SEARCH_MODE_TERMS

    def qa_filter_active(self):
        return self.status_segment.get() == "Avisos QA"

    def selected_source_language(self):
        """O filtro de origem na forma que o banco entende (`None` = todos).

        Lido a cada consulta pelo mesmo motivo de `selected_search_mode`: o
        seletor e a fonte da verdade, e uma copia no estado so daria uma segunda
        coisa para ficar desatualizada.
        """
        return source_filter_code(self.source_menu.get())

    def change_language_filter(self):
        """Troca de par de idiomas: grava o que estava aberto e recomeca.

        Grava ANTES de trocar (`save_changes`), e nao depois: a linha em edicao
        pertence ao par antigo, e apos a troca ela nao esta mais na lista — o
        rascunho seria gravado contra um item que a janela nao mostra mais, ou
        perdido em silencio.

        Volta para a primeira pagina porque a pagina 40 do par anterior nao quer
        dizer nada no novo: o filtro pode ter 3 linhas, e `clamp_page` deixaria o
        usuario numa lista vazia sem explicar por que.
        """
        if self.current["id"]:
            self.save_changes()

        novo_destino = target_language_code(self.target_menu.get())
        if novo_destino and novo_destino != self.lang:
            self.lang = novo_destino
            self.win.title(f"Editar traduções ({self.lang})")

        self.state.page_index = 0
        self.clear_current()
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        self.save_editor_settings()

    def fetch_quality_warning_rows(self, cur):
        """Linhas com aviso — usado pelo relatorio QA, que precisa de todas."""
        return fetch_review_rows(
            cur,
            self.lang,
            search_text=self.state.active_search,
            status_filter="warnings",
            search_mode=self.selected_search_mode(),
            source_language=self.selected_source_language(),
        )

    def update_page_controls(self):
        pages = self.page_count()
        current_page = self.state.page_index + 1 if pages else 0
        search_suffix = " · busca ativa" if self.state.active_search else ""
        status_suffix = f" · {self.status_segment.get().lower()}"
        self.page_label.configure(
            text=(
                f"Página {current_page}/{pages} · "
                f"{self.state.total_rows} traduções{status_suffix}{search_suffix}"
            )
        )
        self.btn_page_prev.configure(
            state="normal" if self.state.page_index > 0 else "disabled"
        )
        self.btn_page_next.configure(
            state="normal" if self.state.page_index + 1 < pages else "disabled"
        )

    def render_rows(self):
        self.row_buttons.clear()
        self.state.selected_index = None
        self.update_page_controls()
        self.update_counts_label()
        self.update_selection_label()

        if self.qa_filter_active():
            vazio = "Nenhum aviso QA encontrado."
        elif self.state.active_search:
            vazio = "Nenhuma tradução encontrada para a busca."
        else:
            vazio = "Nenhuma tradução encontrada."

        self.row_buttons.extend(
            render_row_buttons(
                self.rows_frame, self.state.rows, self.build_row_button, vazio
            )
        )

    def build_row_button(self, parent, index, row):
        return ctk.CTkButton(
            parent,
            text=row_label(row),
            anchor="w",
            height=64,
            fg_color=row_color(row),
            text_color=row_text_color(row),
            hover_color=ROW_HOVER_COLOR,
            font=self.row_font,
            command=lambda i=index: self.select_index(i, save_previous=True),
        )

    def reload_rows(self):
        source_language = self.selected_source_language()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            self.state.status_counts.update(
                get_review_status_counts(
                    cur,
                    self.lang,
                    self.state.active_search,
                    search_mode=self.selected_search_mode(),
                    source_language=source_language,
                )
            )
            # A contagem de avisos ja vem agregada junto com as demais.
            self.state.status_counts["qa"] = self.state.status_counts.get("warnings", 0)

            # O total do filtro ativo tambem ja veio no resumo acima: as duas
            # consultas varriam a mesma tabela com o mesmo `WHERE`. Com busca
            # ativa, cada varredura dessas custa ~100 ms e nao usa indice
            # (`LIKE '%termo%'`), entao e uma por interacao a menos (ROADMAP 2.8).
            status_filter = self.selected_status_filter()
            self.state.total_rows = count_from_status_counts(
                self.state.status_counts,
                status_filter,
            )
            if self.state.total_rows is None:
                self.state.total_rows = count_review_rows(
                    cur,
                    self.lang,
                    search_text=self.state.active_search,
                    status_filter=status_filter,
                    search_mode=self.selected_search_mode(),
                    source_language=source_language,
                )
            self.state.page_index = clamp_page(
                self.state.page_index, self.state.total_rows, PAGE_SIZE
            )
            offset = page_offset(self.state.page_index, PAGE_SIZE)
            self.state.rows = list(
                fetch_review_rows_page(
                    cur,
                    self.lang,
                    limit=PAGE_SIZE,
                    offset=offset,
                    search_text=self.state.active_search,
                    status_filter=self.selected_status_filter(),
                    search_mode=self.selected_search_mode(),
                    source_language=source_language,
                )
            )
        self.render_rows()

    def get_index(self):
        return self.state.selected_index

    def update_row_selection(self, new_index):
        old_index = self.state.selected_index
        if old_index is not None and 0 <= old_index < len(self.row_buttons):
            self.row_buttons[old_index].configure(
                fg_color=row_color(self.state.rows[old_index]),
                text_color=row_text_color(self.state.rows[old_index]),
            )

        self.state.selected_index = new_index
        if new_index is not None and 0 <= new_index < len(self.row_buttons):
            self.row_buttons[new_index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        self.update_selection_label()

    def select_index(self, index, save_previous=False):
        if not self.state.rows:
            return

        if save_previous and self.current["id"]:
            # `save_changes` pode trocar `state.rows` por baixo: com o filtro "Avisos
            # QA" ativo, corrigir o aviso tira a linha atual da lista; com o
            # filtro "pendentes", marcar como verificada faz o mesmo. Nos dois
            # casos ele recarrega e chama `select_index` por conta propria, e a
            # posicao que chegou aqui passa a apontar para outra linha.
            #
            # Guardar o id do alvo antes de gravar e reencontra-lo depois e o
            # que garante que o clique em B nao acabe carregando C.
            target_id = self.state.rows[index][0] if 0 <= index < len(self.state.rows) else None
            self.save_changes()
            if not self.state.rows:
                return
            index = row_index_for_id(self.state.rows, target_id, fallback=index)
            if index is None:
                return

        index = max(0, min(index, len(self.state.rows) - 1))
        self.update_row_selection(index)
        self.load_item()

    def load_item(self):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.state.rows)):
            return

        comment_id = self.state.rows[index][0]
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            row = fetch_translation_by_id(cur, comment_id)

        if row is None:
            return

        orig, trans = row[0], row[1]
        self.current["id"] = comment_id
        self.current["orig"] = orig or ""
        self.current["trans"] = trans or ""
        self.current["saved_trans"] = self.current["trans"]
        # O par de idiomas da LINHA, que nao e o mesmo que o filtro: com
        # "Origem: Todos" ativo a lista mistura pares de proposito, e sem isto
        # nada na tela diz de qual delas veio o texto que esta sendo revisado.
        self.current["source_language"] = row[5] if len(row) > 5 else ""
        self.set_current_history(row)

        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.insert("1.0", self.current["orig"])
        self.orig_text.configure(state="disabled")

        draft = get_editor_draft(
            self.settings,
            self.app.output_db,
            self.lang,
            comment_id,
            self.current["trans"],
        )
        if draft is None:
            auto_text = apply_automatic_substitutions(self.current["trans"], self.automatic_glossary)
            if auto_text != self.current["trans"]:
                # Sugestao das regras automaticas: mostra e sinaliza como nao
                # salva, mas nao grava sozinha nem gera rascunho. Aplicar em
                # massa continua sendo o caminho deliberado, com preview e backup.
                self.current["auto_only"] = True
                self.set_translation_text(auto_text, mark_dirty=True, autosave_draft=False)
            else:
                self.current["auto_only"] = False
                self.set_translation_text(self.current["trans"], mark_dirty=False)
        else:
            self.current["auto_only"] = False
            self.set_translation_text(
                draft["text"],
                mark_dirty=True,
                autosave_draft=False,
            )
            self.draft_label.configure(
                text=f"Rascunho restaurado {format_timestamp(draft['updated_at'])}",
                text_color="#64748b",
            )
            self.show_message("Rascunho restaurado")

        # DEPOIS de carregar, e nao antes. `select_index` pinta a selecao — o que
        # ja atualiza o rotulo — e so entao chama este metodo; sem esta segunda
        # chamada o rotulo anuncia o par da linha ANTERIOR, que e o pior tipo de
        # informacao errada porque parece certa.
        self.update_selection_label()

    def update_current_row_cache(self, verified=None):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.state.rows)):
            return

        if verified is None:
            verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0

        self.state.rows[index] = (
            self.current["id"],
            self.current["orig"],
            self.current["trans"],
            verified,
            self.current["created_at"],
            self.current["updated_at"],
            self.current["verified_at"],
        )
        self.row_buttons[index].configure(text=row_label(self.state.rows[index]))
        if self.state.selected_index == index:
            self.row_buttons[index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        else:
            self.row_buttons[index].configure(
                fg_color=row_color(self.state.rows[index]),
                text_color=row_text_color(self.state.rows[index]),
            )

    def save_changes(self, silent=True, mark_verified=False):
        if not self.current["id"]:
            return

        # Gravacao silenciosa e a que acontece ao navegar pela lista. Se a unica
        # diferenca veio das regras automaticas, o usuario nao pediu nada: rolar
        # 50 linhas nao pode reescrever 50 traducoes e gerar 50 registros de
        # historico (garantia R1 da SPEC.md). Salvar explicitamente ou marcar
        # como verificada continua funcionando normalmente.
        if silent and not mark_verified and self.current["auto_only"]:
            return

        new_trans = self.trans_text.get("1.0", tk.END).rstrip("\n")

        updated_row = None
        propagated_rows = 0
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            update_translation_by_id(cur, self.current["id"], new_trans, mark_verified)
            if mark_verified:
                propagated_rows = set_exact_translation_matches_verified(cur, self.current["id"])
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()

        self.current["trans"] = new_trans
        self.current["saved_trans"] = new_trans
        self.current["auto_only"] = False
        self.clear_current_draft()
        if updated_row is not None:
            self.set_current_history(updated_row)
        try:
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        if mark_verified and propagated_rows:
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                # Verificar propaga para as traducoes iguais, entao a lista
                # inteira pode ter mudado de tamanho. A linha atual continua
                # sendo a certa; a posicao dela, nao.
                self.select_index(
                    row_index_for_id(self.state.rows, self.current["id"], fallback=idx or 0)
                )
            else:
                self.clear_current()
            if not silent:
                self.show_message(
                    f"Tradução salva e verificada; {propagated_rows} iguais também verificadas"
                )
            return propagated_rows

        index = self.get_index()
        old_warning = False
        new_warning = False
        if index is not None and 0 <= index < len(self.state.rows):
            old_verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0
            old_warning = row_has_quality_warning(self.state.rows[index])
            verified = 1 if mark_verified else old_verified
            self.update_current_row_cache(verified)
            new_warning = row_has_quality_warning(self.state.rows[index])
            if old_warning != new_warning:
                if new_warning:
                    self.state.status_counts["qa"] += 1
                else:
                    self.state.status_counts["qa"] = max(0, self.state.status_counts["qa"] - 1)
                self.update_counts_label()
            if mark_verified and old_verified != 1:
                self.state.status_counts["pending"] = max(0, self.state.status_counts["pending"] - 1)
                self.state.status_counts["verified"] += 1
                self.update_counts_label()

        if self.qa_filter_active() and old_warning and not new_warning:
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if idx is None else min(idx, len(self.state.rows) - 1))
            else:
                self.clear_current()

        if mark_verified and self.selected_status_filter() == "pending":
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if idx is None else min(idx, len(self.state.rows) - 1))
            else:
                self.clear_current()

        if not silent:
            if mark_verified:
                self.show_message("Tradução salva e verificada")
            else:
                self.show_message("Tradução salva")

    def navigate(self, delta):
        self.save_changes()
        index = self.get_index()
        if index is None:
            index = 0

        new_index = index + delta
        if 0 <= new_index < len(self.state.rows):
            self.select_index(new_index)
        elif new_index < 0 and self.state.page_index > 0:
            self.state.page_index -= 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(len(self.state.rows) - 1)
        elif new_index >= len(self.state.rows) and self.state.page_index + 1 < self.page_count():
            self.state.page_index += 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")

    def change_page(self, delta):
        self.save_changes()
        new_page = self.state.page_index + delta
        if 0 <= new_page < self.page_count():
            self.state.page_index = new_page
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)

    def go_to_page(self):
        self.save_changes()
        try:
            target_page = int(self.go_page_text.get().strip())
        except ValueError:
            self.show_message("Página inválida")
            return

        pages = self.page_count()
        if not (1 <= target_page <= pages):
            self.show_message("Página fora do intervalo")
            return

        self.state.page_index = target_page - 1
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)

    def go_to_id(self):
        self.save_changes()
        try:
            target_id = int(self.go_id_text.get().strip())
        except ValueError:
            self.show_message("ID inválido")
            return

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            # Vale para todos os filtros, inclusive "Avisos QA": o offset sai de
            # um COUNT indexado em vez de uma varredura ate achar o ID.
            offset = get_review_row_offset(
                cur,
                self.lang,
                target_id,
                search_text=self.state.active_search,
                status_filter=self.selected_status_filter(),
                search_mode=self.selected_search_mode(),
            )

        if offset is None:
            self.show_message("ID não encontrado nos filtros atuais")
            return

        self.state.page_index = page_of_offset(offset, PAGE_SIZE)
        self.reload_rows()
        target_index = local_index_for_offset(offset, PAGE_SIZE, len(self.state.rows))
        if target_index is not None:
            self.select_index(target_index)

    def find_quality_warning_offset(self, start_offset, stop_offset):
        if start_offset >= stop_offset:
            return None

        offset = start_offset
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            while offset < stop_offset:
                page_start = page_offset(page_of_offset(offset, PAGE_SIZE), PAGE_SIZE)
                local_start = offset - page_start
                page_rows = list(
                    fetch_review_rows_page(
                        cur,
                        self.lang,
                        limit=PAGE_SIZE,
                        offset=page_start,
                        search_text=self.state.active_search,
                        status_filter=self.selected_status_filter(),
                        search_mode=self.selected_search_mode(),
                    )
                )
                if not page_rows:
                    break

                page_limit = stop_offset - page_start
                if page_limit < len(page_rows):
                    page_rows = page_rows[:page_limit]

                found = find_first_quality_warning(page_rows, local_start)
                if found is not None:
                    found_index, _row, warnings = found
                    return page_start + found_index, warnings

                offset = page_start + len(page_rows)

        return None

    def go_to_next_quality_warning(self):
        self.save_changes()
        total = self.state.total_rows
        if total == 0:
            self.show_message("Nenhum item nos filtros atuais")
            return

        index = self.get_index()
        base_offset = page_offset(self.state.page_index, PAGE_SIZE)
        start_offset = base_offset if index is None else base_offset + index + 1

        if start_offset >= total:
            start_offset = 0

        if self.qa_filter_active():
            # Todas as linhas do filtro ja tem aviso: basta ir para a proxima.
            target_offset = start_offset
            self.state.page_index = page_of_offset(target_offset, PAGE_SIZE)
            self.reload_rows()
            # `state.rows` vem de um reload novo e pode ser menor que a pagina
            # anterior
            # (o worker de traducao escreve no mesmo banco), entao o indice
            # precisa ser limitado antes de indexar a lista.
            local_index = local_index_for_offset(target_offset, PAGE_SIZE, len(self.state.rows))
            if local_index is not None:
                self.select_index(local_index)
                warnings = evaluate_translation_quality(
                    self.state.rows[local_index][1],
                    self.state.rows[local_index][2],
                )
                if warnings:
                    self.show_message("Aviso QA: " + warnings[0])
            return

        found = self.find_quality_warning_offset(start_offset, total)
        if found is None and start_offset > 0:
            found = self.find_quality_warning_offset(0, start_offset)

        if found is None:
            self.show_message("Nenhum aviso QA nos filtros atuais")
            return

        target_offset, warnings = found
        self.state.page_index = page_of_offset(target_offset, PAGE_SIZE)
        self.reload_rows()
        local_index = local_index_for_offset(target_offset, PAGE_SIZE, len(self.state.rows))
        if local_index is not None:
            self.select_index(local_index)
        self.show_message("Aviso QA: " + warnings[0])

    def export_quality_report(self):
        self.save_changes()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            report_rows = build_quality_report_rows(
                self.fetch_quality_warning_rows(cur),
                self.lang,
            )

        if not report_rows:
            self.show_message("Nenhum aviso QA para exportar")
            return

        save_path = filedialog.asksaveasfilename(
            title="Salvar relatorio QA",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return

        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(QUALITY_REPORT_HEADERS)
                writer.writerows(report_rows)
        except OSError as exc:
            messagebox.showerror("Erro", f"Erro ao exportar relatorio QA:\n{exc}")
            return

        messagebox.showinfo(
            "Exportar QA",
            f"Relatorio QA exportado com {len(report_rows)} avisos:\n{save_path}",
        )

    def mark_and_next(self):
        if not self.current["id"]:
            return

        # Mesma raiz do `select_index`: `save_changes(mark_verified=True)` pode
        # recarregar a lista — propagando para as traducoes iguais, ou tirando
        # esta linha do filtro ativo — e ai a posicao capturada agora aponta
        # para outra linha. Guardamos o id e reencontramos a posicao depois.
        current_id = self.current["id"]
        index = self.get_index()
        propagated = self.save_changes(mark_verified=True) or 0

        if self.selected_status_filter() == "pending":
            if propagated:
                self.show_message(f"Verificada; {propagated} iguais também verificadas")
            else:
                self.show_message("Marcada como verificada" if self.current["id"] else "Sem traduções pendentes")
            return

        position = row_index_for_id(self.state.rows, current_id, fallback=index or 0)
        if position is None:
            self.show_message("Fim da lista")
            return

        # Se a linha saiu da lista, quem ocupou o lugar dela ja E a proxima —
        # avancar mais uma casa pularia uma traducao.
        if self.state.rows[position][0] == current_id:
            new_index = position + 1
        else:
            new_index = position

        if 0 <= new_index < len(self.state.rows):
            self.select_index(new_index)
        elif new_index >= len(self.state.rows) and self.state.page_index + 1 < self.page_count():
            self.state.page_index += 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")
            return

        if propagated:
            self.show_message(f"Verificada; {propagated} iguais também verificadas")
        else:
            self.show_message("Marcada como verificada")

    def mark_pending(self):
        if not self.current["id"]:
            return

        self.save_changes()
        updated_row = None
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            set_translation_verified_by_id(cur, self.current["id"], False)
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()
        if updated_row is not None:
            self.set_current_history(updated_row)

        index = self.get_index()
        if self.selected_status_filter() == "verified":
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if index is None else min(index, len(self.state.rows) - 1))
            else:
                self.clear_current()
        elif index is not None and 0 <= index < len(self.state.rows):
            old_verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0
            self.update_current_row_cache(0)
            if old_verified == 1:
                self.state.status_counts["verified"] = max(0, self.state.status_counts["verified"] - 1)
                self.state.status_counts["pending"] += 1
                self.update_counts_label()

        self.show_message("Marcada como pendente")

    def open_history_window(self):
        if not self.current["id"]:
            self.show_message("Selecione uma traducao")
            return

        self.save_changes()
        # O item e fixado AQUI, e nao lido pela subjanela a cada acao: ela e
        # modeless e a lista principal continua clicavel enquanto ela esta
        # aberta (garantia R3).
        return HistoryWindow(self, self.current["id"], self.current["orig"])

    def undo_translation(self):
        try:
            self.trans_text.edit_undo()
        except tk.TclError:
            self.show_message("Nada para desfazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def redo_translation(self):
        try:
            self.trans_text.edit_redo()
        except tk.TclError:
            self.show_message("Nada para refazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def restore_saved_translation(self):
        if not self.current["id"]:
            return
        self.set_translation_text(self.current["saved_trans"], mark_dirty=False)
        self.current["trans"] = self.current["saved_trans"]
        self.clear_current_draft()
        self.show_message("Tradução restaurada")

    def copy_original_to_translation(self):
        if not self.current["id"]:
            return
        self.set_translation_text(self.current["orig"], mark_dirty=True)
        self.show_message("Original copiado para tradução")

    def toggle_filter(self):
        self.state.page_index = 0
        self.save_editor_settings()
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def apply_search(self):
        self.save_changes()
        self.state.active_search = self.search_text.get().strip()
        self.state.page_index = 0
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def clear_search(self):
        if not self.state.active_search and not self.search_text.get():
            return
        self.search_text.set("")
        self.state.active_search = ""
        self.state.page_index = 0
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def apply_automatic_rules_for_current_language(self):
        self.save_changes()
        previous_id = self.current["id"]

        def concluido(stats):
            # Chega pela thread do Tk quando a operacao termina; `None` quando
            # o usuario cancelou, nao confirmou ou nao havia o que mudar.
            if not stats or stats.get("changed", 0) == 0:
                return
            if not self.win.winfo_exists():
                return

            self.reload_rows()
            if not self.state.rows:
                self.clear_current()
                return

            self.select_index(row_index_for_id(self.state.rows, previous_id, fallback=0))
            self.show_message(f"{stats['changed']} traducao(oes) atualizada(s)")

        # Restrito ao mesmo filtro que a lista mostra: com "Origem: Espanhol"
        # ativo, o usuario esta olhando as traducoes vindas do espanhol, e
        # reescrever tambem as das outras linguas seria uma alteracao em massa
        # que ele nao pediu nem consegue ver na tela.
        apply_automatic_rules_to_database(
            self.app,
            target_language=self.lang,
            parent=self.win,
            on_finish=concluido,
            source_language=self.selected_source_language(),
        )

    def select_suggestion(self, index):
        old = self.state.selected_suggestion
        if old is not None and 0 <= old < len(self.suggestion_buttons):
            self.suggestion_buttons[old].configure(
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
            )

        self.state.selected_suggestion = index
        if 0 <= index < len(self.suggestion_buttons):
            self.suggestion_buttons[index].configure(
                fg_color=SUGGESTION_SELECTED_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )

    def delete_suggestion_from_glossary(self, orig, new):
        # Exclui pelo par, nunca por indice: a lista exibida aqui e deduplicada
        # e a exclusao opera sobre a lista completa do arquivo, entao os indices
        # nao correspondem (garantia S6 da SPEC.md).
        if delete_glossary_entry_by_pair(orig, new) is None:
            self.show_message("Entrada não encontrada no glossário")
            return

        self.reload_glossary(show_feedback=False)
        self.show_message(f'Removido do glossário: "{preview(orig, 30)}"')

    def show_suggestion_context_menu(self, event, orig, new):
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(
            label="Excluir do glossário",
            command=lambda: self.delete_suggestion_from_glossary(orig, new),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def refresh_suggestions(self):
        for child in self.suggestions_frame.winfo_children():
            child.destroy()
        self.suggestion_buttons.clear()
        self.state.selected_suggestion = None

        text = self.trans_text.get("1.0", tk.END)
        self.current_suggestions = find_glossary_suggestions(text, self.glossary)
        self.highlight_glossary_hits()

        if not self.current_suggestions:
            ctk.CTkLabel(self.suggestions_frame, text="Nenhuma sugestão.").pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, (orig, new) in enumerate(self.current_suggestions):
            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=f'"{preview(orig, 45)}" -> "{preview(new, 45)}"',
                anchor="w",
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
                hover_color=ROW_HOVER_COLOR,
                font=self.suggestion_font,
                command=lambda i=index: self.select_suggestion(i),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            btn.bind(
                "<Button-3>",
                lambda event, o=orig, n=new: self.show_suggestion_context_menu(event, o, n),
            )
            self.suggestion_buttons.append(btn)

    def apply_glossary_pair_with_cursor(self, text, orig, new, count=0):
        matches = find_glossary_matches(text, orig)
        if count > 0:
            matches = matches[:count]
        if not matches:
            return text, None

        parts = []
        last = 0
        cursor_offset = 0
        insert_offset = None
        for start, end in matches:
            before = text[last:start]
            parts.append(before)
            cursor_offset += len(before)
            replacement = case_adjusted_replacement(text[start:end], new)
            parts.append(replacement)
            cursor_offset += len(replacement)
            insert_offset = cursor_offset
            last = end
        parts.append(text[last:])
        return "".join(parts), insert_offset

    def apply_suggestions_with_cursor(self, text, suggestions):
        insert_offset = None
        for orig, new in suggestions:
            text, pair_offset = self.apply_glossary_pair_with_cursor(text, orig, new)
            if pair_offset is not None:
                insert_offset = pair_offset
        return text, insert_offset

    def apply_one(self):
        index = self.state.selected_suggestion
        if index is None or not (0 <= index < len(self.current_suggestions)):
            return

        orig, new = self.current_suggestions[index]
        text = self.draft_text()
        updated_text, insert_offset = self.apply_glossary_pair_with_cursor(
            text,
            orig,
            new,
            count=1,
        )
        if insert_offset is None:
            self.show_message("Sugestão não encontrada no texto")
            return
        self.set_translation_text(
            updated_text,
            mark_dirty=True,
            insert_offset=insert_offset,
            focus_editor=True,
        )

    def apply_all(self):
        text = self.draft_text()
        preview_text, preview_offset = self.apply_suggestions_with_cursor(
            text,
            self.current_suggestions,
        )
        if preview_text == text:
            self.show_message("Nenhuma alteração sugerida")
            return

        pop = ctk.CTkToplevel(self.win)
        pop.title("Pré-visualizar substituições")
        pop.geometry("980x560")
        bring_window_to_front(pop, self.win, maximize=True)

        ctk.CTkLabel(pop, text="Antes").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(pop, text="Depois").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 2))

        before_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        after_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        before_text.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        after_text.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        before_text.insert("1.0", text)
        after_text.insert("1.0", preview_text)
        before_text.configure(state="disabled")
        after_text.configure(state="disabled")

        actions = ctk.CTkFrame(pop, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))

        def confirm():
            self.set_translation_text(
                preview_text,
                mark_dirty=True,
                insert_offset=preview_offset,
                focus_editor=True,
            )
            pop.destroy()

        ctk.CTkButton(actions, text="Cancelar", width=100, command=pop.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ctk.CTkButton(actions, text="Aplicar", width=100, command=confirm).pack(side=tk.RIGHT)

        pop.columnconfigure(0, weight=1)
        pop.columnconfigure(1, weight=1)
        pop.rowconfigure(1, weight=1)

    def reload_glossary(self, show_feedback=True):
        self.glossary = load_interactive_substitutions()
        self.automatic_glossary = load_automatic_substitutions()
        self.app.glossary_substitutions = self.glossary
        self.refresh_suggestions()
        if show_feedback:
            self.show_message(f"Glossário atualizado: {len(self.glossary)} entradas")

    def on_glossary_editor_change(self, updated_entries):
        if not self.win.winfo_exists():
            self.unregister_glossary_callback()
            return
        self.glossary = list(updated_entries)
        self.automatic_glossary = load_automatic_substitutions()
        self.app.glossary_substitutions = self.glossary
        self.refresh_suggestions()
        self.show_message(f"Glossário atualizado: {len(self.glossary)} entradas")

    def selected_translation_text(self):
        try:
            return self.trans_text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ""

    def open_integrated_glossary_editor(self):
        selection = self.selected_translation_text()
        if selection:
            open_glossary_editor(self.app, initial_original=selection)
            self.show_message("Selecao enviada ao editor de glossario")
        else:
            open_glossary_editor(self.app)
            self.show_message("Selecione um trecho para pre-preencher o glossario")

    def unregister_glossary_callback(self):
        callbacks = getattr(self.app, "glossary_change_callbacks", [])
        if self.on_glossary_editor_change in callbacks:
            callbacks.remove(self.on_glossary_editor_change)


    def add_gloss_popup(self):
        sel_text = self.selected_translation_text()

        pop = ctk.CTkToplevel(self.win)
        pop.title("Adicionar ao glossário")
        pop.geometry("380x255")
        bring_window_to_front(pop, self.win, maximize=True)

        ctk.CTkLabel(pop, text="Texto original:").pack(anchor="w", padx=12, pady=(12, 2))
        original_entry = ctk.CTkEntry(pop, width=350)
        original_entry.pack(padx=12, fill=tk.X)
        original_entry.insert(0, sel_text)

        ctk.CTkLabel(pop, text="Substituir por:").pack(anchor="w", padx=12, pady=(10, 2))
        replacement_entry = ctk.CTkEntry(pop, width=350)
        replacement_entry.pack(padx=12, fill=tk.X)

        ctk.CTkLabel(pop, text="Tipo:").pack(anchor="w", padx=12, pady=(10, 2))
        type_var = tk.StringVar(master=pop, value="Sugestão")
        ctk.CTkSegmentedButton(
            pop,
            values=["Sugestão", "Automático", "Limpeza"],
            variable=type_var,
        ).pack(padx=12, fill=tk.X)

        _type_map = {"Sugestão": "suggestion", "Automático": "automatic", "Limpeza": "cleanup"}

        def confirm():
            orig = original_entry.get().strip()
            new = replacement_entry.get().strip()
            rule_type = _type_map.get(type_var.get(), "suggestion")
            if orig and (new or rule_type == "cleanup"):
                if add_to_glossary(orig, new, rule_type=rule_type):
                    self.reload_glossary(show_feedback=False)
                    self.show_message("Entrada adicionada ao glossário")
            pop.destroy()

        ctk.CTkButton(pop, text="Adicionar", command=confirm).pack(pady=14)

    def focus_search(self, _event=None):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
        return "break"

    def save_shortcut(self, _event=None):
        self.save_changes(False)
        return "break"

    def verify_shortcut(self, _event=None):
        self.save_changes(False, mark_verified=True)
        return "break"

    def previous_shortcut(self, _event=None):
        self.navigate(-1)
        return "break"

    def next_shortcut(self, _event=None):
        self.navigate(1)
        return "break"

    def next_quality_warning_shortcut(self, _event=None):
        self.go_to_next_quality_warning()
        return "break"

    def close_editor(self):
        self.save_changes()
        self.save_editor_settings()
        self.unregister_glossary_callback()
        self.win.destroy()


def open_translation_editor(app):
    """Abre a janela de edicao de traducoes.

    Continua sendo uma funcao porque e assim que o resto do programa chama, e
    porque quem abre a janela nao tem o que fazer com a instancia.
    """
    return TranslationEditor(app)
