"""Public benchmarks: official BFCL AST, GAIA-style, ChatEval debate.

BFCL uses the Gorilla v4 JSONL dump (1240 Python AST items). GAIA official
466 remains gated. Runs are AgentV2-only; 429 is retried, never scored fail.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
