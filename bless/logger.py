# bless/logger.py — centralised logging configuration
import logging
import sys

_logger = logging.getLogger("bless")


def setup(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    ))
    _logger.setLevel(level)
    _logger.addHandler(handler)


def get() -> logging.Logger:
    return _logger
