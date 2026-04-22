# bless/gui/find_bar.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from ..tools.find import BMFindStrategy, FindOperation
from ..util.base_converter import string_to_byte_array
from ..util.range import Range

if TYPE_CHECKING:
    from .data_view import DataView

_BASE_MAP = {
    "Hex": 16, "Dec": 10, "Oct": 8, "Bin": 2, "ASCII": None
}


def _parse(text: str, fmt: str) -> Optional[bytes]:
    text = text.strip()
    if not text:
        return b""
    base = _BASE_MAP.get(fmt)
    try:
        if base is None:
            return text.encode("utf-8", errors="replace")
        return string_to_byte_array(text, base)
    except (ValueError, KeyError):
        return None


class _BaseBar(Gtk.Box):
    """Shared infrastructure: a dismissible horizontal bar."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                         margin_top=2, margin_bottom=2,
                         margin_start=4, margin_end=4)
        self._dv: Optional["DataView"] = None
        self._op: Optional[FindOperation] = None

        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic",
                                               Gtk.IconSize.MENU))
        close.connect("clicked", lambda _: self.hide_bar())
        self.pack_end(close, False, False, 0)

        self._status = Gtk.Label(label="", xalign=0.0)
        self._status.set_width_chars(20)
        self.pack_end(self._status, False, False, 0)

    def attach_view(self, dv: "DataView") -> None:
        self._dv = dv

    def hide_bar(self) -> None:
        self.hide()

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "red" if error else "#006600"
        self._status.set_markup(f'<span foreground="{color}">{msg}</span>')

    def _make_fmt_combo(self) -> Gtk.ComboBoxText:
        cb = Gtk.ComboBoxText()
        for f in _BASE_MAP:
            cb.append_text(f)
        cb.set_active(0)
        return cb

    def _do_find(self, text: str, fmt: str, forward: bool = True) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        data = _parse(text, fmt)
        if data is None:
            self._set_status("Invalid pattern.", error=True)
            return
        if not data:
            return

        strategy = BMFindStrategy()
        strategy.pattern  = data
        strategy.buffer   = dv.buffer
        strategy.position = dv.cursor_offset

        self.set_sensitive(False)

        def _done(op: FindOperation) -> None:
            def _idle():
                self.set_sensitive(True)
                if op.match:
                    dv.set_selection(op.match.start, op.match.end)
                    dv.move_cursor(op.match.end + 1, 0)
                    dv.display.make_offset_visible(op.match.start, "start")
                    self._set_status(f"Found at 0x{op.match.start:X}.")
                else:
                    self._set_status("Not found.", error=True)
                return False
            GLib.idle_add(_idle)

        self._op = FindOperation(strategy, forward=forward, done_cb=_done)
        self._op.start()


class FindBar(_BaseBar):
    """Simple single-line find bar (Ctrl+F)."""

    def __init__(self) -> None:
        super().__init__()

        self.pack_start(Gtk.Label(label="Find:"), False, False, 0)
        self._entry = Gtk.Entry(width_chars=30)
        self._entry.connect("activate", lambda _: self._search(forward=True))
        self._entry.connect("key-press-event", self._on_entry_key)
        self.pack_start(self._entry, True, True, 0)

        self._fmt = self._make_fmt_combo()
        self.pack_start(self._fmt, False, False, 0)

        btn_next = Gtk.Button(label="Next ↓")
        btn_next.connect("clicked", lambda _: self._search(forward=True))
        self.pack_start(btn_next, False, False, 0)

        btn_prev = Gtk.Button(label="← Prev")
        btn_prev.connect("clicked", lambda _: self._search(forward=False))
        self.pack_start(btn_prev, False, False, 0)

        self.show_all()
        self.hide()

    def show_bar(self) -> None:
        self.show()
        self._entry.grab_focus()

    def _on_entry_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    def _search(self, forward: bool) -> None:
        self._do_find(self._entry.get_text(),
                      self._fmt.get_active_text() or "Hex",
                      forward=forward)


class FindReplaceBar(_BaseBar):
    """Two-row find+replace bar (Ctrl+H)."""

    def __init__(self) -> None:
        super().__init__()

        inner = Gtk.Grid(column_spacing=4, row_spacing=2)
        self.pack_start(inner, True, True, 0)

        inner.attach(Gtk.Label(label="Find:",    xalign=1.0), 0, 0, 1, 1)
        inner.attach(Gtk.Label(label="Replace:", xalign=1.0), 0, 1, 1, 1)

        self._find_entry    = Gtk.Entry(width_chars=28)
        self._replace_entry = Gtk.Entry(width_chars=28)
        inner.attach(self._find_entry,    1, 0, 1, 1)
        inner.attach(self._replace_entry, 1, 1, 1, 1)

        self._fmt = self._make_fmt_combo()
        inner.attach(self._fmt, 2, 0, 1, 2)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for label, cb in (
            ("Next ↓",      lambda _: self._do_find(
                self._find_entry.get_text(),
                self._fmt.get_active_text() or "Hex", forward=True)),
            ("Replace",     lambda _: self._replace_one()),
            ("Replace All", lambda _: self._replace_all()),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            btn_box.pack_start(b, False, False, 0)

        inner.attach(btn_box, 3, 0, 1, 2)

        self._find_entry.connect("activate", lambda _: self._do_find(
            self._find_entry.get_text(),
            self._fmt.get_active_text() or "Hex", True))
        self._find_entry.connect("key-press-event", self._on_key)
        self._replace_entry.connect("key-press-event", self._on_key)

        self.show_all()
        self.hide()

    def show_bar(self) -> None:
        self.show()
        self._find_entry.grab_focus()

    def _on_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    def _replace_one(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        sel = dv.selection
        if sel.is_empty():
            self._do_find(self._find_entry.get_text(),
                          self._fmt.get_active_text() or "Hex", True)
            return
        repl = _parse(self._replace_entry.get_text(),
                      self._fmt.get_active_text() or "Hex")
        if repl is None:
            return
        dv.buffer.replace(sel.start, sel.end, repl)
        dv.set_selection(-1, -1)
        self._set_status("Replaced 1.")
        self._do_find(self._find_entry.get_text(),
                      self._fmt.get_active_text() or "Hex", True)

    def _replace_all(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        fmt  = self._fmt.get_active_text() or "Hex"
        find = _parse(self._find_entry.get_text(), fmt)
        repl = _parse(self._replace_entry.get_text(), fmt)
        if not find or repl is None:
            return
        strategy = BMFindStrategy()
        strategy.pattern  = find
        strategy.buffer   = dv.buffer
        strategy.position = 0
        count = 0
        dv.buffer.begin_action_chaining()
        try:
            while True:
                m = strategy.find_next()
                if m is None:
                    break
                dv.buffer.replace(m.start, m.end, repl)
                count += 1
                strategy.position = m.start + len(repl)
        finally:
            dv.buffer.end_action_chaining()
        self._set_status(f"Replaced {count}.")
