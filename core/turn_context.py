"""FX8 · public turn-context seam for LinkAgent (PHASE-FIX §5 FX8).

EKO-style context can only append to the user suffix after the prefix is
frozen; it must never be merged into S1 / tool sections. ChatPrefix turns
ignore it entirely. Empty blocks are byte-identical to a no-op.
"""

from __future__ import annotations

from typing import Literal, Sequence, TypedDict


class TurnContextBlock(TypedDict):
    kind: Literal["eko", "note", "status"]
    text: str


FORBIDDEN_KINDS = frozenset({"system", "tools"})


def validate_blocks(blocks: Sequence[dict]) -> None:
    """Reject kinds that would splice context into a frozen section."""
    for block in blocks:
        kind = block.get("kind") if isinstance(block, dict) else None
        if kind in FORBIDDEN_KINDS:
            raise ValueError(
                f"turn-context kind {kind!r} is forbidden "
                f"(allowed: eko, note, status)"
            )


def serialize_turn_context(blocks: Sequence[dict]) -> str:
    """Join non-empty texts. Empty input (or all-blank text) yields an
    empty string, so the user message stays byte-identical to a no-op."""
    validate_blocks(blocks)
    parts = [
        str(block.get("text") or "").strip()
        for block in blocks
        if isinstance(block, dict) and str(block.get("text") or "").strip()
    ]
    return "\n".join(parts)
