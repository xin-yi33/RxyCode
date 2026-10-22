"""Browser regressions for Web theme persistence and ALTCHA V1 compatibility."""

from __future__ import annotations

import json
import hashlib
import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
SERVER_SRC = REPO / "packages" / "rxycode-server" / "src"
CADDYFILE = REPO / "infra" / "compose" / "Caddyfile.prod"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from rxycode_server.altcha import _ReplayRegistry, create_challenge, verify_payload

_ALTCHA_SECRET = "browser-regression-only-secret"
_AUTH_401 = json.dumps({"detail": "UNAUTHORIZED"})


def _create_deterministic_signed_challenge(
    counter: int = 17, *, expires_in: int = 1200
) -> dict[str, object]:
    """Use the production signer with deterministic test entropy."""
    with patch("rxycode_server.altcha.secrets.randbelow", return_value=counter):
        if expires_in == 1200:
            return create_challenge(_ALTCHA_SECRET)
        mocked_now = int(time.time()) + expires_in - 1200
        with patch("rxycode_server.altcha.time.time", return_value=mocked_now):
            return create_challenge(_ALTCHA_SECRET)


@pytest.fixture(scope="session")
def web_origin() -> str:
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        pytest.skip("Node.js and the installed apps/web Vite dependency are required")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [node, str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Vite exited before becoming ready (exit {server.returncode})")
            try:
                with urlopen(origin, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite did not become ready within 30 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


@pytest.fixture(scope="session")
def production_web_origin() -> str:
    """Build and serve the production bundle used by compatibility checks."""
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    tsc = WEB / "node_modules" / "typescript" / "bin" / "tsc"
    if not node or not vite.is_file() or not tsc.is_file():
        pytest.skip("Node.js and installed apps/web build dependencies are required")

    subprocess.run(
        [node, str(tsc), "--noEmit", "-p", "tsconfig.json"],
        cwd=WEB,
        check=True,
        timeout=120,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    subprocess.run(
        [node, str(vite), "build"],
        cwd=WEB,
        check=True,
        timeout=180,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [node, str(vite), "preview", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(
                    f"Vite preview exited before becoming ready (exit {server.returncode})"
                )
            try:
                with urlopen(origin, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite preview did not become ready within 30 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _stub_api(
    page,
    login_submissions: list[dict[str, object]] | None = None,
    *,
    counter: int = 17,
    compat_failure: str | None = None,
    short_compat_expiry: bool = False,
):
    challenges: list[dict[str, object]] = []
    registry = _ReplayRegistry()
    challenge_calls = 0

    def fulfill(route, status: int, body: object) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body),
        )

    def handle(route) -> None:
        nonlocal challenge_calls
        request = route.request
        path = urlparse(request.url).path
        if path == "/api/v1/auth/capabilities":
            fulfill(
                route,
                200,
                {"captcha": "altcha", "registration": "open", "code_delivery": "none"},
            )
        elif path == "/api/v1/me":
            fulfill(route, 401, {"detail": "UNAUTHORIZED"})
        elif path == "/api/v1/auth/csrf":
            fulfill(route, 200, {"csrf_token": "browser-test-csrf"})
        elif path == "/api/v1/auth/altcha":
            challenge_calls += 1
            challenges.append({"request": challenge_calls})
            # React StrictMode deliberately mounts/cleans up effects twice in
            # development. Keep both initial attempts failing so only the
            # user's explicit retry can recover the form.
            if challenge_calls <= 2 and compat_failure == "network":
                fulfill(route, 503, {"code": "CHALLENGE_UNAVAILABLE"})
                return
            if challenge_calls <= 2 and compat_failure == "invalid":
                challenge = {
                    "algorithm": "SHA-256",
                    "challenge": "not-a-valid-digest",
                    "maxnumber": 100000,
                    "salt": "bad?expires=1999999999&",
                    "signature": "0" * 64,
                }
            else:
                challenge = _create_deterministic_signed_challenge(
                    counter,
                    expires_in=3 if short_compat_expiry else 1200,
                )
            fulfill(route, 200, challenge)
        elif path in {
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/forgot",
        } and request.method == "POST":
            body = json.loads(request.post_data or "{}")
            valid = verify_payload(body.get("captcha"), _ALTCHA_SECRET, registry)
            if login_submissions is not None:
                login_submissions.append(
                    {"path": path, "captcha_valid": valid, "body": body}
                )
            # The test verifies PoW acceptance, then deliberately stops before
            # any account/session state is created.
            status = 401 if path == "/api/v1/auth/login" else 400
            fulfill(route, status, {"detail": "BROWSER_TEST_STOP"})
        else:
            fulfill(route, 503, {"code": "UNAVAILABLE"})

    page.route("**/api/v1/**", handle)
    return challenges


def _map_virtual_origin(page, virtual_origin: str, local_origin: str) -> None:
    """Serve Vite bytes under a different browser origin without changing page origin."""
    local = urlparse(local_origin)

    def forward(route) -> None:
        request = urlparse(route.request.url)
        target = f"{local.scheme}://{local.netloc}{request.path}"
        if request.query:
            target += f"?{request.query}"
        response = route.fetch(url=target)
        route.fulfill(response=response)

    page.route(f"{virtual_origin}/**", forward)


def _install_worker_failure(page, failure: str) -> None:
    scripts = {
        "worker-disabled": """
          window.__rxyWorkerAttempts = 0;
          Object.defineProperty(window, 'Worker', {
            configurable: true,
            writable: true,
            value: function WorkerDisabled() {
              window.__rxyWorkerAttempts += 1;
              throw new DOMException('Worker disabled for regression test', 'SecurityError');
            },
          });
        """,
        "worker-no-subtle": """
          window.__rxyWorkerAttempts = 0;
          const NativeWorker = window.Worker;
          window.Worker = new Proxy(NativeWorker, {
            construct(target, args) {
              window.__rxyWorkerAttempts += 1;
              return Reflect.construct(target, args);
            },
          });
          const NativeBlob = window.Blob;
          window.Blob = new Proxy(NativeBlob, {
            construct(target, args) {
              const parts = args[0];
              if (Array.isArray(parts) && parts.some((part) =>
                typeof part === 'string' && part.includes('crypto.subtle.digest'))) {
                args[0] = [
                  "Object.defineProperty(self.crypto, 'subtle', {configurable:true,value:undefined});",
                  ...parts,
                ];
              }
              return Reflect.construct(target, args);
            },
          });
        """,
        "worker-and-window-no-subtle": """
          window.__rxyWorkerAttempts = 0;
          const NativeWorker = window.Worker;
          window.Worker = new Proxy(NativeWorker, {
            construct(target, args) {
              window.__rxyWorkerAttempts += 1;
              return Reflect.construct(target, args);
            },
          });
          Object.defineProperty(window.crypto, 'subtle', {
            configurable: true,
            value: undefined,
          });
          const NativeBlob = window.Blob;
          window.Blob = new Proxy(NativeBlob, {
            construct(target, args) {
              const parts = args[0];
              if (Array.isArray(parts) && parts.some((part) =>
                typeof part === 'string' && part.includes('crypto.subtle.digest'))) {
                args[0] = [
                  "Object.defineProperty(self.crypto, 'subtle', {configurable:true,value:undefined});",
                  ...parts,
                ];
              }
              return Reflect.construct(target, args);
            },
          });
        """,
    }
    page.add_init_script(scripts[failure])


def _fill_auth_form(page, auth_path: str) -> None:
    page.locator('input[name="email"]').fill("browser-test@example.invalid")
    password = page.locator('input[name="password"]')
    if password.count():
        password.fill("not-a-real-account-password")


@pytest.mark.parametrize(
    ("auth_path", "endpoint", "counter"),
    [
        ("/login", "/api/v1/auth/login", 17),
        ("/register", "/api/v1/auth/register", 50000),
        ("/forgot", "/api/v1/auth/forgot", 17),
    ],
)
@pytest.mark.parametrize(
    "failure",
    ["worker-disabled", "worker-no-subtle", "worker-and-window-no-subtle"],
)
def test_chromium_compat_solver_submits_genuine_v1_payload_for_auth_forms(
    web_origin: str, auth_path: str, endpoint: str, counter: int, failure: str
) -> None:
    submissions: list[dict[str, object]] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            challenges = _stub_api(page, submissions, counter=counter)
            _install_worker_failure(page, failure)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{web_origin}{auth_path}", wait_until="domcontentloaded")
            expect(page.locator("altcha-widget")).to_have_count(0)
            expect(page.get_by_text("验证通过")).to_be_visible(timeout=15000)
            _fill_auth_form(page, auth_path)
            submit = page.locator('form button[type="submit"]')
            expect(submit).to_be_enabled(timeout=15000)

            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith(endpoint),
                timeout=10000,
            ):
                submit.click()

            assert len(submissions) == 1
            assert submissions[0]["path"] == endpoint
            assert submissions[0]["captcha_valid"] is True
            assert len(challenges) >= 1
            assert page.evaluate("() => window.__rxyWorkerAttempts") == 0
            assert page_errors == []
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize(
    ("failure_kind", "diagnostic"),
    [("network", "NETWORK"), ("invalid", "CHALLENGE")],
)
def test_chromium_compat_failure_keeps_form_locked_until_explicit_retry(
    web_origin: str, failure_kind: str, diagnostic: str
) -> None:
    submissions: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            challenges = _stub_api(
                page, submissions, compat_failure=failure_kind
            )
            _install_worker_failure(page, "worker-disabled")
            page.goto(f"{web_origin}/login", wait_until="domcontentloaded")
            _fill_auth_form(page, "/login")
            submit = page.locator('form button[type="submit"]')
            expect(page.get_by_role("alert")).to_contain_text(diagnostic, timeout=15000)
            expect(submit).to_be_disabled()
            assert submissions == []

            page.get_by_role("button", name="重试验证").click()
            expect(page.get_by_text("验证通过")).to_be_visible(timeout=15000)
            expect(submit).to_be_enabled(timeout=15000)
            assert len(challenges) >= 3
            assert len(submissions) == 0
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/api/v1/auth/login"),
                timeout=10000,
            ):
                submit.click()
            assert len(submissions) == 1
            assert submissions[0]["captcha_valid"] is True
        finally:
            context.close()
            browser.close()


def test_chromium_compat_expiry_clears_token_and_explicit_retry_solves_fresh_challenge(
    web_origin: str,
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            challenges = _stub_api(page, short_compat_expiry=True)
            _install_worker_failure(page, "worker-disabled")
            page.goto(f"{web_origin}/login", wait_until="domcontentloaded")
            _fill_auth_form(page, "/login")
            submit = page.locator('form button[type="submit"]')
            expect(submit).to_be_enabled(timeout=10000)
            expect(page.get_by_text("验证已过期，请重新验证")).to_be_visible(timeout=7000)
            expect(submit).to_be_disabled()

            page.get_by_role("button", name="重试验证").click()
            expect(submit).to_be_enabled(timeout=10000)
            assert len(challenges) >= 3
        finally:
            context.close()
            browser.close()


def test_chromium_loopback_compat_does_not_depend_on_secure_context_flag(
    web_origin: str,
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            challenges = _stub_api(page)
            _install_worker_failure(page, "worker-disabled")
            page.add_init_script(
                "Object.defineProperty(window, 'isSecureContext', {value: false});"
            )
            page.goto(f"{web_origin}/login", wait_until="domcontentloaded")
            expect(page.get_by_text("验证通过")).to_be_visible(timeout=15000)
            assert len(challenges) >= 1
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("secure_context_mode", ["false", "missing"])
def test_mobile_https_origin_compat_uses_real_server_verifier_without_browser_capabilities(
    web_origin: str, secure_context_mode: str
) -> None:
    """HTTPS scheme remains sufficient when Web Crypto/Worker flags are broken."""
    submissions: list[dict[str, object]] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(
            playwright.chromium, ignore_https_errors=True
        )
        try:
            _map_virtual_origin(page, "https://rxycode.xyz", web_origin)
            challenges = _stub_api(page, submissions, counter=99999)
            page.add_init_script(
                f"""(() => {{
                  Object.defineProperty(window, 'isSecureContext', {{
                    configurable: true,
                    value: {"false" if secure_context_mode == "false" else "undefined"},
                  }});
                  Object.defineProperty(window.crypto, 'subtle', {{
                    configurable: true,
                    value: undefined,
                  }});
                  Object.defineProperty(window, 'Worker', {{
                    configurable: true,
                    value: function WorkerDisabled() {{
                      window.__rxyWorkerAttempts += 1;
                      throw new DOMException('Worker disabled for regression test', 'SecurityError');
                    }},
                  }});
                  window.__rxyWorkerAttempts = 0;
                }})();"""
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto("https://rxycode.xyz/login", wait_until="domcontentloaded")
            assert page.evaluate("() => location.protocol") == "https:"
            assert page.evaluate("() => window.isSecureContext") is (
                False if secure_context_mode == "false" else None
            )
            assert page.evaluate("() => window.crypto.subtle") is None
            expect(page.get_by_text("验证通过")).to_be_visible(timeout=20000)
            assert page.evaluate("() => window.__rxyWorkerAttempts") == 0

            _fill_auth_form(page, "/login")
            submit = page.locator('form button[type="submit"]')
            expect(submit).to_be_enabled(timeout=15000)
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/api/v1/auth/login"),
                timeout=10000,
            ):
                submit.click()

            assert len(submissions) == 1
            assert submissions[0]["captcha_valid"] is True
            assert submissions[0]["path"] == "/api/v1/auth/login"
            assert len(challenges) >= 1
            assert page_errors == []
        finally:
            context.close()
            browser.close()


def test_non_loopback_http_auth_entry_shows_no_form_and_sends_no_api_request(
    web_origin: str,
) -> None:
    api_requests: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            _map_virtual_origin(page, "http://auth-test.invalid", web_origin)
            _stub_api(page)
            page.on(
                "request",
                lambda request: api_requests.append(request.url)
                if "/api/v1/" in request.url
                else None,
            )
            page.goto("http://auth-test.invalid/login", wait_until="domcontentloaded")
            expect(page.get_by_role("alert")).to_contain_text("连接不安全")
            expect(page.locator('input[name="email"]')).to_have_count(0)
            expect(page.locator("form")).to_have_count(0)
            assert api_requests == []
        finally:
            context.close()
            browser.close()


def test_allowlisted_public_http_entry_upgrades_route_query_and_fragment(
    web_origin: str,
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(
            playwright.chromium, ignore_https_errors=True
        )
        try:
            _map_virtual_origin(page, "http://rxycode.xyz", web_origin)
            _map_virtual_origin(page, "https://rxycode.xyz", web_origin)
            _stub_api(page)
            page.goto(
                "http://rxycode.xyz/login?next=%2Fapp#mobile-entry",
                wait_until="domcontentloaded",
            )
            page.wait_for_url("https://rxycode.xyz/login?next=%2Fapp#mobile-entry")
            assert page.evaluate("() => location.href") == (
                "https://rxycode.xyz/login?next=%2Fapp#mobile-entry"
            )
            assert page.locator('input[name="email"]').count() == 1
        finally:
            context.close()
            browser.close()


def test_production_caddyfile_redirects_only_trusted_public_http_in_explicit_order() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(
        r"@public_http\s*\{\s*host\s+rxycode\.xyz\s+www\.rxycode\.xyz\s+"
        r"header\s+X-Forwarded-Proto\s+http\s*\}",
        text,
    )
    assert re.search(
        r"@public_https\s*\{\s*host\s+rxycode\.xyz\s+www\.rxycode\.xyz\s+"
        r"header\s+X-Forwarded-Proto\s+https\s*\}",
        text,
    )
    assert "route {" in text
    assert "redir @public_http https://{host}{uri} 308" in text
    assert 'header @public_https Strict-Transport-Security "max-age=86400"' in text
    assert "includeSubDomains" not in text and "preload" not in text
    assert "header_up X-Forwarded-Proto {http.request.header.X-Forwarded-Proto}" in text
    assert "header_up X-Forwarded-Proto https" not in text
    assert "@api path /api/*" in text and "flush_interval -1" in text
    assert text.index("redir @public_http") < text.index("@preview_denied")
    assert text.index("@preview_denied") < text.index("@api path /api/*")

    caddy = shutil.which("caddy")
    if caddy:
        subprocess.run(
            [caddy, "adapt", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )


@pytest.mark.parametrize(
    "capability_mode",
    [
        "mobile-normal",
        "mobile-secure-context-false-worker-subtle-disabled",
        "desktop-official-worker",
    ],
    ids=["mobile-normal", "mobile-https-false-no-worker-no-subtle", "desktop-official-worker"],
)
def test_live_auth_is_anonymous_and_raw_http_returns_308_without_following(
    capability_mode: str,
) -> None:
    """Opt-in production smoke; no stored profile and no authentication POST."""
    live_origin = os.environ.get("RXYCODE_LIVE_AUTH_ORIGIN", "").strip()
    if not live_origin:
        pytest.skip("set RXYCODE_LIVE_AUTH_ORIGIN=https://rxycode.xyz to run live smoke")
    chromium_executable = os.environ.get("RXYCODE_LIVE_AUTH_CHROMIUM", "").strip()
    evidence_dir_value = os.environ.get("RXYCODE_LIVE_AUTH_EVIDENCE_DIR", "").strip()
    evidence_dir = (
        Path(evidence_dir_value).expanduser()
        if evidence_dir_value
        else REPO / "qa-artifacts" / "live-auth-smoke"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(live_origin)
    host = (parsed.hostname or "").lower()
    assert parsed.scheme == "https" and host in {"rxycode.xyz", "www.rxycode.xyz"}
    assert parsed.username is None and parsed.password is None
    assert parsed.port in {None, 443}
    assert parsed.path in {"", "/"} and not parsed.params and not parsed.query and not parsed.fragment

    probe_path = f"/login?codex_http_probe={time.time_ns()}"
    connection = http.client.HTTPConnection(host, 80, timeout=12)
    try:
        connection.request("GET", probe_path, headers={"Host": host, "Cache-Control": "no-cache"})
        raw_response = connection.getresponse()
        raw_status = raw_response.status
        location = raw_response.getheader("Location")
        raw_response.read()
    finally:
        connection.close()
    assert raw_status == 308, f"raw HTTP (no browser or redirect-following client) returned {raw_status}"
    assert location == f"https://{host}{probe_path}"

    auth_posts: list[str] = []
    challenge_gets: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if chromium_executable:
            executable_path = Path(chromium_executable).expanduser()
            assert executable_path.is_file(), (
                "RXYCODE_LIVE_AUTH_CHROMIUM must name an existing Chromium executable"
            )
            launch_options["executable_path"] = str(executable_path.resolve())
        browser = playwright.chromium.launch(**launch_options)
        # Intentionally do not pass storage_state, a persistent profile, or cookies.
        desktop_official = capability_mode == "desktop-official-worker"
        context = browser.new_context(
            viewport=(
                {"width": 1440, "height": 900}
                if desktop_official
                else {"width": 390, "height": 844}
            ),
            is_mobile=not desktop_official,
            has_touch=not desktop_official,
        )
        try:
            assert context.cookies() == []
            # Guard even against a regression that tries to submit: observe the attempt,
            # then abort it before it can reach the live auth service.
            context.route(
                "**/api/v1/auth/**",
                lambda route: route.abort()
                if route.request.method == "POST"
                else route.continue_(),
            )
            page = context.new_page()
            if capability_mode == "mobile-secure-context-false-worker-subtle-disabled":
                page.add_init_script(
                    """(() => {
                      Object.defineProperty(window, 'isSecureContext', {
                        configurable: true, value: false,
                      });
                      Object.defineProperty(window.crypto, 'subtle', {
                        configurable: true, value: undefined,
                      });
                      window.__rxyWorkerAttempts = 0;
                      Object.defineProperty(window, 'Worker', {
                        configurable: true,
                        value: function WorkerDisabled() {
                          window.__rxyWorkerAttempts += 1;
                          throw new DOMException('Worker disabled for live smoke', 'SecurityError');
                        },
                      });
                    })();"""
                )
            elif desktop_official:
                page.add_init_script(
                    """(() => {
                      const NativeWorker = window.Worker;
                      window.__rxyLiveWorkerConstructed = 0;
                      window.Worker = new Proxy(NativeWorker, {
                        construct(target, args) {
                          window.__rxyLiveWorkerConstructed += 1;
                          return Reflect.construct(target, args, target);
                        },
                      });
                    })();"""
                )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    auth_posts.append(request.url)
                    if request.method == "POST" and "/api/v1/auth/" in request.url
                    else challenge_gets.append(request.url)
                    if request.method == "GET" and request.url.endswith("/api/v1/auth/altcha")
                    else None
                ),
            )
            response = page.goto(f"{live_origin.rstrip('/')}/login", wait_until="domcontentloaded")
            assert response is not None and response.status == 200
            assert page.evaluate("() => location.protocol") == "https:"
            if capability_mode == "mobile-normal":
                assert page.evaluate("() => window.isSecureContext") is True
            elif capability_mode == "mobile-secure-context-false-worker-subtle-disabled":
                assert page.evaluate("() => window.isSecureContext") is False
                assert page.evaluate("() => window.crypto.subtle") is None
                assert page.evaluate("() => window.__rxyWorkerAttempts") == 0
            else:
                assert page.evaluate("() => window.isSecureContext") is True
                widget = page.locator("altcha-widget")
                expect(widget).to_be_visible(timeout=15000)
                page.wait_for_function(
                    """() => {
                      const widget = document.querySelector('altcha-widget');
                      return widget && typeof widget.getState === 'function'
                        && widget.getState() === 'verified';
                    }""",
                    timeout=30000,
                )
                assert page.locator("altcha-widget").count() == 1
                assert page.evaluate("() => window.__rxyLiveWorkerConstructed") >= 1
                assert page.get_by_text("正在进行兼容验证…").count() == 0
            if not desktop_official:
                expect(page.get_by_text("验证通过")).to_be_visible(timeout=30000)
            assert "max-age=" in response.headers.get("strict-transport-security", "")
            assert challenge_gets
            assert auth_posts == []
            assert page_errors == []
            browser_version = re.sub(r"[^A-Za-z0-9._-]+", "_", browser.version)
            screenshot_path = evidence_dir.resolve() / (
                f"live-anon-login-{capability_mode}-{browser_version}-{time.time_ns()}.png"
            )
            page.screenshot(path=str(screenshot_path), full_page=True)
            assert screenshot_path.is_file() and screenshot_path.stat().st_size > 0
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("auth_path", ["/login", "/register", "/forgot"])
def test_auth_forms_wait_for_capabilities_before_submitting(
    web_origin: str, auth_path: str
) -> None:
    submissions: list[dict[str, object]] = []
    auth_requests: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            _stub_api(page, submissions)
            page.add_init_script(
                """(() => {
                  const originalFetch = window.fetch.bind(window);
                  let releaseCapabilities;
                  let released = false;
                  window.__rxyCapabilitiesHeld = 0;
                  const capabilitiesGate = new Promise((resolve) => {
                    releaseCapabilities = resolve;
                  });
                  window.__rxyReleaseCapabilities = () => {
                    released = true;
                    releaseCapabilities();
                  };
                  window.fetch = (input, init) => {
                    const requestUrl = input instanceof Request ? input.url : String(input);
                    const path = new URL(requestUrl, location.href).pathname;
                    if (path === '/api/v1/auth/capabilities' && !released) {
                      window.__rxyCapabilitiesHeld += 1;
                      return capabilitiesGate.then(() => originalFetch(input, init));
                    }
                    return originalFetch(input, init);
                  };
                })()"""
            )
            page.on(
                "request",
                lambda request: auth_requests.append(request.url)
                if request.method == "POST" and "/api/v1/auth/" in request.url
                else None,
            )
            page.goto(f"{web_origin}{auth_path}", wait_until="domcontentloaded")
            expect(page.get_by_role("status")).to_contain_text(
                "正在确认验证码配置", timeout=10000
            )
            page.wait_for_function("() => window.__rxyCapabilitiesHeld >= 1")
            _fill_auth_form(page, auth_path)
            invite = page.locator('input[name="invite-code"]')
            if invite.count():
                invite.fill("browser-test-invite")

            submit = page.locator('form button[type="submit"]').first
            expect(submit).to_be_disabled()
            page.locator("form").first.evaluate(
                "(form) => form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}))"
            )
            expect(page.get_by_role("alert")).to_contain_text(
                "正在确认验证码配置", timeout=5000
            )
            assert auth_requests == []

            page.evaluate("() => window.__rxyReleaseCapabilities()")
            expect(submit).to_be_enabled(timeout=15000)
            assert auth_requests == []

            endpoint = f"/api/v1/auth/{auth_path.removeprefix('/')}"
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith(endpoint),
                timeout=10000,
            ):
                submit.click()
            assert len(submissions) == 1
            assert submissions[0]["path"] == endpoint
            assert submissions[0]["captcha_valid"] is True
        finally:
            context.close()
            browser.close()


def test_chromium_unmount_aborts_compat_solve_without_submitting_auth(
    web_origin: str,
) -> None:
    submissions: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            challenges = _stub_api(page, submissions, counter=99999)
            _install_worker_failure(page, "worker-disabled")
            page.add_init_script(
                """(() => {
                  window.__rxyAltchaAbortCount = 0;
                  const originalFetch = window.fetch.bind(window);
                  window.fetch = (input, init) => {
                    const requestUrl = input instanceof Request ? input.url : String(input);
                    const signal = init?.signal ?? (input instanceof Request ? input.signal : null);
                    if (new URL(requestUrl, location.href).pathname === '/api/v1/auth/altcha' && signal) {
                      signal.addEventListener('abort', () => {
                        window.__rxyAltchaAbortCount += 1;
                      }, { once: true });
                    }
                    return originalFetch(input, init);
                  };
                })()"""
            )
            page.goto(f"{web_origin}/login", wait_until="domcontentloaded")
            expect(page.get_by_text("正在进行兼容验证…")).to_be_visible(timeout=10000)
            expect(page.locator('form button[type="submit"]')).to_be_disabled()
            page.locator('a[href="/app"]').click()
            page.wait_for_url("**/app")
            page.wait_for_function("() => window.__rxyAltchaAbortCount >= 1")
            expect(page.locator("altcha-widget")).to_have_count(0)
            assert len(challenges) >= 2
            assert page.evaluate("() => window.__rxyAltchaAbortCount") >= 1
            assert submissions == []
        finally:
            context.close()
            browser.close()


def _new_mobile_page(
    browser_type,
    *,
    color_scheme: str = "light",
    executable_path: str | None = None,
    ignore_https_errors: bool = False,
):
    try:
        browser = browser_type.launch(headless=True, executable_path=executable_path)
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip(f"{browser_type.name} browser binary is not installed")
        raise
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        color_scheme=color_scheme,
        ignore_https_errors=ignore_https_errors,
    )
    return browser, context, context.new_page()


def _new_desktop_page(browser_type, *, color_scheme: str = "light"):
    try:
        browser = browser_type.launch(headless=True)
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip(f"{browser_type.name} browser binary is not installed")
        raise
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        is_mobile=False,
        has_touch=False,
        color_scheme=color_scheme,
    )
    return browser, context, context.new_page()


def _wait_for_altcha_configuration(page) -> None:
    page.wait_for_function(
        "() => { const config = document.querySelector('altcha-widget')?.getConfiguration?.(); "
        "return config?.challenge === '/api/v1/auth/altcha' "
        "&& config?.hideFooter === true && config?.hideLogo === true; }",
        timeout=10000,
    )


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_altcha_v3_widget_solves_and_submits_server_v1_challenge(
    web_origin: str, engine_name: str
) -> None:
    submissions: list[dict[str, object]] = []
    page_errors: list[str] = []
    browser_messages: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_desktop_page(getattr(playwright, engine_name))
        try:
            challenges = _stub_api(page, submissions)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("console", lambda message: browser_messages.append(message.text))
            page.add_init_script(
                """(() => {
                  window.__rxyAltchaEvents = [];
                  const observed = new WeakSet();
                  const attach = () => document.querySelectorAll('altcha-widget').forEach((el) => {
                    if (observed.has(el)) return;
                    observed.add(el);
                    el.addEventListener('statechange', (event) => {
                      const detail = event.detail || {};
                      window.__rxyAltchaEvents.push({
                        state: detail.state,
                            hasPayload: typeof detail.payload === 'string' && detail.payload.length > 0,
                            error: detail.error || null,
                      });
                    });
                  });
                  new MutationObserver(attach).observe(document, { childList: true, subtree: true });
                  document.addEventListener('DOMContentLoaded', attach, { once: true });
                })()"""
            )
            page.goto(f"{web_origin}/login", wait_until="domcontentloaded")
            widget = page.locator("altcha-widget")
            try:
                expect(widget).to_have_count(1, timeout=10000)
            except AssertionError as exc:
                raise AssertionError(
                    f"ALTCHA widget did not render at {page.url}; "
                    f"page errors={page_errors}; body={page.locator('body').inner_text()}"
                ) from exc
            _wait_for_altcha_configuration(page)
            submit = page.locator('form button[type="submit"]')
            page.locator('input[name="email"]').fill("browser-test@example.invalid")
            page.locator('input[name="password"]').fill("not-a-real-account-password")
            try:
                expect(submit).to_be_enabled(timeout=8000)
            except AssertionError as exc:
                raise AssertionError(
                    f"state={widget.evaluate('(el) => el.getState?.()')}; "
                    f"events={page.evaluate('() => window.__rxyAltchaEvents')}; "
                    f"challenges={challenges}; page_errors={page_errors}; "
                    f"browser_messages={browser_messages}"
                ) from exc

            # An expiry transition must clear the parent form's one-use token.
            widget.evaluate("(el) => el.setState('expired')")
            expect(submit).to_be_disabled(timeout=5000)
            widget.evaluate("(el) => el.reset()")
            widget.evaluate("async (el) => { await el.verify(); }", timeout=30000)
            expect(submit).to_be_enabled(timeout=30000)

            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/api/v1/auth/login")
                ),
                timeout=10000,
            ):
                submit.click()

            assert len(submissions) == 1
            assert submissions[0]["captcha_valid"] is True
            states = page.evaluate("() => window.__rxyAltchaEvents.map((event) => event.state)")
            assert "verifying" in states
            assert "verified" in states
            assert "expired" in states
            assert len(challenges) >= 2
            assert page_errors == []
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
@pytest.mark.parametrize("auth_path", ["/register", "/forgot"])
def test_altcha_registration_and_recovery_forms_gate_on_fresh_payload(
    web_origin: str, engine_name: str, auth_path: str
) -> None:
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(getattr(playwright, engine_name))
        try:
            challenges = _stub_api(page)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{web_origin}{auth_path}", wait_until="domcontentloaded")
            widget = page.locator("altcha-widget")
            expect(widget).to_have_count(0)
            expect(page.get_by_text("验证通过")).to_be_visible(timeout=15000)

            page.locator('input[name="email"]').fill("browser-test@example.invalid")
            password = page.locator('input[name="password"]')
            if password.count():
                password.fill("not-a-real-account-password")

            submit = page.locator('form button[type="submit"]')
            expect(submit).to_be_enabled(timeout=10000)
            assert len(challenges) >= 1
            assert page_errors == []
        finally:
            context.close()
            browser.close()


