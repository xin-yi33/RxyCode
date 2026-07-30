import httpx
import hmac
import os
import re
import time
from typing import Optional
from urllib.parse import urlsplit

from .credential_store import delete_credential, store_credential
from .settings import get_config_path, get_model_config, load_config, save_config


HTTP_CODE_MESSAGES = {
    400: "请求无效。请检查 API URL 和 API Key 是否正确。(HTTP 400 Bad Request)",
    401: "认证失败。API Key 可能错误或已过期。(HTTP 401 Unauthorized)",
    403: "访问被拒绝。API Key 没有访问此模型的权限。(HTTP 403 Forbidden)",
    404: "API 端点未找到。请检查 API URL 是否正确。(HTTP 404 Not Found)",
    405: "方法不允许。该 API 端点可能不支持 chat completions 格式。(HTTP 405 Method Not Allowed)",
    413: "请求太大。模型可能有较小的上下文限制。(HTTP 413 Payload Too Large)",
    422: "请求格式无效。API 可能有不同的参数要求。(HTTP 422 Unprocessable Entity)",
    429: "请求过于频繁，已被限流。请稍后重试。(HTTP 429 Too Many Requests)",
    500: "API 服务器遇到内部错误。请稍后重试。(HTTP 500 Internal Server Error)",
    502: "API 服务器暂时不可用或已宕机。(HTTP 502 Bad Gateway)",
    503: "API 服务器过载或正在维护。(HTTP 503 Service Unavailable)",
    504: "API 服务器超时。可能速度较慢或无法访问。(HTTP 504 Gateway Timeout)",
}


def normalize_provider_base_url(
    value: str,
    *,
    require_https: bool = False,
) -> str:
    """Validate and normalize an HTTP(S) provider API root."""
    value = value.strip().rstrip("/")
    if not value or any(char.isspace() for char in value):
        raise ValueError("base_url must be an absolute http:// or https:// URL")

    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "base_url must not contain credentials, query parameters, or fragments"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("base_url contains an invalid port") from exc
    if require_https and parsed.scheme.casefold() != "https":
        raise ValueError(
            "base_url must use https:// when an API credential is sent"
        )
    return value


def _credential_config(api_key: str) -> dict:
    """Prefer an environment reference, otherwise use protected local storage."""
    value = api_key.strip()
    match = re.fullmatch(r"(?:env:|\$\{)([A-Za-z_][A-Za-z0-9_]*)\}?", value)
    if match:
        return {"api_key_env": match.group(1)}

    for name, configured in os.environ.items():
        if not name.upper().endswith(("API_KEY", "ACCESS_TOKEN")) or not configured:
            continue
        if hmac.compare_digest(configured, value):
            return {"api_key_env": name}
    return {"api_key_secret": store_credential(value, get_config_path())}


