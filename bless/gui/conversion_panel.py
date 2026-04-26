# bless/gui/conversion_panel.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

if TYPE_CHECKING:
    from .data_view import DataView

# Fixed char widths so column positions never shift
_VAL_CHARS = {
    "Signed 8 bit": 5,  # -128 .. 127
    "Unsigned 8 bit": 3,  # 0 .. 255
    "Signed 16 bit": 7,  # -32768 .. 32767
    "Unsigned 16 bit": 5,
    "Signed 32 bit": 12,  # -2147483648
    "Unsigned 32 bit": 10,
    "Signed 64 bit": 21,
    "Unsigned 64 bit": 20,
    "Float 32 bit": 16,
    "Float 64 bit": 24,
    "Hexadecimal": 14,  # "XX XX XX XX"
    "Decimal": 12,  # "000 000 000 000"
    "Octal": 16,
    "Binary": 9,  # "00000000"
    "ASCII Text": 9,  # 8 chars + padding
}


class ConversionPanel(Gtk.Frame):
    """
    Bottom panel showing multi-format byte interpretations.
    All value labels use fixed-width monospace text so the column
    positions never shift as values change.
    """

    def __init__(self) -> None:
        super().__init__(label=None)
        self.set_shadow_type(Gtk.ShadowType.NONE)

        self._dv: DataView | None = None

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(sep, False, False, 0)

        grid = Gtk.Grid(
            column_spacing=8,
            row_spacing=4,
            margin_top=4,
            margin_bottom=4,
            margin_start=8,
            margin_end=8,
        )
        vbox.pack_start(grid, False, False, 0)

        col0_labels = [
            "Signed 8 bit:",
            "Unsigned 8 bit:",
            "Signed 16 bit:",
            "Unsigned 16 bit:",
            "Signed 32 bit:",
            "Unsigned 32 bit:",
        ]
        col2_labels = [
            "Signed 64 bit:",
            "Unsigned 64 bit:",
            "Float 32 bit:",
            "Float 64 bit:",
        ]
        col4_labels = [
            "Hexadecimal:",
            "Decimal:",
            "Octal:",
            "Binary:",
            "ASCII Text:",
        ]

        self._value_labels: dict[str, Gtk.Label] = {}

        def _head(text: str) -> Gtk.Label:
            lbl = Gtk.Label(xalign=1.0)
            lbl.set_markup(f"<b>{text}</b>")
            return lbl

        def _val(key: str) -> Gtk.Label:
            chars = _VAL_CHARS.get(key, 12)
            lbl = Gtk.Label(label="—", xalign=0.0, selectable=True)
            # Fixed-width monospace so column layout never shifts
            lbl.set_width_chars(chars)
            lbl.set_max_width_chars(chars)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            # Use monospace font attribute for all value labels
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_family_new("Monospace"))
            lbl.set_attributes(attrs)
            self._value_labels[key] = lbl
            return lbl

        for row, text in enumerate(col0_labels):
            key = text.rstrip(":")
            grid.attach(_head(text), 0, row, 1, 1)
            grid.attach(_val(key), 1, row, 1, 1)

        for row, text in enumerate(col2_labels):
            key = text.rstrip(":")
            grid.attach(_head(text), 2, row, 1, 1)
            grid.attach(_val(key), 3, row, 1, 1)

        for row, text in enumerate(col4_labels):
            key = text.rstrip(":")
            grid.attach(_head(text), 4, row, 1, 1)
            grid.attach(_val(key), 5, row, 1, 1)

        self._le_check = Gtk.CheckButton(label="Show little endian decoding")
        grid.attach(self._le_check, 0, 6, 3, 1)
        self._le_check.connect("toggled", lambda _: self._refresh())

        self._hex_check = Gtk.CheckButton(label="Show unsigned as hexadecimal")
        grid.attach(self._hex_check, 3, 6, 3, 1)
        self._hex_check.connect("toggled", lambda _: self._refresh())

        self._current_bytes = b""
        self._current_offset = 0

    def attach_view(self, dv: DataView) -> None:
        self._dv = dv
        dv.connect_cursor_changed(lambda _: self._refresh_full())
        dv.connect_selection_changed(lambda _: self._refresh_full())
        dv.connect_buffer_changed(lambda _: self._refresh_full())
        self._refresh_full()

    def _refresh_full(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            self._clear()
            return
        buf = dv.buffer
        offset = max(0, min(dv.cursor_offset, buf.size - 1)) if buf.size > 0 else 0
        n = min(8, max(0, buf.size - offset))
        raw = bytearray(n)
        for i in range(n):
            raw[i] = buf[offset + i]
        self._current_bytes = bytes(raw)
        self._current_offset = offset
        self._refresh()

    def _refresh(self) -> None:
        data = self._current_bytes
        le = self._le_check.get_active()
        as_hex = self._hex_check.get_active()
        end = "<" if le else ">"

        def _set(key: str, value: str) -> None:
            lbl = self._value_labels.get(key)
            if lbl:
                lbl.set_text(value)

        def _int(key: str, fmt: str, nb: int) -> None:
            if len(data) >= nb:
                try:
                    v = struct.unpack_from(end + fmt, data)[0]
                    _set(key, f"0x{v:x}" if (as_hex and fmt.isupper()) else str(v))
                except struct.error:
                    _set(key, "—")
            else:
                _set(key, "—")

        def _float(key: str, fmt: str, nb: int) -> None:
            if len(data) >= nb:
                try:
                    v = struct.unpack_from(end + fmt, data)[0]
                    _set(key, f"{v:.8g}")
                except struct.error:
                    _set(key, "—")
            else:
                _set(key, "—")

        b0 = data[0] if data else None

        _set("Signed 8 bit", str(struct.unpack("b", data[:1])[0]) if b0 is not None else "—")
        _set("Unsigned 8 bit", str(b0) if b0 is not None else "—")
        _int("Signed 16 bit", "h", 2)
        _int("Unsigned 16 bit", "H", 2)
        _int("Signed 32 bit", "i", 4)
        _int("Unsigned 32 bit", "I", 4)
        _int("Signed 64 bit", "q", 8)
        _int("Unsigned 64 bit", "Q", 8)
        _float("Float 32 bit", "f", 4)
        _float("Float 64 bit", "d", 8)

        if b0 is not None:
            _set("Hexadecimal", " ".join(f"{x:02X}" for x in data[:4]))
            _set("Decimal", " ".join(str(x) for x in data[:4]))
            _set("Octal", " ".join(f"{x:03o}" for x in data[:4]))
            _set("Binary", format(b0, "08b"))
            _set("ASCII Text", "".join(chr(x) if 0x20 <= x < 0x7F else "." for x in data[:8]))
        else:
            for k in ("Hexadecimal", "Decimal", "Octal", "Binary", "ASCII Text"):
                _set(k, "—")

    def _clear(self) -> None:
        for lbl in self._value_labels.values():
            lbl.set_text("—")