def _theme_api(page, *, authed: bool = False) -> None:
    def handle(route) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/v1/me":
            if authed:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "user": {
                                "id": "browser-user",
                                "kind": "local",
                                "email": "browser-test@example.invalid",
                                "display_name": "Browser Test",
                                "github_id": None,
                            },
                            "organization": {"id": "browser-org", "tenant_id": "browser"},
                            "membership": {"role": "owner"},
                            "default_project_id": None,
                        }
                    ),
                )
            else:
                route.fulfill(status=401, content_type="application/json", body=_AUTH_401)
        elif path == "/api/v1/auth/capabilities":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"captcha": None, "registration": "open"}),
            )
        else:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"code": "UNAVAILABLE"}),
            )

    page.route("**/api/v1/**", handle)


def _assert_dark(page) -> None:
    page.wait_for_function(
        "() => document.documentElement.classList.contains('dark') "
        "&& getComputedStyle(document.documentElement).colorScheme === 'dark' "
        "&& getComputedStyle(document.body).backgroundColor === 'rgb(33, 33, 33)'",
        timeout=5000,
    )


def _assert_light(page) -> None:
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('dark') "
        "&& getComputedStyle(document.documentElement).colorScheme === 'light' "
        "&& getComputedStyle(document.body).backgroundColor === 'rgb(255, 255, 255)'",
        timeout=5000,
    )


