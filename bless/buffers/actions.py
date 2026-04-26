# bless/buffers/actions.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .file_buffer import FileBuffer
from .segment import Segment
from .segment_collection import SegmentCollection
from .simple_buffer import SimpleBuffer

if TYPE_CHECKING:
    from .byte_buffer import ByteBuffer


class ByteBufferAction(ABC):
    """Abstract base for all reversible ByteBuffer mutations."""

    @abstractmethod
    def do(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...

    def make_private_copy(self) -> None:  # optional override
        return

    def private_copy_size(self) -> int:  # optional override
        return 0


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------


class AppendAction(ByteBufferAction):
    def __init__(self, data: bytes, index: int, length: int, bb: ByteBuffer) -> None:
        self._bb = bb
        if length == 0:
            self._seg: Segment | None = None
        else:
            cb = SimpleBuffer()
            self._seg = Segment(cb, cb.size, cb.size + length - 1)
            cb.append(data, index, length)

    def do(self) -> None:
        if self._seg is None:
            return
        self._bb._seg_col.append(Segment(self._seg.buffer, self._seg.start, self._seg.end))
        self._bb._size += self._seg.size

    def undo(self) -> None:
        if self._seg is None:
            return
        self._bb._size -= self._seg.size
        self._bb._seg_col.delete_range(self._bb._size, self._bb._size + self._seg.size - 1)


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------


class InsertAction(ByteBufferAction):
    def __init__(self, pos: int, data: bytes, index: int, length: int, bb: ByteBuffer) -> None:
        self._bb = bb
        self._pos = pos
        if length == 0:
            self._seg: Segment | None = None
        else:
            cb = SimpleBuffer()
            self._seg = Segment(cb, cb.size, cb.size + length - 1)
            cb.append(data, index, length)

    def do(self) -> None:
        if self._seg is None:
            return
        tmp = SegmentCollection()
        tmp.append(Segment(self._seg.buffer, self._seg.start, self._seg.end))
        self._bb._seg_col.insert(tmp, self._pos)
        self._bb._size += self._seg.size

    def undo(self) -> None:
        if self._seg is None:
            return
        self._bb._seg_col.delete_range(self._pos, self._pos + self._seg.size - 1)
        self._bb._size -= self._seg.size


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class DeleteAction(ByteBufferAction):
    def __init__(self, pos1: int, pos2: int, bb: ByteBuffer) -> None:
        self._bb = bb
        self._pos1 = pos1
        self._pos2 = pos2
        self._deleted: SegmentCollection | None = None

    def do(self) -> None:
        self._deleted = self._bb._seg_col.delete_range(self._pos1, self._pos2)
        self._bb._size -= self._pos2 - self._pos1 + 1

    def undo(self) -> None:
        if self._deleted is None:
            return
        self._bb._seg_col.insert(self._deleted, self._pos1)
        self._bb._size += self._pos2 - self._pos1 + 1

    def make_private_copy(self) -> None:
        if self._deleted is None:
            return
        for seg in self._deleted.list:
            if isinstance(seg.buffer, FileBuffer):
                seg.make_private_copy()

    def private_copy_size(self) -> int:
        if self._deleted is None:
            return 0
        return sum(seg.size for seg in self._deleted.list if isinstance(seg.buffer, FileBuffer))


# ---------------------------------------------------------------------------
# Replace  (= Delete + Insert)
# ---------------------------------------------------------------------------


class ReplaceAction(ByteBufferAction):
    def __init__(
        self, pos1: int, pos2: int, data: bytes, index: int, length: int, bb: ByteBuffer
    ) -> None:
        self._del = DeleteAction(pos1, pos2, bb)
        self._ins = InsertAction(pos1, data, index, length, bb)

    def do(self) -> None:
        self._del.do()
        self._ins.do()

    def undo(self) -> None:
        self._ins.undo()
        self._del.undo()

    def make_private_copy(self) -> None:
        self._del.make_private_copy()

    def private_copy_size(self) -> int:
        return self._del.private_copy_size()


# ---------------------------------------------------------------------------
# Multi  (container for chained actions)
# ---------------------------------------------------------------------------


class MultiAction(ByteBufferAction):
    def __init__(self) -> None:
        self._actions: list[ByteBufferAction] = []

    def add(self, action: ByteBufferAction) -> None:
        self._actions.append(action)

    def do(self) -> None:
        for a in self._actions:
            a.do()

    def undo(self) -> None:
        for a in reversed(self._actions):
            a.undo()

    def make_private_copy(self) -> None:
        for a in self._actions:
            a.make_private_copy()

    def private_copy_size(self) -> int:
        return sum(a.private_copy_size() for a in self._actions)
