"""Security and cancellation contracts for the public web fetcher."""

import asyncio
import inspect

import httpx
import pytest


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:secret@example.com/",
        "http://localhost/admin",
        "http://service.local/admin",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
        "http://intranet/admin",
    ],
)
def test_webfetch_rejects_non_public_targets(url):
    from RxyCode.RxyCode1_1_0.tools.webfetch import _validate_target_url

    with pytest.raises(ValueError):
        _validate_target_url(url)


@pytest.mark.asyncio
async def test_webfetch_pins_validated_dns_and_preserves_host_header(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import webfetch
    from RxyCode.RxyCode1_1_0.utils import safe_http

    public_ip = "93.184.216.34"

    async def resolve(hostname, port):
        assert (hostname, port) == ("example.com", 443)
        return [public_ip]

    observed = {}

    async def handler(request):
        observed["host"] = request.url.host
        observed["header"] = request.headers["host"]
        observed["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, text="<p>verified content</p>")

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve)
    monkeypatch.setattr(safe_http.httpx, "AsyncClient", client_factory)

    result = await webfetch.fetch_url_async("https://example.com/article")

    assert result == "verified content"
    assert observed == {
        "host": public_ip,
        "header": "example.com",
        "sni": "example.com",
    }


@pytest.mark.asyncio
async def test_webfetch_revalidates_redirect_targets(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import webfetch
    from RxyCode.RxyCode1_1_0.utils import safe_http

    calls = []

    async def resolve(_hostname, _port):
        return ["93.184.216.34"]

    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/private"},
        )

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve)
    monkeypatch.setattr(safe_http.httpx, "AsyncClient", client_factory)

    result = await webfetch.fetch_url_async("https://example.com/start")

    assert "private or non-routable" in result
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_webfetch_rejects_private_dns_answers_before_connect(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import webfetch
    from RxyCode.RxyCode1_1_0.utils import safe_http

    async def resolve(_hostname, _port):
        raise ValueError("hostname resolves to a private or non-routable address")

    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve)
    result = await webfetch.fetch_url_async("https://example.com/")

    assert "private or non-routable" in result


@pytest.mark.asyncio
async def test_webfetch_network_request_is_cooperatively_cancelled(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import webfetch
    from RxyCode.RxyCode1_1_0.utils import safe_http

    started = asyncio.Event()

    async def resolve(_hostname, _port):
        return ["93.184.216.34"]

    async def handler(_request):
        started.set()
        await asyncio.Event().wait()

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve)
    monkeypatch.setattr(safe_http.httpx, "AsyncClient", client_factory)

    task = asyncio.create_task(webfetch.fetch_url_async("https://example.com/slow"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_webfetch_tool_exposes_native_async_path():
    from RxyCode.RxyCode1_1_0.tools.webfetch import webfetch_tool

    assert inspect.iscoroutinefunction(webfetch_tool.coroutine)
