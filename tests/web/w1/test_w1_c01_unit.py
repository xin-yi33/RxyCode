"""WEB-W1-C01. The new package and the legacy import share one Session class."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-core" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_w1_c01_contract():
    """Legacy, canonical, and rxycode_core Session are one object."""
    from RxyCode.RxyCode1_1_0.core.session import Session as Canonical
    from core.session import Session as Legacy
    from rxycode_core import Session as Packaged

    assert Legacy is Canonical
    assert Packaged is Canonical


def test_w1_c01_negative():
    """Two different Agent classes block the import audit."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2 as Canonical
    from core.agent_v2 import AgentV2 as Legacy
    from rxycode_core import audit_class_identity

    assert Legacy is Canonical
    assert audit_class_identity([Legacy, Canonical]) == "OK"

    class _SecondAgent:
        pass

    assert audit_class_identity([Legacy, _SecondAgent]) == "BLOCKED"

    class _EqualMeta(type):
        def __eq__(cls, other: object) -> bool:
            return isinstance(other, type)

        def __hash__(cls) -> int:
            return 1

    class _Left(metaclass=_EqualMeta):
        pass

    class _Right(metaclass=_EqualMeta):
        pass

    assert _Left == _Right
    assert _Left is not _Right
    assert audit_class_identity([_Left, _Right]) == "BLOCKED"
