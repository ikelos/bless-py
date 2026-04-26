# bless/gui/drawers.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from enum import IntEnum

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
import cairo
from gi.repository import Gdk, Gtk, Pango, PangoCairo


class HighlightType(IntEnum):
    Normal = 0
    Bookmark = 1
    PatternMatch = 2
    Selection = 3
    Sentinel = 4


class RowType(IntEnum):
    Even = 0
    Odd = 1


class ColumnType(IntEnum):
    Even = 0
    Odd = 1


def _parse_rgba(name: str) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.parse(name)
    return c


def _lighter(c: Gdk.RGBA, factor: float) -> Gdk.RGBA:
    return Gdk.RGBA(
        red=c.red + (1.0 - c.red) * factor,
        green=c.green + (1.0 - c.green) * factor,
        blue=c.blue + (1.0 - c.blue) * factor,
        alpha=c.alpha,
    )


def _darker(c: Gdk.RGBA, factor: float) -> Gdk.RGBA:
    return Gdk.RGBA(
        red=c.red * factor,
        green=c.green * factor,
        blue=c.blue * factor,
        alpha=c.alpha,
    )


class DrawerInfo:
    """Colour + font configuration for a Drawer."""

    def __init__(self) -> None:
        self.font_name = "Courier 12"
        self.font_language = "en"
        self.uppercase = True  # hex digits always uppercase

        self.fg_normal: list[list[Gdk.RGBA | None]] = [
            [_parse_rgba("black"), _parse_rgba("blue")],
            [_parse_rgba("black"), _parse_rgba("blue")],
        ]
        self.bg_normal: list[list[Gdk.RGBA | None]] = [
            [_parse_rgba("white"), _parse_rgba("white")],
            [_parse_rgba("white"), _parse_rgba("white")],
        ]
        ht = int(HighlightType.Sentinel)
        self.fg_highlight: list[list[Gdk.RGBA | None]] = [[None] * ht for _ in range(2)]
        self.bg_highlight: list[list[Gdk.RGBA | None]] = [[None] * ht for _ in range(2)]

    def setup_highlight(self, widget: Gtk.Widget) -> None:
        """Derive selection / pattern-match colours from the GTK theme."""
        ctx = widget.get_style_context()
        sel_fg = ctx.get_color(Gtk.StateFlags.SELECTED)
        found, sel_bg = ctx.lookup_color("theme_selected_bg_color")
        if not found:
            sel_bg = Gdk.RGBA(red=0.2, green=0.4, blue=0.8, alpha=1.0)

        pm_bg = _lighter(sel_bg, 0.6)
        pm_fg = _darker(sel_fg, 0.4)

        s = int(HighlightType.Selection)
        p = int(HighlightType.PatternMatch)

        for row in range(2):
            if self.fg_highlight[row][s] is None:
                self.fg_highlight[row][s] = sel_fg
            if self.bg_highlight[row][s] is None:
                self.bg_highlight[row][s] = sel_bg
            if self.fg_highlight[row][p] is None:
                self.fg_highlight[row][p] = pm_fg
            if self.bg_highlight[row][p] is None:
                self.bg_highlight[row][p] = pm_bg


