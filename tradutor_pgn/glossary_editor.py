import hashlib
import os
from pathlib import Path
import tkinter as tk
import weakref
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .app_paths import glossary_catalog_path
from .app_config import LANGUAGES
from .background_task import TaskCanceled, run_with_progress
from .glossary_ui_helpers import describe_scope, normalize_search_text, scope_from_codes, scope_to_codes
from .glossary_rule_inspector import analyze_rule, format_rule_impact
from .glossary_engine import (
    SimulationCanceled, SimulationItem, explain_substitutions, format_explanation, format_simulation_examples,
    format_simulation_summary,
    simulate_database_rule_change, simulate_rule_change,
)
from .editor_text import diff_spans
from .glossary_catalog import (
    CatalogSnapshot, GlossaryCatalog, GlossaryConflictError, GlossaryDuplicateError,
    GlossaryEntryChanges, GlossaryEntryDraft, canonical_identity, validate_entry_draft,
)

from .glossario import (
    build_glossary_lookup,
    GLOSSARY_PRIORITY_DEFAULT,
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_RULE_TYPES,
    GLOSSARY_SCOPE_ALL,
    GLOSSARY_SCOPE_ANY,
    glossary_default_scope,
    initialize_catalog_glossary,
    _default_substitutions_path,
    glossary_entry_scope,
    normalize_glossary_scope,
    scope_matches,
    create_glossary_backup,
    describe_glossary_conflict,
    export_glossary_csv,
    glossary_conflicts,
    apply_all_substitutions,
    clean_comment_for_translation,
    filter_glossary_entries_by_type,
    interactive_rules_from_entries,
    glossary_entry_pair,
    glossary_entry_priority,
    glossary_entry_type,
    normalize_glossary_priority,
    promote_glossary_rule,
    load_interactive_substitutions,
    read_glossary_import,
    validate_glossary_entry,
)
from .db_tools import preview_automatic_rule_impact
from .settings import load_settings
from .editor_common import (
    DESTRUCTIVE_COLOR,
    DESTRUCTIVE_HOVER_COLOR,
    ERROR_TEXT_COLOR,
    MUTED_TEXT_COLOR,
    OK_TEXT_COLOR,
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    WARNING_TEXT_COLOR,
    clamp_page,
    page_count as compute_page_count,
    page_offset,
    preview as common_preview,
    window_safe_geometry,
)
from .editor_widgets import (
    attach_tooltip,
    flash_message,
    render_row_buttons,
    restore_sash,
    save_window_section,
)
from .window_utils import bring_window_to_front, restore_or_maximize


INVALID_PRIORITY_WARNING = "Prioridade precisa ser um número inteiro."
# Os tres nomes ficam — sao a linguagem desta janela —, mas o valor vem da
# paleta compartilhada (ROADMAP 22.9): eram um hex por cor, e um hex so nao serve
# aos dois temas.
WARNING_COLOR = WARNING_TEXT_COLOR
OK_COLOR = OK_TEXT_COLOR
ERROR_COLOR = ERROR_TEXT_COLOR
PAGE_SIZE = 150
MIN_WIDTH = 1040
MIN_HEIGHT = 640
RULE_TYPE_LABELS = {
    GLOSSARY_RULE_SUGGESTION: "Sugestão",
    GLOSSARY_RULE_CLEANUP: "Limpeza",
    GLOSSARY_RULE_AUTOMATIC: "Automática",
}
RULE_TYPE_BY_LABEL = {label: value for value, label in RULE_TYPE_LABELS.items()}
SCOPE_FILTERS = {"Todos os escopos": None, "Somente globais": "global",
                 "Somente específicos": "specific", "Compatíveis com o par atual": "compatible"}
PRIORITY_FILTERS = {"Todas as prioridades": None, "Prioridade positiva": "positive",
                    "Prioridade zero": "zero", "Prioridade negativa": "negative"}


def rule_type_label(rule_type):
    return RULE_TYPE_LABELS.get(rule_type, RULE_TYPE_LABELS[GLOSSARY_RULE_SUGGESTION])


def rule_type_value(label):
    return RULE_TYPE_BY_LABEL.get(label, GLOSSARY_RULE_SUGGESTION)


def entry_pairs(entries):
    return [glossary_entry_pair(entry) for entry in entries]


def preview(text, limit=68):
    return common_preview(text, limit)


def safe_geometry(win, geometry):
    return window_safe_geometry(win, geometry, MIN_WIDTH, MIN_HEIGHT)


def build_glossary_diagnostics(entries, conflicts=None):
    """Avisos por entrada, na ordem de `entries`.

    O aviso de conflito vem de `glossary_conflicts`, e nao de um agrupamento
    proprio, para que o filtro "Conflitos" mostre exatamente as regras para as
    quais o editor consegue dizer quem vence. Sem isso a lista acusaria disputas
    que nao existem — duas regras de mesmo padrao em contextos que o programa
    nunca carrega juntos.
    """
    pair_counts = {}
    for entry in entries:
        identity = canonical_identity(entry)
        pair_counts[identity] = pair_counts.get(identity, 0) + 1

    if conflicts is None:
        conflicts = glossary_conflicts(entries)

    diagnostics = []
    for index, entry in enumerate(entries):
        orig, new = glossary_entry_pair(entry)
        warnings = validate_glossary_entry(
            orig,
            new,
            rule_type=glossary_entry_type(entry),
            scope=glossary_entry_scope(entry),
        )
        if pair_counts.get(canonical_identity(entry), 0) > 1:
            warnings.append("Entrada duplicada.")
        if index in conflicts:
            warnings.append("Mesmo original com substituição diferente.")
        diagnostics.append(warnings)
    return diagnostics


def glossary_entry_warnings(entries, index, diagnostics=None):
    if diagnostics is not None and 0 <= index < len(diagnostics):
        return diagnostics[index]
    orig, new = glossary_entry_pair(entries[index])
    return validate_glossary_entry(
        orig,
        new,
        entries,
        current_index=index,
        rule_type=glossary_entry_type(entries[index]),
        scope=glossary_entry_scope(entries[index]),
    )


def glossary_filter_indices(entries, search_text="", filter_name="Todas", diagnostics=None, *, rule_type=None,
                            scope_filter=None, source_language=None, target_language=None, priority_filter=None):
    if priority_filter not in (None, "positive", "zero", "negative"):
        raise ValueError("Filtro de prioridade inválido")
    if scope_filter not in (None, "global", "specific", "compatible"):
        raise ValueError("Filtro de escopo inválido")
    if scope_filter == "compatible" and not target_language:
        raise ValueError("O idioma de destino é necessário")
    terms = normalize_search_text(search_text or "").split()
    result = []

    for index, entry in enumerate(entries):
        priority = glossary_entry_priority(entry)
        if ((priority_filter == "positive" and priority <= 0) or
                (priority_filter == "zero" and priority != 0) or
                (priority_filter == "negative" and priority >= 0)):
            continue
        if rule_type is not None and glossary_entry_type(entry) != rule_type:
            continue
        scope = glossary_entry_scope(entry)
        if scope_filter == "global" and scope:
            continue
        if scope_filter == "specific" and not scope:
            continue
        if scope_filter == "compatible" and not scope_matches(scope, source_language, target_language):
            continue
        orig, new = glossary_entry_pair(entry)
        label = rule_type_label(glossary_entry_type(entry))
        fields = (tuple(normalize_search_text(value) for value in
                        (orig, new, label, scope)) if terms else ())
        if terms and not all(any(term in value for value in fields) for term in terms):
            continue

        warnings = (glossary_entry_warnings(entries, index, diagnostics)
                    if filter_name in ("Duplicadas", "Conflitos", "Inválidas") else ())
        if filter_name == "Duplicadas" and "Entrada duplicada." not in warnings:
            continue
        if filter_name == "Conflitos" and "Mesmo original com substituição diferente." not in warnings:
            continue
        if filter_name == "Inválidas" and not warnings:
            continue

        result.append(index)

    return result


def sort_glossary_indices(entries, indices, sort_name="Ordem do arquivo"):
    if sort_name == "Original A-Z":
        return sorted(indices, key=lambda index: (glossary_entry_pair(entries[index])[0].casefold(), index))
    if sort_name == "Substituição A-Z":
        return sorted(indices, key=lambda index: (glossary_entry_pair(entries[index])[1].casefold(), index))
    if sort_name == "Maior original":
        return sorted(indices, key=lambda index: (-len(glossary_entry_pair(entries[index])[0]), index))
    if sort_name == "Maior prioridade":
        return sorted(indices, key=lambda index: (-glossary_entry_priority(entries[index]), index))
    if sort_name == "Menor prioridade":
        return sorted(indices, key=lambda index: (glossary_entry_priority(entries[index]), index))
    return list(indices)


def glossary_counts(entries, diagnostics=None):
    counts = {"total": len(entries), "duplicates": 0, "conflicts": 0, "invalid": 0}
    for index in range(len(entries)):
        warnings = glossary_entry_warnings(entries, index, diagnostics)
        if "Entrada duplicada." in warnings:
            counts["duplicates"] += 1
        if "Mesmo original com substituição diferente." in warnings:
            counts["conflicts"] += 1
        if warnings:
            counts["invalid"] += 1
    return counts


def row_label(entries, index, diagnostics=None):
    entry = entries[index]
    orig, new = glossary_entry_pair(entry)
    type_label = rule_type_label(glossary_entry_type(entry))
    warnings = glossary_entry_warnings(entries, index, diagnostics)
    status = "AVISO" if warnings else "OK"
    # A prioridade so aparece quando ha uma: mostra-la como "P0" em 7 mil linhas
    # transformaria a ausencia de decisao em ruido em toda a lista.
    priority = glossary_entry_priority(entry)
    marca = f"  ·  P{priority:+d}" if priority != GLOSSARY_PRIORITY_DEFAULT else ""
    # O idioma aparece so quando a regra o declara, pelo mesmo motivo da
    # prioridade: num glossario de um idioma so, escrever "pt" em cinco mil
    # linhas transforma o normal em ruido e esconde a excecao.
    scope = glossary_entry_scope(entry)
    if scope:
        marca += f"  ·  {scope}"
    return (
        f"{status}  #{index + 1}  -  {type_label}{marca}\n"
        f"De: {preview(orig)}\nPara: {preview(new)}"
    )


class ImportPreviewDialog:
    """Show the exact captured source rows before an append is authorized."""

    def __init__(self, parent, preview, on_confirm, on_close, *, allow_empty=False):
        self.win = ctk.CTkToplevel(parent)
        self.win.title("Prévia da importação")
        self.win.geometry("840x520")
        self.win.minsize(600, 350)
        self.win.transient(parent)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)
        self.on_close = on_close
        self.closed = False
        labels = {"new": "nova", "duplicate": "duplicada", "conflict": "conflitante", "invalid": "inválida"}
        new_count = sum(row.status == "new" for row in preview.rows)
        summary = "; ".join(f"{sum(row.status == status for row in preview.rows)} {label}(s)"
                            for status, label in labels.items())
        ctk.CTkLabel(self.win, text=summary + "\nSomente as linhas novas serão acrescentadas.",
                     wraplength=780).grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self.rows_text = ctk.CTkTextbox(self.win, wrap="word")
        self.rows_text.grid(row=1, column=0, sticky="nsew", padx=12)
        contents = []
        for row in preview.rows:
            if row.entry is not None:
                entry = row.entry
                detail = (f"{entry.original_text!r} → {entry.replacement_text!r}; "
                          f"fase={entry.rule_type}; escopo={entry.scope or 'global'}; prioridade={entry.priority}")
            else:
                detail = f"{row.source!r}: {row.message}"
            contents.append(f"{row.line_number}. {labels[row.status]} — {detail}")
        self.rows_text.insert("1.0", "\n\n".join(contents))
        self.rows_text.configure(state="disabled")
        buttons = ctk.CTkFrame(self.win, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=12)

        def confirm():
            if self.closed:
                return
            self.close()
            on_confirm()

        self.cancel_button = ctk.CTkButton(buttons, text="Cancelar", command=self.close)
        self.cancel_button.pack(side="left", padx=(0, 8))
        self.confirm_button = ctk.CTkButton(buttons, text=f"Importar {new_count} nova(s)" if new_count else "Continuar revisão", command=confirm,
                                           state="normal" if new_count or allow_empty else "disabled")
        self.confirm_button.pack(side="left")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _event: self.close())

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.win.destroy()
        self.on_close()


