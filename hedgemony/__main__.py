"""Lets `python -m hedgemony` work identically to the `hedgemony` command."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
