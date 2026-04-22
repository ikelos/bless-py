# bless/gui/data_view_control.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

from ..util.range import Range
from .areas.area import GetOffsetFlags

if TYPE_CHECKING:
    from .data_view import DataView, CursorState
    from .data_view_display import DataViewDisplay
    from .areas.area import Area


class _Pos:
    """Cursor/selection position expressed as the two adjacent byte boundaries."""
    __slots__ = ("first", "second", "digit")

    def __init__(self, first: int = 0, second: int = 0, digit: int = 0) -> None:
        self.first  = first
        self.second = second
        self.digit  = digit

    def copy(self) -> "_Pos":
        return _Pos(self.first, self.second, self.digit)


class DataViewControl:
    """
    Handles keyboard and mouse input for a DataView.
    Translates raw GTK events into DataView cursor / selection / edit calls.
    """

    def __init__(self, dv: "DataView") -> None:
        self._dv = dv
        self._display: Optional["DataViewDisplay"] = None

        self._sel_start = _Pos()
        self._sel_end   = _Pos()

        # State preserved across key-press calls to avoid repeated lookup
        self._okp_focus_area: Optional["Area"] = None
        self._okp_bpr = 1
        self._okp_dpb = 2
        self._okp_show_type = "closest"

        self._im_context = Gtk.IMContextSimple()

    @property
    def display(self) -> Optional["DataViewDisplay"]:
        return self._display

    @display.setter
    def display(self, d: "DataViewDisplay") -> None:
        self._display = d

    # ------------------------------------------------------------------
    # Helper: area at (x, y)
    # ------------------------------------------------------------------

    def _area_at(self, x: int, y: int) -> Optional["Area"]:
        if self._display is None:
            return None
        for a in self._display.area_group.areas:
            if a.x <= x <= a.x + a.width:
                return a
        return None

    # ------------------------------------------------------------------
    # Offset / position calculation
    # ------------------------------------------------------------------

    def _calc_pos(self, area: "Area", x: int, y: int) -> _Pos:
        off, digit, flags = area.get_offset_by_display_info(x, y)
        dv = self._dv
        buf = dv.buffer

        if flags & GetOffsetFlags.Eof:
            off = buf.size if buf else 0
            return _Pos(off, off, digit)
        if flags & GetOffsetFlags.Abyss:
            return _Pos(off, off + 1, digit)
        return _Pos(off, off, digit)

    def _validate(self, offset: int) -> int:
        buf = self._dv.buffer
        if buf is None:
            return 0
        if offset < 0:
            return 0
        if offset >= buf.size:
            return buf.size - 1
        return offset

    # ------------------------------------------------------------------
    # Selection update
    # ------------------------------------------------------------------

    def _update_selection(self, abyss: bool) -> None:
        dv = self._dv
        sel = dv.selection
        ss, se = self._sel_start, self._sel_end

        if sel.is_empty() and dv.cursor_offset != ss.second:
            off = dv.cursor_offset
            ss.first  = off - (1 if abyss else 0)
            ss.second = off
            ss.digit  = dv.cursor_digit
            se.first  = ss.first
            se.second = ss.second
            se.digit  = ss.digit
        elif not sel.is_empty():
            r = (Range(self._validate(ss.second), self._validate(se.first))
                 if ss.second <= se.first
                 else Range(self._validate(se.second), self._validate(ss.first)))
            if r.start != sel.start or r.end != sel.end:
                ss.second = sel.start
                ss.first  = ss.second - 1
                se.first  = sel.end
                se.second = se.first + 1

    def _evaluate_selection(self, show_type: str = "closest") -> None:
        dv = self._dv
        display = self._display
        if display is None:
            return
        ss, se = self._sel_start, self._sel_end

        if ss.first == se.first and ss.second == se.second:
            cursor = ss.second
            display.make_offset_visible(cursor, show_type)
            dv.set_selection(-1, -1)
            dv.move_cursor(ss.second, ss.digit)
        elif ss.second <= se.first:
            se.second = se.first + 1
            off = self._validate(se.second)
            if se.first >= off:
                off += 1
            cursor = off
            display.make_offset_visible(cursor, show_type)
            buf = dv.buffer
            if buf and ss.second < buf.size:
                dv.set_selection(self._validate(ss.second),
                                 self._validate(se.first))
            else:
                dv.set_selection(-1, -1)
            dv.move_cursor(off, 0)
        else:
            cursor = se.second
            display.make_offset_visible(cursor, show_type)
            buf = dv.buffer
            if buf and se.second < buf.size:
                dv.set_selection(self._validate(se.second),
                                 self._validate(ss.first))
            else:
                dv.set_selection(-1, -1)
            dv.move_cursor(cursor, 0)

    # ------------------------------------------------------------------
    # Focus
    # ------------------------------------------------------------------

    def _update_focus(self, area: "Area") -> None:
        ag = self._display.area_group
        if area.can_focus and ag.focused_area is not area:
            ag.focused_area = area

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def on_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> None:
        self._display.grab_keyboard_focus()
        area = self._area_at(int(event.x), int(event.y))
        if area is None:
            return

        pos = self._calc_pos(area, int(event.x - area.x), int(event.y - area.y))

        if event.button == 3:
            if self._dv.selection.is_empty():
                self._sel_start = pos.copy()
                self._sel_end   = pos.copy()
        else:
            self._update_selection(pos.first != pos.second)
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                self._sel_end = pos.copy()
            else:
                self._sel_start = pos.copy()
                self._sel_end   = pos.copy()

        self._update_focus(area)
        self._evaluate_selection("closest")

    def on_motion_notify(self, widget: Gtk.Widget, event: Gdk.EventMotion) -> None:
        if event.is_hint:
            _, x, y, state = widget.get_window().get_device_position(
                event.device)
        else:
            x, y, state = int(event.x), int(event.y), event.state

        if not (state & Gdk.ModifierType.BUTTON1_MASK):
            return

        area = self._area_at(x, y)
        if area is None:
            return

        pos = self._calc_pos(area, x - area.x, y - area.y)
        self._update_selection(pos.first != pos.second)
        self._sel_end = pos.copy()
        self._update_focus(area)
        self._evaluate_selection("closest")

    def on_button_release(self, widget: Gtk.Widget, event: Gdk.EventButton) -> None:
        area = self._area_at(int(event.x), int(event.y))
        if area is None:
            return

        y = int(event.y)
        if y > area.y + area.height:
            y = area.y + area.height - (area.drawer.height if area.drawer else 16)
        elif y < area.y:
            y = area.y

        pos = self._calc_pos(area, int(event.x - area.x), y - area.y)
        self._update_selection(pos.first != pos.second)
        self._sel_end = pos.copy()
        self._evaluate_selection("closest")

    # ------------------------------------------------------------------
    # Keyboard events
    # ------------------------------------------------------------------

    def on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        dv = self._dv
        display = self._display
        if display is None or dv.buffer is None:
            return False

        ag = display.area_group
        self._okp_focus_area = ag.focused_area
        self._okp_bpr = ag.areas[0].bpr if ag.areas else 1
        self._okp_dpb = (self._okp_focus_area.dpb
                         if self._okp_focus_area else 2)
        self._okp_show_type = "closest"

        cur = _Pos(dv.cursor_offset - 1, dv.cursor_offset, dv.cursor_digit)
        nxt = cur.copy()

        key = event.keyval
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)

        special = True
        if key == Gdk.KEY_Left:
            self._key_left(cur, nxt)
        elif key == Gdk.KEY_Right:
            self._key_right(cur, nxt)
        elif key == Gdk.KEY_Up:
            self._key_up(cur, nxt)
        elif key == Gdk.KEY_Down:
            self._key_down(cur, nxt)
        elif key == Gdk.KEY_Page_Up:
            self._key_page_up(cur, nxt)
        elif key == Gdk.KEY_Page_Down:
            self._key_page_down(cur, nxt)
        elif key == Gdk.KEY_Home:
            self._key_home(cur, nxt)
        elif key == Gdk.KEY_End:
            self._key_end(cur, nxt)
        elif key == Gdk.KEY_Insert:
            dv.overwrite = not dv.overwrite
            return True
        elif key == Gdk.KEY_Tab:
            ag.cycle_focus()
            return True
        elif key in (Gdk.KEY_BackSpace,):
            dv.delete_backspace()
            return True
        elif key == Gdk.KEY_Delete:
            dv.delete()
            return True
        else:
            special = not self._key_default(event, cur, nxt)

        if not special:
            if shift:
                self._sel_end = nxt.copy()
            else:
                self._sel_start = nxt.copy()
                self._sel_end   = nxt.copy()
            self._evaluate_selection(self._okp_show_type)
            return True

        return False

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _key_left(self, cur: _Pos, nxt: _Pos) -> None:
        off, dig = cur.second, cur.digit
        dig -= 1
        if dig < 0:
            off -= 1
            dig = self._okp_dpb - 1
        if off < 0:
            off, dig = 0, 0
        nxt.first  = off - 1
        nxt.second = off
        nxt.digit  = dig

    def _key_right(self, cur: _Pos, nxt: _Pos) -> None:
        off, dig = cur.second, cur.digit
        dig += 1
        if dig >= self._okp_dpb:
            off += 1
            dig = 0
        buf = self._dv.buffer
        if buf and off > buf.size:
            off = buf.size
            dig = self._okp_dpb - 1
        nxt.first  = off - 1
        nxt.second = off
        nxt.digit  = dig

    def _key_up(self, cur: _Pos, nxt: _Pos) -> None:
        off = max(0, cur.second - self._okp_bpr)
        nxt.first  = off - 1
        nxt.second = off
        nxt.digit  = cur.digit

    def _key_down(self, cur: _Pos, nxt: _Pos) -> None:
        buf = self._dv.buffer
        limit = buf.size if buf else 0
        off = min(limit, cur.second + self._okp_bpr)
        nxt.first  = off - 1
        nxt.second = off
        nxt.digit  = cur.digit

    def _key_page_up(self, cur: _Pos, nxt: _Pos) -> None:
        adj = self._display.vscroll.get_adjustment()
        off = max(0, cur.second - self._okp_bpr * int(adj.get_page_increment()))
        self._okp_show_type = "cursor"
        nxt.first  = off
        nxt.second = off
        nxt.digit  = cur.digit

    def _key_page_down(self, cur: _Pos, nxt: _Pos) -> None:
        adj = self._display.vscroll.get_adjustment()
        buf = self._dv.buffer
        limit = buf.size if buf else 0
        off = min(limit, cur.second + self._okp_bpr * int(adj.get_page_increment()))
        self._okp_show_type = "cursor"
        nxt.first  = off
        nxt.second = off
        nxt.digit  = cur.digit

    def _key_home(self, cur: _Pos, nxt: _Pos) -> None:
        nxt.first = nxt.second = nxt.digit = 0
        self._okp_show_type = "start"

    def _key_end(self, cur: _Pos, nxt: _Pos) -> None:
        buf = self._dv.buffer
        s = buf.size if buf else 0
        nxt.first = nxt.second = s
        nxt.digit = 0
        self._okp_show_type = "end"

    def _key_default(self, event: Gdk.EventKey,
                     cur: _Pos, nxt: _Pos) -> bool:
        """Handle printable/digit keys.  Returns True if consumed."""
        dv = self._dv
        fa = self._okp_focus_area
        if fa is None or dv.buffer is None:
            return False
        if not dv.buffer.modify_allowed:
            return False
        if not dv.buffer.is_resizable and not dv.overwrite:
            return False

        if dv.selection.is_empty():
            if (self._im_context.filter_keypress(event)
                    and fa.handle_key(event.keyval, dv.overwrite)):
                self._key_right(cur, nxt)
                from .data_view import CursorState
                dv.cursor_undo_deque.appendleft(
                    CursorState(cur.second, cur.digit, nxt.second, nxt.digit))
                dv.cursor_redo_deque.clear()
                self._sel_start = self._sel_end = nxt.copy()
                return True
            return False
        else:
            dv.buffer.begin_action_chaining()
            try:
                consumed = (self._im_context.filter_keypress(event)
                            and fa.handle_key(event.keyval, False))
                if consumed:
                    cur_sel = dv.selection
                    c_off   = dv.cursor_offset
                    self._key_right(cur, nxt)
                    nxt.first = nxt.second = cur_sel.start
                    self._sel_end = self._sel_start = nxt.copy()
                    if c_off > cur_sel.end:
                        dv.delete()
                    else:
                        dv.set_selection(cur_sel.start + 1, cur_sel.end + 1)
                        dv.delete()
            finally:
                dv.buffer.end_action_chaining()
            return consumed if 'consumed' in dir() else False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        self._okp_focus_area = None
        self._dv = None
        self._display = None
