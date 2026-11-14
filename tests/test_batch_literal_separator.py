from tradutor_pgn.pgn_utils import (
    batch_index_groups,
    isolate_batch_separator_groups,
    split_batch_translation,
)
from tradutor_pgn.translation_worker import estimate_google_work


def test_literal_markers_are_isolated_without_reordering():
    texts = ["primeiro", "com|||marcador", "terceiro", "outro ||| marcador", "ultimo"]
    groups = isolate_batch_separator_groups(texts, batch_index_groups(texts))
    assert groups == [[0], [1], [2], [3], [4]]
    assert [i for group in groups for i in group] == list(range(len(texts)))


def test_ordinary_items_still_share_batches_and_respect_existing_boundaries():
    texts = ["a", "b", "c|||d", "e", "f"]
    assert isolate_batch_separator_groups(texts, [[0, 1, 2], [3, 4]]) == [
        [0, 1], [2], [3, 4]
    ]


def test_single_response_keeps_literal_separator():
    assert split_batch_translation("um ||| dois", 1) == ["um ||| dois"]


def test_google_estimate_accounts_for_isolated_literal_marker():
    estimate = estimate_google_work({"partida.pgn": ["one", "two|||three", "four"]}, {}, [])
    assert estimate.comments == 3
    assert estimate.batches == 3
