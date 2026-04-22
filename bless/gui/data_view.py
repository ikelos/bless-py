# bless/gui/data_view.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations
from collections import deque
from typing import Optional, Callable, TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from ..buffers.byte_buffer import ByteBuffer
from ..util.range import Range
from ..util.base_converter import byte_array_to_string, string_to_byte_array
from .areas.area_group import AreaGroup

if TYPE_CHECKING:
    from .areas.area import Area


DataViewHandler = Callable[["DataView"], None]


class CursorState:
    """Records cursor positions before/after a mutation for undo/redo."""
    __slots__ = ("undo_offset", "undo_digit", "redo_offset", "redo_digit")

    def __init__(self, uo: int, ud: int, ro: int, rd: int) -> None:
        self.undo_offset = uo
        self.undo_digit  = ud
        self.redo_offset = ro
        self.redo_digit  = rd


class DataView:
    """
    High-level editing controller.  Owns:
      - a ByteBuffer
      - a DataViewDisplay (the GTK widget tree)
      - cursor-undo / cursor-redo stacks
      - clipboard operations
    """

    def __init__(self) -> None:
        from .data_view_display import DataViewDisplay
        from .data_view_control import DataViewControl

        self._dv_display = DataViewDisplay(self)
        self._dv_control = DataViewControl(self)
        self._dv_display.control = self._dv_control
        self._dv_control.display = self._dv_display

        self._buffer: Optional[ByteBuffer] = None
        self._overwrite: bool = False
        self._notification: bool = False
        self._clipdata: bytes = b""

        self._clipboard = Gtk.Clipboard.get(Gdk.Atom.intern("CLIPBOARD", True))

        self._cursor_undo: deque[CursorState] = deque()
        self._cursor_redo: deque[CursorState] = deque()

        # event lists
        self._buffer_changed_handlers:      list[DataViewHandler] = []
        self._selection_changed_handlers:   list[DataViewHandler] = []
        self._cursor_changed_handlers:      list[DataViewHandler] = []
        self._overwrite_changed_handlers:   list[DataViewHandler] = []
        self._notification_changed_handlers: list[DataViewHandler] = []
        self._focus_changed_handlers:       list[DataViewHandler] = []

        # subscribe to preferences
        from ..tools.preferences import Preferences
        self._pref_id = f"dv{id(self)}"
        p = Preferences.instance()
        Preferences.proxy().subscribe("Undo.Limited",      self._pref_id, lambda pr: self._on_prefs_changed(pr))
        Preferences.proxy().subscribe("Undo.Actions",      self._pref_id, lambda pr: self._on_prefs_changed(pr))
        Preferences.proxy().subscribe("ByteBuffer.TempDir",self._pref_id, lambda pr: self._on_prefs_changed(pr))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def display(self) -> "DataViewDisplay":
        return self._dv_display

    @property
    def control(self) -> "DataViewControl":
        return self._dv_control

    @property
    def buffer(self) -> Optional[ByteBuffer]:
        return self._buffer

    @buffer.setter
    def buffer(self, bb: Optional[ByteBuffer]) -> None:
        if bb is not None:
            self._setup_buffer(bb)
        else:
            self._cleanup_buffer()

    @property
    def overwrite(self) -> bool:
        return self._overwrite

    @overwrite.setter
    def overwrite(self, v: bool) -> None:
        self._overwrite = v
        for h in self._overwrite_changed_handlers:
            h(self)

    @property
    def notification(self) -> bool:
        return self._notification

    @notification.setter
    def notification(self, v: bool) -> None:
        self._notification = v
        for h in self._notification_changed_handlers:
            h(self)

    @property
    def cursor_offset(self) -> int:
        return self._dv_display.area_group.cursor_offset

    @property
    def cursor_digit(self) -> int:
        return self._dv_display.area_group.cursor_digit

    @property
    def offset(self) -> int:
        return self._dv_display.area_group.offset

    @offset.setter
    def offset(self, v: int) -> None:
        self._dv_display.area_group.offset = v

    @property
    def selection(self) -> Range:
        return Range(self._dv_display.area_group.selection.start,
                     self._dv_display.area_group.selection.end)

    @selection.setter
    def selection(self, r: Range) -> None:
        self.set_selection(r.start, r.end)

    @property
    def focused_area(self) -> Optional["Area"]:
        return self._dv_display.area_group.focused_area

    @property
    def cursor_undo_deque(self) -> deque:
        return self._cursor_undo

    @property
    def cursor_redo_deque(self) -> deque:
        return self._cursor_redo

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def connect_buffer_changed(self, h: DataViewHandler) -> None:
        self._buffer_changed_handlers.append(h)

    def connect_selection_changed(self, h: DataViewHandler) -> None:
        self._selection_changed_handlers.append(h)

    def connect_cursor_changed(self, h: DataViewHandler) -> None:
        self._cursor_changed_handlers.append(h)

    def connect_overwrite_changed(self, h: DataViewHandler) -> None:
        self._overwrite_changed_handlers.append(h)

    def connect_notification_changed(self, h: DataViewHandler) -> None:
        self._notification_changed_handlers.append(h)

    def connect_focus_changed(self, h: DataViewHandler) -> None:
        self._focus_changed_handlers.append(h)

    def fire_focus_changed(self) -> None:
        for h in self._focus_changed_handlers:
            h(self)

    # ------------------------------------------------------------------
    # Buffer wiring
    # ------------------------------------------------------------------

    def _setup_buffer(self, bb: ByteBuffer) -> None:
        self._buffer = bb
        bb.connect_changed(self._on_buffer_changed)
        bb.connect_file_changed(self._on_buffer_file_changed)

        ag = self._dv_display.area_group
        ag.buffer = bb
        ag.set_cursor(0, 0)
        ag.selection = Range()

        # Ensure a focusable area has cursor focus
        ag.set_initial_focus()

        # Reset control selection state for the new buffer
        self._dv_control.reset_selection()

        # Wire conversion panel and find bars to this view
        self._dv_display.conversion_panel.attach_view(self)
        self._dv_display.find_bar.attach_view(self)
        self._dv_display.find_replace_bar.attach_view(self)

        self._dv_display.redraw()
        self._dv_display.vscroll.set_value(0)
        self._dv_display._drawing_area.queue_draw()

        self._on_prefs_changed(None)
        for h in self._buffer_changed_handlers:
            h(self)

    def _cleanup_buffer(self) -> None:
        if self._buffer:
            # disconnect signals (Python callbacks, so just remove)
            pass
        ag = self._dv_display.area_group
        ag.buffer = None
        ag.set_cursor(0, 0)
        ag.selection = Range()
        self._buffer = None

    def _on_buffer_changed(self, bb: ByteBuffer) -> None:
        def _idle():
            if self._buffer and self._buffer.read_allowed:
                self._dv_display.area_group.redraw_now()
            return False
        GLib.idle_add(_idle)

    def _on_buffer_file_changed(self, bb: ByteBuffer) -> None:
        def _idle():
            self._dv_display.show_file_changed_bar()
            self.notification = True
            if self._buffer:
                self._buffer.file_ops_allowed = False
            return False
        GLib.idle_add(_idle)

    def _on_prefs_changed(self, prefs) -> None:
        if self._buffer is None:
            return
        from ..tools.preferences import Preferences
        p = Preferences.instance()
        if p["Undo.Limited"] == "True":
            try:
                max_a = int(p["Undo.Actions"])
                self._buffer.max_undo_actions = max_a
                while len(self._cursor_undo) > max_a:
                    self._cursor_undo.pop()
            except ValueError:
                pass
        else:
            self._buffer.max_undo_actions = -1
        tmpdir = p["ByteBuffer.TempDir"]
        if tmpdir:
            self._buffer.temp_dir = tmpdir

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def move_cursor(self, offset: int, digit: int) -> None:
        self._dv_display.area_group.set_cursor(offset, digit)
        for h in self._cursor_changed_handlers:
            h(self)

    def set_selection(self, start: int, end: int) -> None:
        ag = self._dv_display.area_group
        if not ag.areas:
            return
        sel = ag.selection
        if sel.start == start and sel.end == end:
            return
        r = Range(start, end)
        if r.start > r.end and not r.is_empty():
            r.start, r.end = r.end, r.start
        ag.selection = r
        for h in self._selection_changed_handlers:
            h(self)

    def _add_undo_cursor(self, state: CursorState) -> None:
        if self._buffer and self._buffer.max_undo_actions != -1:
            while len(self._cursor_undo) >= self._buffer.max_undo_actions:
                self._cursor_undo.pop()
        self._cursor_undo.appendleft(state)

    # ------------------------------------------------------------------
    # Edit operations
    # ------------------------------------------------------------------

    def _delete_selection_internal(self) -> None:
        ag = self._dv_display.area_group
        prev = self.selection
        self._add_undo_cursor(
            CursorState(ag.cursor_offset, 0, ag.selection.start, 0))
        self._cursor_redo.clear()
        self.move_cursor(ag.selection.start, 0)
        self.set_selection(-1, -1)
        self._buffer.delete(prev.start, prev.end)

    def copy(self) -> None:
        ag = self._dv_display.area_group
        if not ag.areas or not self._buffer or not self._buffer.read_allowed:
            return
        ba = self._buffer.range_to_bytes(ag.selection.start, ag.selection.end)
        if ba is None:
            return
        self._clipdata = ba
        self._set_clipboard_data()
        self._dv_display.make_offset_visible(ag.cursor_offset, "closest")

    def cut(self) -> None:
        ag = self._dv_display.area_group
        if (not ag.areas or not self._buffer
                or not self._buffer.modify_allowed
                or not self._buffer.is_resizable):
            return
        ba = self._buffer.range_to_bytes(ag.selection.start, ag.selection.end)
        if ba is None:
            return
        self._clipdata = ba
        self._set_clipboard_data()
        self._delete_selection_internal()
        self._dv_display.make_offset_visible(ag.cursor_offset, "closest")

    def paste(self) -> None:
        ag = self._dv_display.area_group
        if not ag.areas or not self._buffer or not self._buffer.modify_allowed:
            return
        if not self._buffer.is_resizable and not self._overwrite:
            return

        data = self._get_paste_data()
        if not data:
            return

        if ag.selection.is_empty():
            if self._overwrite and ag.cursor_offset < self._buffer.size:
                end_pos = min(ag.cursor_offset + len(data) - 1,
                              self._buffer.size - 1)
                self._buffer.replace(ag.cursor_offset, end_pos, data)
            else:
                self._buffer.insert(ag.cursor_offset, data, 0, len(data))
            self._add_undo_cursor(
                CursorState(ag.cursor_offset, 0,
                            ag.cursor_offset + len(data), 0))
            self._cursor_redo.clear()
            self.move_cursor(ag.cursor_offset + len(data), 0)
        else:
            self._buffer.replace(ag.selection.start, ag.selection.end, data)
            self._add_undo_cursor(
                CursorState(ag.selection.start, 0,
                            ag.selection.start + len(data), 0))
            self._cursor_redo.clear()
            self.move_cursor(ag.selection.start + len(data), 0)
            self.set_selection(-1, -1)

        self._dv_display.make_offset_visible(ag.cursor_offset, "closest")

    def delete(self) -> None:
        ag = self._dv_display.area_group
        if not ag.areas or not self._buffer or not self._buffer.modify_allowed:
            return
        if ag.selection.is_empty():
            if ag.cursor_offset < self._buffer.size:
                self._buffer.delete(ag.cursor_offset, ag.cursor_offset)
                self._add_undo_cursor(
                    CursorState(ag.cursor_offset, ag.cursor_digit,
                                ag.cursor_offset, ag.cursor_digit))
                self._cursor_redo.clear()
        else:
            self._delete_selection_internal()
        self._dv_display.make_offset_visible(ag.cursor_offset, "closest")

    def delete_backspace(self) -> None:
        ag = self._dv_display.area_group
        if not ag.areas or not self._buffer or not self._buffer.modify_allowed:
            return
        if ag.selection.is_empty():
            c = ag.cursor_offset
            if c > 0:
                self.move_cursor(c - 1, ag.cursor_digit)
                self._buffer.delete(c - 1, c - 1)
                self._add_undo_cursor(
                    CursorState(c, ag.cursor_digit, c - 1, ag.cursor_digit))
                self._cursor_redo.clear()
        else:
            self._delete_selection_internal()
        self._dv_display.make_offset_visible(ag.cursor_offset, "closest")

    def undo(self) -> None:
        if not self._buffer or not self._buffer.modify_allowed:
            return
        self._buffer.undo()
        if self._cursor_undo:
            ch = self._cursor_undo.popleft()
            self._cursor_redo.appendleft(ch)
            self.set_selection(-1, -1)
            self._dv_display.make_offset_visible(ch.undo_offset, "closest")
            self.move_cursor(ch.undo_offset, ch.undo_digit)

    def redo(self) -> None:
        if not self._buffer or not self._buffer.modify_allowed:
            return
        self._buffer.redo()
        if self._cursor_redo:
            ch = self._cursor_redo.popleft()
            self._add_undo_cursor(ch)
            self.set_selection(-1, -1)
            self._dv_display.make_offset_visible(ch.redo_offset, "closest")
            self.move_cursor(ch.redo_offset, ch.redo_digit)

    def revert(self) -> None:
        if not self._buffer or not self._buffer.modify_allowed:
            return
        self._buffer.revert()
        self._cursor_undo.clear()
        self._cursor_redo.clear()
        self.set_selection(-1, -1)
        self.move_cursor(0, 0)

    # ------------------------------------------------------------------
    # Clipboard helpers
    # ------------------------------------------------------------------

    def _area_type(self) -> str:
        fa = self.focused_area
        return fa.area_type if fa else "hexadecimal"

    def _set_clipboard_data(self) -> None:
        data = self._clipdata
        atype = self._area_type()
        base_map = {"hexadecimal": 16, "decimal": 10,
                    "octal": 8, "binary": 2}

        def get_func(cb, sel, info, _data):
            target = sel.get_target().name()
            if target == "UTF8_STRING":
                b = base_map.get(atype)
                if b:
                    sel.set_text(byte_array_to_string(data, b))
                else:
                    sel.set(sel.get_target(), 8, data)
            else:
                sel.set(sel.get_target(), 8, data)

        targets = [
            Gtk.TargetEntry.new("application/octet-stream", 0, 0),
            Gtk.TargetEntry.new("UTF8_STRING", 0, 0),
        ]
        self._clipboard.set_with_data(targets, get_func, lambda *a: None)

    def _get_paste_data(self) -> Optional[bytes]:
        atype = self._area_type()
        base_map = {"hexadecimal": 16, "decimal": 10,
                    "octal": 8, "binary": 2}

        sd = self._clipboard.wait_for_contents(
            Gdk.Atom.intern("application/octet-stream", False))
        if sd:
            return bytes(sd.get_data())

        sd = self._clipboard.wait_for_contents(
            Gdk.Atom.intern("UTF8_STRING", False))
        if sd:
            text = sd.get_text()
            if text:
                b = base_map.get(atype)
                if b:
                    try:
                        return string_to_byte_array(text, b)
                    except (ValueError, KeyError):
                        pass
                return text.encode("utf-8", errors="replace")
        return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        self.buffer = None
        from ..tools.preferences import Preferences
        for key in ("Undo.Limited", "Undo.Actions", "ByteBuffer.TempDir"):
            Preferences.proxy().unsubscribe(key, self._pref_id)
        self._dv_display.cleanup()
        self._dv_control.cleanup()
