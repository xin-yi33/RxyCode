#!/usr/bin/env python3
"""Run the Phase 1 exit-check test suite in deterministic layers.

Single source of truth for the layer definitions.  ``.github/workflows/ci.yml``
calls this script instead of inlining the same five pytest commands, and local
runs (including the eval watchdog) use it too.

Why layers: each layer is its own pytest process with a hard per-test timeout,
so one hanging test (e.g. a native screen capture on a locked session) is
contained and reported instead of stalling the whole suite.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

#: (name, positional pytest args) — mirror of the CI matrix.
LAYERS = [
    ("unit", ["tests/unit", "-m", "unit and not serial and not live and not pty"]),
    ("integration", ["tests/integration", "-m", "integration and not serial and not live and not pty"]),
    ("contract", ["tests/contract", "-m", "contract and not serial and not live and not pty"]),
    ("serial", ["tests", "-m", "serial and not live and not pty", "-n", "0"]),
    ("regression", ["tests", "-m", "not unit and not integration and not contract and not system and not serial and not live and not pty"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2,
                        help="pytest-xdist workers for parallel layers (serial is always -n 0)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="per-test timeout in seconds")
    parser.add_argument("--verbose", action="store_true",
                        help="pass -v --tb=short to pytest (CI style)")
    parser.add_argument("--junit-dir", default=None,
                        help="write per-layer junitxml files into this directory")
    parser.add_argument("--coverage-data-dir", default=None,
                        help="enable pytest-cov and write per-layer data files here")
    args = parser.parse_args()

    if args.junit_dir:
        os.makedirs(args.junit_dir, exist_ok=True)
    if args.coverage_data_dir:
        os.makedirs(args.coverage_data_dir, exist_ok=True)

    common = ["--timeout", str(args.timeout)]
    if args.verbose:
        common += ["-v", "--tb=short"]
    else:
        common += ["-q", "--tb=line"]

    failed: list[str] = []
    for name, base in LAYERS:
        cmd = [sys.executable, "-m", "pytest", *base]
        if name != "serial":
            cmd += ["-n", str(args.workers), "--dist", "loadscope"]
        cmd += common
        if args.junit_dir:
            cmd.append(f"--junitxml={os.path.join(args.junit_dir, name + '.xml')}")

        env = os.environ.copy()
        env["RXYCODE_TEST_RUN_ID"] = name
        if args.coverage_data_dir:
            env["COVERAGE_FILE"] = os.path.join(
                args.coverage_data_dir, f".coverage.{name}"
            )
            cmd += ["--cov", "--cov-report="]

        print(f"\n=== layer: {name} ===", flush=True)
        proc = subprocess.run(cmd, check=False, env=env)
        if proc.returncode:
            failed.append(name)

    if failed:
        print(f"Failed layers: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("All layers passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
