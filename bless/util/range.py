# bless/util/range.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later


class Range:
    """An inclusive [start, end] byte range.  start > end means empty range."""

    def __init__(self, start: int = 0, end: int = -1) -> None:
        self.start = start
        self.end = end

    @property
    def size(self) -> int:
        if self.end < self.start:
            return 0
        return self.end - self.start + 1

    def is_empty(self) -> bool:
        return self.end < self.start

    def contains(self, pos: int) -> bool:
        return self.start <= pos <= self.end

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Range):
            return self.start == other.start and self.end == other.end
        return NotImplemented

    def __repr__(self) -> str:
        return f"Range({self.start}, {self.end})"
