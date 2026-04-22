# bless/gui/areas/concrete_areas.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later
#
# Concrete area implementations:
#   OffsetArea, HexArea, AsciiArea, DecimalArea, OctalArea, BinaryArea, SeparatorArea

from __future__ import annotations
from typing import TYPE_CHECKING
import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from .area import Area, GetOffsetFlags, register_area
from .area_group import AreaGroup
from ..drawers import (
    DrawerInfo, HighlightType, RowType, ColumnType,
    HexDrawer, AsciiDrawer, DecimalDrawer, OctalDrawer,
    BinaryDrawer, OffsetHexDrawer,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Grouped (bytes-per-group) base for hex/decimal/octal/binary
# ---------------------------------------------------------------------------

class GroupedArea(Area):
    """Area variant where bytes are visually grouped with an extra space between groups."""

    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self._grouping = 1
        self._can_focus = True

    @property
    def grouping(self) -> int:
        return self._grouping

    @grouping.setter
    def grouping(self, v: int) -> None:
        self._grouping = v

    def _render_row_normal(self, row: int, start_byte: int,
                           count: int, blank: bool) -> None:
        if not self.drawer:
            return
        ag = self.area_group
        rx = self.x
        ry = row * self.drawer.height + self.y
        roffset = ag.offset + row * self.bpr + start_byte
        odd = ((roffset // self.bpr) % 2) == 1
        back_even = self.drawer.get_background_color(RowType.Even, HighlightType.Normal)
        back_odd  = self.drawer.get_background_color(RowType.Odd,  HighlightType.Normal)

        if blank:
            self._fill_rect(back_odd if odd else back_even, rx, ry, self.width, self.drawer.height)

        if count <= 0:
            return

        # Advance rx to the start_byte column position
        for skip in range(start_byte):
            w_step = ((self.dpb + 1) * self.drawer.width
                      if skip % self._grouping == self._grouping - 1
                      else self.dpb * self.drawer.width)
            rx += w_step

        row_type = RowType.Odd if odd else RowType.Even
        for pos in range(start_byte, start_byte + count):
            col_type = (ColumnType.Even if (pos // self._grouping) % 2 == 0
                        else ColumnType.Odd)
            self.drawer.draw_normal(self._cr, rx, ry,
                                    ag.get_cached_byte(roffset), row_type, col_type)
            roffset += 1
            w_step = ((self.dpb + 1) * self.drawer.width
                      if pos % self._grouping == self._grouping - 1
                      else self.dpb * self.drawer.width)
            rx += w_step

    def _render_row_highlight(self, row: int, start_byte: int,
                               count: int, blank: bool,
                               ht: HighlightType) -> None:
        if not self.drawer:
            return
        ag = self.area_group
        rx = self.x
        ry = row * self.drawer.height + self.y
        roffset = ag.offset + row * self.bpr + start_byte
        odd = ((roffset // self.bpr) % 2) == 1

        if count <= 0:
            return

        dw = self.drawer.width
        dh = self.drawer.height

        # Advance rx to start_byte column position
        for skip in range(start_byte):
            w_step = ((self.dpb + 1) * dw
                      if skip % self._grouping == self._grouping - 1
                      else self.dpb * dw)
            rx += w_step

        # Compute total pixel span of the highlighted bytes (including gaps)
        span_rx = rx
        for pos in range(start_byte, start_byte + count):
            w_step = ((self.dpb + 1) * dw
                      if pos % self._grouping == self._grouping - 1
                      else self.dpb * dw)
            span_rx += w_step

        # Fill the whole span with highlight background first
        back = self.drawer.get_background_color(
            RowType.Odd if odd else RowType.Even, ht)
        self._fill_rect(back, rx, ry, span_rx - rx, dh)

        # Now redraw each glyph with the highlight surface
        row_type = RowType.Odd if odd else RowType.Even
        cur_rx = rx
        for pos in range(start_byte, start_byte + count):
            self.drawer.draw_highlight(self._cr, cur_rx, ry,
                                       ag.get_cached_byte(roffset), row_type, ht)
            roffset += 1
            w_step = ((self.dpb + 1) * dw
                      if pos % self._grouping == self._grouping - 1
                      else self.dpb * dw)
            cur_rx += w_step

    def calc_width(self, n: int, force: bool = False) -> int:
        if n == 0:
            return 0
        if self.fixed_bpr > 0 and n > self.fixed_bpr and not force:
            return -1
        if n % self._grouping != 0 and not force:
            return -1
        if not self.drawer:
            return n * self.dpb * 8  # fallback estimate
        ngroups = n // self._grouping
        group_w = self._grouping * self.dpb * self.drawer.width
        return ngroups * group_w + (ngroups - 1) * self.drawer.width

    def get_display_info_by_offset(self, offset: int) -> tuple[int, int, int, int]:
        ag = self.area_group
        row   = (offset - ag.offset) // self.bpr
        obyte = (offset - ag.offset) % self.bpr
        oy    = row * (self.drawer.height if self.drawer else 0)
        group       = obyte // self._grouping
        group_offset = obyte % self._grouping
        dw = self.drawer.width if self.drawer else 8
        ox = group * (self._grouping * self.dpb * dw + dw) + self.dpb * dw * group_offset
        return row, obyte, ox, oy

    def get_offset_by_display_info(self, x: int, y: int) -> tuple[int, int, GetOffsetFlags]:
        flags = GetOffsetFlags(0)
        ag = self.area_group
        if not self.drawer:
            return ag.offset, 0, flags
        dw = self.drawer.width
        dh = self.drawer.height
        group_w = self._grouping * self.dpb * dw + dw
        row   = y // dh
        group = x // group_w
        group_byte = (x - group * group_w) // (self.dpb * dw)
        digit = (x - group * group_w - group_byte * self.dpb * dw) // dw
        if group_byte >= self._grouping:
            group_byte = self._grouping - 1
            flags |= GetOffsetFlags.Abyss
        off = ag.offset + row * self.bpr + group * self._grouping + group_byte
        if ag.buffer and off >= ag.buffer.size:
            flags |= GetOffsetFlags.Eof
        return off, digit, flags


# ---------------------------------------------------------------------------
# HexArea
# ---------------------------------------------------------------------------

class HexArea(GroupedArea):
    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "hexadecimal"
        self.dpb = 2

    def realize(self) -> None:
        self.drawer = HexDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()

    def handle_key(self, key: int, overwrite: bool) -> bool:
        ag = self.area_group
        from gi.repository import Gdk as _Gdk
        hex_val = -1
        if _Gdk.KEY_0 <= key <= _Gdk.KEY_9:
            hex_val = key - _Gdk.KEY_0
        elif _Gdk.KEY_A <= key <= _Gdk.KEY_F:
            hex_val = key - _Gdk.KEY_A + 10
        elif _Gdk.KEY_a <= key <= _Gdk.KEY_f:
            hex_val = key - _Gdk.KEY_a + 10
        elif _Gdk.KEY_KP_0 <= key <= _Gdk.KEY_KP_9:
            hex_val = key - _Gdk.KEY_KP_0
        if hex_val == -1 or ag.buffer is None:
            return False

        buf = ag.buffer
        off = ag.cursor_offset
        at_end = off >= buf.size

        if overwrite and not at_end:
            # OVR: replace one nibble in place
            orig = buf[off]
            if self._cursor_digit == 0:
                new_byte = (hex_val << 4) | (orig & 0x0F)
            else:
                new_byte = (orig & 0xF0) | hex_val
            buf.replace(off, off, bytes([new_byte]))
        else:
            # INS mode
            if self._cursor_digit == 0:
                # First nibble: insert a new byte with the high nibble set
                new_byte = hex_val << 4
                if at_end:
                    buf.append(bytes([new_byte]), 0, 1)
                else:
                    buf.insert(off, bytes([new_byte]), 0, 1)
            else:
                # Second nibble: set low nibble of the byte at cursor
                if not at_end:
                    orig = buf[off]
                    new_byte = (orig & 0xF0) | hex_val
                    buf.replace(off, off, bytes([new_byte]))
                # Cursor will advance via _key_right in _key_default
        return True


# ---------------------------------------------------------------------------
# AsciiArea
# ---------------------------------------------------------------------------

class AsciiArea(Area):
    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "ascii"
        self.dpb = 1
        self._can_focus = True

    def realize(self) -> None:
        self.drawer = AsciiDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()

    def _render_row_normal(self, row: int, start_byte: int,
                           count: int, blank: bool) -> None:
        if not self.drawer:
            return
        ag = self.area_group
        rx = self.x
        ry = row * self.drawer.height + self.y
        roffset = ag.offset + row * self.bpr + start_byte
        odd = ((roffset // self.bpr) % 2) == 1
        if blank:
            back = self.drawer.get_background_color(
                RowType.Odd if odd else RowType.Even, HighlightType.Normal)
            self._fill_rect(back, rx, ry, self.width, self.drawer.height)
        if count <= 0:
            return
        row_type = RowType.Odd if odd else RowType.Even
        rx += start_byte * self.drawer.width
        for _ in range(count):
            self.drawer.draw_normal(self._cr, rx, ry,
                                    ag.get_cached_byte(roffset), row_type, ColumnType.Even)
            rx += self.drawer.width
            roffset += 1

    def _render_row_highlight(self, row: int, start_byte: int,
                               count: int, blank: bool,
                               ht: HighlightType) -> None:
        if not self.drawer:
            return
        ag = self.area_group
        rx = self.x + start_byte * self.drawer.width
        ry = row * self.drawer.height + self.y
        roffset = ag.offset + row * self.bpr + start_byte
        odd = ((roffset // self.bpr) % 2) == 1
        row_type = RowType.Odd if odd else RowType.Even
        for _ in range(count):
            self.drawer.draw_highlight(self._cr, rx, ry,
                                       ag.get_cached_byte(roffset), row_type, ht)
            rx += self.drawer.width
            roffset += 1

    def calc_width(self, n: int, force: bool = False) -> int:
        if self.fixed_bpr > 0 and n > self.fixed_bpr and not force:
            return -1
        dw = self.drawer.width if self.drawer else 8
        return n * dw

    def get_display_info_by_offset(self, offset: int) -> tuple[int, int, int, int]:
        ag = self.area_group
        row   = (offset - ag.offset) // self.bpr
        obyte = (offset - ag.offset) % self.bpr
        dw = self.drawer.width if self.drawer else 8
        dh = self.drawer.height if self.drawer else 16
        return row, obyte, obyte * dw, row * dh

    def get_offset_by_display_info(self, x: int, y: int) -> tuple[int, int, GetOffsetFlags]:
        flags = GetOffsetFlags(0)
        ag = self.area_group
        dw = self.drawer.width if self.drawer else 8
        dh = self.drawer.height if self.drawer else 16
        row  = y // dh
        col  = x // dw
        off  = ag.offset + row * self.bpr + col
        if ag.buffer and off >= ag.buffer.size:
            flags |= GetOffsetFlags.Eof
        return off, 0, flags

    def handle_key(self, key: int, overwrite: bool) -> bool:
        ag = self.area_group
        if ag.buffer is None:
            return False
        if not (0x20 <= key <= 0x7E):
            return False
        ba = bytes([key & 0xFF])
        off = ag.cursor_offset
        if off >= ag.buffer.size:
            ag.buffer.append(ba, 0, 1)
        elif overwrite:
            ag.buffer.replace(off, off, ba)
        else:
            ag.buffer.insert(off, ba, 0, 1)
        return True


# ---------------------------------------------------------------------------
# OffsetArea
# ---------------------------------------------------------------------------

class OffsetArea(Area):
    """Read-only column showing the file offset of each row."""

    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "offset"
        self.dpb = 2
        self._bytes = 4   # how many offset bytes to display (4 → 8 hex digits)

    def realize(self) -> None:
        self.drawer = OffsetHexDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()

    def _render_extra(self) -> None:
        if self.bpr <= 0 or not self.drawer or self.drawer.height <= 0:
            return
        ag = self.area_group
        buf_size = ag.buffer.size if ag.buffer else 0
        nrows = self.height // self.drawer.height

        if buf_size == 0:
            for i in range(nrows):
                self._render_row_normal(i, 0, 0, True)
            return

        visible_bytes = nrows * self.bpr
        if ag.offset + visible_bytes > buf_size:
            visible_bytes = buf_size - ag.offset
        visible_bytes = max(visible_bytes, 0)

        full_rows = visible_bytes // self.bpr
        if visible_bytes % self.bpr:
            full_rows += 1

        for i in range(full_rows):
            self._render_row_normal(i, 0, self.bpr, True)

        # The row immediately after the last content row: render its offset
        # even though it has no bytes (so the user sees where the next byte
        # would go, matching the original Bless behaviour).
        if full_rows < nrows:
            self._render_offset_only(full_rows)

        # Fill remaining rows with blank background only
        for i in range(full_rows + 1, nrows):
            self._render_blank_row(i)

    def _render_offset_only(self, row: int) -> None:
        """Render the offset number for a row that has no content bytes."""
        if not self.drawer:
            return
        ag = self.area_group
        dw = self.drawer.width
        dh = self.drawer.height
        ry = row * dh + self.y
        roffset = ag.offset + row * self.bpr
        odd = (row % 2) == 1
        back = self.drawer.get_background_color(
            RowType.Odd if odd else RowType.Even, HighlightType.Normal)
        self._fill_rect(back, self.x, ry, self.width, dh)
        row_type = RowType.Odd if odd else RowType.Even
        rx = (self._bytes - 1) * 2 * dw + self.x
        val = roffset
        for _ in range(self._bytes):
            self.drawer.draw_normal(self._cr, rx, ry, val & 0xFF,
                                    row_type, ColumnType.Even)
            val >>= 8
            rx -= 2 * dw

    def _render_blank_row(self, row: int) -> None:
        if not self.drawer:
            return
        dh = self.drawer.height
        ry = row * dh + self.y
        odd = (row % 2) == 1
        back = self.drawer.get_background_color(
            RowType.Odd if odd else RowType.Even, HighlightType.Normal)
        self._fill_rect(back, self.x, ry, self.width, dh)

    def _render_row_normal(self, row: int, start_byte: int,
                           count: int, blank: bool) -> None:
        if not self.drawer:
            return
        ag = self.area_group
        dw = self.drawer.width
        dh = self.drawer.height
        rx = (self._bytes - 1) * 2 * dw + self.x
        ry = row * dh + self.y
        roffset = ag.offset + row * self.bpr
        odd = ((roffset // self.bpr) % 2) == 1
        back = self.drawer.get_background_color(
            RowType.Odd if odd else RowType.Even, HighlightType.Normal)
        if blank:
            self._fill_rect(back, self.x, ry, self.width, dh)
        if count == 0:
            return
        row_type = RowType.Odd if odd else RowType.Even
        val = roffset
        for _ in range(self._bytes):
            self.drawer.draw_normal(self._cr, rx, ry, val & 0xFF,
                                    row_type, ColumnType.Even)
            val >>= 8
            rx -= 2 * dw

    def _render_row_highlight(self, row: int, start_byte: int,
                               count: int, blank: bool,
                               ht: HighlightType) -> None:
        self._render_row_normal(row, start_byte, count, blank)

    def calc_width(self, n: int, force: bool = False) -> int:
        dw = self.drawer.width if self.drawer else 8
        return self._bytes * 2 * dw

    def get_display_info_by_offset(self, offset: int) -> tuple[int, int, int, int]:
        ag = self.area_group
        row = (offset - ag.offset) // self.bpr
        dh = self.drawer.height if self.drawer else 16
        return row, 0, self.x, row * dh

    def get_offset_by_display_info(self, x: int, y: int) -> tuple[int, int, GetOffsetFlags]:
        ag = self.area_group
        dh = self.drawer.height if self.drawer else 16
        row = y // dh
        return ag.offset + row * self.bpr, 0, GetOffsetFlags(0)


# ---------------------------------------------------------------------------
# DecimalArea / OctalArea / BinaryArea — trivial subclasses of GroupedArea
# ---------------------------------------------------------------------------

class DecimalArea(GroupedArea):
    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "decimal"
        self.dpb = 3

    def realize(self) -> None:
        self.drawer = DecimalDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()


class OctalArea(GroupedArea):
    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "octal"
        self.dpb = 3

    def realize(self) -> None:
        self.drawer = OctalDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()


class BinaryArea(GroupedArea):
    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "binary"
        self.dpb = 8

    def realize(self) -> None:
        self.drawer = BinaryDrawer(self.area_group.drawing_area, self.drawer_info)
        super().realize()


class SeparatorArea(Area):
    """A fixed-width blank spacer between other areas."""

    def __init__(self, ag: AreaGroup) -> None:
        super().__init__(ag)
        self.area_type = "separator"
        self._sep_width = 8

    def _render_row_normal(self, *_): pass
    def _render_row_highlight(self, *_): pass

    def calc_width(self, n: int, force: bool = False) -> int:
        return self._sep_width

    def get_display_info_by_offset(self, offset: int) -> tuple[int, int, int, int]:
        return 0, 0, self.x, 0

    def get_offset_by_display_info(self, x: int, y: int) -> tuple[int, int, GetOffsetFlags]:
        return self.area_group.offset, 0, GetOffsetFlags(0)


# ---------------------------------------------------------------------------
# Auto-register all concrete area types
# ---------------------------------------------------------------------------

register_area("hexadecimal", lambda ag: HexArea(ag))
register_area("ascii",       lambda ag: AsciiArea(ag))
register_area("offset",      lambda ag: OffsetArea(ag))
register_area("decimal",     lambda ag: DecimalArea(ag))
register_area("octal",       lambda ag: OctalArea(ag))
register_area("binary",      lambda ag: BinaryArea(ag))
register_area("separator",   lambda ag: SeparatorArea(ag))
