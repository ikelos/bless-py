# bless/gui/conversion_panel.py
# Copyright (c) 2024 – Python port
# GPL-2.0-or-later

from __future__ import annotations
import struct
from typing import Optional, TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

if TYPE_CHECKING:
    from .data_view import DataView


class ConversionPanel(Gtk.Frame):
    """
    Bottom panel that shows multi-format interpretations of the bytes at
    the current cursor position — matching the original Bless conversion table.
    """

    def __init__(self) -> None:
        super().__init__(label=None)
        self.set_shadow_type(Gtk.ShadowType.NONE)

        self._dv: Optional["DataView"] = None

        grid = Gtk.Grid(column_spacing=12, row_spacing=4,
                        margin_top=4, margin_bottom=4,
                        margin_start=8, margin_end=8)
        self.add(grid)

        # ── Column 0-1: integer interpretations ─────────────────────────
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

        def make_label(text: str, bold: bool = False) -> Gtk.Label:
            lbl = Gtk.Label(label=text, xalign=1.0 if bold else 0.0)
            if bold:
                lbl.set_markup(f"<b>{text}</b>")
            return lbl

        def make_val(key: str) -> Gtk.Label:
            lbl = Gtk.Label(label="—", xalign=0.0, selectable=True)
            self._value_labels[key] = lbl
            return lbl

        for row, lbl in enumerate(col0_labels):
            key = lbl.rstrip(":")
            grid.attach(make_label(lbl, True), 0, row, 1, 1)
            grid.attach(make_val(key), 1, row, 1, 1)

        for row, lbl in enumerate(col2_labels):
            key = lbl.rstrip(":")
            grid.attach(make_label(lbl, True), 2, row, 1, 1)
            grid.attach(make_val(key), 3, row, 1, 1)

        for row, lbl in enumerate(col4_labels):
            key = lbl.rstrip(":")
            grid.attach(make_label(lbl, True), 4, row, 1, 1)
            grid.attach(make_val(key), 5, row, 1, 1)

        # ── Little-endian toggle ─────────────────────────────────────────
        self._le_check = Gtk.CheckButton(label="Show little endian decoding")
        grid.attach(self._le_check, 0, 6, 3, 1)
        self._le_check.connect("toggled", lambda _: self._refresh())

        # ── Unsigned-as-hex toggle ───────────────────────────────────────
        self._hex_check = Gtk.CheckButton(label="Show unsigned as hexadecimal")
        grid.attach(self._hex_check, 3, 6, 3, 1)
        self._hex_check.connect("toggled", lambda _: self._refresh())

        # ── Status bar row ───────────────────────────────────────────────
        self._offset_label = Gtk.Label(label="Offset: —", xalign=0.0)
        self._size_label   = Gtk.Label(label="Size: —",   xalign=0.0)
        self._sel_label    = Gtk.Label(label="Selection: None", xalign=0.0)
        self._mode_label   = Gtk.Label(label="INS", xalign=1.0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
                             margin_top=2)
        for w in (self._offset_label, self._size_label,
                  self._sel_label, self._mode_label):
            status_box.pack_start(w, False, False, 0)
        status_box.pack_end(self._mode_label, False, False, 0)
        grid.attach(status_box, 0, 7, 6, 1)

        self._current_bytes = b""
        self._current_offset = 0

    # ------------------------------------------------------------------
    # Attachment / detachment
    # ------------------------------------------------------------------

    def attach_view(self, dv: "DataView") -> None:
        if self._dv is not None:
            self._detach_view()
        self._dv = dv
        dv.connect_cursor_changed(self._on_cursor_changed)
        dv.connect_selection_changed(self._on_cursor_changed)
        dv.connect_overwrite_changed(self._on_overwrite_changed)
        dv.connect_buffer_changed(self._on_cursor_changed)
        self._refresh_full()

    def _detach_view(self) -> None:
        self._dv = None
        self._clear_all()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _on_cursor_changed(self, dv: "DataView") -> None:
        self._refresh_full()

    def _on_overwrite_changed(self, dv: "DataView") -> None:
        if self._dv is None:
            return
        self._mode_label.set_text("OVR" if self._dv.overwrite else "INS")

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def _refresh_full(self) -> None:
        dv = self._dv
        if dv is None or dv.buffer is None:
            self._clear_all()
            return

        buf    = dv.buffer
        offset = dv.cursor_offset
        size   = buf.size
        sel    = dv.selection

        # Grab up to 8 bytes from cursor position
        n = min(8, max(0, size - offset))
        raw = bytearray(n)
        for i in range(n):
            raw[i] = buf[offset + i]
        self._current_bytes  = bytes(raw)
        self._current_offset = offset

        self._refresh()

        # Status bar
        self._offset_label.set_text(f"Offset: 0x{offset:x} / 0x{max(0,size-1):x}")
        self._size_label.set_text(f"Size: {size}")
        if sel.is_empty():
            self._sel_label.set_text("Selection: None")
        else:
            self._sel_label.set_text(
                f"Selection: 0x{sel.start:x}–0x{sel.end:x} "
                f"({sel.end - sel.start + 1} bytes)")
        self._mode_label.set_text("OVR" if dv.overwrite else "INS")

    def _refresh(self) -> None:
        data   = self._current_bytes
        le     = self._le_check.get_active()
        as_hex = self._hex_check.get_active()
        end    = "<" if le else ">"

        def _set(key: str, value: str) -> None:
            lbl = self._value_labels.get(key)
            if lbl:
                lbl.set_text(value)

        def _int(key: str, fmt: str, nbytes: int) -> None:
            if len(data) >= nbytes:
                try:
                    v = struct.unpack_from(end + fmt, data)[0]
                    _set(key, f"0x{v:x}" if (as_hex and fmt.isupper()) else str(v))
                except struct.error:
                    _set(key, "—")
            else:
                _set(key, "—")

        def _float(key: str, fmt: str, nbytes: int) -> None:
            if len(data) >= nbytes:
                try:
                    v = struct.unpack_from(end + fmt, data)[0]
                    _set(key, f"{v:.8g}")
                except struct.error:
                    _set(key, "—")
            else:
                _set(key, "—")

        b0 = data[0] if data else None

        _set("Signed 8 bit",   str(struct.unpack("b", data[:1])[0]) if b0 is not None else "—")
        _set("Unsigned 8 bit", str(b0) if b0 is not None else "—")
        _int("Signed 16 bit",   "h", 2)
        _int("Unsigned 16 bit", "H", 2)
        _int("Signed 32 bit",   "i", 4)
        _int("Unsigned 32 bit", "I", 4)
        _int("Signed 64 bit",   "q", 8)
        _int("Unsigned 64 bit", "Q", 8)
        _float("Float 32 bit",  "f", 4)
        _float("Float 64 bit",  "d", 8)

        if b0 is not None:
            _set("Hexadecimal", " ".join(f"{x:02X}" for x in data[:4]))
            _set("Decimal",     " ".join(str(x)     for x in data[:4]))
            _set("Octal",       " ".join(f"{x:03o}" for x in data[:4]))
            _set("Binary",      format(b0, "08b"))
            try:
                ascii_part = "".join(
                    chr(x) if 0x20 <= x < 0x7F else "." for x in data[:8])
                _set("ASCII Text", ascii_part)
            except Exception:
                _set("ASCII Text", "—")
        else:
            for k in ("Hexadecimal","Decimal","Octal","Binary","ASCII Text"):
                _set(k, "—")

    def _clear_all(self) -> None:
        for lbl in self._value_labels.values():
            lbl.set_text("—")
        self._offset_label.set_text("Offset: —")
        self._size_label.set_text("Size: —")
        self._sel_label.set_text("Selection: None")
        self._mode_label.set_text("INS")
