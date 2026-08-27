"""Resolve isolated venv paths without cygpath/bash."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def venv_scripts(venv: Path, *, windows: bool | None = None) -> Path:
    root = venv if isinstance(venv, Path) else Path(venv)
    if (os.name == "nt") if windows is None else windows:
        return root / "Scripts"
    return root / "bin"


def venv_python(venv: Path, *, windows: bool | None = None) -> Path:
    scripts = venv_scripts(venv, windows=windows)
    if (os.name == "nt") if windows is None else windows:
        return scripts / "python.exe"
    return scripts / "python"


def venv_site_packages(venv: Path) -> Path:
    root = Path(venv)
    if os.name == "nt":
        return Path(str(root) + os.sep + "Lib" + os.sep + "site-packages")
    lib = Path(str(root) + os.sep + "lib")
    if lib.is_dir():
        for child in sorted(lib.iterdir()):
            if child.name.startswith("python"):
                return Path(str(child) + os.sep + "site-packages")
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return Path(str(root) + os.sep + "lib" + os.sep + ver + os.sep + "site-packages")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(venv_python(target))
