# bless/gui/data_view_control.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from ..util.range import Range
from .areas.area import GetOffsetFlags

if TYPE_CHECKING:
    from .areas.area import Area
    from .data_view import CursorState, DataView
    from .data_view_display import DataViewDisplay


class _Pos:
    """Cursor/selection position.
    `second` is the byte the cursor sits on
    `first` is second-1 (used only
    when extending a selection leftward over an 'abyss' boundary).
    """
    __slots__ = ("first", "second", "digit")

    def __init__(self, first: int = 0, second: int = 0, digit: int = 0) -> None:
        self.first  = first
        self.second = second
        self.digit  = digit

    def copy(self) -> _Pos:
        return _Pos(self.first, self.second, self.digit)


class DataViewControl:
    """
    Handles keyboard and mouse input for a DataView.
    Translates raw GTK events into DataView cursor / selection / edit calls.
    """

    def __init__(self, dv: DataView) -> None:
        self._dv = dv
        self._display: DataViewDisplay | None = None

        self._sel_start = _Pos()
        self._sel_end   = _Pos()
        # True while the mouse button is held for a drag-select
        self._mouse_selecting = False

        self._okp_focus_area: Area | None = None
        self._okp_bpr = 1
        self._okp_dpb = 2
        self._okp_show_type = "closest"

        self._im_context = Gtk.IMContextSimple()

    @property
    def display(self) -> DataViewDisplay | None:
        return self._display

    @display.setter
    def display(self, d: DataViewDisplay) -> None:
        self._display = d

    def reset_selection(self) -> None:
        """Called when a new buffer is loaded — reset stale cursor state."""
        self._sel_start = _Pos(0, 0, 0)
        self._sel_end   = _Pos(0, 0, 0)
        self._mouse_selecting = False

    # ------------------------------------------------------------------
    # Helper: area at (x, y)
    # ------------------------------------------------------------------

    def _area_at(self, x: int, y: int) -> Area | None:
        """Return the focusable Area whose column contains screen-x.
        Separator and offset areas cannot be focused
        fall back to nearest."""
        if self._display is None:
            return None
        areas = self._display.area_group.areas
        # First pass: exact hit on a focusable area
        for a in areas:
            if a.can_focus and a.x <= x < a.x + max(a.width, 1):
                return a
        # Second pass: nearest focusable by column midpoint
        best = None
        best_dist = float("inf")
        for a in areas:
            if a.can_focus:
                mid = a.x + a.width / 2
                d = abs(mid - x)
                if d < best_dist:
                    best_dist = d
                    best = a
        return best

    # ------------------------------------------------------------------
    # Offset / position calculation
    # ------------------------------------------------------------------

    def _calc_pos(self, area: Area, x: int, y: int) -> _Pos:
        """Map area-relative pixel (x,y) to a _Pos."""
        off, digit, flags = area.get_offset_by_display_info(x, y)
        buf = self._dv.buffer

        if flags & GetOffsetFlags.Eof:
            off = buf.size if buf else 0
            return _Pos(off - 1, off, digit)
        # Normal click: cursor sits exactly on the byte clicked
        return _Pos(off - 1, off, digit)

    def _validate(self, offset: int) -> int:
        buf = self._dv.buffer
        if buf is None:
            return 0
        return max(0, min(offset, buf.size - 1))

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _set_cursor_to_pos(self, pos: _Pos, show_type: str = "closest") -> None:
        """Move cursor to pos.second with no selection."""
        dv = self._dv
        if self._display:
            self._display.make_offset_visible(pos.second, show_type)
        dv.set_selection(-1, -1)
        dv.move_cursor(pos.second, pos.digit)

    def _evaluate_selection(self, show_type: str = "closest") -> None:
        dv = self._dv
        display = self._display
        if display is None:
            return
        ss, se = self._sel_start, self._sel_end

        # No drag: just position cursor
        if ss.second == se.second:
            display.make_offset_visible(ss.second, show_type)
            dv.set_selection(-1, -1)
            dv.move_cursor(ss.second, ss.digit)
            return

        # Drag: mark selection between anchor and current
        a = ss.second
        b = se.second
        if a > b:
            a, b = b, a
        # Clamp to valid range
        buf = dv.buffer
        if buf:
            a = max(0, min(a, buf.size - 1))
            b = max(0, min(b, buf.size - 1))
        if a <= b:
            dv.set_selection(a, b)
        else:
            dv.set_selection(-1, -1)
        cursor = se.second
        display.make_offset_visible(cursor, show_type)
        dv.move_cursor(cursor, se.digit)

    # ------------------------------------------------------------------
    # Focus
    # ------------------------------------------------------------------

    def _update_focus(self, area: Area) -> None:
        if self._display is None:
            return
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
        self._update_focus(area)

        if event.button == 1:
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                # Extend selection from existing anchor
                self._sel_end = pos.copy()
            else:
                # New click: anchor both start and end at the same point
                self._sel_start = pos.copy()
                self._sel_end   = pos.copy()
            self._mouse_selecting = True
            self._evaluate_selection("closest")

    def on_motion_notify(self, widget: Gtk.Widget, event: Gdk.EventMotion) -> None:
        if not self._mouse_selecting:
            return
        if event.is_hint:
            _, x, y, state = widget.get_window().get_device_position(event.device)
        else:
            x, y, state = int(event.x), int(event.y), event.state

        if not (state & Gdk.ModifierType.BUTTON1_MASK):
            self._mouse_selecting = False
            return

        area = self._area_at(x, y)
        if area is None:
            return
        pos = self._calc_pos(area, x - area.x, y - area.y)
        self._sel_end = pos.copy()
        self._update_focus(area)
        self._evaluate_selection("closest")

    def on_button_release(self, widget: Gtk.Widget, event: Gdk.EventButton) -> None:
        if not self._mouse_selecting:
            return
        self._mouse_selecting = False
        area = self._area_at(int(event.x), int(event.y))
        if area is None:
            return
        # Clamp y to within the area
        y = int(event.y)
        dh = area.drawer.height if area.drawer else 16
        y = max(area.y, min(y, area.y + area.height - dh))
        pos = self._calc_pos(area, int(event.x - area.x), y - area.y)
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
        self._okp_dpb = (self._okp_focus_area.dpb if self._okp_focus_area else 2)
        self._okp_show_type = "closest"

        cur = _Pos(dv.cursor_offset - 1, dv.cursor_offset, dv.cursor_digit)
        nxt = cur.copy()

        key   = event.keyval
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        handled = False

        if key == Gdk.KEY_Left:
            self._key_left(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Right:
            self._key_right(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Up:
            self._key_up(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Down:
            self._key_down(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Page_Up:
            self._key_page_up(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Page_Down:
            self._key_page_down(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Home:
            self._key_home(cur, nxt)
            handled = True
        elif key == Gdk.KEY_End:
            self._key_end(cur, nxt)
            handled = True
        elif key == Gdk.KEY_Insert:
            dv.overwrite = not dv.overwrite
            return True
        elif key == Gdk.KEY_Tab:
            ag.cycle_focus()
            return True
        elif key == Gdk.KEY_BackSpace:
            dv.delete_backspace()
            return True
        elif key == Gdk.KEY_Delete:
            dv.delete()
            return True
        else:
            handled = self._key_default(event, cur, nxt)

        if handled:
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
        nxt.first = off - 1
        nxt.second = off
        nxt.digit = cur.digit

    def _key_page_down(self, cur: _Pos, nxt: _Pos) -> None:
        adj = self._display.vscroll.get_adjustment()
        buf = self._dv.buffer
        limit = buf.size if buf else 0
        off = min(limit, cur.second + self._okp_bpr * int(adj.get_page_increment()))
        self._okp_show_type = "cursor"
        nxt.first = off - 1
        nxt.second = off
        nxt.digit = cur.digit

    def _key_home(self, cur: _Pos, nxt: _Pos) -> None:
        nxt.first = -1
        nxt.second = 0
        nxt.digit = 0
        self._okp_show_type = "start"

    def _key_end(self, cur: _Pos, nxt: _Pos) -> None:
        buf = self._dv.buffer
        s = buf.size if buf else 0
        nxt.first = s - 1
        nxt.second = s
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

        consumed = False
        if dv.selection.is_empty():
            if fa.handle_key(event.keyval, dv.overwrite):
                consumed = True
                self._key_right(cur, nxt)
                from .data_view import CursorState
                dv.cursor_undo_deque.appendleft(
                    CursorState(cur.second, cur.digit, nxt.second, nxt.digit))
                dv.cursor_redo_deque.clear()
                self._sel_start = self._sel_end = nxt.copy()
        else:
            # Replace selection with typed character
            sel = dv.selection
            dv.buffer.begin_action_chaining()
            try:
                if fa.handle_key(event.keyval, False):
                    consumed = True
                    # Character inserted at sel.start; delete the rest of selection
                    new_end = sel.start + 1
                    if sel.end >= new_end:
                        dv.buffer.delete(new_end, sel.end + 1)
                    nxt.first  = sel.start - 1
                    nxt.second = sel.start + 1
                    nxt.digit  = 0
                    dv.set_selection(-1, -1)
            finally:
                dv.buffer.end_action_chaining()
        return consumed

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        self._okp_focus_area = None
        self._dv = None
        self._display = None
