from __future__ import annotations

import sys
from pathlib import Path

import pytest


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from py39_compat import int_bit_count, strict_zip  # noqa: E402


def test_int_bit_count_matches_binary_population() -> None:
    for value in (0, 1, 2, 3, 255, 1 << 332, -333):
        assert int_bit_count(value) == bin(value).count("1")


def test_strict_zip_matches_equal_inputs() -> None:
    assert list(strict_zip((1, 2), ("a", "b"))) == [
        (1, "a"),
        (2, "b"),
    ]


def test_strict_zip_rejects_unequal_inputs() -> None:
    with pytest.raises(ValueError, match="different lengths"):
        list(strict_zip((1, 2), ("a",)))
