# bless/util/base_converter.py
# Copyright (c) 2005, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

_DEFAULT_MIN_DIGITS = [0, 0, 8, 6, 4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2]


def convert_to_string(num: int, base: int, prepend_prefix: bool = False,
                      lowercase: bool = False, min_digits: int = 0) -> str:
    if base < 2 or base > 16:
        return ""

    alpha = "a" if lowercase else "A"
    digits: list[str] = []

    if num == 0:
        digits = ["0"]
    else:
        n = num
        while n > 0:
            rem = n % base
            digits.append(chr(ord("0") + rem) if rem < 10 else chr(ord(alpha) + rem - 10))
            n //= base
        digits.reverse()

    if min_digits == 0 and base < len(_DEFAULT_MIN_DIGITS):
        min_digits = _DEFAULT_MIN_DIGITS[base]

    while len(digits) < min_digits:
        digits.insert(0, "0")

    result = "".join(digits)

    if prepend_prefix:
        if base == 16:
            result = "0x" + result
        elif base == 8 and result[0] != "0":
            result = "0" + result

    return result


def _char_to_int(c: str, base: int) -> int:
    c = c.lower()
    if "0" <= c <= "9":
        v = ord(c) - ord("0")
    elif "a" <= c <= "f":
        v = ord(c) - ord("a") + 10
    else:
        raise ValueError(f"Character '{c}' is not valid in a base-{base} number.")
    if v >= base:
        raise ValueError(f"Character '{c}' is not valid in a base-{base} number.")
    return v


def convert_to_num(s: str, base: int,
                   start: int = 0, end: int = -1) -> int:
    if end == -1:
        end = len(s) - 1
    val = 0
    for i in range(start, end + 1):
        val = base * val + _char_to_int(s[i], base)
    return val


def parse(s: str) -> int:
    """Auto-detect base from prefix (0x=hex, 0=octal, else decimal)."""
    t = s.strip()
    if not t:
        raise ValueError("Empty string.")
    if t.startswith("0x") or t.startswith("0X"):
        return convert_to_num(t, 16, 2)
    if t.startswith("0") and len(t) > 1:
        return convert_to_num(t, 8)
    return convert_to_num(t, 10)


def byte_array_to_string(data: bytes, base: int) -> str:
    """Convert raw bytes to a space-separated string of base-*base* values."""
    sep = " "
    return sep.join(convert_to_string(b, base) for b in data)


def string_to_byte_array(s: str, base: int) -> bytes:
    """Parse a space-separated string of base-*base* values into bytes."""
    parts = s.split()
    result = bytearray()
    for p in parts:
        result.append(convert_to_num(p, base) & 0xFF)
    return bytes(result)