class GlossaryEditorState:
    """Estado mutavel da janela do glossario, em atributos.

    Antes cada um destes campos era um dict de um item so, lido e escrito pelo
    indice: `dirty = {"value": False}` e depois `dirty["value"]` em toda parte.
    Isso nao era estilo — as 49 funcoes aninhadas de `open_glossary_editor`
    precisavam ESCREVER no estado compartilhado, e uma atribuicao simples dentro
    de uma funcao aninhada cria uma variavel local em vez de alterar a de fora.
    Mutar um dict contornava isso porque mutar um objeto nao e atribuir a um
    nome.

    Numa classe o problema nao existe, entao os dicts sairam. E o espelho do
    `EditorState` do editor de traducoes, pela mesma razao que la: separa o
    estado que muda em tempo de execucao (`self.state.dirty`) da arvore de
    widgets (`self.dirty_label`).
    """

    def __init__(self):
        # O glossario como foi carregado do arquivo.
        self.entries = []
        self.snapshot = CatalogSnapshot((), 0)
        self.selected_id = None
        self.selected_revision = None
        self.diagnostics = []
        self.conflicts = {}

        # A lista como esta sendo exibida.
        self.filtered_indices = []
        self.page_index = 0

        # Selection owns identity/revision. Its index is derived for display.
        self.selected_index = None

        # `loading` suprime o marcador de "nao salvo" enquanto o proprio
        # programa preenche o formulario.
        self.dirty = False
        self.loading = False

        # Indice por original, para a validacao a cada tecla. Derivado de
        # `entries`: invalidado junto com ela.
        self.validation_lookup = None

    @property
    def catalog_revision(self):
        return self.snapshot.catalog_revision

    @property
    def selected_index(self):
        return next((i for i, entry in enumerate(self.snapshot.entries)
                     if entry.stable_id == self.selected_id), None)

    @selected_index.setter
    def selected_index(self, index):
        record = self.snapshot.entries[index] if index is not None and 0 <= index < len(self.snapshot.entries) else None
        self.selected_id = record.stable_id if record else None
        self.selected_revision = record.revision if record else None


def duplicate_extras_indices(entries, shown_indices):
    """Excess copies of a complete canonical identity among displayed rows.

    Para cada identidade `(original, substituicao, tipo, escopo)` repetida na
    lista exibida, ficam de fora a PRIMEIRA copia em ordem de arquivo e entram
    as outras. Apagar todas as copias — que e o que "excluir as exibidas" diria
    ao pe da letra com o filtro "Duplicadas", ja que ele mostra cada copia —
    apagaria a regra; a duplicata e o excesso, nao o par. Pura, e devolve os
    indices em `entries`, em ordem.
    """
    vistos = set()
    extras = []
    for index in sorted(shown_indices):
        pair = canonical_identity(entries[index])
        if pair in vistos:
            extras.append(index)
        else:
            vistos.add(pair)
    return extras


