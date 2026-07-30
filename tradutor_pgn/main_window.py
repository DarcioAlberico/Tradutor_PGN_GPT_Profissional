import tkinter as tk
import webbrowser

import customtkinter as ctk

from .app_config import (
    APP_AUTHORS,
    APP_REPOSITORY_URL,
    AUTO_SOURCE_LABEL,
    LANGUAGES,
)

# Vermelho das acoes destrutivas, em par claro/escuro como o resto do tema.
DESTRUCTIVE_COLOR = ("#b91c1c", "#7f1d1d")
DESTRUCTIVE_HOVER_COLOR = ("#991b1b", "#991b1b")


def grid_button_row(parent, button_specs, columns=3):
    for index, spec in enumerate(button_specs):
        button = ctk.CTkButton(parent, **spec)
        row = index // columns
        column = index % columns
        button.grid(row=row, column=column, sticky=tk.EW, padx=4, pady=4)

    for column in range(columns):
        parent.columnconfigure(column, weight=1)


def create_section(parent, title):
    section = ctk.CTkFrame(parent, corner_radius=8)
    title_label = ctk.CTkLabel(section, text=title, font=ctk.CTkFont(weight="bold"))
    title_label.pack(anchor="w", padx=12, pady=(10, 2))

    content = ctk.CTkFrame(section, fg_color="transparent")
    content.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
    return section, content


def open_repository(_event=None):
    """Abre o repositorio no navegador padrao.

    Recebe e ignora o evento porque e ligada a um `<Button-1>`, e nao a um
    `command`. Se `webbrowser` falhar (uma maquina sem navegador associado), a
    excecao sobe e vira dialogo pelo relator de callbacks (garantia C3) — o que
    e melhor do que um clique que silenciosamente nao faz nada.
    """
    webbrowser.open(APP_REPOSITORY_URL)


def create_credits_footer(parent):
    """Rodape com autoria e link do repositorio.

    Fica no rodape, e nao num botao "Sobre": e informacao que se le uma vez e
    nao se procura de novo, entao ocupar uma celula da grade de "Ferramentas" —
    ao lado de acoes que o usuario usa toda hora — trocaria o lugar certo pelo
    lugar visivel.

    O link e um `CTkLabel` com `cursor="hand2"`, e nao um `CTkButton`: parece o
    que e (um endereco), e nao compete visualmente com os botoes de acao logo
    acima.
    """
    footer = ctk.CTkFrame(parent, fg_color="transparent")

    fonte = ctk.CTkFont(size=11)
    ctk.CTkLabel(
        footer,
        text=f"PGN Tradutor Pro  ·  {APP_AUTHORS}  ·  ",
        font=fonte,
        text_color=("gray45", "gray60"),
    ).pack(side=tk.LEFT)

    link = ctk.CTkLabel(
        footer,
        text=APP_REPOSITORY_URL,
        font=fonte,
        text_color=("#1f6aa5", "#5aa9e6"),
        cursor="hand2",
    )
    link.pack(side=tk.LEFT)
    link.bind("<Button-1>", open_repository)

    return footer, link


