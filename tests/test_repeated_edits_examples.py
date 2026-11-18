from types import SimpleNamespace
from unittest.mock import Mock, patch

from tradutor_pgn.repeated_edits import count_repeated_edits
from tradutor_pgn.repeated_edits_window import RepeatedEditsWindow, format_historical_example


def test_repeated_edits_count_distinct_comments_not_events():
    events = [(7, 'a troca', 'a qualidade'), (7, 'outra troca', 'outra qualidade'),
              (8, 'uma troca', 'uma qualidade')]
    item = count_repeated_edits(events)[0]
    assert item['count'] == 3
    assert item['lines'] == 2
    assert item['example_id'] == 7


def test_examples_keep_the_first_historical_edit_per_comment_and_are_bounded():
    events = [(1, 'a troca', 'a qualidade'), (1, 'outra troca', 'outra qualidade')]
    events += [(n, 'a troca', 'a qualidade') for n in range(2, 10)]
    item = count_repeated_edits(events)[0]
    assert item['lines'] == 9 and item['count'] == 10
    assert [example['comment_id'] for example in item['examples']] == [1, 2, 3, 4, 5]
    assert item['examples'][0]['before'] == 'a troca'
    assert item['examples'][0]['after'] == 'a qualidade'


def test_historical_example_identifies_snapshot_and_limits_large_text():
    text = format_historical_example({'comment_id': 42, 'before': 'a' * 20000, 'after': 'b' * 20000})
    assert '42' in text and 'histórica' in text.lower()
    assert 'truncado' in text.lower() and len(text) < 21000


def test_selected_example_opens_the_correct_current_comment():
    examples = [{'comment_id': 11, 'before': 'a', 'after': 'b'},
                {'comment_id': 22, 'before': 'c', 'after': 'd'}]
    window = SimpleNamespace(current_item=lambda: {'example_id': 11, 'examples': examples},
                             example_choice=SimpleNamespace(get=lambda: '2/2 · ID 22'),
                             editor=SimpleNamespace(jump_to_id=Mock(return_value=True)), win=object())
    window.current_example = lambda: RepeatedEditsWindow.current_example(window)
    RepeatedEditsWindow.show_example(window)
    window.editor.jump_to_id.assert_called_once_with(22)


def test_historical_example_opens_separately_without_editing_database():
    example = {'comment_id': 22, 'before': 'texto antigo', 'after': 'texto novo'}
    window = SimpleNamespace(current_example=lambda: example, win=object())
    with patch('tradutor_pgn.repeated_edits_window.show_historical_example') as dialog:
        RepeatedEditsWindow.show_example_history(window)
    assert 'texto antigo' in dialog.call_args.args[1]
    assert 'texto novo' in dialog.call_args.args[1]


def test_actual_history_keeps_event_frequency_and_unique_comment_count(tmp_path):
    from tradutor_pgn.database import (
        fetch_file_edit_events, initialize_database, record_occurrences,
        resolve_comment_ids, save_translation, update_translation_by_id,
    )
    path = tmp_path / 'cache.db'
    conn = initialize_database(str(path))
    cur = conn.cursor()
    for original in ('first', 'second'):
        save_translation(cur, original, 'a troca', 'pt', 'en')
    ids = resolve_comment_ids(cur, 'pt', ['first', 'second'], 'en')
    source = str(tmp_path / 'game.pgn')
    record_occurrences(cur, source, [(1, 1, 1, 'first'), (2, 1, 2, 'second')], ids)
    for text in ('a qualidade', 'a troca', 'a qualidade'):
        update_translation_by_id(cur, ids['first'], text, history_action='edit')
    update_translation_by_id(cur, ids['second'], 'a qualidade', history_action='edit')
    conn.commit()
    events = fetch_file_edit_events(cur, source, 'pt', 'en')
    item = next(item for item in count_repeated_edits(events) if item['old'] == 'troca')
    assert (item['count'], item['lines']) == (3, 2)
    assert [sample['comment_id'] for sample in item['examples']] == [ids['first'], ids['second']]
    conn.close()