def _navigate_guest_to_register(page) -> None:
    page.get_by_role("button", name="打开会话列表").click()
    account = page.get_by_role("button", name="账户：未登录")
    expect(account).to_be_visible(timeout=10000)
    account.click()
    page.get_by_role("menuitem", name="注册").click()
    page.wait_for_url("**/register**", timeout=10000)


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_theme_cookie_and_computed_styles_survive_mobile_spa_route_and_reload(
    web_origin: str, engine_name: str
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(getattr(playwright, engine_name))
        try:
            _theme_api(page)
            page.goto(f"{web_origin}/app", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="切换到深色")).to_be_visible()
            page.get_by_role("button", name="切换到深色").click()
            _assert_dark(page)
            assert "rxy_theme=dark" in page.evaluate("() => document.cookie")

            _navigate_guest_to_register(page)
            _assert_dark(page)
            page.reload(wait_until="domcontentloaded")
            _assert_dark(page)
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_theme_switch_survives_cookie_write_exception_but_is_not_persisted(
    web_origin: str, engine_name: str
) -> None:
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(getattr(playwright, engine_name))
        try:
            _theme_api(page)
            page.add_init_script(
                """(() => {
                  let owner = Document.prototype;
                  while (owner && !Object.getOwnPropertyDescriptor(owner, 'cookie')) {
                    owner = Object.getPrototypeOf(owner);
                  }
                  Object.defineProperty(owner, 'cookie', {
                    configurable: true,
                    get() { throw new DOMException('Cookie access blocked', 'SecurityError'); },
                    set() { throw new DOMException('Cookie access blocked', 'SecurityError'); },
                  });
                })()"""
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{web_origin}/app", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="切换到深色")).to_be_visible()
            page.get_by_role("button", name="切换到深色").click()
            _assert_dark(page)
            assert page_errors == []

            _navigate_guest_to_register(page)
            _assert_dark(page)
            page.reload(wait_until="domcontentloaded")
            _assert_light(page)
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_theme_topbar_and_settings_entry_points_follow_selected_theme(
    web_origin: str, engine_name: str
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(
            getattr(playwright, engine_name), color_scheme="dark"
        )
        try:
            _theme_api(page, authed=True)
            page.goto(f"{web_origin}/settings/appearance", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="设置", exact=True)).to_be_visible(
                timeout=10000
            )
            _assert_light(page)

            topbar_toggle = page.locator('header button[aria-label="切换到深色"]')
            topbar_toggle.click()
            _assert_dark(page)

            mode_group = page.get_by_role("radiogroup", name="主题模式")
            mode_group.get_by_role("radio", name="浅色").click()
            _assert_light(page)

            mode_group.get_by_role("radio", name="深色").click()
            _assert_dark(page)
            assert "rxy_theme=dark" in page.evaluate("() => document.cookie")
        finally:
            context.close()
            browser.close()


def test_production_css_uses_legacy_safe_syntax(production_web_origin: str) -> None:
    assert production_web_origin.startswith("http://127.0.0.1:")
    css_files = sorted((WEB / "dist" / "assets").glob("*.css"))
    assert css_files, "production build must emit an asset stylesheet"
    css = "\n".join(path.read_text(encoding="utf-8") for path in css_files)
    forbidden = [
        pattern
        for pattern in (r"@layer\b", r"@property\b", r"@nest\b", r"color-mix\s*\(", r"oklch\s*\(")
        if re.search(pattern, css, flags=re.IGNORECASE)
    ]
    assert forbidden == [], f"production CSS contains unsupported constructs: {forbidden}"

    node = shutil.which("node")
    assert node, "Node.js is required to parse the production CSS"
    parser_check = r"""
      const fs = require('node:fs');
      const postcss = require('postcss');
      const root = postcss.parse(fs.readFileSync(process.argv[1], 'utf8'));
      const nested = [];
      root.walkRules((rule) => {
        if (rule.parent.type === 'rule') nested.push(rule.selector);
      });
      if (nested.length) {
        console.error(`Nested CSS rules: ${nested.join(', ')}`);
        process.exit(1);
      }
    """
    for css_file in css_files:
        subprocess.run(
            [node, "-e", parser_check, str(css_file)],
            cwd=WEB,
            check=True,
            timeout=15,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def _assert_production_console_styles(page, origin: str) -> None:
    _theme_api(page)
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(f"{origin}/app", wait_until="domcontentloaded")
    root = page.locator("#root > div").first
    sidebar = page.locator('aside[aria-label="会话列表"]')
    menu = page.get_by_role("button", name="打开会话列表")
    theme = page.get_by_role("button", name="切换到深色")

    page.wait_for_function(
        "() => { const root = document.querySelector('#root > div'); "
        "const aside = document.querySelector('aside[aria-label=\"会话列表\"]'); "
        "return root && aside && getComputedStyle(root).display === 'flex' "
        "&& getComputedStyle(aside).position === 'fixed' "
        "&& aside.getBoundingClientRect().right <= 0; }",
        timeout=10000,
    )
    assert root.evaluate("el => getComputedStyle(el).display") == "flex"
    assert sidebar.evaluate("el => getComputedStyle(el).display") == "flex"
    assert sidebar.evaluate("el => el.getBoundingClientRect().right") <= 0
    assert menu.evaluate("el => getComputedStyle(el).display") != "none"
    expect(theme).to_be_visible()
    assert theme.evaluate("el => getComputedStyle(el).borderRadius") == "6px"
    assert theme.evaluate("el => getComputedStyle(el).padding") == "6px"

    menu.click()
    overlay = page.locator('button.fixed[aria-label="关闭会话列表"]')
    expect(overlay).to_be_visible()
    assert overlay.evaluate("el => getComputedStyle(el).backgroundColor") == (
        "rgba(0, 0, 0, 0.4)"
    )
    page.locator('aside button[aria-label="关闭会话列表"]').click()
    expect(overlay).to_have_count(0)

    theme.click()
    _assert_dark(page)
    composer = page.locator('textarea[aria-label="消息"]').locator("xpath=..")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('textarea[aria-label=\"消息\"]')"
        ".parentElement).backgroundColor === 'rgb(33, 33, 33)'",
        timeout=5000,
    )
    model_button = page.get_by_role("button", name=re.compile(r"^选择模型："))
    expect(model_button).to_be_visible()
    assert "选择模型" in model_button.inner_text()
    assert model_button.evaluate("el => getComputedStyle(el).color") == "rgb(163, 163, 163)"
    alpha_probe = page.evaluate(
        """() => {
          const el = document.createElement('div');
          el.id = 'rxy-alpha-regression-probe';
          el.className = 'bg-waiting/15';
          document.body.appendChild(el);
          return getComputedStyle(el).backgroundColor;
        }"""
    )
    assert alpha_probe == "rgba(251, 191, 36, 0.15)"
    page.evaluate(
        """() => {
          const el = document.createElement('div');
          el.id = 'rxy-hover-alpha-regression-probe';
          el.className = 'hover:bg-card/60';
          el.style.cssText = 'position:fixed;left:0;top:0;width:12px;height:12px;';
          document.body.appendChild(el);
        }"""
    )
    page.locator("#rxy-hover-alpha-regression-probe").hover()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('#rxy-hover-alpha-regression-probe'))"
        ".backgroundColor === 'rgba(33, 33, 33, 0.6)'",
        timeout=5000,
    )
    page.get_by_role("button", name="切换到浅色").click()
    _assert_light(page)
    page.wait_for_function(
        "() => { const composer = document.querySelector('textarea[aria-label=\"消息\"]')"
        ".parentElement; const model = document.querySelector('button[aria-label^=\"选择模型：\"]'); "
        "return getComputedStyle(composer).backgroundColor === 'rgb(255, 255, 255)' "
        "&& getComputedStyle(model).color === 'rgb(82, 82, 82)'; }",
        timeout=5000,
    )
    assert composer.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
    assert "选择模型" in model_button.inner_text()

    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_function(
        "() => { const aside = document.querySelector('aside[aria-label=\"会话列表\"]'); "
        "const menu = document.querySelector('button[aria-label=\"打开会话列表\"]'); "
        "return aside && getComputedStyle(aside).position === 'static' "
        "&& aside.getBoundingClientRect().left === 0 "
        "&& getComputedStyle(menu).display === 'none'; }",
        timeout=5000,
    )
    assert root.evaluate("el => getComputedStyle(el).display") == "flex"
    _assert_light(page)
    assert page_errors == []


