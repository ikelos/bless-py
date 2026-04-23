# bless/buffers/segment.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ibuffer import IBuffer


class ListNode:
    """Node of a doubly-linked intrusive list used by SegmentCollection."""
    __slots__ = ("data", "prev", "next")

    def __init__(self, data: Segment) -> None:
        self.data: Segment = data
        self.prev: ListNode | None = None
        self.next: ListNode | None = None


class LinkedList:
    """Minimal doubly-linked list that mirrors the C# Bless.Util.List<T>."""

    def __init__(self) -> None:
        self._first: ListNode | None = None
        self._last: ListNode | None = None
        self._count: int = 0

    @property
    def first(self) -> ListNode | None:
        return self._first

    @property
    def last(self) -> ListNode | None:
        return self._last

    @property
    def count(self) -> int:
        return self._count

    def append(self, seg: Segment) -> ListNode:
        node = ListNode(seg)
        if self._last is None:
            self._first = self._last = node
        else:
            node.prev = self._last
            self._last.next = node
            self._last = node
        self._count += 1
        return node

    def insert_after(self, ref: ListNode | None, seg: Segment) -> ListNode:
        node = ListNode(seg)
        if ref is None:
            # insert at head
            node.next = self._first
            if self._first:
                self._first.prev = node
            else:
                self._last = node
            self._first = node
        else:
            node.prev = ref
            node.next = ref.next
            if ref.next:
                ref.next.prev = node
            else:
                self._last = node
            ref.next = node
        self._count += 1
        return node

    def insert_before(self, ref: ListNode | None, seg: Segment) -> ListNode:
        if ref is None:
            return self.append(seg)
        node = ListNode(seg)
        node.next = ref
        node.prev = ref.prev
        if ref.prev:
            ref.prev.next = node
        else:
            self._first = node
        ref.prev = node
        self._count += 1
        return node

    def remove(self, node: ListNode) -> None:
        if node.prev:
            node.prev.next = node.next
        else:
            self._first = node.next
        if node.next:
            node.next.prev = node.prev
        else:
            self._last = node.prev
        node.prev = node.next = None
        self._count -= 1

    def __iter__(self):
        n = self._first
        while n is not None:
            yield n.data
            n = n.next

    def display(self) -> None:
        parts = [str(s) for s in self]
        print("List: " + " -> ".join(parts))


class Segment:
    """Represents a contiguous slice of an IBuffer."""

    __slots__ = ("buffer", "start", "end")

    def __init__(self, buffer: IBuffer, start: int, end: int) -> None:
        self.buffer = buffer
        self.start = start
        self.end = end

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    def contains(self, offset: int, mapping: int) -> bool:
        return mapping <= offset <= mapping + self.end - self.start

    def split_at(self, pos: int) -> Segment | None:
        """Split this segment at *pos* bytes from its own start.
        Returns the right half (or None if *pos* is 0 or beyond end)."""
        if pos > self.end - self.start or pos == 0:
            return None
        right = Segment(self.buffer, self.start + pos, self.end)
        self.end = self.start + pos - 1
        return right

    def make_private_copy(self) -> None:
        """Replace the backing buffer with an in-memory copy."""
        from .simple_buffer import SimpleBuffer
        sb = SimpleBuffer()
        sb.append_buffer(self.buffer, self.start, self.size)
        self.buffer = sb
        self.start = 0
        self.end = sb.size - 1

    def __repr__(self) -> str:
        return f"({self.start}->{self.end})"
