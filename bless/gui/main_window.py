# bless/gui/main_window.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations
import os
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from ..buffers.byte_buffer import ByteBuffer
from .data_book import DataBook
from .data_view import DataView
from .plugins.file_operations import FileOperations
from .plugins.find_replace import FindReplaceDialog
from ..tools.preferences import Preferences


class MainWindow(Gtk.ApplicationWindow):
    """
    Top-level application window.

    Builds the menu bar, toolbar and status bar; creates a DataBook;
    wires up all file / edit / search actions; and handles drag-and-drop.
    """

    def __init__(self, app: Gtk.Application, files: list[str] = None) -> None:
        super().__init__(application=app, title="Bless Hex Editor")
        self.set_default_size(900, 600)
        self.set_icon_name("accessories-text-editor")

        self._data_book = DataBook()
        self._file_ops  = FileOperations(self._data_book, self)
        self._find_dlg: FindReplaceDialog | None = None

        self._build_ui()
        self._wire_events()
        self._load_prefs()

        # Open files from command line
        if files:
            for f in files:
                self._file_ops.open_file(f)
        else:
            self._file_ops.new_file()

        self.show_all()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # Menu bar
        menu_bar = self._build_menu_bar()
        root.pack_start(menu_bar, False, False, 0)

        # Toolbar
        self._toolbar = self._build_toolbar()
        root.pack_start(self._toolbar, False, False, 0)

        # DataBook (tabs)
        root.pack_start(self._data_book, True, True, 0)

        # Status bar
        self._statusbar = Gtk.Statusbar()
        root.pack_start(self._statusbar, False, False, 0)
        self._ctx = self._statusbar.get_context_id("main")

    def _build_menu_bar(self) -> Gtk.MenuBar:
        mb = Gtk.MenuBar()

        # File menu
        file_menu = Gtk.Menu()
        for label, cb in (
            ("_New",          lambda *_: self._file_ops.new_file()),
            ("_Open…",        lambda *_: self._file_ops.open_file()),
            ("_Save",         lambda *_: self._file_ops.save_file()),
            ("Save _As…",     lambda *_: self._file_ops.save_file_as()),
            ("_Revert",       lambda *_: self._file_ops.revert_file()),
            (None, None),
            ("_Close",        lambda *_: self._file_ops.close_file()),
            ("_Quit",         lambda *_: self.get_application().quit()),
        ):
            if label is None:
                file_menu.append(Gtk.SeparatorMenuItem())
            else:
                item = Gtk.MenuItem.new_with_mnemonic(label)
                item.connect("activate", cb)
                file_menu.append(item)
        file_item = Gtk.MenuItem.new_with_mnemonic("_File")
        file_item.set_submenu(file_menu)
        mb.append(file_item)

        # Edit menu
        edit_menu = Gtk.Menu()
        for label, cb in (
            ("_Undo",         lambda *_: self._current_dv_call("undo")),
            ("_Redo",         lambda *_: self._current_dv_call("redo")),
            (None, None),
            ("Cu_t",          lambda *_: self._current_dv_call("cut")),
            ("_Copy",         lambda *_: self._current_dv_call("copy")),
            ("_Paste",        lambda *_: self._current_dv_call("paste")),
            ("_Delete",       lambda *_: self._current_dv_call("delete")),
            (None, None),
            ("Select _All",   lambda *_: self._select_all()),
        ):
            if label is None:
                edit_menu.append(Gtk.SeparatorMenuItem())
            else:
                item = Gtk.MenuItem.new_with_mnemonic(label)
                item.connect("activate", cb)
                edit_menu.append(item)
        edit_item = Gtk.MenuItem.new_with_mnemonic("_Edit")
        edit_item.set_submenu(edit_menu)
        mb.append(edit_item)

        # Search menu
        search_menu = Gtk.Menu()
        find_item = Gtk.MenuItem.new_with_mnemonic("_Find & Replace…")
        find_item.connect("activate", lambda *_: self._show_find_dialog())
        search_menu.append(find_item)
        search_item = Gtk.MenuItem.new_with_mnemonic("_Search")
        search_item.set_submenu(search_menu)
        mb.append(search_item)

        # Help menu
        help_menu = Gtk.Menu()
        about_item = Gtk.MenuItem.new_with_mnemonic("_About")
        about_item.connect("activate", lambda *_: self._show_about())
        help_menu.append(about_item)
        help_item = Gtk.MenuItem.new_with_mnemonic("_Help")
        help_item.set_submenu(help_menu)
        mb.append(help_item)

        return mb

    def _build_toolbar(self) -> Gtk.Toolbar:
        tb = Gtk.Toolbar()
        tb.set_style(Gtk.ToolbarStyle.ICONS)
        for icon, tooltip, cb in (
            ("document-new",  "New",     lambda *_: self._file_ops.new_file()),
            ("document-open", "Open",    lambda *_: self._file_ops.open_file()),
            ("document-save", "Save",    lambda *_: self._file_ops.save_file()),
            (None, None, None),
            ("edit-cut",      "Cut",     lambda *_: self._current_dv_call("cut")),
            ("edit-copy",     "Copy",    lambda *_: self._current_dv_call("copy")),
            ("edit-paste",    "Paste",   lambda *_: self._current_dv_call("paste")),
            (None, None, None),
            ("edit-undo",     "Undo",    lambda *_: self._current_dv_call("undo")),
            ("edit-redo",     "Redo",    lambda *_: self._current_dv_call("redo")),
            (None, None, None),
            ("edit-find",     "Find",    lambda *_: self._show_find_dialog()),
        ):
            if icon is None:
                tb.insert(Gtk.SeparatorToolItem(), -1)
            else:
                btn = Gtk.ToolButton.new(
                    Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR),
                    tooltip)
                btn.set_tooltip_text(tooltip)
                btn.connect("clicked", cb)
                tb.insert(btn, -1)
        return tb

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _current_dv_call(self, method: str) -> None:
        dv = self._data_book.current_view
        if dv:
            getattr(dv, method)()

    def _select_all(self) -> None:
        dv = self._data_book.current_view
        if dv and dv.buffer:
            dv.set_selection(0, dv.buffer.size - 1)

    def _show_find_dialog(self) -> None:
        if self._find_dlg is None:
            self._find_dlg = FindReplaceDialog(self._data_book, self)
        self._find_dlg.present()

    def _show_about(self) -> None:
        dlg = Gtk.AboutDialog(transient_for=self, modal=True)
        dlg.set_program_name("Bless Hex Editor")
        dlg.set_comments(
            "A GTK hex editor — Python/GObject-Introspection port "
            "of Alexandros Frantzis's original C# Bless."
        )
        dlg.set_license_type(Gtk.License.GPL_2_0)
        dlg.run()
        dlg.destroy()

    # ------------------------------------------------------------------
    # Events / preferences
    # ------------------------------------------------------------------

    def _wire_events(self) -> None:
        self.connect("delete-event", self._on_delete_event)

        # Drag-and-drop (open files by dropping URIs)
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.connect("drag-data-received", self._on_drag_data_received)

        # DataBook callbacks
        self._data_book.connect_page_added(self._on_page_added)
        self._data_book.connect_switch_page(self._on_switch_page)

    def _on_delete_event(self, widget, event) -> bool:
        # Try to close all pages; if any cancels, block quit
        views = list(self._data_book.views)
        for dv in views:
            if not self._file_ops.close_file(dv):
                return True  # user cancelled
        return False

    def _on_drag_data_received(self, widget, ctx, x, y, data, info, time) -> None:
        uris = data.get_uris()
        for uri in uris:
            if uri.startswith("file://"):
                path = uri[7:].rstrip("\r\n")
                self._file_ops.open_file(path)
        Gtk.drag_finish(ctx, True, False, time)

    def _on_page_added(self, dv: DataView) -> None:
        dv.connect_buffer_changed(self._on_dv_buffer_changed)
        dv.connect_cursor_changed(self._on_dv_cursor_changed)

    def _on_switch_page(self, nb, widget, n) -> None:
        dv = self._data_book.current_view
        if dv:
            self._update_title(dv)

    def _on_dv_buffer_changed(self, dv: DataView) -> None:
        self._update_title(dv)

    def _on_dv_cursor_changed(self, dv: DataView) -> None:
        if dv is not self._data_book.current_view:
            return
        self._statusbar.pop(self._ctx)
        off = dv.cursor_offset
        val = ""
        if dv.buffer and off < dv.buffer.size:
            b = dv.buffer[off]
            val = f"  |  Value: 0x{b:02X} ({b})"
        self._statusbar.push(
            self._ctx,
            f"Offset: 0x{off:08X} ({off}){val}"
        )

    def _update_title(self, dv: DataView) -> None:
        if dv is not self._data_book.current_view:
            return
        if dv.buffer:
            name = os.path.basename(dv.buffer.filename)
            changed = " [modified]" if dv.buffer.has_changed else ""
            self.set_title(f"{name}{changed} — Bless Hex Editor")
        else:
            self.set_title("Bless Hex Editor")

    def _load_prefs(self) -> None:
        prefs_dir = os.path.join(GLib.get_user_config_dir(), "bless")
        os.makedirs(prefs_dir, exist_ok=True)
        prefs_file = os.path.join(prefs_dir, "preferences.xml")
        p = Preferences.instance
        p.load(prefs_file)
        p.auto_save_path = prefs_file


# ---------------------------------------------------------------------------
# Application entry-point
# ---------------------------------------------------------------------------

class BlessApplication(Gtk.Application):

    def __init__(self) -> None:
        super().__init__(application_id="org.bless.hexeditor")
        self._window: MainWindow | None = None

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(self)
        self._window.present()

    def do_open(self, files, n_files, hint) -> None:
        paths = [f.get_path() for f in files]
        if self._window is None:
            self._window = MainWindow(self, files=paths)
        else:
            for p in paths:
                self._window._file_ops.open_file(p)
        self._window.present()


def main(args: list[str] | None = None) -> int:
    if args is None:
        args = sys.argv
    app = BlessApplication()
    return app.run(args)
