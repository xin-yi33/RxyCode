"""LSP (Language Server Protocol) client module.

废弃代码（2026-10-01 注释）：experimental，全库 .py 零 import（grep 验证，
仅 docs 提及）。未接线到 AgentV2 工具面；保留注释存档，接线前勿扩散引用。
"""

from .client import LSPClient, Diagnostic

__all__ = ["LSPClient", "Diagnostic"]