class Drawer:
    """
    Abstract base for all area drawers.
    Subclasses implement :meth:`_create_surface` which pre-renders all 256
    glyphs for a given foreground/background colour pair onto a Cairo surface.
    The hot path then blits a glyph-strip column by column.
    """

    def __init__(self, widget: Gtk.Widget, info: DrawerInfo) -> None:
        self._widget = widget
        self._info = info

        info.setup_highlight(widget)

        fd = Pango.FontDescription.from_string(info.font_name)
        # create_pango_context() gives us a fresh context we can modify safely
        ctx = widget.create_pango_context()
        ctx.set_font_description(fd)
        lang = Pango.Language.from_string(info.font_language)
        ctx.set_language(lang)

        self._layout = Pango.Layout(ctx)
        # Disable ligatures so "ff", "fi", "fl" etc. each render as separate glyphs
        attrs = Pango.AttrList()
        # font-variant-ligatures: none  — disable all ligature substitutions
        attrs.insert(Pango.attr_font_features_new("liga 0, calt 0, clig 0"))
        self._layout.set_attributes(attrs)
        self._layout.set_text("X", -1)
        self._char_w, self._char_h = self._layout.get_pixel_size()
        self._layout.set_text("", -1)

        # surfaces[row_type][highlight_type] = cairo.ImageSurface
        ht = int(HighlightType.Sentinel)
        self._surfaces_normal: list[list[cairo.ImageSurface | None]] = [
            [None] * 2 for _ in range(2)
        ]
        self._surfaces_highlight: list[list[cairo.ImageSurface | None]] = [
            [None] * ht for _ in range(2)
        ]
        self._back_colors: list[list[Gdk.RGBA | None]] = [[None] * ht for _ in range(2)]

        self._init_surfaces()
        self._init_back_colors()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_surfaces(self) -> None:
        for row in range(2):
            for col in range(2):
                fg = self._info.fg_normal[row][col]
                bg = self._info.bg_normal[row][col]
                if fg and bg:
                    self._surfaces_normal[row][col] = self._create_surface(fg, bg)
            for ht in range(int(HighlightType.Sentinel)):
                fg = self._info.fg_highlight[row][ht]
                bg = self._info.bg_highlight[row][ht]
                if fg and bg:
                    self._surfaces_highlight[row][ht] = self._create_surface(fg, bg)

    def _init_back_colors(self) -> None:
        for row in range(2):
            for ht in range(int(HighlightType.Sentinel)):
                bg = self._info.bg_highlight[row][ht]
                if bg:
                    self._back_colors[row][ht] = bg
                else:
                    self._back_colors[row][ht] = self._info.bg_normal[row][0]

    # ------------------------------------------------------------------
    # Surface creation — subclasses override
    # ------------------------------------------------------------------

    def _create_surface(self, fg: Gdk.RGBA, bg: Gdk.RGBA) -> cairo.ImageSurface:
        """Create a 256-glyph strip surface (digits_per_byte * 256 * w × h)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _blit(
        self,
        cr: cairo.Context,
        src: cairo.ImageSurface,
        src_x: int,
        src_y: int,
        dst_x: int,
        dst_y: int,
        w: int,
        h: int,
    ) -> None:
        cr.set_source_surface(src, dst_x - src_x, dst_y - src_y)
        cr.rectangle(dst_x, dst_y, w, h)
        cr.fill()

    def _fill_rect(
        self, cr: cairo.Context, color: Gdk.RGBA, x: int, y: int, w: int, h: int
    ) -> None:
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def draw_normal(
        self, cr: cairo.Context, x: int, y: int, byte: int, row: RowType, col: ColumnType
    ) -> None:
        surf = self._surfaces_normal[int(row)][int(col)]
        if surf:
            self._draw(cr, x, y, byte, surf)

    def draw_highlight(
        self, cr: cairo.Context, x: int, y: int, byte: int, row: RowType, ht: HighlightType
    ) -> None:
        surf = self._surfaces_highlight[int(row)][int(ht)]
        if surf:
            self._draw(cr, x, y, byte, surf)

    def _draw(self, cr: cairo.Context, x: int, y: int, byte: int, surf: cairo.ImageSurface) -> None:
        """Blit a single glyph (byte value) from the pre-rendered strip."""
        raise NotImplementedError

    def get_background_color(self, row: RowType, ht: HighlightType) -> Gdk.RGBA:
        c = self._back_colors[int(row)][int(ht)]
        return c if c else Gdk.RGBA(red=1, green=1, blue=1, alpha=1)

    @property
    def width(self) -> int:
        return self._char_w

    @property
    def height(self) -> int:
        return self._char_h


# ---------------------------------------------------------------------------
# Concrete drawers
# ---------------------------------------------------------------------------


class _MonoDrawer(Drawer):
    """Helper for drawers whose glyph strip has one character per byte."""

    def _glyph_for(self, byte: int) -> str:
        raise NotImplementedError

    def _create_surface(self, fg: Gdk.RGBA, bg: Gdk.RGBA) -> cairo.ImageSurface:
        dpb = self._digits_per_byte
        w = dpb * self._char_w
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 256 * w, self._char_h)
        cr = cairo.Context(surf)
        cr.set_source_rgba(bg.red, bg.green, bg.blue, bg.alpha)
        cr.paint()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
        for i in range(256):
            text = self._glyph_for(i)
            self._layout.set_text(text, -1)
            cr.move_to(i * w, 0)
            PangoCairo.show_layout(cr, self._layout)
        return surf

    def _draw(self, cr: cairo.Context, x: int, y: int, byte: int, surf: cairo.ImageSurface) -> None:
        dpb = self._digits_per_byte
        w = dpb * self._char_w
        self._blit(cr, surf, byte * w, 0, x, y, w, self._char_h)


class HexDrawer(_MonoDrawer):
    _digits_per_byte = 2

    def _glyph_for(self, byte: int) -> str:
        return f"{byte:02X}" if self._info.uppercase else f"{byte:02x}"


class AsciiDrawer(_MonoDrawer):
    _digits_per_byte = 1

    def _glyph_for(self, byte: int) -> str:
        c = chr(byte)
        if c.isprintable() and byte < 128:
            return c
        return "."


class DecimalDrawer(_MonoDrawer):
    _digits_per_byte = 3

    def _glyph_for(self, byte: int) -> str:
        return f"{byte:03d}"


class OctalDrawer(_MonoDrawer):
    _digits_per_byte = 3

    def _glyph_for(self, byte: int) -> str:
        return f"{byte:03o}"


class BinaryDrawer(_MonoDrawer):
    _digits_per_byte = 8

    def _glyph_for(self, byte: int) -> str:
        return format(byte, "08b")


class OffsetHexDrawer(HexDrawer):
    """Re-use HexDrawer for offset column rendering."""
