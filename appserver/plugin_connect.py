"""OAuth connect state machine for plugin store connectors.

HTTP is injected so tests never hit github.com / canva.com. Tokens are returned
to PluginService for user.json storage — this module does not write config.yaml
and must stay off the agent graph / orchestrator.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .plugin_adapter import catalog_entry
from .settings import redact_text


def _oauth_error(code: str, message: str) -> Exception:
    from .plugin_service import PluginError

    return PluginError(code, message)

DEFAULT_REDIRECT = "http://127.0.0.1:8742/oauth/callback"


class HttpTransport(Protocol):
    def post(self, url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        ...


class UrllibTransport:
    def post(self, url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        body = urlencode(data).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urlopen(req, timeout=15) as resp:  # noqa: S310 — caller supplies provider token URL
                raw = resp.read().decode("utf-8")
        except (URLError, TimeoutError, OSError) as exc:
            raise _oauth_error("PLUGIN_OAUTH_EXCHANGE_FAILED", "oauth token exchange failed") from exc
        try:
            payload = json.loads(raw) if raw.strip().startswith("{") else {}
        except json.JSONDecodeError as exc:
            raise _oauth_error("PLUGIN_OAUTH_EXCHANGE_FAILED", "oauth token response was not json") from exc
        if not isinstance(payload, dict):
            raise _oauth_error("PLUGIN_OAUTH_EXCHANGE_FAILED", "oauth token response was not an object")
        return payload


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def client_id_for(name: str, row: dict[str, Any], package_dir: Any | None = None) -> str:
    env_key = f"RXYCODE_{name.upper().replace('-', '_')}_OAUTH_CLIENT_ID"
    env_id = (os.environ.get(env_key) or "").strip()
    if env_id:
        return env_id
    if package_dir is not None:
        oauth_path = package_dir / "oauth.json"
        if oauth_path.is_file() and not oauth_path.is_symlink():
            try:
                payload = json.loads(oauth_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                payload = {}
            if isinstance(payload, dict):
                found = str(payload.get("client_id") or "").strip()
                if found:
                    return found
    catalog_id = str(row.get("client_id") or "").strip()
    if catalog_id:
        return catalog_id
    return f"rxycode-dev-{name}-oauth"


def client_secret_for(name: str) -> str:
    env_key = f"RXYCODE_{name.upper().replace('-', '_')}_OAUTH_CLIENT_SECRET"
    return (os.environ.get(env_key) or "").strip()


def build_authorize_url(
    row: dict[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str | None = None,
) -> str:
    host = str(row.get("authorize_host") or "").strip()
    path = str(row.get("authorize_path") or "").strip() or "/"
    if not host:
        raise _oauth_error("PLUGIN_OAUTH_CONFIG", "catalog row missing authorize_host")
    if not path.startswith("/"):
        path = "/" + path
    scopes = row.get("scopes") or []
    scope_text = " ".join(str(item) for item in scopes if item) if isinstance(scopes, list) else str(scopes)
    query: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if scope_text:
        query["scope"] = scope_text
    if code_challenge:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = "s256"
    return f"https://{host}{path}?{urlencode(query)}"


def start_oauth_session(
    name: str,
    *,
    package_dir: Any | None = None,
    redirect_uri: str = DEFAULT_REDIRECT,
    pending: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    row = catalog_entry(name)
    if row is None or str(row.get("connect") or "").lower() != "oauth":
        raise _oauth_error("PLUGIN_OAUTH_UNSUPPORTED", f"{name} is not an oauth catalog connector")
    state = secrets.token_urlsafe(24)
    verifier = ""
    challenge = None
    if row.get("pkce") is True:
        verifier, challenge = _pkce_pair()
    cid = client_id_for(name, row, package_dir)
    url = build_authorize_url(
        row,
        client_id=cid,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    if pending is not None:
        pending[state] = {
            "name": name,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "token_url": str(row.get("token_url") or ""),
        }
    return {"authorize_url": url, "state": state, "name": name}


def exchange_oauth_code(
    name: str,
    *,
    code: str,
    state: str,
    pending: dict[str, dict[str, str]],
    http: HttpTransport | None = None,
) -> str:
    trimmed_code = (code or "").strip()
    trimmed_state = (state or "").strip()
    if not trimmed_code or not trimmed_state:
        raise _oauth_error("PLUGIN_OAUTH_STATE", "code and state are required")
    session = pending.pop(trimmed_state, None)
    if session is None or session.get("name") != name:
        raise _oauth_error("PLUGIN_OAUTH_STATE", "unknown or expired oauth state")
    row = catalog_entry(name) or {}
    token_url = session.get("token_url") or str(row.get("token_url") or "")
    if not token_url.startswith("https://"):
        raise _oauth_error("PLUGIN_OAUTH_CONFIG", "token_url must be https")
    data = {
        "grant_type": "authorization_code",
        "code": trimmed_code,
        "redirect_uri": session.get("redirect_uri") or DEFAULT_REDIRECT,
        "client_id": client_id_for(name, row),
        "client_secret": client_secret_for(name),
    }
    verifier = session.get("code_verifier") or ""
    if verifier:
        data["code_verifier"] = verifier
    transport = http or UrllibTransport()
    payload = transport.post(token_url, data, {"Accept": "application/json"})
    token = str(payload.get("access_token") or payload.get("token") or "").strip()
    if not token:
        raise _oauth_error("PLUGIN_OAUTH_EXCHANGE_FAILED", redact_text("oauth response missing access_token"))
    return token
