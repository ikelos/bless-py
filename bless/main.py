#!/usr/bin/env python3
# bless/main.py
# Copyright (c) 2004, Alexandros Frantzis — Python port (c) 2024
# GPL-2.0-or-later

import sys

from .gui.main_window import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
