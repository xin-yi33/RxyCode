"""Installed console entry points."""

from __future__ import annotations

import sys

from .main import cli


def main() -> None:
    """Launch the CLI with its normal frontend selection."""
    cli.main(args=sys.argv[1:], prog_name="rxycode")