def setup_main_ui(app):
    main_frame = ctk.CTkFrame(app.root, fg_color="transparent")
    main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

    input_section, input_frame = create_section(main_frame, "Seleção de Arquivo/Pasta")
    input_section.pack(fill=tk.X, pady=(0, 8))

    ctk.CTkLabel(input_frame, text="Arquivo/Pasta PGN:").grid(
        row=0, column=0, sticky=tk.W, pady=5
    )
    ctk.CTkEntry(input_frame, textvariable=app.source_path).grid(
        row=0, column=1, sticky=tk.EW, padx=8, pady=5
    )

    btn_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
    btn_frame.grid(row=0, column=2, sticky=tk.E)
    ctk.CTkButton(btn_frame, text="Arquivo", width=92, command=app.select_file).pack(
        side=tk.LEFT, padx=(0, 6)
    )
    ctk.CTkButton(btn_frame, text="Pasta", width=82, command=app.select_directory).pack(
        side=tk.LEFT
    )

    ctk.CTkCheckBox(
        input_frame,
        text="Processar subdiretórios",
        variable=app.process_subdirs,
    ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

    input_frame.columnconfigure(1, weight=1)

    lang_section, lang_frame = create_section(main_frame, "Idioma de Tradução")
    lang_section.pack(fill=tk.X, pady=(0, 8))

    # A ORIGEM vem primeiro, e nao e so ordem de leitura: ela e a escolha que o
    # usuario precisa rever a cada pasta nova, enquanto o destino costuma ser
    # sempre o mesmo. Deixa-la embaixo, depois de sete botoes, e o desenho que
    # faz alguem traduzir um PGN italiano declarando espanhol.
    ctk.CTkLabel(lang_frame, text="Idioma de origem:").grid(row=0, column=0, sticky=tk.W)

    source_sel = ctk.CTkFrame(lang_frame, fg_color="transparent")
    source_sel.grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
    # "Detectar" e o primeiro e o padrao: e o comportamento que o programa sempre
    # teve (`sl=auto`), entao quem nao mexer no seletor continua onde estava.
    app.source_language_buttons = []
    for i, (name, code) in enumerate([(AUTO_SOURCE_LABEL, "")] + LANGUAGES):
        botao = ctk.CTkRadioButton(
            source_sel,
            text=name,
            value=code,
            variable=app.source_language,
            width=80,
        )
        botao.grid(row=0, column=i, padx=(0, 8))
        app.source_language_buttons.append(botao)

    ctk.CTkLabel(lang_frame, text="Idioma de destino:").grid(
        row=1, column=0, sticky=tk.W, pady=(6, 0)
    )

    lang_sel = ctk.CTkFrame(lang_frame, fg_color="transparent")
    lang_sel.grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=(6, 0))
    for i, (name, code) in enumerate(LANGUAGES):
        ctk.CTkRadioButton(
            lang_sel,
            text=name,
            value=code,
            variable=app.target_language,
            width=80,
        ).grid(row=0, column=i, padx=(0, 8))

    action_section, action_frame = create_section(main_frame, "Controle de Tradução")
    action_section.pack(fill=tk.X, pady=(0, 8))

    app.progress = ctk.CTkProgressBar(action_frame, mode="determinate")
    app.progress.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(0, 10))
    app.progress.set(0)

    btns_line = ctk.CTkFrame(action_frame, fg_color="transparent")
    btns_line.pack(fill=tk.X)

    app.start_button = ctk.CTkButton(
        btns_line,
        text="Iniciar Tradução",
        command=app.start_translation,
    )
    app.start_button.pack(side=tk.LEFT, padx=(0, 6))

    app.pause_button = ctk.CTkButton(
        btns_line,
        text="Pausar",
        command=app.pause_translation,
        state="disabled",
    )
    app.pause_button.pack(side=tk.LEFT, padx=6)

    app.resume_button = ctk.CTkButton(
        btns_line,
        text="Continuar",
        command=app.resume_translation,
        state="disabled",
    )
    app.resume_button.pack(side=tk.LEFT, padx=6)

    app.cancel_button = ctk.CTkButton(
        btns_line,
        text="Cancelar",
        command=app.cancel_translation,
        state="disabled",
    )
    app.cancel_button.pack(side=tk.LEFT, padx=6)

    # Fica ao lado dos controles de execucao, e nao em "Ferramentas": e uma forma
    # de iniciar uma traducao, so que restrita ao que ficou devendo (ROADMAP 7.3).
    app.retry_button = ctk.CTkButton(
        btns_line,
        text="Reprocessar Falhas",
        command=app.retry_failed_translation,
    )
    app.retry_button.pack(side=tk.LEFT, padx=6)

    tools_section, tools_frame = create_section(main_frame, "Ferramentas")
    tools_section.pack(fill=tk.X, pady=(0, 8))

    grid_button_row(
        tools_frame,
        [
            {"text": "Estatísticas do BD", "command": app.show_db_stats},
            {"text": "Exportar CSV", "command": app.export_csv},
            # Ao lado do CSV porque e a mesma acao vista de outro angulo: o CSV e
            # para a planilha, o TMX e para as ferramentas de traducao (ROADMAP 19,
            # item 8).
            {"text": "Exportar TMX", "command": app.export_tmx},
            {"text": "Importar CSV", "command": app.import_csv},
            {"text": "Backup BD", "command": app.backup_database},
            {"text": "Restaurar BD", "command": app.restore_database},
            {"text": "Aplicar Automaticas", "command": app.apply_automatic_rules},
            {"text": "Normalizar PGN", "command": app.normalize_pgn_metadata},
            {"text": "Editar Traduções", "command": app.open_edit_window},
            {"text": "Editar Glossário", "command": app.open_glossary_window},
            {"text": "Corrigir Lances", "command": app.fix_move_notation},
            # A abertura ja reavalia sozinha quando as heuristicas mudam
            # (garantia Q2); este botao e para quem cancelou aquela, ou quem quer
            # conferir em que versao o banco esta.
            {"text": "Reavaliar QA", "command": app.reevaluate_quality_warnings},
            # As duas ultimas, e em vermelho. Sao as unicas acoes da janela que
            # destroem trabalho, e ficam distinguiveis a distancia de um clique
            # apressado — a confirmacao digitada e a defesa, isto e o aviso.
            {
                "text": "Zerar Traduções",
                "command": app.reset_translations,
                "fg_color": DESTRUCTIVE_COLOR,
                "hover_color": DESTRUCTIVE_HOVER_COLOR,
            },
            {
                "text": "Zerar Glossário",
                "command": app.reset_glossary,
                "fg_color": DESTRUCTIVE_COLOR,
                "hover_color": DESTRUCTIVE_HOVER_COLOR,
            },
        ],
        columns=4,
    )

    # O rodape e empacotado ANTES do log, ancorado embaixo. A ordem nao e
    # estetica: o packer do Tk distribui na ordem em que recebe, e o log leva
    # `expand=True` — ele toma toda a cavidade restante, e quem vier depois fica
    # com altura zero. Empacotado assim, o rodape reserva a faixa dele e o log
    # expande no que sobra. Com a ordem ingenua o rodape existe, nao e mapeado, e
    # some da tela sem erro nenhum.
    footer, app.repository_link = create_credits_footer(main_frame)
    footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

    log_section, log_frame = create_section(main_frame, "Log de Processamento")
    log_section.pack(fill=tk.BOTH, expand=True)

    app.log_text = ctk.CTkTextbox(log_frame, height=170, wrap=tk.WORD)
    app.log_text.pack(fill=tk.BOTH, expand=True)
    app.log_text.configure(state="disabled")
