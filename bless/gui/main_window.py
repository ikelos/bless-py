# bless/gui/main_window.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from ..buffers.byte_buffer import ByteBuffer
from ..tools.preferences import Preferences
from .data_book import DataBook
from .data_view import DataView
from .plugins.file_operations import FileOperations


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
        self._initial_files = list(files) if files else []
        self._statusbar_radix: int = 16
        # These are set in _build_menu_bar; declared here for type checkers
        self._mi_undo: Gtk.MenuItem
        self._mi_redo: Gtk.MenuItem
        self._mi_save: Gtk.MenuItem
        self._mi_saveas: Gtk.MenuItem
        self._mi_revert: Gtk.MenuItem
        self._mi_close: Gtk.MenuItem
        # Toolbar buttons that mirror menu sensitivity
        self._tb_save: Gtk.ToolButton
        self._tb_undo: Gtk.ToolButton
        self._tb_redo: Gtk.ToolButton
        self._tb_find: Gtk.ToggleToolButton
        self._tb_findreplace: Gtk.ToggleToolButton

        self._build_ui()
        self._wire_events()
        self._load_prefs()
        self._update_menu_sensitivity(None)

        self.show_all()

        # Defer file-open until after GTK has realized all child widgets
        GLib.idle_add(self._open_initial_files)

    def _open_initial_files(self) -> bool:
        """Idle callback: open files after all widgets have been realized."""
        if self._initial_files:
            for f in self._initial_files:
                self._file_ops.open_file(f)
        else:
            self._file_ops.new_file()
        return False  # don't repeat

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
        # Enable button events so clicking cycles the display radix
        self._statusbar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self._statusbar.connect("button-press-event",
                                lambda *_: self._cycle_statusbar_radix())

        # Keyboard accelerators
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def _accel(key, mods, fn):
            accel.connect(Gdk.keyval_from_name(key), mods,
                          Gtk.AccelFlags.VISIBLE, lambda *_: fn())

        ctrl       = Gdk.ModifierType.CONTROL_MASK
        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK

        _accel("z", ctrl,       lambda: self._current_dv_call("undo"))
        _accel("z", ctrl_shift, lambda: self._current_dv_call("redo"))
        _accel("a", ctrl,       self._select_all)
        _accel("r", ctrl_shift, self._show_select_range)

        # File shortcuts
        _accel("n", ctrl,       lambda: self._file_ops.new_file())
        _accel("o", ctrl,       lambda: self._file_ops.open_file())
        _accel("s", ctrl,       lambda: self._file_ops.save_file())
        _accel("s", ctrl_shift, lambda: self._file_ops.save_file_as())

    def _build_menu_bar(self) -> Gtk.MenuBar:
        mb = Gtk.MenuBar()

        def _item(label: str, cb) -> Gtk.MenuItem:
            it = Gtk.MenuItem.new_with_mnemonic(label)
            it.connect("activate", cb)
            return it

        # --- File ---
        file_menu = Gtk.Menu()
        file_menu.append(_item("_New              Ctrl+N",  lambda *_: self._file_ops.new_file()))
        file_menu.append(_item("_Open…            Ctrl+O",  lambda *_: self._file_ops.open_file()))
        self._mi_save   = _item("_Save             Ctrl+S",  lambda *_: self._file_ops.save_file())
        self._mi_saveas = _item("Save _As…  Shift+Ctrl+S",  lambda *_: self._file_ops.save_file_as())
        self._mi_revert = _item("_Revert",                  lambda *_: self._file_ops.revert_file())
        self._mi_close  = _item("_Close",                   lambda *_: self._file_ops.close_file())
        for it in (self._mi_save, self._mi_saveas, self._mi_revert):
            file_menu.append(it)
        file_menu.append(Gtk.SeparatorMenuItem())
        file_menu.append(self._mi_close)
        file_menu.append(_item("_Quit", lambda *_: self.get_application().quit()))
        fi = Gtk.MenuItem.new_with_mnemonic("_File")
        fi.set_submenu(file_menu)
        mb.append(fi)

        # --- Edit ---
        edit_menu = Gtk.Menu()
        self._mi_undo = _item("_Undo         Ctrl+Z",       lambda *_: self._current_dv_call("undo"))
        self._mi_redo = _item("_Redo  Shift+Ctrl+Z",        lambda *_: self._current_dv_call("redo"))
        edit_menu.append(self._mi_undo)
        edit_menu.append(self._mi_redo)
        edit_menu.append(Gtk.SeparatorMenuItem())
        for label, cb in (
            ("Cu_t",                        lambda *_: self._current_dv_call("cut")),
            ("_Copy",                       lambda *_: self._current_dv_call("copy")),
            ("_Paste",                      lambda *_: self._current_dv_call("paste")),
            ("_Delete",                     lambda *_: self._current_dv_call("delete")),
        ):
            edit_menu.append(_item(label, cb))
        edit_menu.append(Gtk.SeparatorMenuItem())
        edit_menu.append(_item("Select _All         Ctrl+A",  lambda *_: self._select_all()))
        edit_menu.append(_item("Select _Range  Shift+Ctrl+R", lambda *_: self._show_select_range()))
        ei = Gtk.MenuItem.new_with_mnemonic("_Edit")
        ei.set_submenu(edit_menu)
        mb.append(ei)

        # --- Search ---
        search_menu = Gtk.Menu()
        search_menu.append(_item("_Find…            Ctrl+F",   lambda *_: self._show_find()))
        search_menu.append(_item("Find & _Replace…  Ctrl+H",   lambda *_: self._show_find_replace()))
        search_menu.append(Gtk.SeparatorMenuItem())
        search_menu.append(_item("_Go to Offset…    Ctrl+G",   lambda *_: self._show_goto()))
        si = Gtk.MenuItem.new_with_mnemonic("_Search")
        si.set_submenu(search_menu)
        mb.append(si)

        # --- Help ---
        help_menu = Gtk.Menu()
        help_menu.append(_item("_About", lambda *_: self._show_about()))
        hi = Gtk.MenuItem.new_with_mnemonic("_Help")
        hi.set_submenu(help_menu)
        mb.append(hi)

        return mb

    def _update_menu_sensitivity(self, dv: DataView | None) -> None:
        """Enable/disable menu items based on current buffer state."""
        has_buf     = dv is not None and dv.buffer is not None
        has_file    = has_buf and dv.buffer.has_file
        has_changed = has_buf and dv.buffer.has_changed
        can_undo    = has_buf and dv.buffer.can_undo
        can_redo    = has_buf and dv.buffer.can_redo

        self._mi_undo.set_sensitive(can_undo)
        self._mi_redo.set_sensitive(can_redo)
        self._mi_save.set_sensitive(has_changed)
        self._mi_saveas.set_sensitive(has_buf)
        self._mi_revert.set_sensitive(has_file and has_changed)
        self._mi_close.set_sensitive(has_buf)

        # Mirror sensitivity on toolbar buttons
        self._tb_save.set_sensitive(has_changed)
        self._tb_undo.set_sensitive(can_undo)
        self._tb_redo.set_sensitive(can_redo)

    def _build_toolbar(self) -> Gtk.Toolbar:
        tb = Gtk.Toolbar()
        tb.set_style(Gtk.ToolbarStyle.ICONS)

        def _btn(icon: str, tip: str, cb) -> Gtk.ToolButton:
            b = Gtk.ToolButton.new(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR), tip)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            return b

        def _toggle(icon: str, tip: str, cb) -> Gtk.ToggleToolButton:
            b = Gtk.ToggleToolButton.new()
            b.set_icon_widget(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR))
            b.set_tooltip_text(tip)
            b.connect("toggled", cb)
            return b

        self._tb_new    = _btn("document-new",  "New (Ctrl+N)", lambda *_: self._file_ops.new_file())
        self._tb_open   = _btn("document-open", "Open (Ctrl+O)", lambda *_: self._file_ops.open_file())
        self._tb_save   = _btn("document-save", "Save (Ctrl+S)", lambda *_: self._file_ops.save_file())

        self._tb_cut    = _btn("edit-cut",   "Cut",   lambda *_: self._current_dv_call("cut"))
        self._tb_copy   = _btn("edit-copy",  "Copy",  lambda *_: self._current_dv_call("copy"))
        self._tb_paste  = _btn("edit-paste", "Paste", lambda *_: self._current_dv_call("paste"))

        self._tb_undo   = _btn("edit-undo",  "Undo (Ctrl+Z)",       lambda *_: self._current_dv_call("undo"))
        self._tb_redo   = _btn("edit-redo",  "Redo (Shift+Ctrl+Z)", lambda *_: self._current_dv_call("redo"))

        self._tb_find = _toggle("edit-find", "Find (Ctrl+F)",
                                lambda b: self._on_find_toggle(b))
        self._tb_findreplace = _toggle("edit-find-replace", "Find & Replace (Ctrl+H)",
                                       lambda b: self._on_findreplace_toggle(b))

        for item in (
            self._tb_new, self._tb_open, self._tb_save,
            Gtk.SeparatorToolItem(),
            self._tb_cut, self._tb_copy, self._tb_paste,
            Gtk.SeparatorToolItem(),
            self._tb_undo, self._tb_redo,
            Gtk.SeparatorToolItem(),
            self._tb_find, self._tb_findreplace,
        ):
            tb.insert(item, -1)

        return tb

    def _on_find_toggle(self, btn: Gtk.ToggleToolButton) -> None:
        dv = self._data_book.current_view
        if not dv:
            return
        if btn.get_active():
            # Deactivate find-replace toggle
            self._tb_findreplace.handler_block_by_func(self._on_findreplace_toggle)
            self._tb_findreplace.set_active(False)
            self._tb_findreplace.handler_unblock_by_func(self._on_findreplace_toggle)
            dv.display.show_find()
        else:
            dv.display.find_bar.hide()

    def _on_findreplace_toggle(self, btn: Gtk.ToggleToolButton) -> None:
        dv = self._data_book.current_view
        if not dv:
            return
        if btn.get_active():
            self._tb_find.handler_block_by_func(self._on_find_toggle)
            self._tb_find.set_active(False)
            self._tb_find.handler_unblock_by_func(self._on_find_toggle)
            dv.display.show_find_replace()
        else:
            dv.display.find_replace_bar.hide()

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

    def _show_select_range(self) -> None:
        dv = self._data_book.current_view
        if dv:
            dv.display.show_select_range()

    def _show_find(self) -> None:
        dv = self._data_book.current_view
        if dv:
            dv.display.show_find()

    def _show_find_replace(self) -> None:
        dv = self._data_book.current_view
        if dv:
            dv.display.show_find_replace()

    def _show_goto(self) -> None:
        dv = self._data_book.current_view
        if dv:
            dv.display.show_goto()

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
        return any(not self._file_ops.close_file(dv) for dv in views)

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
        dv.connect_selection_changed(lambda d: self._update_statusbar(d))
        dv.connect_overwrite_changed(lambda d: self._update_statusbar(d))
        # Update menu sensitivity whenever buffer state changes
        dv.connect_buffer_changed(lambda d: self._update_menu_sensitivity(d))
        dv.connect_cursor_changed(lambda d: self._update_menu_sensitivity(d))
        # Sync toolbar toggle buttons with bar visibility
        dv.display.find_bar.connect(
            "show", lambda *_: self._sync_find_toggles(True, False))
        dv.display.find_bar.connect(
            "hide", lambda *_: self._sync_find_toggles(False, None))
        dv.display.find_replace_bar.connect(
            "show", lambda *_: self._sync_find_toggles(False, True))
        dv.display.find_replace_bar.connect(
            "hide", lambda *_: self._sync_find_toggles(None, False))

    def _sync_find_toggles(self, find: bool | None, replace: bool | None) -> None:
        """Sync toolbar toggle state without triggering the toggled signal."""
        if find is not None:
            self._tb_find.handler_block_by_func(self._on_find_toggle)
            self._tb_find.set_active(find)
            self._tb_find.handler_unblock_by_func(self._on_find_toggle)
        if replace is not None:
            self._tb_findreplace.handler_block_by_func(self._on_findreplace_toggle)
            self._tb_findreplace.set_active(replace)
            self._tb_findreplace.handler_unblock_by_func(self._on_findreplace_toggle)

    def _on_switch_page(self, nb, widget, n) -> None:
        dv = self._data_book.current_view
        if dv:
            self._update_title(dv)
            self._update_statusbar(dv)
            self._update_menu_sensitivity(dv)
        else:
            self._update_menu_sensitivity(None)

    def _on_dv_buffer_changed(self, dv: DataView) -> None:
        self._update_title(dv)
        self._update_statusbar(dv)

    def _on_dv_cursor_changed(self, dv: DataView) -> None:
        if dv is not self._data_book.current_view:
            return
        self._update_statusbar(dv)

    def _cycle_statusbar_radix(self) -> None:
        radices = [16, 10, 8]
        self._statusbar_radix = radices[
            (radices.index(self._statusbar_radix) + 1) % len(radices)
        ]
        dv = self._data_book.current_view
        if dv:
            self._update_statusbar(dv)

    def _fmt(self, n: int, radix: int) -> str:
        if radix == 16:
            return f"0x{n:x}"
        if radix == 8:
            return f"0{n:o}" if n else "0"
        return str(n)

    def _update_statusbar(self, dv: DataView) -> None:
        if dv is not self._data_book.current_view:
            return
        self._statusbar.pop(self._ctx)
        if dv.buffer is None:
            self._statusbar.push(self._ctx, "")
            return
        r    = self._statusbar_radix
        off  = dv.cursor_offset
        size = dv.buffer.size
        sel  = dv.selection
        mode = "OVR" if dv.overwrite else "INS"

        sel_str = "Selection: None"
        if not sel.is_empty() and sel.start >= 0 and sel.end >= sel.start:
            n    = sel.end - sel.start + 1
            unit = "byte" if n == 1 else "bytes"
            sel_str = (
                f"Selection: {self._fmt(sel.start, r)}"
                f" to {self._fmt(sel.end, r)}"
                f" ({self._fmt(n, r)} {unit})"
            )

        self._statusbar.push(
            self._ctx,
            f"Offset: {self._fmt(off, r)} / {self._fmt(max(0, size-1), r)}"
            f"  |  Size: {self._fmt(size, r)}"
            f"  |  {sel_str}  |  {mode}"
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
        p = Preferences.instance()
        p.load(prefs_file)
        p.auto_save_path = prefs_file


# ---------------------------------------------------------------------------
# Application entry-point
# ---------------------------------------------------------------------------

class BlessApplication(Gtk.Application):

    def __init__(self) -> None:
        super().__init__(application_id="org.bless.hexeditor",
                         flags=Gio.ApplicationFlags.HANDLES_OPEN)
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
    import argparse

    from ..logger import setup as _log_setup

    if args is None:
        args = sys.argv

    parser = argparse.ArgumentParser(
        prog="bless",
        description="Bless Hex Editor",
        add_help=False,   # let GApplication handle --help
    )
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose diagnostic logging to stderr")
    known, remaining = parser.parse_known_args(args[1:])
    _log_setup(verbose=known.debug)

    app = BlessApplication()
    return app.run([args[0]] + remaining)
