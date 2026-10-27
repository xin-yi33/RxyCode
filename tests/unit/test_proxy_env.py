"""`utils/proxy_env` — NO_PROXY IPv6 bypass normalization (overlay → master).

A bare bracketed IPv6 entry like ``[::1]`` in ``NO_PROXY`` crashes
``httpx``'s mount-table build (``InvalidURL: Invalid port: ':1]'``), which
in turn breaks ``ChatOpenAI``/``AgentV2`` construction on hosts where a
proxy manager writes that form. The sanitizer rewrites it in place before
any client is built; stdlib-only, idempotent, never raises.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from utils.proxy_env import (  # noqa: E402
    normalize_no_proxy_value,
    sanitize_no_proxy_env,
)


def test_bracketed_ipv6_is_unbracketed():
    value, changed = normalize_no_proxy_value("localhost,127.0.0.1,[::1]")
    assert value == "localhost,127.0.0.1,::1"
    assert changed == ["[::1]->::1"]


def test_port_suffixed_ipv6_is_kept():
    value, changed = normalize_no_proxy_value("[::1]:8080,example.com")
    assert value == "[::1]:8080,example.com"
    assert changed == []


def test_httpx_accepts_normalized_entries(monkeypatch):
    """The rewritten entry must not crash a real trust_env client."""
    import httpx

    monkeypatch.setenv("NO_PROXY", "localhost,[::1]")
    sanitize_no_proxy_env()  # rewrites os.environ in place
    assert os.environ["NO_PROXY"] == "localhost,::1"
    httpx.Client(trust_env=True)  # must not raise InvalidURL


def test_sanitize_env_is_idempotent_and_never_raises():
    env = {"NO_PROXY": "localhost,[::1]"}
    first = sanitize_no_proxy_env(environ=env)
    assert env["NO_PROXY"] == "localhost,::1"
    assert first
    # Second pass is a no-op.
    assert sanitize_no_proxy_env(environ=env) == []
    # Clean env: nothing reported, nothing written.
    clean = {"NO_PROXY": "localhost"}
    assert sanitize_no_proxy_env(environ=clean) == []
    assert clean["NO_PROXY"] == "localhost"
