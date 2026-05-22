from __future__ import annotations
"""Chunking quality metrics for uploaded documents.

Engineering metrics — no LLM, millisecond-level computation.
"""

import statistics
from typing import Optional


# Sentence/paragraph boundary characters (CN + EN)
_BOUNDARY_CHARS = {"\n", "。", "！", "？", ".", "!", "?", "；", ";"}


def boundary_bleed_rate(chunks: list[str]) -> float:
    """Fraction of chunks whose start/end break mid-sentence or mid-paragraph.

    A chunk is "clean" if it starts at a natural boundary (beginning of string
    or after whitespace/punctuation) and ends at a natural boundary.
    """
    if not chunks:
        return 0.0

    dirty = 0
    for chunk in chunks:
        if not chunk:
            dirty += 1
            continue
        # Check start
        if not _is_boundary_start(chunk):
            dirty += 1
            continue
        # Check end
        if not _is_boundary_end(chunk):
            dirty += 1
            continue

    return dirty / len(chunks)


def _is_boundary_start(text: str) -> bool:
    """True if the chunk starts at a natural text boundary."""
    first = text[0]
    # Clean: whitespace, newline, uppercase (sentence start), CJK char,
    # or explicit boundary punctuation
    if first in ("\n", " ") or first.isspace():
        return True
    if first.isupper():
        return True
    if "\u4e00" <= first <= "\u9fff":
        return True
    if first in _BOUNDARY_CHARS:
        return True
    # Lowercase letter mid-word is suspicious
    return False


def _is_boundary_end(text: str) -> bool:
    """True if the chunk ends at a natural text boundary."""
    last = text[-1]
    return last in _BOUNDARY_CHARS or last.isspace() or last == "\n"


def length_cv(chunks: list[str]) -> float:
    """Coefficient of variation of chunk lengths (std / mean).

    Lower = more consistent chunk sizes. High CV indicates the splitter
    is creating very uneven chunks.
    """
    if not chunks:
        return 0.0
    lengths = [len(c) for c in chunks]
    mean_len = statistics.mean(lengths)
    if mean_len == 0:
        return 0.0
    try:
        std_len = statistics.stdev(lengths)
    except statistics.StatisticsError:
        std_len = 0.0
    return std_len / mean_len


def empty_chunk_rate(chunks: list[str]) -> float:
    """Fraction of chunks that are empty or pure whitespace."""
    if not chunks:
        return 0.0
    empty = sum(1 for c in chunks if not c or not c.strip())
    return empty / len(chunks)


def overlap_adherence(
    chunks: list[str],
    expected_overlap: int,
    tolerance: float = 0.2,
) -> dict[str, float]:
    """Measure how well actual adjacent overlaps match the expected overlap.

    Returns a dict with:
        - ratio: mean(actual_overlap / expected_overlap) for adjacent pairs
        - within_tolerance: fraction of pairs where overlap is within
          [expected * (1-tolerance), expected * (1+tolerance)]
    """
    if len(chunks) < 2 or expected_overlap <= 0:
        return {"ratio": 0.0, "within_tolerance": 0.0}

    ratios: list[float] = []
    within: list[bool] = []
    for prev, curr in zip(chunks, chunks[1:]):
        actual = _compute_overlap(prev, curr)
        ratio = actual / expected_overlap
        ratios.append(ratio)
        low = expected_overlap * (1 - tolerance)
        high = expected_overlap * (1 + tolerance)
        within.append(low <= actual <= high)

    return {
        "ratio": statistics.mean(ratios) if ratios else 0.0,
        "within_tolerance": sum(within) / len(within) if within else 0.0,
    }


def _compute_overlap(a: str, b: str) -> int:
    """Return the length of the longest common suffix of a and prefix of b."""
    max_ol = min(len(a), len(b))
    for length in range(max_ol, 0, -1):
        if a[-length:] == b[:length]:
            return length
    return 0
