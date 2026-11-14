import os
import time
import stat
import weakref
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tradutor_pgn import translation_library


def test_old_staging_directories_are_listed_without_modification(tmp_path):
    old = tmp_path / ".livro-BR.tmp-abc123"
    fresh = tmp_path / ".outro.tmp-abc123"
    unrelated = tmp_path / "livro-BR"
    for path in (old, fresh, unrelated):
        path.mkdir()
    (old / "original.pgn").write_text("dados", encoding="utf8")
    now = time.time()
    os.utime(old, (now - 100000, now - 100000))
    before = (old / "original.pgn").read_bytes()
    result = translation_library.inspect_staging_directories(tmp_path, now=now)
    assert result.total == 1
    assert result.entries[0].name == old.name
    assert (old / "original.pgn").read_bytes() == before


def test_inspection_limits_examples_and_ignores_future_directories(tmp_path):
    now = time.time()
    for index in range(3):
        path = tmp_path / f".obra{index}.tmp-abcdef"
        path.mkdir()
        stamp = now - 100000 - index
        os.utime(path, (stamp, stamp))
    future = tmp_path / ".futuro.tmp-abcdef"
    future.mkdir()
    os.utime(future, (now + 100, now + 100))
    result = translation_library.inspect_staging_directories(tmp_path, now=now, max_entries=2)
    assert result.total == 3 and len(result.entries) == 2
    assert result.future_count == 1
    assert result.entries[0].name == ".obra2.tmp-abcdef"
    assert "data futura" in translation_library.format_staging_inspection(result)


def test_inspection_keeps_only_bounded_examples_in_memory(tmp_path):
    retained = weakref.WeakSet()
    real_entry = translation_library.StagingEntry
    def track_entry(*args):
        entry = real_entry(*args)
        retained.add(entry)
        assert len(retained) <= 4
        return entry
    items = [SimpleNamespace(name=f".obra{i:03}.tmp-id", stat=Mock(return_value=
             SimpleNamespace(st_mode=stat.S_IFDIR, st_mtime=i))) for i in range(100)]
    iterator = Mock()
    iterator.__enter__ = Mock(return_value=iter(reversed(items)))
    iterator.__exit__ = Mock(return_value=False)
    with patch.object(translation_library.os, "scandir", return_value=iterator), \
         patch.object(translation_library, "StagingEntry", side_effect=track_entry):
        result = translation_library.inspect_staging_directories(tmp_path, now=100000, max_entries=3)
    assert result.total == 100
    assert [entry.name for entry in result.entries] == [f".obra{i:03}.tmp-id" for i in range(3)]


def test_inspection_orders_equal_ages_by_name_and_supports_no_examples(tmp_path):
    for name in (".z.tmp-id", ".b.tmp-id", ".A.tmp-id"):
        path = tmp_path / name
        path.mkdir()
        os.utime(path, (1, 1))
    result = translation_library.inspect_staging_directories(tmp_path, now=100000, max_entries=2)
    assert result.total == 3
    assert [entry.name for entry in result.entries] == [".A.tmp-id", ".b.tmp-id"]
    no_examples = translation_library.inspect_staging_directories(tmp_path, now=100000, max_entries=0)
    assert no_examples.total == 3 and no_examples.entries == ()


def test_inspection_can_be_cancelled(tmp_path):
    (tmp_path / ".obra.tmp-abcdef").mkdir()
    with pytest.raises(translation_library.StagingInspectionCanceled):
        translation_library.inspect_staging_directories(tmp_path, should_cancel=lambda: True)


def test_disappearing_candidate_does_not_report_complete_empty_scan(tmp_path):
    item = SimpleNamespace(name=".obra.tmp-abcdef", stat=Mock(side_effect=FileNotFoundError("mudou")))
    iterator = Mock()
    iterator.__enter__ = Mock(return_value=iter([item]))
    iterator.__exit__ = Mock(return_value=False)
    with patch("tradutor_pgn.translation_library.os.scandir", return_value=iterator):
        with pytest.raises(FileNotFoundError):
            translation_library.inspect_staging_directories(tmp_path)


def test_report_explains_uncertainty_and_limits_examples():
    result = translation_library.StagingInspection(2, (translation_library.StagingEntry(".obra.tmp-abc", 90000),))
    report = translation_library.format_staging_inspection(result)
    assert "2" in report and ".obra.tmp-abc" in report
    assert "ativa" in report.lower() and "não" in report.lower()
    assert "1" in report


def test_report_uses_the_configured_age_threshold():
    result = translation_library.StagingInspection(0, (), min_age_seconds=3600)
    assert "1 hora" in translation_library.format_staging_inspection(result)


@pytest.mark.parametrize("threshold", [-1, float("nan"), float("inf")])
def test_invalid_age_threshold_is_rejected(tmp_path, threshold):
    with pytest.raises(ValueError):
        translation_library.inspect_staging_directories(tmp_path, min_age_seconds=threshold)


def test_library_action_reports_the_inspection_result(tmp_path):
    from tradutor_pgn.translation_library_window import TranslationLibraryWindow
    window = SimpleNamespace(closed=False, root_path=tmp_path, win=object())
    result = translation_library.StagingInspection(0, ())
    def run(_parent, _title, work, on_success=None, **_kwargs):
        on_success(work(SimpleNamespace(cancelado=lambda: False)))
    with patch("tradutor_pgn.translation_library_window.run_with_progress", side_effect=run), \
         patch("tradutor_pgn.translation_library_window.inspect_staging_directories", return_value=result), \
         patch("tradutor_pgn.translation_library_window.messagebox.showinfo") as dialog:
        TranslationLibraryWindow.inspect_staging(window)
    assert "0" in dialog.call_args.args[1]
    assert "ativa" in dialog.call_args.args[1].lower()


def test_reparse_points_are_not_reported_as_temporary_folders(tmp_path):
    fake_info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400, st_mtime=0)
    item = SimpleNamespace(name=".obra.tmp-abcdef", stat=Mock(return_value=fake_info))
    iterator = Mock()
    iterator.__enter__ = Mock(return_value=iter([item]))
    iterator.__exit__ = Mock(return_value=False)
    with patch("tradutor_pgn.translation_library.os.scandir", return_value=iterator):
        assert translation_library.inspect_staging_directories(tmp_path, now=100000).total == 0
