---
name: run-tradutor-pgn
description: Rodar, abrir, lançar, dirigir ou tirar screenshot do PGN Tradutor Pro — o app CustomTkinter de tradução de comentários PGN. Use para confirmar uma mudança na interface no app de verdade (não só nos testes), abrir o editor de traduções ou o de glossário, ou capturar a tela de uma janela.
---

# Rodar o PGN Tradutor Pro

App desktop **Tkinter/CustomTkinter**. Não há Playwright, DevTools nem
`chromium-cli` que sirvam: a única forma de dirigi-lo é **carregá-lo no próprio
processo** e bombear o laço de eventos à mão. O driver disso é
`.claude/skills/run-tradutor-pgn/driver.py`.

Caminhos abaixo são relativos à raiz do projeto.

## Pré-requisitos

Verificado no Windows 10 com Python 3.13 (`.python-version`) e display real.

Use **`python -m pip`**, nunca `pip` solto. Nesta máquina o `pip` do PATH é o do
Python 3.12 enquanto o `python` é o 3.13 — instalar com `pip` põe os pacotes no
interpretador errado e o driver falha com `ModuleNotFoundError` num pacote que
você acabou de instalar.

```bash
python -m pip install -r requirements.txt
```

O driver também usa **Pillow** para capturar tela. Ele **não** está em
`requirements.txt` porque o app não precisa dele — só a ferramenta:

```bash
python -m pip install pillow
```

Confira antes de investigar qualquer coisa:

```bash
python -c "import sys, customtkinter, PIL; print(sys.version.split()[0], 'ok')"
```

## Rodar (caminho do agente) — use este

```bash
python .claude/skills/run-tradutor-pgn/driver.py
```

Abre o app, roda uma tradução completa pelo botão "Iniciar Tradução", abre as
duas janelas de edição, exercita o `Ctrl+B` (negrito na seleção) e o aviso de
conflito do glossário, e grava PNGs em
`.claude/skills/run-tradutor-pgn/capturas/`. Sai sozinho.

**Olhe as capturas.** Um quadro em branco é falha de lançamento disfarçada de
sucesso.

Como biblioteca, para dirigir o que você precisa:

```python
import sys; sys.path.insert(0, ".claude/skills/run-tradutor-pgn")
from driver import Driver

with Driver() as d:
    d.seed(traducoes=[("The bishop moves.", "O bispo move.")],
           glossario_entradas=[("bishop", "bispo", "suggestion")])
    editor = d.open_translation_editor()   # devolve o TranslationEditor
    editor.select_index(0)
    d.pump()
    d.key(editor.trans_text, "<Control-b>")
    d.shot("minha-captura.png", editor.win)
```

`open_translation_editor()` devolve a **instância** da classe, então todo método
é alcançável: `select_index`, `save_changes`, `apply_one`, `go_to_id`,
`toggle_bold_selection`, e todos os widgets por nome (`editor.trans_text`,
`editor.search_mode_segment`, `editor.btn_bold`…).

## Rodar uma tradução pela janela principal

É o fluxo central do app, e passa por código que `run_worker` **não** toca:
`app_actions.start_translation` (arquivo de log, estado dos botões, flags), a
thread, e o `_reset_buttons` do fim.

```python
with Driver() as d:
    d.fake_network()                       # ANTES de iniciar, senão vai à rede
    pgn = d.escreve_pgn("partida.pgn",
        '[Event "T"]

1. e4 {A comment.} *
')

    d.start_translation(pgn)               # preenche o caminho e clica
    assert d.app.start_button.cget("state") == "disabled"
    d.wait_translation(90)                 # ver o aviso abaixo: usa mainloop()
    print(d.log())                         # o log da janela
```

**`wait_translation` usa `mainloop()`, não `pump()`** — é a única parte do driver
onde isso vale, e o motivo só aparece com thread no meio:

> O worker roda em outra thread e agenda tudo por `root.after` (garantia C1). O
> Tk só aceita chamadas de outra thread enquanto a main thread está **dentro do
> `mainloop()`**. Bombeando com `update()` num laço ela não está, e o worker
> morre com `RuntimeError: main thread is not in main loop` — que na tela
> aparece como `[ERRO GERAL]` e nenhum PGN gerado. O padrão certo é entrar no
> `mainloop()` e sair por `quit()` de um `after` periódico; `quit()` encerra o
> laço sem destruir os widgets, então a janela continua utilizável depois.

## Dirigir o editor de glossário

