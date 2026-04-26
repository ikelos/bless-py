# bless/buffers/segment_collection.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from .segment import LinkedList, ListNode, Segment


class SegmentCollection:
    """
    An ordered collection of Segments backed by a doubly-linked list.

    The segments are stored in logical order so that their concatenated
    content forms the current byte-buffer view.  All insert/delete operations
    are O(segments) and include automatic coalescing of adjacent segments
    that refer to the same backing buffer.
    """

    def __init__(self) -> None:
        self._list: LinkedList = LinkedList()
        # Cached last-accessed node so sequential access stays fast
        self._cached_node: ListNode | None = None
        self._cached_mapping: int = 0

    @property
    def list(self) -> LinkedList:
        return self._list

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _invalidate_cache(self) -> None:
        self._cached_node = None
        self._cached_mapping = 0

    def _set_cache(self, node: ListNode, mapping: int) -> None:
        self._cached_node = node
        self._cached_mapping = mapping

    # ------------------------------------------------------------------
    # Append / merge helpers
    # ------------------------------------------------------------------

    def append(self, seg: Segment) -> None:
        """Append *seg* to the collection, merging with the last segment if possible."""
        last_node = self._list.last
        if last_node is not None:
            ls = last_node.data
            if ls.buffer is seg.buffer and seg.start == ls.end + 1:
                ls.end = seg.end
                return
        self._list.append(seg)

    def _insert_after(self, ref: ListNode | None, seg: Segment) -> ListNode:
        """Insert *seg* after *ref*, merging if possible; return the node."""
        if ref is not None:
            ls = ref.data
            if ls.buffer is seg.buffer and seg.start == ls.end + 1:
                ls.end = seg.end
                return ref
        return self._list.insert_after(ref, seg)

    def _insert_before(self, ref: ListNode | None, seg: Segment) -> ListNode:
        """Insert *seg* before *ref*, merging if possible; return the node."""
        if ref is not None:
            ls = ref.data
            if ls.buffer is seg.buffer and seg.end + 1 == ls.start:
                ls.start = seg.start
                return ref
        return self._list.insert_before(ref, seg)

    # ------------------------------------------------------------------
    # Segment lookup
    # ------------------------------------------------------------------

    def find_segment(self, offset: int) -> tuple[Segment | None, int, ListNode | None]:
        """
        Find the segment that contains *offset*.

        Returns ``(segment, mapping, node)`` where *mapping* is the logical
        start of *segment* in the collection.  If not found, segment is None
        but mapping/node point to the last examined node.
        """
        if self._cached_node is None:
            if self._list.first is None:
                return None, 0, None
            self._set_cache(self._list.first, 0)

        seg = self._cached_node.data
        cur_mapping = self._cached_mapping
        cur_node = self._cached_node

        if seg.contains(offset, cur_mapping):
            return seg, cur_mapping, cur_node

        if offset < cur_mapping:
            # walk backwards
            while cur_node.prev is not None:
                cur_node = cur_node.prev
                seg = cur_node.data
                cur_mapping -= seg.size
                if seg.contains(offset, cur_mapping):
                    self._set_cache(cur_node, cur_mapping)
                    return seg, cur_mapping, cur_node
        else:
            # walk forwards
            while cur_node.next is not None:
                cur_mapping += seg.size
                cur_node = cur_node.next
                seg = cur_node.data
                if seg.contains(offset, cur_mapping):
                    self._set_cache(cur_node, cur_mapping)
                    return seg, cur_mapping, cur_node

        return None, cur_mapping, cur_node

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def insert(self, sc: SegmentCollection, offset: int) -> None:
        """Insert all segments of *sc* at *offset* in this collection."""
        s, mapping, node = self.find_segment(offset)

        if s is None:
            # Check if we should append
            empty = node is None and offset == 0
            at_end = node is not None and offset == mapping + node.data.size
            if empty or at_end:
                n = sc._list.first
                while n is not None:
                    self.append(n.data)
                    n = n.next
            return

        if mapping == offset:
            # Insert at start of segment — walk sc in reverse and insert_before
            n = sc._list.last
            while n is not None:
                node = self._insert_before(node, n.data)
                n = n.prev
            self._set_cache(node, mapping)
        else:
            # Split segment at offset, insert sc in the gap
            right = s.split_at(offset - mapping)
            self._list.insert_after(node, right)
            n = sc._list.first
            while n is not None:
                node = self._insert_after(node, n.data)
                n = n.next

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_range(self, pos1: int, pos2: int) -> SegmentCollection | None:
        """
        Remove bytes [pos1, pos2] inclusive from the collection.

        Returns a new SegmentCollection containing the removed bytes, or
        None if the range was invalid.
        """
        # Find end first so the cache points near the start afterwards
        s2, mapping2, node2 = self.find_segment(pos2)
        s1, mapping1, node1 = self.find_segment(pos1)

        if s1 is None or s2 is None:
            return None

        result = SegmentCollection()

        # ---- Special case: both ends in the same segment ----
        if node1 is node2:
            remove_node = False

            # Try to split at pos1
            sf = s1.split_at(pos1 - mapping1)
            if sf is None:
                sf = s1
                remove_node = True

            # sf now starts at pos1; try to split at pos2+1
            sl = sf.split_at(pos2 - pos1 + 1)
            if sl is not None:
                self._list.insert_after(node1, sl)

            if remove_node:
                if node1.next is not None:
                    self._set_cache(node1.next, mapping1)
                elif node1.prev is not None:
                    prev_seg = node1.prev.data
                    self._set_cache(node1.prev, mapping1 - prev_seg.size)
                else:
                    self._invalidate_cache()
                self._list.remove(node1)

            result.append(sf)
            return result

        # ---- General case: range spans multiple segments ----

        # Split end segment
        sl = s2.split_at(pos2 - mapping2 + 1)
        if sl is None:
            sl = s2
        else:
            self._list.insert_after(node2, sl)

        n = node1.next

        # Split start segment
        sf = s1.split_at(pos1 - mapping1)
        if sf is None:
            sf = s1
            if node1.prev is not None:
                prev_seg = node1.prev.data
                self._set_cache(node1.prev, mapping1 - prev_seg.size)
            else:
                self._invalidate_cache()
            self._list.remove(node1)

        result.append(sf)

        # Remove all nodes between node1 and node2
        while n is not node2:
            result.append(n.data)
            nxt = n.next
            self._list.remove(n)
            n = nxt

        # Remove node2
        self._list.remove(node2)
        result.append(node2.data)

        return result

    # ------------------------------------------------------------------
    # Get range (non-destructive copy)
    # ------------------------------------------------------------------

    def get_range(self, pos1: int, pos2: int) -> SegmentCollection | None:
        """Return a new SegmentCollection covering [pos1, pos2] without modifying self."""
        s2, mapping2, node2 = self.find_segment(pos2)
        s1, mapping1, node1 = self.find_segment(pos1)

        if s1 is None or s2 is None:
            return None

        result = SegmentCollection()

        if node1 is node2:
            seg = Segment(s1.buffer, pos1 - mapping1 + s1.start, pos2 - mapping1 + s1.start)
            result.append(seg)
            return result

        sf = Segment(s1.buffer, pos1 - mapping1 + s1.start, s1.end)
        sl = Segment(s2.buffer, s2.start, pos2 - mapping2 + s2.start)

        result.append(sf)
        n = node1.next
        while n is not node2:
            result.append(Segment(n.data.buffer, n.data.start, n.data.end))
            n = n.next
        result.append(sl)

        return result
