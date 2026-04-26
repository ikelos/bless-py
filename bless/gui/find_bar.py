# bless/gui/find_bar.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from ..tools.find import BMFindStrategy, FindOperation
from ..util.base_converter import string_to_byte_array

if TYPE_CHECKING:
    from .data_view import DataView

_BASE_MAP = {"Hex": 16, "Dec": 10, "Oct": 8, "Bin": 2, "ASCII": None}


def _parse(text: str, fmt: str) -> bytes | None:
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


def _make_fmt_combo() -> Gtk.ComboBoxText:
    cb = Gtk.ComboBoxText()
    for f in _BASE_MAP:
        cb.append_text(f)
    cb.set_active(0)
    return cb


class _BaseBar(Gtk.Box):
    """Shared infrastructure: a dismissible horizontal bar."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_top=2,
            margin_bottom=2,
            margin_start=4,
            margin_end=4,
        )
        self._dv: DataView | None = None
        self._op: FindOperation | None = None

        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        close.connect("clicked", lambda _: self.hide_bar())
        self.pack_end(close, False, False, 0)

        self._status = Gtk.Label(label="", xalign=0.0)
        self._status.set_width_chars(24)
        self.pack_end(self._status, False, False, 0)

    def attach_view(self, dv: DataView) -> None:
        self._dv = dv

    def hide_bar(self) -> None:
        self.hide()

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "red" if error else "#006600"
        self._status.set_markup(f'<span foreground="{color}">{msg}</span>')

    def _do_find(self, text: str, fmt: str, forward: bool = True, on_found=None) -> None:
        """Start an async search.  Optional on_found(match) called on success."""
        dv = self._dv
        if dv is None or dv.buffer is None:
            self._set_status("No file open.", error=True)
            return
        data = _parse(text, fmt)
        if data is None:
            self._set_status("Invalid pattern.", error=True)
            return
        if not data:
            self._set_status("Empty pattern.", error=True)
            return

        if self._op is not None:
            self._op.cancel()

        strategy = BMFindStrategy()
        strategy.pattern = data
        strategy.buffer = dv.buffer
        strategy.position = dv.cursor_offset

        def _done(op: FindOperation) -> None:
            def _idle():
                if self._dv is None:
                    return False
                if op.match:
                    self._dv.set_selection(op.match.start, op.match.end)
                    self._dv.move_cursor(op.match.end + 1, 0)
                    self._dv.display.make_offset_visible(op.match.start, "start")
                    self._set_status(f"Found at 0x{op.match.start:X}.")
                    # Return keyboard focus so INS/OVR and editing keys work
                    self._dv.display.grab_keyboard_focus()
                    if on_found:
                        on_found(op.match)
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
        self._entry = Gtk.Entry()
        self._entry.set_width_chars(20)
        self._entry.set_hexpand(False)
        self._entry.connect("activate", lambda _: self._search(forward=True))
        self._entry.connect("key-press-event", self._on_entry_key)
        self.pack_start(self._entry, False, False, 0)

        self._fmt = _make_fmt_combo()
        self.pack_start(self._fmt, False, False, 0)

        btn_prev = Gtk.Button(label="← Prev")
        btn_prev.connect("clicked", lambda _: self._search(forward=False))
        self.pack_start(btn_prev, False, False, 0)

        btn_next = Gtk.Button(label="Next →")
        btn_next.connect("clicked", lambda _: self._search(forward=True))
        self.pack_start(btn_next, False, False, 0)

        self.set_no_show_all(True)

    def show_bar(self) -> None:
        self.set_no_show_all(False)
        self.show_all()
        self._entry.grab_focus()

    def hide_bar(self) -> None:
        self.hide()

    def _on_entry_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    def _search(self, forward: bool) -> None:
        self._do_find(self._entry.get_text(), self._fmt.get_active_text() or "Hex", forward=forward)


class FindReplaceBar(_BaseBar):
    """Two-row find+replace bar (Ctrl+H).
    Each field has its own format combo so hex can be found and replaced
    with ASCII (or any other combination).
    """

    def __init__(self) -> None:
        super().__init__()

        inner = Gtk.Grid(column_spacing=4, row_spacing=2)
        self.pack_start(inner, False, False, 0)

        inner.attach(Gtk.Label(label="Find:", xalign=1.0), 0, 0, 1, 1)
        inner.attach(Gtk.Label(label="Replace:", xalign=1.0), 0, 1, 1, 1)

        self._find_entry = Gtk.Entry()
        self._replace_entry = Gtk.Entry()
        for e in (self._find_entry, self._replace_entry):
            e.set_width_chars(20)
            e.set_hexpand(False)
        inner.attach(self._find_entry, 1, 0, 1, 1)
        inner.attach(self._replace_entry, 1, 1, 1, 1)

        # Separate format combo for find and replace
        self._find_fmt = _make_fmt_combo()
        self._replace_fmt = _make_fmt_combo()
        inner.attach(self._find_fmt, 2, 0, 1, 1)
        inner.attach(self._replace_fmt, 2, 1, 1, 1)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, cb in (
            ("Next →", lambda _: self._search_next()),
            ("Replace", lambda _: self._replace_one()),
            ("Replace All", lambda _: self._replace_all()),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            btn_box.pack_start(b, False, False, 0)

        inner.attach(btn_box, 3, 0, 1, 2)

        self._find_entry.connect("activate", lambda _: self._search_next())
        self._find_entry.connect("key-press-event", self._on_key)
        self._replace_entry.connect("key-press-event", self._on_key)

        self.set_no_show_all(True)

    def show_bar(self) -> None:
        self.set_no_show_all(False)
        self.show_all()
        self._find_entry.grab_focus()

    def hide_bar(self) -> None:
        self.hide()

    def _on_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    def _search_next(self) -> None:
        self._do_find(
            self._find_entry.get_text(), self._find_fmt.get_active_text() or "Hex", forward=True
        )

    def _replace_one(self) -> None:
        """Find next match, select it, then replace it."""
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        repl_text = self._replace_entry.get_text()
        repl_fmt = self._replace_fmt.get_active_text() or "Hex"
        repl = _parse(repl_text, repl_fmt)
        if repl is None:
            self._set_status("Invalid replace pattern.", error=True)
            return

        sel = dv.selection
        find_text = self._find_entry.get_text()
        find_fmt = self._find_fmt.get_active_text() or "Hex"
        find_data = _parse(find_text, find_fmt)
        if not find_data:
            self._set_status("Empty find pattern.", error=True)
            return

        # If the current selection already matches the find pattern, replace it
        if not sel.is_empty() and sel.end - sel.start + 1 == len(find_data):
            # Verify the bytes match
            buf = dv.buffer
            sel_bytes = bytes(buf[sel.start + i] for i in range(len(find_data)))
            if sel_bytes == find_data:
                buf.replace(sel.start, sel.end, repl)
                dv.set_selection(-1, -1)
                dv.move_cursor(sel.start + len(repl), 0)
                self._set_status("Replaced. Searching for next…")
                # Search for the next occurrence
                self._do_find(find_text, find_fmt, forward=True)
                return

        # No matching selection: find first, then the user can press Replace again
        self._do_find(find_text, find_fmt, forward=True)

    def _replace_all(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        find_fmt = self._find_fmt.get_active_text() or "Hex"
        repl_fmt = self._replace_fmt.get_active_text() or "Hex"
        find_data = _parse(self._find_entry.get_text(), find_fmt)
        repl_data = _parse(self._replace_entry.get_text(), repl_fmt)
        if not find_data or repl_data is None:
            return
        strategy = BMFindStrategy()
        strategy.pattern = find_data
        strategy.buffer = dv.buffer
        strategy.position = 0
        count = 0
        dv.buffer.begin_action_chaining()
        try:
            while True:
                m = strategy.find_next()
                if m is None:
                    break
                dv.buffer.replace(m.start, m.end, repl_data)
                count += 1
                strategy.position = m.start + len(repl_data)
        finally:
            dv.buffer.end_action_chaining()
        self._set_status(f"Replaced {count} occurrence(s).")
