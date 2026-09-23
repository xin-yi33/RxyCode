"""废弃代码（2026-09-22）。

运行时探针曾把观察行写到 ``D:\\tmp-cursor-probe\\rxycode-probe.log``。
调用点已从 appserver、agent、session、executor、tool 上拔掉。
保留这个空函数，是为了万一还有旧导入时不会抛 ImportError，也不会再创建日志。
"""

from __future__ import annotations


def probe(event: str, **fields: object) -> None:
    """废弃代码（2026-09-22）：不再写探针日志。"""
    return None
