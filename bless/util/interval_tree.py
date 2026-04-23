# bless/util/interval_tree.py
# Copyright (c) 2008, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later
#
# A simple augmented red-black interval tree.  Nodes are keyed by range.start;
# the "max" augmentation stores the maximum range.end in each subtree so that
# overlap queries can prune early.

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from .range import Range

_RED = True
_BLACK = False

class _Node[T]:
    __slots__ = ("key", "values", "max_end", "left", "right", "red")

    def __init__(self, key: int, value: T) -> None:
        self.key: int = key
        self.values: list[T] = [value]
        self.max_end: int = value.end  # type: ignore[attr-defined]
        self.left: _Node[T] | None = None
        self.right: _Node[T] | None = None
        self.red: bool = True

    def update_max(self) -> None:
        m = max(v.end for v in self.values)  # type: ignore[attr-defined]
        if self.left:
            m = max(m, self.left.max_end)
        if self.right:
            m = max(m, self.right.max_end)
        self.max_end = m


class IntervalTree[T]:
    """
    A minimal interval tree supporting:
      - insert(item)       — item must have .start and .end
      - delete(item)       — remove one item matching by identity
      - search_overlap(r)  — return all items overlapping Range r
      - clear()
    """

    def __init__(self) -> None:
        self._root: _Node[T] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(self, item: T) -> None:
        self._root = self._insert(self._root, item.start, item)  # type: ignore
        self._root.red = False

    def delete(self, item: T) -> None:
        self._root, _ = self._delete_item(self._root, item.start, item)  # type: ignore
        if self._root:
            self._root.red = False

    def search_overlap(self, r: Range) -> list[T]:
        results: list[T] = []
        self._search(self._root, r, results)
        return results

    def clear(self) -> None:
        self._root = None

    def __iter__(self):
        return self._inorder(self._root)

    def _inorder(self, node):
        if node is None:
            return
        yield from self._inorder(node.left)
        yield from node.values
        yield from self._inorder(node.right)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self, node: _Node[T] | None, r: Range, out: list[T]) -> None:
        if node is None or node.max_end < r.start:
            return
        # left subtree may contain overlaps
        self._search(node.left, r, out)
        # check this node's intervals
        if node.key <= r.end:
            for v in node.values:
                if v.start <= r.end and v.end >= r.start:  # type: ignore
                    out.append(v)
            # right subtree
            self._search(node.right, r, out)

    # ------------------------------------------------------------------
    # Insert (left-leaning red-black tree)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_red(n: _Node | None) -> bool:
        return n is not None and n.red

    def _rotate_left(self, h: _Node[T]) -> _Node[T]:
        x = h.right
        h.right = x.left
        x.left = h
        x.red = h.red
        h.red = True
        h.update_max()
        x.update_max()
        return x

    def _rotate_right(self, h: _Node[T]) -> _Node[T]:
        x = h.left
        h.left = x.right
        x.right = h
        x.red = h.red
        h.red = True
        h.update_max()
        x.update_max()
        return x

    @staticmethod
    def _flip_colors(h: _Node) -> None:
        h.red = not h.red
        if h.left:
            h.left.red = not h.left.red
        if h.right:
            h.right.red = not h.right.red

    def _insert(self, h: _Node[T] | None, key: int, val: T) -> _Node[T]:
        if h is None:
            return _Node(key, val)

        if key < h.key:
            h.left = self._insert(h.left, key, val)
        elif key > h.key:
            h.right = self._insert(h.right, key, val)
        else:
            h.values.append(val)
            m = val.end  # type: ignore
            if m > h.max_end:
                h.max_end = m
            return h

        if self._is_red(h.right) and not self._is_red(h.left):
            h = self._rotate_left(h)
        if self._is_red(h.left) and h.left and self._is_red(h.left.left):
            h = self._rotate_right(h)
        if self._is_red(h.left) and self._is_red(h.right):
            self._flip_colors(h)

        h.update_max()
        return h

    # ------------------------------------------------------------------
    # Delete (simplified: remove one item from node's values list)
    # ------------------------------------------------------------------

    def _delete_item(self, h: _Node[T] | None, key: int,
                     val: T) -> tuple[_Node[T] | None, bool]:
        """Return (new_root, deleted)."""
        if h is None:
            return None, False
        deleted = False
        if key < h.key:
            h.left, deleted = self._delete_item(h.left, key, val)
        elif key > h.key:
            h.right, deleted = self._delete_item(h.right, key, val)
        else:
            # remove by identity
            new_vals = [v for v in h.values if v is not val]
            deleted = len(new_vals) < len(h.values)
            if deleted:
                h.values = new_vals
            if not h.values:
                # remove this node — replace with in-order successor
                h = self._remove_node(h)
                if h:
                    h.update_max()
                return h, deleted

        if h:
            h.update_max()
        return h, deleted

    def _remove_node(self, h: _Node[T]) -> _Node[T] | None:
        """Remove the node itself, returning a replacement."""
        if h.left is None:
            return h.right
        if h.right is None:
            return h.left
        # Replace with minimum of right subtree
        min_node = self._min_node(h.right)
        h.key = min_node.key
        h.values = min_node.values
        h.right = self._delete_min(h.right)
        return h

    @staticmethod
    def _min_node(n: _Node[T]) -> _Node[T]:
        while n.left:
            n = n.left
        return n

    def _delete_min(self, h: _Node[T]) -> _Node[T] | None:
        if h.left is None:
            return h.right
        h.left = self._delete_min(h.left)
        if h.left:
            h.left.update_max()
        h.update_max()
        return h