Desde o item 3.5 do ROADMAP as duas janelas se dirigem do mesmo jeito: as duas
aberturas devolvem a instância (`TranslationEditor`, `GlossaryEditor`) e todo
método e widget é alcançável pelo nome.

```python
with Driver() as d:
    d.seed(glossario_entradas=[("rook", "torre", "suggestion"),
                               ("rook", "torre alta", "suggestion")])
    g = d.open_glossary_editor()                 # a instancia GlossaryEditor

    g.select_entry(1)                            # a regra que perde o conflito
    d.pump()
    print(d.label_starting(g.win, "Conflito em"))     # o aviso de S9, na tela
    g.keep_this_rule()                                # resolve o conflito
    print(len(g.state.entries), "entradas")
```

O estado vive em `g.state` (`entries`, `filtered_indices`, `page_index`,
`selected_index`, `dirty`) e os widgets são atributos de `g` (`g.orig_text`,
`g.new_text`, `g.filter_segment`, `g.rows_frame`). `d.open_glossary_editor()`
repassa `initial_original=`/`initial_replacement=`, que é como o editor de
traduções manda um trecho para cá.

**Os helpers de árvore continuam valendo, e para uma coisa específica:** conferir
o que está na **tela**. Um método diz o que o programa acha; um widget diz o que o
usuário vê — e o defeito costuma estar entre os dois.

- `d.button(g.win, "Salvar")` — rótulo exato; se errar, o erro lista os que existem.
- `d.button_containing(g.win, "torre alta")` — as **linhas da lista** têm rótulo de
  três linhas (`AVISO  #1  -  Sugestão / De: rook / Para: torre`), então é assim
  que se clica numa entrada como um usuário clicaria.
- `d.label_starting(g.win, "Conflito em")` — lê rótulos **visíveis**. O `so_visiveis`
  importa: o aviso de conflito existe sempre como widget e apenas sai do grid
  quando não há conflito; ler sem checar acha aviso que não está na tela.

## Dirigir o worker de tradução — sem janela nenhuma

O worker (`translation_worker.run_translation`) é onde a maior parte das
mudanças acontece, e **não precisa de GUI**. Ele exige nove atributos de um
objeto `app`, e nenhum é widget: o driver traz um `HeadlessApp` com todos.

```bash
python .claude/skills/run-tradutor-pgn/driver.py --worker
```

Roda o pipeline inteiro — detecção de codificação, lotes, regras de limpeza e
automáticas, cache, gravação no banco e geração do PGN — com a **rede
substituída** por uma função determinista. Nenhuma requisição sai.

Para exercitar a rede de verdade (endpoint público do Google Translate; use
arquivos pequenos):

```bash
python .claude/skills/run-tradutor-pgn/driver.py --worker --online
```

Como biblioteca, sobre o seu próprio PGN:

```python
import sys; sys.path.insert(0, ".claude/skills/run-tradutor-pgn")
from driver import run_worker

app, saida, dados = run_worker('[Event "T"]

1. e4 {A comment.} *
')
print(open(saida, encoding="utf-8").read())   # o PGN traduzido
print(app.logs)                               # o log da execução
print(dados)                                  # banco e arquivos, para inspecionar
```

`run_worker(..., traduzir=fn)` troca a camada de rede pela sua função — é assim
que se exercita falha de API, resposta desalinhada, 429 e o disjuntor, sem tocar
a rede:

```python
def sempre_falha(texto, *a, **k):
    return None          # a API nao respondeu -> garantia B3

app, saida, dados = run_worker(PGN, traduzir=sempre_falha)
```

O diretório devolvido **não é apagado** — é onde ficam o PGN gerado, o banco e o
log para você olhar.

## Rodar (caminho humano)

```bash
python PGN_Tradutor_Pro.py
```

Abre a janela e fica em `mainloop()` até você fechar. **Inútil para um agente** —
bloqueia o terminal e não dá handle nenhum sobre o app.

## Testes

```bash
python -m unittest discover -s tests
```

366 testes, ~70 s. Os de `test_editor_windows.py` e `test_main_window.py` abrem
janelas de verdade — os editores e a janela principal — e são pulados onde não
houver display. O harness comum deles (gate de display, silenciamento de
diálogos, sandbox de caminhos) está em `tests/gui_harness.py`.

## Gotchas

Todos custaram tempo nesta sessão.

- **`sys.argv[0]` decide onde ficam TODOS os dados.** Banco, glossário,
  settings, `backups/` e `logs/` saem de `dirname(abspath(sys.argv[0]))`. O
  driver aponta isso para um diretório temporário, e não é preciosismo: na
  abertura o app roda a retenção de `backups/` (garantia S8), então dirigi-lo
  sobre o diretório do projeto **apaga backups reais do usuário**. Use
  `Driver(sandbox=False)` só quando o alvo for exatamente o dado real.

