# bless/buffers/ibuffer.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later


class IBuffer:
    """Interface/abstract base for all buffer types."""

    def read(self, ba: bytearray, index: int, pos: int, length: int) -> int:
        raise NotImplementedError

    def append(self, data: bytes, index: int, length: int) -> None:
        raise NotImplementedError

    def append_buffer(self, buf: "IBuffer", index: int, length: int) -> None:
        raise NotImplementedError

    def insert(self, pos: int, data: bytes, index: int, length: int) -> None:
        raise NotImplementedError

    def __getitem__(self, index: int) -> int:
        raise NotImplementedError

    def __setitem__(self, index: int, value: int) -> None:
        raise NotImplementedError

    @property
    def size(self) -> int:
        raise NotImplementedError
