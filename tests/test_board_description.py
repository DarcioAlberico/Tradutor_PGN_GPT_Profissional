from tradutor_pgn.pgn_positions import describe_fen


def test_piece_lists_identify_color_and_square():
    text = describe_fen('4k3/8/8/8/8/8/4P3/4K3 w - - 0 1')
    assert 'rei em e1' in text and 'peão em e2' in text and 'rei em e8' in text
    assert 'Brancas:' in text and 'Pretas:' in text


def test_reports_side_and_both_castling_rights():
    text = describe_fen('4k3/8/8/8/8/8/8/4K3 b Kq - 0 1')
    assert 'Pretas jogam' in text
    assert 'brancas: pequeno' in text and 'pretas: grande' in text


def test_reports_en_passant_target_without_claiming_capture_is_legal():
    text = describe_fen('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2')
    assert 'd6' in text and 'en passant' in text.lower()


def test_reports_move_counters():
    text = describe_fen('4k3/8/8/8/8/8/8/4K3 w - - 17 24')
    assert '17' in text and '24' in text


def test_partial_or_invalid_fields_are_not_invented():
    text = describe_fen('4k3/8/8/8/8/8/8/4K3')
    assert 'não informado' in text.lower()
    assert 'não disponível' in describe_fen('invalid').lower()
    assert 'não disponível' in describe_fen(None).lower()


def test_invalid_castling_and_en_passant_fields_are_marked_unknown():
    text = describe_fen('4k3/8/8/8/8/8/8/4K3 z KX z9 nope -1')
    assert 'inválido' in text.lower()
    assert 'brancas: pequeno' not in text


def test_large_numeric_counter_does_not_crash():
    text = describe_fen('4k3/8/8/8/8/8/8/4K3 w - - ' + '9' * 5000 + ' 1')
    assert 'Número do lance: 1' in text
