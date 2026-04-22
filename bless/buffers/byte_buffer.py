# bless/buffers/byte_buffer.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import os
import threading
import tempfile
from collections import deque
from typing import Callable, Optional

from .ibuffer import IBuffer
from .simple_buffer import SimpleBuffer
from .file_buffer import FileBuffer
from .segment import Segment
from .segment_collection import SegmentCollection
from .actions import (
    ByteBufferAction, AppendAction, InsertAction,
    DeleteAction, ReplaceAction, MultiAction,
)

# Progress callback type:  fn(value: float|str, action: str) -> bool
ProgressCallback = Callable[[object, str], bool]
ChangedHandler = Callable[["ByteBuffer"], None]

_auto_num = 1
_auto_num_lock = threading.Lock()


def _next_auto_num() -> int:
    global _auto_num
    with _auto_num_lock:
        n = _auto_num
        _auto_num += 1
    return n


class ByteBuffer:
    """
    A versatile, undo/redo capable byte buffer that can efficiently edit
    files of arbitrary size using a piece-table (SegmentCollection) design.

    All public mutating methods are thread-safe via an internal lock.
    """

    BLOCK_SIZE = 0xFFFF  # 64 KB

    def __init__(self) -> None:
        self._seg_col = SegmentCollection()
        self._file_buf: Optional[FileBuffer] = None
        self._size: int = 0

        self._undo_deque: deque[ByteBufferAction] = deque()
        self._redo_deque: deque[ByteBufferAction] = deque()
        self._save_checkpoint: Optional[ByteBufferAction] = None

        n = _next_auto_num()
        self._auto_filename: str = f"Untitled {n}"

        self._max_undo_actions: int = -1  # unlimited
        self._changed_beyond_undo: bool = False
        self._temp_dir: str = tempfile.gettempdir()

        # permissions
        self._read_allowed: bool = True
        self._modify_allowed: bool = True
        self._file_ops_allowed: bool = True
        self._emit_events: bool = True

        # action chaining
        self._chaining: bool = False
        self._chaining_first: bool = False
        self._multi_action: Optional[MultiAction] = None

        # async save
        self._save_finished = threading.Event()
        self._user_save_callback: Optional[Callable] = None
        self._use_glib_idle: bool = False

        # file-watcher (inotify via watchdog if available, else poll)
        self._watcher = None

        # RLock so that public methods can safely call each other
        self.lock = threading.RLock()

        # event subscriber lists
        self._changed_handlers: list[ChangedHandler] = []
        self._file_changed_handlers: list[ChangedHandler] = []
        self._permissions_changed_handlers: list[ChangedHandler] = []

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def connect_changed(self, handler: ChangedHandler) -> None:
        self._changed_handlers.append(handler)

    def connect_file_changed(self, handler: ChangedHandler) -> None:
        self._file_changed_handlers.append(handler)

    def connect_permissions_changed(self, handler: ChangedHandler) -> None:
        self._permissions_changed_handlers.append(handler)

    def _emit_changed(self) -> None:
        if self._emit_events:
            for h in list(self._changed_handlers):
                h(self)

    def _emit_file_changed(self) -> None:
        if self._emit_events:
            for h in list(self._file_changed_handlers):
                h(self)

    def _emit_permissions_changed(self) -> None:
        if self._emit_events:
            for h in list(self._permissions_changed_handlers):
                h(self)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filename: str) -> "ByteBuffer":
        bb = cls()
        bb._load_with_file(filename)
        # Undo the auto-number increment done by __init__
        global _auto_num
        with _auto_num_lock:
            _auto_num -= 1
        return bb

    def __init_with_name__(self, filename: str) -> None:
        """Post-init helper that sets a custom auto-name (no file loaded)."""
        self._auto_filename = filename
        global _auto_num
        with _auto_num_lock:
            _auto_num -= 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_with_file(self, filename: str) -> None:
        if self._file_buf is None:
            self._file_buf = FileBuffer(filename, 0xFFFF)
        else:
            self._file_buf.load(filename)
        seg = Segment(self._file_buf, 0, self._file_buf.size - 1)
        self._seg_col = SegmentCollection()
        self._seg_col.append(seg)
        self._size = self._file_buf.size
        self._setup_watcher()

    def _setup_watcher(self) -> None:
        self._teardown_watcher()
        if self._file_buf is None:
            return
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            directory = os.path.dirname(self._file_buf.filename)
            fname = os.path.basename(self._file_buf.filename)

            class _Handler(FileSystemEventHandler):
                def __init__(self, bb: ByteBuffer) -> None:
                    self._bb = bb

                def on_modified(self, event) -> None:
                    if not event.is_directory and os.path.basename(event.src_path) == fname:
                        self._bb._emit_file_changed()

            observer = Observer()
            observer.schedule(_Handler(self), directory, recursive=False)
            observer.start()
            self._watcher = observer
        except ImportError:
            pass  # watchdog not installed — file-change detection disabled

    def _teardown_watcher(self) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
                self._watcher.join()
            except Exception:
                pass
            self._watcher = None

    def _add_undo_action(self, action: ByteBufferAction) -> None:
        if self._max_undo_actions != -1:
            while len(self._undo_deque) >= self._max_undo_actions:
                self._undo_deque.pop()
                self._changed_beyond_undo = True
        self._undo_deque.appendleft(action)

    def _handle_chaining(self, action: ByteBufferAction) -> bool:
        if not self._chaining:
            return False
        if self._chaining_first:
            assert self._multi_action is not None
            self._add_undo_action(self._multi_action)
            self._chaining_first = False
        self._multi_action.add(action)
        return True

    # ------------------------------------------------------------------
    # Action chaining
    # ------------------------------------------------------------------

    def begin_action_chaining(self) -> None:
        self._chaining = True
        self._chaining_first = True
        self._multi_action = MultiAction()
        self._emit_events = False

    def end_action_chaining(self) -> None:
        self._chaining = False
        self._chaining_first = False
        self._emit_events = True
        self._emit_changed()

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def append(self, data: bytes, index: int, length: int) -> None:
        with self.lock:
            if not self._modify_allowed or not self.is_resizable:
                return
            aa = AppendAction(data, index, length, self)
            aa.do()
            if not self._handle_chaining(aa):
                self._add_undo_action(aa)
                self._redo_deque.clear()
            self._emit_changed()

    def insert(self, pos: int, data: bytes, index: int, length: int) -> None:
        with self.lock:
            if not self._modify_allowed or not self.is_resizable:
                return
            if pos == self._size:
                self.append(data, index, length)
                return
            ia = InsertAction(pos, data, index, length, self)
            ia.do()
            if not self._handle_chaining(ia):
                self._add_undo_action(ia)
                self._redo_deque.clear()
            self._emit_changed()

    def delete(self, pos1: int, pos2: int) -> None:
        with self.lock:
            if not self._modify_allowed or not self.is_resizable:
                return
            da = DeleteAction(pos1, pos2, self)
            da.do()
            if not self._handle_chaining(da):
                self._add_undo_action(da)
                self._redo_deque.clear()
            self._emit_changed()

    def replace(self, pos1: int, pos2: int, data: bytes,
                index: int = 0, length: int = -1) -> None:
        if length == -1:
            length = len(data)
        with self.lock:
            if not self._modify_allowed:
                return
            equal_length = (pos2 - pos1 + 1 == length)
            if not self.is_resizable and not equal_length:
                return
            ra = ReplaceAction(pos1, pos2, data, index, length, self)
            ra.do()
            if not self._handle_chaining(ra):
                self._add_undo_action(ra)
                self._redo_deque.clear()
            self._emit_changed()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def undo(self) -> None:
        with self.lock:
            if not self._modify_allowed:
                return
            if self._undo_deque:
                action = self._undo_deque.popleft()
                action.undo()
                self._redo_deque.appendleft(action)
                self._emit_changed()

    def redo(self) -> None:
        with self.lock:
            if not self._modify_allowed:
                return
            if self._redo_deque:
                action = self._redo_deque.popleft()
                action.do()
                self._add_undo_action(action)
                self._emit_changed()

    # ------------------------------------------------------------------
    # Byte access
    # ------------------------------------------------------------------

    def __getitem__(self, index: int) -> int:
        with self.lock:
            if not self._read_allowed:
                return 0
            seg, mapping, _ = self._seg_col.find_segment(index)
            if seg is None:
                raise IndexError(f"ByteBuffer[{index}]")
            return seg.buffer[seg.start + index - mapping]

    def range_to_bytes(self, start: int, end: int) -> Optional[bytes]:
        """Return [start, end] inclusive as a bytes object, or None if empty."""
        length = end - start + 1
        if length <= 0:
            return None
        result = bytearray(length)
        for i in range(length):
            result[i] = self[start + i]
        return bytes(result)

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def revert(self) -> None:
        with self.lock:
            if not self._modify_allowed:
                return
            if self._file_buf is None:
                return
            filename = self._file_buf.filename
            if not os.path.exists(filename):
                raise FileNotFoundError(filename)
            self._file_buf.close()
            self._undo_deque.clear()
            self._redo_deque.clear()
            self._load_with_file(filename)
            self._save_checkpoint = None
            self._changed_beyond_undo = False
            self._emit_changed()

    # ------------------------------------------------------------------
    # Async Save As
    # ------------------------------------------------------------------

    def begin_save_as(self, filename: str,
                      progress_cb: Optional[ProgressCallback] = None,
                      done_cb: Optional[Callable] = None) -> threading.Event:
        with self.lock:
            if not self._file_ops_allowed:
                return threading.Event()

            self._save_finished.clear()
            self._user_save_callback = done_cb
            self.modify_allowed = False
            self.file_ops_allowed = False
            self._emit_events = False
            if self._watcher:
                self._watcher.stop()

            def _thread():
                cancelled = False
                exc = None
                stage = "before_create"
                try:
                    stage = "before_create"
                    # check free space
                    dest_dir = os.path.dirname(filename) or "."
                    st = os.statvfs(dest_dir)
                    free = st.f_bavail * st.f_frsize
                    if free < self._size:
                        raise IOError(f"Not enough free space to save '{filename}'.")

                    # write to file
                    stage = "before_write"
                    with open(filename, "wb") as fp:
                        node = self._seg_col.list.first
                        while node is not None and not cancelled:
                            seg = node.data
                            length = seg.size
                            done = 0
                            buf = bytearray(self.BLOCK_SIZE)
                            while done < length and not cancelled:
                                chunk = min(self.BLOCK_SIZE, length - done)
                                seg.buffer.read(buf, 0, seg.start + done, chunk)
                                fp.write(buf[:chunk])
                                done += chunk
                                if progress_cb:
                                    cancelled = progress_cb(
                                        done / max(self._size, 1), "update"
                                    )
                            node = node.next
                except Exception as e:
                    exc = e

                with self.lock:
                    self.file_ops_allowed = True
                    if exc is None and not cancelled:
                        self._make_private_copy_of_undo_redo()
                        self._close_file_internal()
                        self._load_with_file(filename)
                        self._save_checkpoint = (
                            self._undo_deque[0] if self._undo_deque else None
                        )
                        self._changed_beyond_undo = False
                    elif stage == "before_create" and exc:
                        pass  # nothing was written
                    else:
                        # partial write — delete the partial output
                        try:
                            os.unlink(filename)
                        except OSError:
                            pass

                    self.read_allowed = True
                    self.modify_allowed = True
                    self._emit_events = True
                    if self._watcher:
                        self._watcher.start()

                    self._emit_permissions_changed()
                    self._emit_changed()

                    if self._user_save_callback:
                        self._user_save_callback()

                    self._save_finished.set()

            t = threading.Thread(target=_thread, daemon=True)
            t.start()
            return self._save_finished

    # ------------------------------------------------------------------
    # Async Save (same filename, in-place or via temp file)
    # ------------------------------------------------------------------

    def begin_save(self, progress_cb: Optional[ProgressCallback] = None,
                   done_cb: Optional[Callable] = None) -> threading.Event:
        if self._file_buf is None:
            return threading.Event()
        filename = self._file_buf.filename

        # If the size hasn't changed, save in-place (cheaper)
        if not self._file_buf.is_resizable or self._size == self._file_buf.size:
            return self._begin_save_in_place(progress_cb, done_cb)

        # Otherwise: write to a temp file, then move
        tmp_path = os.path.join(self._temp_dir, f".bless_tmp_{os.getpid()}")
        return self._begin_save_via_temp(filename, tmp_path, progress_cb, done_cb)

    def _begin_save_in_place(self, progress_cb, done_cb) -> threading.Event:
        """Save only the segments that have changed (those not backed by FileBuffer)."""
        with self.lock:
            self._save_finished.clear()
            self._user_save_callback = done_cb
            self.modify_allowed = False
            self.file_ops_allowed = False
            self._emit_events = False
            if self._watcher:
                self._watcher.stop()

            save_path = self._file_buf.filename
            seg_col_snapshot = self._seg_col  # keep reference before close

            def _thread():
                exc = None
                try:
                    self._make_private_copy_of_undo_redo()
                    self._close_file_internal()
                    with open(save_path, "r+b") as fp:
                        node = seg_col_snapshot.list.first
                        mapping = 0
                        buf = bytearray(self.BLOCK_SIZE)
                        while node is not None:
                            seg = node.data
                            if not isinstance(seg.buffer, FileBuffer):
                                fp.seek(mapping)
                                done = 0
                                while done < seg.size:
                                    chunk = min(self.BLOCK_SIZE, seg.size - done)
                                    seg.buffer.read(buf, 0, seg.start + done, chunk)
                                    fp.write(buf[:chunk])
                                    done += chunk
                            mapping += seg.size
                            node = node.next
                except Exception as e:
                    exc = e

                with self.lock:
                    if exc is None:
                        self._load_with_file(save_path)
                        self._save_checkpoint = (
                            self._undo_deque[0] if self._undo_deque else None
                        )
                        self._changed_beyond_undo = False

                    self.read_allowed = True
                    self.modify_allowed = True
                    self.file_ops_allowed = True
                    self._emit_events = True
                    if self._watcher:
                        self._watcher.start()

                    self._emit_permissions_changed()
                    self._emit_changed()

                    if self._user_save_callback:
                        self._user_save_callback()

                    self._save_finished.set()

            t = threading.Thread(target=_thread, daemon=True)
            t.start()
            return self._save_finished

    def _begin_save_via_temp(self, save_path, tmp_path, progress_cb, done_cb):
        """Write to a temp file, delete original, move temp into place."""
        event = self.begin_save_as(tmp_path, progress_cb, None)

        def _after_save_as():
            with self.lock:
                if os.path.exists(save_path):
                    os.unlink(save_path)
                os.rename(tmp_path, save_path)
                # reload from final location
                self._load_with_file(save_path)
                self._save_checkpoint = (
                    self._undo_deque[0] if self._undo_deque else None
                )
                self._changed_beyond_undo = False
                self._emit_changed()
                if done_cb:
                    done_cb()
                self._save_finished.set()

        self._user_save_callback = _after_save_as
        return self._save_finished

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close_file(self) -> None:
        with self.lock:
            if self._file_buf is not None and self._file_ops_allowed:
                self._close_file_internal()
                self.read_allowed = False

    def _close_file_internal(self) -> None:
        if self._file_buf is not None:
            self._file_buf.close()
        self._teardown_watcher()
        self._seg_col = None

    # ------------------------------------------------------------------
    # Make private copies of undo/redo (for safe saving)
    # ------------------------------------------------------------------

    def _make_private_copy_of_undo_redo(self) -> None:
        from ..tools.preferences import Preferences
        keep = Preferences.instance().get("Undo.KeepAfterSave", "Always")

        if keep == "Never":
            self._undo_deque.clear()
            self._redo_deque.clear()
            return

        for action in list(self._undo_deque) + list(self._redo_deque):
            action.make_private_copy()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return self._size

    @property
    def filename(self) -> str:
        if self._file_buf is not None:
            return self._file_buf.filename
        return self._auto_filename

    @property
    def has_file(self) -> bool:
        return self._file_buf is not None

    @property
    def has_changed(self) -> bool:
        if self._undo_deque:
            return self._changed_beyond_undo or (
                self._save_checkpoint is not self._undo_deque[0]
            )
        return self._changed_beyond_undo or self._save_checkpoint is not None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_deque)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_deque)

    @property
    def is_resizable(self) -> bool:
        return self._file_buf.is_resizable if self._file_buf else True

    @property
    def read_allowed(self) -> bool:
        return self._read_allowed

    @read_allowed.setter
    def read_allowed(self, value: bool) -> None:
        self._read_allowed = value
        self._emit_permissions_changed()

    @property
    def modify_allowed(self) -> bool:
        return self._modify_allowed

    @modify_allowed.setter
    def modify_allowed(self, value: bool) -> None:
        self._modify_allowed = value
        self._emit_permissions_changed()

    @property
    def file_ops_allowed(self) -> bool:
        return self._file_ops_allowed

    @file_ops_allowed.setter
    def file_ops_allowed(self, value: bool) -> None:
        self._file_ops_allowed = value
        self._emit_permissions_changed()

    @property
    def max_undo_actions(self) -> int:
        return self._max_undo_actions

    @max_undo_actions.setter
    def max_undo_actions(self, value: int) -> None:
        self._max_undo_actions = value
        if value != -1:
            while len(self._undo_deque) > value:
                self._undo_deque.pop()
                self._changed_beyond_undo = True

    @property
    def temp_dir(self) -> str:
        return self._temp_dir

    @temp_dir.setter
    def temp_dir(self, value: str) -> None:
        self._temp_dir = value if value else tempfile.gettempdir()
