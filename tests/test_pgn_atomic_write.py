from unittest.mock import patch

import pytest

from tradutor_pgn.pgn_utils import write_pgn_pieces


def test_generator_failure_preserves_existing_file_and_cleans_temporary(tmp_path):
    target = tmp_path / "saida.pgn"
    target.write_bytes(b"original")

    def pieces():
        yield "parcial"
        raise OSError("disco cheio")

    with pytest.raises(OSError):
        write_pgn_pieces(str(target), pieces, "utf-8")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_failed_replace_does_not_publish_or_leave_temporary(tmp_path):
    target = tmp_path / "saida.pgn"
    with patch("tradutor_pgn.pgn_utils.os.replace", side_effect=OSError("sem permissao")):
        with pytest.raises(OSError):
            write_pgn_pieces(str(target), lambda: ["resultado"], "utf-8")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_cancel_during_write_preserves_existing_file(tmp_path):
    from threading import Event
    from tradutor_pgn.pgn_utils import PgnWriteCanceled
    target = tmp_path / "saida.pgn"
    target.write_bytes(b"original")
    canceled = Event()
    def pieces():
        yield "primeira parte"
        canceled.set()
        yield "parte restante"
    with pytest.raises(PgnWriteCanceled):
        write_pgn_pieces(str(target), pieces, "utf-8", cancel_flag=canceled)
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_generator_reports_cancellation_during_publication(tmp_path):
    from threading import Event
    from tradutor_pgn import pgn_utils
    target = tmp_path / "saida.pgn"
    target.write_bytes(b"original")
    canceled = Event()
    actual = pgn_utils.write_pgn_pieces
    def write_with_cancel(path, factory, *args, **kwargs):
        def pieces():
            for piece in factory():
                yield piece
                canceled.set()
        return actual(path, pieces, *args, **kwargs)
    messages = []
    with patch.object(pgn_utils, "write_pgn_pieces", side_effect=write_with_cancel):
        result = pgn_utils.generate_translated_pgn("unused", str(target), {}, [], messages.append,
                                                   content="1. e4 *", encoding="utf-8", cancel_flag=canceled)
    assert result is False
    assert target.read_bytes() == b"original"
    assert any("cancelada" in message.lower() for message in messages)
    assert not any("[ERRO]" in message for message in messages)
