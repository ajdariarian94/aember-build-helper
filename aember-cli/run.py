#!/usr/bin/env python3
"""The `aember` CLI of aember-build-helper: runs from the submodule, no install."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aember.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
