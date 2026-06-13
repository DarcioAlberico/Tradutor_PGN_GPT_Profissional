import json
import os
import sys
from datetime import datetime


SETTINGS_FILENAME = "pgn_tradutor_pro_settings.json"
MAX_EDITOR_DRAFTS = 200


def default_settings_path():
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, SETTINGS_FILENAME)


def load_settings(path=None):
    if path is None:
        path = default_settings_path()

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def save_settings(settings, path=None):
    if path is None:
        path = default_settings_path()

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def editor_draft_key(db_path, target_language, comment_id):
    normalized_db = os.path.normcase(os.path.abspath(str(db_path or "")))
    return f"{normalized_db}::{target_language or ''}::{int(comment_id)}"


def _ensure_editor_drafts(settings):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        drafts = {}
        settings["editor_drafts"] = drafts
    return drafts


def prune_editor_drafts(settings, max_entries=MAX_EDITOR_DRAFTS):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return 0

    max_entries = max(0, int(max_entries))
    overflow = len(drafts) - max_entries
    if overflow <= 0:
        return 0

    def sort_key(item):
        _key, draft = item
        if isinstance(draft, dict):
            return draft.get("updated_at") or ""
        return ""

    removed = 0
    for key, _draft in sorted(drafts.items(), key=sort_key)[:overflow]:
        drafts.pop(key, None)
        removed += 1
    return removed


def set_editor_draft(
    settings,
    db_path,
    target_language,
    comment_id,
    text,
    base_translation,
    updated_at=None,
    max_entries=MAX_EDITOR_DRAFTS,
):
    text = text or ""
    base_translation = base_translation or ""
    key = editor_draft_key(db_path, target_language, comment_id)
    drafts = _ensure_editor_drafts(settings)

    if text == base_translation:
        return drafts.pop(key, None) is not None

    drafts[key] = {
        "text": text,
        "base_translation": base_translation,
        "updated_at": updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    prune_editor_drafts(settings, max_entries)
    return True


def get_editor_draft(settings, db_path, target_language, comment_id, current_translation):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return None

    draft = drafts.get(editor_draft_key(db_path, target_language, comment_id))
    if not isinstance(draft, dict):
        return None

    text = draft.get("text")
    base_translation = draft.get("base_translation")
    if not isinstance(text, str) or not isinstance(base_translation, str):
        return None

    current_translation = current_translation or ""
    if base_translation != current_translation or text == current_translation:
        return None

    return {
        "text": text,
        "base_translation": base_translation,
        "updated_at": draft.get("updated_at") or "",
    }


def clear_editor_draft(settings, db_path, target_language, comment_id):
    drafts = settings.get("editor_drafts")
    if not isinstance(drafts, dict):
        return False
    return drafts.pop(editor_draft_key(db_path, target_language, comment_id), None) is not None
