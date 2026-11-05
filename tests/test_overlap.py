from itertools import combinations
import random
import unittest

from desk_tidy.core import frames_overlap
from desk_tidy.overlap import analyze_overlaps


class OverlapTest(unittest.TestCase):
    def assert_oracle(self, frames):
        expected = {(i, j) for i, a in enumerate(frames) for j, b in enumerate(frames[i + 1:], i + 1) if frames_overlap(a, b)}
        result = analyze_overlaps(frames)
        self.assertEqual(result.count, len(expected))
        self.assertEqual(result.affected, {i for pair in expected for i in pair})
        self.assertTrue({tuple(sorted(pair)) for pair in result.examples} <= expected)
        self.assertEqual(len(result.examples), min(len(expected), 32))

    def test_exhaustive_small_rectangles_match_pairwise_oracle(self):
        frames = [{"x": x, "y": y, "width": w, "height": h} for x, y, w, h in
                  [(x, y, w, h) for x in (-2, 0) for y in (-2, 0) for w in (1, 3) for h in (1, 3)]]
        for case in combinations(frames, 3):
            self.assert_oracle(case)

    def test_random_quarter_point_rectangles_and_dense_stacks_match_oracle(self):
        rng = random.Random(9)
        for _ in range(300):
            self.assert_oracle([{"x": rng.randrange(-40, 40) / 4, "y": rng.randrange(-40, 40) / 4,
                                 "width": rng.randrange(1, 60) / 4, "height": rng.randrange(1, 60) / 4} for _ in range(rng.randrange(1, 40))])
        self.assert_oracle([{"x": 0, "y": 0, "width": 100, "height": 100}] * 200)

    def test_large_non_overlapping_set_has_no_quadratic_pair_output(self):
        frames = [{"x": i * 12, "y": 0, "width": 10, "height": 10} for i in range(10_000)]
        result = analyze_overlaps(frames)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.examples, ())
        self.assertFalse(result.affected)
