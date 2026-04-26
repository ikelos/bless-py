# bless/gui/session.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later
"""Session persistence using GLib.KeyFile (XDG data directory).

Open file paths are recorded in::

    $XDG_DATA_HOME/bless/session.ini   (typically ~/.local/share/bless/)

using GNOME's standard GLib.KeyFile format.
"""

from __future__ import annotations

import os

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

_GROUP = "Session"
_KEY_FILES = "open_files"


def _session_path() -> str:
    data_dir = os.path.join(GLib.get_user_data_dir(), "bless")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "session.ini")


def load_session() -> list[str]:
    """Return absolute paths of files open in the previous session.

    Non-existent paths are silently dropped.
    """
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(_session_path(), GLib.KeyFileFlags.NONE)
        candidates = kf.get_string_list(_GROUP, _KEY_FILES)
    except GLib.Error:
        return []
    return [f for f in candidates if f and os.path.isfile(f)]


def save_session(files: list[str]) -> None:
    """Persist *files* as the list of currently open paths.

    Empty / falsy entries are ignored.  Errors are silently swallowed so
    a write failure never crashes the editor.
    """
    kf = GLib.KeyFile()
    kf.set_string_list(_GROUP, _KEY_FILES, [f for f in files if f])
    try:
        kf.save_to_file(_session_path())
    except GLib.Error:
        pass
