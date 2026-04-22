# bless/tools/find.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from __future__ import annotations

import threading
from typing import Optional, Callable

from ..util.range import Range
from ..buffers.byte_buffer import ByteBuffer

ProgressCallback = Callable[[object, str], bool]


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------

class IFindStrategy:
    @property
    def pattern(self) -> bytes: ...
    @pattern.setter
    def pattern(self, v: bytes) -> None: ...

    @property
    def buffer(self) -> Optional[ByteBuffer]: ...
    @buffer.setter
    def buffer(self, v: ByteBuffer) -> None: ...

    @property
    def position(self) -> int: ...
    @position.setter
    def position(self, v: int) -> None: ...

    @property
    def cancelled(self) -> bool: ...
    @cancelled.setter
    def cancelled(self, v: bool) -> None: ...

    def find_next(self, limit: int = -1) -> Optional[Range]: ...
    def find_previous(self, limit: int = 0) -> Optional[Range]: ...


# ---------------------------------------------------------------------------
# Boyer-Moore (bad-character only) strategy
# ---------------------------------------------------------------------------

class BMFindStrategy(IFindStrategy):
    """
    Boyer-Moore search using only the bad-character skip table.
    Searches forward and backward through a ByteBuffer.
    """

    def __init__(self) -> None:
        self._pattern = b""
        self._buffer: Optional[ByteBuffer] = None
        self._pos: int = 0
        self._cancelled: bool = False
        self._skip: list[int] = [0] * 256
        self._skip_rev: list[int] = [0] * 256

    def _update_skip_tables(self) -> None:
        plen = len(self._pattern)
        self._skip = [plen] * 256
        self._skip_rev = [plen] * 256
        for i, b in enumerate(self._pattern):
            self._skip[b] = plen - i - 1
        for i in range(plen - 1, -1, -1):
            self._skip_rev[self._pattern[i]] = i

    @property
    def pattern(self) -> bytes:
        return self._pattern

    @pattern.setter
    def pattern(self, v: bytes) -> None:
        self._pattern = bytes(v)
        self._update_skip_tables()

    @property
    def buffer(self) -> Optional[ByteBuffer]:
        return self._buffer

    @buffer.setter
    def buffer(self, v: ByteBuffer) -> None:
        self._buffer = v
        self._pos = 0

    @property
    def position(self) -> int:
        return self._pos

    @position.setter
    def position(self, v: int) -> None:
        self._pos = v

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @cancelled.setter
    def cancelled(self, v: bool) -> None:
        self._cancelled = v

    # ---- forward search ----

    def _find_next_single(self, limit: int) -> Optional[Range]:
        b = self._pattern[0]
        buf = self._buffer
        while self._pos < limit and buf[self._pos] != b and not self._cancelled:
            self._pos += 1
        if self._pos >= limit or self._cancelled:
            return None
        r = Range(self._pos, self._pos)
        self._pos += 1
        return r

    def find_next(self, limit: int = -1) -> Optional[Range]:
        buf = self._buffer
        plen = len(self._pattern)
        buf_len = buf.size
        if limit < 0:
            limit = buf_len - 1
        limit = min(limit + 1, buf_len)
        if plen == 0:
            return None
        if plen == 1:
            return self._find_next_single(limit)

        skip = self._skip
        pos = self._pos

        while pos <= limit - plen and not self._cancelled:
            i = plen - 1
            while i >= 0:
                cur = buf[pos + i]
                if cur != self._pattern[i]:
                    break
                i -= 1
            if i < 0:
                r = Range(pos, pos + plen - 1)
                self._pos = pos + 1
                return r
            t = skip[cur]
            if plen - i > t:
                pos += plen - i
            else:
                pos += t - plen + 1 + i

        self._pos = pos
        return None

    # ---- backward search ----

    def _find_previous_single(self, limit: int) -> Optional[Range]:
        b = self._pattern[0]
        buf = self._buffer
        self._pos -= 1
        while self._pos >= limit and buf[self._pos] != b and not self._cancelled:
            self._pos -= 1
        if self._pos < 0 or self._cancelled:
            self._pos = max(self._pos, 0)
            return None
        return Range(self._pos, self._pos)

    def find_previous(self, limit: int = 0) -> Optional[Range]:
        buf = self._buffer
        plen = len(self._pattern)
        if limit < 0:
            limit = 0
        if plen == 0:
            return None
        if plen == 1:
            return self._find_previous_single(limit)

        skip_rev = self._skip_rev
        self._pos -= 1
        pos = self._pos

        while pos >= limit + plen - 1 and not self._cancelled:
            i = 0
            while i < plen:
                cur = buf[pos - plen + 1 + i]
                if cur != self._pattern[i]:
                    break
                i += 1
            if i >= plen:
                self._pos = pos
                return Range(pos - plen + 1, pos)
            t = skip_rev[cur]
            if i > t:
                pos -= 1
            else:
                pos -= t - i

        self._pos = max(pos, 0)
        return None


