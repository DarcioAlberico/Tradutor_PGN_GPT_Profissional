"""One-off helper: convert edit_window.py closures into TranslationEditor class body."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tradutor_pgn" / "edit_window.py"
OUT = ROOT / "tradutor_pgn" / "edit_window" / "_editor_body.py"

START = "def open_translation_editor(app):"
END_MARKERS = ("    win.after(100, restore_pane_positions)",)


def main():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == START)
    end = next(i for i, line in enumerate(lines) if line.strip() == END_MARKERS[0].strip())
    body = lines[start + 1 : end + 1]

    out = []
    out.append("    def open(self):")
    for line in body:
        if line.startswith("    def "):
            name = line.strip().split("(")[0].replace("def ", "")
            if name == "create_text_editor":
                out.append(line.replace("def create_text_editor", "def _create_text_editor", 1))
            else:
                out.append(line.replace("def ", "def ", 1).replace("    def ", "    def ", 1))
        else:
            out.append(line)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(out)} lines)")


if __name__ == "__main__":
    main()
