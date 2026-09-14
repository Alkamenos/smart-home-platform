#!/usr/bin/env python3
"""Shim for backward compatibility. Use `smart-home` command instead."""

import sys

from smart_home.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
