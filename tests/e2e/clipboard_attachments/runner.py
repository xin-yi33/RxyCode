"""Explicitly opted-in entrypoint for the serial Windows clipboard suite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="directory for a unique run folder and evidence bundle (never cleaned by the runner)",
    )
    args, pytest_args = parser.parse_known_args()
    if os.name != "nt":
        parser.error("this acceptance suite requires Windows")
    if os.environ.get("RXYCODE_CLIPBOARD_E2E") != "1":
        parser.error("set RXYCODE_CLIPBOARD_E2E=1 explicitly for this manual clipboard run")
    if any(
        value in {"-n", "--numprocesses"}
        or (value.startswith("-n") and not value.startswith("--"))
        or value.startswith("--numprocesses=")
        for value in pytest_args
    ):
        parser.error("the system-clipboard acceptance suite cannot run with pytest-xdist workers")
    if args.output_root is not None:
        os.environ["RXYCODE_CLIPBOARD_E2E_OUTPUT"] = str(args.output_root.resolve())
    test_path = Path(__file__).resolve().parent / "test_clipboard_attachments.py"
    return int(pytest.main([str(test_path), "-q", "-s", *pytest_args]))


if __name__ == "__main__":
    raise SystemExit(main())