def test_production_app_layout_styles_on_current_chromium(
    production_web_origin: str,
) -> None:
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(playwright.chromium)
        try:
            _assert_production_console_styles(page, production_web_origin)
        finally:
            context.close()
            browser.close()


def test_real_legacy_chromium_98_production_app_layout(
    production_web_origin: str,
) -> None:
    executable = os.environ.get("RXYCODE_LEGACY_CHROMIUM")
    if not executable:
        pytest.skip("set RXYCODE_LEGACY_CHROMIUM to a real Chromium 98 executable")
    if not Path(executable).is_file():
        pytest.fail(f"RXYCODE_LEGACY_CHROMIUM does not exist: {executable}")

    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(
            playwright.chromium, executable_path=executable
        )
        try:
            assert browser.version.split(".", 1)[0] == "98", (
                "legacy regression requires the actual Chromium 98 binary; "
                f"reported browser.version={browser.version!r}"
            )
            assert "98." in page.evaluate("() => navigator.userAgent")
            _assert_production_console_styles(page, production_web_origin)
        finally:
            context.close()
            browser.close()


def test_production_task_send_uses_secure_uuid_fallback_and_reuses_id_on_retry(
    production_web_origin: str,
) -> None:
    actual_legacy_executable = os.environ.get("RXYCODE_UUID_FALLBACK_CHROMIUM")
    with sync_playwright() as playwright:
        browser, context, page = _new_mobile_page(
            playwright.chromium, executable_path=actual_legacy_executable
        )
        try:
            if actual_legacy_executable:
                assert browser.version.split(".", 1)[0] == "90", (
                    "RXYCODE_UUID_FALLBACK_CHROMIUM must be a real Chromium 90 binary; "
                    f"reported browser.version={browser.version!r}"
                )
            else:
                # Exercise the compatibility branch on the default modern browser too.
                page.add_init_script(
                    "Object.defineProperty(window.crypto, 'randomUUID', "
                    "{ configurable: true, value: undefined });"
                )

            submissions: list[dict[str, object]] = []
            paths: list[str] = []
            page_errors: list[str] = []

            def handle_api(route) -> None:
                request = route.request
                path = urlparse(request.url).path
                paths.append(path)
                if path == "/api/v1/me":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "user": {
                                    "id": "browser-user",
                                    "kind": "local",
                                    "email": "browser-test@example.invalid",
                                    "display_name": "Browser Test",
                                    "github_id": None,
                                },
                                "organization": {"id": "browser-org", "tenant_id": "browser"},
                                "membership": {"role": "owner"},
                                "default_project_id": None,
                            }
                        ),
                    )
                elif path == "/api/v1/auth/csrf":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"csrf_token": "browser-test-csrf"}),
                    )
                elif path == "/api/v1/auth/capabilities":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {"captcha": None, "registration": "open", "code_delivery": "none"}
                        ),
                    )
                elif path == "/api/v1/models":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"models": [], "default_model_ref": None}),
                    )
                elif path == "/api/v1/sessions":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"sessions": []}),
                    )
                elif path == "/api/v1/tasks" and request.method == "POST":
                    submissions.append(json.loads(request.post_data or "{}"))
                    if len(submissions) == 1:
                        route.abort("failed")
                    else:
                        route.fulfill(
                            status=403,
                            content_type="application/json",
                            body=json.dumps({"code": "BYOK_REQUIRED"}),
                        )
                else:
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body=json.dumps({"code": "UNAVAILABLE"}),
                    )

            page.route("**/api/v1/**", handle_api)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{production_web_origin}/app", wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelector('textarea[aria-label=\"消息\"]')")
            page.locator('textarea[aria-label="消息"]').fill("safe UUID fallback regression")

            with page.expect_request(
                lambda request: request.method == "POST" and request.url.endswith("/api/v1/tasks"),
                timeout=10000,
            ):
                page.get_by_role("button", name="发送").click()
            expect(page.get_by_role("alert").filter(has_text="无法连接服务器")).to_be_visible(
                timeout=10000
            )
            assert len(submissions) == 1

            request_id = submissions[0].get("request_id")
            assert isinstance(request_id, str)
            assert re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                request_id,
            ), f"request_id is not a UUIDv4: {request_id!r}"

            with page.expect_request(
                lambda request: request.method == "POST" and request.url.endswith("/api/v1/tasks"),
                timeout=10000,
            ):
                page.get_by_role("button", name="发送").click()
            expect(page.get_by_role("alert").filter(has_text="请先配置自己的 API Key")).to_be_visible(
                timeout=10000
            )
            assert len(submissions) == 2
            assert submissions[1].get("request_id") == request_id
            assert page.url.endswith("/app")
            assert paths.count("/api/v1/tasks") == 2
            assert not any("/runs" in path or "/stream" in path for path in paths)
            assert page_errors == []
        finally:
            context.close()
            browser.close()
