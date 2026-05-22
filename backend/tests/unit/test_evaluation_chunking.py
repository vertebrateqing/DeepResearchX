"""Unit tests for chunking quality metrics."""

import pytest

from deep_research.evaluation.chunking_metrics import (
    boundary_bleed_rate,
    empty_chunk_rate,
    length_cv,
    overlap_adherence,
)


class TestBoundaryBleedRate:
    def test_all_clean(self):
        chunks = ["Hello world.\n", "Second paragraph.\n", "Third one."]
        # All end with punctuation/newline, starts are alphanum
        assert boundary_bleed_rate(chunks) == 0.0

    def test_mid_sentence_cut(self):
        chunks = ["Hello wor", "ld. Next sentence."]
        # First chunk ends mid-word (no boundary char)
        assert boundary_bleed_rate(chunks) == 1.0

    def test_mixed(self):
        chunks = ["Hello world.", "Cut mid", "Next sentence."]
        # chunk 2 ends mid-word ('d' is not a boundary char)
        assert boundary_bleed_rate(chunks) == pytest.approx(1 / 3)

    def test_empty_list(self):
        assert boundary_bleed_rate([]) == 0.0


class TestLengthCV:
    def test_identical_lengths(self):
        chunks = ["a" * 100, "b" * 100, "c" * 100]
        assert length_cv(chunks) == 0.0

    def test_varied_lengths(self):
        chunks = ["a" * 100, "b" * 50, "c" * 150]
        assert length_cv(chunks) > 0.0

    def test_empty_list(self):
        assert length_cv([]) == 0.0


class TestEmptyChunkRate:
    def test_no_empty(self):
        assert empty_chunk_rate(["hello", "world"]) == 0.0

    def test_some_empty(self):
        assert empty_chunk_rate(["hello", "", "   ", "world"]) == 0.5

    def test_all_empty(self):
        assert empty_chunk_rate(["", "   ", ""]) == 1.0


class TestOverlapAdherence:
    def test_perfect_overlap(self):
        chunks = ["hello world", "world xxxx", "xxxx foo"]
        # Adjacent pairs overlap by exactly "world" (5) and "xxxx" (4)
        result = overlap_adherence(chunks, expected_overlap=5)
        # First pair is exact, second is 4/5 = 0.8
        assert result["ratio"] == pytest.approx(0.9, abs=0.01)
        assert result["within_tolerance"] == 1.0

    def test_no_overlap(self):
        chunks = ["abc", "def", "ghi"]
        result = overlap_adherence(chunks, expected_overlap=3)
        assert result["ratio"] == 0.0
        assert result["within_tolerance"] == 0.0

    def test_single_chunk(self):
        assert overlap_adherence(["only one"], expected_overlap=5) == {
            "ratio": 0.0,
            "within_tolerance": 0.0,
        }
