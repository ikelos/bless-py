# bless/gui/data_book.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .data_view import DataView

DataViewHandler = Callable[["DataView"], None]


class DataBook(Gtk.Notebook):
    """
    A Gtk.Notebook containing one DataView per tab.
    Emits Python callbacks for page-added / removed / switched.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_scrollable(True)
        self.set_show_border(True)

        self._views: list[DataView] = []

        self._page_added_handlers:   list[DataViewHandler] = []
        self._page_removed_handlers: list[Callable] = []
        self._switch_handlers:       list[Callable] = []

        self.connect("switch-page", self._on_switch_page)

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def connect_page_added(self, h: DataViewHandler) -> None:
        self._page_added_handlers.append(h)

    def connect_page_removed(self, h: Callable) -> None:
        self._page_removed_handlers.append(h)

    def connect_switch_page(self, h: Callable) -> None:
        self._switch_handlers.append(h)

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    def add_page(self, title: str = "Untitled") -> DataView:
        dv = DataView()
        dv.connect_buffer_changed(self._on_buffer_changed)
        dv.connect_notification_changed(self._on_notification_changed)

        label = Gtk.Label(label=title)
        label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        label_box.pack_start(label, True, True, 0)

        close_btn = Gtk.Button()
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        img = Gtk.Image.new_from_icon_name("window-close-symbolic",
                                           Gtk.IconSize.MENU)
        close_btn.add(img)
        close_btn.connect("clicked", lambda b: self.close_page(dv))
        label_box.pack_start(close_btn, False, False, 0)
        label_box.show_all()

        self.append_page(dv.display, label_box)
        self.set_tab_reorderable(dv.display, True)
        self._views.append(dv)
        dv.display.show_all()

        self.set_current_page(self.page_num(dv.display))

        for h in self._page_added_handlers:
            h(dv)

        return dv

    def close_page(self, dv: DataView) -> None:
        idx = self._views.index(dv) if dv in self._views else -1
        if idx < 0:
            return
        self.remove_page(self.page_num(dv.display))
        self._views.remove(dv)
        dv.cleanup()
        for h in self._page_removed_handlers:
            h(dv)

    @property
    def current_view(self) -> DataView | None:
        n = self.get_current_page()
        if n < 0 or n >= len(self._views):
            return None
        # Match by widget position
        widget = self.get_nth_page(n)
        for dv in self._views:
            if dv.display is widget:
                return dv
        return None

    @property
    def views(self) -> list[DataView]:
        return list(self._views)

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_buffer_changed(self, dv: DataView) -> None:
        idx = self.page_num(dv.display)
        if idx < 0:
            return
        if dv.buffer:
            title = os.path.basename(dv.buffer.filename)
            if dv.buffer.has_changed:
                title = "* " + title
        else:
            title = "Untitled"
        tab_label = self.get_tab_label(dv.display)
        if tab_label and isinstance(tab_label, Gtk.Box):
            for child in tab_label.get_children():
                if isinstance(child, Gtk.Label):
                    child.set_text(title)
                    break

    def _on_notification_changed(self, dv: DataView) -> None:
        idx = self.page_num(dv.display)
        if idx < 0:
            return
        tab_label = self.get_tab_label(dv.display)
        if tab_label and isinstance(tab_label, Gtk.Box):
            for child in tab_label.get_children():
                if isinstance(child, Gtk.Label):
                    markup = (f'<span foreground="red">'
                              f'{child.get_text()}</span>'
                              if dv.notification else child.get_text())
                    child.set_markup(markup)
                    break

    def _on_switch_page(self, notebook, page_widget, page_num) -> None:
        for h in self._switch_handlers:
            h(notebook, page_widget, page_num)
