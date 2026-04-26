# bless/gui/plugins/find_replace.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from ...tools.find import BMFindStrategy, FindOperation, SimpleFindStrategy
from ...util.base_converter import string_to_byte_array

if TYPE_CHECKING:
    from ..data_book import DataBook


class FindReplaceDialog(Gtk.Dialog):
    """
    Find & Replace dialog supporting:
      - Hex / ASCII / Decimal / Octal / Binary input formats
      - Boyer-Moore and Simple search strategies
      - Forward and backward search
      - Replace and Replace All
    """

    _BASE_MAP = {
        "Hexadecimal": 16,
        "Decimal":     10,
        "Octal":       8,
        "Binary":      2,
        "ASCII":       None,  # raw bytes
    }

    def __init__(self, data_book: DataBook, parent: Gtk.Window) -> None:
        super().__init__(title="Find & Replace", parent=parent,
                         flags=Gtk.DialogFlags.DESTROY_WITH_PARENT)
        self._book    = data_book
        self._op: FindOperation | None = None

        self.set_resizable(True)
        self.set_default_size(480, -1)

        grid = Gtk.Grid(column_spacing=8, row_spacing=6,
                        margin_top=12, margin_bottom=4,
                        margin_start=12, margin_end=12)
        self.get_content_area().pack_start(grid, True, True, 0)

        # Find row
        grid.attach(Gtk.Label(label="Find:", xalign=0), 0, 0, 1, 1)
        self._find_entry = Gtk.Entry(hexpand=True)
        grid.attach(self._find_entry, 1, 0, 2, 1)

        # Replace row
        grid.attach(Gtk.Label(label="Replace:", xalign=0), 0, 1, 1, 1)
        self._replace_entry = Gtk.Entry(hexpand=True)
        grid.attach(self._replace_entry, 1, 1, 2, 1)

        # Format combo
        grid.attach(Gtk.Label(label="Format:", xalign=0), 0, 2, 1, 1)
        self._fmt_combo = Gtk.ComboBoxText()
        for fmt in self._BASE_MAP:
            self._fmt_combo.append_text(fmt)
        self._fmt_combo.set_active(0)
        grid.attach(self._fmt_combo, 1, 2, 1, 1)

        # Strategy combo
        self._strat_combo = Gtk.ComboBoxText()
        self._strat_combo.append_text("Boyer-Moore")
        self._strat_combo.append_text("Simple")
        self._strat_combo.set_active(0)
        grid.attach(self._strat_combo, 2, 2, 1, 1)

        # Status label
        self._status_label = Gtk.Label(label="", xalign=0)
        self._status_label.set_markup("<i>Ready</i>")
        grid.attach(self._status_label, 0, 3, 3, 1)

        # Buttons
        btn_box = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL,
                                layout_style=Gtk.ButtonBoxStyle.END,
                                spacing=6)

        self._btn_prev    = Gtk.Button(label="← Previous")
        self._btn_next    = Gtk.Button(label="Next →")
        self._btn_replace = Gtk.Button(label="Replace")
        self._btn_all     = Gtk.Button(label="Replace All")
        self._btn_cancel  = Gtk.Button(label="Cancel")

        for b in (self._btn_prev, self._btn_next,
                  self._btn_replace, self._btn_all, self._btn_cancel):
            btn_box.pack_start(b, False, False, 0)

        grid.attach(btn_box, 0, 4, 3, 1)

        self._btn_prev.connect("clicked",   lambda b: self._search(forward=False))
        self._btn_next.connect("clicked",   lambda b: self._search(forward=True))
        self._btn_replace.connect("clicked",lambda b: self._replace_one())
        self._btn_all.connect("clicked",    lambda b: self._replace_all())
        self._btn_cancel.connect("clicked", lambda b: self.hide())

        self.connect("delete-event", lambda w, e: (w.hide(), True)[-1])
        self.show_all()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_entry(self, text: str) -> bytes | None:
        fmt_name = self._fmt_combo.get_active_text()
        base = self._BASE_MAP.get(fmt_name)
        if not text.strip():
            return b""
        try:
            if base is None:
                return text.encode("utf-8", errors="replace")
            return string_to_byte_array(text, base)
        except (ValueError, KeyError):
            return None

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "red" if error else "#006600"
        self._status_label.set_markup(f'<span foreground="{color}">{msg}</span>')

    def _make_strategy(self):
        if self._strat_combo.get_active() == 0:
            return BMFindStrategy()
        return SimpleFindStrategy()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self, forward: bool = True) -> None:
        dv = self._book.current_view
        if dv is None or dv.buffer is None:
            self._set_status("No file open.", error=True)
            return

        data = self._parse_entry(self._find_entry.get_text())
        if data is None:
            self._set_status("Invalid search pattern.", error=True)
            return

        strategy = self._make_strategy()
        strategy.pattern = data
        strategy.buffer  = dv.buffer
        strategy.position = (dv.cursor_offset if forward
                             else dv.cursor_offset)

        self._btn_next.set_sensitive(False)
        self._btn_prev.set_sensitive(False)

        def _done(op: FindOperation) -> None:
            def _idle():
                self._btn_next.set_sensitive(True)
                self._btn_prev.set_sensitive(True)
                if op.match:
                    dv.set_selection(op.match.start, op.match.end)
                    dv.move_cursor(op.match.end + 1, 0)
                    dv.display.make_offset_visible(op.match.start, "start")
                    self._set_status(
                        f"Found at offset 0x{op.match.start:X}.")
                else:
                    self._set_status("Pattern not found.", error=True)
                return False
            GLib.idle_add(_idle)

        self._op = FindOperation(strategy, forward=forward, done_cb=_done)
        self._op.start()

    # ------------------------------------------------------------------
    # Replace
    # ------------------------------------------------------------------

    def _replace_one(self) -> None:
        dv = self._book.current_view
        if dv is None or dv.buffer is None:
            return
        sel = dv.selection
        if sel.is_empty():
            self._search(forward=True)
            return
        repl = self._parse_entry(self._replace_entry.get_text())
        if repl is None:
            return
        dv.buffer.replace(sel.start, sel.end, repl)
        dv.set_selection(-1, -1)
        self._set_status("Replaced 1 occurrence.")
        self._search(forward=True)

    def _replace_all(self) -> None:
        dv = self._book.current_view
        if dv is None or dv.buffer is None:
            return

        find_data = self._parse_entry(self._find_entry.get_text())
        repl_data = self._parse_entry(self._replace_entry.get_text())
        if find_data is None or repl_data is None or not find_data:
            return

        strategy = self._make_strategy()
        strategy.pattern  = find_data
        strategy.buffer   = dv.buffer
        strategy.position = 0

        count = 0
        dv.buffer.begin_action_chaining()
        try:
            offset_delta = 0
            while True:
                strategy.position += offset_delta
                m = strategy.find_next()
                if m is None:
                    break
                dv.buffer.replace(m.start, m.end, repl_data)
                count += 1
                offset_delta = len(repl_data)
                strategy.position = m.start + offset_delta
        finally:
            dv.buffer.end_action_chaining()

        self._set_status(f"Replaced {count} occurrence(s).")