def add_model(
    name: str,
    api_key: str,
    base_url: str,
    model_name: Optional[str] = None,
    max_tokens: int = 8192,
    temperature: float = 0.7,
) -> dict:
    base_url = normalize_provider_base_url(base_url, require_https=True)
    cfg = load_config()
    models = cfg.setdefault("models", {})
    previous_reference = models.get(name, {}).get("api_key_secret", "")
    entry = {
        **_credential_config(api_key),
        "base_url": base_url,
        "model_name": model_name or name,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    models[name] = entry
    if not cfg.get("active_model"):
        cfg["active_model"] = name
    try:
        save_config(cfg)
    except BaseException:
        delete_credential(entry.get("api_key_secret", ""), get_config_path())
        raise
    if previous_reference != entry.get("api_key_secret"):
        delete_credential(previous_reference, get_config_path())
    return entry


def remove_model(name: str) -> bool:
    cfg = load_config()
    models = cfg.get("models", {})
    if name not in models:
        return False
    removed = models.pop(name)
    if cfg.get("active_model") == name:
        cfg["active_model"] = next(iter(models), None)
    save_config(cfg)
    delete_credential(removed.get("api_key_secret", ""), get_config_path())
    return True


def list_models() -> dict:
    cfg = load_config()
    return cfg.get("models", {})


def set_active_model(name: str) -> bool:
    cfg = load_config()
    if name not in cfg.get("models", {}):
        return False
    cfg["active_model"] = name
    save_config(cfg)
    return True


def test_model_connection(name: str) -> dict:
    """Probe an already persisted model by its local nickname."""
    cfg = load_config()
    models = cfg.get("models", {})
    if name not in models:
        return {"success": False, "error": f"Model '{name}' not found"}

    model = get_model_config(name, cfg)
    if not model.get("api_key"):
        env_name = model.get("api_key_env", "the configured environment variable")
        return {
            "success": False,
            "error": f"API credential is unavailable; set {env_name} and retry.",
        }
    return probe_model_connection(
        api_key=model["api_key"],
        base_url=model["base_url"],
        provider_model_id=model["model_name"],
    )


def discover_provider_models(base_url: str, api_key: str) -> dict:
    """GET {base_url}/models with the supplied credential.

    Returns a structured response without persisting anything to disk.
    Used by the Add-model wizard to surface the real model id list so the
    user can pick a value the provider actually serves.
    """
    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
    except ValueError as exc:
        return {"ok": False, "models": [], "error": str(exc)}

    api_key = api_key.strip()
    if not api_key:
        return {"ok": False, "models": [], "error": "API key is required"}

    def safe_error(value: object) -> str:
        text = str(value)
        return text.replace(api_key, "[REDACTED]") if api_key else text

    url = f"{base_url}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    start = time.time()
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url, headers=headers)
            elapsed = round(time.time() - start, 2)
            if resp.status_code != 200:
                friendly = HTTP_CODE_MESSAGES.get(resp.status_code)
                if friendly:
                    return {"ok": False, "models": [], "error": friendly, "elapsed": elapsed}
                return {
                    "ok": False,
                    "models": [],
                    "elapsed": elapsed,
                    "error": safe_error(f"HTTP {resp.status_code}: {resp.text[:200]}"),
                }
            try:
                data = resp.json()
            except Exception:
                return {
                    "ok": False,
                    "models": [],
                    "elapsed": elapsed,
                    "error": "Provider returned non-JSON /models payload",
                }
            ids: list[str] = []
            if isinstance(data, dict):
                raw_list = data.get("data")
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, dict):
                            mid = item.get("id")
                            if isinstance(mid, str) and mid.strip():
                                ids.append(mid.strip())
                elif isinstance(data.get("models"), list):
                    for item in data["models"]:
                        if isinstance(item, dict):
                            mid = item.get("id") or item.get("name")
                            if isinstance(mid, str) and mid.strip():
                                ids.append(mid.strip())
                        elif isinstance(item, str) and item.strip():
                            ids.append(item.strip())
            if not ids:
                return {
                    "ok": False,
                    "models": [],
                    "elapsed": elapsed,
                    "error": "Provider /models response did not contain any model id",
                }
            return {"ok": True, "models": ids, "elapsed": elapsed}
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        estr = safe_error(e)
        if "Name or service not known" in estr or "getaddrinfo" in estr:
            return {"ok": False, "models": [], "elapsed": elapsed, "error": "无法解析 API 地址。请检查域名是否正确。(DNS 解析失败)"}
        if "Connection refused" in estr:
            return {"ok": False, "models": [], "elapsed": elapsed, "error": "API 服务器拒绝连接。请检查 URL 和端口是否正确。"}
        if "Connection timed out" in estr or "timeout" in estr.lower():
            return {"ok": False, "models": [], "elapsed": elapsed, "error": "连接超时。API 服务器可能过慢、无法访问，或 URL 不正确。"}
        if "SSLError" in estr or "ssl" in estr.lower():
            return {"ok": False, "models": [], "elapsed": elapsed, "error": "SSL/TLS 错误。API 服务器可能有无效或自签名证书。"}
        return {"ok": False, "models": [], "elapsed": elapsed, "error": estr}


def probe_model_connection(
    *,
    api_key: str,
    base_url: str,
    provider_model_id: str,
) -> dict:
    """Test an unsaved provider configuration without touching disk."""
    api_key = api_key.strip()
    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    provider_model_id = provider_model_id.strip()
    if not api_key or not base_url or not provider_model_id:
        return {"success": False, "error": "Missing API credential, base URL, or provider model ID"}

    def safe_error(value: object) -> str:
        text = str(value)
        return text.replace(api_key, "[REDACTED]") if api_key else text

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider_model_id,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 32,
        "stream": False,
    }

    start = time.time()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload, headers=headers)
            elapsed = round(time.time() - start, 2)
            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                return {"success": True, "elapsed": elapsed, "reply": reply}
            else:
                friendly = HTTP_CODE_MESSAGES.get(resp.status_code)
                if friendly:
                    return {"success": False, "elapsed": elapsed, "error": friendly}
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": safe_error(f"HTTP {resp.status_code}: {resp.text[:200]}"),
                }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        estr = safe_error(e)
        if "Name or service not known" in estr or "getaddrinfo" in estr:
            return {"success": False, "elapsed": elapsed, "error": "无法解析 API 地址。请检查域名是否正确。(DNS 解析失败)"}
        if "Connection refused" in estr:
            return {"success": False, "elapsed": elapsed, "error": "API 服务器拒绝连接。请检查 URL 和端口是否正确。"}
        if "Connection timed out" in estr or "timeout" in estr.lower():
            return {"success": False, "elapsed": elapsed, "error": "连接超时。API 服务器可能过慢、无法访问，或 URL 不正确。"}
        if "SSLError" in estr or "ssl" in estr.lower():
            return {"success": False, "elapsed": elapsed, "error": "SSL/TLS 错误。API 服务器可能有无效或自签名证书。"}
        return {"success": False, "elapsed": elapsed, "error": estr}