# ---------------------------------------------------------------------------
# Simple (brute-force) strategy
# ---------------------------------------------------------------------------

class SimpleFindStrategy(IFindStrategy):

    def __init__(self) -> None:
        self._pattern = b""
        self._buffer: Optional[ByteBuffer] = None
        self._pos: int = 0
        self._cancelled: bool = False

    @property
    def pattern(self) -> bytes:
        return self._pattern

    @pattern.setter
    def pattern(self, v: bytes) -> None:
        self._pattern = bytes(v)

    @property
    def buffer(self) -> Optional[ByteBuffer]:
        return self._buffer

    @buffer.setter
    def buffer(self, v: ByteBuffer) -> None:
        self._buffer = v
        self._pos = 0

    @property
    def position(self) -> int:
        return self._pos

    @position.setter
    def position(self, v: int) -> None:
        self._pos = v

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @cancelled.setter
    def cancelled(self, v: bool) -> None:
        self._cancelled = v

    def find_next(self, limit: int = -1) -> Optional[Range]:
        buf = self._buffer
        buf_len = buf.size
        plen = len(self._pattern)
        if limit < 0 or limit > buf_len:
            limit = buf_len
        pos = self._pos
        i = 0
        while pos < limit and i < plen:
            if buf[pos] == self._pattern[i]:
                i += 1
            else:
                if i > 0:
                    pos = pos - i + 1
                i = 0
            pos += 1
        self._pos = pos
        if i == plen and plen > 0:
            return Range(pos - plen, pos - 1)
        return None

    def find_previous(self, limit: int = 0) -> Optional[Range]:
        buf = self._buffer
        plen = len(self._pattern)
        if limit < 0:
            limit = 0
        pos = self._pos - 1
        i = plen - 1
        while pos >= limit and i >= 0:
            if buf[pos] == self._pattern[i]:
                i -= 1
            else:
                if i < plen - 1:
                    pos = pos + (plen - 1 - i) - 1
                i = plen - 1
            pos -= 1
        self._pos = pos
        if i == -1 and plen > 0:
            return Range(pos + 1, pos + plen)
        return None


# ---------------------------------------------------------------------------
# Async find operation
# ---------------------------------------------------------------------------

class FindOperation:
    """
    Run a find-next or find-previous in a background thread.
    Call ``start()`` and then ``wait()`` or register ``on_done``.
    """

    def __init__(self, strategy: IFindStrategy,
                 forward: bool = True,
                 progress_cb: Optional[ProgressCallback] = None,
                 done_cb: Optional[Callable] = None) -> None:
        self._strategy = strategy
        self._forward = forward
        self._progress_cb = progress_cb
        self._done_cb = done_cb
        self.match: Optional[Range] = None
        self._finished = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # We do NOT lock the buffer here: find is read-only and must not
        # block the GTK thread from rendering while the search runs.

    def start(self) -> None:
        self._strategy.cancelled = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._strategy.cancelled = True

    def wait(self, timeout: float = None) -> bool:
        return self._finished.wait(timeout)

    def _run(self) -> None:
        try:
            if self._forward:
                self.match = self._strategy.find_next()
            else:
                self.match = self._strategy.find_previous()
        finally:
            if self._done_cb:
                self._done_cb(self)
            self._finished.set()
