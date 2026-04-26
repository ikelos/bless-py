# bless/buffers/simple_buffer.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

from .ibuffer import IBuffer


class SimpleBuffer(IBuffer):
    """A lightweight, in-memory buffer that grows on demand."""

    def __init__(self) -> None:
        self._data = bytearray()

    def read(self, ba: bytearray, index: int, pos: int, length: int) -> int:
        ba[index : index + length] = self._data[pos : pos + length]
        return length

    def append(self, data: bytes, index: int, length: int) -> None:
        if length == 0:
            return
        self._data.extend(data[index : index + length])

    def append_buffer(self, buf: IBuffer, index: int, length: int) -> None:
        if length == 0:
            return
        tmp = bytearray(length)
        buf.read(tmp, 0, index, length)
        self._data.extend(tmp)

    def insert(self, pos: int, data: bytes, index: int, length: int) -> None:
        if length == 0:
            return
        self._data[pos:pos] = data[index : index + length]

    def __getitem__(self, index: int) -> int:
        if index >= len(self._data):
            return 0
        return self._data[index]

    def __setitem__(self, index: int, value: int) -> None:
        if index < len(self._data):
            self._data[index] = value

    @property
    def size(self) -> int:
        return len(self._data)