- **`mainloop()` não serve; bombeie com `update()`.** É o que `Driver.pump()`
  faz. Sem isso nada é desenhado e as capturas saem pretas.

- **Espere ≥250 ms depois de abrir uma janela.** `bring_window_to_front` agenda
  `after(50)` e `after(200)`; antes disso a janela não tem posição final e a
  captura sai torta ou pega a janela de trás.

- **`event_generate` NÃO entrega alguns atalhos sem um widget com foco.**
  `<Control-f>` é um deles; `<Control-s>` chega. Um teste de atalho sem
  `focus_set()` passa sem exercitar nada. `Driver.key()` já foca antes.

- **`messagebox` bloqueia para sempre.** `run_translation` tem um
  `except Exception` que chama `showerror`; num driver isso trava o processo
  esperando um clique que nunca vem. O driver silencia todo o `messagebox` (e o
  `filedialog`) por padrão.

- **`tk_popup` é modal.** O menu de contexto das sugestões, chamado de verdade,
  espera um clique — ~40 s até desistir. O driver o substitui.

- **`CTkButton.invoke()` chama o `command` direto**, sem passar pelo Tcl. Logo a
  exceção volta para quem chamou, e **não** pelo `report_callback_exception`.
  Para exercitar o relator de erros, use `widget.after(0, ...)`.

- **Cancele os `after` pendentes antes de `destroy()`**, senão o Tk imprime
  `invalid command name` no meio da saída. `Driver.stop()` faz isso.

- **Windows não apaga arquivo SQLite aberto.** Feche as conexões antes de
  remover o sandbox; o driver usa `ignore_errors=True` porque o app pode ter
  deixado alguma viva.

- **Thread + Tk exige `mainloop()`.** Ver a seção da janela principal. Vale para
  qualquer coisa que rode em thread e toque a interface — hoje, a tradução.

- **O worker chama `messagebox` no fim, pela fila do Tk.** Numa raiz que executa
  na hora (é o caso do `HeadlessApp`), isso abre um diálogo modal de verdade e
  trava o processo. `run_worker` silencia; se você chamar `run_translation`
  direto, silencie você.

- **A função de tradução falsa precisa preservar o separador ` ||| `.** O worker
  junta o lote com ele e reencontra as partes para realinhar (garantia B2). Uma
  falsa que devolva texto solto cai no caminho individual e você mede outra
  coisa sem perceber.

- **`ImageGrab` fotografa a TELA.** A janela precisa estar visível e por cima —
  uma janela `withdraw()`n sai como o que estiver atrás dela. Não use com a
  máquina bloqueada.

## Troubleshooting

| Sintoma | Causa e correção |
|---|---|
| Captura preta ou da janela errada | Bombeou pouco. `d.pump(1.5)` depois de abrir. |
| O processo trava e não retorna | Algum `messagebox`/`filedialog`/`tk_popup` modal escapou do silenciamento. Veja quais módulos o `Driver.start()` cobre. |
| `TclError: invalid command name ...` na saída | `after` pendente disparando após o `destroy`. Use `Driver.stop()`/o `with`. |
| Atalho não faz nada | Faltou foco. Use `d.key(widget, "<Control-x>")`. |
| `PermissionError` ao limpar o sandbox | Conexão SQLite viva. Inofensivo — o diretório fica em `%TEMP%`. |
| `backups/` do projeto encolheu | Você rodou com `--real` ou `sandbox=False`. É a retenção S8 fazendo o trabalho dela. |
| `ModuleNotFoundError` logo após instalar | `pip` e `python` são interpretadores diferentes. Sempre `python -m pip`. |
| `LookupError: botao 'X' nao encontrado` | O erro lista os rótulos existentes — provavelmente acento ou espaço. |
| Aviso de conflito lido mas não visível | `label_starting(..., so_visiveis=False)` pega widget fora do grid. |
| `--worker` trava no fim da execução | Algum `messagebox` do worker não foi silenciado. |
| Worker cai na tradução individual sem motivo | Sua função falsa não preservou o separador de lote (B2). |
| `[ERRO GERAL] main thread is not in main loop` | Esperou a tradução com `pump()` em vez de `wait_translation()`. |
| Tradução termina mas nenhum PGN aparece | Ou é o caso acima, ou a API não respondeu — sem resposta o PGN não é gerado de propósito (B3). |
