"""Entry point for the packaged app (PyInstaller): same as `python -m aion2meter`."""
import sys

from aion2meter.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
