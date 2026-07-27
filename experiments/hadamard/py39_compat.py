#!/usr/bin/env python3
"""Small compatibility helpers for the repository's Python 3.9 CI floor."""

from __future__ import annotations

from itertools import zip_longest
from typing import Any, Iterable, Iterator


_NATIVE_BIT_COUNT = getattr(int, "bit_count", None)


def int_bit_count(value: int) -> int:
    """Return the number of one bits, using the native fast path when present."""

    if _NATIVE_BIT_COUNT is not None:
        return _NATIVE_BIT_COUNT(value)
    return bin(value).count("1")


def strict_zip(*iterables: Iterable[Any]) -> Iterator[tuple[Any, ...]]:
    """Zip lazily and raise when the inputs have different lengths."""

    sentinel = object()
    for values in zip_longest(*iterables, fillvalue=sentinel):
        if any(value is sentinel for value in values):
            raise ValueError("zip() arguments have different lengths")
        yield values
