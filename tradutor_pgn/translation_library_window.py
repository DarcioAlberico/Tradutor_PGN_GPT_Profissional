"""Janela de consulta não destrutiva da biblioteca de traduções."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .translation_library import _legacy_bundle, _manifest_bundle, bundle_summary, list_bundles, review_percentage, search_bundles, sort_bundles, verify_bundle
from .translation_library import StagingInspectionCanceled, format_staging_inspection, inspect_staging_directories
from .background_task import TaskCanceled, run_with_progress
from .app_config import LANGUAGE_NAMES
from .library_preferences import parse_preferences, save_preferences
from .settings import load_settings
from .editor_widgets import attach_tooltip
from .window_utils import bring_window_to_front

PAGE_SIZE = 20
STATUS_OPTIONS = {"Todos": None, "Com manifesto": "ready", "Sem manifesto": "legacy",
                  "Incompleto": "incomplete", "Manifesto inválido": "invalid"}
ORDER_OPTIONS = {"Nome (A–Z)": "name", "Nome (Z–A)": "reverse_name",
                 "Mais recentes": "recent", "Mais antigos": "oldest",
                 "Mais falhas": "failures_desc", "Menos falhas": "failures_asc"}
FAILURE_OPTIONS = {"Falhas: Todas": None, "Falhas: Com falhas": "with",
                   "Falhas: Sem falhas": "without", "Falhas: Não informado": "unknown"}


class TranslationLibraryWindow:
    def __init__(self, parent, root_path, open_path, loader=list_bundles, verifier=verify_bundle,
                 review_resolver=None, on_review=None, progress_resolver=None):
        self.root_path = root_path
        self.open_path = open_path
        self.loader = loader
        self.verifier = verifier
        self.review_resolver = review_resolver
        self.on_review = on_review
        self.progress_resolver = progress_resolver
        self.preferences = parse_preferences(load_settings().get("translation_library"))
        self._preferences_pending = True
        self._loaded_successfully = False
        self.items = []
        self.visible_bundles = []
        self.page_index = 0
        self.page_count = 0
        self.loading = False
        self._batching_filters = False
        self.closed = False
        self._poll_id = None
        self._results = queue.Queue()
        self.verifying = False
        self._integrity_cancel = threading.Event()
        self._verify_results = queue.Queue()
        self._verify_poll_id = None
        self.resolving_review = False
        self._review_results = queue.Queue()
        self._review_poll_id = None
        self.loading_progress = False
        self._progress_results = queue.Queue()
        self._progress_poll_id = None
        self.win = ctk.CTkToplevel(parent)
        self.win.title("Biblioteca de traduções")
        self.win.geometry("850x600")
        self.win.minsize(600, 400)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.transient(parent)
        bring_window_to_front(self.win, parent, maximize=False)
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(3, weight=1)

        title = ctk.CTkLabel(self.win, text="Biblioteca de traduções", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, sticky="w", padx=20, pady=(16, 3))
        ctk.CTkLabel(self.win, text="Busque por nome, idioma ou motor, em qualquer ordem e sem exigir acentos.",
                     anchor="w", text_color=("#555555", "#b0b0b0")).grid(row=1, column=0, sticky="ew", padx=20)
        controls = ctk.CTkFrame(self.win, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=20, pady=12)
        controls.grid_columnconfigure(0, weight=1)
        self.query = tk.StringVar(master=self.win)
        self.search_entry = ctk.CTkEntry(controls, textvariable=self.query, placeholder_text="Buscar traduções (Ctrl+F)")
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.refresh_button = ctk.CTkButton(controls, text="Atualizar", width=110, command=self.refresh)
        self.refresh_button.grid(row=0, column=1)
        self.clear_filters_button = ctk.CTkButton(controls, text="Limpar filtros (Ctrl+L)", width=145,
                                                  command=self.clear_filters)
        self.clear_filters_button.grid(row=0, column=2, padx=(8, 0))
        attach_tooltip(self.clear_filters_button, "Filtros e ordenação são lembrados; a busca textual não é salva.")
        self.staging_button = ctk.CTkButton(controls, text="Temporários…", width=120, command=self.inspect_staging)
        self.staging_button.grid(row=0, column=3, padx=(8, 0))
        filters = ctk.CTkFrame(controls, fg_color="transparent")
        filters.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.status_filter = tk.StringVar(master=self.win, value=self._label_for(STATUS_OPTIONS, self.preferences["status"]))
        self.order_var = tk.StringVar(master=self.win, value=self._label_for(ORDER_OPTIONS, self.preferences["order"]))
        ctk.CTkLabel(filters, text="Situação:").pack(side="left", padx=(0, 5))
        ctk.CTkOptionMenu(filters, variable=self.status_filter, values=list(STATUS_OPTIONS), width=145).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(filters, text="Ordenar:").pack(side="left", padx=(0, 5))
        ctk.CTkOptionMenu(filters, variable=self.order_var, values=list(ORDER_OPTIONS), width=135).pack(side="left")
        self.failure_filter = tk.StringVar(master=self.win, value=self._label_for(FAILURE_OPTIONS, self.preferences["failures"]))
        ctk.CTkOptionMenu(filters, variable=self.failure_filter, values=list(FAILURE_OPTIONS), width=135).pack(side="left", padx=(8, 0))
        facets = ctk.CTkFrame(controls, fg_color="transparent")
        facets.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.source_filter = tk.StringVar(master=self.win, value="Origem: Todos")
        self.target_filter = tk.StringVar(master=self.win, value="Destino: Todos")
        self.provider_filter = tk.StringVar(master=self.win, value="Motor: Todos")
        self._source_options = {"Origem: Todos": None}
        self._target_options = {"Destino: Todos": None}
        self._provider_options = {"Motor: Todos": None}
        self.source_menu = ctk.CTkOptionMenu(facets, variable=self.source_filter, values=list(self._source_options), width=160)
        self.source_menu.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.target_menu = ctk.CTkOptionMenu(facets, variable=self.target_filter, values=list(self._target_options), width=160)
        self.target_menu.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.provider_menu = ctk.CTkOptionMenu(facets, variable=self.provider_filter, values=list(self._provider_options), width=160)
        self.provider_menu.pack(side="left", fill="x", expand=True)
        self.cards = ctk.CTkScrollableFrame(self.win, fg_color="transparent")
        self.cards.grid(row=3, column=0, sticky="nsew", padx=16)
        self.cards.grid_columnconfigure(0, weight=1)
        pager = ctk.CTkFrame(self.win, fg_color="transparent")
        pager.grid(row=4, column=0, sticky="ew", padx=20, pady=(5, 0))
        self.previous_button = ctk.CTkButton(pager, text="Anterior (Alt+←)", width=135, command=self.previous_page)
        self.previous_button.pack(side="left")
        self.page_label = ctk.CTkLabel(pager, text="Página 0 de 0", width=120)
        self.page_label.pack(side="left", padx=8)
        self.next_button = ctk.CTkButton(pager, text="Próxima (Alt+→)", width=135, command=self.next_page)
        self.next_button.pack(side="left")
        self.active_filters_label = ctk.CTkLabel(pager, text="Filtros: 0", anchor="e", text_color=("#555555", "#b0b0b0"))
        self.active_filters_label.pack(side="right")
        status = ctk.CTkFrame(self.win, fg_color="transparent")
        status.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 14))
        self.cancel_integrity_button = ctk.CTkButton(status, text="Cancelar verificação", width=150,
                                                    command=self.cancel_integrity, state="disabled")
        self.cancel_integrity_button.pack(side="right", padx=(8, 0))
        self.status_label = ctk.CTkLabel(status, text="", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.query.trace_add("write", self._filter)
        self.status_filter.trace_add("write", self._filter)
        self.order_var.trace_add("write", self._filter)
        self.failure_filter.trace_add("write", self._filter)
        self.source_filter.trace_add("write", self._filter)
        self.target_filter.trace_add("write", self._filter)
        self.provider_filter.trace_add("write", self._filter)
        self.win.bind("<Escape>", lambda _event: self.close())
        self.win.bind("<Control-f>", lambda _event: self.focus_search())
        self.win.bind("<Alt-Left>", lambda _event: self._page_shortcut(-1))
        self.win.bind("<Alt-Right>", lambda _event: self._page_shortcut(1))
        self.win.bind("<Control-l>", lambda _event: self.clear_filters_shortcut())
        self.win.bind("<F5>", lambda _event: self.refresh_shortcut())
        self.win.bind("<Alt-Home>", lambda _event: self.first_page_shortcut())
        self.win.bind("<Alt-End>", lambda _event: self.last_page_shortcut())
        self.refresh()

    @staticmethod
    def card_status(bundle):
        return {"ready": "Pacote com manifesto", "legacy": "Pacote anterior, sem manifesto",
                "incomplete": "Pacote incompleto", "invalid": "Manifesto inválido"}.get(bundle.status, "Estado desconhecido")

    @staticmethod
    def _label_for(options, value):
        return next((label for label, candidate in options.items() if candidate == value), next(iter(options)))

    def refresh(self):
        if self.closed or self.loading:
            return
        self.loading = True
        self.refresh_button.configure(state="disabled")
        self.status_label.configure(text="Carregando biblioteca…")

        def work():
            try:
                self._results.put((True, self.loader(self.root_path)))
            except Exception:
                self._results.put((False, None))

        threading.Thread(target=work, daemon=True).start()
        self._poll_id = self.win.after(30, self._poll)

    def inspect_staging(self):
        if self.closed:
            return
        root = self.root_path

        def work(task):
            try:
                return inspect_staging_directories(root, should_cancel=task.cancelado)
            except StagingInspectionCanceled as exc:
                raise TaskCanceled() from exc

        def done(result):
            if not self.closed:
                messagebox.showinfo("Temporários de tradução", format_staging_inspection(result), parent=self.win)

        run_with_progress(self.win, "Inspecionar temporários", work, on_success=done,
                          on_error=lambda error: messagebox.showerror(
                              "Temporários de tradução", f"Não foi possível concluir a inspeção:\n{error}", parent=self.win),
                          message="Procurando pastas temporárias antigas…")

    def _poll(self):
        self._poll_id = None
        if self.closed:
            return
        try:
            ok, result = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.win.after(30, self._poll)
            return
        self.refresh_button.configure(state="normal")
        if not ok:
            self._loaded_successfully = False
            self.items = []
            self._refresh_facets()
            self.loading = False
            self._render()
            self.status_label.configure(text="Não foi possível ler a biblioteca. Confira o acesso e atualize.")
            return
        self.items = result
        self._refresh_facets(restore_preferences=True)
        self._loaded_successfully = True
        self.loading = False
        self._render()

    def _refresh_facets(self, restore_preferences=False):
        def languages(prefix, values):
            result = {f"{prefix}: Todos": None}
            if "" in values:
                result[f"{prefix}: Não informado"] = ""
            for code in sorted(values - {""}, key=str.casefold):
                result[f"{prefix}: {LANGUAGE_NAMES.get(code, code)} ({code})"] = code
            return result

        self._source_options = languages("Origem", {item.source_language or "" for item in self.items})
        self._target_options = languages("Destino", {item.target_language or "" for item in self.items})
        providers = {item.provider or "" for item in self.items}
        self._provider_options = {"Motor: Todos": None}
        if "" in providers:
            self._provider_options["Motor: Não informado"] = ""
        for provider in sorted(providers - {""}, key=str.casefold):
            self._provider_options[f"Motor: [{provider}]"] = provider
        for menu, variable, options in (
            (self.source_menu, self.source_filter, self._source_options),
            (self.target_menu, self.target_filter, self._target_options),
            (self.provider_menu, self.provider_filter, self._provider_options),
        ):
            menu.configure(values=list(options))
            if variable.get() not in options:
                variable.set(next(iter(options)))
        if self._preferences_pending and restore_preferences:
            for variable, options, key in (
                (self.source_filter, self._source_options, "source"),
                (self.target_filter, self._target_options, "target"),
                (self.provider_filter, self._provider_options, "provider"),
            ):
                variable.set(self._label_for(options, self.preferences[key]))
            self._preferences_pending = False

    def _filter(self, *_args):
        self.page_index = 0
        if not self.closed and not self.loading and not self._batching_filters:
            self._render()

    def clear_filters(self):
        self._batching_filters = True
        try:
            self.query.set("")
            self.status_filter.set("Todos")
            self.failure_filter.set("Falhas: Todas")
            self.source_filter.set("Origem: Todos")
            self.target_filter.set("Destino: Todos")
            self.provider_filter.set("Motor: Todos")
        finally:
            self._batching_filters = False
        self.page_index = 0
        if not self.closed and not self.loading:
            self._render()

    def clear_filters_shortcut(self):
        self.clear_filters()
        return "break"

    def refresh_shortcut(self):
        self.refresh()
        return "break"

    def first_page_shortcut(self):
        if not self.loading and self.page_index:
            self.page_index = 0
            self._render()
        return "break"

    def last_page_shortcut(self):
        if not self.loading and self.page_count and self.page_index != self.page_count - 1:
            self.page_index = self.page_count - 1
            self._render()
        return "break"

    def previous_page(self):
        if not self.loading and self.page_index > 0:
            self.page_index -= 1
            self._render()

    def focus_search(self):
        self.search_entry.focus_set()
        return "break"

    def _page_shortcut(self, direction):
        if direction < 0:
            self.previous_page()
        else:
            self.next_page()
        return "break"

    def next_page(self):
        if not self.loading and self.page_index + 1 < self.page_count:
            self.page_index += 1
            self._render()

    def _render(self):
        active = sum((bool(self.query.get().strip()), self.status_filter.get() != "Todos",
                      self.failure_filter.get() != "Falhas: Todas", self.source_filter.get() != "Origem: Todos",
                      self.target_filter.get() != "Destino: Todos", self.provider_filter.get() != "Motor: Todos"))
        self.active_filters_label.configure(text=f"Filtros: {active}")
        for child in self.cards.winfo_children():
            child.destroy()
        filtered = search_bundles(
            self.items, self.query.get(), STATUS_OPTIONS.get(self.status_filter.get()),
            source=self._source_options.get(self.source_filter.get()),
            target=self._target_options.get(self.target_filter.get()),
            provider=self._provider_options.get(self.provider_filter.get()),
            failures=FAILURE_OPTIONS.get(self.failure_filter.get()),
        )
        order = ORDER_OPTIONS.get(self.order_var.get(), "name")
        filtered = sort_bundles(filtered, "name" if order == "reverse_name" else order)
        if order == "reverse_name":
            filtered.reverse()
        self.page_count = (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE
        self.page_index = min(self.page_index, max(0, self.page_count - 1))
        start = self.page_index * PAGE_SIZE
        self.visible_bundles = filtered[start:start + PAGE_SIZE]
        self.page_label.configure(text=f"Página {self.page_index + 1 if self.page_count else 0} de {self.page_count}")
        self.previous_button.configure(state="normal" if self.page_index else "disabled")
        self.next_button.configure(state="normal" if self.page_index + 1 < self.page_count else "disabled")
        for row, bundle in enumerate(self.visible_bundles):
            card = ctk.CTkFrame(self.cards, corner_radius=8)
            card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=bundle.directory.name, anchor="w",
                         font=ctk.CTkFont(weight="bold", size=15)).grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
            metadata = self.card_status(bundle)
            if bundle.target_language:
                metadata += f"  •  {bundle.source_language or 'auto'} → {bundle.target_language}"
            if bundle.provider:
                metadata += f"  •  {bundle.provider}"
            if bundle.created_at:
                metadata += f"  •  {bundle.created_at[:10]}"
            if bundle.failed_comments is not None:
                metadata += f"  •  Falhas na geração: {bundle.failed_comments}"
            ctk.CTkLabel(card, text=metadata, anchor="w", wraplength=650).grid(row=1, column=0, sticky="ew", padx=12)
            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=2, column=0, sticky="w", padx=12, pady=(4, 10))
            ctk.CTkButton(buttons, text="Abrir pasta", width=100,
                          command=lambda item=bundle: self._open(item.directory)).pack(side="left", padx=(0, 6))
            if bundle.status in ("ready", "legacy"):
                ctk.CTkButton(buttons, text="Original", width=90,
                              command=lambda item=bundle: self.open_bundle_file(item, "original")).pack(side="left", padx=(0, 6))
                ctk.CTkButton(buttons, text="Traduzido", width=100,
                              command=lambda item=bundle: self.open_bundle_file(item, "translation")).pack(side="left")
            if bundle.status == "ready":
                ctk.CTkButton(buttons, text="Verificar integridade", width=145,
                              command=lambda item=bundle: self.check_integrity(item)).pack(side="left", padx=(6, 0))
            if bundle.status in ("ready", "legacy"):
                review_buttons = ctk.CTkFrame(card, fg_color="transparent")
                review_buttons.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 10))
                if self.review_resolver is not None and self.on_review is not None:
                    ctk.CTkButton(review_buttons, text="Revisar pendentes", width=145,
                                  command=lambda item=bundle: self.review_bundle(item)).pack(side="left")
                if bundle.status == "ready" and self.progress_resolver is not None:
                    ctk.CTkButton(review_buttons, text="Consultar progresso", width=145,
                                  command=lambda item=bundle: self.show_review_progress(item)).pack(side="left", padx=(6, 0))
                ctk.CTkButton(review_buttons, text="Copiar resumo", width=120,
                              command=lambda item=bundle: self.copy_summary(item)).pack(side="left", padx=(6, 0))
        if self.visible_bundles:
            self.status_label.configure(text=f"{len(filtered)} pacote(s) encontrado(s).")
        else:
            self.status_label.configure(text="Nenhum pacote encontrado. Traduza um PGN ou ajuste a busca.")

    def open_bundle_file(self, bundle, kind):
        directory = bundle.directory
        if directory.is_symlink() or not directory.is_dir():
            self.status_label.configure(text="O pacote não está mais disponível. Atualize a biblioteca.")
            return
        current = _manifest_bundle(directory) if bundle.status == "ready" else _legacy_bundle(directory)
        path = current.original if kind == "original" else current.translated
        expected = bundle.original if kind == "original" else bundle.translated
        if current.status != bundle.status or path is None or path != expected:
            self.status_label.configure(text="O arquivo não está mais disponível. Atualize a biblioteca.")
            return
        self._open(path)

    def copy_summary(self, bundle):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(bundle_summary(bundle))
            self.status_label.configure(text="Resumo copiado para a área de transferência.")
        except tk.TclError:
            self.status_label.configure(text="Não foi possível copiar o resumo.")

    def check_integrity(self, bundle):
        if self.closed:
            return
        if self.verifying:
            self.status_label.configure(text="Aguarde a verificação em andamento.")
            return
        self.verifying = True
        self._integrity_cancel.clear()
        self.cancel_integrity_button.configure(state="normal")
        self.status_label.configure(text=f"Verificando {bundle.directory.name}…")

        def work():
            try:
                if self.verifier is verify_bundle:
                    result = self.verifier(bundle.directory, should_cancel=self._integrity_cancel.is_set)
                else:
                    result = self.verifier(bundle.directory)
            except Exception:
                result = None
            self._verify_results.put((bundle.directory.name, result))

        threading.Thread(target=work, daemon=True).start()
        self._verify_poll_id = self.win.after(30, self._poll_integrity)

    def cancel_integrity(self):
        if self.verifying and not self.closed:
            self._integrity_cancel.set()
            self.cancel_integrity_button.configure(state="disabled")
            self.status_label.configure(text="Cancelando verificação de integridade…")

    def review_bundle(self, bundle):
        if self.closed or self.review_resolver is None or self.on_review is None:
            return
        if self.resolving_review:
            self.status_label.configure(text="Aguarde a busca da revisão em andamento.")
            return
        self.resolving_review = True
        self.status_label.configure(text=f"Localizando revisão de {bundle.directory.name}…")

        def work():
            try:
                result = self.review_resolver(bundle.directory)
            except Exception:
                result = None
            self._review_results.put(result)

        threading.Thread(target=work, daemon=True).start()
        self._review_poll_id = self.win.after(30, self._poll_review)

    def show_review_progress(self, bundle):
        if self.closed or self.progress_resolver is None:
            return
        if self.loading_progress:
            self.status_label.configure(text="Aguarde a consulta de progresso em andamento.")
            return
        self.loading_progress = True
        self.status_label.configure(text=f"Consultando progresso de {bundle.directory.name}…")

        def work():
            try:
                result = self.progress_resolver(bundle.directory)
            except Exception:
                result = None
            self._progress_results.put((bundle.directory.name, result))

        threading.Thread(target=work, daemon=True).start()
        self._progress_poll_id = self.win.after(30, self._poll_progress)

    def _poll_progress(self):
        self._progress_poll_id = None
        if self.closed:
            return
        try:
            name, result = self._progress_results.get_nowait()
        except queue.Empty:
            self._progress_poll_id = self.win.after(30, self._poll_progress)
            return
        self.loading_progress = False
        if result is not None and result.status == "ready":
            percentage = review_percentage(result.verified, result.total)
            message = f"{result.verified} de {result.total} comentários distintos verificados ({percentage}%); {result.pending} pendentes."
        elif result is not None and result.status in ("compatible", "unlinked", "ambiguous"):
            message = "sem vínculo confiável neste banco para consultar progresso."
        elif result is not None and result.status == "integrity":
            message = "integridade do pacote não confirmada."
        elif result is not None and result.status == "no_occurrences":
            message = "sem ocorrências registradas para este arquivo e idioma."
        else:
            message = "não foi possível consultar o progresso."
        self.status_label.configure(text=f"{name}: {message}")

    def _poll_review(self):
        self._review_poll_id = None
        if self.closed:
            return
        try:
            result = self._review_results.get_nowait()
        except queue.Empty:
            self._review_poll_id = self.win.after(30, self._poll_review)
            return
        self.resolving_review = False
        if result is not None and result.status == "ready" and result.link is not None:
            self.status_label.configure(text="Abrindo revisão dos comentários pendentes.")
            self.on_review(result.link)
            return
        if result is not None and result.status == "compatible" and result.link is not None:
            link = result.link
            accepted = messagebox.askyesno(
                "Revisão compatível",
                "Foi encontrada no banco uma obra com o mesmo conteúdo original e os idiomas "
                f"{link.source_language or 'não declarado'} → {link.target_language}.\n\n"
                f"Arquivo registrado: {link.source_file}\n\n"
                "Ela pode pertencer a outra execução. Abrir os comentários pendentes dessa obra?",
                parent=self.win,
            )
            if accepted:
                self.status_label.configure(text="Abrindo revisão compatível dos comentários pendentes.")
                self.on_review(link)
            else:
                self.status_label.configure(text="Revisão compatível não aberta.")
            return
        messages = {
            "integrity": "Não foi possível confirmar a integridade do pacote para revisão.",
            "unlinked": "Este pacote não possui vínculo de revisão neste banco.",
            "no_occurrences": "Não há ocorrências registradas para este arquivo e idioma.",
            "ambiguous": "Há várias obras ou pares compatíveis; não é possível escolher automaticamente.",
        }
        self.status_label.configure(text=messages.get(getattr(result, "status", None), "Não foi possível localizar a revisão."))

    def _poll_integrity(self):
        self._verify_poll_id = None
        if self.closed:
            return
        try:
            name, result = self._verify_results.get_nowait()
        except queue.Empty:
            self._verify_poll_id = self.win.after(30, self._poll_integrity)
            return
        self.verifying = False
        self.cancel_integrity_button.configure(state="disabled")
        if self._integrity_cancel.is_set() or (result is not None and result.status == "canceled"):
            message = "verificação cancelada"
        elif result is None or result.status == "unavailable":
            message = "não pôde ser verificado"
        elif result.status == "changed":
            message = "mudou durante a verificação; tente novamente"
        elif result.status == "verified":
            message = "original e traduzido correspondem ao manifesto"
        elif result.status == "mismatch":
            changed = []
            if result.original_ok is False:
                changed.append("original")
            if result.translation_ok is False:
                changed.append("traduzido")
            message = f"divergência no arquivo {' e '.join(changed)}"
        else:
            message = "não pôde ser verificado"
        self.status_label.configure(text=f"{name}: {message}.")

    def _open(self, path):
        try:
            self.open_path(str(path))
        except OSError as exc:
            messagebox.showerror("Biblioteca", f"Não foi possível abrir o item:\n{exc}", parent=self.win)

    def close(self):
        if self.closed:
            return
        if self._loaded_successfully and not self.loading:
            values = parse_preferences({
                "status": STATUS_OPTIONS.get(self.status_filter.get()),
                "order": ORDER_OPTIONS.get(self.order_var.get()),
                "failures": FAILURE_OPTIONS.get(self.failure_filter.get()),
                "source": self._source_options.get(self.source_filter.get()),
                "target": self._target_options.get(self.target_filter.get()),
                "provider": self._provider_options.get(self.provider_filter.get()),
            })
            try:
                save_preferences(values)
            except (OSError, ValueError):
                messagebox.showwarning(
                    "Biblioteca", "Não foi possível salvar os filtros e a ordenação. "
                    "As configurações existentes foram preservadas.", parent=self.win,
                )
        self.closed = True
        self._integrity_cancel.set()
        if self._poll_id is not None:
            self.win.after_cancel(self._poll_id)
        if self._verify_poll_id is not None:
            self.win.after_cancel(self._verify_poll_id)
        if self._review_poll_id is not None:
            self.win.after_cancel(self._review_poll_id)
        if self._progress_poll_id is not None:
            self.win.after_cancel(self._progress_poll_id)
        self.win.destroy()
