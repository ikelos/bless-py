# bless/gui/areas/area.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Callable
from enum import IntFlag

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
import cairo

from ..drawers import Drawer, DrawerInfo, HighlightType, RowType, ColumnType

if TYPE_CHECKING:
    from .area_group import AreaGroup


class GetOffsetFlags(IntFlag):
    Eof   = 1
    Abyss = 2


AreaCreatorFunc = Callable[["AreaGroup"], "Area"]
_factory: dict[str, AreaCreatorFunc] = {}


def register_area(name: str, creator: AreaCreatorFunc) -> None:
    _factory[name] = creator


def create_area(name: str, ag: "AreaGroup") -> Optional["Area"]:
    fn = _factory.get(name)
    return fn(ag) if fn else None


class Area(ABC):
    """
    Abstract base for all display columns (hex, ascii, offset, …).

    Each Area knows how to:
      - render itself row by row into a Cairo context (``_render_row_*``)
      - map a screen (x, y) to a buffer offset
      - map a buffer offset to a screen (x, y)
      - handle keyboard input
    """

    def __init__(self, area_group: "AreaGroup") -> None:
        self.area_group = area_group
        self.drawer: Optional[Drawer] = None
        self.drawer_info = DrawerInfo()
        self.area_type: str = ""

        self.x: int = 0
        self.y: int = 0
        self.width: int = 0
        self.height: int = 0
        self.bpr: int = 0          # bytes per row
        self.dpb: int = 0          # digits per byte
        self.fixed_bpr: int = -1   # -1 means auto

        self._cr: Optional[cairo.Context] = None
        self._realized: bool = False
        self._can_focus: bool = False
        self._cursor_digit: int = 0
        self._cursor_focus: bool = False
        self._is_active: bool = True

        self._active_cursor_color   = Gdk.RGBA(red=1, green=0, blue=0, alpha=1)
        self._inactive_cursor_color = Gdk.RGBA(red=0.5, green=0.5, blue=0.5, alpha=1)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def _render_row_normal(self, row: int, start_byte: int,
                           count: int, blank: bool) -> None: ...

    @abstractmethod
    def _render_row_highlight(self, row: int, start_byte: int,
                               count: int, blank: bool,
                               ht: HighlightType) -> None: ...

    @abstractmethod
    def get_display_info_by_offset(
        self, offset: int
    ) -> tuple[int, int, int, int]:
        """Return (row, byte_in_row, x, y)."""
        ...

    @abstractmethod
    def get_offset_by_display_info(
        self, x: int, y: int
    ) -> tuple[int, int, GetOffsetFlags]:
        """Return (offset, digit, flags)."""
        ...

    @abstractmethod
    def calc_width(self, n: int, force: bool = False) -> int:
        """Return pixel-width needed for *n* bytes per row, or -1 if invalid."""
        ...

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def handle_key(self, key: int, overwrite: bool) -> bool:
        return False

    def realize(self) -> None:
        self._active_cursor_color   = Gdk.RGBA(red=1, green=0, blue=0, alpha=1)
        self._inactive_cursor_color = Gdk.RGBA(red=0.5, green=0.5, blue=0.5, alpha=1)
        self._realized = True

    # ------------------------------------------------------------------
    # Drawing helpers available to subclasses
    # ------------------------------------------------------------------

    def _fill_rect(self, color: Gdk.RGBA, x: int, y: int, w: int, h: int) -> None:
        if self._cr is None:
            return
        self._cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        self._cr.rectangle(x, y, w, h)
        self._cr.fill()

    def set_cairo_context(self, cr: cairo.Context) -> None:
        self._cr = cr

    # ------------------------------------------------------------------
    # Rendering entry-points called by AreaGroup
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Render the visible portion of this area.  Called by AreaGroup."""
        if not self._realized or self.bpr <= 0 or self.drawer is None:
            return
        self._render_extra()
        self._render_highlights()
        self._render_cursor()

    def _render_extra(self) -> None:
        """Render all rows (normal mode)."""
        ag = self.area_group
        if self.drawer is None or self.drawer.height <= 0 or self.height <= 0:
            return
        buf_size = ag.buffer.size if ag.buffer else 0
        nrows = self.height // self.drawer.height
        visible = nrows * self.bpr
        visible = max(0, min(visible, buf_size - ag.offset))

        full_rows = visible // self.bpr
        last_row_bytes = visible % self.bpr
        if last_row_bytes > 0:
            full_rows += 1

        for i in range(full_rows):
            n = self.bpr if i < full_rows - 1 or last_row_bytes == 0 else last_row_bytes
            self._render_row_normal(i, 0, n, True)

        # Fill remainder of window with blank background
        if self.drawer:
            for i in range(full_rows, nrows):
                self._render_row_normal(i, 0, 0, True)

    def _render_highlights(self) -> None:
        ag = self.area_group
        from .area_group import AreaGroup
        overlaps = ag.get_highlights_in_view()
        for ah in overlaps:
            self._render_highlight(ah, HighlightType.Normal, HighlightType.Normal)

    def _render_highlight(self, h, left_ht: HighlightType,
                          right_ht: HighlightType) -> None:
        pass  # Detailed per-highlight rendering handled in subclasses

    def _render_cursor(self) -> None:
        if not self._cursor_focus or not self._can_focus:
            return
        ag = self.area_group
        if ag.buffer is None:
            return
        row, _, cx, cy = self.get_display_info_by_offset(ag.cursor_offset)
        if self.drawer is None:
            return
        # Shift right by cursor_digit so hex shows cursor on the active nibble
        cx += self._cursor_digit * self.drawer.width
        # Translate to screen coordinates
        sx = cx + self.x
        sy = cy + self.y
        w  = self.drawer.width
        h  = self.drawer.height
        color = (self._active_cursor_color if self._is_active
                 else self._inactive_cursor_color)
        if self._cr is None:
            return
        # Draw as a 2-pixel outline so the character underneath stays visible
        self._cr.save()
        self._cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        self._cr.set_line_width(2.0)
        self._cr.rectangle(sx + 1, sy + 1, w - 2, h - 2)
        self._cr.stroke()
        self._cr.restore()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def can_focus(self) -> bool:
        return self._can_focus

    @property
    def has_cursor_focus(self) -> bool:
        return self._cursor_focus

    @property
    def cursor_digit(self) -> int:
        return self._cursor_digit

    @cursor_digit.setter
    def cursor_digit(self, v: int) -> None:
        self._cursor_digit = v

    @property
    def is_active(self) -> bool:
        return self._is_active

    @is_active.setter
    def is_active(self, v: bool) -> None:
        self._is_active = v

    @property
    def fixed_bytes_per_row(self) -> int:
        return self.fixed_bpr

    @fixed_bytes_per_row.setter
    def fixed_bytes_per_row(self, v: int) -> None:
        self.fixed_bpr = v
