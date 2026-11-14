import unittest

from tradutor_pgn import translation_worker


class GoogleEstimateTests(unittest.TestCase):
    def test_estimate_excludes_cached_empty_and_repeated_comments(self):
        files = {"a": ["cached", "hello", "hello", ""], "b": ["hello", "world"]}
        estimate = translation_worker.estimate_google_work(files, {"cached": "pronto"}, [])
        self.assertEqual(estimate.comments, 2)
        self.assertEqual(estimate.batches, 2)
        self.assertEqual(estimate.characters, len("hello") + len("world"))

    def test_empty_and_cached_inputs_need_no_batches(self):
        estimate = translation_worker.estimate_google_work({"a": ["cached", ""]}, {"cached": "x"}, [])
        self.assertEqual((estimate.comments, estimate.batches, estimate.characters), (0, 0, 0))
