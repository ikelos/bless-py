# bless/gui/plugins/file_operations.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...buffers.byte_buffer import ByteBuffer

if TYPE_CHECKING:
    from ..data_book import DataBook
    from ..data_view import DataView


class FileOperations:
    """
    Provides New, Open, Save, Save As, Revert and Close operations
    that operate on the DataBook's current DataView.
    """

    def __init__(self, data_book: DataBook, parent: Gtk.Window) -> None:
        self._book  = data_book
        self._parent = parent

    # ------------------------------------------------------------------
    # New
    # ------------------------------------------------------------------

    def new_file(self) -> DataView:
        dv = self._book.add_page("Untitled")
        bb = ByteBuffer()
        dv.buffer = bb
        return dv

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    def open_file(self, filename: str | None = None) -> DataView | None:
        if filename is None:
            filename = self._choose_file_to_open()
        if not filename:
            return None

        # Check if already open
        for dv in self._book.views:
            if dv.buffer and dv.buffer.has_file and dv.buffer.filename == filename:
                self._book.set_current_page(
                    self._book.page_num(dv.display))
                return dv

        try:
            bb = ByteBuffer.from_file(filename)
        except Exception as ex:
            self._error(f"Cannot open '{os.path.basename(filename)}'", str(ex))
            return None

        title = os.path.basename(filename)
        dv = self._book.add_page(title)
        dv.buffer = bb
        return dv

    def _choose_file_to_open(self) -> str | None:
        dialog = Gtk.FileChooserDialog(
            title="Open File",
            parent=self._parent,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,   Gtk.ResponseType.OK,
        )
        filename = None
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
        dialog.destroy()
        return filename

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_file(self, dv: DataView | None = None) -> None:
        if dv is None:
            dv = self._book.current_view
        if dv is None or dv.buffer is None:
            return
        if not dv.buffer.has_file:
            self.save_file_as(dv)
            return
        self._do_save(dv, dv.buffer.filename)

    def save_file_as(self, dv: DataView | None = None) -> None:
        if dv is None:
            dv = self._book.current_view
        if dv is None or dv.buffer is None:
            return
        filename = self._choose_file_to_save()
        if not filename:
            return
        self._do_save(dv, filename)

    def _do_save(self, dv: DataView, filename: str) -> None:
        bb = dv.buffer
        if not bb:
            return

        dialog = Gtk.MessageDialog(
            parent=self._parent,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            text=f"Saving '{os.path.basename(filename)}'…",
        )
        dialog.show()

        def _done():
            dialog.destroy()
            if bb.has_file:
                self._book._on_buffer_changed(dv)

        bb.begin_save_as(filename, done_cb=_done)

    def _choose_file_to_save(self) -> str | None:
        dialog = Gtk.FileChooserDialog(
            title="Save File As",
            parent=self._parent,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,   Gtk.ResponseType.OK,
        )
        dialog.set_do_overwrite_confirmation(True)
        filename = None
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
        dialog.destroy()
        return filename

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def revert_file(self, dv: DataView | None = None) -> None:
        if dv is None:
            dv = self._book.current_view
        if dv is None or dv.buffer is None:
            return
        if not dv.buffer.has_file:
            return

        md = Gtk.MessageDialog(
            parent=self._parent,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Revert '{os.path.basename(dv.buffer.filename)}'?",
        )
        md.format_secondary_text(
            "All unsaved changes will be permanently lost.")
        if md.run() == Gtk.ResponseType.YES:
            dv.revert()
        md.destroy()

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close_file(self, dv: DataView | None = None) -> bool:
        """Returns True if the page was closed (or user chose not to save)."""
        if dv is None:
            dv = self._book.current_view
        if dv is None:
            return True

        if dv.buffer and dv.buffer.has_changed:
            name = (os.path.basename(dv.buffer.filename)
                    if dv.buffer.has_file else "Untitled")
            md = Gtk.MessageDialog(
                parent=self._parent,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.WARNING,
                text=f"Save changes to '{name}' before closing?",
            )
            md.add_buttons(
                "Close without saving", Gtk.ResponseType.NO,
                Gtk.STOCK_CANCEL,       Gtk.ResponseType.CANCEL,
                Gtk.STOCK_SAVE,         Gtk.ResponseType.YES,
            )
            resp = md.run()
            md.destroy()
            if resp == Gtk.ResponseType.YES:
                self.save_file(dv)
            elif resp == Gtk.ResponseType.CANCEL:
                return False

        self._book.close_page(dv)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _error(self, title: str, message: str) -> None:
        md = Gtk.MessageDialog(
            parent=self._parent,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        md.format_secondary_text(message)
        md.run()
        md.destroy()
