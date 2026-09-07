#!/usr/bin/env python
# coding: utf-8
"""PyInstaller entry point: launch the pack manager GUI."""

import sys

from pyocd_pack_inject.gui import main

if __name__ == '__main__':
    sys.exit(main())
