# bless/gui/data_view_display.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

from .areas.area_group import AreaGroup
from .areas.concrete_areas import HexArea, AsciiArea, OffsetArea, SeparatorArea
from .conversion_panel import ConversionPanel
from .find_bar import FindBar, FindReplaceBar
from .goto_offset import GotoOffsetBar

if TYPE_CHECKING:
    from .data_view import DataView
    from .data_view_control import DataViewControl
    from .areas.area import Area


class DataViewDisplay(Gtk.Box):
    """
    GTK widget that wraps:
      DrawingArea + VScrollbar
      ├── FindBar         (Ctrl+F, hidden by default)
      ├── FindReplaceBar  (Ctrl+H, hidden by default)
      └── ConversionPanel (always shown)
    """

    def __init__(self, dv: "DataView") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._dv = dv
        self._control: Optional["DataViewControl"] = None
        self._realized = False

        # ── Area group ────────────────────────────────────────────────
        self._area_group = AreaGroup()
        ag = self._area_group

        self._drawing_area = Gtk.DrawingArea()
        ag.drawing_area = self._drawing_area
        ag.areas.clear()
        for factory in (OffsetArea,
                        lambda g: SeparatorArea(g),
                        HexArea,
                        lambda g: SeparatorArea(g),
                        AsciiArea):
            ag.areas.append(factory(ag))

        # ── Scrollbar ─────────────────────────────────────────────────
        adj = Gtk.Adjustment(value=0, lower=0, upper=1,
                             step_increment=1, page_increment=10,
                             page_size=10)
        self._vscroll = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL,
                                      adjustment=adj)
        adj.connect("value-changed", self._on_scrolled)

        hex_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hex_row.pack_start(self._drawing_area, True, True, 0)
        hex_row.pack_start(self._vscroll, False, False, 0)

        # ── File-changed bar ──────────────────────────────────────────
        self._file_changed_bar = Gtk.InfoBar()
        self._file_changed_bar.set_message_type(Gtk.MessageType.WARNING)
        lbl = Gtk.Label(label="File has changed on disk.")
        self._file_changed_bar.get_content_area().pack_start(lbl, False, False, 0)
        self._file_changed_bar.add_button("Reload", Gtk.ResponseType.YES)
        self._file_changed_bar.connect("response", self._on_file_changed_response)

        # ── Find / replace / goto bars ────────────────────────────────
        self._find_bar         = FindBar()
        self._find_replace_bar = FindReplaceBar()
        self._goto_bar         = GotoOffsetBar()

        # ── Conversion panel ──────────────────────────────────────────
        self._conv_panel = ConversionPanel()

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        # ── Pack everything ───────────────────────────────────────────
        self.pack_start(self._file_changed_bar, False, False, 0)
        self.pack_start(hex_row,               True,  True,  0)
        self.pack_start(self._find_bar,         False, False, 0)
        self.pack_start(self._find_replace_bar, False, False, 0)
        self.pack_start(self._goto_bar,         False, False, 0)
        self.pack_start(sep,                    False, False, 0)
        self.pack_start(self._conv_panel,       False, False, 0)

        # ── Wire drawing area events ──────────────────────────────────
        da = self._drawing_area
        da.connect("realize",              self._on_realized)
        da.connect("draw",                 self._on_drawn)
        da.connect("configure-event",      self._on_configured)
        da.connect("button-press-event",   self._on_button_press)
        da.connect("button-release-event", self._on_button_release)
        da.connect("motion-notify-event",  self._on_motion_notify)
        da.connect("key-press-event",      self._on_key_press)
        da.connect("scroll-event",         self._on_scroll)
        da.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK   |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.KEY_PRESS_MASK      |
            Gdk.EventMask.SCROLL_MASK         |
            Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        da.set_can_focus(True)

        self.show_all()
        self._file_changed_bar.hide()
        # These bars start hidden; revealed by keyboard shortcuts
        self._find_bar.hide()
        self._find_replace_bar.hide()
        self._goto_bar.hide()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def area_group(self) -> AreaGroup:
        return self._area_group

    @property
    def vscroll(self) -> Gtk.Scrollbar:
        return self._vscroll

    @property
    def control(self) -> Optional["DataViewControl"]:
        return self._control

    @control.setter
    def control(self, c: "DataViewControl") -> None:
        self._control = c

    @property
    def conversion_panel(self) -> ConversionPanel:
        return self._conv_panel

    @property
    def find_bar(self) -> FindBar:
        return self._find_bar

    @property
    def find_replace_bar(self) -> FindReplaceBar:
        return self._find_replace_bar

    # ------------------------------------------------------------------
    # Layout / resize
    # ------------------------------------------------------------------

    def _find_best_bpr(self, width: int) -> int:
        if not self._area_group.areas or not self._area_group.areas[0].drawer:
            return 16
        n = 1
        best = 1
        while True:
            total = 0
            broke = False
            for a in self._area_group.areas:
                w = a.calc_width(n)
                if w < 0:
                    broke = True
                    break
                total += w
            if broke:
                break
            if total > width:
                break
            best = n
            n += 1
        return best

    def _resize(self, win_w: int, win_h: int) -> None:
        bpr = self._find_best_bpr(win_w)
        if bpr <= 0:
            bpr = 1

        ag = self._area_group
        if bpr > 0 and ag.offset % bpr != 0:
            ag.offset = (ag.offset // bpr) * bpr

        x = 0
        font_h = win_h
        for a in ag.areas:
            a.bpr    = bpr
            a.width  = max(0, a.calc_width(bpr, force=True))
            a.x      = x
            a.height = win_h
            x += a.width
            if a.drawer and 0 < a.drawer.height < font_h:
                font_h = a.drawer.height

        if font_h <= 0:
            font_h = 16

        adj = self._vscroll.get_adjustment()
        adj.set_page_size(win_h // font_h)
        self._vscroll.set_increments(3, max(1, adj.get_page_size() - 1))
        self._setup_scrollbar_range(bpr)

    def _setup_scrollbar_range(self, bpr: int) -> None:
        dv = self._dv
        if not dv.buffer or bpr <= 0:
            return
        buf_size = dv.buffer.size
        nrows = (buf_size + bpr - 1) // bpr
        adj   = self._vscroll.get_adjustment()
        page  = adj.get_page_size()
        if nrows <= page:
            self._vscroll.set_value(0)
            adj.set_lower(0)
            adj.set_upper(max(nrows, page))
            self._vscroll.hide()
        else:
            adj.set_lower(0)
            adj.set_upper(nrows + 1)
            self._vscroll.show()

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def make_offset_visible(self, offset: int, show_type: str) -> None:
        ag = self._area_group
        if not ag.areas:
            return
        first = ag.areas[0]
        bpr   = first.bpr
        if bpr <= 0:
            return
        font_h = first.drawer.height if first.drawer else 16
        nrows  = first.height // font_h if font_h else 1
        cur_row = ag.offset // bpr
        end_row = cur_row + nrows - 1
        tgt_row = offset  // bpr
        adj     = self._vscroll.get_adjustment()

        def _set(row: int) -> None:
            adj.set_value(max(0.0, float(row)))
            self._on_scrolled(adj)

        if show_type == "closest":
            if   cur_row > tgt_row:  show_type = "start"
            elif end_row < tgt_row:  show_type = "end"
            else: return

        if   show_type == "start":  _set(tgt_row)
        elif show_type == "end":    _set(max(0, tgt_row - nrows + 1))
        elif show_type == "cursor":
            cur_row2 = ag.cursor_offset // bpr
            diff = cur_row2 - cur_row
            if   0 <= diff <= nrows:  _set(tgt_row - diff)
            elif diff > nrows:        _set(max(0, tgt_row - nrows + 1))
            else:                     _set(tgt_row)

    def grab_keyboard_focus(self) -> None:
        self._drawing_area.grab_focus()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def redraw(self) -> None:
        if not self._realized:
            return
        alloc = self._drawing_area.get_allocation()
        self._resize(alloc.width, alloc.height)
        self._drawing_area.queue_draw()

    def show_file_changed_bar(self) -> None:
        self._file_changed_bar.show_all()

    @property
    def goto_bar(self) -> GotoOffsetBar:
        return self._goto_bar

    def show_goto(self) -> None:
        self._find_bar.hide()
        self._find_replace_bar.hide()
        self._goto_bar.show_bar()

    def show_find(self) -> None:
        self._find_replace_bar.hide()
        self._find_bar.show_bar()

    def show_find_replace(self) -> None:
        self._find_bar.hide()
        self._find_replace_bar.show_bar()

    def cleanup(self) -> None:
        self._control = None

    # ------------------------------------------------------------------
    # GTK signal handlers
    # ------------------------------------------------------------------

    def _on_realized(self, widget) -> None:
        self._area_group.realize()
        self._realized = True
        alloc = widget.get_allocation()
        self._resize(alloc.width, alloc.height)
        self._area_group.set_initial_focus()
        widget.queue_draw()

    def _on_drawn(self, widget, cr) -> None:
        self._area_group.draw(cr)

    def _on_configured(self, widget, event) -> None:
        if not self._realized:
            return
        self._resize(event.width, event.height)
        self.make_offset_visible(self._dv.offset, "start")
        widget.queue_draw()

    def _on_scrolled(self, adj) -> None:
        bpr = 0
        if self._area_group.areas:
            bpr = self._area_group.areas[0].bpr
        if bpr > 0:
            self._area_group.offset = int(adj.get_value()) * bpr

    def _on_button_press(self, widget, event) -> bool:
        if self._control:
            self._control.on_button_press(widget, event)
        return True

    def _on_button_release(self, widget, event) -> bool:
        if self._control:
            self._control.on_button_release(widget, event)
        return True

    def _on_motion_notify(self, widget, event) -> bool:
        if self._control:
            self._control.on_motion_notify(widget, event)
        return True

    def _on_key_press(self, widget, event) -> bool:
        # Ctrl+F → find bar; Ctrl+H → find+replace bar
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.show_find()
            return True
        if ctrl and event.keyval in (Gdk.KEY_h, Gdk.KEY_H):
            self.show_find_replace()
            return True
        if ctrl and event.keyval in (Gdk.KEY_g, Gdk.KEY_G):
            self.show_goto()
            return True
        if self._control:
            return self._control.on_key_press(widget, event)
        return False

    def _on_scroll(self, widget, event) -> bool:
        adj = self._vscroll.get_adjustment()
        _, dx, dy = event.get_scroll_deltas()
        adj.set_value(adj.get_value() + dy * 3)
        return True

    def _on_file_changed_response(self, bar, response) -> None:
        if response == Gtk.ResponseType.YES:
            self._dv.revert()
        bar.hide()
