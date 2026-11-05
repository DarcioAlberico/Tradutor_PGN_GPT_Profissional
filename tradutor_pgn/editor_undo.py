"""Identify native Text undo groups without comparing their text contents.

Tk 8.6 exposes no undo position. This command proxy owns the separators while
Tk retains the text, inverse commands and redo stack. Consecutive insertions
or deletions stay grouped; explicit separators and whole-text edits retain
their normal boundaries.
"""


class TextUndoHistory:
    def __init__(self, text):
        self.text = text
        self.tk = text.tk
        self.original = text._w + "_undo_original"
        self.undo = []
        self.redo = []
        self.boundary = True
        self.mode = None
        self.automatic = self.tk.getboolean(text.cget("autoseparators"))
        self.replaying = False
        self.allow_action = None
        self.tk.call("rename", text._w, self.original)
        self.tk.createcommand(text._w, self._command)
        self.tk.call(self.original, "configure", "-autoseparators", False)
        text.bind("<Destroy>", self._destroy, add="+")

    @property
    def undo_token(self):
        return self.undo[-1] if self.undo else None

    @property
    def redo_token(self):
        return self.redo[-1] if self.redo else None

    def _destroy(self, event):
        if event.widget is self.text:
            self.tk.deletecommand(self.text._w)
            self.allow_action = None
            self.text = self.tk = None

    def _has_deletion(self, indices):
        # The terminal newline is immutable, including in multi-range deletes.
        for index in range(0, len(indices), 2):
            start = indices[index]
            end = indices[index + 1] if index + 1 < len(indices) else f"{start} + 1 chars"
            if self.tk.call(self.original, "compare", end, ">", "end-1c"):
                end = "end-1c"
            if self.tk.call(self.original, "compare", start, "<", end):
                return True
        return False

    def _command(self, *args):
        if self.replaying:
            return self.tk.call(self.original, *args)
        command = args[0]
        if command == "cget" and args[1] == "-autoseparators":
            return int(self.automatic)
        if command in {"configure", "config"} and "-autoseparators" in args[1:]:
            index = args.index("-autoseparators")
            if index + 1 < len(args):
                self.automatic = self.tk.getboolean(args[index + 1])
                args = (*args[:index + 1], False, *args[index + 2:])
        if command == "edit":
            action = args[1]
            if action in {"undo", "redo"}:
                token = self.undo_token if action == "undo" else self.redo_token
                if self.allow_action is not None and not self.allow_action(action, token):
                    return ""
                self.replaying = True
                try:
                    result = self.tk.call(self.original, *args)
                finally:
                    self.replaying = False
                source, target = (self.undo, self.redo) if action == "undo" else (self.redo, self.undo)
                if source:
                    target.append(source.pop())
                self.boundary, self.mode = True, None
                return result
            if action in {"separator", "reset"}:
                self.boundary, self.mode = True, None
                if action == "reset":
                    self.undo.clear()
                    self.redo.clear()
        if command not in {"insert", "delete", "replace"}:
            return self.tk.call(self.original, *args)
        if self.tk.call(self.original, "cget", "-state") == "disabled":
            return self.tk.call(self.original, *args)
        if command == "insert" and not any(args[index] for index in range(2, len(args), 2)):
            return self.tk.call(self.original, *args)
        if command == "delete" and not self._has_deletion(args[1:]):
            return self.tk.call(self.original, *args)
        if command == "replace" and not args[3] and not self._has_deletion(args[1:3]):
            return self.tk.call(self.original, *args)
        boundary = self.boundary or (self.automatic and self.mode != command) or command == "replace"
        if boundary:
            self.tk.call(self.original, "edit", "separator")
        result = self.tk.call(self.original, *args)
        if boundary:
            self.undo.append(object())
        self.redo.clear()
        self.boundary = command == "replace"
        self.mode = command
        return result
