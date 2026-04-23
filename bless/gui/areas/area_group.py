# bless/gui/areas/area_group.py
# Copyright (c) 2008, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo
from gi.repository import Gdk, Gtk

from ...util.interval_tree import IntervalTree
from ...util.range import Range
from ..drawers import HighlightType

if TYPE_CHECKING:
    from ...buffers.byte_buffer import ByteBuffer
    from .area import Area


class Highlight(Range):
    """A coloured range overlay on the data view."""

    def __init__(self, ht: HighlightType = HighlightType.Normal,
                 start: int = 0, end: int = -1) -> None:
        super().__init__(start, end)
        self.type = ht


class AreaGroup:
    """
    Coordinates a list of Area instances that all display the same
    ByteBuffer region simultaneously.

    Responsibilities:
      - owns the current scroll offset and cursor position
      - owns the selection highlight
      - manages the interval tree of overlays (selection, pattern matches, …)
      - drives the render pipeline on the shared Gtk.DrawingArea
    """

    def __init__(self) -> None:
        self._areas: list[Area] = []
        self._buffer: ByteBuffer | None = None
        self._drawing_area: Gtk.DrawingArea | None = None
        self._focused_area: Area | None = None

        self._offset: int = 0
        self._cursor_offset: int = 0
        self._prev_cursor_offset: int = 0

        self._highlights: IntervalTree[Highlight] = IntervalTree()
        self._selection = Highlight(HighlightType.Selection)
        self._highlights.insert(self._selection)
        self._pattern_highlights: list[Highlight] = []

        self._buffer_cache: bytearray | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def areas(self) -> list[Area]:
        return self._areas

    @property
    def buffer(self) -> ByteBuffer | None:
        return self._buffer

    @buffer.setter
    def buffer(self, bb: ByteBuffer | None) -> None:
        self._buffer = bb
        self._offset = 0
        self._cursor_offset = 0
        self._rebuild_cache()

    @property
    def drawing_area(self) -> Gtk.DrawingArea | None:
        return self._drawing_area

    @drawing_area.setter
    def drawing_area(self, da: Gtk.DrawingArea) -> None:
        self._drawing_area = da

    @property
    def focused_area(self) -> Area | None:
        return self._focused_area

    @focused_area.setter
    def focused_area(self, area: Area | None) -> None:
        # Remove cursor focus from every area first
        for a in self._areas:
            a._cursor_focus = False
        self._focused_area = area
        if area is not None:
            area._cursor_focus = True
        self.redraw_now()

    def set_initial_focus(self) -> None:
        """Give cursor focus to the first focusable area."""
        for a in self._areas:
            if a.can_focus:
                self.focused_area = a
                return

    def cycle_focus(self) -> None:
        """Move cursor focus to the next focusable area (Tab key)."""
        focusable = [a for a in self._areas if a.can_focus]
        if not focusable:
            return
        if self._focused_area in focusable:
            idx = focusable.index(self._focused_area)
            nxt = focusable[(idx + 1) % len(focusable)]
        else:
            nxt = focusable[0]
        self.focused_area = nxt

    @property
    def offset(self) -> int:
        return self._offset

    @offset.setter
    def offset(self, v: int) -> None:
        if self._offset != v:
            self._offset = v
            self._rebuild_cache()

    @property
    def cursor_offset(self) -> int:
        return self._cursor_offset

    @property
    def prev_cursor_offset(self) -> int:
        return self._prev_cursor_offset

    @property
    def cursor_digit(self) -> int:
        if self._focused_area:
            return self._focused_area.cursor_digit
        return 0

    @property
    def selection(self) -> Range:
        return self._selection

    @selection.setter
    def selection(self, r: Range) -> None:
        self._highlights.delete(self._selection)
        # Clear old pattern-match highlights
        for pm in list(self._pattern_highlights):
            self._highlights.delete(pm)
        self._pattern_highlights.clear()

        self._selection.start = r.start
        self._selection.end   = r.end
        if not self._selection.is_empty():
            self._highlights.insert(self._selection)
            # Scan buffer for identical byte sequences and add PatternMatch highlights
            self._add_pattern_highlights(r)
        self.redraw_now()

    def _add_pattern_highlights(self, r: Range) -> None:
        """Find all occurrences of the selected byte sequence and highlight them."""
        if self._buffer is None or r.is_empty():
            return
        length = r.end - r.start + 1
        if length < 1 or length > 256:   # skip very long selections
            return
        # Read the selected pattern
        pattern = bytearray(length)
        try:
            for i in range(length):
                pattern[i] = self._buffer[r.start + i]
        except (IndexError, Exception):
            return
        # Scan the buffer for matches (simple BM-like scan)
        from ...tools.find import BMFindStrategy
        strategy = BMFindStrategy()
        strategy.buffer  = self._buffer
        strategy.pattern = bytes(pattern)
        strategy.position = 0
        while True:
            m = strategy.find_next()
            if m is None:
                break
            # Don't add a pattern highlight over the selection itself
            if m.start == r.start and m.end == r.end:
                continue
            pm = Highlight(HighlightType.PatternMatch, m.start, m.end)
            self._pattern_highlights.append(pm)
            self._highlights.insert(pm)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _rebuild_cache(self) -> None:
        if self._buffer is None or self._drawing_area is None:
            self._buffer_cache = None
            return
        first_area = self._areas[0] if self._areas else None
        if first_area is None or first_area.drawer is None or first_area.bpr <= 0:
            return
        bpr    = first_area.bpr
        da_h   = self._drawing_area.get_allocated_height()
        row_h  = first_area.drawer.height
        nrows  = (da_h + row_h - 1) // row_h if row_h else 1
        n_bytes = min(nrows * bpr, max(0, self._buffer.size - self._offset))
        if n_bytes <= 0:
            self._buffer_cache = bytearray()
            return
        self._buffer_cache = bytearray(n_bytes)
        # Single bulk read — vastly faster than per-byte for large files
        with self._buffer.lock:
            seg, mapping, _ = self._buffer._seg_col.find_segment(self._offset)
            if seg is None:
                return
            # Walk segments, filling cache
            pos = 0
            cur_off = self._offset
            seg2, mapping2, node2 = self._buffer._seg_col.find_segment(cur_off)
            while pos < n_bytes and seg2 is not None:
                seg_start = seg2.start + (cur_off - mapping2)
                seg_avail = seg2.end - seg_start + 1
                to_read   = min(seg_avail, n_bytes - pos)
                seg2.buffer.read(self._buffer_cache, pos, seg_start, to_read)
                pos     += to_read
                cur_off += to_read
                if node2 and node2.next:
                    node2    = node2.next
                    seg2     = node2.data
                    mapping2 = cur_off  # mapping of next segment
                else:
                    break

    def get_cached_byte(self, pos: int) -> int:
        idx = pos - self._offset
        if self._buffer_cache and 0 <= idx < len(self._buffer_cache):
            return self._buffer_cache[idx]
        if self._buffer:
            return self._buffer[pos]
        return 0

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def set_cursor(self, offset: int, digit: int) -> None:
        self._prev_cursor_offset = self._cursor_offset
        self._cursor_offset = offset
        for a in self._areas:
            a.cursor_digit = digit

    # ------------------------------------------------------------------
    # Highlights / overlays
    # ------------------------------------------------------------------

    def add_highlight(self, h: Highlight) -> None:
        self._highlights.insert(h)

    def remove_highlight(self, h: Highlight) -> None:
        self._highlights.delete(h)

    def get_highlights_in_view(self) -> list[Highlight]:
        if self._buffer is None or not self._areas:
            return []
        first = self._areas[0]
        bpr = first.bpr if first.bpr > 0 else 1
        drawer_h = first.drawer.height if first.drawer else 16
        da_h = (self._drawing_area.get_allocated_height()
                if self._drawing_area else 0)
        nrows = da_h // drawer_h if drawer_h else 1
        view_end = self._offset + nrows * bpr
        view_range = Range(self._offset, view_end)
        return self._highlights.search_overlap(view_range)

    # ------------------------------------------------------------------
    # Layout calculation
    # ------------------------------------------------------------------

    def calculate_layout(self) -> None:
        """
        Compute bpr and x/y for every area so they fit the DrawingArea width.
        Uses the same greedy approach as the original C# code.
        """
        if not self._drawing_area or not self._areas:
            return
        total_w = self._drawing_area.get_allocated_width()
        # Find maximum bpr that fits
        bpr = 1
        while True:
            total = sum(a.calc_width(bpr + 1) for a in self._areas)
            if total > total_w:
                break
            bpr += 1

        # Apply bpr and compute x positions
        x = 0
        for a in self._areas:
            w = a.calc_width(bpr, force=True)
            a.bpr = bpr
            a.x = x
            a.width = w
            if a.drawer:
                a.height = self._drawing_area.get_allocated_height()
            x += w

    # ------------------------------------------------------------------
    # Realize
    # ------------------------------------------------------------------

    def realize(self) -> None:
        for a in self._areas:
            a.realize()

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    def redraw_now(self) -> None:
        if self._drawing_area:
            self._drawing_area.queue_draw()

    def draw(self, cr: cairo.Context) -> None:
        """Called from the DrawingArea's ``draw`` signal."""
        self._rebuild_cache()
        for a in self._areas:
            a.set_cairo_context(cr)
            a.render()
