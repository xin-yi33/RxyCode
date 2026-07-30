#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Version bump: RxyCode 1.1.0 -> 1.1.0, RxyCode1_1_0 -> RxyCode1_1_0.

Walks all text files (excluding superpowers-zh, node_modules, __pycache__, .git, .codebuddy)
and applies targeted replacements.
"""
import os
import sys

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories to skip entirely
SKIP_DIRS = {
    "superpowers-zh", "node_modules", "__pycache__", ".git",
    ".codebuddy", "dist", ".pytest_cache", ".vitest",
}

# File extensions to process
TEXT_EXTS = {
    ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml",
    ".cfg", ".ini", ".ts", ".tsx", ".js", ".jsx",
    ".sh", ".bat", ".cmd", ".env", ".example", ".yml.example",
}

# Replacements: (old, new, description)
# Order matters - more specific patterns first
REPLACEMENTS = [
    # Python module name: RxyCode1_1_0 -> RxyCode1_1_0
    ("RxyCode1_1_0", "RxyCode1_1_0", "module name"),
    # Display version with v prefix: RxyCode v1.1.0 -> RxyCode v1.1.0
    ("RxyCode v1.1.0", "RxyCode v1.1.0", "display version v"),
    # Display version without v: RxyCode 1.1.0 -> RxyCode 1.1.0
    ("RxyCode 1.1.0", "RxyCode 1.1.0", "display version"),
    # package.json version: "version": "1.1.0" -> "version": "1.1.0"
    ('"version": "1.1.0"', '"version": "1.1.0"', "package.json version"),
]

# Files that should also get extension-less treatment
NO_EXT_FILES = {"Makefile", "Dockerfile", ".env", ".env.example", ".gitignore", ".dockerignore"}


def should_process(path, name):
    """Check if a file should be processed."""
    full = os.path.join(path, name)
    # Skip if any skip dir is in the path
    parts = full.replace("\\", "/").split("/")
    for skip in SKIP_DIRS:
        if skip in parts:
            return False
    # Check extension
    _, ext = os.path.splitext(name)
    if ext.lower() in TEXT_EXTS:
        return True
    if name in NO_EXT_FILES:
        return True
    return False


def process_file(filepath):
    """Process a single file, return number of replacements made."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return 0

    original = content
    total_replacements = 0

    for old, new, desc in REPLACEMENTS:
        count = content.count(old)
        if count > 0:
            content = content.replace(old, new)
            total_replacements += count

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return total_replacements
    return 0


def main():
    total_files = 0
    total_replacements = 0

    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skip directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            if not should_process(dirpath, filename):
                continue
            filepath = os.path.join(dirpath, filename)
            count = process_file(filepath)
            if count > 0:
                total_files += 1
                total_replacements += count
                rel = os.path.relpath(filepath, ROOT)
                print(f"  [{count:3d}] {rel}")

    print(f"\nDone: {total_files} files, {total_replacements} replacements")


if __name__ == "__main__":
    main()
