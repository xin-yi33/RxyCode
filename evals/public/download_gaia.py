"""Download official GAIA 2023 validation attachments from ModelScope."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent / "official" / "gaia"
FILES = ROOT / "files"
PARQUET = ROOT / "metadata.parquet"
BASE = (
    "https://www.modelscope.cn/api/v1/datasets/AI-ModelScope/GAIA/"
    "repo?Revision=master&FilePath=2023/validation/"
)


def main() -> None:
    FILES.mkdir(parents=True, exist_ok=True)
    if not PARQUET.is_file():
        dest = PARQUET
        url = BASE + "metadata.parquet"
        print("GET", url)
        urllib.request.urlretrieve(url, dest)
    frame = pd.read_parquet(PARQUET)
    names = sorted({str(name).strip() for name in frame["file_name"].fillna("") if str(name).strip()})
    for name in names:
        dest = FILES / name
        if dest.is_file() and dest.stat().st_size > 0:
            print("skip", name, dest.stat().st_size)
            continue
        url = BASE + name
        print("GET", name)
        urllib.request.urlretrieve(url, dest)
        print(" wrote", dest.stat().st_size)
    print("done", len(names), "files")


if __name__ == "__main__":
    main()
