# bless/tools/preferences.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections.abc import Callable

PreferencesChangedHandler = Callable[["Preferences"], None]


class Preferences:
    """
    Singleton application preferences stored as a flat key→value dict
    with optional XML auto-save and a pub/sub change-notification system.
    """

    _instance: Preferences | None = None
    _default: Preferences | None = None
    _proxy: PreferencesProxy | None = None

    @classmethod
    def instance(cls) -> Preferences:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def default(cls) -> Preferences:
        if cls._default is None:
            cls._default = cls()
        return cls._default

    @classmethod
    def proxy(cls) -> PreferencesProxy:
        if cls._proxy is None:
            cls._proxy = PreferencesProxy(cls.instance())
        return cls._proxy

    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._prefs: dict[str, str] = {}
        self._auto_save_path: str | None = None
        self._notify = True

    def get(self, key: str, default: str = "") -> str:
        return self._prefs.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._prefs[key] = value
        try:
            if self._auto_save_path:
                self.save(self._auto_save_path)
        except Exception:
            pass
        if self._notify:
            Preferences.proxy().change(key, value, "__Preferences__")

    def set_without_notify(self, key: str, value: str) -> None:
        self._notify = False
        self.set(key, value)
        self._notify = True

    def __getitem__(self, key: str) -> str:
        return self._prefs.get(key, "")

    def __setitem__(self, key: str, value: str) -> None:
        self.set(key, value)

    def __iter__(self):
        return iter(self._prefs.items())

    @property
    def auto_save_path(self) -> str | None:
        return self._auto_save_path

    @auto_save_path.setter
    def auto_save_path(self, path: str) -> None:
        self._auto_save_path = path

    def save(self, path: str) -> None:
        root = ET.Element("preferences")
        for k, v in self._prefs.items():
            pref = ET.SubElement(root, "pref", name=k)
            pref.text = v
        tree = ET.ElementTree(root)
        ET.indent(tree, space="\t")
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        tree = ET.parse(path)
        for pref in tree.findall("pref"):
            name = pref.get("name")
            if name is not None:
                self._prefs[name] = pref.text or ""

    def load_from(self, other: Preferences) -> None:
        for k, v in other:
            self._prefs[k] = v

    def display(self) -> None:
        for k, v in self._prefs.items():
            print(f"[{k}]: {v}")


class PreferencesProxy:
    """
    Mediates change notifications between Preferences and subscribers.
    Subscribers register interest in a specific key; when that key changes
    they receive the whole Preferences object.
    """

    def __init__(self, prefs: Preferences) -> None:
        self._prefs = prefs
        self._subscribers: dict[str, dict[str, PreferencesChangedHandler]] = {}
        self._enabled = True

    @property
    def enable(self) -> bool:
        return self._enabled

    @enable.setter
    def enable(self, value: bool) -> None:
        self._enabled = value

    def subscribe(self, key: str, sub_id: str, handler: PreferencesChangedHandler) -> None:
        self._subscribers.setdefault(key, {})[sub_id] = handler

    def unsubscribe(self, key: str, sub_id: str) -> None:
        self._subscribers.get(key, {}).pop(sub_id, None)

    def change(self, key: str, value: str, source_id: str) -> None:
        if not self._enabled:
            return
        for sub_id, handler in list(self._subscribers.get(key, {}).items()):
            if sub_id != source_id:
                handler(self._prefs)
