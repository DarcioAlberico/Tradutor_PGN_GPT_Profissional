"""Ensaio integrado de recuperação em outra pasta, sem usar dados reais."""

import json
import shutil
from contextlib import closing

from tradutor_pgn.database import initialize_database, save_translation
from tradutor_pgn.db_backup import create_database_backup, restore_database_from_backup
from tradutor_pgn.glossary_catalog import GlossaryCatalog, GlossaryEntryDraft
from tradutor_pgn.settings import load_settings, save_settings
from tradutor_pgn.translation_output import publish_translation_bundle


def test_recover_translation_database_glossary_settings_and_pgn_on_new_machine(tmp_path):
    original = tmp_path / "maquina-antiga"
    original.mkdir()
    db_path = original / "traducoes.db"
    with closing(initialize_database(str(db_path))) as conn:
        save_translation(conn.cursor(), "The rook is active.", "A torre está ativa.", "pt", "en")
        conn.commit()

    catalog = GlossaryCatalog(str(original / "glossario-v2.db"))
    catalog.initialize()
    saved_entry = catalog.add(GlossaryEntryDraft("rook", "torre", scope="pt"), 1).entry

    settings_path = original / "pgn_tradutor_pro_settings.json"
    save_settings({"font_size": 17}, str(settings_path))
    pgn = original / "partida.pgn"
    pgn.write_text('[Event "Teste"]\n\n1. e4 {The rook is active.} 1-0\n', encoding="utf-8")

    def generate(path):
        with open(path, "w", encoding="utf-8") as file:
            file.write('[Event "Teste"]\n\n1. e4 {A torre está ativa.} 1-0\n')
        return True

    output = original / "Minhas Traduções"
    result = publish_translation_bundle(str(pgn), "pt", str(output), generate)
    assert result.status == "published"

    db_backup = create_database_backup(str(db_path), backup_dir=str(original / "backups"))
    glossary_backup = original / "backups" / "glossario.db"
    catalog.backup(str(glossary_backup))
    old_snapshot = catalog.list_entries()

    medium = tmp_path / "copia"
    medium.mkdir()
    shutil.copy2(db_backup, medium / "traducoes.db")
    shutil.copy2(glossary_backup, medium / "glossario.db")
    shutil.copy2(settings_path, medium / settings_path.name)
    shutil.copytree(output, medium / output.name)

    recovered = tmp_path / "maquina-nova"
    recovered.mkdir()
    target = recovered / "traducoes.db"
    with closing(initialize_database(str(target))):
        pass
    restore_database_from_backup(str(target), str(medium / "traducoes.db"))
    with closing(initialize_database(str(target))) as conn:
        rows = conn.execute("SELECT original_comment, translated_comment FROM comments").fetchall()
        assert [tuple(row) for row in rows] == [("The rook is active.", "A torre está ativa.")]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    new_catalog = GlossaryCatalog(str(recovered / "glossario-v2.db"))
    new_catalog.initialize()
    new_catalog.restore(str(medium / "glossario.db"), new_catalog.list_entries().catalog_revision)
    restored = new_catalog.list_entries()
    assert [(entry.stable_id, entry.original_text, entry.replacement_text) for entry in restored.entries] == [
        (saved_entry.stable_id, "rook", "torre")
    ]
    shutil.copy2(medium / settings_path.name, recovered / settings_path.name)
    assert load_settings(str(recovered / settings_path.name))["font_size"] == 17
    shutil.copytree(medium / output.name, recovered / output.name)
    originals = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    copies = {p.relative_to(recovered / output.name): p.read_bytes()
              for p in (recovered / output.name).rglob("*") if p.is_file()}
    assert copies == originals
    assert catalog.list_entries() == old_snapshot
    assert json.loads(settings_path.read_text(encoding="utf-8"))["font_size"] == 17
