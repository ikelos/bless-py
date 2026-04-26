# bless/buffers/file_buffer.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

import os
import stat

from .ibuffer import IBuffer

# ioctl for block device size on Linux
try:
    import fcntl
    import struct

    BLKGETSIZE64 = 0x80081272
    _HAS_BLKGETSIZE64 = True
except ImportError:
    _HAS_BLKGETSIZE64 = False


class FileBuffer(IBuffer):
    """
    A buffer that provides a sliding-window view into a file (or block device).
    The window is re-centred around requested offsets so that sequential reads
    remain fast without loading the whole file into memory.
    """

    DEFAULT_WINDOW = 65536  # 64 KB

    def __init__(self, filename: str, window_size: int = DEFAULT_WINDOW) -> None:
        self._window = bytearray(window_size)
        self._win_offset = 0
        self._win_occupied = 0
        self._file_length = 0
        self._is_resizable = False
        self._fp = None
        self._filename = None
        self.load(filename)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _in_window(self, pos: int) -> bool:
        return self._win_offset <= pos < self._win_offset + self._win_occupied

    def _refill_window(self, pos: int) -> None:
        win_start = max(0, pos - len(self._window) // 2)
        self._fp.seek(win_start)
        data = self._fp.read(len(self._window))
        n = len(data)
        self._window[:n] = data
        self._win_offset = win_start
        self._win_occupied = n

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, filename: str) -> None:
        if self._fp is not None:
            self._fp.close()

        st = os.stat(filename)
        mode = st.st_mode

        if stat.S_ISREG(mode):
            self._file_length = st.st_size
            self._is_resizable = True
        elif stat.S_ISBLK(mode):
            if not _HAS_BLKGETSIZE64:
                raise NotImplementedError("Block device size query not supported on this platform.")
            fd = os.open(filename, os.O_RDONLY)
            try:
                buf = bytearray(8)
                fcntl.ioctl(fd, BLKGETSIZE64, buf)
                self._file_length = struct.unpack_from("<Q", buf)[0]
            finally:
                os.close(fd)
            self._is_resizable = False
        else:
            raise NotImplementedError("File object is not a regular file or block device.")

        self._fp = open(filename, "rb")  # noqa: SIM115
        self._filename = filename

        # Pre-load the window
        data = self._fp.read(len(self._window))
        n = len(data)
        self._window[:n] = data
        self._win_offset = 0
        self._win_occupied = n

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def read(self, ba: bytearray, index: int, pos: int, length: int) -> int:
        if pos >= self._file_length or pos < 0:
            return 0
        if pos + length > self._file_length:
            length = self._file_length - pos
        self._fp.seek(pos)
        chunk = self._fp.read(length)
        ba[index : index + len(chunk)] = chunk
        return len(chunk)

    def __getitem__(self, index: int) -> int:
        if not self._in_window(index):
            if index >= self._file_length:
                raise IndexError(f"FileBuffer[{index}]")
            self._refill_window(index)
        return self._window[index - self._win_offset]

    def __setitem__(self, index: int, value: int) -> None:
        pass  # read-only

    def append(self, data: bytes, index: int, length: int) -> None:
        pass  # read-only

    def append_buffer(self, buf: IBuffer, index: int, length: int) -> None:
        pass  # read-only

    def insert(self, pos: int, data: bytes, index: int, length: int) -> None:
        pass  # read-only

    @property
    def size(self) -> int:
        return self._file_length

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def is_resizable(self) -> bool:
        return self._is_resizable
