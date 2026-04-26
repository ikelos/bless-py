# bless/gui/select_range_bar.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from .data_view import DataView


def _parse_val(text: str) -> int | None:
    """Parse a decimal integer or 0x-prefixed hex string.  Returns None if invalid."""
    t = text.strip()
    if not t:
        return None
    try:
        if t.startswith("0x") or t.startswith("0X"):
            return int(t, 16)
        return int(t, 10)
    except ValueError:
        return None


class SelectRangeBar(Gtk.Box):
    """
    Inline bar (Shift+Ctrl+R) that selects a byte range.

    Layout mirrors the range.png mockup:
      [Select range from:] [entry_from]  [to/±length] [entry_to]  [✓ Select] [×]

    Both fields accept decimal integers or 0x… hex values.
    The Select button is greyed out until both fields contain valid values.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         margin_top=3, margin_bottom=3,
                         margin_start=6, margin_end=6)
        self._dv: DataView | None = None

        self.pack_start(Gtk.Label(label="Select range from:"), False, False, 0)

        self._from_entry = Gtk.Entry()
        self._from_entry.set_width_chars(14)
        self._from_entry.set_placeholder_text("0 or 0x…")
        self.pack_start(self._from_entry, False, False, 0)

        self.pack_start(Gtk.Label(label="to/±length"), False, False, 0)

        self._to_entry = Gtk.Entry()
        self._to_entry.set_width_chars(14)
        self._to_entry.set_placeholder_text("end or 0x…")
        self.pack_start(self._to_entry, False, False, 0)

        # Select button with a check-mark icon
        self._btn_select = Gtk.Button()
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.pack_start(
            Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.BUTTON),
            False, False, 0)
        btn_box.pack_start(Gtk.Label(label="Select"), False, False, 0)
        self._btn_select.add(btn_box)
        self._btn_select.set_sensitive(False)
        self._btn_select.connect("clicked", lambda _: self._do_select())
        self.pack_start(self._btn_select, False, False, 0)

        # Close button
        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic",
                                               Gtk.IconSize.MENU))
        close.connect("clicked", lambda _: self.hide_bar())
        self.pack_start(close, False, False, 0)

        # Wire validation to every keystroke
        self._from_entry.connect("changed", lambda _: self._validate())
        self._to_entry.connect("changed",   lambda _: self._validate())
        self._from_entry.connect("activate", lambda _: self._to_entry.grab_focus())
        self._to_entry.connect("activate",   lambda _: self._do_select())
        self._from_entry.connect("key-press-event", self._on_key)
        self._to_entry.connect("key-press-event",   self._on_key)

        self.set_no_show_all(True)

    # ------------------------------------------------------------------

    def attach_view(self, dv: DataView) -> None:
        self._dv = dv

    def show_bar(self) -> None:
        self.set_no_show_all(False)
        self.show_all()
        self._from_entry.grab_focus()
        self._from_entry.select_region(0, -1)

    def hide_bar(self) -> None:
        self.hide()

    def _on_key(self, widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        return False

    # ------------------------------------------------------------------

    def _validate(self) -> bool:
        """Return True and enable Select button when both fields are valid."""
        a = _parse_val(self._from_entry.get_text())
        b = _parse_val(self._to_entry.get_text())
        ok = (a is not None and b is not None)
        self._btn_select.set_sensitive(ok)
        return ok

    def _do_select(self) -> None:
        if not self._validate():
            return
        dv = self._dv
        if dv is None or dv.buffer is None:
            return
        a = _parse_val(self._from_entry.get_text())
        b = _parse_val(self._to_entry.get_text())
        if a is None or b is None:
            return
        # Always select lowest→highest regardless of input order
        lo, hi = min(a, b), max(a, b)
        buf_size = dv.buffer.size
        lo = max(0, min(lo, buf_size - 1))
        hi = max(0, min(hi, buf_size - 1))
        dv.set_selection(lo, hi)
        dv.move_cursor(lo, 0)
        dv.display.make_offset_visible(lo, "start")
        self.hide_bar()