class RuleImpactReport:
    """Relatório rolável, selecionável e copiável da fotografia analisada."""

    def __init__(self, parent, report):
        self.win = ctk.CTkToplevel(parent)
        self.win.title("Entender esta regra")
        self.win.geometry("720x560")
        self.win.minsize(450, 300)
        self.win.transient(parent)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)
        ctk.CTkLabel(self.win, text="Análise do rascunho e do texto de teste", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        self.text = ctk.CTkTextbox(self.win, wrap=tk.WORD)
        self.text.grid(row=1, column=0, sticky="nsew", padx=14)
        self.text.insert("1.0", report)
        self.text.configure(state="disabled")
        actions = ctk.CTkFrame(self.win, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="e", padx=14, pady=12)
        ctk.CTkButton(actions, text="Copiar análise", width=130, command=self.copy).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkButton(actions, text="Fechar", width=100, command=self.win.destroy).pack(side=tk.LEFT)
        self.win.bind("<Escape>", lambda _event: self.win.destroy())
        bring_window_to_front(self.win, parent, maximize=False)

    def copy(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.text.get("1.0", "end-1c"))


def show_rule_impact_report(parent, report):
    return RuleImpactReport(parent, report)


class GlossaryEditor:
    """A janela de edicao do glossario.

    Era uma funcao de 985 linhas com 49 funcoes aninhadas, presas ao mesmo
    escopo de closure e escrevendo no estado por dicts de um item so. O outro
    editor passou por isto no item 3.1 do ROADMAP; este ficou para tras, e a
    assimetria aparecia ate de fora: abrir o editor de traducoes devolvia a
    instancia, abrir este devolvia `None`.

    A conversao nao mudou comportamento nenhum: cada funcao virou metodo com o
    mesmo corpo.
    """

    _instances = weakref.WeakSet()

    def __init__(self, app, on_change=None, initial_original=None, initial_replacement=None):
        self.app = app
        self.on_change = on_change
        self.build_state()
        self.build_list_pane()
        self.build_detail_pane()
        self.build_footer()
        self.connect_events()
        self.load_first_entry(initial_original, initial_replacement)
        self._instances.add(self)

    def build_state(self):
        """Janela, configuracoes salvas, estado e variaveis de controle."""
        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title("Editor de Glossário")
        self.win.geometry("1120x700")
        self.win.minsize(1040, 640)

        self.settings = load_settings()
        self.editor_settings = self.settings.get("glossary_editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

        # Restaurar a geometria salva OU maximizar — nunca as duas, que era o que
        # estava escrito aqui e fazia a restauracao perder sempre (o maximizar e
        # agendado e roda depois). Ver `restore_or_maximize`.
        saved_geometry = self.editor_settings.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            saved_geometry = safe_geometry(self.win, saved_geometry)
        restore_or_maximize(self.win, self.app.root, saved_geometry)

        self.state = GlossaryEditorState()
        self.preview_explanation = None
        self.preview_explanation_context = None
        self.import_preview_window = None
        self.catalog = GlossaryCatalog(glossary_catalog_path(), _default_substitutions_path())
        self.row_buttons = []
        self.form_baseline = {
            "orig": "",
            "new": "",
            "type": GLOSSARY_RULE_SUGGESTION,
            "priority": GLOSSARY_PRIORITY_DEFAULT,
            "scope": GLOSSARY_SCOPE_ALL,
        }

        self.search_text = tk.StringVar(master=self.win, value="")
        saved_type_filter = self.editor_settings.get("type_filter", "Todos os tipos")
        self.type_filter_text = tk.StringVar(master=self.win, value=(
            saved_type_filter if saved_type_filter in {"Todos os tipos", *RULE_TYPE_BY_LABEL} else "Todos os tipos"
        ))
        saved_scope_filter = self.editor_settings.get("scope_filter", "Todos os escopos")
        self.scope_filter_text = tk.StringVar(master=self.win, value=(
            saved_scope_filter if saved_scope_filter in SCOPE_FILTERS else "Todos os escopos"
        ))
        saved_priority = self.editor_settings.get("priority_filter", "Todas as prioridades")
        self.priority_filter_text = tk.StringVar(master=self.win, value=(
            saved_priority if isinstance(saved_priority, str) and saved_priority in PRIORITY_FILTERS else "Todas as prioridades"
        ))
        self.test_text_var = tk.StringVar(master=self.win, value="")
        self.sort_text = tk.StringVar(
            master=self.win,
            value=self.editor_settings.get("sort", "Ordem do arquivo"),
        )
        self.rule_type_text = tk.StringVar(
            master=self.win,
            value=rule_type_label(GLOSSARY_RULE_SUGGESTION),
        )
        self.priority_text = tk.StringVar(
            master=self.win, value=str(GLOSSARY_PRIORITY_DEFAULT)
        )
        self.scope_text = tk.StringVar(master=self.win, value="")
        # O padrao declarado pelo arquivo, lido uma vez: e ele que a janela
        # oferece como valor de partida e o que a gravacao preserva.
        self.file_default_scope = glossary_default_scope()

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

    @staticmethod
    def pane_color():
        return "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"

    def apply_pane_color(self, _mode=None):
        try:
            self.main_pane.configure(bg=self.pane_color())
        except tk.TclError:  # a janela ja foi destruida
            pass

    def build_list_pane(self):
        """Painel esquerdo: paginacao, busca, filtros, ordem e a lista."""
        self.main_pane = tk.PanedWindow(
            self.win,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_color(),
        )
        # O `PanedWindow` e Tk puro e nao repinta sozinho quando o tema troca —
        # e agora o tema troca de dentro do programa, pela tela de
        # Configuracoes (28.10), nao so pelo Windows. O mesmo gancho do editor
        # de traducoes, com a mesma tolerancia: sem o registrador, a janela
        # fica com a cor do tema anterior ate ser reaberta.
        try:
            ctk.AppearanceModeTracker.add(self.apply_pane_color, self.win)
        except Exception:  # pragma: no cover - versao sem o registrador
            pass
        self.main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        list_frame = ctk.CTkFrame(self.main_pane, corner_radius=8, width=420)
        self.main_pane.add(list_frame, minsize=340)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(6, weight=1)

        header = ctk.CTkFrame(list_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        header.columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="Glossário", font=ctk.CTkFont(weight="bold")).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.list_count_label = ctk.CTkLabel(header, text="", anchor="e")
        self.list_count_label.grid(row=0, column=1, sticky="e")

        page_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        page_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        page_bar.columnconfigure(1, weight=1)
        self.btn_page_prev = ctk.CTkButton(page_bar, text="< Página", width=92)
        self.btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.page_label = ctk.CTkLabel(page_bar, text="", anchor="center")
        self.page_label.grid(row=0, column=1, sticky="ew")
        self.btn_page_next = ctk.CTkButton(page_bar, text="Página >", width=92)
        self.btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

        search_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        search_bar.columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(
            search_bar,
            textvariable=self.search_text,
            placeholder_text="Buscar texto, tipo ou escopo",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        attach_tooltip(self.search_entry, "Busque sem acentos; combine palavras do original, tradução, tipo e escopo.")
        self.btn_search = ctk.CTkButton(search_bar, text="Buscar", width=82)
        self.btn_search.grid(row=0, column=1, padx=(0, 6))
        self.btn_clear_search = ctk.CTkButton(search_bar, text="Limpar", width=74)
        self.btn_clear_search.grid(row=0, column=2)
        self.btn_clear_filters = ctk.CTkButton(search_bar, text="Limpar filtros", width=105,
                                               command=self.clear_all_filters)
        self.btn_clear_filters.grid(row=0, column=3, padx=(6, 0))
        attach_tooltip(self.btn_clear_filters, "Limpa busca, diagnóstico, tipo e escopo sem descartar a edição.")

        self.filter_segment = ctk.CTkSegmentedButton(
            list_frame,
            values=["Todas", "Duplicadas", "Conflitos", "Inválidas"],
        )
        filtro_salvo = self.editor_settings.get("filter")
        self.filter_segment.set(
            filtro_salvo
            if filtro_salvo in {"Todas", "Duplicadas", "Conflitos", "Inválidas"}
            else "Todas"
        )
        self.filter_segment.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))
        # So com o filtro "Duplicadas" e so quando ha copia a mais na lista
        # (ROADMAP 28.9, item 5): fora disso o botao nao existe, em vez de
        # existir desabilitado explicando uma condicao. `grid_remove` guarda a
        # posicao; ele volta na mesma linha, entre o filtro e a ordem.
        self.btn_delete_shown_duplicates = ctk.CTkButton(
            list_frame,
            text="",
            fg_color=DESTRUCTIVE_COLOR,
            hover_color=DESTRUCTIVE_HOVER_COLOR,
            command=self.delete_shown_duplicates,
        )
        self.btn_delete_shown_duplicates.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.btn_delete_shown_duplicates.grid_remove()

        sort_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        sort_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))
        sort_bar.columnconfigure(1, weight=1)
        ctk.CTkLabel(sort_bar, text="Ordem").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.sort_menu = ctk.CTkOptionMenu(
            sort_bar,
            variable=self.sort_text,
            values=["Ordem do arquivo", "Original A-Z", "Substituição A-Z", "Maior original",
                    "Maior prioridade", "Menor prioridade"],
        )
        self.sort_menu.grid(row=0, column=1, sticky="ew")
        self.type_filter_menu = ctk.CTkOptionMenu(
            sort_bar, variable=self.type_filter_text,
            values=["Todos os tipos", *RULE_TYPE_BY_LABEL], width=130,
        )
        self.type_filter_menu.grid(row=0, column=2, sticky="e", padx=(6, 0))
        self.scope_filter_menu = ctk.CTkOptionMenu(sort_bar, variable=self.scope_filter_text,
                                                  values=list(SCOPE_FILTERS))
        self.scope_filter_menu.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        self.priority_filter_menu = ctk.CTkOptionMenu(sort_bar, variable=self.priority_filter_text,
                                                     values=list(PRIORITY_FILTERS))
        self.priority_filter_menu.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        self.counts_label = ctk.CTkLabel(list_frame, text="", anchor="w")
        self.counts_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.rows_frame = ctk.CTkScrollableFrame(list_frame, height=420)
        self.rows_frame.grid(row=6, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def build_detail_pane(self):
        """Painel direito: o formulario, o aviso de conflito e o teste rapido."""
        detail_frame = ctk.CTkFrame(self.main_pane, corner_radius=8)
        self.main_pane.add(detail_frame, minsize=620)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(1, weight=1)
        detail_frame.rowconfigure(3, weight=1)
        detail_frame.rowconfigure(10, weight=1)

        ctk.CTkLabel(detail_frame, text="Texto encontrado:").grid(
            row=0,
            column=0,
            sticky="w",
            padx=10,
            pady=(10, 2),
        )
        # A letra dos dois textos, com `Ctrl+roda` e `Ctrl+±` como no outro
        # editor (ROADMAP 28.9, item 5); o tamanho e lembrado.
        tamanho = self.editor_settings.get("font_size", 12)
        if not isinstance(tamanho, int) or isinstance(tamanho, bool):
            tamanho = 12
        self.font_size = max(9, min(24, tamanho))
        self.text_font = ctk.CTkFont(size=self.font_size)
        self.orig_text = ctk.CTkTextbox(
            detail_frame, height=120, wrap=tk.WORD, font=self.text_font
        )
        self.orig_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        ctk.CTkLabel(detail_frame, text="Substituir por:").grid(
            row=2,
            column=0,
            sticky="w",
            padx=10,
            pady=(0, 2),
        )
        self.new_text = ctk.CTkTextbox(
            detail_frame, height=120, wrap=tk.WORD, font=self.text_font
        )
        self.new_text.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 8))

        type_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
        type_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))
        type_bar.columnconfigure(4, weight=1)
        ctk.CTkLabel(type_bar, text="Tipo:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.type_menu = ctk.CTkOptionMenu(
            type_bar,
            variable=self.rule_type_text,
            values=[rule_type_label(rule_type) for rule_type in GLOSSARY_RULE_TYPES],
            width=160,
        )
        self.type_menu.grid(row=0, column=1, sticky="w")
        attach_tooltip(
            self.type_menu,
            "Limpeza: altera o original antes de traduzir.\n"
            "Sugestão: oferece uma opção ao revisor ou modelo.\n"
            "Automática: aplica a substituição depois da tradução.",
        )

        # Campo de texto, e nao um seletor de valores: a prioridade e um inteiro
        # qualquer no arquivo, e um `Substituicoes.txt` editado a mao pode trazer
        # um valor fora de qualquer faixa que a janela oferecesse. Um seletor
        # teria de escolher entre esconder esse valor ou troca-lo — o campo
        # mostra o que esta la, e o que nao for inteiro vira aviso de validacao.
        ctk.CTkLabel(type_bar, text="Prioridade:").grid(
            row=0, column=2, sticky="w", padx=(16, 6)
        )
        self.priority_entry = ctk.CTkEntry(
            type_bar,
            textvariable=self.priority_text,
            width=70,
            justify="center",
        )
        self.priority_entry.grid(row=0, column=3, sticky="w")
        attach_tooltip(self.priority_entry, "Maior prioridade vence; com 0, o comprimento decide.")
        presets = ctk.CTkFrame(type_bar, fg_color="transparent")
        presets.grid(row=0, column=4, sticky="w", padx=(8, 0))
        self.priority_preset_buttons = {}
        for label, value, caption in (("Baixa (-1)", -1, "Baixa"), ("Normal (0)", 0, "Normal"), ("Alta (+1)", 1, "Alta")):
            button = ctk.CTkButton(presets, text=caption, width=60, height=24,
                                   command=lambda priority=value: self.set_priority(priority))
            button.pack(side=tk.LEFT, padx=(0, 6))
            attach_tooltip(button, f"{label}: define a prioridade; valores maiores ainda podem prevalecer.")
            self.priority_preset_buttons[label] = button
        self.type_help_label = ctk.CTkLabel(type_bar, text="", text_color=MUTED_TEXT_COLOR, anchor="w")
        self.type_help_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(2, 0))
        self.refresh_type_help()

        # Campo de texto pelo mesmo motivo da prioridade: o escopo aceita um
        # codigo de idioma, um par (`en>pt`) ou `*`, e um arquivo editado a mao
        # pode trazer um valor que nenhum seletor previa. Mostrar o que esta la e
        # deixar a validacao avisar e melhor do que esconder ou trocar.
        scope_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
        scope_bar.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 8))
        scope_bar.columnconfigure(2, weight=1)
        ctk.CTkLabel(scope_bar, text="Idioma:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.scope_entry = ctk.CTkEntry(
            scope_bar,
            textvariable=self.scope_text,
            width=110,
            justify="center",
        )
        self.scope_entry.grid(row=0, column=1, sticky="w")
        padrao = self.file_default_scope or "todos"
        attach_tooltip(self.scope_entry, f"Destino ou par 'en>pt'; '*' = todos; padrão do arquivo: {padrao}.")
        scope_presets = ctk.CTkFrame(scope_bar, fg_color="transparent")
        scope_presets.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.scope_preset_buttons = {}
        for label, value in (("Todos", "all"), ("Destino atual", "target"), ("Par atual", "pair")):
            button = ctk.CTkButton(scope_presets, text=label, width=105, height=24,
                                   command=lambda selection=value: self.apply_scope_preset(selection))
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.scope_preset_buttons[label] = button
        selectors = ctk.CTkFrame(scope_bar, fg_color="transparent")
        selectors.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        labels = ["Todos", "Personalizado"] + [name for name, _ in LANGUAGES]
        self.scope_source_var = tk.StringVar(master=self.win, value="Todos")
        self.scope_target_var = tk.StringVar(master=self.win, value="Todos")
        ctk.CTkLabel(selectors, text="Origem:").pack(side=tk.LEFT, padx=(0, 4))
        self.scope_source_menu = ctk.CTkOptionMenu(selectors, variable=self.scope_source_var, values=labels, width=115,
                                                  command=lambda _value: self.apply_scope_selectors())
        self.scope_source_menu.pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkLabel(selectors, text="Destino:").pack(side=tk.LEFT, padx=(0, 4))
        self.scope_target_menu = ctk.CTkOptionMenu(selectors, variable=self.scope_target_var, values=labels, width=115,
                                                  command=lambda _value: self.apply_scope_selectors())
        self.scope_target_menu.pack(side=tk.LEFT, padx=(0, 8))
        self.scope_help_label = ctk.CTkLabel(selectors, text=describe_scope(self.scope_text.get()),
                                             text_color=MUTED_TEXT_COLOR, anchor="w")
        self.scope_help_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.validation_label = ctk.CTkLabel(
            detail_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=OK_COLOR,
        )
        self.validation_label.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))

        # So aparece quando a entrada selecionada disputa um padrao com outra. Fora
        # disso a barra sai do grid, para nao ocupar espaco permanente com nada.
        self.conflict_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
        self.conflict_bar.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.conflict_bar.columnconfigure(0, weight=1)
        self.conflict_label = ctk.CTkLabel(
            self.conflict_bar,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=WARNING_COLOR,
            wraplength=460,
        )
        self.conflict_label.grid(row=0, column=0, sticky="ew")
        # Duas saidas para o mesmo conflito, e a ordem na barra e a ordem em que
        # convem tenta-las: priorizar nao apaga nada e da para desfazer mudando
        # um numero; manter remove as concorrentes do arquivo.
        self.btn_promote_conflict = ctk.CTkButton(
            self.conflict_bar, text="Priorizar esta", width=120
        )
        self.btn_promote_conflict.grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.btn_keep_conflict = ctk.CTkButton(self.conflict_bar, text="Manter esta", width=110)
        attach_tooltip(
            self.btn_promote_conflict,
            "Esta regra passa a vencer as concorrentes; nenhuma é apagada (S10)",
        )
        attach_tooltip(
            self.btn_keep_conflict,
            "Esta regra fica e as concorrentes são APAGADAS do glossário",
        )
        self.btn_keep_conflict.grid(row=0, column=2, sticky="e", padx=(6, 0))
        self.conflict_bar.grid_remove()

        test_header = ctk.CTkFrame(detail_frame, fg_color="transparent")
        test_header.grid(row=8, column=0, sticky="ew", padx=10, pady=(0, 2))
        test_header.columnconfigure(1, weight=1)
        ctk.CTkLabel(test_header, text="Teste rápido:").grid(row=0, column=0, sticky="w")
        self.preview_status_label = ctk.CTkLabel(test_header, text="", text_color=MUTED_TEXT_COLOR, anchor="w")
        self.preview_status_label.grid(row=0, column=1, sticky="ew", padx=(8, 4))
        self.btn_apply_preview = ctk.CTkButton(test_header, text="Aplicar selecionada", width=140)
        self.btn_apply_preview.grid(row=0, column=2, sticky="e")
        self.btn_apply_all_preview = ctk.CTkButton(test_header, text="Aplicar todas", width=110)
        self.btn_apply_all_preview.grid(row=0, column=3, sticky="e", padx=(6, 0))
        self.btn_preview_details = ctk.CTkButton(test_header, text="Ver regras", width=95,
                                                  state="disabled", command=self.show_preview_explanation)
        self.btn_preview_details.grid(row=0, column=4, sticky="e", padx=(6, 0))

        test_row = ctk.CTkFrame(detail_frame, fg_color="transparent")
        test_row.grid(row=9, column=0, sticky="ew", padx=10, pady=(0, 6))
        test_row.columnconfigure(0, weight=1)
        self.test_input = ctk.CTkEntry(
            test_row,
            textvariable=self.test_text_var,
            placeholder_text="Digite ou cole uma frase para testar a substituição selecionada",
        )
        self.test_input.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_clear_preview = ctk.CTkButton(test_row, text="Limpar", width=70, command=self.clear_preview)
        self.btn_clear_preview.grid(row=0, column=1, padx=(0, 6))
        self.btn_copy_preview = ctk.CTkButton(test_row, text="Copiar resultado", width=115, command=self.copy_preview)
        self.btn_copy_preview.grid(row=0, column=2)
        self.btn_compare_draft = ctk.CTkButton(test_row, text="Comparar edição", width=130,
                                               command=self.compare_draft_preview)
        self.btn_compare_draft.grid(row=0, column=3, padx=(6, 0))
        attach_tooltip(self.test_input, "Ctrl+T: focar teste rápido; Ctrl+Shift+T: limpar o texto.")

        self.preview_text = ctk.CTkTextbox(detail_frame, height=90, wrap=tk.WORD)
        self.preview_text.grid(row=10, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview_text.configure(state="disabled")
        self.btn_rule_impact = ctk.CTkButton(
            detail_frame, text="Entender esta regra", width=160, command=self.explain_current_rule,
        )
        self.btn_rule_impact.grid(row=11, column=0, sticky="w", padx=10, pady=(0, 8))
        attach_tooltip(self.btn_rule_impact, "Compara o rascunho com o catálogo carregado e o texto de teste, sem salvar.")
        self.btn_compare_pending = ctk.CTkButton(
            detail_frame, text="Comparar pendentes", width=160,
            command=lambda: self.compare_draft_preview(database=True),
        )
        self.btn_compare_pending.grid(row=11, column=0, sticky="e", padx=10, pady=(0, 8))
        attach_tooltip(self.btn_compare_pending, "Compara o catálogo e a edição nas traduções pendentes, sem gravar.")

    def build_footer(self):
        """Rodape: mensagens, indicador de alteracoes e a barra de acoes."""
        footer = ctk.CTkFrame(self.win, corner_radius=8)
        footer.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        footer.columnconfigure(0, weight=1)

        status_line = ctk.CTkFrame(footer, fg_color="transparent")
        status_line.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        self.msg_label = ctk.CTkLabel(status_line, text="", text_color=OK_COLOR)
        self.msg_label.pack(side=tk.LEFT)
        self.dirty_label = ctk.CTkLabel(status_line, text="Salvo", text_color=OK_COLOR)
        self.dirty_label.pack(side=tk.LEFT, padx=(12, 0))
        self.file_label = ctk.CTkLabel(status_line, text="", text_color=MUTED_TEXT_COLOR)
        self.file_label.pack(side=tk.LEFT, padx=(12, 0))

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))
        action_specs = [
            ("Nova entrada", 120),
            ("Salvar", 100),
            ("Salvar como nova", 140),
            ("Excluir", 100),
            ("Deduplicar", 110),
            ("Backup", 100),
            ("Recarregar", 110),
            ("Exportar CSV", 120),
            ("Importar CSV", 120),
            ("Restaurar backup", 140),
        ]
        self.buttons = {}
        for column, (text, width) in enumerate(action_specs):
            button = ctk.CTkButton(actions, text=text, width=width)
            row = column // 5
            col = column % 5
            button.grid(row=row, column=col, sticky="ew", padx=(0, 6), pady=2)
            actions.columnconfigure(col, weight=1)
            self.buttons[text] = button

    def connect_events(self):
        self._language_traces = []
        for name in ("source_language", "target_language"):
            variable = getattr(self.app, name, None)
            if hasattr(variable, "trace_add"):
                token = variable.trace_add("write", self.refresh_pair_filter)
                self._language_traces.append((variable, token))
        self.win.bind("<Destroy>", self.remove_language_traces, add="+")
        """Liga os comandos, os atalhos e o fechamento da janela."""
        self.buttons["Nova entrada"].configure(command=self.new_entry)
        self.buttons["Salvar"].configure(command=self.save_current)
        self.buttons["Salvar como nova"].configure(command=self.save_as_new)
        self.buttons["Excluir"].configure(command=self.delete_current)
        self.buttons["Deduplicar"].configure(command=self.deduplicate_entries)
        self.buttons["Backup"].configure(command=self.create_backup_now)
        self.buttons["Recarregar"].configure(command=self.reload_all)
        self.buttons["Exportar CSV"].configure(command=self.export_csv)
        self.buttons["Importar CSV"].configure(command=self.import_csv)
        self.buttons["Restaurar backup"].configure(command=self.restore_backup)
        self.btn_page_prev.configure(command=lambda: self.change_page(-1))
        self.btn_page_next.configure(command=lambda: self.change_page(1))
        self.btn_search.configure(command=self.apply_search)
        self.btn_clear_search.configure(command=self.clear_search)
        self.btn_keep_conflict.configure(command=self.keep_this_rule, state="disabled")
        self.btn_promote_conflict.configure(command=self.promote_this_rule)
        self.priority_text.trace_add("write", lambda *_a: self.mark_dirty())
        self.scope_text.trace_add("write", self._scope_changed)
        self.rule_type_text.trace_add("write", self._type_changed)
        self.test_text_var.trace_add("write", lambda *_a: self.refresh_preview())
        self.btn_apply_preview.configure(command=self.refresh_preview)
        self.btn_apply_all_preview.configure(command=self.apply_all_to_preview)
        self.sort_menu.configure(command=self.restart_at_first_page)
        self.type_filter_menu.configure(command=self.restart_at_first_page)
        self.scope_filter_menu.configure(command=self.restart_at_first_page)
        self.priority_filter_menu.configure(command=self.restart_at_first_page)
        self.filter_segment.configure(command=self.restart_at_first_page)
        self.search_entry.bind("<Return>", lambda _event: self.apply_search())
        self.orig_text.bind(
            "<<Modified>>",
            lambda event: (self.orig_text.edit_modified(False), self.mark_dirty())[1],
        )
        self.new_text.bind(
            "<<Modified>>",
            lambda event: (self.new_text.edit_modified(False), self.mark_dirty())[1],
        )
        self.win.bind("<Control-s>", lambda _event: (self.save_current(), "break")[1])
        self.win.bind("<Control-S>", lambda _event: (self.save_current(), "break")[1])
        self.win.bind("<Control-n>", lambda _event: (self.new_entry(), "break")[1])
        self.win.bind("<Control-N>", lambda _event: (self.new_entry(), "break")[1])
        self.win.bind("<Control-t>", lambda _event: self.focus_preview())
        self.win.bind("<Control-Shift-T>", lambda _event: self.clear_preview_shortcut())
        # A paridade minima com o editor de traducoes (ROADMAP 22.12). Este
        # editor ligava dois atalhos contra os treze do outro, e os que faltavam
        # sao os do fluxo de quem varre uma lista: achar, andar e virar pagina.
        # O resto do que o outro tem (voltar, campo de pagina, selecao em lote)
        # continua de fora — ver a secao 10 da SPEC.
        self.win.bind("<Control-l>", self.focus_search)
        self.win.bind("<Control-L>", self.focus_search)
        self.win.bind("<Alt-Left>", lambda _event: (self.step_entry(-1), "break")[1])
        self.win.bind("<Alt-Right>", lambda _event: (self.step_entry(1), "break")[1])
        self.win.bind("<Control-Prior>", lambda _event: (self.change_page(-1), "break")[1])
        self.win.bind("<Control-Next>", lambda _event: (self.change_page(1), "break")[1])
        # Zoom dos dois textos, as mesmas tres teclas e a roda do outro editor.
        self.win.bind("<Control-plus>", lambda _event: (self.adjust_font(1), "break")[1])
        self.win.bind("<Control-equal>", lambda _event: (self.adjust_font(1), "break")[1])
        self.win.bind("<Control-minus>", lambda _event: (self.adjust_font(-1), "break")[1])
        self.win.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.win.protocol("WM_DELETE_WINDOW", self.close_editor)

    def load_first_entry(self, initial_original=None, initial_replacement=None):
        """Primeira carga: a lista, e a entrada pre-preenchida quando ha uma."""
        has_initial_entry = bool(
            (initial_original or "").strip() or (initial_replacement or "").strip()
        )
        self.reload_all(select_first=not has_initial_entry)
        if has_initial_entry:
            self.start_prefilled_entry(initial_original, initial_replacement)
        self.win.after(100, self.restore_pane_position)

    def show_message(self, text, color=OK_COLOR):
        # Sem tempo fixo: ele vem do tamanho do texto (ROADMAP 22.6). Eram 1.800
        # ms para qualquer mensagem, e as desta janela variam de "Salvo" a frases
        # que nomeiam a regra em conflito.
        flash_message(self.msg_label, self.win, text, text_color=color)

    def adjust_font(self, delta):
        self.font_size = max(9, min(24, self.font_size + delta))
        self.text_font.configure(size=self.font_size)
        self.save_editor_settings()

    def zoom_with_wheel(self, event):
        """Um entalhe da roda vale um ponto, como no editor de traducoes."""
        self.adjust_font(1 if getattr(event, "delta", 0) > 0 else -1)
        return "break"

    def save_editor_settings(self):
        save_window_section(
            self.settings,
            "glossary_editor",
            {
                "filter": self.filter_segment.get(),
                "sort": self.sort_text.get(),
                "type_filter": self.type_filter_text.get(),
                "scope_filter": self.scope_filter_text.get(),
                "priority_filter": self.priority_filter_text.get(),
                "font_size": self.font_size,
            },
            window=self.win,
            sashes=(("main_sash_x", self.main_pane, 0),),
        )

    def restore_pane_position(self):
        restore_sash(self.main_pane, self.editor_settings.get("main_sash_x"), 360, 520)

    def update_app_glossary(self):
        self.app.glossary_substitutions = load_interactive_substitutions()
        if hasattr(self.app, "log_message"):
            self.app.log_message(
                f"Glossário atualizado: {len(self.app.glossary_substitutions)} entradas"
            )
        for callback in list(getattr(self.app, "glossary_change_callbacks", [])):
            callback(self.app.glossary_substitutions)
        if self.on_change is not None:
            self.on_change(self.app.glossary_substitutions)

    def text_value(self, widget):
        return widget.get("1.0", tk.END).rstrip("\n")

    def set_text(self, widget, value):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        try:
            widget.edit_modified(False)
        except tk.TclError:
            pass

    def current_pair(self):
        return self.text_value(self.orig_text), self.text_value(self.new_text)

    def current_rule_type(self):
        return rule_type_value(self.rule_type_text.get())

    def set_rule_type(self, rule_type):
        self.rule_type_text.set(rule_type_label(glossary_entry_type((None, None, rule_type))))

    def refresh_type_help(self):
        examples = {
            GLOSSARY_RULE_CLEANUP: "Limpeza: antes de traduzir; por exemplo, remover um marcador.",
            GLOSSARY_RULE_SUGGESTION: "Sugestão: oferece uma opção ao revisor ou modelo.",
            GLOSSARY_RULE_AUTOMATIC: "Automática: substitui depois de traduzir; por exemplo, rook → torre.",
        }
        self.type_help_label.configure(text=examples[self.current_rule_type()])

    def _type_changed(self, *_args):
        self.refresh_type_help()
        self.mark_dirty()

    def current_priority(self):
        """A prioridade digitada, ou `None` se o texto nao for um inteiro.

        `None` e um estado legitimo do formulario, e nao um erro a esconder: o
        campo esta vazio ou tem lixo, a validacao avisa e "Salvar" recusa. Cair
        para zero em silencio gravaria uma decisao que o usuario nao tomou.
        """
        texto = self.priority_text.get().strip()
        if not texto:
            return None
        try:
            return int(texto)
        except ValueError:
            return None

    def set_priority(self, priority):
        self.priority_text.set(str(normalize_glossary_priority(priority)))

    def apply_scope_preset(self, selection):
        source, target = self.preview_languages()
        if selection == "all":
            self.scope_text.set("*")
        elif selection == "target" and target:
            self.scope_text.set(target)
        elif selection == "pair" and source and target:
            self.scope_text.set(f"{source}>{target}")
        else:
            self.show_message("Declare os idiomas necessários na janela principal.", WARNING_COLOR)

    def _scope_changed(self, *_args):
        codes = scope_to_codes(self.scope_text.get())
        names = {code: name for name, code in LANGUAGES}
        if codes is None:
            self.scope_source_var.set("Personalizado")
            self.scope_target_var.set("Personalizado")
        else:
            self.scope_source_var.set(names.get(codes[0], "Todos"))
            self.scope_target_var.set(names.get(codes[1], "Todos"))
        self.scope_help_label.configure(text=describe_scope(self.scope_text.get()))
        self.mark_dirty()

    def apply_scope_selectors(self):
        source = self.scope_source_var.get()
        target = self.scope_target_var.get()
        if "Personalizado" in (source, target):
            self.show_message("Ajuste o escopo avançado ou escolha Todos antes de usar os seletores.", WARNING_COLOR)
            self._scope_changed()
            return
        codes = {name: code for name, code in LANGUAGES}
        if source not in ("Todos", *codes) or target not in ("Todos", *codes):
            self._scope_changed()
            return
        self.scope_text.set(scope_from_codes(codes.get(source, ""), codes.get(target, "")))

    def current_scope(self):
        """O escopo digitado, ja canonico.

        Diferente da prioridade, aqui nao ha estado invalido: campo vazio e `'*'`
        querem dizer a mesma coisa ("todo par"), e um codigo desconhecido e
        preservado para que a validacao possa avisar em vez de o programa
        adivinhar.
        """
        return normalize_glossary_scope(self.scope_text.get())

    def persistible_draft(self, orig, new, rule_type, priority, scope):
        """Return the normalized draft or explain why it cannot be stored."""
        if priority is None:
            self.show_message(INVALID_PRIORITY_WARNING, ERROR_COLOR)
            return None
        try:
            return validate_entry_draft(
                GlossaryEntryDraft(orig, new, rule_type, scope, priority)
            )
        except ValueError as exc:
            self.show_message(str(exc), ERROR_COLOR)
            return None

    def set_scope(self, scope):
        """Mostra o escopo, escrevendo `'*'` quando ele contraria o padrao.

        Campo vazio significaria "herda o padrao", e para uma regra global num
        arquivo que declara `escopo = 'pt'` isso seria o oposto do que ela diz.
        """
        scope = normalize_glossary_scope(scope)
        if not scope and self.file_default_scope:
            self.scope_text.set(GLOSSARY_SCOPE_ANY)
        else:
            self.scope_text.set(scope)

    def set_form_baseline(
        self, orig="", new="", rule_type=None, priority=None, scope=None
    ):
        self.form_baseline["orig"] = orig or ""
        self.form_baseline["new"] = new or ""
        self.form_baseline["type"] = rule_type or GLOSSARY_RULE_SUGGESTION
        self.form_baseline["priority"] = normalize_glossary_priority(priority)
        self.form_baseline["scope"] = normalize_glossary_scope(scope)
        self.form_baseline["stable_id"] = self.state.selected_id
        self.form_baseline["revision"] = self.state.selected_revision
        self.form_baseline["catalog_revision"] = self.state.catalog_revision

    def form_changed(self):
        orig, new = self.current_pair()
        return (
            orig != self.form_baseline["orig"]
            or new != self.form_baseline["new"]
            or self.current_rule_type() != self.form_baseline["type"]
            or self.current_priority() != self.form_baseline["priority"]
            or self.current_scope() != self.form_baseline["scope"]
        )

    def set_dirty(self, value):
        self.state.dirty = value
        self.dirty_label.configure(
            text="Alterações não salvas" if value else "Salvo",
            text_color=WARNING_COLOR if value else OK_COLOR,
        )
        self.refresh_validation()

    def mark_dirty(self, _event=None):
        if not self.state.loading:
            self.set_dirty(self.form_changed())
            self.refresh_preview()

    def preview_languages(self):
        """O par com que a previa avalia o escopo (garantia S11).

        Sai da janela principal, que e onde o par de uma traducao e escolhido.
        Sem ele — um `app` de teste, ou uma versao futura sem esses seletores —
        `None` desliga o filtro por escopo, que e o comportamento de sempre.
        """
        def valor(nome):
            variavel = getattr(self.app, nome, None)
            try:
                return variavel.get() or None
            except AttributeError:
                return None

        return valor("source_language"), valor("target_language")

    def preview_rules(self, entries):
        """As regras que o PIPELINE tiraria destas entradas (ROADMAP 22.12).

        A previa usava os pares crus, e por isso divergia da aplicacao real em
        tres pontos: a prioridade era descartada (com uma regra promovida por
        "Priorizar esta", a previa dava um resultado e o pipeline outro — a
        previa contradizia o banner de conflito exibido ao lado dela, garantia
        S9), o escopo era ignorado e o `@casa@` ficava inerte, casando nada.
        """
        return interactive_rules_from_entries(entries, *self.preview_languages())

    def refresh_preview(self):
        """A previa da regra ABERTA, com a conversao de verdade.

        A entrada e montada dos campos do formulario, e nao lida do arquivo: o
        proposito do teste rapido e experimentar o que ainda nao foi salvo.

        `apply_all_substitutions` com uma regra so, e nao `apply_substitution`:
        o pipeline troca TODAS as ocorrencias, e a previa trocava apenas a
        primeira — num paragrafo com tres "bishop" ela mostrava um resultado que
        nunca aconteceria.
        """
        self.preview_explanation = None
        self.preview_explanation_context = None
        self.btn_preview_details.configure(state="disabled")
        orig, new = self.current_pair()
        sample = self.test_text_var.get()
        if not orig:
            self.set_preview_text(sample, "Informe uma regra" if sample else "Digite um texto")
            return

        entrada = (
            orig,
            new,
            self.current_rule_type(),
            self.current_priority() or 0,
            self.current_scope(),
        )
        regras = filter_glossary_entries_by_type([entrada], self.current_rule_type(), *self.preview_languages())
        source, target = self.preview_languages()
        if not scope_matches(self.current_scope(), source, target):
            self.set_preview_text(sample, "Fora do escopo atual")
            return
        if self.current_priority() is None:
            self.set_preview_text(sample, "Prioridade inválida")
            return
        self.set_preview_text(
            (clean_comment_for_translation(sample, regras) if self.current_rule_type() == GLOSSARY_RULE_CLEANUP
             else apply_all_substitutions(sample, regras)) if regras else sample
        )

    def apply_all_to_preview(self):
        context = (self.test_text_var.get(), list(self.preview_rules(self.state.entries)))
        explanation = explain_substitutions(*context)
        self.preview_explanation = explanation
        self.preview_explanation_context = context
        self.btn_preview_details.configure(state="normal" if explanation.matches else "disabled")
        count = len(explanation.matches)
        rules = {(m.pattern, m.configured_replacement, m.priority) for m in explanation.matches}
        self.set_preview_text(explanation.text, f"{count} ocorrência(s), {len(rules)} regra(s)")

    def show_preview_explanation(self):
        context = self.preview_explanation_context
        if context is None:
            return

        def work(task):
            try:
                return explain_substitutions(*context, include_suppressed=True, should_cancel=task.cancelado)
            except SimulationCanceled as exc:
                raise TaskCanceled() from exc

        def done(explanation):
            if self.preview_explanation_context is context:
                messagebox.showinfo("Regras aplicadas", format_explanation(explanation), parent=self.win)

        run_with_progress(self.win, "Analisar regras", work, on_success=done,
                          on_error=lambda error: messagebox.showerror(
                              "Analisar regras", f"Não foi possível analisar: {error}", parent=self.win),
                          message="Analisando regras concorrentes…")

    def explain_current_rule(self):
        """Analisa uma fotografia do formulário sem alterar o catálogo."""
        orig, replacement = self.current_pair()
        draft = (orig, replacement, self.current_rule_type(), self.current_priority(), self.current_scope())
        entries = list(self.state.entries)
        selected = self.state.selected_index
        sample = self.test_text_var.get()
        source, target = self.preview_languages()

        def work(task):
            try:
                return analyze_rule(draft, entries, selected, sample, source, target, should_cancel=task.cancelado)
            except SimulationCanceled as exc:
                raise TaskCanceled() from exc

        def done(result):
            show_rule_impact_report(self.win, format_rule_impact(result))

        run_with_progress(self.win, "Entender esta regra", work, on_success=done,
                          on_error=lambda _error: messagebox.showerror(
                              "Entender esta regra", "Não foi possível concluir a análise.", parent=self.win),
                          message="Analisando a regra e o catálogo carregado…")

    def compare_draft_preview(self, *, database=False):
        """Compara a entrada aberta com o catálogo usando apenas o texto de teste."""
        orig, replacement = self.current_pair()
        priority = self.current_priority()
        source, target = self.preview_languages()
        sample = self.test_text_var.get()
        if not orig or priority is None or (not database and not sample) or not target:
            message = ("Informe regra, prioridade e idioma de destino." if database else
                       "Informe regra, prioridade, texto de teste e idioma de destino.")
            self.show_message(message, WARNING_COLOR)
            return
        before = list(self.state.entries)
        after = list(before)
        entry = (orig, replacement, self.current_rule_type(), priority, self.current_scope())
        index = self.state.selected_index
        if index is None:
            after.append(entry)
        else:
            after[index] = entry
        def work(task):
            try:
                if database:
                    return simulate_database_rule_change(
                        self.app.output_db, before, after, target_language=target,
                        source_language=source, should_cancel=task.cancelado,
                        progress_callback=task.report,
                    )
                return simulate_rule_change([SimulationItem(sample, source, target)], before, after,
                                            should_cancel=task.cancelado)
            except SimulationCanceled as exc:
                raise TaskCanceled() from exc

        def done(result):
            if database:
                text = format_simulation_summary(result)
                text += (f"\nDestino {target}"
                         + (f" e origem {source}." if source else "; todas as origens foram consideradas."))
                if result.examples:
                    text += "\n\n" + format_simulation_examples(result)
            elif result.examples:
                text = format_simulation_examples(result)
            else:
                text = "A edição não altera o resultado automático deste texto no par escolhido."
            if entry[2] != GLOSSARY_RULE_AUTOMATIC:
                text += ("\n\nA regra editada não é automática; a comparação mostra somente "
                         "seus efeitos sobre o conjunto de regras automáticas, inclusive uma possível remoção.")
            text += "\n\nComparação somente das regras automáticas do catálogo; não inclui regras de semente ou limpeza."
            if database:
                text += " As regras são reaplicadas aos textos já armazenados; traduções futuras podem ser diferentes."
            messagebox.showinfo("Comparar edição", text, parent=self.win)

        run_with_progress(self.win, "Comparar edição", work, on_success=done,
                          on_error=lambda error: messagebox.showerror(
                              "Comparar edição", f"Não foi possível comparar: {error}", parent=self.win),
                          message="Comparando regras automáticas…")

    def set_preview_text(self, value, status=None):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", value)
        sample = self.test_text_var.get()
        if sample != value and max(len(sample), len(value)) <= 2000 and all(ord(c) <= 0xFFFF for c in sample + value):
            _before, after = diff_spans(sample, value)
            dark = ctk.get_appearance_mode() == "Dark"
            self.preview_text.tag_config("preview_change", background="#14532d" if dark else "#bbf7d0",
                                         foreground="#ffffff" if dark else "#111827")
            for start, end in after:
                self.preview_text.tag_add("preview_change", f"1.0+{start}c", f"1.0+{end}c")
        self.preview_text.configure(state="disabled")
        self.preview_status_label.configure(text=status or ("Texto alterado" if sample != value else "Sem alteração"))

    def clear_preview(self):
        self.test_text_var.set("")

    def clear_preview_shortcut(self):
        self.clear_preview()
        return "break"

    def focus_preview(self):
        self.test_input.focus_set()
        return "break"

    def copy_preview(self):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self.preview_text.get("1.0", "end-1c"))
            self.show_message("Resultado copiado.")
        except tk.TclError:
            self.show_message("Não foi possível copiar o resultado.", ERROR_COLOR)

    def refresh_validation(self):
        orig, new = self.current_pair()
        current_index = self.state.selected_index
        warnings = validate_glossary_entry(
            orig,
            new,
            current_index=current_index,
            rule_type=self.current_rule_type(),
            scope=self.current_scope(),
            existing_lookup=self.current_validation_lookup(),
        )
        if self.current_priority() is None:
            warnings.append(INVALID_PRIORITY_WARNING)
        if warnings:
            self.validation_label.configure(
                text="Avisos: " + " | ".join(warnings),
                text_color=WARNING_COLOR,
            )
        elif orig or new:
            self.validation_label.configure(text="Entrada válida", text_color=OK_COLOR)
        else:
            self.validation_label.configure(text="", text_color=OK_COLOR)
        self.refresh_preview()

    def refresh_conflict(self):
        """Diz qual regra do conflito o programa aplica (garantia S9).

        Descreve a entrada **como esta no arquivo**, nao o que esta no
        formulario: quem vence depende da posicao no glossario e do tipo
        gravados, e o texto sendo digitado ainda nao e nenhum dos dois.
        """
        index = self.state.selected_index
        complete = (index is not None and self.form_baseline.get("stable_id") == self.state.selected_id
                    and self.form_baseline.get("revision") == self.state.selected_revision)
        self.buttons["Excluir"].configure(state="normal" if complete else "disabled")
        self.buttons["Salvar"].configure(state="normal" if complete or (self.state.selected_id is None and self.state.catalog_revision > 0) else "disabled")
        for label in ("Salvar como nova", "Deduplicar", "Importar CSV", "Restaurar backup", "Backup"):
            self.buttons[label].configure(state="normal" if self.state.catalog_revision > 0 else "disabled")
        self.btn_promote_conflict.configure(state="normal" if complete else "disabled")
        message = ""
        if index is not None and 0 <= index < len(self.state.entries):
            message = describe_glossary_conflict(self.state.entries, index, self.state.conflicts)

        if message:
            self.conflict_label.configure(text=message)
            self.conflict_bar.grid()
        else:
            self.conflict_label.configure(text="")
            self.conflict_bar.grid_remove()

    def keep_this_rule(self):
        """Bulk changes require a dedicated atomic catalog operation."""
        self.show_message("Ação indisponível até a operação atômica do catálogo.", WARNING_COLOR)
        return None

    def promote_this_rule(self):
        """Resolve o conflito pela prioridade, sem apagar nada (ROADMAP 1.5).

        "Manter esta" tambem faz esta regra vencer, mas removendo as outras do
        arquivo — uma decisao que nao da para revisar depois, porque o que foi
        descartado nao esta mais la. Aqui as duas regras continuam existindo e a
        escolha e um numero no glossario.
        """
        index = self.state.selected_index
        if index is None or index not in self.state.conflicts:
            self.show_message("Selecione uma regra em conflito", WARNING_COLOR)
            return
        if self.state.dirty and not self.confirm_discard_changes():
            return
        identity = self.require_selected_record()
        if identity is None:
            return

        promovidas = promote_glossary_rule(self.state.entries, index, self.state.conflicts)
        if promovidas is None:
            self.show_message("Esta regra já vence o conflito", WARNING_COLOR)
            return

        nova = glossary_entry_priority(promovidas[index])
        info = self.state.conflicts[index]
        if not messagebox.askyesno(
            "Priorizar esta regra",
            f"Dar prioridade {nova} à regra #{index + 1} para {info['pattern']!r}?\n\n"
            "As regras que disputam o mesmo texto continuam no glossário; esta "
            "passa a ser a aplicada.",
            parent=self.win,
        ):
            return

        def gravar():
            try:
                result = self.catalog.update(*identity, GlossaryEntryChanges(priority=nova))
            except GlossaryConflictError as exc:
                self.report_revision_conflict(exc)
                return
            except Exception as exc:
                messagebox.showerror("Erro", f"Erro ao gravar glossário:\n{exc}", parent=self.win)
                return

            self.show_message(f"Regra priorizada (prioridade {nova})")
            self.finish_mutation(result, identity[0])

        entrada = promovidas[index]
        if glossary_entry_type(entrada) == GLOSSARY_RULE_AUTOMATIC:
            orig, new = glossary_entry_pair(entrada)
            self.measure_promotion_then(orig, new, GLOSSARY_RULE_AUTOMATIC, nova,
                                        glossary_entry_scope(entrada), gravar)
        else:
            gravar()

    def load_rows_from_file(self):
        try:
            if not os.path.exists(self.catalog.db_path):
                initialize_catalog_glossary()
            self.state.snapshot = self.catalog.list_entries()
            self.file_default_scope = self.state.snapshot.default_scope
            self.state.entries = [
                (entry.original_text, entry.replacement_text, entry.rule_type, entry.priority, entry.scope)
                for entry in self.state.snapshot.entries
            ]
            self.state.conflicts = glossary_conflicts(self.state.entries)
            self.state.diagnostics = build_glossary_diagnostics(
                self.state.entries, self.state.conflicts
            )
        except Exception as exc:
            self.state.entries = []
            self.state.snapshot = CatalogSnapshot((), 0)
            self.state.selected_index = None
            self.state.diagnostics = []
            self.state.conflicts = {}
            # Com `parent`, como os outros treze dialogos deste arquivo. Era o
            # unico sem ele, e por isso o unico que abria ATRAS do editor
            # maximizado — um erro invisivel numa janela que parece travada
            # (ROADMAP 22.12).
            messagebox.showerror(
                "Erro", f"Erro ao carregar glossário:\n{exc}", parent=self.win
            )
        # O indice de validacao e derivado de `entries`; invalida junto.
        self.state.validation_lookup = None
        self.file_label.configure(text="Catálogo: glossario-v2.db")

    def current_validation_lookup(self):
        if self.state.validation_lookup is None:
            self.state.validation_lookup = build_glossary_lookup(self.state.entries)
        return self.state.validation_lookup

    def apply_filter(self):
        source, target = self.preview_languages()
        scope_filter = SCOPE_FILTERS[self.scope_filter_text.get()]
        if scope_filter == "compatible" and not target:
            self.scope_filter_text.set("Todos os escopos")
            scope_filter = None
            self.show_message("Escolha um idioma de destino na janela principal para filtrar pelo par.", WARNING_COLOR)
        self.state.filtered_indices = glossary_filter_indices(
            self.state.entries,
            self.search_text.get(),
            self.filter_segment.get(),
            self.state.diagnostics,
            rule_type=RULE_TYPE_BY_LABEL.get(self.type_filter_text.get()),
            scope_filter=scope_filter, source_language=source, target_language=target,
            priority_filter=PRIORITY_FILTERS[self.priority_filter_text.get()],
        )
        self.state.filtered_indices = sort_glossary_indices(
            self.state.entries, self.state.filtered_indices, self.sort_text.get()
        )
        self.state.page_index = clamp_page(
            self.state.page_index, len(self.state.filtered_indices), PAGE_SIZE
        )
        self.render_rows()
        self.save_editor_settings()

    def page_count(self):
        return compute_page_count(len(self.state.filtered_indices), PAGE_SIZE)

    def update_page_controls(self):
        pages = self.page_count()
        current_page = self.state.page_index + 1 if pages else 0
        self.page_label.configure(text=f"Página {current_page}/{pages}")
        self.btn_page_prev.configure(state="normal" if self.state.page_index > 0 else "disabled")
        self.btn_page_next.configure(
            state="normal" if self.state.page_index + 1 < pages else "disabled"
        )

    def change_page(self, delta):
        new_page = self.state.page_index + delta
        if 0 <= new_page < self.page_count():
            self.state.page_index = new_page
            self.render_rows()

    def step_entry(self, delta):
        """Vai para a entrada anterior ou seguinte DA LISTA FILTRADA (22.12).

        Pela lista filtrada, e nao pela posicao no arquivo: com "Duplicadas"
        ativo, `+1` sobre o indice do arquivo pousaria numa regra que a tela nao
        mostra — o mesmo erro que a garantia R10 nomeou no editor de traducoes.

        Vira a pagina quando passa da borda, porque a alternativa e um atalho que
        para de funcionar na centesima linha sem dizer por que.
        """
        visiveis = self.state.filtered_indices
        if not visiveis:
            return None
        try:
            posicao = visiveis.index(self.state.selected_index)
        except ValueError:
            posicao = -1 if delta > 0 else len(visiveis)

        nova = posicao + delta
        if not (0 <= nova < len(visiveis)):
            return None

        pagina = nova // PAGE_SIZE
        if pagina != self.state.page_index:
            self.state.page_index = pagina
            self.render_rows()
        self.select_entry(visiveis[nova])
        return visiveis[nova]

    def focus_search(self, _event=None):
        self.search_entry.focus_set()
        return "break"

    def restart_at_first_page(self, _value=None):
        """Trocar o filtro ou a ordem volta para a primeira pagina.

        Era um `lambda` com `page_index.update({"value": 0})` embutido — a unica
        forma de atribuir dentro de uma expressao enquanto o estado morava num
        dict. Com o estado em atributos, e um metodo comum, como o
        `toggle_filter` do editor de traducoes.
        """
        self.state.page_index = 0
        self.apply_filter()

    def refresh_pair_filter(self, *_args):
        if self.scope_filter_text.get() == "Compatíveis com o par atual":
            self.restart_at_first_page()

    def remove_language_traces(self, event):
        if event.widget is not self.win:
            return
        for variable, token in self._language_traces:
            try:
                variable.trace_remove("write", token)
            except tk.TclError:
                pass
        self._language_traces.clear()

    def refresh_counts(self):
        counts = glossary_counts(self.state.entries, self.state.diagnostics)
        self.counts_label.configure(
            text=(
                f"Total: {counts['total']} · "
                f"Duplicadas: {counts['duplicates']} · "
                f"Conflitos: {counts['conflicts']} · "
                f"Avisos: {counts['invalid']}"
            )
        )
        self.update_filter_selection_label()
        self.update_page_controls()
        self.update_delete_shown_duplicates_button()

    def update_filter_selection_label(self):
        label = f"{len(self.state.filtered_indices)} exibidas"
        if self.state.selected_index is not None and self.state.selected_index not in self.state.filtered_indices:
            label += " · seleção fora do filtro"
        self.list_count_label.configure(text=label)

    def shown_duplicate_extras(self):
        if self.filter_segment.get() != "Duplicadas":
            return []
        return duplicate_extras_indices(self.state.entries, self.state.filtered_indices)

    def update_delete_shown_duplicates_button(self):
        extras = self.shown_duplicate_extras()
        if not extras:
            self.btn_delete_shown_duplicates.grid_remove()
            return
        plural = "cópia repetida exibida" if len(extras) == 1 else "cópias repetidas exibidas"
        self.btn_delete_shown_duplicates.configure(text=f"Excluir as {len(extras)} {plural}")
        self.btn_delete_shown_duplicates.configure(state="disabled")
        self.btn_delete_shown_duplicates.grid()

    def delete_shown_duplicates(self):
        """Bulk changes require a dedicated atomic catalog operation."""
        self.show_message("Ação indisponível até a operação atômica do catálogo.", WARNING_COLOR)
        return None

    def build_row_button(self, parent, _visible_index, entry_index):
        button = ctk.CTkButton(
            parent,
            text=row_label(self.state.entries, entry_index, self.state.diagnostics),
            anchor="w",
            height=64,
            fg_color=ROW_COLOR,
            text_color=ROW_TEXT_COLOR,
            hover_color=ROW_HOVER_COLOR,
            command=lambda i=entry_index: self.select_entry(i),
        )
        if entry_index == self.state.selected_index:
            button.configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        return button

    def render_rows(self):
        self.row_buttons.clear()
        self.refresh_counts()

        start = page_offset(self.state.page_index, PAGE_SIZE)
        page_indices = self.state.filtered_indices[start:start + PAGE_SIZE]
        botoes = render_row_buttons(
            self.rows_frame, page_indices, self.build_row_button, "Nenhuma entrada encontrada."
        )
        # A lista guarda pares: o destaque e movido pela posicao no ARQUIVO, que
        # nao e a posicao na pagina quando ha filtro ou ordenacao.
        self.row_buttons.extend(zip(page_indices, botoes))

    def update_row_selection(self, index):
        """Move o destaque trocando so as cores dos botoes afetados.

        Antes isto chamava `render_rows()`, que destroi e recria ate 150
        CTkButtons e ainda recalcula os contadores sobre todas as entradas — a
        cada clique numa linha. O editor de traducoes ja fazia assim.
        """
        for entry_index, button in self.row_buttons:
            selecionado = entry_index == index
            button.configure(
                fg_color=SELECTED_ROW_COLOR if selecionado else ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR if selecionado else ROW_TEXT_COLOR,
            )

    def select_entry(self, index):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.state.selected_index = index
        self.state.loading = True
        entry = self.state.entries[index]
        orig, new = glossary_entry_pair(entry)
        rule_type = glossary_entry_type(entry)
        priority = glossary_entry_priority(entry)
        scope = glossary_entry_scope(entry)
        self.set_text(self.orig_text, orig)
        self.set_text(self.new_text, new)
        self.set_rule_type(rule_type)
        self.set_priority(priority)
        self.set_scope(scope)
        self.set_form_baseline(orig, new, rule_type, priority, scope)
        self.state.loading = False
        self.set_dirty(False)
        self.update_row_selection(index)
        self.update_filter_selection_label()
        self.refresh_conflict()
        self.orig_text.focus_set()

    def clear_form(self):
        self.state.selected_index = None
        self.state.loading = True
        self.set_text(self.orig_text, "")
        self.set_text(self.new_text, "")
        self.set_rule_type(GLOSSARY_RULE_SUGGESTION)
        self.set_priority(GLOSSARY_PRIORITY_DEFAULT)
        # Uma entrada nova herda o padrao do arquivo: num glossario declarado
        # `escopo = 'pt'`, a regra que o usuario acaba de escrever e portuguesa.
        self.set_scope(self.file_default_scope)
        self.set_form_baseline(scope=self.file_default_scope)
        self.state.loading = False
        self.set_dirty(False)
        self.refresh_conflict()
        self.render_rows()
        self.orig_text.focus_set()

    def start_prefilled_entry(self, original, replacement=""):
        self.state.selected_index = None
        self.state.page_index = 0
        self.search_text.set("")
        self.filter_segment.set("Todas")
        self.type_filter_text.set("Todos os tipos")
        self.scope_filter_text.set("Todos os escopos")
        self.priority_filter_text.set("Todas as prioridades")
        self.state.loading = True
        self.set_text(self.orig_text, (original or "").strip())
        self.set_text(self.new_text, (replacement or "").strip())
        self.set_rule_type(GLOSSARY_RULE_SUGGESTION)
        self.set_priority(GLOSSARY_PRIORITY_DEFAULT)
        # Uma entrada nova herda o padrao do arquivo: num glossario declarado
        # `escopo = 'pt'`, a regra que o usuario acaba de escrever e portuguesa.
        self.set_scope(self.file_default_scope)
        self.set_form_baseline(scope=self.file_default_scope)
        self.state.loading = False
        self.set_dirty(True)
        self.refresh_conflict()
        self.apply_filter()
        if self.text_value(self.orig_text):
            self.new_text.focus_set()
        else:
            self.orig_text.focus_set()
        self.show_message("Nova entrada pronta para revisar", WARNING_COLOR)

    def confirm_discard_changes(self):
        return messagebox.askyesno(
            "Alterações não salvas",
            "Descartar as alterações atuais?",
            parent=self.win,
        )

    def new_entry(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.clear_form()
        self.show_message("Nova entrada")

    def reload_all(self, select_first=True):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.load_rows_from_file()
        self.state.selected_index = None
        self.state.page_index = 0
        self.apply_filter()
        if select_first and self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])
        else:
            self.clear_form()

    def finish_mutation(self, result, stable_id=None):
        self.set_dirty(False)
        self.load_rows_from_file()
        self.state.selected_id = stable_id
        self.apply_filter()
        if self.state.selected_index is not None:
            self.select_entry(self.state.selected_index)
        else:
            self.clear_form()
        self.update_app_glossary()
        if result.warning:
            self.show_message(result.warning, WARNING_COLOR)

    def report_revision_conflict(self, conflict, baseline=None, attempted=None):
        """Compare revisions and reload only with explicit user consent."""
        baseline = dict(self.form_baseline) if baseline is None else baseline
        attempted = (*self.current_pair(), self.current_rule_type(), self.current_priority(), self.current_scope()) if attempted is None else attempted
        current = conflict.current_entry
        def describe(values):
            orig, new, phase, priority, scope = values
            return f"{orig!r} → {new!r}; tipo={phase}; prioridade={priority}; escopo={scope!r}"
        previous = (baseline["orig"], baseline["new"], baseline["type"], baseline["priority"], baseline["scope"])
        actual = describe((current.original_text, current.replacement_text, current.rule_type, current.priority, current.scope)) if current else "Entrada removida ou catálogo alterado."
        message = (f"A revisão mudou em outra janela.\n\nBase: {describe(previous)}"
                   f"\nSua edição: {describe(attempted)}\nAtual: {actual}"
                   "\n\nNada foi gravado.")
        if not messagebox.askyesno(
            "Conflito de revisão" if current or conflict.stable_id is None else "Entrada não encontrada",
            message + "\n\nRecarregar agora descarta o rascunho. Escolha Não para cancelar e mantê-lo.",
            parent=self.win,
        ):
            return False
        self.set_dirty(False)
        self.load_rows_from_file()
        self.state.selected_id = conflict.stable_id
        self.apply_filter()
        if self.state.selected_index is not None:
            self.select_entry(self.state.selected_index)
        else:
            self.clear_form()
        return True

    def require_selected_record(self):
        """A projection without its complete record never authorizes a mutation."""
        stable_id = self.form_baseline.get("stable_id")
        revision = self.form_baseline.get("revision")
        if (stable_id and revision and self.state.selected_id == stable_id
                and self.state.selected_revision == revision
                and self.state.selected_index is not None):
            return stable_id, revision
        self.set_dirty(False)
        self.reload_all()
        self.show_message("Seleção incompleta; catálogo recarregado. Selecione novamente.", WARNING_COLOR)
        return None

    def report_entry_vanished(self):
        """A entrada editada nao existe mais como estava no arquivo."""
        self.apply_filter()
        self.clear_form()
        messagebox.showwarning(
            "Entrada não encontrada",
            "A entrada que estava sendo editada foi alterada ou removida do "
            "glossário por fora desta janela.\n\n"
            "Nada foi gravado, para não sobrescrever outra entrada. A lista foi "
            "recarregada.",
            parent=self.win,
        )

    def save_current(self):
        orig, new = self.current_pair()
        rule_type = self.current_rule_type()
        priority = self.current_priority()
        scope = self.current_scope()
        draft = self.persistible_draft(orig, new, rule_type, priority, scope)
        if draft is None:
            return
        orig, new, rule_type, scope, priority = (
            draft.original_text, draft.replacement_text, draft.rule_type,
            draft.scope, draft.priority,
        )
        baseline = dict(self.form_baseline)
        identity = None
        if self.state.selected_id is not None or baseline.get("stable_id") is not None:
            identity = self.require_selected_record()
            if identity is None:
                return
        warnings = validate_glossary_entry(
            orig,
            new,
            self.state.entries,
            self.state.selected_index,
            rule_type=rule_type,
            scope=scope,
        )
        if priority is None:
            warnings.append(INVALID_PRIORITY_WARNING)
        blocking = [
            warning
            for warning in warnings
            if warning in {
                "Texto original vazio.",
                "Texto de substituição vazio.",
                INVALID_PRIORITY_WARNING,
            }
        ]
        if blocking:
            self.show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        def gravar():
            try:
                if identity is None:
                    result = self.catalog.add(
                        GlossaryEntryDraft(orig, new, rule_type, scope, priority),
                        baseline["catalog_revision"],
                    )
                else:
                    result = self.catalog.update(
                        *identity, GlossaryEntryChanges(orig, new, rule_type, scope, priority)
                    )
            except GlossaryConflictError as exc:
                self.report_revision_conflict(exc, baseline, (orig, new, rule_type, priority, scope))
                return
            except GlossaryDuplicateError:
                self.show_message("Entrada já existia neste tipo e escopo", WARNING_COLOR)
                return
            except Exception as exc:
                messagebox.showerror("Erro", f"Erro ao salvar glossário:\n{exc}", parent=self.win)
                return

            self.show_message("Entrada salva")
            self.finish_mutation(result, result.entry.stable_id)

        self.confirm_promotion_then(orig, new, rule_type, priority, scope, gravar)

    def promotes_to_automatic(self, orig, new, rule_type, priority, scope):
        """Gravar este formulario cria um comportamento automatico NOVO?

        Sim quando o tipo e `automatic` e a linha de base nao era esta mesma
        regra automatica: uma entrada nova, uma sugestao promovida, ou uma
        automatica cujo texto mudou (que e outra regra com o mesmo tipo).
        Salvar de novo uma automatica que nao mudou nao pergunta nada — nao ha
        impacto novo a mostrar.
        """
        if rule_type != GLOSSARY_RULE_AUTOMATIC:
            return False
        base = self.form_baseline
        return not (
            base["type"] == GLOSSARY_RULE_AUTOMATIC
            and (base["orig"], base["new"], base["priority"], base["scope"])
            == (orig, new, normalize_glossary_priority(priority), normalize_glossary_scope(scope))
        )

    def confirm_promotion_then(self, orig, new, rule_type, priority, scope, gravar):
        """Grava direto, ou mede o impacto e grava so se o usuario confirmar.

        E a garantia S20 (ROADMAP 28.5): promover a `automatic` mostra antes
        quantas traducoes pendentes a regra alteraria e dez delas. A medicao
        roda fora da thread do Tk, entao `gravar` e uma continuacao e nao um
        `return` — e enquanto ela roda o formulario continua sujo, que e o
        estado verdadeiro: nada foi gravado ainda.
        """
        if not self.promotes_to_automatic(orig, new, rule_type, priority, scope):
            gravar()
            return
        self.measure_promotion_then(orig, new, rule_type, priority, scope, gravar)

    def measure_promotion_then(self, orig, new, rule_type, priority, scope, gravar):
        """A medicao de S20 sem a pergunta "e promocao?" — quem chama ja sabe."""
        def decidido(promover):
            if not self.win.winfo_exists():
                return
            if promover:
                gravar()
            else:
                self.show_message("Promoção cancelada; nada foi gravado", WARNING_COLOR)

        preview_automatic_rule_impact(
            self.app,
            (orig, new, rule_type, priority, scope),
            parent=self.win,
            on_decision=decidido,
        )

    def save_as_new(self):
        orig, new = self.current_pair()
        rule_type = self.current_rule_type()
        priority = self.current_priority()
        scope = self.current_scope()
        draft = self.persistible_draft(orig, new, rule_type, priority, scope)
        if draft is None:
            return
        orig, new, rule_type, scope, priority = (
            draft.original_text, draft.replacement_text, draft.rule_type,
            draft.scope, draft.priority,
        )
        expected_catalog_revision = self.state.catalog_revision
        baseline = dict(self.form_baseline)
        warnings = validate_glossary_entry(
            orig, new, self.state.entries, rule_type=rule_type, scope=scope
        )
        if (
            "Texto original vazio." in warnings
            or "Texto de substituição vazio." in warnings
            or priority is None
        ):
            self.show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        def gravar():
            try:
                result = self.catalog.add(
                    GlossaryEntryDraft(orig, new, rule_type, scope, priority),
                    expected_catalog_revision,
                )
            except GlossaryConflictError as exc:
                self.report_revision_conflict(exc, baseline, (orig, new, rule_type, priority, scope))
                return
            except GlossaryDuplicateError:
                self.show_message("Entrada já existia neste tipo e escopo", WARNING_COLOR)
                return
            except Exception as exc:
                messagebox.showerror(
                    "Erro", f"Erro ao salvar nova entrada:\n{exc}", parent=self.win
                )
                return

            self.show_message("Nova entrada salva")
            self.finish_mutation(result, result.entry.stable_id)

        # "Salvar como nova" sempre cria uma entrada, entao uma automatica aqui e
        # sempre uma regra automatica nova — a linha de base nao conta.
        if rule_type == GLOSSARY_RULE_AUTOMATIC:
            self.measure_promotion_then(orig, new, rule_type, priority, scope, gravar)
        else:
            gravar()

    def delete_current(self):
        index = self.state.selected_index
        if index is None or not (0 <= index < len(self.state.entries)):
            self.show_message("Selecione uma entrada", WARNING_COLOR)
            return

        identity = self.require_selected_record()
        if identity is None:
            return
        if not messagebox.askyesno(
            "Excluir entrada",
            "Excluir a entrada selecionada do glossário?",
            parent=self.win,
        ):
            return

        try:
            result = self.catalog.delete(*identity)
        except GlossaryConflictError as exc:
            self.report_revision_conflict(exc)
            return
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao excluir entrada:\n{exc}", parent=self.win)
            return

        self.show_message("Entrada excluída")
        self.finish_mutation(result)
        if self.state.filtered_indices:
            # The previous index chooses a neighbour only after deletion by ID.
            seguintes = [i for i in self.state.filtered_indices if i >= index]
            self.select_entry(seguintes[0] if seguintes else self.state.filtered_indices[-1])
        else:
            self.clear_form()

    def deduplicate_entries(self):
        identities = [canonical_identity(entry) for entry in self.state.snapshot.entries]
        removed = len(identities) - len(set(identities))
        if removed and not messagebox.askyesno(
            "Deduplicar glossário",
            f"Remover {removed} duplicata(s) exata(s)?",
            parent=self.win,
        ):
            return

        try:
            result = self.catalog.deduplicate(self.state.catalog_revision)
        except GlossaryConflictError as exc:
            self.report_revision_conflict(exc)
            return
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao deduplicar glossário:\n{exc}", parent=self.win)
            return

        if not removed:
            self.state.snapshot = result.snapshot
            self.form_baseline["catalog_revision"] = result.snapshot.catalog_revision
            self.show_message(
                result.warning or "Nenhuma duplicata exata encontrada",
                WARNING_COLOR if result.warning else OK_COLOR,
            )
            return

        self.show_message(f"{removed} duplicata(s) removida(s)")
        self.finish_mutation(result, self.state.selected_id)

    def create_backup_now(self):
        try:
            backup_path = create_glossary_backup()
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao criar backup:\n{exc}", parent=self.win)
            return

        if backup_path:
            self.show_message(f"Backup criado: {os.path.basename(backup_path)}")
        else:
            self.show_message("Arquivo de glossário ainda não existe", WARNING_COLOR)

    def export_csv(self):
        save_path = filedialog.asksaveasfilename(
            title="Exportar glossário CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            parent=self.win,
        )
        if not save_path:
            return

        try:
            stats = export_glossary_csv(save_path, entries=self.state.entries)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao exportar CSV:\n{exc}", parent=self.win)
            return

        self.show_message(f"CSV exportado: {stats['exported']} entradas")

    def import_csv(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        path = filedialog.askopenfilename(
            title="Importar glossário", parent=self.win,
            filetypes=[("Glossário CSV ou texto", "*.csv *.txt"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self.preview_import_file(path)

    def preview_import_file(self, path):
        if self.import_preview_window is not None:
            self.import_preview_window.win.lift()
            return
        try:
            mirror = self.catalog.mirror_path
            is_mirror = bool(mirror and Path(path).resolve() == Path(mirror).resolve())
            mirror_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest() if is_mirror else None
            entries = read_glossary_import(path)
            if mirror_hash and hashlib.sha256(Path(path).read_bytes()).hexdigest() != mirror_hash:
                raise ValueError("O arquivo mudou durante a leitura; tente novamente.")
            preview = self.catalog.preview_import(entries)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao ler importação:\n{exc}", parent=self.win)
            return
        shown_draft = (self.current_pair(), self.current_rule_type(), self.current_priority(), self.current_scope())

        def confirmed():
            current_draft = (self.current_pair(), self.current_rule_type(), self.current_priority(), self.current_scope())
            if self.state.dirty and current_draft != shown_draft and not self.confirm_discard_changes():
                return
            try:
                create_glossary_backup()
                result = self.catalog.import_entries(entries, "append", preview.catalog_revision)
            except GlossaryConflictError as exc:
                self.report_revision_conflict(exc)
                return
            except Exception as exc:
                messagebox.showerror("Erro", f"Erro ao importar glossário:\n{exc}", parent=self.win)
                return
            self.finish_mutation(result)
            if mirror_hash and messagebox.askyesno(
                "Concluir revisão do glossário",
                "As entradas novas foram importadas. Deseja atualizar o arquivo legado "
                "com o catálogo atual? Uma cópia do arquivo revisado será guardada "
                "antes da atualização, inclusive entradas conflitantes ou inválidas.",
                parent=self.win,
            ):
                try:
                    resolution = self.catalog.accept_external_mirror(
                        mirror_hash, result.snapshot.catalog_revision
                    )
                except (OSError, ValueError, GlossaryConflictError) as exc:
                    messagebox.showwarning("Revisão do glossário", str(exc), parent=self.win)
                    return
                self.show_message(
                    resolution.warning or f"Arquivo sincronizado; cópia: {resolution.backup_path}",
                    WARNING_COLOR if resolution.warning else OK_COLOR,
                )
                return
            self.show_message(result.warning or f"Importadas {result.inserted_count} entrada(s) nova(s).",
                              WARNING_COLOR if result.warning else OK_COLOR)

        def closed():
            self.import_preview_window = None

        self.import_preview_window = ImportPreviewDialog(
            self.win, preview, confirmed, closed, allow_empty=is_mirror
        )

    def restore_backup(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        path = filedialog.askopenfilename(
            title="Restaurar backup SQLite V2 ou importar texto", parent=self.win,
            filetypes=[("Backup SQLite V2", "*.db *.sqlite *.bak"), ("Glossário legado (importação)", "*.txt"),
                       ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        if os.path.splitext(path)[1].lower() in (".txt", ".csv"):
            self.preview_import_file(path)
            return
        expected = self.state.catalog_revision
        if not messagebox.askyesno(
            "Restaurar catálogo",
            f"Substituir integralmente as {len(self.state.entries)} entradas pelo backup SQLite V2?\n"
            "Será criado um backup de segurança. Todas as janelas do glossário serão recarregadas; "
            "rascunhos abertos serão descartados.", parent=self.win,
        ):
            return
        try:
            create_glossary_backup(protect=(path,))
            result = self.catalog.restore(path, expected)
        except GlossaryConflictError as exc:
            self.report_revision_conflict(exc)
            return
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao restaurar catálogo:\n{exc}", parent=self.win)
            return
        for editor in list(self._instances):
            if editor.catalog._access_key == self.catalog._access_key and editor.win.winfo_exists():
                if editor.import_preview_window is not None:
                    editor.import_preview_window.close()
                editor.set_dirty(False)
                editor.reload_all()
        self.update_app_glossary()
        self.show_message(result.warning or "Catálogo restaurado; janelas recarregadas.",
                          WARNING_COLOR if result.warning else OK_COLOR)

    def apply_search(self):
        self.state.page_index = 0
        self.apply_filter()
        if self.state.selected_id is None and self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])

    def clear_search(self):
        self.search_text.set("")
        self.state.page_index = 0
        self.apply_filter()
        if self.state.selected_id is None and self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])

    def clear_all_filters(self):
        self.search_text.set("")
        self.filter_segment.set("Todas")
        self.type_filter_text.set("Todos os tipos")
        self.scope_filter_text.set("Todos os escopos")
        self.priority_filter_text.set("Todas as prioridades")
        self.state.page_index = 0
        self.apply_filter()

    def close_editor(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.save_editor_settings()
        # A lista do rastreador e de CLASSE: sem tirar o desta janela, cada
        # abrir-e-fechar deixaria mais um la (a mesma razao do editor, F18).
        try:
            ctk.AppearanceModeTracker.remove(self.apply_pane_color)
        except Exception:  # pragma: no cover - versao sem o registrador
            pass
        self.win.destroy()


def open_glossary_editor(
    app, on_change=None, initial_original=None, initial_replacement=None
):
    """Abre a janela de edicao do glossario.

    Continua sendo uma funcao porque e assim que o resto do programa chama.
    Devolve a instancia, como `open_translation_editor`: quem dirige a janela
    de fora (os testes de widget, a skill) nao precisa mais andar na arvore de
    widgets para alcancar um metodo.
    """
    return GlossaryEditor(app, on_change, initial_original, initial_replacement)

