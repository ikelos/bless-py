# bless/logger.py — centralised logging configuration
from __future__ import annotations

import logging
import sys

_logger = logging.getLogger("bless")
_handler: logging.StreamHandler | None = None


def setup(verbose: bool = False) -> None:
    """Configure the 'bless' logger.  Safe to call multiple times."""
    global _handler
    level = logging.DEBUG if verbose else logging.WARNING
    _logger.setLevel(level)
    # Add handler exactly once so repeated calls don't duplicate output
    if _handler is None:
        _handler = logging.StreamHandler(sys.stderr)
        _handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        _logger.addHandler(_handler)
    _handler.setLevel(level)


def get() -> logging.Logger:
    return _logger
