# bless/gui/goto_offset.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from .data_view import DataView


def _parse_offset(text: str) -> int | None:
    """Parse decimal or 0x-prefixed hex offset string."""
    t = text.strip()
    if not t:
        return None
    try:
        if t.startswith("0x") or t.startswith("0X"):
            return int(t, 16)
        return int(t, 10)
    except ValueError:
        return None


class GotoOffsetBar(Gtk.Box):
    """
    Inline bar (Ctrl+G) that accepts an offset and scrolls to it.
    Accepts decimal or hex (0x…) values.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                         margin_top=2, margin_bottom=2,
                         margin_start=4, margin_end=4)
        self._dv: DataView | None = None

        self.pack_start(Gtk.Label(label="Go to offset:"), False, False, 0)

        self._entry = Gtk.Entry()
        self._entry.set_width_chars(18)
        self._entry.set_placeholder_text("decimal or 0x…")
        self._entry.connect("activate",        lambda _: self._go())
        self._entry.connect("key-press-event", self._on_key)
        self.pack_start(self._entry, False, False, 0)

        btn = Gtk.Button(label="Go")
        btn.connect("clicked", lambda _: self._go())
        self.pack_start(btn, False, False, 0)

        self._status = Gtk.Label(label="", xalign=0.0)
        self._status.set_width_chars(20)
        self.pack_start(self._status, False, False, 0)

        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic",
                                               Gtk.IconSize.MENU))
        close.connect("clicked", lambda _: self.hide_bar())
        self.pack_end(close, False, False, 0)

        self.set_no_show_all(True)

    def attach_view(self, dv: DataView) -> None:
        self._dv = dv

    def show_bar(self) -> None:
        self.set_no_show_all(False)
        self.show_all()
        self._entry.grab_focus()
        self._entry.select_region(0, -1)

    def hide_bar(self) -> None:
        self.hide()

    def _on_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    def _go(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            self._status.set_markup('<span foreground="red">No file open.</span>')
            return
        offset = _parse_offset(self._entry.get_text())
        if offset is None:
            self._status.set_markup(
                '<span foreground="red">Invalid offset.</span>')
            return
        buf_size = dv.buffer.size
        if offset < 0 or offset >= buf_size:
            self._status.set_markup(
                f'<span foreground="red">Out of range (0–0x{max(0,buf_size-1):x}).</span>')
            return
        dv.display.make_offset_visible(offset, "start")
        dv.move_cursor(offset, 0)
        dv.set_selection(-1, -1)
        self._status.set_markup(
            f'<span foreground="#006600">Jumped to 0x{offset:x}.</span>')
        self.hide_bar()
