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
